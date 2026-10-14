"""Verificar G0/G1/G3 juntos, con evidencia vigente y alcance habilitado explícito."""

from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from check_e0 import dependency_check, file_hash, run_check  # noqa: E402

from geoqc.core.evidence import canonical_hash, evaluate_gate, validate_manifest  # noqa: E402
from geoqc.core.revisions import evaluate_supplement, expanded_gates  # noqa: E402


def aggregate(raw: list[dict]) -> list[dict]:
    results = []
    for vid in sorted({item["id"] for item in raw}):
        nodes = [item for item in raw if item["id"] == vid]
        statuses = {item["status"] for item in nodes}
        status = "FAILED" if "FAILED" in statuses else "INCOMPLETE" if statuses != {"PASSED"} else "PASSED"
        results.append({"id": vid, "status": status, "tests": nodes})
    return results


def snapshot() -> dict[str, str]:
    sources = [
        *ROOT.glob("geoqc/**/*.py"),
        *ROOT.glob("tests/**/*.py"),
        *ROOT.glob("tools/*.py"),
        *ROOT.glob("configs/*.yaml"),
        *ROOT.glob("docs/requirements*.md"),
        ROOT / "geoqc/py.typed",
        ROOT / "requirements-win-py312.lock",
        ROOT / "pyproject.toml",
        ROOT / "SDD_QC_Geofisico_MASW_TRS_v1_4.md",
        ROOT / "docs/validation_manifest_v1_4.json",
        ROOT / "docs/e1_e3_implementation.md",
        *ROOT.glob("docs/e2_implementation.md"),
        *ROOT.glob("examples/e2/*"),
        *ROOT.glob("docs/e4_implementation.md"),
        *ROOT.glob("examples/e4/*"),
        *ROOT.glob("requirements-gimli-win-py312.lock"),
        *ROOT.glob("docs/e5_implementation.md"),
        *ROOT.glob("examples/e5/*"),
        *ROOT.glob("docs/e6_implementation.md"),
        *ROOT.glob("examples/e6/*"),
        *ROOT.glob("docs/*masw*r1*"),
        *ROOT.glob("docs/masw_review_*.md"),
        *ROOT.glob("docs/adr/0002*.md"),
    ]
    return {path.relative_to(ROOT).as_posix(): file_hash(path) for path in sorted(sources)}


