import numpy as np
import pytest

from geoqc.core.evidence import canonical_hash
from geoqc.core.models import Shot
from geoqc.synth.trs import two_layer_times
from geoqc.synth.wavelets import causal_pulse
from geoqc.trs.contracts import PickCalibration, TRSProtocol
from geoqc.trs.picking import aic_curve, estimator_hash, pick_shot, pick_trace
from geoqc.trs.report import trs_diagnostics
from tests.synthetic.e4_support import DT, TIME, pick_protocol, realization, record, trs_shot, wilson


@pytest.fixture(scope="module", params=[15, 20, 30])
def calibrated(request):
    db = request.param
    protocol = pick_protocol(db)
    rng = np.random.default_rng(4400 + db)
    errors = []
    for _ in range(2000):
        data, truth = realization(rng, db)
        pick = pick_trace(trs_shot(data), 0, protocol)
        if pick.onset_s is not None:
            errors.append(pick.onset_s - truth)
    assert len(errors) >= 1900
    calibration = PickCalibration(
        domain_id=protocol.domain_id,
        protocol_hash=canonical_hash(protocol),
        estimator_hash=estimator_hash(),
        dt_s=DT,
        errors_s=tuple(errors),
        training_ref=f"PCG64 seed {4400 + db}, n=2000, requirements_e4.md",
    )
    return db, protocol, calibration


@pytest.mark.vid("V-E4-1")
def test_causal_onset_accuracy(calibrated, record_property):
    db, protocol, _ = calibrated
    rng = np.random.default_rng(6400 + db)
    errors, missing = [], 0
    for _ in range(500):
        data, truth = realization(rng, db)
        pick = pick_trace(trs_shot(data), 0, protocol)
        if pick.onset_s is None:
            missing += 1
        else:
            errors.append(pick.onset_s - truth)
    assert missing <= 10
    assert np.median(abs(np.array(errors))) <= DT
    assert np.percentile(abs(np.array(errors)), 95) <= 3 * DT
    record(
        record_property,
        "onset_accuracy",
        {
            "db": db,
            "n": 500,
            "missing": missing,
            "bias_s": float(np.mean(errors)),
            "median_abs_error_s": float(np.median(abs(np.array(errors)))),
            "p95_abs_error_s": float(np.percentile(abs(np.array(errors)), 95)),
            "filter": "NONE, DC from noise",
        },
    )


@pytest.mark.vid("V-E4-2")
def test_dead_burst_ambiguity_and_polarity(calibrated):
    db, protocol, calibration = calibrated
    rng = np.random.default_rng(7400 + db)
    dead = pick_trace(trs_shot(np.zeros(TIME.size)), 0, protocol, calibration)
    assert dead.confidence == "MISSING" and dead.onset_s is None
    noise = rng.normal(0, 0.02, TIME.size)
    burst = noise.copy()
    burst[300:304] += 3
    assert pick_trace(trs_shot(burst), 0, protocol, calibration).confidence in ("AMBIGUOUS", "MISSING")
    first, _ = realization(rng, 30, onset=0.025)
    second, _ = realization(rng, 30, onset=0.10)
    assert pick_trace(trs_shot(first + second), 0, protocol, calibration).confidence == "AMBIGUOUS"
    data, _ = realization(rng, db)
    positive = pick_trace(trs_shot(data), 0, protocol, calibration)
    negative = pick_trace(trs_shot(-data), 0, protocol, calibration)
    assert positive.onset_s == negative.onset_s
    assert positive.sigma_s == negative.sigma_s


@pytest.mark.vid("V-E4-3")
def test_independent_holdout_intervals(calibrated, record_property):
    db, protocol, calibration = calibrated
    rng = np.random.default_rng(5400 + db)
    errors, interval_hits, hits68, confident_large = [], 0, 0, 0
    training = np.array(calibration.errors_s)
    bias = float(np.mean(training))
    q68 = np.quantile(training - bias, [0.16, 0.84])
    missing = 0
    for _ in range(2000):
        data, truth = realization(rng, db)
        pick = pick_trace(trs_shot(data), 0, protocol, calibration)
        if pick.confidence != "CALIBRATED":
            missing += 1
            continue
        errors.append(pick.onset_s - truth)
        interval_hits += pick.interval_s[0] <= truth <= pick.interval_s[1]
        hits68 += pick.onset_s - q68[1] <= truth <= pick.onset_s - q68[0]
        confident_large += abs(pick.onset_s - truth) > 3 * pick.sigma_s
    n = len(errors)
    assert n >= 1900
    assert abs(interval_hits / n - 0.95) <= 0.02
    assert abs(hits68 / n - 0.68) <= 0.03
    assert confident_large / n <= 0.02
    record(
        record_property,
        "holdout_calibration",
        {
            "db": db,
            "n": n,
            "missing": missing,
            "training_n": len(training),
            "training_hash": canonical_hash(calibration),
            "bias_train_s": bias,
            "sigma_train_s": float(np.std(training, ddof=1)),
            "bias_holdout_s": float(np.mean(errors)),
            "coverage68": hits68 / n,
            "coverage68_wilson95": wilson(hits68, n),
            "coverage95": interval_hits / n,
            "coverage95_wilson95": wilson(interval_hits, n),
            "confident_over_3sigma": confident_large,
            "confident_denominator": n,
            "scope": calibration.scope,
        },
    )


