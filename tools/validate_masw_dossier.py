"""Evidencia de ejecución de pruebas del dosier; no acredita gates científicos."""

import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parent = ROOT / "evidence/masw_quality/validation"
    parent.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="run-", dir=parent))
    files = [
        ROOT / "tools/report_masw_quality.py",
        ROOT / "tools/tests/test_masw_dossier.py",
        Path(__file__),
        ROOT / "docs/requirements_masw_dossier.md",
        *sorted((ROOT / "geoqc").rglob("*.py")),
    ]
    before = {p.relative_to(ROOT).as_posix(): digest(p) for p in files}
    env = dict(
        os.environ,
        PYTHONUTF8="1",
        PYTHONHASHSEED="0",
        OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
    )
    commands = {
        "pytest": ["pytest", "tools/tests", "-q", f"--junitxml={output / 'pytest.xml'}"],
        "ruff": [
            "ruff",
            "check",
            "tools/report_masw_quality.py",
            "tools/tests/test_masw_dossier.py",
            "tools/validate_masw_dossier.py",
        ],
        "format": [
            "ruff",
            "format",
            "--check",
            "tools/report_masw_quality.py",
            "tools/tests/test_masw_dossier.py",
            "tools/validate_masw_dossier.py",
        ],
    }
    checks = {}
    for name, command in commands.items():
        run = subprocess.run(
            [sys.executable, "-m", *command],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        (output / f"{name}.txt").write_text(run.stdout + run.stderr, encoding="utf-8")
        checks[name] = {"exit_code": run.returncode, "artifact_ref": f"{name}.txt"}
        print(run.stdout[-600:])
    cases = []
    if (output / "pytest.xml").exists():
        for node in ElementTree.parse(output / "pytest.xml").iter("testcase"):
            status = (
                "FAILED"
                if node.find("failure") is not None or node.find("error") is not None
                else "SKIPPED"
                if node.find("skipped") is not None
                else "PASSED"
            )
            cases.append({"id": node.attrib["classname"] + "/" + node.attrib["name"], "status": status})
    stable = before == {p.relative_to(ROOT).as_posix(): digest(p) for p in files}
    passed = (
        stable
        and bool(cases)
        and all(c["status"] == "PASSED" for c in cases)
        and all(c["exit_code"] == 0 for c in checks.values())
    )
    evidence = {
        "id": "MASW_DOSSIER_EXERCISE",
        "specification_version": "1.4",
        "status": "PASSED" if passed else "FAILED",
        "timestamp": datetime.now(UTC).isoformat(),
        "scope": "DIAGNOSTIC_REPORT_IMPLEMENTATION_NOT_G5_G6_G9",
        "input_hashes": before,
        "source_stable": stable,
        "checks": checks,
        "tests": cases,
        "metrics": {"cases": len(cases), "skipped": sum(c["status"] == "SKIPPED" for c in cases)},
        "tolerances": {"plane_velocity_error_ms": 1, "planar_coherence_min": 0.999},
        "seed": None,
        "versions": {"python": platform.python_version()},
        "platform": platform.platform(),
        "artifact_refs": ["pytest.xml", "pytest.txt", "ruff.txt", "format.txt"],
        "eligible_for_acceptance": False,
    }
    (output / "execution.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": evidence["status"], "cases": len(cases), "path": str(output)}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
