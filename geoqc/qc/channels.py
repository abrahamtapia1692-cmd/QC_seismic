from __future__ import annotations

import json

import numpy as np

from geoqc.core.models import BoolArray, FloatArray, Shot
from geoqc.qc.contracts import Diagnostic, QCProtocol, Window


def diagnostic(id: str, state: str, unit: str, reason: str, **fields: object) -> Diagnostic:
    return Diagnostic.model_validate({"id": id, "state": state, "unit": unit, "reason": reason, **fields})


def window_samples(shot: Shot, channel: int, window: Window) -> tuple[FloatArray, BoolArray]:
    """No comprime huecos ni rellena ventanas fuera del registro."""
    dt, t0 = shot.dt_s[channel], shot.t0_s[channel]
    lo = int(np.ceil((window.start_s - t0) / dt - 1e-9))
    hi = int(np.ceil((window.end_s - t0) / dt - 1e-9))
    if lo < 0 or hi > shot.data.shape[1] or hi - lo < 2:
        return np.empty(0), np.empty(0, dtype=bool)
    return shot.data[channel, lo:hi], shot.valid_mask[channel, lo:hi]


def channel_statistics(shot: Shot, protocol: QCProtocol) -> tuple[dict[str, object], ...]:
    n = shot.data.shape[0]
    expected = protocol.expected_relative_amplitude
    if expected is not None and len(expected) != n:
        raise ValueError("Modelo de amplitud no coincide con canales")
    rows: list[dict[str, object]] = []
    rms = np.full(n, np.nan)
    for j in range(n):
        data, mask = window_samples(shot, j, protocol.analysis)
        valid = data[mask]
        if valid.size < 2:
            rows.append(
                {"state": "MISSING", "reason": "Menos de dos muestras válidas", "valid_samples": int(valid.size)}
            )
            continue
        dc = float(np.mean(valid))
        centered = valid - dc
        rms[j] = float(np.sqrt(np.mean(centered**2)))
        rows.append(
            {
                "state": "VALID",
                "valid_samples": int(valid.size),
                "dc": dc,
                "rms_ac": rms[j],
                "rms_total": float(np.sqrt(np.mean(valid**2))),
                "zero_fraction": float(np.mean(valid == 0)),
                "constant": bool(np.all(valid == valid[0])),
                "dead": bool(np.all(valid == 0)),
                "mad": float(np.median(abs(valid - np.median(valid)))),
                "amplitude_anomaly": None,
                "amplitude_reason": "Modelo comparable de propagación/gain ausente",
            }
        )
    positive = np.isfinite(rms) & (rms > 0)
    if expected is not None and np.count_nonzero(positive) >= 3:
        normalized = rms[positive] / np.asarray(expected)[positive]
        logs = np.log(normalized)
        median = float(np.median(logs))
        mad = float(np.median(abs(logs - median)))
        # Un MAD casi nulo no divide por cero ni convierte redondeo en una anomalía.
        for index, residual in zip(np.flatnonzero(positive), logs - median, strict=True):
            ratio = float(np.exp(residual))
            score = None if mad <= 1e-12 else float(abs(residual) / (1.4826 * mad))
            outside = ratio < protocol.amplitude_ratio_bounds[0] or ratio > protocol.amplitude_ratio_bounds[1]
            rows[index].update(
                normalized_amplitude_ratio=ratio,
                log_mad_score=score,
                amplitude_anomaly=outside and (score is None or score > protocol.log_mad_limit),
                amplitude_reason="Residual respecto a modelo declarado; causa no identificada",
                mad_branch="ZERO_OR_ROUNDOFF" if score is None else "ROBUST_LOG_RMS",
            )
    return tuple(rows)


def clipping(shot: Shot, channel: int, protocol: QCProtocol) -> Diagnostic:
    data, mask = window_samples(shot, channel, protocol.analysis)
    valid = data[mask]
    if valid.size < 2:
        return diagnostic("clip", "MISSING", "fraction", "Ventana sin soporte válido")
    acquisition = shot.acquisition
    if acquisition.adc_rails is None or protocol.rail_scale_to_data is None:
        # Dos plateaus en extremos y predominio de saltos son solo sospecha.
        scale = float(np.ptp(valid))
        diffs = np.diff(data)
        pairs = mask[:-1] & mask[1:]
        flat = (diffs == 0) & pairs
        runs = flat[:-1] & flat[1:]
        at_low = data[1:-1] == np.min(valid)
        at_high = data[1:-1] == np.max(valid)
        suspect = scale > 0 and np.count_nonzero(runs & at_low) >= 2 and np.count_nonzero(runs & at_high) >= 2
        return diagnostic(
            "clip",
            "MISSING",
            "fraction",
            "Rails/escala desconocidos; sospecha morfológica no confirma clipping",
            details_json=json.dumps({"suspected": bool(suspect), "confirmed": False}),
        )
    if acquisition.stack_count > 1 and acquisition.stack_kind in ("SUM", "UNKNOWN"):
        return diagnostic("clip", "MODEL_INAPPLICABLE", "fraction", "Stack agregado oculta saturación por réplica")
    if acquisition.stack_count > 1:
        return diagnostic("clip", "MODEL_INAPPLICABLE", "fraction", "Promedio no permite certificar rails de réplicas")
    scale_to_data = protocol.rail_scale_to_data
    if isinstance(scale_to_data, tuple):
        if len(scale_to_data) != shot.data.shape[0]:
            raise ValueError("Escala ADC por canal no coincide con receptores")
        channel_scale = scale_to_data[channel]
    else:
        channel_scale = scale_to_data
    lo, hi = np.asarray(acquisition.adc_rails) * channel_scale
    if protocol.rail_tolerance >= (hi - lo) / 2:
        raise ValueError("Tolerancia de rail debe ser menor a medio rango ADC")
    if np.any(valid < lo - protocol.rail_tolerance) or np.any(valid > hi + protocol.rail_tolerance):
        return diagnostic("clip", "INVALID", "fraction", "Muestras fuera de rails: escala/gain inconsistentes")
    phi = float(np.mean((abs(valid - lo) <= protocol.rail_tolerance) | (abs(valid - hi) <= protocol.rail_tolerance)))
    return diagnostic(
        "clip",
        "VALID",
        "fraction",
        "Fracción junto a rails conocidos; denominador de muestras válidas",
        value=phi,
        flagged=phi > 0,
        details_json=json.dumps({"valid_samples": int(valid.size), "rails_in_data_unit": [float(lo), float(hi)]}),
    )