@pytest.mark.vid("V-E4-4")
def test_scaling_translation_permutation_and_aic_reference():
    rng = np.random.default_rng(4444)
    data, _ = realization(rng, 20, onset=0.06)
    source = trs_shot(np.array([data, data * 0.3, -data]), receiver_x=[1, 2, 3])
    protocol = pick_protocol()
    picks = pick_shot(source, protocol)
    scaled = Shot.model_validate(source.model_dump() | {"data": source.data * 7})
    assert [pick.onset_s for pick in pick_shot(scaled, protocol)] == [pick.onset_s for pick in picks]
    order = [2, 0, 1]
    geometry = source.geometry.model_dump() | {
        "xr": source.geometry.xr[order],
        "yr": source.geometry.yr[order],
        "zr": source.geometry.zr[order],
    }
    acquisition = source.acquisition.model_dump() | {
        "receiver_ids": tuple(source.acquisition.receiver_ids[j] for j in order)
    }
    permuted = Shot.model_validate(
        source.model_dump()
        | {
            "data": source.data[order],
            "valid_mask": source.valid_mask[order],
            "geometry": geometry,
            "acquisition": acquisition,
        }
    )
    assert [pick.onset_s for pick in pick_shot(permuted, protocol)] == [picks[j].onset_s for j in order]
    translated = trs_shot(data, t0=-0.025 + 0.01)
    translated_protocol = type(protocol).model_validate(
        protocol.model_dump()
        | {"search": {"start_s": 0.01, "end_s": 0.17}, "noise": {"start_s": -0.015, "end_s": 0.005}}
    )
    assert pick_trace(translated, 0, translated_protocol).onset_s == pytest.approx(picks[0].onset_s + 0.01)
    samples = rng.normal(size=64)
    splits, values = aic_curve(samples, min_segment=8)
    # Referencia ddof=0 por segmentos; el escalado añade constante común.
    expected = np.array(
        [k * np.log(np.var(samples[:k])) + (64 - k) * np.log(np.var(samples[k:])) for k in splits.astype(int)]
    )
    np.testing.assert_allclose(values - values[0], expected - expected[0], atol=1e-11)
    assert int(splits[np.argmin(values)]) == int(splits[np.argmin(expected)])


@pytest.mark.vid("V-E4-4")
def test_calibrated_report_integrates_source_correction_and_inversion(calibrated):
    db, protocol, calibration = calibrated
    rng = np.random.default_rng(8400 + db)
    receivers = np.linspace(3, 24, 24)
    expected = np.array(two_layer_times(receivers, 300, 1500, 5).first_s) + 0.03
    data = np.array([realization(rng, db, onset=float(onset))[0] for onset in expected])
    settings = TRSProtocol(
        picking=protocol,
        branch_error_model="GAUSSIAN_CANDIDATE",
        horizontal_two_layers_verified=True,
        geological_model_ref="known synthetic generator",
        source_clock_correction_s=0.03,
        time_correction_ref="known +30ms",
        roi_ref="known horizontal 0..10m",
        max_evaluations=80,
        provenance="integration test",
    )
    report = trs_diagnostics(trs_shot(data, receiver_x=receivers), settings, calibration)
    assert all(row["arrival"]["confidence"] == "CALIBRATED" for row in report["picks"])
    assert all(
        abs(row["arrival"]["onset_s"] - onset) < 0.001 for row, onset in zip(report["picks"], expected, strict=True)
    )
    right = next(row for row in report["branches"] if row["side"] == "RIGHT")
    assert right["parameters"]["state"] == "VALID" and right["inversion"]["state"] == "VALID"
    assert np.max(abs(np.array(right["inversion"]["velocities_ms"]) / [300, 1500] - 1)) < 0.05
    assert report["eligible_for_acceptance"] is False and report["evidence_status"] == "INCOMPLETE"


@pytest.mark.vid("V-E4-1")
def test_smooth_e3_source_does_not_inherit_synthetic_calibration(record_property):
    rng = np.random.default_rng(44100)
    smooth = causal_pulse(TIME, 80, onset_s=0.05)
    data = smooth.samples + rng.normal(0, 0.015, TIME.size)
    pick = pick_trace(trs_shot(data), 0, pick_protocol())
    assert pick.confidence in ("UNCALIBRATED", "AMBIGUOUS", "MISSING") and pick.sigma_s is None
    record(
        record_property,
        "smooth_source_control",
        {
            "analytic_onset_s": 0.05,
            "estimated_onset_s": pick.onset_s,
            "bias_s": None if pick.onset_s is None else pick.onset_s - 0.05,
            "confidence": pick.confidence,
            "scope": "gradual pulse outside hard-front calibration; no accuracy target or confident sigma inherited",
        },
    )
