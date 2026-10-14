"""Registrar resultados reales por obligación, incluidos setup/teardown y skips."""

import json
import os
from pathlib import Path

import pytest

ITEMS: dict[str, str] = {}
REPORTS: dict[str, dict[str, str]] = {}
PROPERTIES: dict[str, list] = {}
SUPPLEMENT: dict[str, list] = {}


def pytest_collection_modifyitems(items):
    manifest = json.loads(Path("docs/validation_manifest_v1_4.json").read_text(encoding="utf-8"))
    known = {test["id"] for test in manifest["tests"]}
    for item in items:
        markers = list(item.iter_markers("vid"))
        if len(markers) != 1 or len(markers[0].args) != 1 or markers[0].args[0] not in known:
            raise pytest.UsageError(f"Cada test necesita un vid vigente único: {item.nodeid}")
        ITEMS[item.nodeid] = markers[0].args[0]
        supplemental = list(item.iter_markers("rm"))
        for marker in supplemental:
            if len(marker.args) != 2 or marker.args[0] not in {f"RM-{i:02}" for i in range(1, 9)}:
                raise pytest.UsageError(f"Marcador RM inválido: {item.nodeid}")
        SUPPLEMENT[item.nodeid] = [list(marker.args) for marker in supplemental]


def pytest_runtest_logreport(report):
    REPORTS.setdefault(report.nodeid, {})[report.when] = report.outcome
    if report.user_properties:
        PROPERTIES[report.nodeid] = list(report.user_properties)


def pytest_sessionfinish(session, exitstatus):
    target = os.environ.get("GEOQC_TEST_RESULTS")
    if target is None:
        return
    results = []
    for nodeid, vid in sorted(ITEMS.items()):
        phases = REPORTS.get(nodeid, {})
        outcomes = set(phases.values())
        status = (
            "FAILED"
            if "failed" in outcomes
            else "SKIPPED"
            if "skipped" in outcomes
            else "PASSED"
            if phases == {"setup": "passed", "call": "passed", "teardown": "passed"}
            else "INCOMPLETE"
        )
        results.append(
            {
                "nodeid": nodeid,
                "id": vid,
                "status": status,
                "phases": phases,
                "scientific_properties": PROPERTIES.get(nodeid, []),
                "supplement_criteria": SUPPLEMENT.get(nodeid, []),
            }
        )
    Path(target).write_text(
        json.dumps({"pytest_exit_code": int(exitstatus), "tests": results}, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
