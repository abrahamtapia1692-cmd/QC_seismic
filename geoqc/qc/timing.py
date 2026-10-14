from __future__ import annotations

import json
import math

import numpy as np
from scipy.signal import correlate, correlation_lags, find_peaks

from geoqc.core.models import FloatArray, Shot
from geoqc.core.physics import geophone_response
from geoqc.qc.channels import diagnostic, window_samples
from geoqc.qc.contracts import Diagnostic, QCProtocol, RepeatProtocol


def time_budget(shot: Shot, channel: int, protocol: QCProtocol) -> dict[str, object]:
    dt, t0 = shot.dt_s[channel], shot.t0_s[channel]
    end = t0 + shot.data.shape[1] * dt
    data, mask = window_samples(shot, channel, protocol.analysis)
    usable = data.size * dt if data.size and np.all(mask) else None
    required = None
    if protocol.min_group_velocity_ms is not None:
        if shot.acquisition.technique != "MASW":
            raise ValueError("Presupuesto de grupo MASW no se aplica a primeras llegadas TRS")
        required = float(np.max(shot.geometry.horizontal_offsets_m)) / protocol.min_group_velocity_ms
        required += protocol.wavelet_duration_s + protocol.post_margin_s
    first_post = max(int(np.ceil(-t0 / dt - 1e-9)), 0)
    post_mask = shot.valid_mask[channel, first_post:]
    holes = np.flatnonzero(~post_mask)
    contiguous_end = t0 + (first_post + int(holes[0])) * dt if holes.size else end
    available = max(contiguous_end - protocol.guard_s, 0) if t0 <= 0 else 0
    band = protocol.frequency_band_hz
    return {
        "pre_s": min(max(-t0, 0), shot.data.shape[1] * dt),
        "post_s": max(end, 0),
        "guard_s": protocol.guard_s,
        "usable_s": usable,
        "fft_bin_hz": None if usable is None else 1 / usable,
        "post_required_s": required,
        "post_available_s": available,
        "post_sufficient": None if required is None else t0 <= 0 and available >= required,
        "budget_kind": "VERIFIED_GROUP_VELOCITY" if protocol.group_velocity_verified else "CONSERVATIVE_SCENARIO",
        "group_velocity_ref": protocol.group_velocity_ref,
        "nyquist_hz": 1 / (2 * dt),
        "band_policy_satisfied": None if band is None else band[1] <= protocol.nyquist_margin / (2 * dt),
        "antialias_verified": protocol.antialias_verified,
        "timebase_accuracy_state": "NOT_IDENTIFIABLE_WITHOUT_EXTERNAL_CLOCK_REFERENCE",
        "reason": "Padding no cambia resolución; escenario no demuestra banda ni velocidad de campo",
    }


def repeatability(reference: FloatArray, replicas: FloatArray, protocol: RepeatProtocol) -> dict[str, object]:
    """Dispersión muestral de lags a referencia común, sin calibración causal."""
    rows = np.asarray(replicas, dtype=float)
    if rows.ndim != 2:
        raise ValueError("Réplicas deben tener forma (repeticiones,muestras)")
    comparisons = [compare_repeats(reference, row, protocol) for row in rows]
    valid_lags = [result.value for result in comparisons if result.state == "VALID" and result.value is not None]
    all_valid = len(valid_lags) == len(comparisons) and len(valid_lags) >= 3
    jitter = diagnostic(
        "jitter_ms",
        "VALID" if all_valid else "MISSING",
        "ms",
        "Desviación muestral de lags con referencia compartida; causa y CI no calibrados"
        if all_valid
        else "Se requieren al menos tres réplicas identificables; no se excluyen ambiguas para certificar jitter",
        value=float(np.std(valid_lags, ddof=1) * 1000) if all_valid else None,
    )
    return {
        "jitter": jitter.model_dump(mode="json"),
        "comparisons": [result.model_dump(mode="json") for result in comparisons],
        "common_reference": protocol.reference,
        "eligible_for_acceptance": False,
    }


