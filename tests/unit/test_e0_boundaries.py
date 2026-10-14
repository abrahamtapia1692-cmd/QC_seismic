"""Casos que evitan aprobar E0 solo con escenarios nominales."""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from geoqc.core.config import Threshold, load_config
from geoqc.core.evidence import canonical_hash, evaluate_gate, seeded_rng, validate_manifest
from geoqc.core.models import ArrivalPick, Coverage, DispersionCurve, Geometry, IngestFailure, Metric, QCReport
from geoqc.core.physics import geophone_response, wavelengths_m
from geoqc.core.planning import observed_band, planning


def threshold(direction="higher_is_better"):
    return {
        "id": "snr_db",
        "unit": "dB",
        "direction": direction,
        "warn": 8.0 if direction == "higher_is_better" else 5.0,
        "fail": 5.0 if direction == "higher_is_better" else 8.0,
        "boundary": "inclusive",
        "mandatory": True,
        "critical": True,
        "calibration_state": "UNVALIDATED",
    }


def geom(n=24, dx=2.0, offset=6.0, **overrides):
    payload = {
        "xr": tuple(offset + j * dx for j in range(n)),
        "yr": (0.0,) * n,
        "zr": (0.0,) * n,
        "xs": 0.0,
        "ys": 0.0,
        "zs": 0.0,
        "uncertainty_m": (0.05,) * n,
        "crs": "local-SI",
        "provenance": ("fixture",),
    }
    return Geometry(**(payload | overrides))


