from __future__ import annotations

import itertools
import math

import numpy as np
from scipy.optimize import least_squares

from geoqc.core.models import FloatArray


def layered_first_times(
    offsets_m: FloatArray, velocities_ms: tuple[float, ...], thicknesses_m: tuple[float, ...]
) -> FloatArray:
    """Envolvente de ramas físicamente accesibles; capas isotrópicas horizontales."""
    x = np.asarray(offsets_m, dtype=float)
    v, h = np.asarray(velocities_ms), np.asarray(thicknesses_m)
    if x.ndim != 1 or len(v) != len(h) + 1 or not np.all(np.isfinite(x)) or np.any(x < 0):
        raise ValueError("Offsets no negativos y h por capa finita requeridos")
    if not np.all(np.isfinite(v)) or not np.all(np.isfinite(h)) or np.any(v <= 0) or np.any(h <= 0):
        raise ValueError("Velocidades/espesores finitos positivos requeridos")
    branches = [x / v[0]]
    for j in range(1, len(v)):
        if np.any(v[:j] >= v[j]):
            continue
        angles = np.arcsin(v[:j] / v[j])
        critical = float(np.sum(2 * h[:j] * np.tan(angles)))
        intercept = float(np.sum(2 * h[:j] / v[:j] * np.cos(angles)))
        branches.append(np.where(x >= critical, intercept + x / v[j], np.inf))
    return np.asarray(np.min(branches, axis=0), dtype=float)


def _input(
    offsets: FloatArray, times: FloatArray, sigma: FloatArray | None, minimum: int
) -> tuple[FloatArray, FloatArray, FloatArray | None]:
    x, y = np.asarray(offsets, dtype=float), np.asarray(times, dtype=float)
    if (
        x.ndim != 1
        or x.shape != y.shape
        or x.size < minimum
        or not np.all(np.isfinite(x))
        or not np.all(np.isfinite(y))
    ):
        raise ValueError("Tiempo-distancia requiere vectores finitos suficientes")
    order = np.argsort(x)
    x, y = x[order], y[order]
    if np.any(np.diff(x) <= 0) or np.any(x < 0):
        raise ValueError("Separar lados y consolidar offsets repetidos antes del ajuste")
    s = None if sigma is None else np.asarray(sigma, dtype=float)
    if s is not None:
        if s.shape != y.shape or not np.all(np.isfinite(s)) or np.any(s <= 0):
            raise ValueError("Sigmas conocidas positivas por observación")
        s = s[order]
    return x, y, s


def fit_branches(
    offsets_m: FloatArray,
    times_s: FloatArray,
    *,
    sigma_s: FloatArray | None = None,
    max_segments: int = 3,
    minimum_points: int = 5,
    variance_floor_s2: float = 1e-16,
    continuity: str = "CONTINUOUS",
    gaussian_error_model: bool = True,
) -> dict[str, object]:
    if not gaussian_error_model:
        return {"state": "MODEL_INAPPLICABLE", "reason": "BIC gaussiano no válido para pérdidas robustas"}
    if continuity != "CONTINUOUS":
        return {"state": "MODEL_INAPPLICABLE", "reason": "Saltos requieren otro modelo y conteo de parámetros"}
    if (
        max_segments not in (1, 2, 3)
        or minimum_points < 3
        or not math.isfinite(variance_floor_s2)
        or variance_floor_s2 <= 0
    ):
        raise ValueError("K=1..3, mínimos y piso de varianza explícitos")
    x, y, sigma = _input(offsets_m, times_s, sigma_s, minimum_points)
    weights = np.ones_like(y) if sigma is None else 1 / sigma
    candidates = []
    for segments in range(1, max_segments + 1):
        if x.size < segments * minimum_points:
            continue
        starts: list[tuple[int, ...]]
        if segments == 1:
            starts = [()]
        else:
            # Multistart independiente de etiquetas: cuantiles y rejilla gruesa de offsets.
            slots = np.linspace(minimum_points, x.size - minimum_points, 9, dtype=int)
            starts = list(itertools.combinations([int(slot) for slot in np.unique(slots)], segments - 1))
        best = None
        for start in starts:
            initial_knots = np.array([(x[i - 1] + x[i]) / 2 for i in start])

            def solve(knots: FloatArray) -> tuple[FloatArray, FloatArray]:
                knots = np.sort(knots)
                matrix = np.column_stack([np.ones_like(x), x, *(np.maximum(x - knot, 0) for knot in knots)])
                coefficients = np.linalg.lstsq(matrix * weights[:, None], y * weights, rcond=None)[0]
                return coefficients, matrix @ coefficients - y

            if segments > 1:
                optimized = least_squares(
                    lambda knots: solve(knots)[1] * weights,
                    initial_knots,
                    bounds=(x[minimum_points - 1], x[-minimum_points]),
                    max_nfev=80,
                    ftol=1e-12,
                    xtol=1e-12,
                    gtol=1e-12,
                )
                knots = np.sort(optimized.x)
            else:
                knots = np.empty(0)
            coefficients, residual = solve(knots)
            groups = np.searchsorted(knots, x, side="right")
            group_counts = np.bincount(groups, minlength=segments)
            slopes = np.cumsum(np.r_[coefficients[1], coefficients[2:]])
            if np.any(group_counts < minimum_points) or np.any(slopes <= 0):
                continue
            rss = float(np.sum(residual**2))
            parameters = 2 * segments + int(sigma is None)
            if sigma is None:
                variance = max(rss / x.size, variance_floor_s2)
                neg2loglik = x.size * math.log(2 * math.pi * variance) + rss / variance
            else:
                neg2loglik = float(np.sum((residual / sigma) ** 2 + np.log(2 * np.pi * sigma**2)))
            bic = neg2loglik + parameters * math.log(x.size)
            record = {
                "segments": segments,
                "parameters": parameters,
                "bic": bic,
                "rss_s2": rss,
                "slopes_s_per_m": slopes.tolist(),
                "velocities_ms": (1 / slopes).tolist(),
                "breakpoints_m": knots.tolist(),
                "coefficients": coefficients.tolist(),
                "points_per_branch": group_counts.tolist(),
                "neg2loglik": neg2loglik,
            }
            if best is None or bic < best["bic"]:
                best = record
        if best is not None:
            candidates.append(best)
    if not candidates:
        return {"state": "MODEL_INAPPLICABLE", "reason": "Ramas sin soporte mínimo/pendiente positiva"}
    selected = min(candidates, key=lambda record: record["bic"])
    return {
        "state": "VALID",
        "selected": selected,
        "candidates": candidates,
        "reason": "Ramas visibles, no número de capas; BIC gaussiano y mínimos explícitos",
        "depth_identifiable": False,
        "eligible_for_acceptance": False,
    }


