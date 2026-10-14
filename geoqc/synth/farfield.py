"""Suma modal asintótica de campo lejano; nunca un Green completo de campo cercano."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
from scipy.interpolate import PchipInterpolator

from geoqc.core.models import Array, FrozenModel
from geoqc.synth.dispersion import PhaseCurve


class FarfieldWaveform(FrozenModel):
    data: Array
    dt_s: float
    fft_samples: int
    previous_fft_samples: int
    padding_relative_change: float
    maximum_scenario_group_delay_s: float
    model: str = "S(f) exp(-ikr)/sqrt(kr) exp(-pi f r/(Q c)); approximate farfield, band-limited"
    limitations: tuple[str, ...] = (
        "Not an onset truth reference",
        "Not full Green; no body-wave interference",
        "Declared finite band; no extrapolation of c(f)",
    )


def farfield_waveform(
    source_samples: npt.ArrayLike,
    *,
    dt_s: float,
    offsets_m: npt.ArrayLike,
    branches: tuple[PhaseCurve, ...],
    modal_amplitudes: tuple[float, ...],
    quality_factors: tuple[float | None, ...],
    padding_tolerance: float = 1e-3,
    max_padding_factor: int = 16,
) -> FarfieldWaveform:
    source, r = np.asarray(source_samples, dtype=np.float64), np.asarray(offsets_m, dtype=np.float64)
    if (
        source.ndim != 1
        or source.size < 16
        or r.ndim != 1
        or r.size == 0
        or not np.all(np.isfinite(source))
        or not np.all(np.isfinite(r))
        or np.any(r <= 0)
        or not np.isfinite(dt_s)
        or dt_s <= 0
    ):
        raise ValueError("Fuente finita 1D, offsets r>0 y dt>0 requeridos")
    if not branches or len(branches) != len(modal_amplitudes) or len(branches) != len(quality_factors):
        raise ValueError("Cada rama requiere amplitud y Q explícitos")
    if (
        not np.isfinite(padding_tolerance)
        or not 0 < padding_tolerance < 1
        or max_padding_factor not in (4, 8, 16, 32, 64)
    ):
        raise ValueError("Tolerancia/presupuesto de padding explícitos")
    delays = []
    for branch, amplitude, q in zip(branches, modal_amplitudes, quality_factors, strict=True):
        if (
            branch.frequencies_hz.size < 2
            or branch.frequencies_hz[-1] >= 1 / (2 * dt_s)
            or not np.isfinite(amplitude)
            or amplitude < 0
            or (q is not None and (not np.isfinite(q) or q <= 0))
        ):
            raise ValueError("Rama fuera de Nyquist o amplitud/Q inválidos")
        derivative = PchipInterpolator(branch.frequencies_hz, branch.velocities_ms).derivative()(branch.frequencies_hz)
        group_slowness = (branch.velocities_ms - branch.frequencies_hz * derivative) / branch.velocities_ms**2
        if np.any(group_slowness <= 0):
            raise ValueError("Escenario de grupo no positivo; modelo no habilitado para este generador")
        delays.append(float(r.max() * group_slowness.max()))
    maximum_delay = max(delays)
    if maximum_delay >= max_padding_factor * source.size * dt_s / 2:
        raise ValueError("PADDING_BUDGET: retardo del escenario excede ventana extendida; ampliar registro/padding")
    previous = None
    for factor in (2, 4, 8, 16, 32, 64):
        if factor > max_padding_factor:
            break
        nfft = factor * source.size
        frequencies = np.fft.rfftfreq(nfft, dt_s)
        spectrum = np.fft.rfft(source, n=nfft)
        wave = np.zeros((r.size, frequencies.size), dtype=np.complex128)
        for branch, amplitude, q in zip(branches, modal_amplitudes, quality_factors, strict=True):
            supported = (
                (frequencies >= branch.frequencies_hz[0])
                & (frequencies <= branch.frequencies_hz[-1])
                & (frequencies > 0)
            )
            f = frequencies[supported]
            c = np.asarray(PchipInterpolator(branch.frequencies_hz, branch.velocities_ms)(f), dtype=np.float64)
            k = 2 * np.pi * f / c
            kr = r[:, None] * k[None, :]
            damping = 1.0 if q is None else np.exp(-np.pi * f * r[:, None] / (q * c))
            wave[:, supported] += amplitude * spectrum[supported] * np.exp(-1j * kr) / np.sqrt(kr) * damping
        data = np.fft.irfft(wave, n=nfft, axis=1)[:, : source.size]
        if previous is not None:
            relative = float(np.linalg.norm(data - previous) / max(np.linalg.norm(data), np.finfo(float).tiny))
            if relative <= padding_tolerance:
                return FarfieldWaveform(
                    data=data,
                    dt_s=dt_s,
                    fft_samples=nfft,
                    previous_fft_samples=nfft // 2,
                    padding_relative_change=relative,
                    maximum_scenario_group_delay_s=maximum_delay,
                )
        previous = data
    raise ValueError("PADDING_NOT_CONVERGED: ventanas extendidas difieren; no declarar waveform sin wrap-around")
