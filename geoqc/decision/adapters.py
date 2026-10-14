"""Adaptación explícita de QC común; no consume flags de elegibilidad externos."""

from collections import Counter

from geoqc.core.evidence import canonical_hash
from geoqc.core.models import Metric, QCReport, Shot
from geoqc.decision.contracts import DecisionRecord


def record_from_common_qc(shot: Shot, report: QCReport) -> DecisionRecord:
    """IDs repetidos por traza se califican con hash de soporte, conservado en la métrica.

    Reporte y Shot deben venir del mismo cálculo en la aplicación. La coincidencia
    de hashes originales es comprobación de consistencia, no autenticación de datos.
    """
    report = QCReport.model_validate(report.model_dump(mode="json"))
    if report.data_hashes != shot.input_hashes:
        raise ValueError("QC común y Shot no comparten hashes originales")
    counts = Counter(m.id for m in report.metrics)
    metrics = tuple(
        Metric.model_validate(
            m.model_dump() | {"id": m.id if counts[m.id] == 1 else f"{m.id}@{canonical_hash(m.support_refs)}"}
        )
        for m in report.metrics
    )
    support = tuple(sorted({ref for m in metrics for ref in m.support_refs}))
    if not support:
        raise ValueError("QC común requiere soporte explícito")
    return DecisionRecord(
        id=shot.id,
        technique=shot.acquisition.technique,
        component=shot.acquisition.component,
        geometry_hash=canonical_hash(shot.geometry),
        config_hash=report.config_hash,
        code_hash=report.code_hash,
        data_hashes=report.data_hashes,
        support_refs=support,
        metrics=metrics,
        upstream_missing_requirement_ids=report.missing_requirement_ids,
    )
