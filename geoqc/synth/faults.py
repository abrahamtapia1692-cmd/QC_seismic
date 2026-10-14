"""Inyección reproducible; registra el cambio, no promete detectabilidad universal."""

from __future__ import annotations

import json
from typing import Literal

import numpy as np

from geoqc.core.evidence import seeded_rng
from geoqc.core.models import Geometry, Shot

FaultKind = Literal[
    "dead",
    "clip",
    "noise",
    "polarity",
    "time_shift",
    "geometry",
    "dt",
    "hum",
    "burst",
    "coupling",
    "jitter",
    "truncation",
]


def inject_fault(
    shot: Shot, *, kind: FaultKind, channels: tuple[int, ...], severity: float, seed: int, frequency_hz: float = 50.0
) -> Shot:
    n, ns = shot.data.shape
    known = {
        "dead",
        "clip",
        "noise",
        "polarity",
        "time_shift",
        "geometry",
        "dt",
        "hum",
        "burst",
        "coupling",
        "jitter",
        "truncation",
    }
    if (
        kind not in known
        or not channels
        or len(set(channels)) != len(channels)
        or any(type(j) is not int or not 0 <= j < n for j in channels)
        or not np.isfinite(severity)
    ):
        raise ValueError("Tipo/canales/severidad explícitos y finitos requeridos")
    if severity < 0 or (kind == "dt" and severity <= -1) or (kind == "truncation" and not 0 < severity < 1):
        raise ValueError("Severidad fuera del dominio de este inyector")
    generator = seeded_rng(seed)
    data, mask = shot.data.copy(), shot.valid_mask.copy()
    reasons, dt = list(shot.mask_reasons), list(shot.dt_s)
    geometry = shot.geometry
    actual_shifts = []
    for channel in channels:
        if kind == "dead":
            data[channel] = 0
            mask[channel] = False
            reasons[channel] = ";".join(filter(None, (reasons[channel], "INJECTED_DEAD")))
        elif kind == "clip":
            data[channel] = np.clip(data[channel], -severity, severity)
        elif kind in ("noise", "burst"):
            perturbation = generator.normal(size=ns)
            if kind == "burst":
                window = np.zeros(ns)
                window[ns // 3 : 2 * ns // 3] = 1
                perturbation *= window
            else:
                perturbation -= perturbation.mean()
            perturbation *= severity / np.sqrt(np.mean(perturbation**2))
            data[channel] += perturbation
        elif kind == "polarity":
            data[channel] *= -1
        elif kind in ("time_shift", "jitter"):
            shift = severity if kind == "time_shift" else float(generator.normal(scale=severity))
            time = np.arange(ns) * dt[channel]
            sample_shift = shift / dt[channel]
            rounded = round(sample_shift)
            if np.isclose(sample_shift, rounded, rtol=0, atol=1e-12):
                old_data, old_mask = data[channel].copy(), mask[channel].copy()
                data[channel] = 0.0
                mask[channel] = False
                if 0 <= rounded < ns:
                    data[channel, rounded:] = old_data[: ns - rounded]
                    mask[channel, rounded:] = old_mask[: ns - rounded]
                elif -ns < rounded < 0:
                    data[channel, :rounded] = old_data[-rounded:]
                    mask[channel, :rounded] = old_mask[-rounded:]
            else:
                data[channel] = np.interp(time - shift, time, data[channel], left=0.0, right=0.0)
                mask[channel] = np.interp(time - shift, time, mask[channel].astype(float), left=0.0, right=0.0) >= 1
            reasons[channel] = ";".join(filter(None, (reasons[channel], "INJECTED_SHIFT_EDGE")))
            actual_shifts.append((channel, shift))
        elif kind == "geometry":
            coordinates = geometry.xr.copy()
            coordinates[channel] += severity
            geometry = Geometry.model_validate(
                geometry.model_dump()
                | {"xr": coordinates, "provenance": (*geometry.provenance, "injected coordinate error")}
            )
        elif kind == "dt":
            dt[channel] *= 1 + severity
        elif kind == "hum":
            if not np.isfinite(frequency_hz) or not 0 < frequency_hz < 1 / (2 * dt[channel]):
                raise ValueError("Hum fuera de banda de Nyquist")
            phase = generator.uniform(0.0, 2 * np.pi)
            data[channel] += severity * np.sin(2 * np.pi * frequency_hz * np.arange(ns) * dt[channel] + phase)
        elif kind == "coupling":
            data[channel] *= severity
        elif kind == "truncation":
            start = int(np.floor(ns * (1 - severity)))
            data[channel, start:] = np.nan
            mask[channel, start:] = False
            reasons[channel] = ";".join(filter(None, (reasons[channel], "INJECTED_TRUNCATION")))
    headers = json.loads(shot.headers_json)
    headers.setdefault("synthetic_faults", []).append(
        {
            "kind": kind,
            "channels": channels,
            "severity": severity,
            "seed": seed,
            "frequency_hz": frequency_hz if kind == "hum" else None,
            "actual_shifts_s": actual_shifts,
            "interpretation": "controlled perturbation; coupling denotes apparent amplitude change only",
        }
    )
    return Shot.model_validate(
        shot.model_dump(exclude={"data", "valid_mask", "geometry"})
        | {
            "data": data,
            "valid_mask": mask,
            "mask_reasons": tuple(reasons),
            "dt_s": tuple(dt),
            "geometry": geometry,
            "headers_json": json.dumps(headers, allow_nan=False),
        }
    )
