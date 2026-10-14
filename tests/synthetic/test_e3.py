"""Referencias básicas E3; independencia numérica y dominio declarado."""

import numpy as np
import pytest

from geoqc.core.physics import rayleigh_halfspace_velocity
from geoqc.synth.dispersion import LayeredModel, phase_disba, phase_fem
from geoqc.synth.faults import inject_fault
from geoqc.synth.trs import dipping_apparent_velocities, gradient_time, two_layer_times
from geoqc.synth.wavelets import causal_pulse, noise_at_snr, ricker


@pytest.mark.vid("V-E3-1")
def test_ricker_spectrum_parseval_and_causal_truth_are_separate():
    dt, fp = 0.001, 20.0
    time = np.arange(-1.0, 1.0, dt)
    source = ricker(time, fp)
    spectrum = np.fft.fft(source)
    freqs = np.fft.fftfreq(time.size, dt)
    positive = freqs > 0
    peak = freqs[positive][np.argmax(abs(spectrum[positive]))]
    assert abs(peak - fp) <= 1 / (time.size * dt)
    assert np.sum(source**2) * dt == pytest.approx(np.sum(abs(spectrum) ** 2) / time.size * dt, rel=1e-10)
    pulse = causal_pulse(time, fp, onset_s=0.1)
    assert np.all(pulse.samples[time < 0.1] == 0)
    assert pulse.analytic_onset_s == 0.1
    assert pulse.first_nonzero_sample_s >= 0.1


@pytest.mark.vid("V-E3-1")
@pytest.mark.parametrize("kind", ["white", "colored", "coherent", "traffic", "hum", "bursts"])
def test_generated_snr_against_direct_energy_measure(kind):
    source = np.tile(ricker(np.arange(-0.1, 0.1, 0.001), 20.0), (8, 1))
    result = noise_at_snr(source, snr_db=6.0, seed=41, kind=kind)
    independently_measured = 10 * np.log10(np.sum(source**2) / np.sum(result.noise**2))
    assert independently_measured == pytest.approx(6.0, abs=1e-10)
    if kind == "coherent":
        assert np.array_equal(result.noise[0], result.noise[-1])


@pytest.mark.vid("V-E3-2")
def test_two_layers_critical_accessibility_and_crossover():
    v1, v2, h = 500.0, 1000.0, 5.0
    critical = 2 * h * np.tan(np.arcsin(v1 / v2))
    cross = 2 * h * np.sqrt((v2 + v1) / (v2 - v1))
    result = two_layer_times((0.0, critical - 0.001, critical, cross, 2 * cross), v1, v2, h)
    assert result.head_s[0] is None
    assert result.head_s[1] is None
    assert result.head_s[2] is not None
    assert result.critical_distance_m == pytest.approx(critical, rel=1e-12)
    assert result.crossover_distance_m == pytest.approx(cross, rel=1e-12)
    assert result.head_s[3] == pytest.approx(cross / v1, abs=1e-12)
    assert result.first_s[-1] == pytest.approx(result.head_s[-1], abs=1e-12)
    recovered_h = result.intercept_time_s * v1 * v2 / (2 * np.sqrt(v2 * v2 - v1 * v1))
    assert recovered_h == pytest.approx(h, rel=1e-12)


@pytest.mark.vid("V-E3-2")
def test_gradient_limit_and_dip_domain():
    source, receiver = (0.0, 0.0), (20.0, 0.0)
    assert gradient_time(source, receiver, v0=1000.0, gradient=0.0) == 0.02
    assert gradient_time(source, receiver, v0=1000.0, gradient=1e-10) == pytest.approx(0.02, abs=1e-12)
    assert gradient_time(source, receiver, v0=1000.0, gradient=100.0) == pytest.approx(
        2 * np.arcsinh(1.0) / 100, rel=1e-12
    )
    vplus, vminus = dipping_apparent_velocities(500.0, 1000.0, 0.0)
    assert (vplus, vminus) == pytest.approx((1000.0, 1000.0))
    with pytest.raises(ValueError):
        dipping_apparent_velocities(500.0, 1000.0, 40.0)
    with pytest.raises(ValueError):
        gradient_time(source, receiver, v0=1000.0, gradient=-1.0)


@pytest.mark.vid("V-E3-3")
def test_reciprocity_analytic_gradient_and_surface_two_layers():
    a, b = (0.0, 1.0), (12.0, 3.0)
    assert gradient_time(a, b, v0=1000.0, gradient=50.0) == pytest.approx(
        gradient_time(b, a, v0=1000.0, gradient=50.0), abs=1e-12
    )
    result = two_layer_times((12.0,), 500.0, 1000.0, 5.0)
    reverse = two_layer_times((abs(0.0 - 12.0),), 500.0, 1000.0, 5.0)
    assert result.first_s == reverse.first_s


