import numpy as np
import pytest
from scipy.stats import norm

from geoqc.synth.trs import two_layer_times
from geoqc.trs.branches import fit_branches, horizontal_two_layer_parameters, layered_first_times, robust_line
from geoqc.trs.contracts import ReciprocalObservation
from geoqc.trs.coverage import survey_plan
from geoqc.trs.inversion import invert_two_layer, normalized_misfit
from geoqc.trs.reciprocity import reciprocal_pair
from tests.synthetic.e4_support import record, wilson


def observation(source, receiver, time=0.04, sigma=0.0001, **fields):
    return ReciprocalObservation(
        source_id=source,
        receiver_id=receiver,
        time_s=time,
        sigma_s=sigma,
        error_model_ref="registered known error",
        **fields,
    )


@pytest.mark.vid("V-E4-5")
@pytest.mark.parametrize("rho", [0, 0.6])
def test_reciprocity_distribution_and_shared_errors(rho, record_property):
    rng = np.random.default_rng(4500 + round(100 * rho))
    sigmas = np.array([0.0003, 0.0004])
    covariance = np.outer(sigmas, sigmas) * np.array([[1, rho], [rho, 1]])
    errors = rng.multivariate_normal([0, 0], covariance, 10000)
    zvalues = []
    for pair in errors[::100]:
        result = reciprocal_pair(
            observation("A", "B", 0.04 + pair[0], sigmas[0]),
            observation("B", "A", 0.04 + pair[1], sigmas[1]),
            covariance_s2=covariance[0, 1],
            tolerance_s=0.001,
            detectable_effect_s=0.002,
        )
        zvalues.append(result["z"])
        assert result["sigma_delta_s"] == pytest.approx(np.sqrt(sigmas @ sigmas - 2 * covariance[0, 1]))
    standardized = (errors[:, 0] - errors[:, 1]) / np.sqrt(sigmas @ sigmas - 2 * covariance[0, 1])
    assert abs(standardized.mean()) < 0.03
    assert 0.97 < standardized.std(ddof=1) < 1.03
    coverage = np.mean(abs(standardized) <= norm.ppf(0.975))
    assert abs(coverage - 0.95) < 0.01
    record(
        record_property,
        "reciprocity_errors",
        {
            "rho": rho,
            "n": 10000,
            "z_mean": float(standardized.mean()),
            "z_std": float(standardized.std(ddof=1)),
            "coverage95": float(coverage),
            "coverage_wilson95": wilson(round(coverage * 10000), 10000),
        },
    )
    deterministic = reciprocal_pair(
        observation("A", "B", sigma=0), observation("B", "A", sigma=0), tolerance_s=0.001, detectable_effect_s=0.002
    )
    assert deterministic["delta_s"] == 0 and deterministic["z"] is None
    assert deterministic["statistical_discrepancy"] is False


@pytest.mark.vid("V-E4-6")
def test_reciprocity_tolerance_is_not_inflated_and_power(record_property):
    effect = 0.5 / 1500
    result = reciprocal_pair(
        observation("A", "B", time=0.04 + effect), observation("B", "A"), tolerance_s=0.001, detectable_effect_s=0.002
    )
    assert result["delta_s"] == pytest.approx(0.0003333333333333)
    assert result["operational_within_tolerance"] is True
    weak = reciprocal_pair(
        observation("A", "B", sigma=0.003),
        observation("B", "A", sigma=0.003),
        tolerance_s=0.001,
        detectable_effect_s=0.002,
    )
    assert weak["evidence_status"] == "INCOMPLETE" and weak["power"] < 0.8
    rng = np.random.default_rng(4600)
    rates = []
    for magnitude in (effect, 0.002):
        sigma = 0.0005
        errors = rng.normal(magnitude, sigma, 10000)
        detected = np.count_nonzero(abs(errors / sigma) > norm.ppf(0.975))
        expected = norm.cdf(-norm.ppf(0.975) - magnitude / sigma) + norm.sf(norm.ppf(0.975) - magnitude / sigma)
        assert abs(detected / 10000 - expected) < 0.015
        rates.append(
            {
                "effect_s": magnitude,
                "n": 10000,
                "power": float(expected),
                "observed": detected / 10000,
                "wilson95": wilson(detected, 10000),
            }
        )
    record(record_property, "detection_power", rates)


@pytest.mark.vid("V-E4-7")
def test_source_delay_pattern_and_nonunique_cause():
    for receiver in ("B", "C", "D"):
        result = reciprocal_pair(
            observation("A", receiver, time=0.042),
            observation(receiver, "A", time=0.04),
            tolerance_s=0.001,
            detectable_effect_s=0.002,
        )
        assert result["delta_s"] == pytest.approx(0.002)
        assert result["delta_orientation"] == "A_TO_B_MINUS_B_TO_A"
        assert result["operational_within_tolerance"] is False
        assert "SOURCE_DELAY" in result["cause_candidates"] and "GEOMETRY" in result["cause_candidates"]
        corrected = reciprocal_pair(
            observation("A", receiver, time=0.042, source_delay_s=0.002),
            observation(receiver, "A", time=0.04),
            tolerance_s=0.001,
            detectable_effect_s=0.002,
        )
        assert abs(corrected["delta_s"]) < 1e-15