def horizontal_two_layer_parameters(fit: dict[str, object], *, model_verified: bool) -> dict[str, object]:
    if not model_verified or fit.get("state") != "VALID":
        return {"state": "MODEL_INAPPLICABLE", "reason": "Modelo horizontal dos capas no verificado"}
    selected = fit["selected"]
    if not isinstance(selected, dict) or selected["segments"] != 2:
        return {"state": "MODEL_INAPPLICABLE", "reason": "No hay dos ramas observables"}
    v1, v2 = selected["velocities_ms"]
    intercept0, _, change = selected["coefficients"]
    ti = intercept0 - change * selected["breakpoints_m"][0]
    if v2 <= v1 or ti <= 0:
        return {"state": "MODEL_INAPPLICABLE", "reason": "Modelo de refracción 0<V1<V2 no aplicable"}
    h = ti * v1 / (2 * math.sqrt(1 - (v1 / v2) ** 2))
    return {
        "state": "VALID",
        "v1_ms": v1,
        "v2_ms": v2,
        "intercept_s": ti,
        "thickness_m": h,
        "reason": "Estimación condicional; capas equivalentes/ocultas no excluidas",
    }


def robust_line(
    offsets_m: FloatArray, times_s: FloatArray, *, sigma_s: float, threshold_sigma: float = 6
) -> dict[str, object]:
    if not math.isfinite(sigma_s) or sigma_s <= 0 or not math.isfinite(threshold_sigma) or threshold_sigma <= 0:
        raise ValueError("Sigma y umbral robusto positivos")
    x, y, _ = _input(offsets_m, times_s, None, 5)
    i, j = np.triu_indices(x.size, 1)
    slope = float(np.median((y[j] - y[i]) / (x[j] - x[i])))
    intercept = float(np.median(y - slope * x))
    outliers = abs(y - (intercept + slope * x)) > threshold_sigma * sigma_s
    for _ in range(3):
        keep = ~outliers
        if np.count_nonzero(keep) < 5:
            return {"state": "MODEL_INAPPLICABLE", "reason": "Soporte robusto insuficiente"}
        matrix = np.column_stack([np.ones(np.count_nonzero(keep)), x[keep]])
        intercept, slope = np.linalg.lstsq(matrix, y[keep], rcond=None)[0]
        outliers = abs(y - (intercept + slope * x)) > threshold_sigma * sigma_s
    return {
        "state": "VALID",
        "slope_s_per_m": float(slope),
        "intercept_s": float(intercept),
        "outlier_mask_sorted_offsets": outliers.tolist(),
        "bic": None,
        "reason": "Theil-Sen inicial y rechazo explícito; no hereda likelihood BIC gaussiano",
    }
