import numpy as np
import pytest

from geoqc.synth.dispersion import LayeredModel, PhaseCurve, phase_disba, phase_fem
from geoqc.synth.eikonal import fast_marching
from geoqc.synth.faults import inject_fault
from geoqc.synth.trs import gradient_time, two_layer_times
from geoqc.synth.wavelets import noise_at_snr, ricker
from tests.unit.test_e1 import fixture_shot


@pytest.mark.vid("V-E3-2")
@pytest.mark.parametrize(
    "v1,v2,h,r",
    [
        (0.0, 1000.0, 5.0, (1.0,)),
        (1000.0, 500.0, 5.0, (1.0,)),
        (500.0, 500.0, 5.0, (1.0,)),
        (500.0, 1000.0, 0.0, (1.0,)),
        (500.0, 1000.0, 5.0, (-1.0,)),
        (500.0, np.nan, 5.0, (1.0,)),
    ],
)
def test_two_layer_domain_rejected(v1, v2, h, r):
    with pytest.raises(ValueError):
        two_layer_times(r, v1, v2, h)


@pytest.mark.vid("V-E3-2")
def test_eikonal_limits_and_boundaries_are_explicit():
    with pytest.raises(ValueError):
        fast_marching(np.zeros((3, 3)), spacing_m=1.0, source_ij=(0, 0))
    grid = fast_marching(np.full((3, 3), 1000.0), spacing_m=1.0, source_ij=(0, 0))
    assert grid.at((2.0, 0.0)) == 0.002
    with pytest.raises(ValueError):
        grid.at((4.0, 0.0))
    with pytest.raises(ValueError):
        grid.at((0.5, 0.0))
    with pytest.raises(ValueError):
        gradient_time((0.0, -1.0), (1.0, 0.0), v0=1000.0, gradient=50.0)


@pytest.mark.vid("V-E3-5")
@pytest.mark.parametrize(
    "layers", [[], [(5.0, 400.0, 200.0, 1800.0)], [(0.0, 400.0, 400.0, 1800.0)], [(0.0, 0.0, 200.0, 1800.0)]]
)
def test_layered_reference_elastic_domain(layers):
    with pytest.raises(ValueError):
        LayeredModel(layers=layers)


@pytest.mark.vid("V-E3-5")
def test_external_forward_missing_points_rejected(monkeypatch):
    from types import SimpleNamespace

    import disba

    def factory(*args, **kwargs):
        return lambda periods, **kwargs: SimpleNamespace(period=periods[:-1], velocity=np.ones(periods.size - 1))

    monkeypatch.setattr(disba, "PhaseDispersion", factory)
    with pytest.raises(ValueError, match="perdió puntos"):
        phase_disba(LayeredModel(layers=[(0.0, 400.0, 200.0, 1800.0)]), np.array([4.0, 8.0]))


@pytest.mark.vid("V-E3-5")
def test_fem_semispace_independent_closed_form_and_refinement(record_property):
    from geoqc.core.physics import rayleigh_halfspace_velocity

    model = LayeredModel(layers=[(0.0, 400.0, 200.0, 1800.0)])
    expected = rayleigh_halfspace_velocity(200.0, 1 / 3)
    values = [float(phase_fem(model, (10.0,), points_per_decay=ppd).velocities_ms[0]) for ppd in (10, 20, 40)]
    errors = abs(np.asarray(values) - expected) / expected
    record_property(
        "fem_halfspace",
        {
            "points_per_decay": [10, 20, 40],
            "c_ms": values,
            "analytic_c_ms": expected,
            "relative_errors": errors.tolist(),
        },
    )
    assert errors[2] < errors[1] < errors[0]
    assert errors[2] < 0.005
    with pytest.raises(ValueError):
        phase_fem(model, (10.0,), points_per_decay=2)


@pytest.mark.vid("V-E3-1")
@pytest.mark.parametrize("case", ["dc", "nan", "bad_kind", "alias", "unrepresentable_snr"])
def test_noise_unknown_and_invalid_inputs_rejected(case):
    signal = np.tile(ricker(np.arange(-0.1, 0.1, 0.001), 20.0), (2, 1))
    kwargs = {"snr_db": 6.0, "seed": 41}
    if case == "dc":
        signal[:] = 1.0
    elif case == "nan":
        signal[0, 0] = np.nan
    elif case == "bad_kind":
        kwargs["kind"] = "unknown"
    elif case == "alias":
        kwargs.update(kind="hum", dt_s=0.1)
    else:
        kwargs["snr_db"] = 1e308
    with pytest.raises(ValueError):
        noise_at_snr(signal, **kwargs)


@pytest.mark.vid("V-E3-7")
def test_fault_constraints_and_missing_valid_data():
    shot = fixture_shot()
    with pytest.raises(ValueError):
        inject_fault(shot, kind="unknown", channels=(0,), severity=0.1, seed=41)
    with pytest.raises(ValueError):
        inject_fault(shot, kind="noise", channels=(10,), severity=0.1, seed=41)
    with pytest.raises(ValueError):
        inject_fault(shot, kind="truncation", channels=(0,), severity=1.0, seed=41)
    with pytest.raises(ValueError):
        inject_fault(shot, kind="hum", channels=(0,), severity=0.1, frequency_hz=600.0, seed=41)
    dead = inject_fault(shot, kind="dead", channels=(0,), severity=0.0, seed=41)
    assert not dead.valid_mask[0].any()
    assert dead.mask_reasons[0] == "INJECTED_DEAD"


@pytest.mark.vid("V-E3-5")
def test_farfield_modal_sum_and_propagation_delay_are_checked():
    from geoqc.synth.farfield import farfield_waveform

    curve = PhaseCurve(
        frequencies_hz=np.array([4.0, 10.0, 20.0, 40.0]),
        velocities_ms=np.full(4, 200.0),
        method="analytic halfspace",
        numerical_settings=("constant",),
    )
    source = ricker(np.arange(4000) * 0.001 - 0.2, 20.0)
    single = farfield_waveform(
        source,
        dt_s=0.001,
        offsets_m=(100.0, 110.0),
        branches=(curve,),
        modal_amplitudes=(1.0,),
        quality_factors=(None,),
        padding_tolerance=0.005,
    )
    summed = farfield_waveform(
        source,
        dt_s=0.001,
        offsets_m=(100.0, 110.0),
        branches=(curve, curve),
        modal_amplitudes=(1.0, 2.0),
        quality_factors=(None, None),
        padding_tolerance=0.005,
    )
    assert np.allclose(summed.data, single.data * 3, rtol=1e-12, atol=1e-12)
    assert np.allclose(
        single.data[0, :-50] * np.sqrt(100.0), single.data[1, 50:] * np.sqrt(110.0), rtol=1e-10, atol=1e-12
    )
