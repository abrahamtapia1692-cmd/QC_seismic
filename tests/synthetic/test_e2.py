"""Experimentos E2 registrados en docs/requirements_e2.md."""

import json

import numpy as np
import pytest
from scipy.signal import lfilter
from scipy.stats import linregress
from scipy.stats import t as student_t

from geoqc.core.config import Threshold, load_config
from geoqc.core.models import Acquisition, Geometry, Shot
from geoqc.qc import common_qc
from geoqc.qc.channels import channel_statistics, clipping
from geoqc.qc.contracts import QCProtocol, RepeatProtocol, Window
from geoqc.qc.spectral import mains_line, noise_psd, snr
from geoqc.qc.timing import (
    compare_repeats,
    instrument_response,
    repeatability,
    required_stacks,
    stack_noise_independence,
    time_budget,
)


def shot(data, *, dt=0.001, t0=0.0, rails=None, stack_count=1, stack_kind="RAW", mask=None, offsets=None):
    data = np.atleast_2d(data)
    n = data.shape[0]
    mask = np.ones_like(data, dtype=bool) if mask is None else mask
    return Shot(
        id="e2-synthetic",
        data=data,
        valid_mask=mask,
        mask_reasons=tuple("excluded" if not np.all(row) else "" for row in mask),
        dt_s=(dt,) * n,
        t0_s=(t0,) * n,
        geometry=Geometry(
            xr=np.arange(n) + 1 if offsets is None else offsets,
            yr=np.zeros(n),
            zr=np.zeros(n),
            xs=0,
            ys=0,
            zs=0,
            uncertainty_m=(0.01,) * n,
            crs="local-SI",
            provenance=("fixture",),
        ),
        acquisition=Acquisition(
            technique="MASW",
            wave="RAYLEIGH",
            component="Z",
            source_type="synthetic",
            receiver_ids=tuple(f"r{j}" for j in range(n)),
            adc_rails=rails,
            stack_count=stack_count,
            stack_kind=stack_kind,
        ),
        input_hashes=("a" * 64,),
        headers_json='{"fixture":"independent labels outside headers"}',
    )


def protocol(end, **kwargs):
    return QCProtocol(analysis=Window(start_s=0, end_s=end), provenance="registered:e2-synthetic", **kwargs)


def wilson(success, count):
    z = 1.959963984540054
    p = success / count
    center = (p + z * z / (2 * count)) / (1 + z * z / count)
    half = z * np.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / (1 + z * z / count)
    return [float(center - half), float(center + half)]


def record(record_property, name, value):
    record_property(name, json.dumps(value, allow_nan=False))


@pytest.mark.vid("V-E2-1")
def test_time_budget():
    p = QCProtocol(
        analysis=Window(start_s=0, end_s=1.9),
        min_group_velocity_ms=80,
        wavelet_duration_s=0.3,
        frequency_band_hz=(1000, 2000),
        provenance="scenario",
    )
    for distance, required in [(51, 0.9375), (134, 1.975)]:
        s = shot(np.zeros((1, 4000)), dt=0.0005, t0=-0.1, offsets=[distance])
        result = time_budget(s, 0, p)
        assert result["post_required_s"] == pytest.approx(required)
        assert result["post_sufficient"] is (distance == 51)
        assert result["band_policy_satisfied"] is False
        assert result["antialias_verified"] is None
        assert result["fft_bin_hz"] == pytest.approx(1 / 1.9)
        assert result["budget_kind"] == "CONSERVATIVE_SCENARIO"


@pytest.mark.vid("V-E2-2")
def test_dead_controls_and_attenuation(record_property):
    rng = np.random.default_rng(2202)
    time = np.arange(1024) * 0.001
    base = np.sin(2 * np.pi * 32 * time)
    gains = np.exp(-np.arange(24) / 8)
    p = protocol(1.024, expected_relative_amplitude=tuple(gains), amplitude_model_ref="known gain and attenuation")
    for k in range(1, 5):
        data = gains[:, None] * base
        data[:k] = 0
        stats = channel_statistics(shot(data), p)
        assert [row["dead"] for row in stats] == [True] * k + [False] * (24 - k)
    false_positive = 0
    for _ in range(250):
        data = gains[:, None] * (base + rng.normal(0, 0.01, (24, base.size))) + rng.uniform(-10, 10, (24, 1))
        stats = channel_statistics(shot(data), p)
        false_positive += any(row["dead"] or row["amplitude_anomaly"] for row in stats)
    assert false_positive / 250 <= 0.02
    record(
        record_property,
        "clean_fpr",
        {
            "numerator": false_positive,
            "denominator": 250,
            "unit": "independent realization",
            "wilson95": wilson(false_positive, 250),
        },
    )
    stats = channel_statistics(
        shot(np.tile(base, (24, 1))),
        protocol(1.024, expected_relative_amplitude=(1,) * 24, amplitude_model_ref="equal gains"),
    )
    assert all(row["mad_branch"] == "ZERO_OR_ROUNDOFF" and not row["amplitude_anomaly"] for row in stats)
    constant = channel_statistics(shot(np.ones((3, 100))), protocol(0.1))
    assert all(row["constant"] and not row["dead"] for row in constant)


