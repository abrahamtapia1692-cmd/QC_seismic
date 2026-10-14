import numpy as np
import pytest
from scipy.stats import linregress, norm

from geoqc.masw.statistics import empirical_max_threshold, iid_threshold, kluyver_cdf, uncertainty_from_errors
from tests.synthetic.e5_support import spectral_errors, wilson


@pytest.mark.vid("V-E5-11")
@pytest.mark.parametrize("snr_db", [10, 20])
def test_precision_holdout_bias_covariance_and_coverage(snr_db, record_property):
    train = spectral_errors(6500 + snr_db, 1000, snr_db)
    holdout = spectral_errors(7500 + snr_db, 1000, snr_db)
    calibrated = uncertainty_from_errors(np.full(3, 200.0), train)
    quantiles = np.quantile(train, [0.025, 0.975], axis=0)
    coverage = np.mean((holdout >= quantiles[0]) & (holdout <= quantiles[1]), axis=0)
    assert np.max(abs(coverage - 0.95)) <= 0.025
    assert calibrated["repeatability_cov"] is None
    assert np.array(calibrated["covariance_ms2"]).shape == (3, 3)
    intervals = calibrated["interval95_ms"]
    assert np.max(abs(np.mean(holdout, axis=0))) < 1
    record_property(
        "curve_precision_holdout",
        {
            "snr_db": snr_db,
            "train_n": 1000,
            "holdout_n": 1000,
            "train_seed": 6500 + snr_db,
            "holdout_seed": 7500 + snr_db,
            "frequencies_hz": [8, 16, 32],
            "coverage95": coverage.tolist(),
            "coverage95_wilson": [wilson(round(p * 1000), 1000) for p in coverage],
            "holdout_bias_ms": np.mean(holdout, axis=0).tolist(),
            "example_interval95_ms": intervals,
            "calibration": calibrated,
            "not_resolution_sigma": True,
        },
    )


@pytest.mark.vid("V-E5-12")
def test_precision_factor_experiment_with_regression_and_exceptions(record_property):
    rows = []
    for snr in (10, 20):
        for n in (12, 24):
            for dx in (1.0, 2.0):
                errors = spectral_errors(12000 + snr * 10 + n + int(dx), 300, snr, n=n, dx=dx, frequencies=(8, 16, 32))
                rows.append(
                    {
                        "snr_db": snr,
                        "n": n,
                        "effective_aperture_m": n * dx,
                        "relative_sigma": (np.std(errors, axis=0, ddof=1) / 200).tolist(),
                    }
                )
    logs = np.array([np.log(row["relative_sigma"][0]) for row in rows])
    apertures = np.log([row["effective_aperture_m"] for row in rows])
    regression = linregress(apertures, logs)
    assert regression.slope < 0
    for i in range(4):
        assert rows[i + 4]["relative_sigma"][0] < rows[i]["relative_sigma"][0]
    record_property(
        "precision_factors",
        {
            "study": rows,
            "log_sigma_vs_log_aperture_slope": float(regression.slope),
            "slope95_ci": [
                float(regression.slope - 1.96 * regression.stderr),
                float(regression.slope + 1.96 * regression.stderr),
            ],
            "exceptions": ["Changing modes, correlated noise or active support is a different domain"],
            "frequency_indices": [8, 16, 32],
            "sigma_units": "dimensionless sigma_c/c",
        },
    )


