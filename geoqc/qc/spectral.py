from __future__ import annotations

import json

import numpy as np
from scipy.signal import periodogram, welch

from geoqc.core.models import Shot
from geoqc.qc.channels import diagnostic, window_samples
from geoqc.qc.contracts import Diagnostic, QCProtocol


def snr(shot: Shot, channel: int, protocol: QCProtocol) -> Diagnostic:
    """Potencias medias AC en ventanas físicas disjuntas, sin optimizar selección."""
    if protocol.noise is None or protocol.signal is None or not protocol.noise_independent:
        return diagnostic("snr_db", "MISSING", "dB", "Falta ventana independiente de ruido o de señal")
    if protocol.noise_stationarity != "VERIFIED":
        return diagnostic("snr_db", "MODEL_INAPPLICABLE", "dB", "Estacionariedad entre ventanas sin verificar")
    noise, nm = window_samples(shot, channel, protocol.noise)
    signal, sm = window_samples(shot, channel, protocol.signal)
    if min(noise.size, signal.size) < 8 or not np.all(nm) or not np.all(sm):
        return diagnostic("snr_db", "MISSING", "dB", "Ventanas incompletas o enmascaradas; no se comprimen huecos")
    noise, signal = noise - noise.mean(), signal - signal.mean()
    pn, ps = float(np.mean(noise**2)), float(np.mean(signal**2))
    details: dict[str, object] = {
        "noise_power": pn,
        "signal_total_power": ps,
        "dc_removed": "per_window_mean",
        "noise_samples": noise.size,
        "signal_samples": signal.size,
        "stationarity_ref": protocol.stationarity_ref,
    }
    if pn <= 0:
        return diagnostic(
            "snr_db",
            "CENSORED",
            "dB",
            "Ruido AC cero; límite superior no finito, no estimación",
            details_json=json.dumps(details),
        )
    total = ps / pn
    net = max(total - 1, 0.0)
    details.update(
        snr_total_ratio=total, snr_net_ratio=net, snr_total_db=float(10 * np.log10(total)) if total > 0 else None
    )
    if net <= 0:
        return diagnostic(
            "snr_db",
            "CENSORED",
            "dB",
            "Sustracción no positiva: potencia neta no resuelta",
            details_json=json.dumps(details),
        )
    return diagnostic(
        "snr_db",
        "VALID",
        "dB",
        "10log10((P_total-P_ruido)/P_ruido); estimación sin CI de campo",
        value=float(10 * np.log10(net)),
        details_json=json.dumps(details),
    )


def noise_psd(shot: Shot, channel: int, protocol: QCProtocol) -> dict[str, object]:
    if protocol.noise is None or protocol.signal is None or not protocol.noise_independent:
        return {"state": "MISSING", "reason": "Ventanas independientes ausentes"}
    if protocol.noise_stationarity != "VERIFIED":
        return {"state": "MODEL_INAPPLICABLE", "reason": "Estacionariedad no verificada"}
    noise, nm = window_samples(shot, channel, protocol.noise)
    signal, sm = window_samples(shot, channel, protocol.signal)
    segment = protocol.welch_segment_samples
    if min(noise.size, signal.size) < segment or not np.all(nm) or not np.all(sm):
        return {"state": "MISSING", "reason": "Welch requiere segmentos completos, sin huecos"}
    fs = 1 / shot.dt_s[channel]
    options = {
        "fs": fs,
        "window": "hann",
        "nperseg": segment,
        "noverlap": segment // 2,
        "detrend": False,
        "scaling": "density",
    }
    f, pn = welch(noise - noise.mean(), **options)
    _, ps = welch(signal - signal.mean(), **options)
    raw = ps - pn
    segments = 1 + (noise.size - segment) // (segment - segment // 2)
    duration = segment / fs
    return {
        "state": "VALID",
        "frequency_hz": f.tolist(),
        "noise_psd": pn.tolist(),
        "signal_total_psd": ps.tolist(),
        "net_psd": np.maximum(raw, 0).tolist(),
        "net_positive_mask": (raw > 0).tolist(),
        "unit": f"{shot.acquisition.amplitude_unit}^2/Hz",
        "segment_duration_s": duration,
        "bin_width_hz": fs / segment,
        "noise_segments": int(segments),
        "dof_upper_bound": int(2 * segments),
        "reason": "Hann 50% overlap; segmentos correlacionados, DOF efectivo/CI no calibrados",
        "minimum_band_cycles_per_segment": None
        if protocol.frequency_band_hz is None
        else duration * protocol.frequency_band_hz[0],
    }


def mains_line(shot: Shot, channel: int, protocol: QCProtocol) -> Diagnostic:
    if protocol.mains_hz is None:
        return diagnostic("mains_line", "MISSING", "Hz", "Frecuencia de red del sitio no declarada")
    data, mask = window_samples(shot, channel, protocol.analysis)
    if data.size < 16 or not np.all(mask):
        return diagnostic("mains_line", "MISSING", "Hz", "Ventana espectral incompleta")
    dt = shot.dt_s[channel]
    resolution = 1 / (data.size * dt)
    if resolution > protocol.mains_search_hz / 2:
        return diagnostic("mains_line", "MODEL_INAPPLICABLE", "Hz", "Duración insuficiente para buscar línea de red")
    center, width = protocol.mains_hz, protocol.mains_search_hz
    if center - 3 * width <= 0 or center + 3 * width >= 1 / (2 * dt):
        return diagnostic("mains_line", "MODEL_INAPPLICABLE", "Hz", "Banda de control fuera de Nyquist")
    f, power = periodogram(data - data.mean(), fs=1 / dt, window="hann", scaling="density")
    candidate = np.flatnonzero(abs(f - center) <= width)
    controls = (abs(f - center) > width) & (abs(f - center) <= 3 * width)
    index = int(candidate[np.argmax(power[candidate])])
    floor = float(np.median(power[controls]))
    peak = float(power[index])
    ratio = peak / floor if floor > 0 else None
    detected = peak > 0 and (floor == 0 or peak > protocol.line_power_ratio * floor)
    return diagnostic(
        "mains_line",
        "VALID",
        "Hz",
        "Pico Hann frente a mediana de bandas laterales; resolución por duración",
        value=float(f[index]) if detected else None,
        flagged=bool(detected),
        details_json=json.dumps(
            {
                "bin_width_hz": resolution,
                "frequency_half_bin_hz": resolution / 2,
                "peak_to_background": ratio,
                "duration_s": data.size * dt,
            }
        ),
    )
