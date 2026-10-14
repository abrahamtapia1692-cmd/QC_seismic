"""Referencia de semiespacio; el generador multicapa pertenece a E3."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import numpy.typing as npt

from geoqc.core.physics import rayleigh_halfspace_velocity, rayleigh_ratio

__all__ = ["rayleigh_halfspace_velocity", "rayleigh_halfspace_factory", "rayleigh_ratio"]


def rayleigh_halfspace_factory(vs: float, nu: float) -> Callable[[npt.ArrayLike], npt.NDArray[np.float64]]:
    c = rayleigh_halfspace_velocity(vs, nu)

    def curve(frequencies_hz: npt.ArrayLike) -> npt.NDArray[np.float64]:
        f = np.asarray(frequencies_hz, dtype=np.float64)
        if not np.all(np.isfinite(f)) or np.any(f <= 0):
            raise ValueError("Frecuencias finitas positivas requeridas")
        return np.full_like(f, c)

    return curve
