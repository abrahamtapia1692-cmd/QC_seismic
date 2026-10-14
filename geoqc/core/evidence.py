"""Hashes canónicos y evaluación de obligaciones; los resultados vienen del runner."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel

from geoqc.core.errors import EvidenceError

GateStatus = Literal["PASSED", "FAILED", "INCOMPLETE"]


def _canonical(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return {"__model__": type(value).__name__, "value": _canonical(value.model_dump(mode="json"))}
    if isinstance(value, np.ndarray):
        if value.dtype.kind not in "bifuc":
            raise ValueError("Solo arrays científicos booleanos o numéricos")
        if not np.all(np.isfinite(value)):
            raise ValueError("Array no finito: expresar faltantes mediante contrato y máscara")
        normalized = np.ascontiguousarray(value.astype(value.dtype.newbyteorder("<")))
        return {"__array__": normalized.dtype.str, "shape": list(normalized.shape), "hex": normalized.tobytes().hex()}
    if isinstance(value, np.generic):
        return _canonical(value.item())
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not np.isfinite(value):
            raise ValueError("JSON científico no admite NaN/Inf")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("Claves canónicas deben ser texto")
        return {"__mapping__": [[key, _canonical(item)] for key, item in sorted(value.items())]}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    raise ValueError(f"Tipo sin representación canónica: {type(value).__name__}")


def canonical_hash(value: Any) -> str:
    body = json.dumps(_canonical(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def seeded_rng(seed: int) -> np.random.Generator:
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**64:
        raise ValueError("Semilla entera explícita en [0,2**64)")
    return np.random.Generator(np.random.PCG64(seed))


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    tests, gates = manifest.get("tests"), manifest.get("gates")
    if not isinstance(tests, list) or not isinstance(gates, dict) or not tests or not gates:
        raise EvidenceError("Manifiesto requiere registro de pruebas y gates")
    ids = [item["id"] for item in tests]
    if len(set(ids)) != len(ids):
        raise EvidenceError("ID de prueba duplicado")
    covered: set[str] = set()
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(gate_id: str) -> None:
        if gate_id not in gates or gate_id in visiting:
            raise EvidenceError(f"Dependencia desconocida o cíclica: {gate_id}")
        if gate_id in visited:
            return
        visiting.add(gate_id)
        for dependency in gates[gate_id]["depends_on"]:
            visit(dependency)
        visiting.remove(gate_id)
        visited.add(gate_id)

    for gate_id, gate in gates.items():
        required = gate["required_test_ids"]
        if not required or len(set(required)) != len(required) or not set(required) <= set(ids):
            raise EvidenceError(f"Obligaciones de gate inválidas: {gate_id}")
        covered.update(required)
        visit(gate_id)
    if covered != set(ids):
        raise EvidenceError("Prueba sin gate")


def evaluate_gate(manifest: Mapping[str, Any], gate_id: str, results: Sequence[Mapping[str, Any]]) -> GateStatus:
    validate_manifest(manifest)
    gates = manifest["gates"]
    if gate_id not in gates:
        raise EvidenceError("Gate desconocido")
    known = {item["id"] for item in manifest["tests"]}
    by_id: dict[str, str] = {}
    for result in results:
        vid, status = result["id"], result["status"]
        if vid not in known or vid in by_id or status not in {"PASSED", "FAILED", "SKIPPED", "INCOMPLETE", "NOT_RUN"}:
            raise EvidenceError("Resultado desconocido, duplicado o con estado inválido")
        by_id[vid] = status

    def evaluate(current: str) -> GateStatus:
        gate = gates[current]
        states = [by_id.get(vid, "NOT_RUN") for vid in gate["required_test_ids"]]
        states.extend(evaluate(dependency) for dependency in gate["depends_on"])
        if "FAILED" in states:
            return "FAILED"
        if all(status == "PASSED" for status in states):
            return "PASSED"
        return "INCOMPLETE"

    return evaluate(gate_id)
