"""Auditoría documental y contrapruebas acotadas; no ejecuta obligaciones RM."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    supplement_path = ROOT / "docs/validation_masw_r1.json"
    supplement = json.loads(supplement_path.read_text(encoding="utf-8"))
    base = json.loads((ROOT / supplement["base_manifest_ref"]).read_text(encoding="utf-8"))
    normative = (ROOT / supplement["normative_ref"]).read_text(encoding="utf-8")
    rows = supplement["obligations"]
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids)) == 8
    assert set(ids) == set(re.findall(r"^\| (RM-\d+) \|", normative, re.MULTILINE))
    base_ids = {row["id"] for row in base["tests"]}
    assert len(base_ids) == 100
    for row in rows:
        assert row["required"] and row["status"] == "NOT_RUN" and row["evidence_refs"] == []
        assert row["base_test_refs"] and set(row["base_test_refs"]) <= base_ids
        assert row["gate_refs"] and set(row["gate_refs"]) <= set(base["gates"])
        assert all(f"### {section} " in normative for section in row["contract_sections"])
    policy = supplement["policy"]
    assert not policy["inherit_base_passed"] and not policy["field_eligible"]
    assert policy["expanded_G5_status"] == "INCOMPLETE"
    assert policy["required_skip_result"] == "INCOMPLETE"
    for relative, expected in supplement["preserved_inputs"].items():
        assert digest(ROOT / relative) == expected, relative

    documents = [
        "SDD_QC_Geofisico_MASW_TRS_v1_4.md",
        "README.md",
        "docs/masw_review_2026_10_12.md",
        "docs/adr/0002-masw-r1.md",
        "docs/revision_v1_4.md",
        "docs/requirements_e5.md",
        "docs/e5_implementation.md",
        "docs/open_questions.md",
    ]
    output_relative = "evidence/masw_r1/document_checks.json"
    links = 0
    for relative in documents:
        path = ROOT / relative
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            if target.startswith(("http:", "https:", "#")):
                continue
            resolved = (path.parent / target.split("#")[0]).resolve()
            if resolved == ROOT / output_relative:
                continue  # Artefacto producido al terminar esta misma ejecución.
            assert resolved.exists(), (relative, target)
            links += 1

    # Contrapruebas analíticas; las tolerancias verifican aritmética, no umbrales de campo.
    rayleigh_ratio = float(np.sqrt(2 - 2 / np.sqrt(3)))
    assert abs(rayleigh_ratio - 0.919401686761966) < 1e-14
    assert not np.isclose(rayleigh_ratio, 1)
    scaled_determinants = [float(np.linalg.det(a * np.eye(2))) for a in (1, 1e-6)]
    assert scaled_determinants[1] < 1e-10  # Matriz invertible pese al determinante pequeño.
    rho = 0.99
    z_independent = 1 / np.sqrt(2)
    z_correlated = 1 / np.sqrt(2 - 2 * rho)
    assert z_independent < 3 < z_correlated  # Umbral ilustrativo, no aprobado para campo.
    heights, velocities = np.array([10.0, 20.0]), np.array([200.0, 400.0])
    travel = np.sum(heights / velocities)
    analytic = 30 * heights / (travel**2 * velocities)
    step = 1e-5
    finite_difference = []
    for i in range(2):
        delta = np.zeros(2)
        delta[i] = step
        finite_difference.append(
            (30 / np.sum(heights / (velocities * np.exp(delta))) - 30 / np.sum(heights / (velocities * np.exp(-delta))))
            / (2 * step)
        )
    np.testing.assert_allclose(finite_difference, analytic, rtol=1e-8, atol=1e-8)

    # Sondas de implementación: registrar lo observado; NO considerar estas brechas aprobadas.
    from geoqc.core.models import DispersionCurve
    from geoqc.masw.contracts import MASWProtocol
    from geoqc.masw.curves import merge_curves
    from geoqc.masw.engineering import parameter_resolution
    from geoqc.qc.contracts import Window

    protocol = MASWProtocol(
        signal=Window(start_s=0, end_s=1),
        frequencies_hz=(8, 16),
        velocities_ms=(100, 200),
        mode_identity="CONFIRMED",
        mode_evidence_ref="unresolved-review-probe",
        provenance="MASW-R1 audit probe",
    )
    common = dict(
        frequencies_hz=(8.0,),
        sigma_ms=(1.0,),
        valid_mask=(True,),
        reasons=("VALID",),
        mode_identity="CONFIRMED",
        band_refs=("same-support",),
    )
    curves = tuple(
        DispersionCurve(
            **common, velocities_ms=(speed,), point_provenance=(f"shot-{i}",), covariance_ref="shared-rho-0.99"
        )
        for i, speed in enumerate((100.0, 101.0))
    )
    merged = merge_curves(curves)
    local = parameter_resolution(np.eye(2), np.eye(2), damping=10)
    np.testing.assert_allclose(local["resolution"], np.eye(2) / 101, rtol=1e-12, atol=1e-14)
    np.testing.assert_allclose(local["covariance"], np.eye(2) / 101**2, rtol=1e-12, atol=1e-14)
    source_files = [
        "geoqc/core/models.py",
        "geoqc/masw/contracts.py",
        "geoqc/masw/curves.py",
        "geoqc/masw/engineering.py",
        "geoqc/synth/dispersion.py",
        "geoqc/masw/report.py",
        "tests/synthetic/test_e5_engineering.py",
        "tests/unit/test_e5_boundaries.py",
        "tests/synthetic/test_e5_curves.py",
    ]
    payload = {
        "id": "MASW-R1-DOCUMENT-REVIEW",
        "specification_version": "1.4",
        "document_revision": "MASW-R1",
        "status": "DOCUMENT_CONSISTENCY_VERIFIED",
        "scope": "Documentos, aritmética y sondas acotadas; no cierre RM/G5/G9",
        "timestamp": datetime.now(UTC).isoformat(),
        "review_date_local": "2026-10-12",
        "versions": {"python": platform.python_version(), "numpy": np.__version__, "platform": platform.platform()},
        "seed": None,
        "input_hashes": {name: digest(ROOT / name) for name in documents + source_files},
        "supplement_hash": digest(supplement_path),
        "validator_hash": digest(Path(__file__)),
        "checks": {
            "base_ids": len(base_ids),
            "additional_obligations": len(ids),
            "local_links": links,
            "preserved_inputs": supplement["preserved_inputs"],
            "all_RM_NOT_RUN": True,
        },
        "counterexamples": {
            "rayleigh_over_vs_nu025": rayleigh_ratio,
            "scaled_identity_determinants": scaled_determinants,
            "correlated_difference_z": float(z_correlated),
            "independent_difference_z": float(z_independent),
            "vs30_logvs_gradient": analytic.tolist(),
            "vs30_gradient_finite_difference": finite_difference,
            "local_noise_variance_damping10": 1 / 101**2,
            "local_posterior_variance_damping10": 1 / 101,
            "local_resolution_damping10": 1 / 101,
        },
        "observed_gaps": {
            "protocol_retains_declared_confirmed": protocol.mode_identity == "CONFIRMED",
            "merge_reports_compatible_without_cross_covariance": merged["points"][0]["compatible_overlap"],
            "merge_retains_covariance_reference": "shared-rho-0.99" in json.dumps(merged),
            "field_acceptance_enabled": merged["eligible_for_acceptance"],
        },
        "implementation_and_field_validation": "NOT_ESTABLISHED_BY_THIS_REVIEW",
        "tolerances": {
            "rayleigh_atol": 1e-14,
            "vs30_gradient_rtol": 1e-8,
            "vs30_gradient_atol": 1e-8,
            "matrix_rtol": 1e-12,
            "matrix_atol": 1e-14,
        },
    }
    (ROOT / output_relative).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"status": payload["status"], "checks": payload["checks"], "observed_gaps": payload["observed_gaps"]},
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
