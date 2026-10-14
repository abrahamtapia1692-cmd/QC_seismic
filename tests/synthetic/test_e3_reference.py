import numpy as np
import pytest

from geoqc.synth.eikonal import fast_marching
from geoqc.synth.faults import inject_fault
from geoqc.synth.trs import gradient_time
from geoqc.synth.wavelets import apply_causal_geophone, causal_pulse
from tests.unit.test_e1 import fixture_shot


@pytest.mark.vid("V-E3-2")
def test_gradient_against_independent_eikonal_mesh_and_domain_convergence(record_property):
    expected = gradient_time((0.0, 0.0), (20.0, 0.0), v0=1000.0, gradient=100.0)
    measured = []
    for h in (0.5, 0.25, 0.125):
        x, z = np.arange(-5.0, 25.0 + h / 2, h), np.arange(0.0, 10.0 + h / 2, h)
        speed = np.broadcast_to((1000.0 + 100.0 * z)[:, None], (z.size, x.size))
        grid = fast_marching(speed, spacing_m=h, source_ij=(0, round(5 / h)), origin_xz_m=(-5.0, 0.0))
        measured.append(grid.at((20.0, 0.0)))
    errors = abs(np.array(measured) - expected) / expected
    h = 0.125
    x, z = np.arange(-10.0, 30.0 + h / 2, h), np.arange(0.0, 20.0 + h / 2, h)
    expanded = fast_marching(
        np.broadcast_to((1000.0 + 100.0 * z)[:, None], (z.size, x.size)),
        spacing_m=h,
        source_ij=(0, 80),
        origin_xz_m=(-10.0, 0.0),
    )
    domain_change = abs(expanded.at((20.0, 0.0)) - measured[-1]) / expected
    record_property(
        "eikonal_convergence",
        {
            "grid_h_m": [0.5, 0.25, 0.125],
            "analytic_time_s": expected,
            "fmm_time_s": measured,
            "relative_errors": errors.tolist(),
            "expanded_domain_relative_change": domain_change,
        },
    )
    assert errors[2] < errors[1] < errors[0]
    assert errors[2] < 0.01
    assert domain_change < 0.001


@pytest.mark.vid("V-E3-1")
def test_source_and_instrument_keep_causal_onset_truth():
    time = np.arange(-0.1, 0.5, 0.001)
    pulse = causal_pulse(time, 20.0, onset_s=0.03)
    processed = apply_causal_geophone(pulse, time, fn_hz=4.5, damping=0.7)
    assert np.all(processed.samples[time < 0.03] == 0)
    assert processed.analytic_onset_s == 0.03
    assert processed.first_nonzero_sample_s == pulse.first_nonzero_sample_s
    assert processed.processing


@pytest.mark.vid("V-E3-5")
def test_farfield_ifft_padding_and_rejection_of_wrapped_arrivals(record_property):
    from geoqc.synth.dispersion import PhaseCurve
    from geoqc.synth.farfield import farfield_waveform
    from geoqc.synth.wavelets import ricker

    time = np.arange(4000) * 0.001 - 0.2
    source = ricker(time, 20.0)
    curve = PhaseCurve(
        frequencies_hz=np.array([4.0, 10.0, 20.0, 40.0]),
        velocities_ms=np.full(4, 200.0),
        method="exact homogeneous scenario",
        numerical_settings=("constant",),
    )
    result = farfield_waveform(
        source,
        dt_s=0.001,
        offsets_m=(100.0, 200.0),
        branches=(curve,),
        modal_amplitudes=(1.0,),
        quality_factors=(None,),
        padding_tolerance=0.005,
    )
    assert np.isrealobj(result.data)
    assert result.data.shape == (2, 4000)
    assert result.padding_relative_change <= 0.005
    record_property(
        "ifft_padding",
        {
            "fft_samples": result.fft_samples,
            "previous_fft_samples": result.previous_fft_samples,
            "relative_change": result.padding_relative_change,
            "tolerance": 0.005,
        },
    )
    with pytest.raises(ValueError, match="PADDING_BUDGET"):
        farfield_waveform(
            source, dt_s=0.001, offsets_m=(1e6,), branches=(curve,), modal_amplitudes=(1.0,), quality_factors=(None,)
        )


@pytest.mark.vid("V-E3-7")
def test_fault_strengths_checked_by_separate_measurements_and_combinations():
    shot = fixture_shot(ns=256)
    noise = inject_fault(shot, kind="noise", channels=(0,), severity=0.2, seed=41)
    assert np.sqrt(np.mean((noise.data[0] - shot.data[0]) ** 2)) == pytest.approx(0.2, abs=1e-12)
    clipped = inject_fault(shot, kind="clip", channels=(0,), severity=0.1, seed=41)
    assert np.max(abs(clipped.data[0])) == 0.1
    assert np.any(abs(shot.data[0]) > 0.1)
    polarity = inject_fault(shot, kind="polarity", channels=(0,), severity=1.0, seed=41)
    assert np.allclose(polarity.data[0], -shot.data[0])
    dt = inject_fault(shot, kind="dt", channels=(0,), severity=0.05, seed=41)
    assert dt.dt_s[0] == pytest.approx(shot.dt_s[0] * 1.05)
    geometry = inject_fault(shot, kind="geometry", channels=(0,), severity=0.5, seed=41)
    assert geometry.geometry.xr[0] - shot.geometry.xr[0] == 0.5
    amplitude = inject_fault(shot, kind="coupling", channels=(0,), severity=0.5, seed=41)
    assert np.std(amplitude.data[0]) / np.std(shot.data[0]) == 0.5
    combo = inject_fault(noise, kind="polarity", channels=(0,), severity=1.0, seed=41)
    assert np.allclose(combo.data[0], -noise.data[0])
    ramp = np.arange(256, dtype=float)[None, :]
    from geoqc.core.models import Shot

    one = fixture_shot(n=1, ns=256)
    one = Shot.model_validate(one.model_dump() | {"data": ramp})
    shifted = inject_fault(one, kind="time_shift", channels=(0,), severity=0.002, seed=41)
    assert np.array_equal(shifted.data[0, 2:], one.data[0, :-2])
    truncated = inject_fault(shot, kind="truncation", channels=(0,), severity=0.25, seed=41)
    assert np.sum(~truncated.valid_mask[0]) == 64
