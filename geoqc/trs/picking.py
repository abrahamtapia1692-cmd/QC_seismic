from __future__ import annotations

import hashlib
import importlib.metadata
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import find_peaks

from geoqc.core.evidence import canonical_hash
from geoqc.core.models import ArrivalPick, FloatArray, Shot
from geoqc.qc.channels import window_samples
from geoqc.trs.contracts import PickCalibration, PickProtocol


@lru_cache(maxsize=1)
def estimator_hash() -> str:
    return canonical_hash(
        {
            "dependencies": {name: importlib.metadata.version(name) for name in ("numpy", "scipy", "pydantic")},
            "source": {
                name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
                for name in ("picking.py", "contracts.py")
            },
        }
    )


def aic_curve(
    samples: FloatArray, *, min_segment: int = 8, floor_fraction: float = 1e-8
) -> tuple[FloatArray, FloatArray]:
    """ML ddof=0; escalado común conserva argmin; var floor relativo explícito."""
    a = np.asarray(samples, dtype=float)
    if a.ndim != 1 or a.size < 2 * min_segment + 1 or not np.all(np.isfinite(a)) or min_segment < 2:
        raise ValueError("Ventana AIC finita y segmentos suficientes requeridos")
    if not 0 < floor_fraction < 1:
        raise ValueError("Piso relativo en (0,1)")
    scale = float(np.max(abs(a)))
    if scale == 0:
        raise ValueError("AIC sin señal/ruido variable")
    a = a / scale
    sums = np.r_[0.0, np.cumsum(a)]
    squares = np.r_[0.0, np.cumsum(a * a)]
    k = np.arange(min_segment, a.size - min_segment + 1, dtype=float)
    index = k.astype(int)
    left = squares[index] / k - (sums[index] / k) ** 2
    right_n = a.size - k
    right = (squares[-1] - squares[index]) / right_n - ((sums[-1] - sums[index]) / right_n) ** 2
    floor = max(float(np.var(a)) * floor_fraction, float(np.finfo(float).tiny))
    values = k * np.log(np.maximum(left, floor)) + right_n * np.log(np.maximum(right, floor))
    return k, np.asarray(values, dtype=float)


