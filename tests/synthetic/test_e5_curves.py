import numpy as np
import pytest

from geoqc.core.models import DispersionCurve
from geoqc.masw.contracts import MASWProtocol
from geoqc.masw.curves import contiguous_bands, merge_curves, near_ratios, repeatability, ridge_path
from geoqc.masw.report import masw_diagnostics
from geoqc.masw.transform import phase_shift
from geoqc.qc.contracts import Window
from geoqc.synth.dispersion import phase_disba
from tests.synthetic.e5_support import FAMILIES, shot


@pytest.mark.vid("V-E5-7")
def test_ridge_grid_prior_sensitivity_does_not_create_observations(record_property):
    f, x = np.array([8.0, 12.0, 16.0, 24.0, 32.0]), np.arange(24) * 2
    truth = np.array([300.0, 275.0, 240.0, 205.0, 190.0])
    signal = np.exp(-2j * np.pi * f[:, None] * x / truth[:, None])
    rows = []
    for step in (2.0, 1.0, 0.5):
        c = np.arange(150, 351, step)
        scores = phase_shift(signal, f, x, c)["coherence"]
        for prior in (0.0, 0.02, 100.0):
            indices = ridge_path(scores, f, c, penalty=prior)
            error = float(np.sqrt(np.mean(((c[list(indices)] - truth) / truth) ** 2)))
            rows.append(
                {
                    "grid_step_ms": step,
                    "penalty": prior,
                    "rms_relative": error,
                    "curve_ms": c[list(indices)].tolist(),
                    "mode_identity": "APPARENT",
                }
            )
            if prior == 0:
                assert error < 0.01
    assert rows[-1]["rms_relative"] > rows[-3]["rms_relative"]
    record_property("ridge_prior_grid", {"study": rows, "prior_infers_missing_band": False})


@pytest.mark.vid("V-E5-7")
@pytest.mark.parametrize("snr_db", [10, 20])
def test_three_families_observable_fundamental_and_missing_identity(snr_db, record_property):
    rng = np.random.default_rng(6700 + snr_db)
    f, x, c = np.arange(8, 33, 2), np.arange(24) * 2, np.arange(80, 701, 0.5)
    rows = []
    for model in FAMILIES:
        truth = phase_disba(model, f).velocities_ms
        observable = truth / f >= 2.5 * 2
        signal = np.exp(-2j * np.pi * f[:, None] * x / truth[:, None])
        errors = []
        for _ in range(20):
            noise = (rng.normal(size=signal.shape) + 1j * rng.normal(size=signal.shape)) / np.sqrt(
                2 * 10 ** (snr_db / 10)
            )
            score = phase_shift(signal + noise, f, x, c)["coherence"]
            path = ridge_path(score, f, c, penalty=0.0001)
            errors.append(
                float(np.sqrt(np.mean(((c[list(path)][observable] - truth[observable]) / truth[observable]) ** 2)))
            )
        assert max(errors) < (0.06 if snr_db == 10 else 0.03)
        rows.append(
            {
                "model": model.model_dump(mode="json"),
                "snr_db": snr_db,
                "rms_relative": errors,
                "observable_mask": observable.tolist(),
                "observability": "lambda>=2.5dx declared synthetic domain",
            }
        )
    # Datos observados de un modo cualquiera no confirman fundamental.
    time = np.arange(2000) * 0.001
    higher_only = np.cos(2 * np.pi * 16 * (time[None, :] - x[:, None] / 300))
    protocol = MASWProtocol(
        signal=Window(start_s=0, end_s=2),
        frequencies_hz=(16, 20),
        velocities_ms=(200, 250, 300, 350),
        provenance="fundamental absent",
    )
    result = masw_diagnostics(shot(higher_only, x=x), protocol)
    assert all(row["mode_identity"] != "CONFIRMED" for row in result["curves"])
    assert not result["eligible_for_acceptance"]
    record_property("observable_curves", rows)


