from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from geoqc.masw.union import merge_curves as merge_curves


def refine_peak_velocities(
    scores: npt.ArrayLike, frequencies_hz: npt.ArrayLike, velocities_ms: npt.ArrayLike, indices: tuple[int, ...]
) -> Any:
    score, f, c = np.asarray(scores, float), np.asarray(frequencies_hz, float), np.asarray(velocities_ms, float)
    if score.shape != (f.size, c.size) or len(indices) != f.size or np.any(c <= 0):
        raise ValueError("Picos/rejillas alineados requeridos")
    result = c[list(indices)].copy()
    for i, j in enumerate(indices):
        if 0 < j < c.size - 1 and score[i, j] >= max(score[i, j - 1], score[i, j + 1]):
            q = f[i] / c[j - 1 : j + 2]
            centered = q - q[1]
            a, b, _ = np.polyfit(centered, score[i, j - 1 : j + 2], 2)
            if a < 0:
                peak = q[1] - b / (2 * a)
                if min(q) <= peak <= max(q) and peak > 0:
                    result[i] = f[i] / peak
    return result


def ridge_path(
    scores: npt.ArrayLike,
    frequencies_hz: npt.ArrayLike,
    velocities_ms: npt.ArrayLike,
    *,
    slope_scale_ms_per_hz: float = 30,
    penalty: float = 0.02,
) -> tuple[int, ...]:
    score, f, c = np.asarray(scores, float), np.asarray(frequencies_hz, float), np.asarray(velocities_ms, float)
    if (
        score.shape != (f.size, c.size)
        or not f.size
        or not c.size
        or np.any(np.diff(f) <= 0)
        or not all(np.all(np.isfinite(a)) for a in (score, f, c))
        or slope_scale_ms_per_hz <= 0
        or penalty < 0
    ):
        raise ValueError("DP requiere scores finitos, f creciente y penalización dimensional válida")
    cost = -score[0]
    back = np.zeros((f.size, c.size), dtype=int)
    for i in range(1, f.size):
        slope = (c[:, None] - c[None, :]) / ((f[i] - f[i - 1]) * slope_scale_ms_per_hz)
        previous = cost[:, None] + penalty * slope**2
        back[i] = np.argmin(previous, axis=0)
        cost = np.min(previous, axis=0) - score[i]
    path = [int(np.argmin(cost))]
    for i in range(f.size - 1, 0, -1):
        path.append(int(back[i, path[-1]]))
    return tuple(reversed(path))


def contiguous_bands(
    frequencies_hz: npt.ArrayLike,
    valid: npt.ArrayLike,
    *,
    max_gap_hz: float,
    support_refs: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    f, mask = np.asarray(frequencies_hz, float), np.asarray(valid)
    if (
        f.ndim != 1
        or mask.dtype != bool
        or mask.shape != f.shape
        or np.any(f <= 0)
        or np.any(np.diff(f) <= 0)
        or not np.all(np.isfinite(f))
        or max_gap_hz <= 0
    ):
        raise ValueError("Banda requiere frecuencias positivas crecientes, máscara bool y gap>0")
    support = ("UNSPECIFIED",) * f.size if support_refs is None else support_refs
    if len(support) != f.size:
        raise ValueError("Soporte por punto requerido")
    groups: list[list[int]] = []
    for i in np.flatnonzero(mask):
        if (
            not groups
            or i != groups[-1][-1] + 1
            or f[i] - f[groups[-1][-1]] > max_gap_hz
            or support[i] != support[groups[-1][-1]]
        ):
            groups.append([])
        groups[-1].append(int(i))
    return [
        {
            "indices": g,
            "f_bounds_hz": [float(f[g[0]]), float(f[g[-1]])],
            "octaves": float(np.log2(f[g[-1]] / f[g[0]])),
            "support_ref": support[g[0]],
        }
        for g in groups
    ]


def near_ratios(offsets_m: npt.ArrayLike, wavelengths_m: npt.ArrayLike) -> dict[str, Any]:
    r, wavelength = np.asarray(offsets_m, float), np.asarray(wavelengths_m, float)
    if (
        r.ndim != 1
        or not r.size
        or np.any(r < 0)
        or np.any(wavelength <= 0)
        or not all(np.all(np.isfinite(v)) for v in (r, wavelength))
    ):
        raise ValueError("Offsets radiales >=0 y longitudes de onda positivas")
    return {
        "near_offset_ratio": (np.min(r) / wavelength).tolist(),
        "NACD_center": (np.mean(r) / wavelength).tolist(),
        "validity": "GEOMETRIC_ATTRIBUTE_ONLY",
    }


def repeatability(curves_ms: npt.ArrayLike) -> dict[str, Any]:
    values = np.asarray(curves_ms, float)
    if values.ndim != 2 or values.shape[0] < 2 or not np.all(np.isfinite(values)) or np.any(values <= 0):
        raise ValueError("Réplicas positivas en soporte/modalidad común verificados")
    mean = values.mean(axis=0)
    return {
        "mean_ms": mean.tolist(),
        "std_shots_ms": values.std(axis=0, ddof=1).tolist(),
        "repeatability_cov": (values.std(axis=0, ddof=1) / mean).tolist(),
        "cause_candidates": ["source", "modal composition", "lateral variation", "instrument"],
        "precision_cov": None,
    }
