"""Pruebas de E0 v1.4: contratos, planificación y evidencia verificable."""

import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from geoqc.core.config import load_config
from geoqc.core.evidence import canonical_hash, evaluate_gate, seeded_rng
from geoqc.core.models import Acquisition, Geometry, Metric, Shot
from geoqc.core.physics import geophone_response, rayleigh_halfspace_velocity
from geoqc.core.planning import observed_band, planning


def geometry(x=(6.0, 8.0, 10.0)):
    return Geometry(
        xr=x,
        yr=(0.0,) * len(x),
        zr=(0.0,) * len(x),
        xs=0.0,
        ys=0.0,
        zs=0.0,
        uncertainty_m=(0.05,) * len(x),
        crs="local",
        provenance=("fixture",),
    )


def shot(data=None, mask=None):
    return Shot(
        id="shot-1",
        data=np.ones((3, 8)) if data is None else data,
        valid_mask=np.ones((3, 8), dtype=bool) if mask is None else mask,
        mask_reasons=("", "", ""),
        dt_s=(0.001,) * 3,
        t0_s=(-0.1,) * 3,
        geometry=geometry(),
        acquisition=Acquisition(
            technique="MASW", wave="RAYLEIGH", component="Z", receiver_ids=("r1", "r2", "r3"), source_type="hammer"
        ),
        input_hashes=("a" * 64,),
        headers_json='{"GAIN":2}',
    )


@pytest.mark.vid("V-E0-1")
def test_package_importable_and_headless():
    import geoqc.core

    assert geoqc.core.__name__ == "geoqc.core"
    import sys

    assert not any(name.startswith(("PySide6", "pyqtgraph")) for name in sys.modules)


@pytest.mark.vid("V-E0-2")
def test_seed_and_canonical_hash():
    assert np.array_equal(seeded_rng(41).normal(size=100), seeded_rng(41).normal(size=100))
    assert canonical_hash({"b": 2, "a": 1}) == canonical_hash({"a": 1, "b": 2})
    assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})
    with pytest.raises(ValueError):
        canonical_hash({"bad": float("nan")})


@pytest.mark.vid("V-E0-3")
@pytest.mark.parametrize(
    "bad",
    [
        {"id": "M", "unit": "dB", "direction": "higher_is_better", "warn": 5, "fail": 8},
        {"id": "M", "unit": "dB", "direction": "lower_is_better", "warn": 8, "fail": 5},
        {"id": "M", "unit": "dB", "warn": 8, "fail": 5},
        {"id": "M", "unit": "dB", "direction": "higher_is_better", "warn": 8, "fail": 5, "surprise": 1},
    ],
)
def test_invalid_threshold_configuration_rejected(tmp_path, bad):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"schema_version": "1.4", "profile": "vs30_sitio", "metrics": [bad]}))
    with pytest.raises(ValueError):
        load_config(path)


@pytest.mark.vid("V-E0-4")
def test_historical_near_offset_is_not_nacd():
    cfg = load_config(Path("configs/vs30_sitio.yaml"))
    report = planning(cfg, geometry(tuple(6.0 + 2 * j for j in range(24))))
    assert report.nacd_center_at_48m == pytest.approx(29 / 48)
    assert report.near_offset_ratio_at_48m == pytest.approx(6 / 48)
    assert 6 / 0.5 / 2.5 == 4.8
    assert report.status == "NOT_DEMONSTRATED"
    assert not report.eligible_for_acceptance


@pytest.mark.vid("V-E0-5")
def test_favorable_prior_does_not_create_observed_evidence():
    cfg = load_config(Path("configs/vs30_sitio.yaml"))
    report = planning(cfg, geometry())
    assert not report.eligible_for_acceptance
    empty = observed_band((4.0, 8.0), (400.0, 400.0), (False, False), ("MISSING", "MISSING"))
    assert empty.frequencies_hz == ()
    assert empty.nominal_depth_m is None


@pytest.mark.vid("V-E0-6")
@pytest.mark.parametrize("name,target", [("vs30_sitio", 30.0), ("cimentacion_estandar", 15.0)])
def test_draft_profiles_and_band_frontiers(name, target):
    cfg = load_config(Path("configs") / f"{name}.yaml")
    assert cfg.project.z_obj_m == target
    assert planning(cfg, geometry()).status == "NOT_DEMONSTRATED"
    with pytest.raises(ValueError):
        load_config(Path("configs") / f"{name}.yaml", mode="acceptance")
    band = observed_band((4.0, 8.0), (200.0, 160.0), (True, False), ("VALID", "MISSING"), kappa_z=2.5)
    assert band.nominal_depth_m == 20.0
    assert band.frequencies_hz == (4.0,)
    assert not band.eligible_for_acceptance