PROFILES = [
    [(5.0, 400.0, 200.0, 1800.0), (0.0, 800.0, 400.0, 2000.0)],
    [(3.0, 360.0, 180.0, 1700.0), (8.0, 600.0, 300.0, 1900.0), (0.0, 1000.0, 500.0, 2100.0)],
    [(4.0, 700.0, 350.0, 1900.0), (6.0, 400.0, 200.0, 1800.0), (0.0, 1000.0, 500.0, 2100.0)],
]


@pytest.mark.vid("V-E3-5")
@pytest.mark.parametrize("layers", PROFILES)
def test_dunkin_vs_independent_vertical_fem_with_refinement(layers, record_property):
    model = LayeredModel(layers=layers)
    frequencies = np.geomspace(4.0, 40.0, 7)
    external = phase_disba(model, frequencies, dc_ms=0.005)
    coarse = phase_fem(model, frequencies, points_per_decay=20, depth_decay_lengths=12.0)
    refined = phase_fem(model, frequencies, points_per_decay=40, depth_decay_lengths=16.0)
    expanded = phase_fem(model, frequencies, points_per_decay=40, depth_decay_lengths=22.0)
    assert np.array_equal(external.frequencies_hz, frequencies)
    difference = np.max(abs(refined.velocities_ms - external.velocities_ms) / external.velocities_ms)
    mesh_change = np.max(abs(refined.velocities_ms - coarse.velocities_ms) / refined.velocities_ms)
    domain_change = np.max(abs(expanded.velocities_ms - refined.velocities_ms) / expanded.velocities_ms)
    record_property(
        "forward_comparison",
        {
            "relative_difference": float(difference),
            "mesh_change": float(mesh_change),
            "domain_change": float(domain_change),
            "frequencies_hz": frequencies.tolist(),
            "disba_ms": external.velocities_ms.tolist(),
            "fem_ms": refined.velocities_ms.tolist(),
        },
    )
    assert difference <= 0.005
    assert mesh_change < 0.005
    assert domain_change < 0.001


@pytest.mark.vid("V-E3-6")
def test_layered_high_low_limits_with_frequency_convergence(record_property):
    model = LayeredModel(layers=PROFILES[0])
    frequencies = np.array([0.005, 0.01, 0.02, 200.0, 400.0, 800.0])
    result = phase_disba(model, frequencies, dc_ms=0.001)
    surface = rayleigh_halfspace_velocity(200.0, 1 / 3)
    basement = rayleigh_halfspace_velocity(400.0, 1 / 3)
    error_low = abs(result.velocities_ms[:3] - basement) / basement
    error_high = abs(result.velocities_ms[-3:] - surface) / surface
    record_property(
        "asymptotic_convergence",
        {
            "f_hz": frequencies.tolist(),
            "c_ms": result.velocities_ms.tolist(),
            "low_errors": error_low.tolist(),
            "high_errors": error_high.tolist(),
        },
    )
    assert error_low[0] < error_low[1] < error_low[2]
    assert np.all(error_high < 0.01)
    assert error_low[0] < 0.01


@pytest.mark.vid("V-E3-7")
@pytest.mark.parametrize(
    "kind,severity",
    [
        ("dead", 0.0),
        ("clip", 0.1),
        ("noise", 0.2),
        ("polarity", 1.0),
        ("time_shift", 0.002),
        ("geometry", 0.5),
        ("dt", 0.05),
        ("hum", 0.2),
        ("burst", 0.2),
        ("coupling", 0.5),
        ("jitter", 0.002),
        ("truncation", 0.25),
    ],
)
def test_injection_deterministic_and_preserves_provenance(kind, severity):
    from tests.unit.test_e1 import fixture_shot

    source = fixture_shot(ns=128)
    first = inject_fault(source, kind=kind, channels=(0,), severity=severity, seed=41)
    second = inject_fault(source, kind=kind, channels=(0,), severity=severity, seed=41)
    assert np.array_equal(first.data, second.data, equal_nan=True)
    assert first.headers_json == second.headers_json
    assert np.array_equal(source.data[1:], first.data[1:], equal_nan=True)
    assert not np.array_equal(source.data, first.data, equal_nan=True) or kind in ("geometry", "dt")
