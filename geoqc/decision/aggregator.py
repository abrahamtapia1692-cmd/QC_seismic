"""Agregación determinista por objetivo, soporte y registros efectivamente usados."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from geoqc.core.evidence import canonical_hash
from geoqc.core.models import Metric, Quality
from geoqc.decision.contracts import (
    AnnotatedAssessment,
    DecisionAssessment,
    DecisionInput,
    DecisionRecord,
    OperatorDecision,
    Requirement,
    RequirementResult,
)
from geoqc.masw.r1 import SUPPLEMENT_HASH


def _dependencies(records: dict[str, DecisionRecord]) -> dict[str, set[str]]:
    ancestors: dict[str, set[str]] = {}
    visiting: set[str] = set()

    def visit(key: str) -> set[str]:
        if key not in records or key in visiting:
            raise ValueError(f"Dependencia ausente o cíclica: {key}")
        if key not in ancestors:
            visiting.add(key)
            value: set[str] = set()
            for parent in records[key].dependency_ids:
                value.add(parent)
                value.update(visit(parent))
            visiting.remove(key)
            ancestors[key] = value
        return ancestors[key]

    for key in records:
        visit(key)
    return ancestors


def _supersessions(data: DecisionInput, records: dict[str, DecisionRecord]) -> dict[str, str]:
    replacements: dict[str, str] = {}
    for change in data.supersessions:
        if change.original_id not in records or change.replacement_id not in records:
            raise ValueError("Supersesión requiere original y sustituto conservados")
        original, replacement = records[change.original_id], records[change.replacement_id]
        fields = ("technique", "component", "geometry_hash", "config_hash", "support_refs")
        if any(getattr(original, field) != getattr(replacement, field) for field in fields):
            raise ValueError("Supersesión incompatible con geometría/componente/configuración/soporte")
        old = {m.id: m for m in original.metrics}
        new = {m.id: m for m in replacement.metrics}
        if len(set(change.resolved_metric_ids)) != len(change.resolved_metric_ids):
            raise ValueError("Causas de supersesión duplicadas")
        for key in change.resolved_metric_ids:
            if key not in old or key not in new:
                raise ValueError("Métrica resuelta ausente en original o sustituto")
            a, b = old[key], new[key]
            if a.unit != b.unit or a.support_refs != b.support_refs:
                raise ValueError("Soporte/unidad del control resuelto incompatibles")
            if b.validity != "VALID" or b.applicability != "APPLICABLE" or b.quality_status != "PASS":
                raise ValueError("La causa de supersesión aún no está resuelta")
        # No se puede resolver un fallo menor y esconder otro bloqueo obligatorio/crítico.
        required = {r.metric_id for r in data.requirements if r.record_id == original.id and r.mandatory}
        unresolved = {
            m.id
            for m in original.metrics
            if (m.mandatory or m.critical or m.id in required)
            and (m.validity != "VALID" or m.applicability != "APPLICABLE" or m.quality_status != "PASS")
        }
        if not unresolved <= set(change.resolved_metric_ids):
            raise ValueError("Supersesión no resuelve todos los bloqueos del original")
        if replacement.upstream_missing_requirement_ids:
            raise ValueError("Sustituto conserva requisitos upstream pendientes")
        replacements[original.id] = replacement.id
    for key in replacements:
        _effective(key, replacements)
    return replacements


def _effective(key: str, replacements: dict[str, str]) -> str:
    seen: set[str] = set()
    while key in replacements:
        if key in seen:
            raise ValueError("Supersesión cíclica")
        seen.add(key)
        key = replacements[key]
    return key


def _evaluate(req: Requirement, effective: str, record: DecisionRecord | None) -> RequirementResult:
    reasons: list[str] = []
    state: Literal["SATISFIED", "BLOCKED", "INCOMPLETE", "NOT_APPLICABLE"]
    if req.applicability == "NOT_APPLICABLE":
        state = "NOT_APPLICABLE"
        reasons.append(req.applicability_reason)
    else:
        metric = None if record is None else next((m for m in record.metrics if m.id == req.metric_id), None)
        if req.applicability == "UNKNOWN":
            reasons.append("APPLICABILITY_UNKNOWN")
        if record is None:
            reasons.append("REQUIRED_RECORD_NOT_USED")
        elif (
            req.technique != record.technique
            or req.component != record.component
            or not set(req.support_refs) <= set(record.support_refs)
        ):
            reasons.append("RECORD_CONTEXT_MISMATCH")
        if metric is None:
            reasons.append("METRIC_MISSING")
        else:
            if metric.unit != req.unit or not set(req.support_refs) <= set(metric.support_refs):
                reasons.append("METRIC_CONTEXT_MISMATCH")
            if metric.applicability != "APPLICABLE":
                reasons.append(f"METRIC_{metric.applicability}")
            if metric.validity != "VALID":
                reasons.append(metric.validity)
            if metric.quality_status is None:
                reasons.append("QUALITY_MISSING")
            if req.calibration_required:
                # Hasta conectar un registro confiable de alcance/vigencia, abstenerse.
                reasons.append("UNCALIBRATED")
        state = "INCOMPLETE" if reasons else "BLOCKED" if metric and metric.quality_status != "PASS" else "SATISFIED"
        if state == "BLOCKED" and metric:
            reasons.append(f"QUALITY_{metric.quality_status}")
    return RequirementResult(id=req.id, effective_record_id=effective, state=state, reasons=tuple(reasons))


def _quality(metrics: list[Metric]) -> Quality | None:
    values = {m.quality_status for m in metrics if m.validity == "VALID" and m.applicability == "APPLICABLE"}
    return "FAIL" if "FAIL" in values else "WARN" if "WARN" in values else "PASS" if "PASS" in values else None


def aggregate(data: DecisionInput) -> DecisionAssessment:
    """No acepta flags de reporte/UI; deriva todo y mantiene el release diagnóstico."""
    # Revalidar incluso modelos construidos mediante model_copy/model_construct.
    data = DecisionInput.model_validate(data.model_dump(mode="json"))
    records = {r.id: r for r in data.records}
    ancestors = _dependencies(records)
    replacements = _supersessions(data, records)
    if not set(data.selected_record_ids) <= records.keys():
        raise ValueError("Registro seleccionado ausente")
    used = set(data.selected_record_ids)
    for key in data.selected_record_ids:
        used.update(ancestors[key])
    results = tuple(
        _evaluate(req, effective, records.get(effective) if effective in used else None)
        for req in data.requirements
        for effective in (_effective(req.record_id, replacements),)
    )
    mandatory = {r.id for r in data.requirements if r.mandatory}
    missing = tuple(r.id for r in results if r.id in mandatory and r.state == "INCOMPLETE")
    blocked = tuple(r.id for r in results if r.id in mandatory and r.state == "BLOCKED")
    blockers = ["DIAGNOSTIC_RELEASE", "G9_FIELD_VALIDATION_PENDING"]
    blockers.extend(f"REQUIREMENT_INCOMPLETE:{key}" for key in missing)
    blockers.extend(f"REQUIREMENT_BLOCKED:{key}" for key in blocked)
    critical: set[str] = set()
    incomplete_upstream = False
    for key in sorted(used):
        record = records[key]
        if record.technique == "MASW" and (
            record.source_schema_version != "1.4-r1"
            or record.document_revision != "MASW-R1"
            or record.supplement_hash != SUPPLEMENT_HASH
        ):
            blockers.append(f"MASW_R1_MIGRATION_REQUIRED:{key}")
            incomplete_upstream = True
        for missing_id in record.upstream_missing_requirement_ids:
            blockers.append(f"UPSTREAM_MISSING:{key}:{missing_id}")
            incomplete_upstream = True
        for metric in record.metrics:
            linked = [
                r
                for r in data.requirements
                if key in (r.record_id, _effective(r.record_id, replacements))
                and r.metric_id == metric.id
                and r.applicability != "NOT_APPLICABLE"
            ]
            is_critical = metric.critical or any(r.critical and r.mandatory for r in linked)
            is_mandatory = metric.mandatory or any(r.mandatory for r in linked)
            if metric.quality_status == "FAIL" and is_critical:
                critical.add(key)
                blockers.append(f"CRITICAL_FAIL:{key}:{metric.id}")
            if is_mandatory and (
                metric.validity != "VALID" or metric.applicability != "APPLICABLE" or metric.quality_status is None
            ):
                # NA del perfil puede dispensar exclusivamente ese requisito/control.
                waived = (
                    any(
                        r.record_id == key and r.metric_id == metric.id and r.applicability == "NOT_APPLICABLE"
                        for r in data.requirements
                    )
                    and not linked
                )
                if not waived:
                    incomplete_upstream = True
                    blockers.append(f"MANDATORY_METRIC_INCOMPLETE:{key}:{metric.id}")
            if is_mandatory and metric.quality_status in ("WARN", "FAIL"):
                blockers.append(f"MANDATORY_METRIC_BLOCKED:{key}:{metric.id}")
    evidence = (
        "OUT_OF_SCOPE"
        if data.scope_status == "OUT_OF_SCOPE"
        else "INCOMPLETE"
        if missing or incomplete_upstream or data.scope_status == "UNKNOWN"
        else "COMPLETE"
    )
    if data.scope_status != "IN_SCOPE":
        blockers.append(f"SCOPE_{data.scope_status}")
    engine_root = Path(__file__).resolve().parents[1]
    engine_hash = canonical_hash(
        {
            p.relative_to(engine_root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(engine_root.rglob("*.py"))
        }
    )
    values = dict(
        input=data,
        quality_status=_quality([m for key in sorted(used) for m in records[key].metrics]),
        evidence_status=evidence,
        verdict="OUT_OF_SCOPE" if evidence == "OUT_OF_SCOPE" else "RED" if critical else "YELLOW",
        requirement_results=results,
        satisfied_requirement_ids=tuple(r.id for r in results if r.state == "SATISFIED"),
        missing_requirement_ids=missing,
        blocked_requirement_ids=blocked,
        not_applicable_requirement_ids=tuple(r.id for r in results if r.state == "NOT_APPLICABLE"),
        used_record_ids=tuple(sorted(used)),
        downstream_blocked_record_ids=tuple(sorted(key for key in used if ancestors[key] & critical)),
        blockers=tuple(blockers),
        engine_hash=engine_hash,
    )
    return DecisionAssessment.model_validate(values | {"scientific_digest": canonical_hash(values)})


def annotate(assessment: DecisionAssessment, event: OperatorDecision) -> AnnotatedAssessment:
    """Recalcular antes de registrar una decisión, sin convertirla en validación científica."""
    current = aggregate(assessment.input)
    event = OperatorDecision.model_validate(event.model_dump(mode="json"))
    if current != assessment or event.scientific_digest != current.scientific_digest:
        raise ValueError("Decisión/reporte no corresponde al digest científico vigente")
    if event.scope_ref != current.input.scope_ref:
        raise ValueError("Alcance de anotación incompatible")
    return AnnotatedAssessment(assessment=current, operator_decision=event)