@pytest.mark.vid("V-E0-7")
def test_holes_and_topography_do_not_get_uniform_aperture():
    g = geometry((6.0, 8.0, 12.0))
    assert g.aperture_m == 6.0
    assert g.uniform_effective_aperture_m is None
    assert g.mean_horizontal_offset_m == pytest.approx(26 / 3)
    with pytest.raises(ValidationError):
        Geometry(
            xr=(0.0, 1.0),
            yr=(0.0,),
            zr=(0.0, 0.0),
            xs=0.0,
            ys=0.0,
            zs=0.0,
            uncertainty_m=(0.0, 0.0),
            crs="local",
            provenance=("f",),
        )


@pytest.mark.vid("V-E0-8")
def test_response_and_nominal_depth_are_conditioned():
    h = geophone_response(np.array([4.5, 3.0, 2.0, 1.5]), 4.5, 0.7)
    assert abs(h[0]) == pytest.approx(1 / 1.4, rel=1e-9)
    assert abs(h[2]) == pytest.approx(0.19452747359242148, rel=1e-12)
    assert abs(h[3]) > 0
    c = rayleigh_halfspace_velocity(180.0, 0.4)
    assert c / (4.5 * 2.5) == pytest.approx(15.07512692986214)
    assert c / (2.0 * 2.5) == pytest.approx(33.919035592189815)
    with pytest.raises(ValueError):
        geophone_response(np.array([1.0]), 0.0, 0.7)


@pytest.mark.vid("V-E0-9")
def test_shot_owns_immutable_data_and_roundtrips():
    source = np.ones((3, 8))
    s = shot(source)
    source[:] = 9.0
    assert np.all(s.data == 1)
    with pytest.raises(ValueError):
        s.data[0, 0] = 2
    with pytest.raises(ValueError):
        s.data.setflags(write=True)
    with pytest.raises(ValidationError):
        s.id = "changed"
    restored = Shot.model_validate_json(s.model_dump_json())
    assert np.array_equal(restored.data, s.data)
    assert restored.headers_json == s.headers_json
    assert restored.t0_s == (-0.1,) * 3


@pytest.mark.vid("V-E0-9")
def test_nan_must_be_masked_and_reason_preserved():
    a = np.ones((3, 8))
    a[0, 0] = np.nan
    with pytest.raises(ValidationError):
        shot(a)
    mask = np.ones((3, 8), dtype=bool)
    mask[0, 0] = False
    with pytest.raises(ValidationError):
        shot(a, mask)
    s = Shot(
        id="bad-channel",
        data=a,
        valid_mask=mask,
        mask_reasons=("CORRUPT_SAMPLE", "", ""),
        dt_s=(0.001,) * 3,
        t0_s=(0.0,) * 3,
        geometry=geometry(),
        acquisition=Acquisition(
            technique="MASW", wave="RAYLEIGH", component="Z", receiver_ids=("r1", "r2", "r3"), source_type="hammer"
        ),
        input_hashes=("a" * 64,),
        headers_json="{}",
    )
    assert json.loads(s.model_dump_json())["data"][0][0] is None
    assert not s.valid_mask[0, 0]


@pytest.mark.vid("V-E0-9")
def test_missing_metric_cannot_claim_valid_pass():
    with pytest.raises(ValidationError):
        Metric(
            id="SNR",
            unit="dB",
            mandatory=True,
            critical=True,
            applicability="APPLICABLE",
            validity="MISSING",
            reason="no pretrigger",
            value=None,
            quality_status="PASS",
        )
    m = Metric(
        id="SNR",
        unit="dB",
        mandatory=True,
        critical=True,
        applicability="APPLICABLE",
        validity="MISSING",
        reason="no pretrigger",
        value=None,
    )
    assert m.quality_status is None


@pytest.mark.vid("V-E0-10")
def test_gate_validates_graph_and_skips_do_not_pass():
    manifest = json.loads(Path("docs/validation_manifest_v1_4.json").read_text(encoding="utf-8"))
    required = manifest["gates"]["G0"]["required_test_ids"]
    results = [{"id": i, "status": "PASSED"} for i in required]
    assert evaluate_gate(manifest, "G0", results) == "PASSED"
    results[0]["status"] = "SKIPPED"
    assert evaluate_gate(manifest, "G0", results) == "INCOMPLETE"
    assert evaluate_gate(manifest, "G0", []) == "INCOMPLETE"
    results[0]["status"] = "FAILED"
    assert evaluate_gate(manifest, "G0", results) == "FAILED"
    manifest["gates"]["G0"]["depends_on"] = ["G1"]
    with pytest.raises(ValueError):
        evaluate_gate(manifest, "G0", results)
