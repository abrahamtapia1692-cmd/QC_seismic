from __future__ import annotations

import heapq
import math

import numpy as np

from geoqc.core.models import FloatArray


def solve_eikonal(
    speed_ms: FloatArray, *, spacing_m: float, initial_times_s: dict[tuple[int, int], float]
) -> FloatArray:
    """FMM de primer orden, acepta frente inicial explícito y semillas subnodo."""
    v = np.asarray(speed_ms, dtype=float)
    if v.ndim != 2 or min(v.shape) < 2 or np.any(v <= 0) or not np.all(np.isfinite(v)):
        raise ValueError("Malla 2D de velocidades positivas finitas")
    if not math.isfinite(spacing_m) or spacing_m <= 0 or not initial_times_s:
        raise ValueError("Paso y frente inicial explícitos requeridos")
    times = np.full(v.shape, np.inf)
    known = np.zeros(v.shape, dtype=bool)
    queue: list[tuple[float, int, int]] = []
    for (i, j), arrival in initial_times_s.items():
        if type(i) is not int or type(j) is not int or not 0 <= i < v.shape[0] or not 0 <= j < v.shape[1]:
            raise ValueError("Nodo inicial fuera de dominio")
        if not math.isfinite(arrival) or arrival < 0:
            raise ValueError("Tiempo inicial finito no negativo")
        times[i, j] = arrival
        heapq.heappush(queue, (arrival, i, j))
    while queue:
        time, i, j = heapq.heappop(queue)
        if known[i, j] or time > times[i, j]:
            continue
        known[i, j] = True
        for ii, jj in ((i - 1, j), (i + 1, j), (i, j - 1), (i, j + 1)):
            if not 0 <= ii < v.shape[0] or not 0 <= jj < v.shape[1] or known[ii, jj]:
                continue
            tx = min((times[ii, c] for c in (jj - 1, jj + 1) if 0 <= c < v.shape[1] and known[ii, c]), default=np.inf)
            tz = min((times[r, jj] for r in (ii - 1, ii + 1) if 0 <= r < v.shape[0] and known[r, jj]), default=np.inf)
            low, high = min(tx, tz), max(tx, tz)
            step = spacing_m / v[ii, jj]
            trial = (
                low + step
                if high - low >= step
                else (low + high + math.sqrt(max(0, 2 * step**2 - (high - low) ** 2))) / 2
            )
            if trial < times[ii, jj]:
                times[ii, jj] = trial
                heapq.heappush(queue, (float(trial), ii, jj))
    return times


def point_source_forward(
    speed_ms: FloatArray,
    *,
    spacing_m: float,
    source_xz_m: tuple[float, float],
    origin_xz_m: tuple[float, float] = (0, 0),
) -> FloatArray:
    v = np.asarray(speed_ms, dtype=float)
    if v.ndim != 2 or min(v.shape) < 2 or np.any(v <= 0) or not np.all(np.isfinite(v)) or spacing_m <= 0:
        raise ValueError("Malla y paso positivos finitos")
    if not all(math.isfinite(value) for value in (*source_xz_m, *origin_xz_m, spacing_m)):
        raise ValueError("Fuente/origen/paso finitos")
    xf = (source_xz_m[0] - origin_xz_m[0]) / spacing_m
    zf = (source_xz_m[1] - origin_xz_m[1]) / spacing_m
    if not 0 <= xf <= v.shape[1] - 1 or not 0 <= zf <= v.shape[0] - 1:
        raise ValueError("Fuente fuera del dominio de malla")
    columns, rows = {math.floor(xf), math.ceil(xf)}, {math.floor(zf), math.ceil(zf)}
    # Fuente subnodo: integrales rectas locales aproximadas; refinamiento obligatorio.
    seeds = {(i, j): math.hypot(j - xf, i - zf) * spacing_m / float(v[i, j]) for i in rows for j in columns}
    return solve_eikonal(v, spacing_m=spacing_m, initial_times_s=seeds)
