from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np

from geoqc.core.config import ProjectConfig, Threshold
from geoqc.core.evidence import canonical_hash
from geoqc.core.models import Metric, QCReport, Quality, Shot
from geoqc.qc.channels import channel_statistics, clipping
from geoqc.qc.contracts import QCProtocol
from geoqc.qc.quality import aggregate_quality, assess_quality, trace_quality
from geoqc.qc.similarity import local_similarity
from geoqc.qc.spectral import mains_line, noise_psd, snr
from geoqc.qc.timing import time_budget


def common_qc(shot: Shot, protocol: QCProtocol, config: ProjectConfig | None = None) -> dict[str, Any]:
    statistics = channel_statistics(shot, protocol)
    similarities = (
        None
        if protocol.similarity is None
        else local_similarity(
            shot.data,
            shot.valid_mask,
            shot.dt_s,
            shot.t0_s,
            np.column_stack((shot.geometry.xr, shot.geometry.yr, shot.geometry.zr)),
            protocol.similarity,
        )
    )
    thresholds: dict[str, Threshold] = {threshold.id: threshold for threshold in config.metrics} if config else {}
    metrics = []
    traces: list[dict[str, Any]] = []
    missing = ["FIELD_CALIBRATION_G9", "TECHNIQUE_SPECIFIC_QC", "REPEATED_SOURCE_EVIDENCE"]
    satisfied: list[str] = []
    for j, receiver in enumerate(shot.acquisition.receiver_ids):
        clip, signal_noise = clipping(shot, j, protocol), snr(shot, j, protocol)
        for item in (clip, signal_noise):
            ref = f"{shot.id}/{receiver}/{item.id}"
            threshold = thresholds.get(item.id)
            valid = item.state == "VALID" and item.value is not None
            classification = None
            if threshold is not None and threshold.unit != item.unit:
                raise ValueError(f"Unidad de umbral incompatible con {item.id}")
            if valid and threshold is not None and item.value is not None:
                classification = threshold.diagnostic_classification(item.value)
            metrics.append(
                Metric(
                    id=item.id,
                    unit=item.unit,
                    scope="trace",
                    support_refs=(ref,),
                    value=item.value,
                    applicability="APPLICABLE",
                    validity="VALID"
                    if valid
                    else "MODEL_INAPPLICABLE"
                    if item.state == "MODEL_INAPPLICABLE"
                    else "MISSING"
                    if item.state == "MISSING"
                    else "INVALID",
                    reason=item.reason,
                    mandatory=True,
                    critical=threshold.critical if threshold else False,
                    direction=threshold.direction if threshold else None,
                    threshold_ref=f"{config.profile}/{item.id}" if threshold and config else None,
                    calibration_ref=threshold.calibration_ref if threshold else None,
                    quality_status=classification,
                )
            )
            (satisfied if valid else missing).append(ref)
        traces.append(
            {
                "receiver_id": receiver,
                "channel_1based": j + 1,
                "valid_fraction": float(shot.valid_mask[j].mean()),
                "amplitude_unit": shot.acquisition.amplitude_unit,
                "statistics": statistics[j],
                "time_budget": time_budget(shot, j, protocol),
                "clip": clip.model_dump(mode="json"),
                "snr": signal_noise.model_dump(mode="json"),
                "mains": mains_line(shot, j, protocol).model_dump(mode="json"),
                "psd": noise_psd(shot, j, protocol),
            }
        )
        if similarities is not None:
            traces[-1]["similarity"] = similarities[j]
        traces[-1]["quality"] = trace_quality(traces[-1], protocol.quality_policy)
    qualities = [metric.quality_status for metric in metrics if metric.quality_status is not None]
    quality: Quality | None = (
        "FAIL" if "FAIL" in qualities else "WARN" if "WARN" in qualities else "PASS" if qualities else None
    )
    source = Path(__file__).resolve().parents[1]
    hashes = {
        p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(source.rglob("*.py"))
    }
    report = QCReport(
        scope="shot",
        metrics=tuple(metrics),
        quality_status=quality,
        evidence_status="INCOMPLETE",
        missing_requirement_ids=tuple(missing),
        satisfied_requirement_ids=tuple(satisfied),
        config_hash=canonical_hash((config, protocol)),
        data_hashes=shot.input_hashes,
        code_hash=canonical_hash(hashes),
        calibration_refs=tuple(sorted({m.calibration_ref for m in metrics if m.calibration_ref})),
        evidence_refs=(protocol.provenance,),
    )
    return {
        "schema_version": "1.4",
        "shot_id": shot.id,
        "scope": "COMMON_QC_DIAGNOSTIC_ONLY",
        "report": report.model_dump(mode="json"),
        "protocol": protocol.model_dump(mode="json"),
        "traces": traces,
        "data_quality": aggregate_quality(trace["quality"]["grade"] for trace in traces),
        "data_assessment": assess_quality(trace["quality"] for trace in traces),
        "quality_policy": protocol.quality_policy.model_dump(mode="json"),
        "eligible_for_acceptance": report.eligible_for_acceptance,
        "threshold_state": "DRAFT_DIAGNOSTIC_CANDIDATES",
        "operator_decision": "PENDING",
    }
