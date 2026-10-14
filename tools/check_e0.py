"""Ejecutar G0 y escribir evidencia derivada, sin promover gates posteriores."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoqc.core.evidence import evaluate_gate, validate_manifest  # noqa: E402
from geoqc.core.physics import (  # noqa: E402
    geophone_response,
    kappa2_from_nu,
    rayleigh_cubic,
    rayleigh_halfspace_velocity,
    rayleigh_radical_residual,
    rayleigh_ratio,
    rayleigh_xi,
)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_check(arguments: list[str], env: dict[str, str]) -> dict:
    command = [sys.executable, "-m", *arguments]
    completed = subprocess.run(
        command, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    print(completed.stdout, end="")
    print(completed.stderr, end="", file=sys.stderr)
    return {
        "command": ["python", "-m", *arguments],
        "exit_code": completed.returncode,
        "status": "PASSED" if completed.returncode == 0 else "FAILED",
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def dependency_check(extra_groups: tuple[str, ...] = ("dev",)) -> dict:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    problems = []
    expressions = list(project["dependencies"])
    for group in extra_groups:
        expressions.extend(project["optional-dependencies"][group])
    for expression in expressions:
        requirement = Requirement(expression)
        actual = importlib.metadata.version(requirement.name)
        if actual not in requirement.specifier:
            problems.append(f"{requirement.name}=={actual} no satisface {requirement.specifier}")
    for line in (ROOT / "requirements-win-py312.lock").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            name, expected = line.split("==")
            actual = importlib.metadata.version(name)
            if actual != expected:
                problems.append(f"Lock: {name}=={expected}, instalado {actual}")
    return {"status": "FAILED" if problems else "PASSED", "problems": problems}


def analytic_metrics() -> dict:
    nus = np.linspace(-0.999, 0.5, 301)
    xis = [rayleigh_xi(float(nu)) for nu in nus]
    polynomial = [abs(rayleigh_cubic(xi, kappa2_from_nu(float(nu)))) for xi, nu in zip(xis, nus, strict=True)]
    radical = [abs(rayleigh_radical_residual(xi, kappa2_from_nu(float(nu)))) for xi, nu in zip(xis, nus, strict=True)]
    closed_form = 2 - 2 / np.sqrt(3.0)
    c = rayleigh_halfspace_velocity(180.0, 0.4)
    return {
        "rayleigh_ratios": {str(nu): rayleigh_ratio(nu) for nu in (0.0, 0.25, 0.3, 0.4, 0.45, 0.5)},
        "closed_form_xi_nu025_absolute_error": abs(rayleigh_xi(0.25) - closed_form),
        "max_cubic_residual": max(polynomial),
        "max_equivalent_radical_residual": max(radical),
        "sampled_nu_domain": [-0.999, 0.5],
        "sample_count": 301,
        "nominal_depth_m_vs180_nu04_kappa25": {"f4_5": c / (4.5 * 2.5), "f2": c / (2.0 * 2.5)},
        "normalized_geophone_amplitudes_fn4_5_damping07": {
            str(f): float(abs(h))
            for f, h in zip((4.5, 3.0, 2.0, 1.5), geophone_response((4.5, 3.0, 2.0, 1.5), 4.5, 0.7), strict=True)
        },
        "tolerances_used_by_tests": {
            "closed_form_xi_absolute": 1e-13,
            "alternative_root_absolute": 1e-9,
            "auxetic_alternative_root_absolute": 1e-11,
            "radical_absolute": 1e-10,
            "rounded_literature_absolute": 1e-4,
            "rounded_regression_absolute": 1e-5,
        },
        "scope": "Referencia analítica; no calibración ni validación de campo",
    }


def main() -> int:
    manifest_path = ROOT / "docs/validation_manifest_v1_4.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_manifest(manifest)
    env = dict(os.environ, PYTHONHASHSEED="0", PYTHONUTF8="1")
    with tempfile.TemporaryDirectory(prefix="geoqc-e0-") as temporary:
        raw_path = Path(temporary) / "results.json"
        env["GEOQC_TEST_RESULTS"] = str(raw_path)
        checks = {
            "dependencies": dependency_check(),
            "pytest": run_check(
                [
                    "pytest",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    "tests/unit/test_e0.py",
                    "tests/unit/test_e0_boundaries.py",
                    "tests/unit/test_rayleigh_halfspace.py",
                ],
                env,
            ),
            "ruff": run_check(["ruff", "check", "geoqc", "tests", "tools"], env),
            "format": run_check(["ruff", "format", "--check", "geoqc", "tests", "tools"], env),
            "mypy": run_check(["mypy", "geoqc"], env),
        }
        raw = json.loads(raw_path.read_text(encoding="utf-8")) if raw_path.exists() else {"tests": []}
    results = []
    for vid in sorted({item["id"] for item in raw["tests"]}):
        nodes = [item for item in raw["tests"] if item["id"] == vid]
        statuses = {item["status"] for item in nodes}
        status = "FAILED" if "FAILED" in statuses else "INCOMPLETE" if statuses != {"PASSED"} else "PASSED"
        results.append({"id": vid, "status": status, "tests": nodes})
    # Herramientas forman parte de V-E0-1; pytest puede fallar incluso en colección.
    if any(check["status"] != "PASSED" for check in checks.values()):
        for result in results:
            if result["id"] == "V-E0-1":
                result["status"] = "FAILED"
                break
        else:
            results.append({"id": "V-E0-1", "status": "FAILED", "tests": []})
    gates = {gate: evaluate_gate(manifest, gate, results) for gate in manifest["gates"]}
    versions = {
        name: importlib.metadata.version(name)
        for name in (
            "geoqc",
            "numpy",
            "scipy",
            "pydantic",
            "PyYAML",
            "pytest",
            "hypothesis",
            "ruff",
            "mypy",
            "types-PyYAML",
        )
    }
    sources = sorted(
        [
            *ROOT.glob("geoqc/**/*.py"),
            *ROOT.glob("tests/**/*.py"),
            Path(__file__),
            ROOT / "tools/lock_environment.py",
            ROOT / "geoqc/py.typed",
            ROOT / "pyproject.toml",
            ROOT / "requirements-win-py312.lock",
            *ROOT.glob("configs/*.yaml"),
            ROOT / "docs/requirements_v1_4.md",
            ROOT / "SDD_QC_Geofisico_MASW_TRS_v1_4.md",
            manifest_path,
        ]
    )
    hashes = {path.relative_to(ROOT).as_posix(): file_hash(path) for path in sources}
    payload = {
        "schema_version": "1.4",
        "id": "G0",
        "status": gates["G0"],
        "scope": "E0_IMPLEMENTATION_ONLY",
        "eligible_for_field_acceptance": False,
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "versions": {"python": platform.python_version(), **versions},
        "platform": platform.platform(),
        "rng": {"algorithm": "PCG64", "fixture_seed": 41, "hypothesis_derandomize": True, "pythonhashseed": 0},
        "input_sha256": hashes,
        "checks": checks,
        "analytic_metrics": analytic_metrics(),
        "results": results,
        "gates": gates,
        "summary": {
            "test_cases": len(raw["tests"]),
            "validated_obligation_ids": len(results),
            "skipped_test_cases": sum(item["status"] == "SKIPPED" for item in raw["tests"]),
        },
    }
    directory = ROOT / "evidence/e0"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "G0.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    gate_hash = file_hash(directory / "G0.json")
    for result in results:
        artifact = {
            "schema_version": "1.4",
            "specification_version": "1.4",
            **result,
            "scope": "E0_IMPLEMENTATION_ONLY",
            "gate_artifact": "G0.json",
            "gate_artifact_sha256": gate_hash,
            "input_sha256": hashes,
            "versions": payload["versions"],
            "rng": payload["rng"],
            "timestamp_utc": payload["timestamp_utc"],
        }
        (directory / f"{result['id']}.json").write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
    print(json.dumps({"G0": gates["G0"], **payload["summary"]}, indent=2))
    return 0 if gates["G0"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