@pytest.mark.vid("V-E0-1")
def test_installed_package_imports_outside_workspace(tmp_path):
    result = subprocess.run(
        [sys.executable, "-I", "-c", "import geoqc, geoqc.core;print(geoqc.__version__)"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    from geoqc import __version__

    assert result.stdout.strip() == __version__


@pytest.mark.vid("V-E0-1")
def test_cli_plan_exports_diagnostic_scenario(tmp_path):
    geometry_path = tmp_path / "geometry.json"
    geometry_path.write_text(geom().model_dump_json(), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "geoqc",
            "plan",
            "--config",
            "configs/vs30_sitio.yaml",
            "--geometry",
            str(geometry_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    assert body["status"] == "NOT_DEMONSTRATED"
    assert body["eligible_for_acceptance"] is False


@pytest.mark.vid("V-E0-2")
def test_array_hash_preserves_shape_dtype_and_normalizes_endianness():
    x = np.arange(6, dtype="<f8").reshape(2, 3)
    assert canonical_hash(x) == canonical_hash(x.astype(">f8"))
    assert canonical_hash(x) != canonical_hash(x.reshape(3, 2))
    assert canonical_hash(x) != canonical_hash(x.astype(np.float32))
    tag = {"__array__": x.dtype.str, "shape": list(x.shape), "hex": x.tobytes().hex()}
    assert canonical_hash(x) != canonical_hash(tag)
    with pytest.raises(ValueError):
        canonical_hash(np.array([np.inf]))


@pytest.mark.vid("V-E0-2")
@pytest.mark.parametrize("seed", [-1, True, 1.5, 2**64])
def test_invalid_seed_not_silently_coerced(seed):
    with pytest.raises(ValueError):
        seeded_rng(seed)


@pytest.mark.vid("V-E0-3")
@pytest.mark.parametrize("direction", ["higher_is_better", "lower_is_better"])
def test_threshold_values_at_inclusive_boundaries(direction):
    rule = Threshold(**threshold(direction))
    toward_pass = np.inf if direction == "higher_is_better" else -np.inf
    toward_warn = np.inf if direction == "higher_is_better" else -np.inf
    assert rule.diagnostic_classification(rule.warn) == "WARN"
    assert rule.diagnostic_classification(rule.fail) == "FAIL"
    assert rule.diagnostic_classification(np.nextafter(rule.warn, toward_pass)) == "PASS"
    assert rule.diagnostic_classification(np.nextafter(rule.fail, toward_warn)) == "WARN"


@pytest.mark.vid("V-E0-3")
@pytest.mark.parametrize(
    "key,value",
    [
        ("warn", 4.0),
        ("boundary", "undefined"),
        ("direction", "unknown"),
        ("id", "unknown_detector"),
        ("calibration_state", "CALIBRATED"),
        ("surprise", 1),
    ],
)
def test_complete_threshold_rejects_each_single_invalid_field(key, value):
    with pytest.raises(ValidationError):
        Threshold(**(threshold() | {key: value}))


@pytest.mark.vid("V-E0-3")
@pytest.mark.parametrize("key", ["direction", "warn", "fail", "boundary", "unit", "mandatory", "calibration_state"])
def test_complete_threshold_rejects_each_missing_operational_field(key):
    payload = threshold()
    del payload[key]
    with pytest.raises(ValidationError):
        Threshold(**payload)


@pytest.mark.vid("V-E0-3")
@pytest.mark.parametrize(
    "suffix,body",
    [
        ("yaml", "profile: vs30_sitio\nprofile: cimentacion_estandar\n"),
        ("json", '{"profile":"vs30_sitio","profile":"cimentacion_estandar"}'),
    ],
)
def test_duplicate_config_keys_rejected(tmp_path, suffix, body):
    path = tmp_path / f"duplicate.{suffix}"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicada"):
        load_config(path)


@pytest.mark.vid("V-E0-4")
def test_two_historical_arithmetic_values_do_not_change_center_definition():
    assert 6 / 0.5 / 2.5 == 4.8
    assert 6 / 0.25 / 2.5 == 9.6
    cfg = load_config(Path("configs/vs30_sitio.yaml"))
    report = planning(cfg, geom())
    assert report.aperture_m == 46.0
    assert report.uniform_effective_aperture_m == 48.0
    assert report.nacd_center_at_48m == pytest.approx(29 / 48)
    assert report.near_offset_ratio_at_48m == 0.125


@pytest.mark.vid("V-E0-6")
def test_array_design_changes_have_competing_effects():
    cfg = load_config(Path("configs/vs30_sitio.yaml"))
    original = planning(cfg, geom())
    wide = planning(cfg, geom(dx=4.0))
    longer = planning(cfg, geom(n=48))
    farther = planning(cfg, geom(offset=12.0))
    assert wide.aperture_m > original.aperture_m
    assert wide.scenario_uniform_nyquist_frequency_hz == original.scenario_uniform_nyquist_frequency_hz / 2
    assert longer.aperture_m > original.aperture_m
    assert longer.scenario_uniform_nyquist_frequency_hz == original.scenario_uniform_nyquist_frequency_hz
    assert (
        farther.scenario_near_offset_ratio_at_band_edges[0] == original.scenario_near_offset_ratio_at_band_edges[0] * 2
    )
    assert all(report.status == "NOT_DEMONSTRATED" for report in (original, wide, longer, farther))


@pytest.mark.vid("V-E0-6")
@pytest.mark.parametrize("name", ["vs30_sitio", "cimentacion_estandar"])
def test_band_edges_and_target_frontier_are_exact_scenario_relations(name):
    cfg = load_config(Path(f"configs/{name}.yaml"))
    report = planning(cfg, geom())
    for f, wavelength in zip(
        report.scenario_frequency_band_hz, report.scenario_wavelengths_at_band_edges_m, strict=True
    ):
        assert wavelength * f == pytest.approx(report.nominal_phase_velocity_ms)
    assert (
        report.nominal_phase_velocity_ms / report.scenario_max_frequency_for_target_hz / cfg.planning.kappa_z
        == pytest.approx(cfg.project.z_obj_m)
    )
    assert not report.eligible_for_acceptance


@pytest.mark.vid("V-E0-7")
@pytest.mark.parametrize("overrides", [{"yr": (0.0, 1.0, 0.0)}, {"zr": (0.0, 0.1, 0.0)}, {"xr": (6.0, 8.0, 12.0)}])
def test_irregular_geometry_has_no_uniform_kernel(overrides):
    assert geom(n=3, **overrides).uniform_effective_aperture_m is None


@pytest.mark.vid("V-E0-8")
def test_complex_response_asymptotes_and_subnatural_band_states():
    response = geophone_response((0.0, 4.5, 4.5e7), 4.5, 0.7)
    assert response[0] == 0j
    assert response[1] == pytest.approx(1j / 1.4)
    assert response[2] == pytest.approx(1.0, abs=2e-7)
    valid = observed_band((2.0,), (169.595177960949,), (True,), ("VALID",))
    unknown = observed_band((2.0,), (169.595177960949,), (False,), ("UNCALIBRATED_RESPONSE",))
    assert valid.nominal_depth_m == pytest.approx(33.9190355921898)
    assert unknown.nominal_depth_m is None
    assert unknown.source_valid_mask == (False,)
    assert valid.eligible_for_acceptance is False


@pytest.mark.vid("V-E0-8")
def test_response_remains_finite_when_direct_frequency_squares_overflow():
    response = geophone_response((0.0, 1e308), 4.5, 0.7)
    assert np.all(np.isfinite(response))
    assert response[1] == pytest.approx(1.0)


@pytest.mark.vid("V-E0-5")
def test_unrepresentable_wavelength_is_rejected():
    with pytest.raises(ValueError, match="representable"):
        wavelengths_m((1e-308,), (1e308,))


@pytest.mark.vid("V-E0-5")
@pytest.mark.parametrize("f,c", [((0.0,), (100.0,)), ((1.0,), (np.inf,)), ((1.0, 2.0), (100.0,))])
def test_shared_wavelength_utility_validates_physical_inputs(f, c):
    with pytest.raises(ValueError):
        wavelengths_m(f, c)


@pytest.mark.vid("V-E0-9")
def test_pick_curve_coverage_and_failure_contracts_roundtrip():
    pick = ArrivalPick(
        onset_s=0.025,
        sigma_s=0.001,
        bias_s=0.0,
        confidence="UNCALIBRATED",
        reason="laboratory",
        window_s=(0.0, 0.1),
        interval_s=(0.023, 0.027),
        preprocessing_ref="raw",
    )
    curve = DispersionCurve(
        frequencies_hz=(2.0, 4.0),
        velocities_ms=(200.0, 180.0),
        sigma_ms=(None, 5.0),
        valid_mask=(False, True),
        reasons=("UNCALIBRATED", "VALID"),
        point_provenance=("s1", "s1"),
        mode_identity="UNKNOWN",
    )
    coverage = Coverage(
        roi_ref="roi",
        mesh_ref="mesh",
        topography_ref="survey",
        ray_model_ref="straight",
        hits=(0, 1),
        dws_m=(0.0, 2.0),
        angular_span_degrees=(None, 0.0),
        anisotropy=(None, 1.0),
        resolved_mask=(False, False),
        limitations=("single direction",),
    )
    failure = IngestFailure(
        path="missing.seg2", data_hash=None, error_code="NOT_FOUND", reason="absent", action_ids=("LOCATE",)
    )
    for model in (pick, curve, coverage, failure):
        assert type(model).model_validate_json(model.model_dump_json()) == model
    with pytest.raises(ValidationError):
        ArrivalPick(**(pick.model_dump() | {"confidence": "MISSING"}))
    with pytest.raises(ValidationError):
        Coverage(**(coverage.model_dump() | {"resolved_mask": (True, False)}))


@pytest.mark.vid("V-E0-9")
def test_report_preserves_incomplete_evidence_and_blocks_acceptance():
    metric = Metric(
        id="SNR",
        unit="dB",
        mandatory=True,
        critical=True,
        applicability="UNKNOWN",
        validity="MISSING",
        reason="no pretrigger",
    )
    report = QCReport(
        scope="shot",
        metrics=(metric,),
        quality_status=None,
        evidence_status="INCOMPLETE",
        missing_requirement_ids=("REQ-E0-DATA",),
        satisfied_requirement_ids=(),
        config_hash="a" * 64,
        data_hashes=(),
        code_hash="b" * 64,
        calibration_refs=(),
        evidence_refs=(),
    )
    assert not report.eligible_for_acceptance
    for invalid in (
        {"quality_status": "PASS"},
        {"evidence_status": "COMPLETE"},
        {"diagnostic_mode": False},
        {"operator_decision": "ACCEPTED"},
    ):
        with pytest.raises(ValidationError):
            QCReport(**(report.model_dump() | invalid))


@pytest.mark.vid("V-E0-10")
def test_manifest_matches_plan_and_unknown_or_duplicate_results_rejected():
    import re

    manifest = json.loads(Path("docs/validation_manifest_v1_4.json").read_text(encoding="utf-8"))
    body = Path("SDD_QC_Geofisico_MASW_TRS_v1_4.md").read_text(encoding="utf-8")
    ids = set(re.findall(r"^- \*\*(V-E\d+-\d+[a-z]?):", body, re.MULTILINE))
    assert len(ids) == len(manifest["tests"]) == 100
    assert ids == {test["id"] for test in manifest["tests"]}
    validate_manifest(manifest)
    valid = {"id": "V-E0-1", "status": "PASSED"}
    for results in ([valid, valid], [{"id": "UNKNOWN", "status": "PASSED"}]):
        with pytest.raises(ValueError):
            evaluate_gate(manifest, "G0", results)
    required = manifest["gates"]["G0"]["required_test_ids"]
    results = [{"id": vid, "status": "PASSED"} for vid in required]
    assert evaluate_gate(manifest, "G1", results) == "INCOMPLETE"
    manifest["tests"].append(manifest["tests"][0])
    with pytest.raises(ValueError):
        validate_manifest(manifest)
