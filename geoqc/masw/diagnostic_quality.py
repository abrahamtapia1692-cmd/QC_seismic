"""Atributos de cresta aparente: utilidad diagnóstica, sin confianza modal/operativa.

El fondo de I(q) y su contraste NO son potencia de ruido ni SNR. El cambio entre
variantes NO es sigma. El dominio de kernel de esta versión es uniforme completo.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal

import numpy as np
import numpy.typing as npt
from pydantic import Field
from scipy.signal import find_peaks

from geoqc.core.models import FrozenModel

Fraction = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class UsabilityPolicy(FrozenModel):
    id: Literal["MASW_APPARENT_USABILITY_V1_DRAFT"] = "MASW_APPARENT_USABILITY_V1_DRAFT"
    calibration_state: Literal["DRAFT_NOT_FIELD_CALIBRATED"] = "DRAFT_NOT_FIELD_CALIBRATED"
    coherence_min: Fraction = 0.60
    contrast_min: Fraction = 0.25
    competitor_ratio_max: Fraction = 0.80
    sensitivity_max_rel: Fraction = 0.05
    amplitude_floor_rel: Annotated[float, Field(gt=0, lt=1)] = 1e-6
    q_samples_per_null: Annotated[int, Field(ge=24, le=192, strict=True)] = 24


class RidgeQuality(FrozenModel):
    frequency_hz: float
    grade: Literal["UTILIZABLE", "REVISAR", "NO_UTILIZABLE", "NO_EVALUABLE"]
    reasons: tuple[str, ...]
    coherence: float | None = None
    background_coherence: float | None = None
    contrast: float | None = None
    competitor_ratio: float | None = None
    competitor_q_m_inv: float | None = None
    sensitivity_rel: float | None = None
    exclusion_radius_q_m_inv: float | None = None
    active_channel_ids: tuple[int, ...]
    metric_unit: Literal["1"] = "1"
    mode_identity: Literal["APPARENT"] = "APPARENT"
    source_attribution: Literal["NOT_ESTABLISHED"] = "NOT_ESTABLISHED"
    eligible_for_acceptance: Literal[False] = False


def classify_metrics(metrics: Mapping[str, float | None], policy: UsabilityPolicy) -> tuple[str, ...]:
    reasons = []
    for key, limit, lower, reason in (
        ("coherence", policy.coherence_min, True, "LOW_COHERENCE"),
        ("contrast", policy.contrast_min, True, "LOW_CONTRAST"),
        ("competitor_ratio", policy.competitor_ratio_max, False, "COMPETING_PEAK"),
        ("sensitivity_rel", policy.sensitivity_max_rel, False, "PROCESSING_SENSITIVE"),
    ):
        value = metrics.get(key)
        if value is None or not np.isfinite(value):
            reasons.append("METRIC_MISSING")
        elif (lower and value < limit) or (not lower and value > limit):
            reasons.append(reason)
    return tuple(dict.fromkeys(reasons))


def assess_ridges(
    spectrum: npt.ArrayLike,
    frequencies_hz: npt.ArrayLike,
    x_m: npt.ArrayLike,
    velocities_ms: npt.ArrayLike,
    variant_velocities_ms: npt.ArrayLike,
    policy: UsabilityPolicy,
) -> tuple[RidgeQuality, ...]:
    """Buscar competidores en TODO el dominio q firmado, no solo la rejilla c>0.

    Variantes NaN representan soporte ausente, sin imputación de estabilidad.
    Las exclusiones de canales se conservan; no se usa N_activo dx ante huecos.
    """
    u, f, x, c, variants = (
        np.asarray(spectrum, complex),
        np.asarray(frequencies_hz, float),
        np.asarray(x_m, float),
        np.asarray(velocities_ms, float),
        np.asarray(variant_velocities_ms, float),
    )
    if (
        f.ndim != 1
        or not f.size
        or x.ndim != 1
        or x.size < 2
        or u.shape != (f.size, x.size)
        or c.shape != f.shape
        or variants.ndim != 2
        or variants.shape[1] != f.size
        or not all(np.all(np.isfinite(a)) for a in (u, f, x, c))
        or np.any(f <= 0)
        or np.any(c <= 0)
        or np.any(np.diff(f) <= 0)
        or np.unique(x).size != x.size
        or np.any(np.isinf(variants))
        or np.any(variants[np.isfinite(variants)] <= 0)
    ):
        raise ValueError("Espectros finitos, frecuencias/velocidades positivas y variantes alineadas requeridos")
    policy = UsabilityPolicy.model_validate(policy.model_dump())
    order = np.argsort(x)
    x, u = x[order], u[:, order]
    dx = float(x[1] - x[0])
    uniform = bool(np.allclose(np.diff(x), dx, rtol=1e-12, atol=0))
    magnitude = abs(u)
    active = (magnitude > magnitude.max(axis=0) * policy.amplitude_floor_rel) & (magnitude > 0)
    n = x.size
    width = 1 / (n * dx)
    qn = 1 / (2 * dx)
    q = np.linspace(-qn, qn, n * policy.q_samples_per_null + 1)
    steering = np.exp(2j * np.pi * q[:, None] * (x - x[0]))
    results = []
    for j, frequency in enumerate(f):
        ids = tuple(int(order[k]) + 1 for k in np.flatnonzero(active[j]))
        common = dict(frequency_hz=float(frequency), active_channel_ids=ids)
        if len(ids) < 2:
            results.append(
                RidgeQuality.model_validate(common | dict(grade="NO_UTILIZABLE", reasons=("NO_SPECTRAL_SUPPORT",)))
            )
            continue
        if not uniform or not active[j].all():
            results.append(
                RidgeQuality.model_validate(common | dict(grade="NO_EVALUABLE", reasons=("KERNEL_UNSUPPORTED",)))
            )
            continue
        normalized = u[j] / magnitude[j]
        score = np.clip(abs(steering @ normalized) / n, 0, 1)
        q0 = float(frequency / c[j])
        peak = float(np.clip(abs(np.exp(2j * np.pi * q0 * (x - x[0])) @ normalized) / n, 0, 1))
        outside = abs(q - q0) >= width
        background = float(np.median(score[outside])) if outside.any() else None
        peaks, _ = find_peaks(score)
        peaks = np.unique(np.concatenate(([0], peaks, [q.size - 1])))
        competitors = peaks[outside[peaks]]
        rival = int(competitors[np.argmax(score[competitors])]) if competitors.size else None
        ratio = float(score[rival] / peak) if rival is not None and peak > 0 else None
        sensitivity = (
            float(np.max(abs(variants[:, j] - c[j]) / c[j]))
            if variants.shape[0] and np.all(np.isfinite(variants[:, j]))
            else None
        )
        metrics = dict(
            coherence=peak,
            contrast=None if background is None else peak - background,
            competitor_ratio=ratio,
            sensitivity_rel=sensitivity,
        )
        reasons = list(classify_metrics(metrics, policy))
        if q0 >= qn:
            reasons.append("NYQUIST_LIMIT")
        elif q0 + width >= qn:
            reasons.append("LOBE_AT_NYQUIST")
        if q0 <= width:
            reasons.append("DIRECTION_UNRESOLVED")
        if sensitivity is None:
            reasons.append("VARIANTS_MISSING")
        results.append(
            RidgeQuality.model_validate(
                common
                | metrics
                | dict(
                    background_coherence=background,
                    competitor_q_m_inv=None if rival is None else float(q[rival]),
                    exclusion_radius_q_m_inv=width,
                    grade="NO_EVALUABLE" if sensitivity is None else "REVISAR" if reasons else "UTILIZABLE",
                    reasons=tuple(reasons) if reasons else ("INTERNAL_CHECKS_PASSED",),
                )
            )
        )
    return tuple(results)
