"""Diagnósticos de ruido y candidatos de filtrado; nunca certifican un pick por fase cero."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any, Literal, Self

import numpy as np
from pydantic import Field, model_validator
from scipy.signal import butter, coherence, iirnotch, periodogram, sosfiltfilt, tf2sos

from geoqc.core.models import BoolArray, FloatArray, FrozenModel, Positive
from geoqc.qc.contracts import Window


class NoiseProtocol(FrozenModel):
    noise: Window
    signal: Window
    low_band_hz: tuple[Positive, Positive] = (1.0, 15.0)
    minimum_cycles: Positive = 3.0
    noise_blocks: int = Field(default=4, ge=3, le=16)
    block_power_ratio_warn: Positive = 4.0
    low_ratio_warn: Positive = 0.5
    mains_candidates_hz: tuple[Positive, ...] = (50.0, 60.0)
    harmonics: int = Field(default=5, ge=1, le=10)
    line_prominence_db: Positive = 10.0
    reference: str = Field(min_length=1)
    reference_kind: Literal["PRETRIGGER", "POST_SIGNAL"] = Field(
        default="PRETRIGGER", exclude_if=lambda value: value == "PRETRIGGER")

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.low_band_hz[0] >= self.low_band_hz[1]:
            raise ValueError("Banda creciente requerida")
        if max(self.noise.start_s, self.signal.start_s) < min(self.noise.end_s, self.signal.end_s):
            raise ValueError("Ventanas de ruido/señal deben ser disjuntas")
        if self.reference_kind == "POST_SIGNAL" and self.noise.start_s < self.signal.end_s:
            raise ValueError("Referencia posterior debe seguir a la ventana de señal")
        return self


def samples_in_window(data: FloatArray, mask: BoolArray, dt: float, t0: float, window: Window) -> FloatArray | None:
    lo = int(np.ceil((window.start_s - t0) / dt - 1e-9))
    hi = int(np.ceil((window.end_s - t0) / dt - 1e-9))
    if lo < 0 or hi > data.size or hi - lo < 16 or not np.all(mask[lo:hi]):
        return None
    values = data[lo:hi]
    return values if np.all(np.isfinite(values)) else None


def digital_integrity(data: FloatArray, dt: float) -> dict[str, Any]:
    """Una cola que decae no es truncamiento. Solo detecta colas digitales constantes."""
    if data.ndim != 1 or not data.size or not np.isfinite(dt) or dt <= 0:
        raise ValueError("Traza no vacía e intervalo positivo requeridos")
    finite = np.isfinite(data)
    run = 0
    if finite[-1]:
        different = np.flatnonzero(data != data[-1])
        run = data.size if not different.size else data.size - int(different[-1]) - 1
    suspicious = run >= max(16, int(np.ceil(0.05 / dt))) and run < data.size
    return {
        "samples": int(data.size),
        "finite_samples": int(finite.sum()),
        "flat_tail_samples": run,
        "truncated_record": None,
        "alerts": ["Cola digital constante: revisar registro y adquisición"] if suspicious else [],
        "reason": "Truncamiento no identificable sin duración esperada o evidencia de pérdida",
    }


def noise_diagnostics(
    data: FloatArray, mask: BoolArray, dt: float, t0: float, protocol: NoiseProtocol
) -> dict[str, Any]:
    if data.ndim != 1 or mask.shape != data.shape or not np.isfinite(dt) or dt <= 0 or not np.isfinite(t0):
        raise ValueError("Traza, máscara y reloj incompatibles")
    noise = samples_in_window(data, mask, dt, t0, protocol.noise)
    signal = samples_in_window(data, mask, dt, t0, protocol.signal)
    out: dict[str, Any] = {
        "state": "MISSING",
        "alerts": [],
        "actions": [],
        "lines": [],
        "snr": {
            "state": "MISSING",
            "value": None,
            "unit": "dB",
            "reason": "Ventanas declaradas sin soporte suficiente",
        },
    }
    if noise is None or signal is None or noise.size < 16 * protocol.noise_blocks:
        out["actions"] = ["Registrar pretrigger suficiente y declarar ventanas sin señal; no usar coda automáticamente"]
        return out
    noise_ac, signal_ac = noise - noise.mean(), signal - signal.mean()
    pn, pt = float(np.mean(noise_ac**2)), float(np.mean(signal_ac**2))
    sigma_mad = float(np.median(abs(noise - np.median(noise))) / 0.6744897501960817)
    blocks = np.array_split(noise, protocol.noise_blocks)
    powers = [float(np.mean((block - block.mean()) ** 2)) for block in blocks]
    ratio = max(powers) / min(powers) if min(powers) > 0 else None
    compatible = ratio is not None and ratio <= protocol.block_power_ratio_warn
    net = pt / pn - 1 if pn > 0 else None
    value = float(10 * np.log10(net)) if net is not None and net > 0 else None
    out.update(
        state="CONDITIONAL",
        noise_power=pn,
        signal_total_power=pt,
        noise_sigma_mad=sigma_mad,
        noise_rms_ac=float(np.sqrt(pn)),
        noise_samples=int(noise.size),
        signal_samples=int(signal.size),
        stationarity={
            "state": ("COMPATIBLE_WITHIN_PRETRIGGER" if protocol.reference_kind == "PRETRIGGER"
                      else "COMPATIBLE_WITHIN_POST_SIGNAL_REFERENCE") if compatible else "VARIABLE_OR_UNRESOLVED",
            "block_powers": powers,
            "max_min_power_ratio": ratio,
            "transfer_to_signal_verified": False,
        },
        snr={
            "state": "CONDITIONAL",
            "value": value,
            "unit": "dB",
            "reason": "SNR de ventana bajo supuesto de transferencia del ruido; no SNR validada del primer arribo",
            "censoring": "ZERO_NOISE" if pn <= 0 else "NET_NOT_RESOLVED" if value is None else None,
            "noise_power": pn,
            "signal_total_power": pt,
            "snr_net_ratio": net,
        },
    )
    if not compatible:
        out["alerts"].append("Ruido " + ("pretrigger" if protocol.reference_kind == "PRETRIGGER" else "de referencia posterior")
                             + " variable o no resuelto: SNR solo condicional")
        out["actions"].append("Revisar subventanas de ruido y repetir una toma de ruido antes del disparo")
    if sigma_mad > 0 and np.sqrt(pn) / sigma_mad > 2:
        out["alerts"].append("Transitorios/colas en ruido: RMS supera 2× escala MAD; se conserva toda su potencia")
    f, psd = periodogram(noise_ac, fs=1 / dt, window="hann", detrend=False, scaling="density")
    df = 1 / (noise.size * dt)
    requested_low, high = protocol.low_band_hz
    resolved_low = max(requested_low, protocol.minimum_cycles / (noise.size * dt))
    band = (f >= resolved_low) & (f <= high)
    low_power = float(psd[band].sum() * df) if band.sum() >= 2 else None
    low_ratio = low_power / pt if low_power is not None and pt > 0 else None
    out["low_frequency"] = {
        "state": "MISSING" if low_ratio is None else "PARTIAL" if resolved_low > requested_low else "MEASURED",
        "requested_band_hz": protocol.low_band_hz,
        "supported_band_hz": [resolved_low, high] if resolved_low < high else None,
        "noise_power_to_signal_total_power": low_ratio,
        "bin_width_hz": df,
        "cause": "UNIDENTIFIED",
        "minimum_cycles": protocol.minimum_cycles,
    }
    if low_ratio is not None and low_ratio > protocol.low_ratio_warn:
        out["alerts"].append("Energía de ruido LF elevada en banda soportada; causa no identificada")
        out["actions"].append("Inspeccionar cables/acople/ambiente y repetir; no atribuir automáticamente a viento")
    for fundamental in protocol.mains_candidates_hz:
        for harmonic in range(1, protocol.harmonics + 1):
            center = fundamental * harmonic
            if center + 6 * df >= f[-1] or center - 6 * df <= 0 or df > 2.5:
                continue
            candidate = np.flatnonzero(abs(f - center) <= max(1, df))
            control = (abs(f - center) >= 3 * df) & (abs(f - center) <= 6 * df)
            if candidate.size == 0 or control.sum() < 3:
                continue
            k = int(candidate[np.argmax(psd[candidate])])
            floor, peak = float(np.median(psd[control])), float(psd[k])
            if peak <= 0 or floor <= 0:
                continue
            prominence = float(10 * np.log10(peak / floor))
            if prominence < protocol.line_prominence_db:
                continue
            shift = 0.0
            if 0 < k < psd.size - 1 and np.all(psd[k - 1 : k + 2] > 0):
                a, b, c = np.log(psd[k - 1 : k + 2])
                if a - 2 * b + c < 0:
                    shift = float(np.clip(0.5 * (a - c) / (a - 2 * b + c), -0.5, 0.5))
            out["lines"].append(
                {
                    "state": "CANDIDATE",
                    "nominal_hz": center,
                    "fundamental_hz": fundamental,
                    "harmonic": harmonic,
                    "estimated_hz": float(f[k] + shift * df),
                    "prominence_db": prominence,
                    "bin_width_hz": df,
                    "frequency_uncertainty_hz": None,
                    "cause": "UNIDENTIFIED",
                }
            )
    out["line_detection_state"] = "INSUFFICIENT_DURATION" if df > 2.5 else "SEARCHED"
    if out["lines"]:
        out["alerts"].append("Líneas espectrales candidatas próximas a red/armónicos; comprobar persistencia")
        out["actions"].append("Comprobar ruido en toma independiente antes de seleccionar un notch")
    out["spectrum"] = {
        "frequency_hz": f.tolist(),
        "noise_psd_native_units": psd.tolist(),
        "window": "HANN",
        "detrend": "MEAN_REMOVED",
        "bin_width_hz": df,
    }
    return out


def low_frequency_coherence(a: FloatArray, b: FloatArray, dt: float, band_hz: tuple[float, float]) -> dict[str, Any]:
    """No estima coherencia de un único segmento (sería artificialmente uno)."""
    if (
        a.shape != b.shape
        or a.ndim != 1
        or not np.isfinite(dt)
        or dt <= 0
        or not 0 < band_hz[0] < band_hz[1] < 1 / (2 * dt)
    ):
        raise ValueError("Par/intervalo/banda inválidos")
    segment = int(np.ceil(3 / (band_hz[0] * dt)))
    required = segment + 3 * (segment - segment // 2)
    if (
        a.size < required
        or not np.all(np.isfinite(a))
        or not np.all(np.isfinite(b))
        or np.std(a) == 0
        or np.std(b) == 0
    ):
        return {
            "state": "MISSING",
            "value": None,
            "required_duration_s": required * dt,
            "reason": "Se requieren cuatro segmentos y tres ciclos por segmento; no rellenar con ceros",
        }
    f, c = coherence(a, b, fs=1 / dt, window="hann", nperseg=segment, noverlap=segment // 2, detrend="constant")
    in_band = (f >= band_hz[0]) & (f <= band_hz[1]) & np.isfinite(c)
    return {
        "state": "MEASURED",
        "value": float(np.median(c[in_band])) if in_band.any() else None,
        "band_hz": band_hz,
        "segments": 1 + (a.size - segment) // (segment - segment // 2),
        "cause": "UNIDENTIFIED",
        "confidence_interval": None,
    }


def filter_candidate(
    data: FloatArray,
    dt: float,
    *,
    highpass_hz: float | None = None,
    notch_hz: tuple[float, ...] = (),
    q: float = 30,
    pick: Callable[[FloatArray], float | None] | None = None,
) -> tuple[FloatArray, dict[str, Any]]:
    """Devuelve copia experimental. Acuerdo de picks no equivale a exactitud del arribo."""
    if data.ndim != 1 or data.size < 32 or not np.all(np.isfinite(data)) or not np.isfinite(dt) or dt <= 0:
        raise ValueError("Filtrado requiere traza completa, finita y dt positivo")
    if not np.isfinite(q) or q <= 0:
        raise ValueError("Q debe ser positivo")
    nyquist = 1 / (2 * dt)
    frequencies = ([highpass_hz] if highpass_hz is not None else []) + list(notch_hz)
    if not frequencies or any(not np.isfinite(f) or not 0 < f < nyquist for f in frequencies):
        raise ValueError("Especificar frecuencias de filtro dentro de Nyquist")
    result = data.copy()
    steps: list[dict[str, Any]] = []
    if highpass_hz is not None:
        sos = butter(4, highpass_hz, btype="highpass", fs=1 / dt, output="sos")
        result = np.asarray(sosfiltfilt(sos, result), dtype=float)
        steps.append({"kind": "BUTTERWORTH_HIGHPASS", "hz": highpass_hz, "order_one_pass": 4, "sos": sos.tolist()})
    for hz in notch_hz:
        b, a = iirnotch(hz, q, fs=1 / dt)
        sos = tf2sos(b, a)
        result = np.asarray(sosfiltfilt(sos, result), dtype=float)
        steps.append({"kind": "NOTCH", "hz": hz, "Q": q, "sos": sos.tolist()})
    before = None if pick is None else pick(data.copy())
    after = None if pick is None else pick(result.copy())
    before = float(before) if before is not None and np.isfinite(before) else None
    after = float(after) if after is not None and np.isfinite(after) else None
    delta = None if before is None or after is None else after - before
    if delta is not None and not np.isfinite(delta):
        delta = None
    return result, {
        "status": "CANDIDATE_ONLY",
        "promoted_to_raw": False,
        "input_sha256": hashlib.sha256(data.tobytes()).hexdigest(),
        "output_sha256": hashlib.sha256(result.tobytes()).hexdigest(),
        "preprocessing_chain": steps,
        "implementation": "SOS forward-backward; SciPy default padding",
        "pick_before_s": before,
        "pick_after_s": after,
        "pick_delta_s": delta,
        "pick_stability": "UNVERIFIED" if delta is None else "PASS" if abs(delta) <= 0.25 * dt else "FAIL",
        "pick_tolerance_s": 0.25 * dt,
        "limitations": "Fase cero no garantiza onset invariante: revisar pre-ringing, amplitud, bordes y banda útil",
    }