@pytest.mark.vid("V-E2-3")
def test_clip_adc_gain_mask_plateau_and_sine():
    time = np.arange(10000) * 0.001
    sine = 0.9 * np.sin(2 * np.pi * 4 * time)
    p = protocol(10, rail_scale_to_data=1)
    assert np.mean(abs(sine) > 0.98 * max(sine)) > 0.1
    assert clipping(shot(sine, rails=(-1, 1)), 0, p).value == 0
    plateau = np.round(sine, 1)
    assert clipping(shot(plateau, rails=(-1, 1)), 0, p).value == 0
    data = np.clip(2 * sine, -1, 1)
    assert clipping(shot(data, rails=(-1, 1)), 0, p).value == np.mean(abs(data) == 1)
    mask = np.ones((1, data.size), dtype=bool)
    mask[0, ::7] = False
    masked = clipping(shot(data, rails=(-1, 1), mask=mask), 0, p)
    assert masked.value == np.mean(abs(data[mask[0]]) == 1)
    assert clipping(shot(data * 3, rails=(-1, 1)), 0, protocol(10, rail_scale_to_data=3)).value == np.mean(
        abs(data) == 1
    )
    assert clipping(shot(data, rails=(-1, 1)), 0, protocol(10)).state == "MISSING"
    unknown = clipping(shot(data), 0, p)
    assert unknown.state == "MISSING" and json.loads(unknown.details_json)["confirmed"] is False
    for kind in ("SUM", "MEAN", "UNKNOWN"):
        assert clipping(shot(data, rails=(-1, 1), stack_count=4, stack_kind=kind), 0, p).state == "MODEL_INAPPLICABLE"
    threshold = Threshold(
        id="clip",
        unit="fraction",
        direction="lower_is_better",
        warn=1e-4,
        fail=1e-3,
        boundary="inclusive",
        mandatory=True,
        critical=True,
        calibration_state="UNVALIDATED",
    )
    for hits, expected in [(0, "PASS"), (1, "WARN"), (10, "FAIL")]:
        data = np.zeros(10000)
        data[:hits] = 1
        assert threshold.diagnostic_classification(clipping(shot(data, rails=(-1, 1)), 0, p).value) == expected


@pytest.mark.vid("V-E2-4")
@pytest.mark.parametrize("kind,length", [("white", 2048), ("white", 8192), ("ar1", 8192)])
def test_snr_monte_carlo(kind, length, record_property):
    rng = np.random.default_rng(2240 + length)
    time = np.arange(length) * 0.001
    base = np.sin(2 * np.pi * 31.25 * time)
    base -= base.mean()
    p = protocol(
        2 * length * 0.001,
        noise=Window(start_s=0, end_s=length * 0.001),
        signal=Window(start_s=length * 0.001, end_s=2 * length * 0.001),
        noise_independent=True,
        noise_stationarity="VERIFIED",
        stationarity_ref="same stationary process",
    )
    summary = []
    for db in (0, 5, 10, 20, 30):
        scale = np.sqrt(np.mean(base**2) / 10 ** (db / 10))
        errors, censored = [], 0
        for _ in range(500):
            noise = rng.normal(size=(2, length + 256))
            if kind == "ar1":
                noise = lfilter([np.sqrt(1 - 0.6**2)], [1, -0.6], noise, axis=1)
            noise = noise[:, 256:] * scale
            result = snr(shot(np.concatenate((noise[0], base + noise[1]))), 0, p)
            if result.state == "CENSORED":
                censored += 1
            else:
                errors.append(result.value - db)
                details = json.loads(result.details_json)
                assert details["snr_total_ratio"] == pytest.approx(details["snr_net_ratio"] + 1)
        bias, mae = float(np.mean(errors)), float(np.mean(abs(np.asarray(errors))))
        half = float(student_t.ppf(0.975, len(errors) - 1) * np.std(errors, ddof=1) / np.sqrt(len(errors)))
        if db >= 5:
            assert censored == 0 and mae <= 1.5 and abs(bias) <= 1
        summary.append(
            {
                "snr_db": db,
                "n": 500,
                "censored": censored,
                "bias_db": bias,
                "mae_db": mae,
                "bias_ci95": [bias - half, bias + half],
                "length_samples": length,
                "kind": kind,
            }
        )
    record(record_property, "snr_strata", summary)


