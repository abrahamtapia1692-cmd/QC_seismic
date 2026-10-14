"""Física de referencia exacta (headless: sin I/O ni UI).

Vive en ``core`` (y no en ``synth``) porque ``core/feasibility.py`` (E0.4) la necesita
para estimar c(f_low); ``synth/modal.py`` la reexporta. Así se respeta la dependencia
``synth -> core`` y nunca ``core -> synth``.

Ecuación de Rayleigh para un semiespacio elástico homogéneo
-----------------------------------------------------------
Con ξ = (c_R/Vs)² y κ² = (Vs/Vp)² = (1-2ν) / (2(1-ν)):

    P(ξ) = ξ³ - 8 ξ² + 8 (3 - 2κ²) ξ - 16 (1 - κ²) = 0

Propiedades usadas (y verificadas en tests):
  * P(0) = -16 (1-κ²) < 0   y   P(1) = 1  para todo κ²  ->  el intervalo [0, 1] encierra
    SIEMPRE una raíz (brentq no necesita un intervalo "ajustado a mano").
  * Hay exactamente una raíz en (0, 1); las otras dos son > 1 o complejas.
  * La forma con radicales  (2-ξ)² = 4 sqrt(1-ξ) sqrt(1-κ²ξ)  tiene la raíz trivial espuria
    ξ = 0 (introducida al elevar al cuadrado en el sentido contrario); la forma cúbica no.
    Se conserva la forma con radicales solo como verificación independiente del residuo.
  * ν = 0.25  ->  κ² = 1/3  ->  ξ = 2 - 2/√3  (forma cerrada exacta; c_R/Vs = 0.919402...).
"""
from __future__ import annotations

import math

import numpy as np
from scipy.optimize import brentq

NU_LOWER_EXCLUSIVE = -1.0
NU_UPPER_INCLUSIVE = 0.5


def _check_nu(nu: float) -> None:
    if not isinstance(nu, (int, float, np.floating)) or not math.isfinite(nu):
        raise ValueError(f"nu debe ser un número finito, recibido {nu!r}")
    if not (NU_LOWER_EXCLUSIVE < nu <= NU_UPPER_INCLUSIVE):
        raise ValueError(f"nu fuera de rango físico (-1, 0.5]: {nu}")


def kappa2_from_nu(nu: float) -> float:
    """κ² = (Vs/Vp)² = (1-2ν)/(2(1-ν))."""
    _check_nu(nu)
    return (1.0 - 2.0 * nu) / (2.0 * (1.0 - nu))


def rayleigh_cubic(xi: float, kappa2: float) -> float:
    """P(ξ) en forma de Horner."""
    return ((xi - 8.0) * xi + 8.0 * (3.0 - 2.0 * kappa2)) * xi - 16.0 * (1.0 - kappa2)


def rayleigh_radical_residual(xi: float, kappa2: float) -> float:
    """Residuo de la forma con radicales (verificación independiente; válido en ξ<1)."""
    return (2.0 - xi) ** 2 - 4.0 * math.sqrt(1.0 - xi) * math.sqrt(1.0 - kappa2 * xi)


def rayleigh_xi(nu: float, tol: float = 1e-14) -> float:
    """Raíz ξ=(c_R/Vs)² en (0,1) de la cúbica de Rayleigh."""
    if not tol > 0.0:
        raise ValueError("tol debe ser > 0")
    k2 = kappa2_from_nu(nu)
    f = lambda x: rayleigh_cubic(x, k2)  # noqa: E731
    lo, hi = f(0.0), f(1.0)
    if not (lo < 0.0 < hi):  # no debería ocurrir; defensa ante NaN/regresiones
        raise RuntimeError(f"intervalo [0,1] no encierra la raíz: P(0)={lo}, P(1)={hi}")
    return brentq(f, 0.0, 1.0, xtol=tol, rtol=4 * np.finfo(float).eps, maxiter=200)


def rayleigh_ratio(nu: float, tol: float = 1e-14) -> float:
    """c_R / Vs de un semiespacio homogéneo."""
    return math.sqrt(rayleigh_xi(nu, tol))


def rayleigh_halfspace_velocity(vs: float, nu: float, tol: float = 1e-14) -> float:
    """c_R [m/s] de un semiespacio elástico homogéneo con velocidad de corte ``vs`` [m/s]."""
    if not (isinstance(vs, (int, float, np.floating)) and math.isfinite(vs) and vs > 0.0):
        raise ValueError(f"vs debe ser finito y > 0, recibido {vs!r}")
    return vs * rayleigh_ratio(nu, tol)
