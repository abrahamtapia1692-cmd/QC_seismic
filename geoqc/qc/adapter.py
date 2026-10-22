"""Trace QC composition using native diagnostics and explicit optional protocols."""
from __future__ import annotations

from typing import Any, Self

import numpy as np
from pydantic import Field, model_validator

from geoqc.core.config import ProjectConfig
from geoqc.core.models import FrozenModel, Shot
from geoqc.qc.contracts import QCProtocol, Window
from geoqc.qc.noise import (
    NoiseProtocol,
    digital_integrity,
    low_frequency_coherence,
    noise_diagnostics,
    samples_in_window,
)
from geoqc.qc.operational import OperationalPolicy, aggregate_screening, screen_traces
from geoqc.qc.quality import aggregate_quality, assess_quality, trace_quality
from geoqc.qc.report import common_qc


class TraceQCRequest(FrozenModel):
    protocol: QCProtocol
    noise: NoiseProtocol | None = None
    config: ProjectConfig | None = None
    operational_policy: OperationalPolicy | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def same_windows(self) -> Self:
        if self.noise is not None and (
            self.noise.noise != self.protocol.noise or self.noise.signal != self.protocol.signal
        ):
            raise ValueError("QC y diagnóstico de ruido requieren las mismas ventanas explícitas")
        return self


def waveform_preview(shot: Shot, channel: int, bins: int = 128) -> dict[str, Any]:
    """Actual min/max samples in temporal order; masked bins break the display line."""
    data, mask = shot.data[channel], shot.valid_mask[channel]
    points: list[list[Any]] = []
    for indices in np.array_split(np.arange(data.size), min(bins, data.size)):
        if not np.all(mask[indices]) or not np.all(np.isfinite(data[indices])):
            points.append([int(indices[0]), None])
            continue
        lo = int(indices[np.argmin(data[indices])])
        hi = int(indices[np.argmax(data[indices])])
        points.extend([[i, float(data[i])] for i in sorted({lo, hi})])
    return {"method": "MIN_MAX_ENVELOPE_DISPLAY_ONLY", "sample_count": int(data.size),
            "dt_s": shot.dt_s[channel], "t0_s": shot.t0_s[channel], "points": points}


def trace_qc(shot: Shot, request: TraceQCRequest | None = None) -> dict[str, Any]:
    supplied = request is not None
    if request is None:
        request = TraceQCRequest(protocol=QCProtocol(
            analysis=Window(start_s=min(shot.t0_s), end_s=max(
                t0 + shot.data.shape[1] * dt for t0, dt in zip(shot.t0_s, shot.dt_s, strict=True))),
            provenance="Full-record time envelope from sample clocks; integrity-only fallback. "
                       "No noise, signal, amplitude or channel-comparability assumptions supplied."))
    result = common_qc(shot, request.protocol, request.config)
    for j, trace in enumerate(result["traces"]):
        trace["integrity"] = digital_integrity(shot.data[j], shot.dt_s[j])
        if request.noise is not None:
            trace["noise_diagnostics"] = noise_diagnostics(
                shot.data[j], shot.valid_mask[j], shot.dt_s[j], shot.t0_s[j], request.noise)
        trace["quality"] = trace_quality(trace, request.protocol.quality_policy)
        trace["waveform_preview"] = waveform_preview(shot, j)
    result["data_quality"] = aggregate_quality(t["quality"]["grade"] for t in result["traces"])
    result["data_assessment"] = assess_quality(t["quality"] for t in result["traces"])
    if request.operational_policy is not None:
        if shot.acquisition.technique != "TRS":
            raise ValueError("La política diagnóstica por muestras requiere TRS")
        screen_traces(shot, request.protocol, result["traces"], request.operational_policy)
        result["operational_assessment"] = aggregate_screening(result["traces"], request.operational_policy.id)
    coherence = []
    if request.noise:
        for j in range(shot.data.shape[0] - 1):
            windows = [samples_in_window(shot.data[k], shot.valid_mask[k], shot.dt_s[k],
                       shot.t0_s[k], request.noise.noise) for k in (j, j + 1)]
            a, b = windows
            if a is None or b is None or a.shape != b.shape or shot.dt_s[j] != shot.dt_s[j + 1]:
                diagnostic = {"state": "MISSING", "value": None, "reason": "Ventanas o relojes sin soporte común"}
            elif request.noise.low_band_hz[1] >= 1 / (2 * shot.dt_s[j]):
                diagnostic = {"state": "MODEL_INAPPLICABLE", "value": None, "reason": "Banda fuera de Nyquist"}
            else:
                diagnostic = low_frequency_coherence(a, b, shot.dt_s[j], request.noise.low_band_hz)
            coherence.append({"receiver_ids": list(shot.acquisition.receiver_ids[j:j + 2]), **diagnostic})
    return result | {"integration_version": "trace-qc-1", "request": request.model_dump(mode="json"),
                     "noise_coherence": coherence,
                     "protocol_source": "DECLARED" if supplied else "FULL_RECORD_INTEGRITY_ONLY",
                     "project_config_supplied": request.config is not None,
                     "methodology": {
                         "integrity": "EXECUTED", "snr_clipping": "EXECUTED_WITH_APPLICABILITY_GUARDS",
                         "noise": "EXECUTED_CONDITIONAL" if request.noise else "NOT_REQUESTED",
                         "similarity": "EXECUTED_WITH_APPLICABILITY_GUARDS" if request.protocol.similarity else "NOT_REQUESTED",
                         "filtering": "NOT_APPLIED_RAW_PRESERVED",
                         "repeatability": "NOT_REQUESTED_REQUIRES_SOURCE_GROUPS",
                         "reciprocity": "NOT_REQUESTED_REQUIRES_PHYSICAL_PAIRS"}}