@pytest.mark.vid("V-E5-8")
def test_modal_amplitudes_separability_and_apparent_mode(record_property):
    x, f = np.arange(24) * 2, np.array([20.0, 24.0])
    c = np.arange(100, 501)
    rows = []
    for c1 in (300, 165):
        u0 = np.exp(-2j * np.pi * f[:, None] * x / 160)
        u1 = 2 * np.exp(-2j * np.pi * f[:, None] * x / c1)
        scores = phase_shift(u0 + u1, f, x, c)["coherence"]
        apparent = c[np.argmax(scores, axis=1)]
        rows.append(
            {
                "c0": 160,
                "c1": c1,
                "true_A1_over_A0": 2,
                "apparent_ms": apparent.tolist(),
                "coherence_at_c0": scores[:, 60].tolist(),
                "coherence_at_c1": scores[:, c1 - 100].tolist(),
                "identity": "APPARENT",
                "modal_energy_inferred": False,
            }
        )
        if c1 == 300:
            assert np.max(abs(apparent - c1) / c1) < 0.03
        else:
            assert np.all((apparent >= 160) & (apparent <= 165))
    record_property("mode_ambiguity", rows)


@pytest.mark.vid("V-E5-9")
def test_near_ratios_do_not_create_observed_support():
    ratios = near_ratios(6 + np.arange(24) * 2, [48])
    assert ratios["near_offset_ratio"] == pytest.approx([0.125])
    assert ratios["NACD_center"] == pytest.approx([0.6041666666666666])
    bands = contiguous_bands([8, 12, 16, 24, 32], np.array([False, True, True, False, False]), max_gap_hz=4.1)
    assert bands[0]["f_bounds_hz"] == [12, 16]
    assert all("depth" not in key for key in ratios)


@pytest.mark.vid("V-E5-13")
def test_repeatability_on_common_support_and_confounded_causes(record_property):
    rng = np.random.default_rng(713)
    reference = np.array([180, 200, 240])
    repeats = reference + rng.normal(0, 2, (100, 3))
    result = repeatability(repeats)
    assert max(result["repeatability_cov"]) < 0.02
    assert result["precision_cov"] is None and len(result["cause_candidates"]) > 1
    source_and_mode_shift = repeatability(np.array([reference, reference * 1.08]))
    assert min(source_and_mode_shift["repeatability_cov"]) > 0.05
    record_property("repeatability", {**result, "confounded_shift": source_and_mode_shift})


@pytest.mark.vid("V-E5-19")
def test_octaves_and_disjoint_segments():
    complete = contiguous_bands([8, 12, 16, 24, 32], np.ones(5, dtype=bool), max_gap_hz=8.1)
    assert complete[0]["octaves"] == 2
    gaps = contiguous_bands([8, 12, 16, 24, 32], np.array([True, True, False, True, True]), max_gap_hz=8.1)
    assert len(gaps) == 2 and max(row["octaves"] for row in gaps) < 1


def curve(f, c, mode="CONFIRMED", support="site-A"):
    return DispersionCurve(
        frequencies_hz=f,
        velocities_ms=c,
        sigma_ms=(2.0,) * len(f),
        valid_mask=(True,) * len(f),
        reasons=("VALID",) * len(f),
        mode_identity=mode,
        point_provenance=tuple(f"shot:{x}" for x in f),
        band_refs=(support,),
    )


@pytest.mark.vid("V-E5-22")
def test_union_preserves_holes_modes_support_and_conflicts():
    left = curve((8, 12), (180, 190))
    right = curve((24, 32), (220, 230))
    result = merge_curves((left, right))
    assert [row["frequency_hz"] for row in result["points"]] == [8, 12, 24, 32]
    assert result["interpolated_points"] == [] and not result["eligible_for_acceptance"]
    incompatible = curve((12, 16), (240, 250), support="site-B")
    joined = merge_curves((left, incompatible))
    overlap = joined["points"][1]
    assert not overlap["compatible_overlap"] and len(overlap["contributions"]) == 2
    different_mode = curve((12, 16), (190, 200), mode="APPARENT")
    assert not merge_curves((left, different_mode))["points"][1]["compatible_overlap"]
