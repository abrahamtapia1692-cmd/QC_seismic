"""Pruebas discriminantes de las correcciones a la revisión externa del dosier."""

from pathlib import Path

import numpy as np
import pytest

from geoqc.io.binary import parse_seg2
from geoqc.qc.noise import (
    NoiseProtocol,
    digital_integrity,
    filter_candidate,
    low_frequency_coherence,
    noise_diagnostics,
)
from geoqc.qc.quality import TraceQualityPolicy, assess_quality, trace_quality
from tools.tests.test_trace_quality import valid_trace


def protocol():
    return NoiseProtocol(noise={"start_s": -4, "end_s": 0}, signal={"start_s": 0, "end_s": 4}, reference="synthetic")


def diagnostic(data):
    return noise_diagnostics(data, np.isfinite(data), 0.001, -4, protocol())


def test_conditional_snr_uses_power_and_is_invariant_to_gain_without_adc():
    rng = np.random.default_rng(791)
    data = rng.normal(size=8000)
    time = np.arange(4000) * 0.001
    data[4000:] += np.sqrt(20) * np.sin(2 * np.pi * 80 * time)
    a, b = diagnostic(data), diagnostic(data * 1e-5)
    assert a["snr"]["value"] == pytest.approx(10, abs=0.5)
    assert a["snr"]["value"] == pytest.approx(b["snr"]["value"])
    assert a["snr"]["state"] == "CONDITIONAL"
    assert not a["stationarity"]["transfer_to_signal_verified"]


def test_mad_does_not_erase_impulsive_noise_power():
    rng = np.random.default_rng(88)
    a = rng.normal(size=8000)
    b = a.copy()
    b[np.arange(0, 4000, 100)] += 30
    ordinary, spikes = diagnostic(a), diagnostic(b)
    assert spikes["noise_power"] > 5 * ordinary["noise_power"]
    assert spikes["noise_sigma_mad"] == pytest.approx(ordinary["noise_sigma_mad"], rel=0.1)
    assert any("MAD" in alert for alert in spikes["alerts"])


def test_nonstationarity_is_disclosed_without_selecting_quietest_quartile():
    rng = np.random.default_rng(381)
    data = rng.normal(size=8000)
    data[2000:4000] *= 10
    result = diagnostic(data)
    assert result["stationarity"]["state"] == "VARIABLE_OR_UNRESOLVED"
    assert result["noise_power"] > 30
    assert result["snr"]["state"] == "CONDITIONAL"


def test_zero_noise_and_gaps_do_not_become_infinite_good_snr():
    data = np.zeros(8000)
    data[4000:] = np.sin(np.arange(4000))
    result = diagnostic(data)
    assert result["snr"]["value"] is None
    assert result["snr"]["censoring"] == "ZERO_NOISE"
    mask = np.ones(8000, dtype=bool)
    mask[1000] = False
    result = noise_diagnostics(data, mask, 0.001, -4, protocol())
    assert result["state"] == "MISSING"


def test_line_frequency_drift_and_harmonics_are_candidates_with_resolution():
    rng = np.random.default_rng(93)
    time = np.arange(8000) * 0.001 - 4
    data = rng.normal(0, 0.1, time.size) + np.sin(2 * np.pi * 59.95 * time) + 0.5 * np.sin(2 * np.pi * 119.9 * time)
    lines = diagnostic(data)["lines"]
    for nominal, actual in [(60, 59.95), (120, 119.9)]:
        line = next(line for line in lines if line["nominal_hz"] == nominal)
        assert line["estimated_hz"] == pytest.approx(actual, abs=0.03)
        assert line["bin_width_hz"] == 0.25
        assert line["frequency_uncertainty_hz"] is None
        assert line["state"] == "CANDIDATE"


