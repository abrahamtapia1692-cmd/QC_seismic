"""Lamb axisimétrico homogéneo: tracción normal finita, ondas P/S/R, superficie libre.

Integral Hankel del Green completo Z. No importa transformadores MASW ni disba.
Convención temporal exp(+i omega t); omega complejo con parte imaginaria negativa.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt
from scipy.integrate import quad_vec, simpson
from scipy.special import j0


def surface_admittance(k: npt.ArrayLike, omega: complex, *, vp_ms: float, vs_ms: float, rho_kg_m3: float) -> Any:
    k = np.asarray(k, float)
    p = np.sqrt(k**2 - (omega / vp_ms) ** 2 + 0j)
    q = np.sqrt(k**2 - (omega / vs_ms) ** 2 + 0j)
    ks2 = (omega / vs_ms) ** 2
    denominator = (2 * k**2 - ks2) ** 2 - 4 * k**2 * p * q
    return -p * ks2 / (rho_kg_m3 * vs_ms**2 * denominator)


def lamb_surface(
    frequencies_hz: npt.ArrayLike,
    offsets_m: npt.ArrayLike,
    *,
    vp_ms: float,
    vs_ms: float,
    rho_kg_m3: float = 1800,
    source_radius_m: float = 0.5,
    damping_fraction: float = 0.02,
    dk_m_inv: float = 0.0005,
    kmax_m_inv: float = 12,
    adaptive: bool = False,
) -> dict[str, Any]:
    f, r = np.asarray(frequencies_hz, float), np.asarray(offsets_m, float)
    if (
        f.ndim != 1
        or r.ndim != 1
        or not f.size
        or not r.size
        or np.any(f <= 0)
        or np.any(r <= 0)
        or not all(np.all(np.isfinite(v)) for v in (f, r))
        or not all(
            np.isfinite(v) and v > 0
            for v in (vp_ms, vs_ms, rho_kg_m3, source_radius_m, damping_fraction, dk_m_inv, kmax_m_inv)
        )
        or vp_ms**2 <= 4 * vs_ms**2 / 3
    ):
        raise ValueError("Green requiere medio elástico estable, fuente/offset/banda positivos")
    if kmax_m_inv / dk_m_inv > 500000:
        raise ValueError("Presupuesto de integración excedido")
    k = np.linspace(0, kmax_m_inv, int(np.ceil(kmax_m_inv / dk_m_inv)) + 1)
    values = []
    errors: list[float | None] = []
    for frequency in f:
        omega = 2 * np.pi * frequency * (1 - 1j * damping_fraction)

        def integrand(wavenumber: npt.ArrayLike, omega: complex = omega) -> Any:
            wave = np.asarray(wavenumber)
            compliance = surface_admittance(wave, omega, vp_ms=vp_ms, vs_ms=vs_ms, rho_kg_m3=rho_kg_m3)
            return compliance * np.exp(-0.5 * (wave * source_radius_m) ** 2) * wave / (2 * np.pi)

        if adaptive:
            result, error = quad_vec(
                lambda wave: integrand(wave) * j0(wave * r),
                0,
                kmax_m_inv,
                epsabs=1e-18,
                epsrel=1e-8,
                limit=2000,
                points=[
                    2 * np.pi * frequency / vp_ms,
                    2 * np.pi * frequency / vs_ms,
                    2 * np.pi * frequency / (0.92 * vs_ms),
                ],
            )
            values.append(result)
            errors.append(float(error))
        else:
            values.append(simpson(integrand(k)[None, :] * j0(r[:, None] * k), x=k, axis=1))
            errors.append(None)
    return {
        "spectrum": np.asarray(values),
        "integration_error": errors,
        "method": "Axisymmetric homogeneous Lamb Green; full spectral P/S/R surface normal compliance",
        "settings": {
            "dk_m_inv": dk_m_inv,
            "kmax_m_inv": kmax_m_inv,
            "adaptive": adaptive,
            "source_radius_m": source_radius_m,
            "damping_fraction": damping_fraction,
            "vp_ms": vp_ms,
            "vs_ms": vs_ms,
            "rho_kg_m3": rho_kg_m3,
        },
        "limitations": [
            "Homogeneous isotropic halfspace only",
            "Gaussian normal traction; Z surface",
            "Finite complex-frequency damping explicit; no instrument response",
            "Does not calibrate layered nearfield or arbitrary field sources",
        ],
    }
