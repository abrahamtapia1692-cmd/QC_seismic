from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt
from scipy.optimize import brentq

from geoqc.core.models import Shot
from geoqc.masw.contracts import MASWProtocol


def _inputs(
    spectrum: npt.ArrayLike, frequencies_hz: npt.ArrayLike, x_m: npt.ArrayLike, weights: npt.ArrayLike | None
) -> tuple[npt.NDArray[np.complex128], npt.NDArray[np.float64], npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    u, f, x = np.asarray(spectrum, complex), np.asarray(frequencies_hz, float), np.asarray(x_m, float)
    w = np.ones(x.size) if weights is None else np.asarray(weights, float)
    if (
        f.ndim != 1
        or x.ndim != 1
        or not f.size
        or x.size < 2
        or u.shape != (f.size, x.size)
        or w.shape != x.shape
        or np.any(w < 0)
        or not all(np.all(np.isfinite(a)) for a in (u, f, x, w))
        or np.any(f <= 0)
        or np.any(np.diff(f) <= 0)
    ):
        raise ValueError("U[f,canal], f>0 creciente, x finita, pesos no negativos requeridos")
    return u, f, x, w


def phase_shift(
    spectrum: npt.ArrayLike,
    frequencies_hz: npt.ArrayLike,
    x_m: npt.ArrayLike,
    velocities_ms: npt.ArrayLike,
    *,
    direction: int = 1,
    weights: npt.ArrayLike | None = None,
) -> dict[str, Any]:
    u, f, x, w = _inputs(spectrum, frequencies_hz, x_m, weights)
    c = np.asarray(velocities_ms, float)
    if c.ndim != 1 or not c.size or np.any(c <= 0) or not np.all(np.isfinite(c)) or direction not in (-1, 1):
        raise ValueError("c positiva finita y dirección ±1")
    active = (np.abs(u) > 0) & (w[None, :] > 0)
    normalized = np.zeros_like(u)
    np.divide(u, np.abs(u), out=normalized, where=active)
    scores = np.zeros((f.size, c.size))
    sums = np.sum(active * w, axis=1)
    for i, frequency in enumerate(f):
        if sums[i] > 0:
            steering = np.exp(2j * np.pi * frequency * direction * x[None, :] / c[:, None])
            scores[i] = np.abs(steering @ (normalized[i] * w)) / sums[i]
    return {"coherence": np.clip(scores, 0, 1), "active": active, "n_active": active.sum(axis=1)}


def spatial_kernel(delta_q_m_inv: npt.ArrayLike, x_m: npt.ArrayLike, weights: npt.ArrayLike | None = None) -> Any:
    x, q = np.asarray(x_m, float), np.asarray(delta_q_m_inv, float)
    w = np.ones(x.size) if weights is None else np.asarray(weights, float)
    if (
        x.ndim != 1
        or w.shape != x.shape
        or np.any(w < 0)
        or np.sum(w) <= 0
        or not all(np.all(np.isfinite(a)) for a in (x, q, w))
    ):
        raise ValueError("Kernel requiere posiciones y pesos válidos")
    return np.abs(np.exp(2j * np.pi * q[..., None] * x) @ w) / np.sum(w)


def uniform_fwhm(n: int, dx_m: float, *, power: bool = False) -> float:
    if type(n) is not int or n < 2 or not np.isfinite(dx_m) or dx_m <= 0:
        raise ValueError("N>=2 y dx>0")
    target = np.sqrt(0.5) if power else 0.5
    return 2 * float(
        brentq(lambda q: float(spatial_kernel(q, np.arange(n) * dx_m)) - target, 0, 1 / (n * dx_m), xtol=1e-14)
    )


def velocity_fwhm(frequency_hz: float, c0_ms: float, width_q_m_inv: float) -> dict[str, Any]:
    if not all(np.isfinite(v) and v > 0 for v in (frequency_hz, c0_ms, width_q_m_inv)):
        raise ValueError("Frecuencia, velocidad y ancho positivos")
    q = frequency_hz / c0_ms
    a = width_q_m_inv / (2 * q)
    if a >= 1:
        return {"finite": False, "c_bounds_ms": None, "relative_width": None, "a": a}
    return {
        "finite": True,
        "c_bounds_ms": (frequency_hz / (q + width_q_m_inv / 2), frequency_hz / (q - width_q_m_inv / 2)),
        "relative_width": 2 * a / (1 - a * a),
        "a": a,
    }


def shot_spectrum(shot: Shot, protocol: MASWProtocol) -> dict[str, Any]:
    if shot.acquisition.technique != "MASW":
        raise ValueError("MASW requiere adquisición Rayleigh Z")
    if not np.allclose(shot.dt_s, shot.dt_s[0], rtol=1e-12, atol=0) or not np.allclose(
        shot.t0_s, shot.t0_s[0], rtol=0, atol=1e-12
    ):
        raise ValueError("Relojes no alineados: no remuestrear silenciosamente")
    g = shot.geometry
    if not np.allclose(g.yr, g.yr[0], atol=1e-10, rtol=0) or not np.allclose(g.zr, g.zr[0], atol=1e-10, rtol=0):
        raise ValueError("Transformador inicial exige línea horizontal along-x")
    dt = shot.dt_s[0]
    time = shot.t0_s[0] + np.arange(shot.data.shape[1]) * dt
    selection = (time >= protocol.signal.start_s) & (time < protocol.signal.end_s)
    if selection.sum() < 16 or protocol.signal.start_s < time[0] - dt / 2 or protocol.signal.end_s > time[-1] + dt:
        raise ValueError("Ventana física completa con >=16 muestras requerida")
    data = np.array(shot.data[:, selection], copy=True)
    valid = np.all(shot.valid_mask[:, selection], axis=1)
    data[~valid] = 0
    data -= data.mean(axis=1, keepdims=True)
    window = np.ones(data.shape[1]) if protocol.window == "RECTANGULAR" else np.hanning(data.shape[1])
    u = np.fft.rfft(data * window, axis=1).T
    bins = np.fft.rfftfreq(data.shape[1], dt)
    indexes = np.array([np.argmin(abs(bins - f)) for f in protocol.frequencies_hz])
    if not np.allclose(bins[indexes], protocol.frequencies_hz, rtol=1e-10, atol=1e-10):
        raise ValueError("Frecuencias solicitadas deben coincidir con bins FFT observados")
    weights = np.ones(data.shape[0]) if protocol.weights is None else np.array(protocol.weights)
    if weights.shape != valid.shape:
        raise ValueError("Un peso por receptor físico")
    weights *= valid
    return {
        "spectrum": u[indexes],
        "frequencies_hz": bins[indexes],
        "x_m": np.asarray(g.xr - g.xs),
        "weights": weights,
        "excluded": [
            "MASKED_WINDOW" if not v else "ZERO_WEIGHT" if w == 0 else "" for v, w in zip(valid, weights, strict=True)
        ],
        "window_samples": int(selection.sum()),
    }


def fk_reference(
    spectrum: npt.ArrayLike, frequencies_hz: npt.ArrayLike, x_m: npt.ArrayLike, q_m_inv: npt.ArrayLike
) -> Any:
    u, f, x, w = _inputs(spectrum, frequencies_hz, x_m, None)
    q = np.asarray(q_m_inv, float)
    if q.ndim != 1 or not np.all(np.isfinite(q)):
        raise ValueError("Rejilla q finita")
    # Fourier espacial directo sin normalizar amplitudes; admite geometría irregular.
    return np.abs(u @ np.exp(2j * np.pi * x[:, None] * q[None, :])) ** 2


def tau_p_reference(data: npt.ArrayLike, dt_s: float, x_m: npt.ArrayLike, slowness_s_m: npt.ArrayLike) -> Any:
    a, x, p = np.asarray(data, float), np.asarray(x_m, float), np.asarray(slowness_s_m, float)
    if a.ndim != 2 or a.shape[0] != x.size or dt_s <= 0 or not all(np.all(np.isfinite(v)) for v in (a, x, p)):
        raise ValueError("Tau-p requiere datos y geometría alineados")
    t = np.arange(a.shape[1]) * dt_s
    stacks = np.zeros((p.size, t.size))
    for i, slow in enumerate(p):
        for trace, coordinate in zip(a, x, strict=True):
            stacks[i] += np.interp(t + slow * coordinate, t, trace, left=0, right=0)
    return stacks / x.size
