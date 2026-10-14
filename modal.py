"""Sintético MASW por suma modal (E3.3). Esta iteración solo contiene el caso de
semiespacio homogéneo (verdad exacta); la suma modal multicapa llega en E3.3."""
from __future__ import annotations

from typing import Callable

import numpy as np

from geoqc.core.physics import rayleigh_halfspace_velocity, rayleigh_ratio  # reexport

__all__ = ["rayleigh_halfspace_velocity", "rayleigh_halfspace_factory", "rayleigh_ratio"]


def rayleigh_halfspace_factory(vs: float, nu: float) -> Callable[[np.ndarray], np.ndarray]:
    """Curva c(f) de un semiespacio homogéneo (no dispersivo): devuelve c_R constante para
    cada frecuencia, con la misma forma de llamada que una curva de dispersión."""
    c = rayleigh_halfspace_velocity(vs, nu)

    def curve(freq: np.ndarray) -> np.ndarray:
        f = np.asarray(freq, dtype=float)
        if not np.all(np.isfinite(f)) or np.any(f <= 0.0):
            raise ValueError("las frecuencias deben ser finitas y > 0")
        return np.full_like(f, c)

    return curve