@pytest.mark.vid("V-E4-8")
def test_visible_two_layer_recovery_and_absent_branch(record_property):
    x = np.linspace(1, 120, 120)
    truth = np.array(two_layer_times(x, 300, 1500, 5).first_s)
    y = truth + np.random.default_rng(4800).normal(0, 0.00002, x.size)
    fit = fit_branches(x, y, sigma_s=np.full(x.size, 0.00002), max_segments=2)
    result = horizontal_two_layer_parameters(fit, model_verified=True)
    assert result["state"] == "VALID"
    assert abs(result["v1_ms"] / 300 - 1) <= 0.02 and abs(result["v2_ms"] / 1500 - 1) <= 0.02
    assert abs(result["intercept_s"] - two_layer_times(x, 300, 1500, 5).intercept_time_s) <= 0.001
    assert abs(result["thickness_m"] / 5 - 1) <= 0.05
    record(record_property, "two_layer_recovery", result)
    near = fit_branches(x[:10], truth[:10], max_segments=2)
    assert horizontal_two_layer_parameters(near, model_verified=True)["state"] == "MODEL_INAPPLICABLE"
    assert horizontal_two_layer_parameters(fit, model_verified=False)["state"] == "MODEL_INAPPLICABLE"


@pytest.mark.vid("V-E4-9")
@pytest.mark.parametrize(
    "velocities,thicknesses,expected",
    [((300,), (), 1), ((300, 1500), (5,), 2), ((300, 600, 1500), (5, 8), 3), ((300, 600, 1500), (5, 0.5), 2)],
)
def test_bic_visible_branches_and_parameter_count(velocities, thicknesses, expected, record_property):
    x = np.linspace(0.5, 120, 160)
    y = layered_first_times(x, velocities, thicknesses)
    fit = fit_branches(x, y, max_segments=3)
    assert fit["selected"]["segments"] == expected
    for candidate in fit["candidates"]:
        assert candidate["parameters"] == 2 * candidate["segments"] + 1
        assert candidate["bic"] == pytest.approx(candidate["neg2loglik"] + candidate["parameters"] * np.log(x.size))
    record(record_property, "visible_branches", {"velocities": velocities, "h": thicknesses, "fit": fit})
    assert fit_branches(x, y, gaussian_error_model=False)["state"] == "MODEL_INAPPLICABLE"
    assert fit_branches(x, y, continuity="DISCONTINUOUS")["state"] == "MODEL_INAPPLICABLE"


@pytest.mark.vid("V-E4-10")
def test_hidden_layer_exact_equivalence(record_property):
    x = np.linspace(0, 120, 1201)
    v1, vmid, v2, h1, hmid = 300, 600, 1500, 5, 0.5
    ti = 2 * h1 / v1 * np.sqrt(1 - (v1 / v2) ** 2) + 2 * hmid / vmid * np.sqrt(1 - (vmid / v2) ** 2)
    heq = ti * v1 / (2 * np.sqrt(1 - (v1 / v2) ** 2))
    first3 = layered_first_times(x, (v1, vmid, v2), (h1, hmid))
    first2 = np.array(two_layer_times(x, v1, v2, heq).first_s)
    np.testing.assert_allclose(first3, first2, atol=1e-15, rtol=1e-14)
    assert heq == pytest.approx(5.233853586, rel=1e-8)
    record(
        record_property,
        "hidden_equivalence",
        {
            "equivalent_h_m": float(heq),
            "max_time_difference_s": float(max(abs(first3 - first2))),
            "identifiability": "NOT_IDENTIFIABLE_FROM_FIRST_ARRIVALS",
            "required_complement": "independent geology, other waves or constraints",
        },
    )


@pytest.mark.vid("V-E4-11")
def test_robust_outlier_recall_and_slope(record_property):
    rng = np.random.default_rng(41100)
    x = np.linspace(5, 100, 100)
    tp, positives, fp, negatives, errors = 0, 0, 0, 0, []
    for _ in range(100):
        truth = np.zeros(100, dtype=bool)
        truth[rng.choice(100, 10, replace=False)] = True
        y = 0.015 + x / 1500 + rng.normal(0, 0.00005, 100)
        y[truth] += rng.choice([-1, 1], 10) * rng.uniform(0.020, 0.040, 10)
        result = robust_line(x, y, sigma_s=0.00005)
        identified = np.array(result["outlier_mask_sorted_offsets"])
        tp += np.count_nonzero(identified & truth)
        fp += np.count_nonzero(identified & ~truth)
        positives += 10
        negatives += 90
        errors.append(result["slope_s_per_m"] * 1500 - 1)
    assert tp / positives >= 0.95 and abs(np.mean(errors)) <= 0.01
    record(
        record_property,
        "outlier_experiment",
        {
            "n": 100,
            "positives": positives,
            "recall": tp / positives,
            "recall_wilson95": wilson(tp, positives),
            "negatives": negatives,
            "fpr": fp / negatives,
            "fpr_wilson95": wilson(fp, negatives),
            "slope_bias_relative": float(np.mean(errors)),
        },
    )


