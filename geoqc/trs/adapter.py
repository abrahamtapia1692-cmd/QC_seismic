"""Headless local TRS dossier: preserve native picks, abstentions and provenance."""
from __future__ import annotations

from typing import Any

from geoqc.core.evidence import canonical_hash
from geoqc.core.models import Shot
from geoqc.qc.adapter import TraceQCRequest, trace_qc
from geoqc.qc.operational import aggregate_screening
from geoqc.qc.quality import assess_quality
from geoqc.trs.contracts import TRSProtocol
from geoqc.trs.picking import estimator_hash
from geoqc.trs.report import trs_diagnostics


def build_trs_dossier(shots: tuple[Shot, ...], protocol: TRSProtocol, revision_id: str,
                      engine_reference: dict[str, Any], trace_qc_request: TraceQCRequest | None = None) -> dict[str, Any]:
    if not 1 <= len(shots) <= 4 or len({shot.id for shot in shots}) != len(shots):
        raise ValueError("Se requieren 1..4 tiros TRS con identificadores únicos")
    records: list[dict[str, Any]] = []
    for shot in shots:
        if shot.acquisition.technique != "TRS" or shot.acquisition.wave != "P":
            raise ValueError("El sidecar debe declarar TRS/P; no se convierte técnica automáticamente")
        diagnostic = trs_diagnostics(shot, protocol)
        records.append({"shot_id": shot.id, "amplitude_unit": shot.acquisition.amplitude_unit,
                        "geometry": shot.geometry.model_dump(mode="json"),
                        "acquisition": shot.acquisition.model_dump(mode="json"),
                        "diagnostics": diagnostic, "trace_qc": trace_qc(shot, trace_qc_request)})
    body: dict[str, Any] = {
        "schema_version": "app-trs-dossier-0.1", "method": "TRS", "scope": "LOCAL_TRS_DIAGNOSTIC_ONLY",
        "acquisition_revision_id": revision_id,
        "input_manifest": {"shots": [{"shot_id": shot.id, "input_hashes": list(shot.input_hashes),
                                       "scientific_shot_hash": canonical_hash(shot),
                                       "headers_hash": canonical_hash(shot.headers_json)} for shot in shots],
                           "protocol_hash": canonical_hash(protocol)},
        "protocol": protocol.model_dump(mode="json"),
        "engine_reference": engine_reference | {"trs_estimator_hash": estimator_hash()},
        "diagnostic_quality": records,
        "trace_qc_assessment": assess_quality(t["quality"] for r in records for t in r["trace_qc"]["traces"]),
        "scientific_status": "DIAGNOSTIC_ONLY_INCOMPLETE_EVIDENCE",
        "missing_evidence": sorted({reason for record in records
                                    for reason in (*record["diagnostics"]["missing_requirement_ids"],
                                                   *record["trace_qc"]["report"]["missing_requirement_ids"])}),
        "sufficiency": {"status": "NOT_DEMONSTRATED"}, "eligible_for_acceptance": False,
    }
    if protocol.picking.noise_position == "DECLARED_POST_SIGNAL":
        body["missing_evidence"].append("POST_SIGNAL_NOISE_WINDOW_NOT_FIELD_VALIDATED")
    if trace_qc_request is not None and trace_qc_request.operational_policy is not None:
        body["operational_assessment"] = aggregate_screening(
            [t for r in records for t in r["trace_qc"]["traces"]], trace_qc_request.operational_policy.id)
    return body | {"scientific_digest": canonical_hash(body)}
