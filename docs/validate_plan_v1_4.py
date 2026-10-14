"""Comprobar coherencia documental y contrapruebas de la revisión; no cerrar gates."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np
from scipy.optimize import brentq

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "SDD_QC_Geofisico_MASW_TRS_v1_4.md"
MANIFEST = ROOT / "docs/validation_manifest_v1_4.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    text = PLAN.read_text(encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    previous = json.loads((ROOT / "evidence/audit_plan_v1_3.json").read_text(encoding="utf-8"))
    ids = set(re.findall(r"^- \*\*(V-E\d+-\d+[a-z]?):", text, re.MULTILINE))
    registered = [item["id"] for item in manifest["tests"]]
    assert len(registered) == len(set(registered)) == 100
    assert ids == set(registered), {"only_plan": sorted(ids - set(registered)), "only_manifest": sorted(set(registered) - ids)}
    gates = manifest["gates"]
    assert len(gates) == 11
    covered = set()
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(gate_id: str) -> None:
        assert gate_id in gates, gate_id
        assert gate_id not in visiting, f"Dependencia cíclica: {gate_id}"
        if gate_id in visited:
            return
        visiting.add(gate_id)
        for dependency in gates[gate_id]["depends_on"]:
            visit(dependency)
        visiting.remove(gate_id)
        visited.add(gate_id)

    for gate_id, gate in gates.items():
        visit(gate_id)
        assert gate["status"] == "NOT_RUN"
        assert gate["required_test_ids"]
        assert len(gate["required_test_ids"]) == len(set(gate["required_test_ids"]))
        assert set(gate["required_test_ids"]) <= ids
        covered.update(gate["required_test_ids"])
    assert covered == ids
    assert set(f"V-E4-{n}" for n in range(18, 22)) <= set(gates["G4"]["required_test_ids"])
    assert {"V-E5-17", "V-E5-17b", "V-E5-18", "V-E5-19", "V-E5-20"} <= set(gates["G5"]["required_test_ids"])
    assert {"V-E6-4", "V-E6-5"} <= set(gates["G6"]["required_test_ids"])
    assert "V-E8-3" in gates["G8"]["required_test_ids"]
    assert all(item["status"] == "NOT_IMPLEMENTED_FOR_SPEC_1_4" and item["required"] for item in manifest["tests"])
    assert digest(ROOT / "SDD_QC_Geofisico_MASW_TRS.md") == previous["sdd_sha256"]
    for name, expected in previous["input_sha256"].items():
        historical = ROOT / ("docs/archive/pyproject_v0_0_1.toml" if name == "pyproject.toml" else name)
        assert digest(historical) == expected, name
    mappings = manifest["audit_findings"]
    assert set(mappings) == {f"H{n:02}" for n in range(1, 31)}
    for finding, mapping in mappings.items():
        assert mapping["specification_change"] == "INCORPORATED"
        assert mapping["execution_status"] == "PENDING"
        assert mapping["validation_test_ids"] and set(mapping["validation_test_ids"]) <= ids, finding

    local_links = 0
    for relative in ("README.md", PLAN.name, "docs/revision_v1_4.md", "docs/open_questions.md", "docs/adr/0001-revision-teorica-del-plan.md"):
        path = ROOT / relative
        body = path.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)]+)\)", body):
            if target.startswith(("https:", "http:", "#")):
                continue
            assert (path.parent / target.split("#")[0]).resolve().exists(), (relative, target)
            local_links += 1

    n, dx = 24, 2.0
    def kernel(q: float) -> float:
        return float(abs(np.sin(n * math.pi * dx * q) / (n * np.sin(math.pi * dx * q))))
    width_amplitude = 2 * brentq(lambda q: kernel(q) - .5, 1e-12, 1 / (n * dx) - 1e-12) * n * dx
    width_power = 2 * brentq(lambda q: kernel(q) ** 2 - .5, 1e-12, 1 / (n * dx) - 1e-12) * n * dx
    assert abs(width_amplitude - 1.2074756732) < 1e-9
    assert abs(width_power - .8865573942) < 1e-9
    assert (6 + (24 - 1) * 2 / 2) / 48 == 29 / 48
    assert previous["hidden_layer_nonidentifiability"]["max_time_difference_between_models_s"] == 0
    assert previous["rayleigh_tail_not_always_conservative"]["kluyver_tail"] > .3
    assert math.ceil(math.log(.05) / math.log(.95)) == 59
    checks = {
        "test_ids_complete": len(ids), "gate_dependencies_acyclic": True,
        "specification_manifest_retains_initial_states": True, "audit_findings_mapped": len(mappings),
        "historical_plan_and_source_hashes_preserved": True,
        "historical_pyproject_archive": "docs/archive/pyproject_v0_0_1.toml", "local_links_checked": local_links,
        "fwhm_amplitude_N24_times_Ndx": width_amplitude,
        "fwhm_power_N24_times_Ndx": width_power,
        "counterexamples_preserved": ["NACD", "hidden_layer", "rayleigh_tail", "binomial_size"],
    }
    payload = {
        "id": "PLAN-REVISION-1.4", "status": "DOCUMENT_CONSISTENCY_VERIFIED",
        "scope": "Documento, manifiesto, integridad histórica y contrapruebas; no cierre de gates",
        "specification_version": "1.4", "audit_date_local": "2026-10-03",
        "input_hashes": {"plan": digest(PLAN), "manifest": digest(MANIFEST),
                         "previous_audit": digest(ROOT / "evidence/audit_plan_v1_3.json"),
                         "validator": digest(Path(__file__))}, "checks": checks,
        "implementation_and_field_validation": "NOT_ASSESSED_BY_DOCUMENT_CHECK",
        "execution_state_source": "evidence/e1_e3/execution.json",
    }
    (ROOT / "evidence/plan_revision_v1_4.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(checks, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
