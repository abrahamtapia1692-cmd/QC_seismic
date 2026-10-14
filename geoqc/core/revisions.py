"""Supplement evaluation for trusted runner output, not user-supplied reports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from geoqc.core.evidence import GateStatus, validate_manifest


def evaluate_supplement(
    execution: Mapping[str, Any],
    criteria: Mapping[str, Sequence[str]],
    *,
    supplement_hash: str,
    code_hash: str,
    protocol_hash: str,
) -> dict[str, GateStatus]:
    if not criteria or any(not names or len(set(names)) != len(names) for names in criteria.values()):
        raise ValueError("Cada obligación requiere criterios únicos explícitos")
    incomplete: dict[str, GateStatus] = dict.fromkeys(criteria, "INCOMPLETE")
    if (
        execution.get("document_revision") != "MASW-R1"
        or execution.get("supplement_hash") != supplement_hash
        or execution.get("code_hash") != code_hash
        or execution.get("protocol_hash") != protocol_hash
    ):
        return incomplete
    tests = execution.get("tests")
    if not isinstance(tests, list):
        return incomplete
    groups: dict[tuple[str, str], list[str]] = {}
    nodes: set[str] = set()
    for case in tests:
        if not isinstance(case, dict) or not isinstance(case.get("nodeid"), str) or case["nodeid"] in nodes:
            return incomplete
        nodes.add(case["nodeid"])
        phases = case.get("phases", {})
        if not isinstance(phases, dict):
            return incomplete
        state = (
            "FAILED"
            if "failed" in phases.values()
            else "PASSED"
            if phases == dict(setup="passed", call="passed", teardown="passed") and case.get("status") == "PASSED"
            else "INCOMPLETE"
        )
        markers = case.get("supplement_criteria", [])
        if not isinstance(markers, list):
            return incomplete
        for marker in markers:
            if (
                not isinstance(marker, (list, tuple))
                or len(marker) != 2
                or marker[0] not in criteria
                or marker[1] not in criteria[marker[0]]
            ):
                return incomplete
            groups.setdefault(tuple(marker), []).append(state)
    result: dict[str, GateStatus] = {}
    for obligation, names in criteria.items():
        states = [state for name in names for state in groups.get((obligation, name), ["INCOMPLETE"])]
        result[obligation] = (
            "FAILED"
            if "FAILED" in states
            else "PASSED"
            if all(state == "PASSED" for state in states) and execution.get("pytest_exit_code") == 0
            else "INCOMPLETE"
        )
    return result


def expanded_gates(
    base: Mapping[str, GateStatus],
    manifest: Mapping[str, Any],
    supplement: Mapping[str, GateStatus],
    required_ids: Sequence[str],
) -> dict[str, GateStatus]:
    """G5 adds ALL supplement obligations; propagate to dependent gates."""
    validate_manifest(manifest)
    if not required_ids or len(set(required_ids)) != len(required_ids):
        raise ValueError("Obligaciones requeridas únicas y no vacías")
    result: dict[str, GateStatus] = {}

    def visit(gate: str) -> GateStatus:
        if gate in result:
            return result[gate]
        states = [base.get(gate, "INCOMPLETE")]
        if gate == "G5":
            states.extend(supplement.get(key, "INCOMPLETE") for key in required_ids)
        states.extend(visit(parent) for parent in manifest["gates"][gate]["depends_on"])
        result[gate] = (
            "FAILED" if "FAILED" in states else "PASSED" if all(s == "PASSED" for s in states) else "INCOMPLETE"
        )
        return result[gate]

    for gate in manifest["gates"]:
        visit(gate)
    return result
