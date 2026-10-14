"""Referencias analíticas con dominio explícito; z interna es profundidad positiva."""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt

from geoqc.core.models import FrozenModel


class TwoLayerTimes(FrozenModel):
    direct_s: tuple[float, ...]
    head_s: tuple[float | None, ...]
    first_s: tuple[float, ...]
    critical_distance_m: float
    crossover_distance_m: float
    intercept_time_s: float
    domain: str = "Surface source/receivers; horizontal two layers; isotropic V1<V2; z positive down"


def two_layer_times(distances_m: npt.ArrayLike, v1_ms: float, v2_ms: float, thickness_m: float) -> TwoLayerTimes:
    r = np.asarray(distances_m, dtype=np.float64)
    if (
        r.ndim != 1
        or not np.all(np.isfinite(r))
        or np.any(r < 0)
        or not all(map(math.isfinite, (v1_ms, v2_ms, thickness_m)))
        or not 0 < v1_ms < v2_ms
        or thickness_m <= 0
    ):
        raise ValueError("r>=0, 0<V1<V2 y h>0 finitos; solo dos capas horizontales")
    critical = 2 * thickness_m * math.tan(math.asin(v1_ms / v2_ms))
    crossover = 2 * thickness_m * math.sqrt((v2_ms + v1_ms) / (v2_ms - v1_ms))
    intercept = 2 * thickness_m / v1_ms * math.sqrt(1 - (v1_ms / v2_ms) ** 2)
    direct = r / v1_ms
    heads = tuple(float(distance / v2_ms + intercept) if distance >= critical else None for distance in r)
    return TwoLayerTimes(
        direct_s=tuple(float(v) for v in direct),
        head_s=heads,
        first_s=tuple(
            float(min(d, head)) if head is not None else float(d) for d, head in zip(direct, heads, strict=True)
        ),
        critical_distance_m=critical,
        crossover_distance_m=crossover,
        intercept_time_s=intercept,
    )


def dipping_apparent_velocities(v1_ms: float, v2_ms: float, dip_degrees: float) -> tuple[float, float]:
    if not all(map(math.isfinite, (v1_ms, v2_ms, dip_degrees))) or not 0 < v1_ms < v2_ms:
        raise ValueError("Velocidades 0<V1<V2 y ángulo finitos")
    theta, dip = math.asin(v1_ms / v2_ms), math.radians(dip_degrees)
    plus, minus = theta + dip, theta - dip
    if not 0 < plus < math.pi / 2 or not 0 < minus < math.pi / 2:
        raise ValueError("Ramas fuera del dominio 0<theta_c±phi<pi/2")
    return v1_ms / math.sin(plus), v1_ms / math.sin(minus)


def gradient_time(
    source_xz: tuple[float, float], receiver_xz: tuple[float, float], *, v0: float, gradient: float
) -> float:
    if not all(map(math.isfinite, (*source_xz, *receiver_xz, v0, gradient))) or v0 <= 0 or gradient < 0:
        raise ValueError("v0>0, g>=0 y posiciones finitas; g<0 no modelado")
    if source_xz[1] < 0 or receiver_xz[1] < 0:
        raise ValueError("Referencia definida para fuente/receptor en z>=0 (profundidad)")
    r = math.hypot(source_xz[0] - receiver_xz[0], source_xz[1] - receiver_xz[1])
    if gradient == 0:
        return r / v0
    vs, vr = v0 + gradient * source_xz[1], v0 + gradient * receiver_xz[1]
    a = gradient * r / (2 * math.sqrt(vs * vr))
    # acosh(1+2a^2)=2asinh(a) evita cancelación al tender g a cero.
    return 2 * math.asinh(a) / gradient