def compare_repeats(reference: FloatArray, observed: FloatArray, protocol: RepeatProtocol) -> Diagnostic:
    """Lag observado-reference: interpolación parabólica local de correlación absoluta."""
    if not protocol.same_source or not protocol.comparable_acquisition:
        return diagnostic("repeat", "MODEL_INAPPLICABLE", "s", "Fuente/componentes/adquisición no comparables")
    a, b = np.asarray(reference, dtype=float), np.asarray(observed, dtype=float)
    if a.ndim != 1 or b.shape != a.shape or a.size < 32 or not np.all(np.isfinite(a)) or not np.all(np.isfinite(b)):
        return diagnostic("repeat", "MISSING", "s", "Trazas finitas completas de igual forma requeridas")
    a, b = a - a.mean(), b - b.mean()
    norm = float(np.linalg.norm(a) * np.linalg.norm(b))
    if norm == 0:
        return diagnostic("repeat", "MISSING", "s", "Señal AC constante")
    f = np.fft.rfftfreq(a.size, protocol.dt_s)
    lo, hi = protocol.frequency_band_hz
    for samples in (a, b):
        energy = abs(np.fft.rfft(samples)) ** 2
        if float(energy[(f >= lo) & (f <= hi)].sum() / energy.sum()) < 0.95:
            return diagnostic("repeat", "MODEL_INAPPLICABLE", "s", "Menos del 95% de potencia en banda declarada")
    if a.size * protocol.dt_s < 5 / lo:
        return diagnostic("repeat", "MODEL_INAPPLICABLE", "s", "Duración menor a cinco ciclos de frecuencia mínima")
    corr = np.asarray(correlate(b, a, mode="full", method="fft") / norm)
    lags = correlation_lags(b.size, a.size, mode="full")
    allowed = np.flatnonzero(abs(lags * protocol.dt_s) <= protocol.max_lag_s)
    curve = abs(corr[allowed])
    local = int(np.argmax(curve))
    index = int(allowed[local])
    if local in (0, curve.size - 1):
        return diagnostic("repeat", "AMBIGUOUS", "s", "Máximo en borde de búsqueda; ampliar dominio físico")
    peaks, _ = find_peaks(curve)
    competitors = [p for p in peaks if abs(p - local) > 2 and curve[p] >= protocol.ambiguity_ratio * curve[local]]
    if competitors or curve[local] < protocol.min_abs_correlation:
        return diagnostic("repeat", "AMBIGUOUS", "s", "Picos periódicos equivalentes o baja correlación")
    left, middle, right = abs(corr[index - 1 : index + 2])
    denominator = left - 2 * middle + right
    shift = 0.0 if denominator == 0 else float(0.5 * (left - right) / denominator)
    lag = float((lags[index] + shift) * protocol.dt_s)
    return diagnostic(
        "repeat",
        "VALID",
        "s",
        "Lag relativo submuestra; causa trigger/fuente no separable; CI sin calibrar",
        value=lag,
        flagged=bool(corr[index] < 0),
        details_json=json.dumps(
            {
                "aligned_rho": float(corr[index]),
                "polarity_reversed_relative_to_reference": bool(corr[index] < 0),
                "lag_cause": "SOURCE_OR_TRIGGER_OR_PROPAGATION",
                "reference": protocol.reference,
                "method": "absolute cross-correlation, local parabolic interpolation",
            }
        ),
    )


def required_stacks(
    *,
    actual: int,
    snr_actual_db: float,
    snr_target_db: float,
    independent_noise: bool,
    comparable: bool,
    stack_kind: str,
) -> Diagnostic:
    if type(actual) is not int or actual < 1 or not all(math.isfinite(v) for v in (snr_actual_db, snr_target_db)):
        raise ValueError("N positivo y SNR finitos requeridos")
    if not independent_noise or not comparable or stack_kind != "MEAN":
        return diagnostic(
            "required_stacks", "MODEL_INAPPLICABLE", "count", "Requiere ruido independiente, comparabilidad y promedio"
        )
    exponent = (snr_target_db - snr_actual_db) / 10
    if exponent > 100:
        return diagnostic("required_stacks", "INVALID", "count", "Predicción fuera del rango operativo")
    count = max(actual, math.ceil(actual * 10**exponent))
    return diagnostic(
        "required_stacks",
        "VALID",
        "count",
        "Predicción condicionada a independencia, no garantía de mejora",
        value=float(count),
    )


def stack_noise_independence(noise_replicas: FloatArray, *, max_abs_rho: float = 0.2) -> Diagnostic:
    a = np.asarray(noise_replicas, dtype=float)
    if not 0 < max_abs_rho < 1:
        raise ValueError("Umbral candidato rho debe estar en (0,1)")
    if a.ndim != 2 or min(a.shape) < 2 or not np.all(np.isfinite(a)) or np.any(np.std(a, axis=1) == 0):
        return diagnostic(
            "noise_independence", "MISSING", "correlation", "Réplicas independientes de ruido incompletas"
        )
    matrix = np.corrcoef(a)
    maximum = float(np.max(abs(matrix[np.triu_indices(a.shape[0], 1)])))
    return diagnostic(
        "noise_independence",
        "VALID",
        "correlation",
        "Correlación muestral; no prueba universal de independencia",
        value=maximum,
        flagged=maximum >= max_abs_rho,
    )


def instrument_response(
    frequencies_hz: FloatArray, *, fn_hz: float, damping: float, calibration_ref: str | None = None
) -> dict[str, object]:
    f = np.asarray(frequencies_hz, dtype=float)
    if f.ndim != 1 or f.size == 0:
        raise ValueError("Frecuencias 1D no vacías requeridas")
    h = geophone_response(f, fn_hz, damping)
    return {
        "frequency_hz": f.tolist(),
        "real": h.real.tolist(),
        "imag": h.imag.tolist(),
        "magnitude": abs(h).tolist(),
        "calibration_state": "UNVERIFIED_REFERENCE" if calibration_ref else "MISSING",
        "calibration_ref": calibration_ref,
        "kind": "NOMINAL_SECOND_ORDER_VELOCITY",
        "reason": "Respuesta nominal relativa; f_n no es corte físico ni límite de profundidad",
    }
