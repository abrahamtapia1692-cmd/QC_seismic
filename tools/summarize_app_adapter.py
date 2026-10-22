"""Archive selected JUnit reports and an E5 dossier; does not run or approve gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoqc.io.readers import read_shot  # noqa: E402
from geoqc.masw.adapter import (  # noqa: E402
    MASWAdapterInput,
    ReceiverExclusion,
    build_masw_dossier,
    capture_engine_reference,
)
from geoqc.masw.contracts import MASWProtocol  # noqa: E402
from geoqc.masw.diagnostic_quality import UsabilityPolicy  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def report_counts(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    counts = {key: sum(int(suite.get(key, "0")) for suite in suites)
              for key in ("tests", "failures", "errors", "skipped")}
    counts["passed"] = counts["tests"] - sum(counts[key] for key in ("failures", "errors", "skipped"))
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    base = ROOT / "evidence/app_local/adapter"
    parser.add_argument("--application-report", type=Path, default=base / "application_tests_final.xml")
    parser.add_argument("--core-report", type=Path, default=base / "core_regression_tests_final.xml")
    args = parser.parse_args()
    counts = {"application": report_counts(args.application_report), "core_regression": report_counts(args.core_report)}
    failures = any(item["failures"] or item["errors"] for item in counts.values())
    incomplete = any(item["tests"] == 0 or item["skipped"] for item in counts.values())
    status = "FAILED" if failures else "INCOMPLETE" if incomplete else "PASSED"
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = base / "runs" / f"{stamp}_{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(args.application_report, output / "application_tests.xml")
    shutil.copyfile(args.core_report, output / "core_regression_tests.xml")
    shot = read_shot(ROOT / "examples/e5/masw_plane.sgy")
    reference = capture_engine_reference()
    request = MASWAdapterInput(
        acquisition_revision_id="local-e5-revision-1",
        shots=(shot,),
        protocol=MASWProtocol.model_validate_json((ROOT / "examples/e5/protocol.json").read_bytes()),
        usability_policy=UsabilityPolicy.model_validate_json((ROOT / "configs/masw_usability_v1.json").read_bytes()),
        sensitivity_exclusions=(ReceiverExclusion(shot_id=shot.id, receiver_id="r0"),),
        engine_reference=reference,
    )
    result = build_masw_dossier(request)
    (output / "e5_dossier.json").write_text(result.to_json() + "\n", encoding="utf-8")
    files = [
        ROOT / "tools/report_masw_quality.py", ROOT / "tools/tests/test_masw_adapter.py",
        ROOT / "tools/tests/test_masw_extraction_regression.py",
        ROOT / "tools/tests/test_masw_dossier.py", ROOT / "tools/tests/test_masw_usability.py",
        Path(__file__), ROOT / "tests/fixtures/app_adapter/oysand_before_extraction.json",
        ROOT / "examples/e5/masw_plane.sgy", ROOT / "examples/e5/masw_plane.sgy.json",
        ROOT / "examples/e5/protocol.json", ROOT / "configs/masw_usability_v1.json",
        ROOT / "tests/unit/test_e1_cli.py", ROOT / "tests/unit/test_e5_boundaries.py",
        ROOT / "tests/unit/test_masw_r1.py", ROOT / "tests/synthetic/test_e5_pipeline.py",
        ROOT / "tests/synthetic/test_e5_transform.py", ROOT / "tests/synthetic/test_e5_curves.py",
        ROOT / "tests/synthetic/e5_support.py", ROOT / "tests/conftest.py",
    ]
    summary = {
        "scope": "APP_LOCAL_ADAPTER_AND_SELECTED_REGRESSIONS_ONLY",
        "status": status,
        "counts": counts,
        "scientific_gates_evaluated": False,
        "backend_or_worker_service_tested": False,
        "source_binding": "Hashes captured when archiving reports; this collector does not attest test execution code",
        "engine_reference": reference.model_dump(mode="json"),
        "input_and_test_hashes": {path.relative_to(ROOT).as_posix(): digest(path) for path in files},
        "artifact_hashes": {path.name: digest(path) for path in output.iterdir() if path.is_file()},
        "e5_scientific_digest": result.scientific_digest,
        "documented_core_regression_thread_limits": {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"},
    }
    (output / "validation.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output": output.relative_to(ROOT).as_posix(), "status": status, "counts": counts}))
    return 0 if status == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
