"""Generar el manifiesto documental v1.4; nunca marca pruebas como ejecutadas."""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]
body = (ROOT / "SDD_QC_Geofisico_MASW_TRS_v1_4.md").read_text(encoding="utf-8")
limits = {0: 10, 1: 6, 2: 10, 3: 8, 4: 21, 5: 22, 6: 6, 7: 3, 8: 4, 9: 7, 10: 2}
stages = {i: [f"V-E{i}-{n}" for n in range(1, limit + 1)] for i, limit in limits.items()}
stages[5].insert(stages[5].index("V-E5-18"), "V-E5-17b")
dependencies = {0: [], 1: ["G0"], 3: ["G0"], 2: ["G1", "G3"], 4: ["G2"], 5: ["G2"],
                6: ["G4", "G5"], 7: ["G6"], 8: ["G7"], 9: ["G8"], 10: ["G9"]}
scopes = {0: "implementation_and_analytic_reference", 1: "ingestion", 3: "basic_synthetics",
          2: "common_qc_synthetic", 4: "trs_synthetic_domain", 5: "masw_synthetic_domain",
          6: "decision", 7: "user_interface", 8: "reports",
          9: "independent_calibration_and_field_validation", 10: "packaging_with_validated_profile"}
gates = {}
for i in (0, 1, 3, 2, 4, 5, 6, 7, 8, 9, 10):
    tests = stages[i].copy()
    if i == 0:
        tests.append("V-E3-4")
    if i == 3:
        tests.remove("V-E3-8")
    if i == 5:
        tests.append("V-E3-8")
    gates[f"G{i}"] = {"depends_on": dependencies[i], "required_test_ids": tests,
                       "status": "NOT_RUN", "scope": scopes[i]}

mapping = {
    "H01": ["V-E0-4", "V-E5-9", "V-E5-10"], "H02": ["V-E0-8", "V-E2-9"],
    "H03": ["V-E0-5", "V-E5-14", "V-E5-15", "V-E5-22"], "H04": ["V-E5-3"],
    "H05": ["V-E5-11", "V-E5-12"], "H06": ["V-E5-17"],
    "H07": ["V-E5-17b", "V-E5-18", "V-E5-21"], "H08": ["V-E3-8", "V-E5-10"],
    "H09": ["V-E4-10"], "H10": ["V-E3-1", "V-E4-1", "V-E4-2", "V-E4-3"],
    "H11": ["V-E6-1", "V-E6-2", "V-E6-4", "V-E6-5"], "H12": ["V-E0-10"],
    "H13": ["V-E0-10"], "H14": ["V-E2-3"], "H15": ["V-E2-2", "V-E2-6"],
    "H16": ["V-E4-5", "V-E4-6", "V-E4-7"], "H17": ["V-E3-2", "V-E4-8", "V-E4-9"],
    "H18": ["V-E0-7", "V-E1-4", "V-E1-5", "V-E5-4", "V-E5-6"],
    "H19": ["V-E5-7", "V-E5-8"], "H20": ["V-E4-18", "V-E4-19", "V-E4-20", "V-E4-21"],
    "H21": ["V-E4-14", "V-E4-15", "V-E5-16"], "H22": ["V-E9-1", "V-E9-3"],
    "H23": ["V-E2-1", "V-E2-5", "V-E9-4"], "H24": ["V-E2-4", "V-E2-8", "V-E6-3"],
    "H25": ["V-E0-9", "V-E8-2"], "H26": ["V-E0-3", "V-E0-6", "V-E5-20", "V-E9-7"],
    "H27": ["V-E2-7", "V-E2-10", "V-E4-13", "V-E5-1", "V-E5-16"],
    "H28": ["V-E4-9", "V-E6-6"], "H29": ["V-E8-1", "V-E8-3", "V-E8-4"],
    "H30": ["V-E0-1", "V-E0-10"],
}
descriptions = {}
for test_id, description in re.findall(r"^- \*\*(V-E\d+-\d+[a-z]?):\*\* (.+)$", body, re.M):
    descriptions.setdefault(test_id, description)
new_ids = {"V-E0-9", "V-E0-10", "V-E3-8", "V-E5-21", "V-E5-22", "V-E6-6", "V-E8-4", "V-E9-7"}
registered = []
for stage in sorted(stages):
    for test_id in stages[stage]:
        registered.append({"id": test_id, "specification_version": "1.4", "required": True,
                           "status": "NOT_IMPLEMENTED_FOR_SPEC_1_4",
                           "gate_refs": [name for name, gate in gates.items() if test_id in gate["required_test_ids"]],
                           "description": descriptions[test_id],
                           "previous_test_id": None if test_id in new_ids else test_id})
payload = {
    "schema_version": "1.0", "specification_version": "1.4",
    "plan_file": "SDD_QC_Geofisico_MASW_TRS_v1_4.md", "status": "SPECIFICATION_ONLY",
    "gate_policy": {"all_required_tests_must_pass": True, "required_skip_result": "INCOMPLETE",
                    "audit_evidence_is_implementation_evidence": False, "field_calibration_gate": "G9",
                    "acceptance_requires_validated_profile": True},
    "gates": gates, "tests": registered,
    "audit_findings": {finding: {"specification_change": "INCORPORATED", "execution_status": "PENDING",
                                "validation_test_ids": tests} for finding, tests in mapping.items()},
}
target = ROOT / "docs/validation_manifest_v1_4.json"
if target.exists():
    existing = json.loads(target.read_text(encoding="utf-8"))
    if any(g["status"] != "NOT_RUN" for g in existing["gates"].values()):
        raise SystemExit("Hay estados de ejecución registrados; no sobrescribirlos con un generador documental.")
    if any(t["status"] != "NOT_IMPLEMENTED_FOR_SPEC_1_4" for t in existing["tests"]):
        raise SystemExit("Hay resultados registrados; conservarlos mediante migración explícita.")
target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"{len(registered)} pruebas, {len(gates)} gates, {len(mapping)} hallazgos mapeados; ejecución pendiente.")