@pytest.mark.vid("V-E2-4")
def test_snr_missing_censored_and_psd():
    rng = np.random.default_rng(2241)
    data = rng.normal(size=4096)
    p = protocol(
        4.096,
        noise=Window(start_s=0, end_s=2.048),
        signal=Window(start_s=2.048, end_s=4.096),
        noise_independent=True,
        noise_stationarity="VERIFIED",
        stationarity_ref="controlled",
    )
    assert snr(shot(data), 0, protocol(4.096)).state == "MISSING"
    assert snr(shot(np.r_[np.zeros(2048), data[:2048]]), 0, p).state == "CENSORED"
    assert snr(shot(np.r_[data[:2048], np.zeros(2048)]), 0, p).state == "CENSORED"
    missing = np.ones((1, 4096), dtype=bool)
    missing[0, 1] = False
    assert snr(shot(data, mask=missing), 0, p).state == "MISSING"
    result = noise_psd(shot(data), 0, p)
    assert result["unit"] == "counts^2/Hz" and result["bin_width_hz"] == 1000 / 256
    assert result["dof_upper_bound"] == 2 * result["noise_segments"]
    assert np.all(np.asarray(result["net_psd"]) >= 0)
    # Integral PSD blanca cerca de varianza; no se exige igualdad de una ventana Hann.
    assert sum(result["noise_psd"]) * result["bin_width_hz"] == pytest.approx(np.var(data[:2048]), rel=0.05)


@pytest.mark.vid("V-E2-5")
@pytest.mark.parametrize("frequency", [50, 60])
def test_mains_duration_precision(frequency, record_property):
    rng = np.random.default_rng(2250 + frequency)
    time = np.arange(20000) * 0.001
    errors = []
    p = protocol(20, mains_hz=frequency)
    for _ in range(100):
        actual = frequency + rng.uniform(-0.4, 0.4)
        data = 0.5 * np.sin(2 * np.pi * actual * time + rng.uniform(0, 2 * np.pi)) + rng.normal(0, 0.05, time.size)
        result = mains_line(shot(data), 0, p)
        assert result.flagged and abs(result.value - actual) <= 0.1
        errors.append(abs(result.value - actual))
    record(
        record_property,
        "line_error",
        {"n": 100, "duration_s": 20, "noise_sigma": 0.05, "bin_hz": 0.05, "max_abs_error_hz": max(errors)},
    )
    assert mains_line(shot(data[:100]), 0, protocol(0.1, mains_hz=frequency)).state == "MODEL_INAPPLICABLE"


def repeat_protocol(**changes):
    return RepeatProtocol.model_validate(
        dict(
            dt_s=0.001,
            max_lag_s=0.01,
            frequency_band_hz=(10, 100),
            same_source=True,
            comparable_acquisition=True,
            reference="same-source controlled pulse",
        )
        | changes
    )


def pulse(time, delay=0):
    u = time - 0.512 - delay
    return np.exp(-0.5 * (u / 0.025) ** 2) * np.cos(2 * np.pi * 40 * u)


@pytest.mark.vid("V-E2-6")
def test_polarity_propagation_and_amplitude():
    time = np.arange(3000) * 0.001
    reference = np.sin(2 * np.pi * 40 * time)
    neighbor = np.sin(2 * np.pi * 40 * time - 2 * np.pi / 3)
    assert np.corrcoef(reference, neighbor)[0, 1] == pytest.approx(-0.5)
    p = repeat_protocol(max_lag_s=0.1)
    assert compare_repeats(reference, neighbor, p).state == "AMBIGUOUS"
    time = np.arange(1024) * 0.001
    assert compare_repeats(pulse(time), -pulse(time), repeat_protocol()).flagged
    data = np.tile(pulse(time), (24, 1))
    data[3] *= 0.2
    rows = channel_statistics(
        shot(data), protocol(1.024, expected_relative_amplitude=(1,) * 24, amplitude_model_ref="known propagation")
    )
    assert rows[3]["amplitude_anomaly"] is True
    assert "causa no identificada" in rows[3]["amplitude_reason"]


