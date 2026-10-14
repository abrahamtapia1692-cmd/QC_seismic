"""Contratos de decisión diagnóstica; entradas no otorgan confianza operativa."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from geoqc.core.models import Applicability, Digest, FrozenModel, Metric, Quality

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]


class Requirement(FrozenModel):
    id: Text
    record_id: Text
    metric_id: Text
    unit: Text
    support_refs: tuple[Text, ...] = Field(min_length=1)
    technique: Literal["TRS", "MASW"]
    component: Literal["Z", "X", "Y"]
    mandatory: bool
    critical: bool
    applicability: Applicability
    applicability_reason: Text
    calibration_required: bool


class DecisionRecord(FrozenModel):
    id: Text
    technique: Literal["TRS", "MASW"]
    component: Literal["Z", "X", "Y"]
    geometry_hash: Digest
    config_hash: Digest
    code_hash: Digest
    data_hashes: tuple[Digest, ...] = Field(min_length=1)
    support_refs: tuple[Text, ...] = Field(min_length=1)
    metrics: tuple[Metric, ...]
    dependency_ids: tuple[Text, ...] = ()
    upstream_missing_requirement_ids: tuple[Text, ...] = ()
    source_schema_version: Literal["1.4", "1.4-r1"] = "1.4"
    document_revision: str | None = None
    supplement_hash: Digest | None = None

    @model_validator(mode="after")
    def unique_metrics(self) -> Self:
        # Una métrica por soporte; controles por traza necesitan IDs distintos.
        if len({m.id for m in self.metrics}) != len(self.metrics):
            raise ValueError("IDs de métricas duplicados en registro")
        if any(not m.id.strip() for m in self.metrics):
            raise ValueError("Identificador de métrica vacío")
        if len(set(self.dependency_ids)) != len(self.dependency_ids):
            raise ValueError("Dependencias duplicadas")
        return self


class Supersession(FrozenModel):
    original_id: Text
    replacement_id: Text
    resolved_metric_ids: tuple[Text, ...] = Field(min_length=1)
    responsible: Text
    reason: Text


class DecisionInput(FrozenModel):
    profile_ref: Text
    scope_ref: Text
    scope_status: Literal["IN_SCOPE", "OUT_OF_SCOPE", "UNKNOWN"]
    requirements: tuple[Requirement, ...] = Field(min_length=1)
    records: tuple[DecisionRecord, ...]
    selected_record_ids: tuple[Text, ...]
    supersessions: tuple[Supersession, ...] = ()

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        for ids in (
            tuple(r.id for r in self.requirements),
            tuple(r.id for r in self.records),
            self.selected_record_ids,
            tuple(s.original_id for s in self.supersessions),
        ):
            if len(set(ids)) != len(ids):
                raise ValueError("Identificadores duplicados en decisión")
        return self


class RequirementResult(FrozenModel):
    id: Text
    effective_record_id: Text
    state: Literal["SATISFIED", "BLOCKED", "INCOMPLETE", "NOT_APPLICABLE"]
    reasons: tuple[Text, ...]


class DecisionAssessment(FrozenModel):
    input: DecisionInput
    quality_status: Quality | None
    evidence_status: Literal["COMPLETE", "INCOMPLETE", "OUT_OF_SCOPE"]
    verdict: Literal["YELLOW", "RED", "OUT_OF_SCOPE"]
    diagnostic_mode: Literal[True] = True
    eligible_for_acceptance: Literal[False] = False
    requirement_results: tuple[RequirementResult, ...]
    satisfied_requirement_ids: tuple[Text, ...]
    missing_requirement_ids: tuple[Text, ...]
    blocked_requirement_ids: tuple[Text, ...]
    not_applicable_requirement_ids: tuple[Text, ...]
    used_record_ids: tuple[Text, ...]
    downstream_blocked_record_ids: tuple[Text, ...]
    blockers: tuple[Text, ...]
    scientific_digest: Digest
    engine_hash: Digest


class OperatorDecision(FrozenModel):
    decision: Literal["PENDING", "ACCEPTED", "REPEAT", "EXTEND"]
    responsible: Text
    scope_ref: Text
    reason: Text
    caveats: tuple[Text, ...]
    scientific_digest: Digest
    timestamp: datetime

    @model_validator(mode="after")
    def explicit_caveats(self) -> Self:
        if self.timestamp.tzinfo is None:
            raise ValueError("Fecha de decisión requiere zona horaria")
        if self.decision == "ACCEPTED" and not self.caveats:
            raise ValueError("Aceptación humana diagnóstica requiere salvedades explícitas")
        return self


class AnnotatedAssessment(FrozenModel):
    assessment: DecisionAssessment
    operator_decision: OperatorDecision
    acceptance_kind: Literal["HUMAN_ANNOTATION_ONLY"] = "HUMAN_ANNOTATION_ONLY"


class Action(FrozenModel):
    id: Text
    description: Text
    condition: Text
    assumptions: tuple[Text, ...] = Field(min_length=1)
    validity: Literal["VALID", "MODEL_INAPPLICABLE", "INVALID"]
    reason: Text
    value: float | None
    unit: Text
