from __future__ import annotations

from typing import Literal

import numpy as np
import numpy.typing as npt
from scipy.signal import bilinear, lfilter

from geoqc.core.evidence import seeded_rng
from geoqc.core.models import Array, FrozenModel, Positive


def _time(value: npt.ArrayLike, fp_hz: float) -> npt.NDArray[np.float64]:
    t = np.asarray(value, dtype=np.float64)
    if (
        t.ndim != 1
        or t.size == 0
        or not np.all(np.isfinite(t))
        or np.any(np.diff(t) <= 0)
        or not np.isfinite(fp_hz)
        or fp_hz <= 0
    ):
        raise ValueError("Tiempo creciente finito y frecuencia positiva requeridos")
    return t


def ricker(time_s: npt.ArrayLike, fp_hz: float) -> npt.NDArray[np.float64]:
    t = _time(time_s, fp_hz)
    squared = (np.pi * fp_hz * t) ** 2
    return np.asarray((1 - 2 * squared) * np.exp(-squared), dtype=np.float64)


class CausalPulse(FrozenModel):
    samples: Array
    analytic_onset_s: float
    first_nonzero_sample_s: float | None
    model: str = "H(t) (t/tau)^2 exp(-t/tau) cos(2pi fp t); tau=1/fp"
    processing: tuple[str, ...] = ()


def causal_pulse(time_s: npt.ArrayLike, fp_hz: float, *, onset_s: float = 0.0) -> CausalPulse:
    t = _time(time_s, fp_hz)
    if not np.isfinite(onset_s):
        raise ValueError("Onset debe ser finito")
    u = t - onset_s
    result = np.zeros(t.size)
    support = u >= 0
    scaled = u[support] * fp_hz
    result[support] = scaled**2 * np.exp(-scaled) * np.cos(2 * np.pi * scaled)
    nonzero = np.flatnonzero(result != 0)
    return CausalPulse(
        samples=result, analytic_onset_s=onset_s, first_nonzero_sample_s=float(t[nonzero[0]]) if nonzero.size else None
    )


def apply_causal_geophone(pulse: CausalPulse, time_s: npt.ArrayLike, *, fn_hz: float, damping: float) -> CausalPulse:
    t = _time(time_s, fn_hz)
    if (
        t.size != pulse.samples.size
        or t.size < 2
        or not np.allclose(np.diff(t), np.diff(t)[0], rtol=1e-9, atol=0)
        or not np.isfinite(damping)
        or damping <= 0
    ):
        raise ValueError("Muestreo uniforme, forma compatible y amortiguamiento positivo")
    wn, dt = 2 * np.pi * fn_hz, float(t[1] - t[0])
    b, a = bilinear([1.0, 0.0, 0.0], [1.0, 2 * damping * wn, wn * wn], fs=1 / dt)
    samples = np.asarray(lfilter(b, a, pulse.samples), dtype=np.float64)
    nonzero = np.flatnonzero(samples != 0)
    return CausalPulse(
        samples=samples,
        analytic_onset_s=pulse.analytic_onset_s,
        first_nonzero_sample_s=float(t[nonzero[0]]) if nonzero.size else None,
        model=pulse.model,
        processing=(
            *pulse.processing,
            f"causal bilinear geophone fn={fn_hz},h={damping}; known response, not field calibration",
        ),
    )


class NoiseRealization(FrozenModel):
    noise: Array
    noisy_signal: Array
    snr_db: float
    seed: int
    kind: str
    dt_s: Positive
    model_parameters: tuple[str, ...]
    scope: str = "Signal/noise energies in same full supplied window; excludes DC; no field SNR claim"


def noise_at_snr(
    signal: npt.ArrayLike,
    *,
    snr_db: float,
    seed: int,
    kind: Literal["white", "colored", "coherent", "traffic", "hum", "bursts"] = "white",
    dt_s: float = 0.001,
    hum_hz: float = 50.0,
) -> NoiseRealization:
    data = np.asarray(signal, dtype=np.float64)
    if (
        data.ndim != 2
        or min(data.shape) < 2
        or not np.all(np.isfinite(data))
        or not np.isfinite(snr_db)
        or kind not in ("white", "colored", "coherent", "traffic", "hum", "bursts")
    ):
        raise ValueError("Matriz finita, ventana y modelo de ruido explícitos requeridos")
    generator = seeded_rng(seed)
    if not np.isfinite(dt_s) or dt_s <= 0:
        raise ValueError("dt debe ser positivo finito")
    if kind == "hum" and (not np.isfinite(hum_hz) or not 0 < hum_hz < 1 / (2 * dt_s)):
        raise ValueError("Hum debe pertenecer a banda sin aliasing")
    if kind == "traffic" and 13.0 >= 1 / (2 * dt_s):
        raise ValueError("Modelo de tráfico 5/9/13 Hz fuera de banda")
    noise = generator.normal(size=data.shape if kind != "coherent" else (1, data.shape[1]))
    noise -= noise.mean(axis=1, keepdims=True)
    if kind == "colored":
        freqs = np.fft.rfftfreq(data.shape[1])
        scale = np.zeros_like(freqs)
        scale[1:] = 1 / np.sqrt(freqs[1:])
        noise = np.fft.irfft(np.fft.rfft(noise, axis=1) * scale, n=data.shape[1], axis=1)
    if kind == "coherent":
        noise = np.broadcast_to(noise, data.shape).copy()
    elif kind == "hum":
        phases = generator.uniform(0.0, 2 * np.pi, size=(data.shape[0], 1))
        noise = np.sin(2 * np.pi * hum_hz * np.arange(data.shape[1]) * dt_s + phases)
    elif kind in ("traffic", "bursts"):
        t = np.arange(data.shape[1]) / data.shape[1]
        envelope = np.exp(-(((t - 0.5) / 0.12) ** 2))
        if kind == "traffic":
            phases = generator.uniform(0.0, 2 * np.pi, size=3)
            common = sum(
                np.sin(2 * np.pi * f * np.arange(data.shape[1]) * dt_s + phase)
                for f, phase in zip((5.0, 9.0, 13.0), phases, strict=True)
            )
            noise = np.broadcast_to(common * envelope, data.shape).copy()
        else:
            noise *= envelope
    noise -= noise.mean(axis=1, keepdims=True)
    signal_energy = np.sum((data - data.mean(axis=1, keepdims=True)) ** 2)
    if signal_energy == 0:
        raise ValueError("SNR de señal DC/cero no definida por este estimando")
    with np.errstate(over="ignore", under="ignore"):
        ratio = float(np.power(10.0, snr_db / 10))
    if not np.isfinite(ratio) or ratio <= 0:
        raise ValueError("SNR fuera del rango numérico representable")
    noise *= np.sqrt(signal_energy / (np.sum(noise**2) * ratio))
    parameters = (
        "SNR over full supplied window, DC removed per channel",
        f"hum_hz={hum_hz}"
        if kind == "hum"
        else "traffic:5/9/13 Hz Gaussian envelope"
        if kind == "traffic"
        else "colored:1/f power; coherent:common noise"
        if kind in ("colored", "coherent")
        else kind,
    )
    return NoiseRealization(
        noise=noise,
        noisy_signal=data + noise,
        snr_db=snr_db,
        seed=seed,
        kind=kind,
        dt_s=dt_s,
        model_parameters=parameters,
    )
