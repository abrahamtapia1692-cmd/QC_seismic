"""Versioned MASW-R1 data contracts and externally anchored modal evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal, Self

import numpy as np
from pydantic import BaseModel, Field, model_validator

from geoqc.core.evidence import canonical_hash
from geoqc.core.models import Digest, DispersionCurve, FrozenModel, Nonnegative, Positive

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Mode = Annotated[str, Field(pattern=r"^M[0-9]+$")]
Confidence = Literal["CONFIRMED", "APPARENT", "UNKNOWN"]
# Pinned normative supplement distributed with this implementation. Changes require migration.
SUPPLEMENT_HASH = "62140f332d255df578180637ae80b132d30880d6aa0977ba696970e00d106c26"


class R1Model(BaseModel):
    model_config = FrozenModel.model_config
    schema_version: Literal["1.4-r1"] = "1.4-r1"
    document_revision: Literal["MASW-R1"] = "MASW-R1"


class CurveR1(R1Model):
    frequencies_hz: tuple[Positive, ...]
    velocities_ms: tuple[Positive, ...]
    sigma_ms: tuple[Nonnegative | None, ...]
    valid_mask: tuple[bool, ...]
    reasons: tuple[Text, ...]
    mode_identity: Confidence
    declared_mode_identity: Confidence | None = None
    mode_labels: tuple[Mode | None, ...]
    point_ids: tuple[Text, ...]
    point_provenance: tuple[Text, ...]
    support_refs: tuple[Text | None, ...]
    covariance_ref: str | None = None
    resolution_ref: str | None = None
    band_refs: tuple[str, ...] = ()
    migration_ref: str | None = None
    velocity_kind: Literal["APPARENT", "MODAL_PHASE"] = "APPARENT"

    @model_validator(mode="after")
    def aligned(self) -> Self:
        n = len(self.frequencies_hz)
        if not n or any(
            len(v) != n
            for v in (
                self.velocities_ms,
                self.sigma_ms,
                self.valid_mask,
                self.reasons,
                self.mode_labels,
                self.point_ids,
                self.point_provenance,
                self.support_refs,
            )
        ):
            raise ValueError("Curva requiere campos alineados no vacíos")
        if len(set(self.point_ids)) != n or any(
            b <= a for a, b in zip(self.frequencies_hz, self.frequencies_hz[1:], strict=False)
        ):
            raise ValueError("Frecuencias crecientes e identidades únicas requeridas")
        if any(valid and reason != "VALID" for valid, reason in zip(self.valid_mask, self.reasons, strict=True)):
            raise ValueError("Máscara y motivos incompatibles")
        return self


def migrate_curve(curve: DispersionCurve) -> CurveR1:
    """Preserve declarations; legacy confidence does not establish a physical mode."""
    body = curve.model_dump(mode="json", exclude={"schema_version", "mode_uncertainty_reason"})
    digest = canonical_hash(curve)
    n = len(curve.frequencies_hz)
    return CurveR1.model_validate(
        body
        | {
            "mode_identity": "UNKNOWN" if curve.mode_identity == "CONFIRMED" else curve.mode_identity,
            "declared_mode_identity": curve.mode_identity,
            "mode_labels": (None,) * n,
            "point_ids": tuple(f"legacy:{digest}:{i}" for i in range(n)),
            "support_refs": (None,) * n,
            "migration_ref": f"1.4:{digest}",
        }
    )


def numerical_tolerance(matrix: np.ndarray[Any, Any]) -> float:
    return float(64 * np.finfo(float).eps * max(matrix.shape) * np.linalg.norm(matrix, 2))


class JointCovariance(R1Model):
    point_ids: tuple[Text, ...]
    matrix: tuple[tuple[float, ...], ...]
    unit: Literal["(m/s)^2"] = "(m/s)^2"
    provenance: Text

    @model_validator(mode="after")
    def positive_semidefinite(self) -> Self:
        n = len(self.point_ids)
        if not n or len(set(self.point_ids)) != n or len(self.matrix) != n or any(len(r) != n for r in self.matrix):
            raise ValueError("Covarianza e identidades únicas deben estar alineadas")
        matrix = np.asarray(self.matrix)
        tolerance = numerical_tolerance(matrix)
        if np.max(abs(matrix - matrix.T)) > tolerance or np.min(np.diag(matrix)) < 0:
            raise ValueError("Covarianza debe ser simétrica con diagonal no negativa")
        if np.min(np.linalg.eigvalsh((matrix + matrix.T) / 2)) < -tolerance:
            raise ValueError("Covarianza debe ser semidefinida positiva")
        return self


class ModalEvidence(R1Model):
    id: Text
    shot_hash: Digest
    protocol_hash: Digest
    estimator_hash: Digest
    domain_id: Text
    direction: Literal[-1, 1]
    frequencies_hz: tuple[Positive, ...]
    support_hashes: tuple[Digest, ...]
    mode_labels: tuple[Mode, ...]
    authority_id: Text
    method: Text
    source_kind: Literal["HUMAN", "CALIBRATED_METHOD"]
    calibration_ref: Text | None = None
    alternatives: tuple[Text, ...]
    limitations: Text
    wave: Literal["RAYLEIGH"] = "RAYLEIGH"
    component: Literal["Z"] = "Z"

    @model_validator(mode="after")
    def aligned(self) -> Self:
        n = len(self.frequencies_hz)
        if not n or len(self.support_hashes) != n or len(self.mode_labels) != n or not self.alternatives:
            raise ValueError("Evidencia requiere puntos, soporte, modo y alternativas")
        if any(b <= a for a, b in zip(self.frequencies_hz, self.frequencies_hz[1:], strict=False)):
            raise ValueError("Frecuencias de evidencia deben crecer")
        if self.source_kind == "CALIBRATED_METHOD" and self.calibration_ref is None:
            raise ValueError("Método calibrado requiere referencia de calibración")
        return self


class ModalApproval(R1Model):
    """Trusted application input, never loaded from the scientific report itself."""

    content_hash: Digest
    authority_id: Text
    active: bool


def resolve_modes(
    *,
    reference: str | None,
    requested: Confidence,
    shot_hash: str,
    protocol_hash: str,
    estimator_hash: str,
    domain_id: str | None,
    direction: int,
    frequencies_hz: tuple[float, ...],
    support_hashes: tuple[str, ...],
    observed: tuple[bool, ...],
    evidence: Mapping[str, ModalEvidence] | None = None,
    approvals: Mapping[str, ModalApproval] | None = None,
) -> dict[str, Any]:
    if not frequencies_hz or len(support_hashes) != len(frequencies_hz) or len(observed) != len(frequencies_hz):
        raise ValueError("Contexto modal desalineado")
    document = None if evidence is None or reference is None else evidence.get(reference)
    approval = None if approvals is None or reference is None else approvals.get(reference)
    reason = "NO_VERIFIED_MODAL_EVIDENCE"
    verified = False
    if document is not None and approval is not None:
        # Revalidate even model_copy/model_construct objects before trusting their fields.
        try:
            document = ModalEvidence.model_validate(document.model_dump())
            approval = ModalApproval.model_validate(approval.model_dump())
            verified = (
                document.id == reference
                and approval.active
                and approval.authority_id == document.authority_id
                and approval.content_hash == canonical_hash(document)
                and document.shot_hash == shot_hash
                and document.protocol_hash == protocol_hash
                and document.estimator_hash == estimator_hash
                and document.domain_id == domain_id
                and document.direction == direction
            )
        except ValueError:
            verified = False
            document = None
        reason = "VERIFIED_EXTERNAL_APPROVAL" if verified else "UNTRUSTED_OR_INCOMPATIBLE_MODAL_EVIDENCE"
    states: list[str] = []
    labels: list[str | None] = []
    reasons: list[str] = []
    by_frequency = {} if document is None else {f: i for i, f in enumerate(document.frequencies_hz)}
    for f, support, has_data in zip(frequencies_hz, support_hashes, observed, strict=True):
        i = by_frequency.get(f)
        if has_data and verified and document is not None and i is not None and document.support_hashes[i] == support:
            states.append("CONFIRMED")
            labels.append(document.mode_labels[i])
            reasons.append(reason)
        else:
            states.append("APPARENT" if has_data and requested == "APPARENT" else "UNKNOWN")
            labels.append(None)
            reasons.append(
                "NO_OBSERVED_SUPPORT" if not has_data else "POINT_OUTSIDE_APPROVED_SUPPORT" if verified else reason
            )
    return {
        "declared_mode_identity": requested,
        "mode_identity": states[0] if len(set(states)) == 1 else "UNKNOWN",
        "point_mode_identity": states,
        "mode_labels": labels,
        "mode_reasons": reasons,
        "velocity_kind": ["MODAL_PHASE" if s == "CONFIRMED" else "APPARENT" for s in states],
        "mode_evidence_ref": reference,
        "verified_evidence_hash": canonical_hash(document) if verified and document is not None else None,
        "confirmation_source": document.source_kind if verified and document is not None else None,
    }