def pick_trace(
    shot: Shot, channel: int, protocol: PickProtocol, calibration: PickCalibration | None = None
) -> ArrivalPick:
    window = (protocol.search.start_s, protocol.search.end_s)
    processing = f"{protocol.preprocessing};STA/LTA+AIC;protocol_sha256={canonical_hash(protocol)}"

    def abstain(reason: str, ambiguous: bool = False) -> ArrivalPick:
        return ArrivalPick(
            onset_s=None,
            sigma_s=None,
            bias_s=None,
            confidence="AMBIGUOUS" if ambiguous else "MISSING",
            reason=reason,
            window_s=window,
            preprocessing_ref=processing,
        )

    if shot.acquisition.technique != "TRS" or shot.acquisition.wave != "P":
        return abstain("Picking TRS requiere onda P y adquisición TRS")
    dt = shot.dt_s[channel]
    if protocol.band_hz[1] >= 0.8 / (2 * dt):
        return abstain("Banda declarada fuera de política Nyquist")
    search, sm = window_samples(shot, channel, protocol.search)
    noise, nm = window_samples(shot, channel, protocol.noise)
    nsta, nlta = max(round(protocol.sta_s / dt), 2), max(round(protocol.lta_s / dt), 4)
    if min(search.size, noise.size) < nlta or not np.all(sm) or not np.all(nm):
        return abstain("Ventanas incompletas/enmascaradas: no se rellenan huecos")
    dc = float(np.mean(noise))
    signal = search - dc
    pn = float(np.mean((noise - dc) ** 2))
    if pn == 0:
        return abstain("Ruido AC cero: no hay modelo de confianza temporal")
    # LTA = estimación estacionaria externa; media móvil corta causal, sin fase cero.
    power = signal * signal
    sta = np.convolve(power, np.ones(nsta) / nsta, mode="full")[: signal.size]
    indices = np.flatnonzero(sta > protocol.trigger_ratio * pn)
    if not indices.size:
        return abstain("No se identifica cambio de energía sobre el ruido")
    candidate = int(indices[0])
    sustained = max(round(protocol.min_sustained_s / dt), nsta)
    support = power[candidate : min(candidate + sustained, signal.size)]
    if support.size < sustained or np.count_nonzero(support > 4 * pn) < sustained // 3:
        return abstain("Burst aislado o llegada sin soporte sostenido", True)
    # Presencia de episodios comparables separados exige abstención, no escoger certeza.
    envelope = uniform_filter1d(power, size=sustained, mode="constant")
    primary_peak = float(np.max(envelope[candidate : candidate + sustained]))
    peaks, _ = find_peaks(
        envelope, distance=max(1, round(2 * protocol.refine_post_s / dt)), prominence=0.25 * primary_peak
    )
    competing = [
        peak
        for peak in peaks
        if (peak - candidate) * dt > 2 * protocol.refine_post_s and envelope[peak] > 0.5 * primary_peak
    ]
    if competing:
        return abstain("Múltiples episodios de energía: primera llegada ambigua", True)
    left = max(0, candidate - round(protocol.refine_pre_s / dt))
    right = min(signal.size, candidate + round(protocol.refine_post_s / dt))
    if right - left <= 2 * protocol.minimum_segment_samples:
        return abstain("Refinamiento AIC sin segmentos suficientes", True)
    splits, values = aic_curve(
        signal[left:right],
        min_segment=protocol.minimum_segment_samples,
        floor_fraction=protocol.variance_floor_fraction,
    )
    k = int(splits[np.argmin(values)])
    # k separa [:k] de [k:]; primer sample de la segunda población es k.
    index = left + k
    if k in (protocol.minimum_segment_samples, right - left - protocol.minimum_segment_samples):
        return abstain("Mínimo AIC en límite de segmentos", True)
    sample_start = int(np.ceil((protocol.search.start_s - shot.t0_s[channel]) / dt - 1e-9))
    onset = shot.t0_s[channel] + (sample_start + index) * dt
    if calibration is None:
        return ArrivalPick(
            onset_s=onset,
            sigma_s=None,
            bias_s=None,
            confidence="UNCALIBRATED",
            reason="Onset diagnóstico; curvatura AIC no es sigma; polaridad separada",
            window_s=window,
            preprocessing_ref=processing,
        )
    if (
        calibration.protocol_hash != canonical_hash(protocol)
        or calibration.dt_s != dt
        or calibration.domain_id != protocol.domain_id
        or calibration.estimator_hash != estimator_hash()
    ):
        return abstain("Calibración incompatible con protocolo/dt/dominio", True)
    errors = np.asarray(calibration.errors_s)
    bias = float(np.mean(errors))
    corrected = onset - bias
    if not window[0] <= corrected <= window[1]:
        return abstain("Corrección de sesgo fuera de ventana", True)
    residuals = errors - bias
    quantiles = np.quantile(residuals, [0.025, 0.975])
    interval = (float(corrected - quantiles[1]), float(corrected - quantiles[0]))
    # El intervalo empírico puede ser asimétrico; contiene estimación por contrato.
    interval = (min(interval[0], corrected), max(interval[1], corrected))
    return ArrivalPick(
        onset_s=corrected,
        sigma_s=float(np.std(errors, ddof=1)),
        bias_s=bias,
        confidence="CALIBRATED",
        reason="Solo dominio sintético declarado; intervalos por errores train independientes",
        window_s=window,
        preprocessing_ref=processing,
        interval_s=interval,
        shared_error_refs=(calibration.training_ref,),
    )


def pick_shot(
    shot: Shot, protocol: PickProtocol, calibration: PickCalibration | None = None
) -> tuple[ArrivalPick, ...]:
    return tuple(pick_trace(shot, j, protocol, calibration) for j in range(shot.data.shape[0]))