@pytest.mark.vid("V-E2-7")
def test_subsample_delay_independent_reference(record_property):
    time = np.arange(1024) * 0.001
    errors = []
    for delay in np.linspace(-0.0024, 0.0024, 201):
        result = compare_repeats(pulse(time), pulse(time, delay), repeat_protocol())
        assert result.state == "VALID"
        errors.append(abs(result.value - delay))
    assert max(errors) <= 0.05 * 0.001
    record(
        record_property,
        "lag_error",
        {
            "n": 201,
            "dt_s": 0.001,
            "max_error_s": max(errors),
            "truth": "analytic translated continuous waveform, no injector/interpolation",
            "band_hz": [10, 100],
        },
    )
    assert compare_repeats(pulse(time), pulse(time), repeat_protocol(same_source=False)).state == "MODEL_INAPPLICABLE"
    assert (
        compare_repeats(pulse(time), pulse(time), repeat_protocol(frequency_band_hz=(200, 400))).state
        == "MODEL_INAPPLICABLE"
    )
    delays = np.array([-0.001, 0, 0.001, 0.002])
    report = repeatability(pulse(time), np.array([pulse(time, delay) for delay in delays]), repeat_protocol())
    assert report["jitter"]["value"] == pytest.approx(np.std(delays, ddof=1) * 1000, abs=0.005)
    assert repeatability(pulse(time), np.array([pulse(time)] * 2), repeat_protocol())["jitter"]["state"] == "MISSING"


@pytest.mark.vid("V-E2-8")
def test_stack_slope_and_correlated_failure(record_property):
    rng = np.random.default_rng(2280)
    time = np.arange(4096) * 0.001
    clean = np.sin(2 * np.pi * 31.25 * time)
    counts = np.array([1, 2, 4, 8, 16])
    slopes = []
    for _ in range(200):
        replicas = rng.normal(size=(16, time.size))
        improvement = [10 * np.log10(np.var(clean) / np.var(replicas[:n].mean(axis=0))) for n in counts]
        slopes.append(linregress(10 * np.log10(counts), improvement).slope)
    mean = float(np.mean(slopes))
    half = float(student_t.ppf(0.975, 199) * np.std(slopes, ddof=1) / np.sqrt(200))
    assert 0.85 <= mean - half <= mean + half <= 1.15
    record(record_property, "stack_slope", {"n": 200, "mean": mean, "ci95": [mean - half, mean + half]})
    common = rng.normal(size=time.size)
    correlated = np.tile(common, (16, 1))
    assert stack_noise_independence(correlated).flagged is True
    assert stack_noise_independence(replicas).flagged is False
    assert np.var(correlated.mean(axis=0)) == pytest.approx(np.var(common))
    prediction = required_stacks(
        actual=4, snr_actual_db=6, snr_target_db=12, independent_noise=True, comparable=True, stack_kind="MEAN"
    )
    assert prediction.value == 16
    assert (
        required_stacks(
            actual=4, snr_actual_db=6, snr_target_db=12, independent_noise=False, comparable=True, stack_kind="MEAN"
        ).state
        == "MODEL_INAPPLICABLE"
    )


@pytest.mark.vid("V-E2-9")
def test_response_complex_nominal_and_sub_fn():
    f = np.array([0, 1, 2, 4.5, 10, 30, 100])
    for fn, damping in [(4.5, 0.7), (10, 0.4)]:
        result = instrument_response(f, fn_hz=fn, damping=damping)
        # Transferencia de velocidad obtenida de s²/(s²+2h wn s+wn²), s=i omega.
        s, wn = 2j * np.pi * f, 2 * np.pi * fn
        independent = s**2 / (s**2 + 2 * damping * wn * s + wn**2)
        estimated = np.array(result["real"]) + 1j * np.array(result["imag"])
        np.testing.assert_allclose(estimated, independent, rtol=1e-14, atol=1e-15)
        assert abs(estimated[1]) > 0 and result["calibration_state"] == "MISSING"
    assert (
        instrument_response(f, fn_hz=4.5, damping=0.7, calibration_ref="unverified")["calibration_state"]
        == "UNVERIFIED_REFERENCE"
    )


@pytest.mark.vid("V-E2-10")
def test_report_requires_calibration_and_no_hidden_acceptance():
    from pathlib import Path

    data = np.random.default_rng(2210).normal(size=(3, 128))
    result = common_qc(shot(data), protocol(0.128), load_config(Path("configs/vs30_sitio.yaml")))
    assert result["eligible_for_acceptance"] is False
    assert result["report"]["evidence_status"] == "INCOMPLETE"
    assert result["report"]["quality_status"] is None
    assert "FIELD_CALIBRATION_G9" in result["report"]["missing_requirement_ids"]
    assert all(trace["clip"]["state"] == "MISSING" for trace in result["traces"])
    json.dumps(result, allow_nan=False)