@pytest.mark.vid("V-E5-17")
def test_kluyver_against_two_million_mc_each_n_with_familywise_intervals(record_property):
    rows = []
    for n, expected in ((12, 0.744483), (24, 0.545573), (48, 0.392000)):
        rng = np.random.default_rng(800 + n)
        samples = []
        for _ in range(100):
            phase = rng.uniform(-np.pi, np.pi, (20000, n))
            samples.append(np.hypot(np.cos(phase).sum(axis=1), np.sin(phase).sum(axis=1)) / n)
        sample = np.concatenate(samples)
        threshold = iid_threshold(n, 0.0005)["threshold"]
        assert abs(threshold - expected) < 0.005 and abs(np.quantile(sample, 0.9995) - threshold) < 0.005
        for a in (0.3167508, threshold):
            cdf = kluyver_cdf(a, n)
            refined = kluyver_cdf(a, n, cutoff=200, order=64)
            quad_error = abs(cdf - refined)
            count = int(np.sum(sample > a))
            interval = wilson(count, sample.size, z=norm.ppf(1 - 0.05 / (2 * 6)))
            assert interval[0] - quad_error <= 1 - refined <= interval[1] + quad_error
            assert quad_error < 1e-6
            rows.append(
                {
                    "n": n,
                    "a": float(a),
                    "mc_count": count,
                    "mc_n": int(sample.size),
                    "familywise_binomial_ci": interval,
                    "kluyver_tail": 1 - refined,
                    "cutoff_order_change": quad_error,
                    "asymptotic_tail": float(np.exp(-n * a * a)),
                }
            )
    counter = rows[0]
    assert counter["kluyver_tail"] == pytest.approx(0.30636, abs=0.0001)
    assert counter["kluyver_tail"] > counter["asymptotic_tail"]
    record_property(
        "kluyver_mc",
        {
            "study": rows,
            "quantiles_expected": [0.744483, 0.545573, 0.392000],
            "asymptotic_is_global_bound": False,
            "mc_seed_rule": "800+N",
        },
    )


def colored_correlated_maxima(seed, count):
    rng = np.random.default_rng(seed)
    x, f, c = np.arange(24) * 2, np.array([8, 16, 32]), np.arange(100, 401, 5)
    common = rng.normal(size=(count, 1, 1)) + 1j * rng.normal(size=(count, 1, 1))
    independent = rng.normal(size=(count, 3, 24)) + 1j * rng.normal(size=(count, 3, 24))
    noise = (np.sqrt(0.6) * common + np.sqrt(0.4) * independent) / f[None, :, None]
    phasors = noise / abs(noise)
    maxima = np.zeros(count)
    for direction in (-1, 1):
        for i, frequency in enumerate(f):
            steering = np.exp(2j * np.pi * frequency * direction * x[None, :] / c[:, None])
            values = abs(phasors[:, i] @ steering.T) / 24
            maxima = np.maximum(maxima, values.max(axis=1))
    return maxima


@pytest.mark.vid("V-E5-17b")
def test_colored_correlated_complete_grid_maximum_holdout(record_property):
    train = colored_correlated_maxima(882, 2000)
    holdout = colored_correlated_maxima(883, 4000)
    threshold = empirical_max_threshold(train, 0.05)
    count = int(np.sum(holdout > threshold))
    interval = wilson(count, 4000)
    assert interval[0] <= 0.05 <= interval[1]
    record_property(
        "maximum_null_holdout",
        {
            "alpha": 0.05,
            "threshold": threshold,
            "train_n": 2000,
            "holdout_n": 4000,
            "false_records": count,
            "false_record_rate": count / 4000,
            "wilson95": interval,
            "train_seed": 882,
            "holdout_seed": 883,
            "noise": "complex Gaussian; receiver/frequency common component0.6; colored amplitude1/f",
            "grid": {"f": [8, 16, 32], "c_ms": [100, 400, 5], "directions": [-1, 1], "n": 24, "dx_m": 2},
            "real_field_noise": "UNCALIBRATED: no real noise corpus available; no transfer asserted",
        },
    )


@pytest.mark.vid("V-E5-18")
def test_significance_boundary_and_independent_iid_cohort(record_property):
    boundary = iid_threshold(24, 0.05, hypotheses=10)["threshold"]
    assert 1 - kluyver_cdf(boundary, 24) == pytest.approx(0.005, abs=1e-8)
    assert not boundary > boundary and boundary + 1e-10 > boundary
    rng = np.random.default_rng(818)
    phases = rng.uniform(-np.pi, np.pi, (10000, 10, 24))
    scores = abs(np.exp(1j * phases).mean(axis=2))
    count = int(np.sum(scores.max(axis=1) > boundary))
    assert wilson(count, 10000)[0] <= 0.05
    record_property(
        "bonferroni_holdout",
        {
            "threshold": boundary,
            "n_active": 24,
            "hypotheses": 10,
            "record_count": 10000,
            "false_records": count,
            "wilson95": wilson(count, 10000),
            "origin_identified": False,
        },
    )