@pytest.mark.vid("V-E4-12")
def test_crossover_heuristic_and_seven_physical_shots():
    times = two_layer_times(np.array([46, 72]), 300, 1500, 15)
    assert times.crossover_distance_m == pytest.approx(36.7423461417)
    receivers = np.linspace(0, 46, 24)
    sources = np.r_[-10, np.linspace(0, 46, 5), 56]
    plan = survey_plan(receivers, sources, crossover_m=times.crossover_distance_m)
    assert plan["physical_shot_count"] == 7
    assert plan["required_offset_heuristic_m"] == pytest.approx(55.1135192126)
    assert plan["eligible_for_acceptance"] is False
    assert plan["shots"][0]["branch_points_nominal"] > 0


@pytest.mark.vid("V-E4-14")
def test_inversion_known_roi_and_noise(record_property):
    rng = np.random.default_rng(41400)
    x = np.linspace(1, 120, 120)
    truth = np.array(two_layer_times(x, 300, 1500, 5).first_s)
    qvalues, errors, not_converged = [], [], 0
    for _ in range(100):
        y = truth + rng.normal(0, 0.0005, 120)
        result = invert_two_layer(
            x,
            y,
            sigma_s=np.full(120, 0.0005),
            initial_v1_v2_h=(315, 1400, 5.3),
            max_evaluations=80,
            horizontal_model_verified=True,
            roi_ref="horizontal 0..10m",
        )
        not_converged += not result["converged"]
        qvalues.append(result["misfit"]["Q"])
        errors.append(np.array(result["velocities_ms"]) / [300, 1500] - 1)
    assert not_converged == 0 and 0.7 <= np.mean(qvalues) <= 1.5
    assert np.percentile(abs(np.array(errors)), 95) <= 0.10
    record(
        record_property,
        "inversion_ensemble",
        {
            "n": 100,
            "q_mean": float(np.mean(qvalues)),
            "q_range": [min(qvalues), max(qvalues)],
            "velocity_p95_relative_error": float(np.percentile(abs(np.array(errors)), 95)),
            "not_converged": not_converged,
            "resolution": "LOCAL_PARAMETRIC_ONLY, DOES_NOT_PROVE_UNIQUENESS",
        },
    )
    fast = invert_two_layer(
        x,
        truth,
        sigma_s=np.full(120, 0.0005),
        initial_v1_v2_h=(500, 2500, 15),
        max_evaluations=3,
        horizontal_model_verified=True,
        roi_ref="known",
    )
    assert fast["state"] in ("NOT_CONVERGED", "MODEL_INAPPLICABLE")
    assert fast["eligible_for_acceptance"] is False
    unseen = invert_two_layer(
        x[:12] / 10,
        truth[:12] / 10,
        sigma_s=np.full(12, 0.0005),
        initial_v1_v2_h=(300, 1500, 5),
        max_evaluations=80,
        horizontal_model_verified=True,
        roi_ref="unseen lower layer",
    )
    assert unseen["state"] == "MODEL_INAPPLICABLE" and unseen["thickness_m"] is None


@pytest.mark.vid("V-E4-15")
def test_corruption_detection_and_flexible_model_counterexample(record_property):
    rng = np.random.default_rng(41500)
    x = np.linspace(1, 120, 120)
    truth = np.array(two_layer_times(x, 300, 1500, 5).first_s)
    detected, increases = 0, []
    for _ in range(100):
        y = truth + rng.normal(0, 0.0005, 120)
        wrong = y.copy()
        positions = rng.choice(120, 6, replace=False)
        wrong[positions] += rng.choice([-1, 1], 6) * 0.005
        options = dict(
            sigma_s=np.full(120, 0.0005),
            initial_v1_v2_h=(300, 1500, 5),
            max_evaluations=80,
            horizontal_model_verified=True,
            roi_ref="known",
        )
        clean = invert_two_layer(x, y, **options)
        corrupt = invert_two_layer(x, wrong, **options)
        ratio = corrupt["misfit"]["Q"] / clean["misfit"]["Q"]
        increases.append(ratio)
        detected += ratio >= 1.5
    assert detected / 100 >= 0.95
    record(
        record_property,
        "corruption_power",
        {
            "n": 100,
            "corrupted_fraction": 0.05,
            "detection": detected / 100,
            "wilson95": wilson(detected, 100),
            "q_ratio_mean": float(np.mean(increases)),
            "protocol": "6 independent ±5ms outliers",
        },
    )
    # Un modelo flexible que interpola cada dato reduce Q a cero sin recuperar verdad.
    assert normalized_misfit(wrong, wrong, np.diag(np.full(120, 0.0005) ** 2))["Q"] == 0