def test_low_frequency_band_and_coherence_require_duration_not_padding():
    rng = np.random.default_rng(82)
    short = rng.normal(size=700)
    result = low_frequency_coherence(short, short.copy(), 0.001, (1, 15))
    assert result["state"] == "MISSING"
    assert result["required_duration_s"] == 7.5
    t = np.arange(10000) * 0.001
    shared = 4 * np.sin(2 * np.pi * 7 * t)
    a = shared + rng.normal(0, 0.05, t.size)
    b = shared + rng.normal(0, 0.05, t.size)
    result = low_frequency_coherence(a, b, 0.001, (6, 8))
    assert result["state"] == "MEASURED" and result["value"] > 0.9
    data = np.sin(2 * np.pi * 7 * (np.arange(8000) * 0.001))
    d = diagnostic(data)
    assert d["low_frequency"]["state"] == "MEASURED"
    assert d["low_frequency"]["noise_power_to_signal_total_power"] > 0.9


def test_zero_phase_candidate_attenuates_noise_preserves_raw_and_rejects_unstable_pick():
    dt = 0.001
    t = np.arange(6000) * dt
    data = np.sin(2 * np.pi * 59.95 * t) + np.sin(2 * np.pi * 3 * t) + np.sin(2 * np.pi * 100 * t)
    raw = data.copy()
    picks = iter((1.0, 1.003))
    filtered, audit = filter_candidate(data, dt, highpass_hz=10, notch_hz=(59.95,), pick=lambda _: next(picks))
    np.testing.assert_array_equal(data, raw)
    for frequency in (3, 59.95):
        wave = np.exp(-2j * np.pi * frequency * t[1000:-1000])
        assert abs(np.dot(filtered[1000:-1000], wave)) < 0.05 * abs(np.dot(data[1000:-1000], wave))
    assert audit["pick_stability"] == "FAIL"
    assert audit["status"] == "CANDIDATE_ONLY"
    assert not audit["promoted_to_raw"]
    assert len(audit["preprocessing_chain"]) == 2
    assert audit["input_sha256"] != audit["output_sha256"]
    _, no_picks = filter_candidate(data, dt, notch_hz=(60,))
    assert no_picks["pick_stability"] == "UNVERIFIED"


def test_zero_phase_can_create_energy_before_a_causal_onset():
    data = np.zeros(2000)
    data[1000] = 1
    filtered, audit = filter_candidate(data, 0.001, highpass_hz=10)
    assert np.max(abs(filtered[900:1000])) > 0.001
    assert audit["pick_stability"] == "UNVERIFIED"


def test_incomplete_evidence_is_not_bad_and_all_channels_remain_in_denominator():
    t = valid_trace()
    t["clip"] = {"state": "MISSING", "reason": "ADC desconocido"}
    pending = trace_quality(t, TraceQualityPolicy())
    assert pending["assessment_grade"] == "NO_EVALUABLE"
    t["statistics"]["dead"] = True
    bad = trace_quality(t, TraceQualityPolicy())
    result = assess_quality([pending] * 46 + [bad] * 2)
    assert result["grade"] == "NO_EVALUABLE"
    assert result["demonstrated_bad_traces"] == 2
    assert result["total_traces"] == 48
    assert result["good_percent_bounds"] == [0, 100 * 46 / 48]
    result = assess_quality([pending] * 70 + [bad] * 30)
    assert result["grade"] == "MALA"  # Incluso resolver todo faltante no alcanza el 75%.
    good = trace_quality(valid_trace(), TraceQualityPolicy())
    assert assess_quality([good] * 90 + [pending] * 10)["grade"] == "BUENA"
    assert assess_quality([])["grade"] == "NO_EVALUABLE"


def test_claimed_truncation_channel22_is_not_supported_by_samples():
    path = Path("examples/field/raw/chevremont/example/Chevremont/60m.sg2")
    decoded = parse_seg2(path.read_bytes())
    values = decoded.traces[21]
    result = digital_integrity(values, decoded.dt_s[21])
    assert result["samples"] == result["finite_samples"] == 4000
    assert np.ptp(values[-400:]) > 0
    assert result["alerts"] == []
    assert result["truncated_record"] is None
    synthetic = values.copy()
    synthetic[-400:] = 0
    assert digital_integrity(synthetic, decoded.dt_s[21])["alerts"]
