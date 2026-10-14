"""Evidencia reproducible de casos E6 diagnósticos, sin acreditar cierre G6."""

from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from check_e0 import run_check  # noqa: E402
from check_foundation import aggregate, snapshot  # noqa: E402

from geoqc.core.evidence import canonical_hash  # noqa: E402


def main() -> int:
    runs = ROOT / "evidence/e6/runs"
    runs.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-"), dir=runs))
    before = snapshot()
    env = dict(
        os.environ,
        PYTHONHASHSEED="0",
        PYTHONUTF8="1",
        OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        GEOQC_TEST_RESULTS=str(directory / "tests.json"),
        COVERAGE_FILE=str(directory / ".coverage"),
    )
    checks = {
        "pytest": run_check(
            [
                "pytest",
                "tests/unit/test_e6.py",
                "-q",
                "-p",
                "no:cacheprovider",
                "--cov=geoqc.decision",
                "--cov-report=term-missing",
                f"--cov-report=json:{directory / 'coverage.json'}",
            ],
            env,
        ),
        "ruff": run_check(
            [
                "ruff",
                "check",
                "geoqc/decision",
                "geoqc/cli.py",
                "tests/unit/test_e6.py",
                "tools/check_decision.py",
                "tools/create_decision_demo.py",
                "tools/check_foundation.py",
            ],
            env,
        ),
        "format": run_check(
            [
                "ruff",
                "format",
                "--check",
                "geoqc/decision",
                "geoqc/cli.py",
                "tests/unit/test_e6.py",
                "tools/check_decision.py",
                "tools/create_decision_demo.py",
                "tools/check_foundation.py",
            ],
            env,
        ),
        "mypy": run_check(["mypy", "geoqc"], env),
    }
    after = snapshot()
    checks["source_integrity"] = {"status": "PASSED" if before == after else "FAILED"}
    raw_path = directory / "tests.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))["tests"] if raw_path.exists() else []
    coverage_path = directory / "coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8")) if coverage_path.exists() else None
    percent = None if coverage is None else coverage["totals"]["percent_covered"]
    checks["coverage"] = {
        "status": "PASSED" if percent is not None and percent >= 85 else "FAILED",
        "minimum_percent": 85,
        "actual_percent": percent,
    }
    cases = aggregate(raw)
    expected = {f"V-E6-{i}" for i in range(1, 7)}
    checks["required_cases"] = {
        "status": "PASSED"
        if {r["id"] for r in cases} == expected and all(r["status"] == "PASSED" for r in cases)
        else "FAILED"
    }
    status = "PASSED" if all(check["status"] == "PASSED" for check in checks.values()) else "FAILED"
    payload = {
        "id": "E6_DIAGNOSTIC_IMPLEMENTATION",
        "specification_version": "1.4",
        "document_revision": "MASW-R1",
        "status": status,
        "timestamp": datetime.now(UTC).isoformat(),
        "scope": "PARTIAL_E6_DIAGNOSTIC_CASES_ONLY",
        "gate_status": "INCOMPLETE",
        "gate": "G6",
        "eligible_for_acceptance": False,
        "pending": ["G5 expanded MASW-R1", "trusted operational registry", "complete E6/E8 integration", "G9"],
        "input_hashes": after,
        "code_hash": canonical_hash(after),
        "config_hash": canonical_hash({"threads": 1, "coverage_minimum": 85}),
        "protocol_ref": "docs/requirements_e6.md",
        "seed": None,
        "randomness": "No stochastic cases in E6 rule tests",
        "platform": platform.platform(),
        "versions": {
            "python": platform.python_version(),
            **{
                name: importlib.metadata.version(name)
                for name in ("numpy", "scipy", "pydantic", "pytest", "ruff", "mypy")
            },
        },
        "checks": checks,
        "implemented_cases": cases,
        "metrics": {
            "test_cases": len(raw),
            "skips": sum(r["status"] == "SKIPPED" for r in raw),
            "coverage_percent": percent,
        },
        "tolerances": {"rules": "exact", "coverage_minimum_percent": 85},
        "artifact_refs": ["tests.json", "coverage.json"],
    }
    (directory / "execution.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": status,
                "G6": "INCOMPLETE",
                "execution_artifact": str(directory.relative_to(ROOT)),
                **payload["metrics"],
            },
            indent=2,
        )
    )
    # Éxito del comando significa casos diagnósticos aprobados, nunca cierre G6.
    return 0 if status == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
