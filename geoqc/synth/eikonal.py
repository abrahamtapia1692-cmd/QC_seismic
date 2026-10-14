"""Referencia FMM cartesiana de primer orden; convergencia y dominio se prueban aparte."""

from __future__ import annotations

import heapq
import math

import numpy as np
import numpy.typing as npt

from geoqc.core.models import Array, FrozenModel


class EikonalGrid(FrozenModel):
    times_s: Array
    spacing_m: float
    origin_xz_m: tuple[float, float]
    source_xz_m: tuple[float, float]
    domain_xz_m: tuple[float, float, float, float]
    method: str = "First-order isotropic Cartesian fast marching; z=depth positive down"

    def at(self, receiver_xz_m: tuple[float, float]) -> float:
        x, z = receiver_xz_m
        jfloat, ifloat = (x - self.origin_xz_m[0]) / self.spacing_m, (z - self.origin_xz_m[1]) / self.spacing_m
        j, i = round(jfloat), round(ifloat)
        if (
            not np.isclose(j, jfloat, rtol=0, atol=1e-9)
            or not np.isclose(i, ifloat, rtol=0, atol=1e-9)
            or not 0 <= i < self.times_s.shape[0]
            or not 0 <= j < self.times_s.shape[1]
        ):
            raise ValueError("Receptor fuera de malla o no representable; no interpolar silenciosamente")
        return float(self.times_s[i, j])


def fast_marching(
    speed_ms: npt.ArrayLike,
    *,
    spacing_m: float,
    source_ij: tuple[int, int],
    origin_xz_m: tuple[float, float] = (0.0, 0.0),
) -> EikonalGrid:
    v = np.asarray(speed_ms, dtype=np.float64)
    if (
        v.ndim != 2
        or min(v.shape) < 2
        or not np.all(np.isfinite(v))
        or np.any(v <= 0)
        or not math.isfinite(spacing_m)
        or spacing_m <= 0
    ):
        raise ValueError("Malla 2D y velocidades positivas finitas, paso uniforme positivo")
    ni, nj = v.shape
    si, sj = source_ij
    if not 0 <= si < ni or not 0 <= sj < nj or not all(map(math.isfinite, origin_xz_m)):
        raise ValueError("Fuente/origen fuera del dominio")
    time = np.full(v.shape, np.inf)
    known = np.zeros(v.shape, dtype=bool)
    time[si, sj] = 0.0
    queue = [(0.0, si, sj)]
    while queue:
        arrival, i, j = heapq.heappop(queue)
        if known[i, j]:
            continue
        known[i, j] = True
        for ii, jj in ((i - 1, j), (i + 1, j), (i, j - 1), (i, j + 1)):
            if not 0 <= ii < ni or not 0 <= jj < nj or known[ii, jj]:
                continue
            a = min((time[r, jj] for r in (ii - 1, ii + 1) if 0 <= r < ni and known[r, jj]), default=np.inf)
            b = min((time[ii, c] for c in (jj - 1, jj + 1) if 0 <= c < nj and known[ii, c]), default=np.inf)
            lower, upper = min(a, b), max(a, b)
            step = spacing_m / v[ii, jj]
            candidate = (
                lower + step
                if upper - lower >= step
                else (lower + upper + math.sqrt(max(0.0, 2 * step * step - (upper - lower) ** 2))) / 2
            )
            if candidate < time[ii, jj]:
                time[ii, jj] = candidate
                heapq.heappush(queue, (float(candidate), ii, jj))
    return EikonalGrid(
        times_s=time,
        spacing_m=spacing_m,
        origin_xz_m=origin_xz_m,
        source_xz_m=(origin_xz_m[0] + sj * spacing_m, origin_xz_m[1] + si * spacing_m),
        domain_xz_m=(
            origin_xz_m[0],
            origin_xz_m[0] + (nj - 1) * spacing_m,
            origin_xz_m[1],
            origin_xz_m[1] + (ni - 1) * spacing_m,
        ),
    )
