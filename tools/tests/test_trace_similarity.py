"""Validación de la similitud diagnóstica local, sin declarar calibración de campo."""

import json

import numpy as np
import pytest

from geoqc.qc.contracts import SimilarityProtocol, Window
from geoqc.qc.similarity import lagged_correlation, local_similarity
from tools.report_trace_quality import qc_record, synthetic_shot


def protocol(**changes):
    values = dict(
        arrival=Window(start_s=0, end_s=0.4),
        baseline=Window(start_s=-0.2, end_s=-0.05),
        neighbor_radius_m=2.1,
        min_apparent_velocity_ms=100,
        max_lag_s=0.02,
        comparable_channels=True,
        reference="synthetic independent waveform controls",
    )
    return SimilarityProtocol(**(values | changes))


def waveforms(seed=713):
    rng = np.random.default_rng(seed)
    time = np.arange(800) * 0.001 - 0.2
    data = []
    for j in range(9):
        u = time - 0.15 - 0.002 * j
        data.append(
            (0.1 + j / 3) * np.exp(-0.5 * (u / 0.025) ** 2) * np.cos(2 * np.pi * 40 * u)
            + rng.normal(0, 0.0001, time.size)
            + 0.1 * j
        )
    return time, np.array(data), np.arange(9.0)[:, None]


def evaluate(data, coords, settings=None, mask=None):
    return local_similarity(
        data,
        np.isfinite(data) if mask is None else mask,
        (0.001,) * len(data),
        (-0.2,) * len(data),
        coords,
        settings or protocol(),
    )


def test_correlation_matches_independent_pearson_and_recovers_delay_with_gain_and_dc():
    rng = np.random.default_rng(73)
    a = rng.normal(size=200)
    b = rng.normal(size=200)
    assert lagged_correlation(a, b, 0)["signed_rho"] == pytest.approx(np.corrcoef(a, b)[0, 1])
    shifted = np.r_[np.zeros(6), a[:-6]] * 5 + 30
    result = lagged_correlation(shifted, a, 12)
    assert result["lag_samples"] == 6
    assert result["abs_rho"] == pytest.approx(1)
    inverse = lagged_correlation(-shifted, a, 12)
    assert inverse["signed_rho"] == pytest.approx(-1)


def test_delays_amplitude_decay_and_dc_are_not_shape_faults():
    _, data, coords = waveforms()
    results = evaluate(data, coords)
    assert all(r["grade"] == "BUENA" and r["median_abs_rho"] > 0.99 for r in results[1:-1])
    assert results[0]["state"] == "MISSING"  # Dos vecinos: no inventar soporte en el borde.


def test_isolated_frequency_fault_is_red_but_neighbors_are_not_contaminated():
    time, data, coords = waveforms()
    u = time - 0.158
    data[4] = np.exp(-0.5 * (u / 0.025) ** 2) * np.cos(2 * np.pi * 110 * u)
    rows = evaluate(data, coords)
    assert rows[4]["grade"] == "MALA"
    assert rows[4]["median_abs_rho"] < 0.5
    assert rows[4]["neighbor_consensus_rho"] > 0.99
    assert all(rows[j]["grade"] == "BUENA" for j in (2, 3, 5, 6))
    assert all(p["neighbor_channel_1based"] != 5 for p in rows[4]["pairs"])


def test_heterogeneous_neighborhood_abstains_instead_of_condemning_every_channel():
    _, data, coords = waveforms()
    data = np.random.default_rng(411).normal(size=data.shape)
    rows = evaluate(data, coords)
    assert all(row["grade"] == "REGULAR" for row in rows)
    assert rows[4]["neighbor_consensus_rho"] < 0.8


def test_geometry_not_channel_order_defines_neighbors_and_pair_lag_sign_is_consistent():
    _, data, coords = waveforms()
    original = evaluate(data, coords)
    permutation = np.array([4, 0, 8, 2, 5, 1, 6, 7, 3])
    reordered = evaluate(data[permutation], coords[permutation])
    for j, previous in enumerate(permutation):
        assert reordered[j]["median_abs_rho"] == pytest.approx(original[previous]["median_abs_rho"])
    forward = next(p for p in original[4]["pairs"] if p["neighbor_channel_1based"] == 6)
    reverse = next(p for p in original[5]["pairs"] if p["neighbor_channel_1based"] == 5)
    assert forward["lag_s"] == -reverse["lag_s"]
    assert forward["lag_s"] == forward["lag_samples"] * 0.001
    assert reverse["lag_s"] == reverse["lag_samples"] * 0.001
    assert abs(forward["lag_s"]) <= forward["max_lag_s"]


def test_gaps_constants_and_short_windows_do_not_create_false_correlations():
    _, data, coords = waveforms()
    mask = np.ones_like(data, dtype=bool)
    mask[4, 350] = False
    data[4, 350] = np.nan
    data[5] = 0
    rows = evaluate(data, coords, mask=mask)
    assert rows[4]["state"] == rows[5]["state"] == "MISSING"
    assert rows[4]["median_abs_rho"] is None
    json.dumps(rows, allow_nan=False)
    assert lagged_correlation(np.zeros(20), np.zeros(20), 2) is None
    with pytest.raises(ValueError):
        lagged_correlation(np.zeros(8), np.zeros(8), 0)


def test_incompatible_clocks_and_undeclared_comparability():
    _, data, coords = waveforms()
    with pytest.raises(ValueError, match="muestreo"):
        local_similarity(data, np.isfinite(data), (0.002,) + (0.001,) * 8, (-0.2,) * 9, coords, protocol())
    with pytest.raises(ValueError, match="rejilla"):
        local_similarity(data, np.isfinite(data), (0.001,) * 9, (-0.2005,) + (-0.2,) * 8, coords, protocol())
    assert all(r["state"] == "MISSING" for r in evaluate(data, coords, protocol(comparable_channels=False)))


def test_protocol_rejects_excess_lag_and_overlapping_baseline():
    with pytest.raises(ValueError, match="solape"):
        protocol(max_lag_s=0.2)
    with pytest.raises(ValueError, match="disjuntas"):
        protocol(baseline=Window(start_s=0.1, end_s=0.3))


def test_optional_common_qc_integration_catches_good_snr_but_wrong_waveform():
    shot, settings, _ = synthetic_shot(18)
    data = shot.data.copy()
    time = shot.t0_s[6] + np.arange(data.shape[1]) * shot.dt_s[6]
    window = (time >= 0) & (time < 0.5)
    data[6, window] = 0.1 * np.sin(2 * np.pi * 110 * time[window])
    shot = type(shot).model_validate(shot.model_dump() | {"data": data})
    before = qc_record(shot, settings, site="Test", kind="SINTÉTICO", source="test")
    assert before["traces"][6]["quality"]["grade"] == "BUENA"
    similarity = protocol(arrival=Window(start_s=0, end_s=0.5), neighbor_radius_m=4.1)
    settings = type(settings).model_validate(settings.model_dump() | {"similarity": similarity})
    after = qc_record(shot, settings, site="Test", kind="SINTÉTICO", source="test")
    assert after["traces"][6]["similarity"]["grade"] == "MALA"
    assert after["traces"][6]["quality"]["grade"] == "MALA"
    assert after["traces"][6]["snr"]["value"] > 12
