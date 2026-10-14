"""Referencias analíticas; sin criterios empíricos de aceptación."""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt
from scipy.optimize import brentq


def _finite_number(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.floating)) or not math.isfinite(value):
        raise ValueError(f"{name} debe ser un número finito")


def kappa2_from_nu(nu: float) -> float:
    _finite_number(nu, "nu")
    if not -1.0 < nu <= 0.5:
        raise ValueError("nu fuera del dominio (-1,0.5]; 0.5 es límite incompresible")
    return (1.0 - 2.0 * nu) / (2.0 * (1.0 - nu))


def rayleigh_cubic(xi: float, kappa2: float) -> float:
    return ((xi - 8.0) * xi + 8.0 * (3.0 - 2.0 * kappa2)) * xi - 16.0 * (1.0 - kappa2)


def rayleigh_radical_residual(xi: float, kappa2: float) -> float:
    return (2.0 - xi) ** 2 - 4.0 * math.sqrt(1.0 - xi) * math.sqrt(1.0 - kappa2 * xi)


def rayleigh_xi(nu: float, tol: float = 1e-14) -> float:
    _finite_number(tol, "tol")
    if not 0 < tol < 1:
        raise ValueError("tol debe pertenecer a (0,1)")
    k2 = kappa2_from_nu(nu)

    def polynomial(x: float) -> float:
        return rayleigh_cubic(x, k2)

    return float(brentq(polynomial, 0.0, 1.0, xtol=tol, rtol=4 * np.finfo(float).eps, maxiter=200))


def rayleigh_ratio(nu: float, tol: float = 1e-14) -> float:
    return math.sqrt(rayleigh_xi(nu, tol))


def rayleigh_halfspace_velocity(vs: float, nu: float, tol: float = 1e-14) -> float:
    _finite_number(vs, "vs")
    if vs <= 0:
        raise ValueError("vs debe ser positiva")
    return vs * rayleigh_ratio(nu, tol)


def geophone_response(frequencies_hz: npt.ArrayLike, fn_hz: float, damping: float) -> npt.NDArray[np.complex128]:
    _finite_number(fn_hz, "fn_hz")
    _finite_number(damping, "damping")
    if fn_hz <= 0 or damping <= 0:
        raise ValueError("Frecuencia natural y amortiguamiento deben ser positivos")
    f = np.asarray(frequencies_hz, dtype=np.float64)
    if not np.all(np.isfinite(f)) or np.any(f < 0):
        raise ValueError("Frecuencias deben ser finitas y no negativas")
    scale = np.maximum(f, fn_hz)
    normalized_f, normalized_fn = f / scale, fn_hz / scale
    denominator = normalized_fn**2 - normalized_f**2 + 1j * damping * (2 * normalized_fn * normalized_f)
    return np.asarray(-(normalized_f**2) / denominator, dtype=np.complex128)


def wavelengths_m(frequencies_hz: npt.ArrayLike, velocities_ms: npt.ArrayLike) -> npt.NDArray[np.float64]:
    """λ=c/f en SI, compartida por escenario y estimación observada."""
    f = np.asarray(frequencies_hz, dtype=np.float64)
    c = np.asarray(velocities_ms, dtype=np.float64)
    if (
        f.shape != c.shape
        or not np.all(np.isfinite(f))
        or not np.all(np.isfinite(c))
        or np.any(f <= 0)
        or np.any(c <= 0)
    ):
        raise ValueError("f y c positivas finitas con formas iguales")
    with np.errstate(over="ignore"):
        wavelengths = np.asarray(c / f, dtype=np.float64)
    if not np.all(np.isfinite(wavelengths)) or np.any(wavelengths <= 0):
        raise ValueError("λ fuera del rango representable positivo finito")
    return wavelengths