def gimli_dependencies() -> dict:
    python = ROOT / ".venv-gimli/Scripts/python.exe"
    if not python.is_file():
        return {"status": "FAILED", "reason": "Referencia aislada pyGIMLi ausente"}
    command = [
        str(python),
        "-X",
        "utf8",
        "-c",
        "import json, importlib.metadata as m; print(json.dumps({n:m.version(n) for n in ('numpy','pgcore','pygimli','scooby','setuptools')}))",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
    if completed.returncode != 0:
        return {"status": "FAILED", "reason": completed.stderr}
    versions = json.loads(completed.stdout)
    expected = {
        line.split("==")[0]: line.split("==")[1]
        for line in (ROOT / "requirements-gimli-win-py312.lock").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }
    return {"status": "PASSED" if versions == expected else "FAILED", "versions": versions, "expected": expected}


def main(*, include_common: bool = False, include_trs: bool = False, include_masw: bool = False) -> int:
    include_trs = include_trs or include_masw
    include_common = include_common or include_trs
    manifest = json.loads((ROOT / "docs/validation_manifest_v1_4.json").read_text(encoding="utf-8"))
    validate_manifest(manifest)
    supplement = (
        json.loads((ROOT / "docs/validation_masw_r1.json").read_text(encoding="utf-8")) if include_masw else None
    )
    criteria = json.loads((ROOT / "docs/masw_r1_criteria.json").read_text(encoding="utf-8")) if include_masw else None
    if supplement is not None and criteria is not None:
        required_rm = [row["id"] for row in supplement["obligations"] if row["required"]]
        if len(set(required_rm)) != len(required_rm) or set(criteria["criteria"]) != set(required_rm):
            raise ValueError("Criterios de suplemento incompletos o duplicados")
    before = snapshot()
    env = dict(
        os.environ,
        PYTHONHASHSEED="0",
        PYTHONUTF8="1",
        MPLBACKEND="Agg",
        OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
    )
    with tempfile.TemporaryDirectory(prefix="geoqc-foundation-") as temporary:
        folder = Path(temporary)
        env["GEOQC_TEST_RESULTS"] = str(folder / "tests.json")
        env["COVERAGE_FILE"] = str(folder / ".coverage")
        checks = {
            "dependencies": dependency_check(("dev", "reference")),
            "pytest": run_check(
                [
                    "pytest",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    "--cov=geoqc.io",
                    *(["--cov=geoqc.qc"] if include_common else []),
                    *(["--cov=geoqc.trs"] if include_trs else []),
                    *(["--cov=geoqc.masw"] if include_masw else []),
                    "--cov-report=term-missing",
                    f"--cov-report=json:{folder / 'coverage.json'}",
                ],
                env,
            ),
            "ruff": run_check(["ruff", "check", "geoqc", "tests", "tools"], env),
            "format": run_check(["ruff", "format", "--check", "geoqc", "tests", "tools"], env),
            "mypy": run_check(["mypy", "geoqc"], env),
        }
        if include_trs:
            checks["gimli_dependencies"] = gimli_dependencies()
        raw = (
            json.loads((folder / "tests.json").read_text(encoding="utf-8"))["tests"]
            if (folder / "tests.json").exists()
            else []
        )
        coverage = (
            json.loads((folder / "coverage.json").read_text(encoding="utf-8"))
            if (folder / "coverage.json").exists()
            else None
        )
    after = snapshot()
    checks["source_integrity_during_checks"] = {"status": "PASSED" if before == after else "FAILED"}
    results = aggregate(raw)
    if any(check["status"] != "PASSED" for check in checks.values()):
        for result in results:
            if result["id"] == "V-E0-1":
                result["status"] = "FAILED"
                break
        else:
            results.append({"id": "V-E0-1", "status": "FAILED", "tests": []})
    gates = {gate: evaluate_gate(manifest, gate, results) for gate in manifest["gates"]}
    # Los casos E6 actuales verifican un motor diagnóstico parcial. Descubrir sus
    # marcadores no acredita registro operativo ni integración completa E6/E8.
    for gate in ("G6", "G7", "G8", "G9", "G10"):
        if gates[gate] != "FAILED":
            gates[gate] = "INCOMPLETE"
    io_files = (
        {}
        if coverage is None
        else {name: entry for name, entry in coverage["files"].items() if "/io/" in name.replace("\\", "/")}
    )
    io_statements = sum(entry["summary"]["num_statements"] for entry in io_files.values())
    io_covered = sum(entry["summary"]["covered_lines"] for entry in io_files.values())
    io_percentage = 100 * io_covered / io_statements if io_statements else None
    coverage_status = "INCOMPLETE" if io_percentage is None else "PASSED" if io_percentage >= 90 else "FAILED"
    if gates["G1"] == "PASSED" and coverage_status != "PASSED":
        gates["G1"] = coverage_status
    # Propagar condición adicional de G1 a todos sus descendientes.
    if gates["G1"] != "PASSED":
        for gate in ("G2", "G4", "G5", "G6", "G7", "G8", "G9", "G10"):
            if gates[gate] != "FAILED":
                gates[gate] = "INCOMPLETE"
    versions = {
        # Las versiones se registran tras evaluar pruebas y cobertura base.
        name: importlib.metadata.version(name)
        for name in (
            "geoqc",
            "numpy",
            "scipy",
            "pydantic",
            "pytest",
            "hypothesis",
            "ruff",
            "mypy",
            "disba",
            "obspy",
            "numba",
            "llvmlite",
            "coverage",
            "pytest-cov",
        )
    }
    base_gates = dict(gates)
    supplement_execution = None
    if supplement is not None and criteria is not None:
        supplement_hash = after["docs/validation_masw_r1.json"]
        protocol_hash = canonical_hash(
            {
                key: after[key]
                for key in (
                    "docs/requirements_masw_r1.md",
                    "docs/masw_r1_criteria.json",
                    "docs/masw_review_2026_10_12.md",
                )
            }
        )
        code_hash = canonical_hash(after)
        envelope = {
            "document_revision": "MASW-R1",
            "supplement_hash": supplement_hash,
            "protocol_hash": protocol_hash,
            "code_hash": code_hash,
            "pytest_exit_code": checks["pytest"]["exit_code"],
            "tests": raw,
        }
        rm_results = evaluate_supplement(
            envelope,
            criteria["criteria"],
            supplement_hash=supplement_hash,
            protocol_hash=protocol_hash,
            code_hash=code_hash,
        )
        if any(check["status"] != "PASSED" for check in checks.values()):
            rm_results = {key: "INCOMPLETE" if state == "PASSED" else state for key, state in rm_results.items()}
        gates = expanded_gates(base_gates, manifest, rm_results, required_rm)
        supplement_execution = {
            **envelope,
            "criteria": criteria["criteria"],
            "results": rm_results,
            "trust_boundary": "OUTPUT_OF_THIS_RUNNER_NOT_IMPORTED_REPORT_FLAGS",
        }
    payload = {
        "schema_version": "1.4",
        "id": "MASW-G0-G1-G2-G3-G4-G5"
        if include_masw
        else "TRS-G0-G1-G2-G3-G4"
        if include_trs
        else "COMMON-G0-G1-G2-G3"
        if include_common
        else "FOUNDATION-G0-G1-G3",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "document_revision": "MASW-R1" if include_masw else None,
        "scope": "IMPLEMENTATION_AND_DECLARED_SYNTHETIC_DOMAIN_ONLY",
        "eligible_for_field_acceptance": False,
        "decision_scope": {
            "status": "DIAGNOSTIC_IMPLEMENTATION_ONLY",
            "gate_credit": "INCOMPLETE",
            "pending": ["trusted_operational_registry", "complete_MASW_R1_E6_E8_integration"],
        },
        "versions": {"python": platform.python_version(), **versions},
        "reference_environment": checks.get("gimli_dependencies"),
        "platform": platform.platform(),
        "input_sha256": after,
        "scientific_code_and_inputs_digest": canonical_hash(after),
        "rng": {"algorithm": "PCG64", "fixture_seed": 41, "hypothesis_derandomize": True, "pythonhashseed": 0},
        "enabled_scope": {
            "formats": [
                "SEG-Y rev0 IBM32",
                "SEG-Y rev1 IBM32/IEEE32; big/little endian; known extension count",
                "SEG-2 rev1 codes 1/2/4/5; big/little endian; explicit sidecar",
            ],
            "not_enabled": ["miniSEED", "SEG-D", "SEG-Y rev2/2.1", "SEG-2 code3", "SEG-Y extension count -1"],
            "dispersion": {
                "model": "isotropic elastic horizontal layers, fundamental Rayleigh",
                "comparison_profiles": 3,
                "band_hz": [4.0, 40.0],
                "model_mismatch_and_nearfield": "NOT_VALIDATED",
            },
            "common_qc": None
            if not include_common
            else {
                "protocol_ref": "docs/requirements_e2.md",
                "obligation_ids": [f"V-E2-{j}" for j in range(1, 11)],
                "field_calibration": "NOT_VALIDATED",
                "snr_realizations_per_stratum": 500,
                "snr_strata": 15,
                "fault_corpus_realizations": 1200,
                "lag_accuracy_domain": "ANALYTIC_NOISELESS_GAUSSIAN_MODULATED_PULSE_10_100_HZ",
                "ambiguous_dt_geometry_without_external_reference": "NOT_IDENTIFIABLE",
            },
        },
        "checks": checks,
        "trs_scope": None
        if not include_trs
        else {
            "protocol_ref": "docs/requirements_e4.md",
            "holdout_picks": 6000,
            "scenario_corpus": 300,
            "inversion": "horizontal two-layer parametric; diagonal known errors",
            "coverage": "2D rectangular Siddon polylines; independent local linear resolution",
            "forward_reference": "isolated pyGIMLi Dijkstra; spatial/angular refinement separated",
            "not_enabled": [
                "field calibration",
                "arbitrary 2D nonlinear inversion acceptance",
                "unique hidden-layer detection",
                "topographic ray tracing",
            ],
            "performance_threads": {"OMP_NUM_THREADS": 1, "OPENBLAS_NUM_THREADS": 1, "MKL_NUM_THREADS": 1},
        },
        "coverage_io": {
            "status": coverage_status,
            "minimum_percent": 90,
            "actual_percent": io_percentage,
            "modules": {} if coverage is None else {name: entry["summary"] for name, entry in io_files.items()},
        },
        "coverage_common_qc": None
        if not include_common or coverage is None
        else {name: entry["summary"] for name, entry in coverage["files"].items() if "/qc/" in name.replace("\\", "/")},
        "results": results,
        "masw_scope": None
        if not include_masw
        else {
            "transform": "phase shift with signed directions; actual support/kernel; diagnostic bands",
            "uncertainty": "declared complex-Gaussian spectral domain; empirical error covariance/holdout",
            "null": "IID equal phases N12/24/48 and declared colored correlated maximum domain",
            "nearfield": "full P/S/R axisymmetric homogeneous halfspace Gaussian normal surface source only",
            "layered_nearfield": "UNCALIBRATED",
            "real_field_noise": "UNCALIBRATED; no real array-noise corpus in workspace",
            "vs30": "independent FEM/disba discrete synthetic ensembles; not G9 profile qualification",
            "field_acceptance": False,
        },
        "coverage_masw": None
        if not include_masw or coverage is None
        else {
            name: entry["summary"] for name, entry in coverage["files"].items() if "/masw/" in name.replace("\\", "/")
        },
        "coverage_trs": None
        if not include_trs or coverage is None
        else {
            name: entry["summary"] for name, entry in coverage["files"].items() if "/trs/" in name.replace("\\", "/")
        },
        "gates": gates,
        "base_gates": base_gates,
        "supplement_execution": supplement_execution,
        "summary": {
            "test_cases": len(raw),
            "validated_obligation_ids": len(results),
            "skipped_test_cases": sum(item["status"] == "SKIPPED" for item in raw),
        },
    }
    directory = ROOT / (
        "evidence/e5"
        if include_masw
        else "evidence/e4"
        if include_trs
        else "evidence/e2"
        if include_common
        else "evidence/e1_e3"
    )
    directory.mkdir(parents=True, exist_ok=True)
    if include_masw:
        runs = ROOT / "evidence/masw_r1/runs"
        runs.mkdir(parents=True, exist_ok=True)
        directory = Path(tempfile.mkdtemp(prefix=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-"), dir=runs))
    execution = directory / "execution.json"
    execution.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    artifact_hash = file_hash(execution)
    enabled_gates = (
        ("G0", "G1", "G2", "G3", "G4", "G5")
        if include_masw
        else ("G0", "G1", "G2", "G3", "G4")
        if include_trs
        else ("G0", "G1", "G2", "G3")
        if include_common
        else ("G0", "G1", "G3")
    )
    for gate in enabled_gates:
        document = {
            "schema_version": "1.4",
            "id": gate,
            "document_revision": payload["document_revision"],
            "status": gates[gate],
            "required_test_ids": manifest["gates"][gate]["required_test_ids"],
            "required_supplement_ids": required_rm if include_masw and gate == "G5" else [],
            "base_status": base_gates[gate],
            "execution_artifact": "execution.json",
            "execution_artifact_sha256": artifact_hash,
            "scope": payload["scope"],
            "eligible_for_field_acceptance": False,
            "coverage_io": payload["coverage_io"] if gate == "G1" else None,
            "coverage_common_qc": payload["coverage_common_qc"] if gate == "G2" else None,
            "coverage_trs": payload["coverage_trs"] if gate == "G4" else None,
            "coverage_masw": payload["coverage_masw"] if gate == "G5" else None,
            "masw_scope": payload["masw_scope"] if gate == "G5" else None,
        }
        (directory / f"{gate}.json").write_text(
            json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
    for result in results:
        artifact = {
            "schema_version": "1.4",
            "specification_version": "1.4",
            **result,
            "execution_artifact": "execution.json",
            "execution_artifact_sha256": artifact_hash,
            "input_sha256": after,
            "versions": payload["versions"],
            "rng": payload["rng"],
        }
        (directory / f"{result['id']}.json").write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "gates": {gate: gates[gate] for gate in enabled_gates},
                "base_gates": {gate: base_gates[gate] for gate in enabled_gates},
                "supplement": None if supplement_execution is None else supplement_execution["results"],
                "execution_artifact": str(execution.relative_to(ROOT)),
                "io_coverage_percent": io_percentage,
                **payload["summary"],
            },
            indent=2,
        )
    )
    return 0 if all(gates[gate] == "PASSED" for gate in enabled_gates) else 1


if __name__ == "__main__":
    raise SystemExit(main())
