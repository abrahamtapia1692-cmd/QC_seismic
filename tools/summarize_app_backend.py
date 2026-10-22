"""Archive an executed backend JUnit report and provenance without credentials."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import sys
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoqc_app.config import Settings  # noqa: E402
from geoqc_app.db import Database  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def installed_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, action="append")
    parser.add_argument("--config", type=Path, default=ROOT / ".local/backend.json")
    parser.add_argument("--example-dossier", type=Path)
    parser.add_argument("--scope", choices=("LOCAL_BACKEND_RECOVERY", "LOCAL_UPLOAD_LIFECYCLE", "LOCAL_DOSSIER_EXPORTS",
                                           "LOCAL_DOSSIER_DETAIL", "LOCAL_WEB_CLIENT", "LOCAL_TRS_CLIENT"),
                        default="LOCAL_BACKEND_RECOVERY")
    args = parser.parse_args()
    reports = args.report or [ROOT / "evidence/app_local/backend_recovery_tests.xml"]
    suites = []
    for path in reports:
        report = ET.parse(path).getroot()
        suites.extend([report] if report.tag == "testsuite" else list(report.iter("testsuite")))
    totals = {key: sum(int(suite.get(key, "0")) for suite in suites)
              for key in ("tests", "failures", "errors", "skipped")}
    if totals["tests"] < 1 or any(totals[key] for key in ("failures", "errors", "skipped")):
        raise ValueError("El reporte debe contener casos ejecutados sin fallos, errores ni skips")
    with Database(Settings.load(args.config)).connect() as conn:
        postgres = conn.execute("SHOW server_version").fetchone()
    sources = sorted((ROOT / "geoqc_app").rglob("*.py")) + sorted((ROOT / "geoqc_app/sql").glob("*.sql"))
    sources += [ROOT / "tools/tests/test_app_backend.py", ROOT / "tools/tests/test_app_exports.py",
                ROOT / "tools/tests/test_app_dossiers.py",
                ROOT / "pyproject.toml", Path(__file__)]
    if args.scope in ("LOCAL_WEB_CLIENT", "LOCAL_TRS_CLIENT"):
        sources += [ROOT / "tools/tests/test_app_web.py"] + sorted((ROOT / "geoqc_app/web").glob("*"))
    if args.scope == "LOCAL_TRS_CLIENT":
        sources += sorted((ROOT / "geoqc").rglob("*.py"))
        sources += [ROOT / "tools/tests/test_app_trs.py", ROOT / "tools/tests/test_km_demo.py",
                    ROOT / "tools/tests/test_prepare_km_app.py", ROOT / "tools/build_km_demo.py",
                    ROOT / "tools/prepare_km_app.py"]
        sources += sorted((ROOT / "examples/km_app/demo_trs_f1").glob("*"))
    captured = datetime.now(UTC)
    folder = ROOT / "evidence/app_local/backend/runs" / (captured.strftime("%Y%m%dT%H%M%SZ_") + uuid.uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    archived = []
    for index, report_path in enumerate(reports):
        name = "tests.xml" if index == 0 else f"tests_{index + 1}.xml"
        shutil.copyfile(report_path, folder / name)
        archived.append({"file": name, "sha256": digest(folder / name)})
    screenshots = []
    if args.scope == "LOCAL_WEB_CLIENT":
        for name in ("web_desktop.png", "web_mobile.png"):
            screenshot = ROOT / "evidence/app_local" / name
            if screenshot.exists():
                shutil.copyfile(screenshot, folder / name)
                screenshots.append({"file": name, "sha256": digest(folder / name)})
    examples = None
    if args.example_dossier is not None:
        from geoqc_app.render_exports import render_export, renderer_reference
        source_bytes = args.example_dossier.read_bytes()
        source_document = json.loads(source_bytes)
        artifacts = []
        for format in ("CSV", "HTML", "PDF"):
            name = ("trs_snapshot." if source_document.get("method") == "TRS" else "e5_snapshot.") + format.lower()
            (folder / name).write_bytes(render_export(source_document, format))
            artifacts.append({"file": name, "sha256": digest(folder / name),
                              "renderer_reference": renderer_reference(format)})
        examples = {"scope": "SUPPLIED_SCIENTIFIC_SNAPSHOT_NOT_DATABASE_PUBLICATION",
                    "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
                    "scientific_digest": source_document["scientific_digest"], "artifacts": artifacts}
    document = {
        "captured_at_utc": captured.isoformat(), "scope": args.scope,
        "note": "Archives an existing test report; source hashes are captured now, not proof of test execution provenance.",
        "test_totals": totals, "report_sha256": digest(folder / "tests.xml"), "reports": archived,
        "export_examples": examples,
        "screenshots": screenshots,
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        "postgresql": postgres["server_version"] if postgres else None,
                        "packages": {name: installed_version(name) for name in
                                     ("fastapi", "starlette", "psycopg", "psutil", "httpx2", "reportlab", "pypdf",
                                      "playwright")}},
        "sources_sha256": {path.relative_to(ROOT).as_posix(): digest(path) for path in sources},
        "remaining": ["PostgreSQL restart and storage power loss", "Temporary/attempt cleanup",
                      "Measured resource limits", "Integrated acceptance closure"],
    }
    (folder / "execution.json").write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(folder.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
