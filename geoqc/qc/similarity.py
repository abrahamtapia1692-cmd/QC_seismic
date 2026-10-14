"""Consistencia local de formas de onda con desfase limitado por geometría.

No estima picks, no prueba causalidad instrumental y no certifica consistencia física.
Correlación Pearson por solape, sin rellenar ni comprimir huecos, sin filtrar la señal.
"""

from __future__ import annotations

from itertools import combinations
from typing import Any

import numpy as np

from geoqc.core.models import BoolArray, FloatArray
from geoqc.qc.contracts import SimilarityProtocol, Window


def lagged_correlation(a: FloatArray, b: FloatArray, max_lag: int) -> dict[str, Any] | None:
    """Lag positivo: a llega después de b. Magnitud para forma; signo se conserva.

    El signo del máximo no basta para inferir polaridad: puede haber ciclos equivalentes.
    Cada lag se normaliza con su propio solape y media (>=75% del registro).
    """
    if a.ndim != 1 or b.shape != a.shape or a.size < 16 or max_lag < 0 or max_lag > a.size // 4:
        raise ValueError("Pares completos de igual longitud y desfase con >=75% de solape requeridos")
    if not np.all(np.isfinite(a)) or not np.all(np.isfinite(b)):
        return None
    best: dict[str, Any] | None = None
    # Cero primero y luego lags próximos; empate exacto favorece el desfase menor.
    for lag in sorted(range(-max_lag, max_lag + 1), key=abs):
        aa = a[max(lag, 0) : min(a.size, a.size + lag)]
        bb = b[max(-lag, 0) : min(b.size, b.size - lag)]
        aa, bb = aa - aa.mean(), bb - bb.mean()
        norm = float(np.linalg.norm(aa) * np.linalg.norm(bb))
        if norm <= 0:
            continue
        rho = float(np.clip(np.dot(aa, bb) / norm, -1, 1))
        if best is None or abs(rho) > best["abs_rho"]:
            best = {
                "abs_rho": abs(rho),
                "signed_rho": rho,
                "lag_samples": lag,
                "overlap_samples": int(aa.size),
                "at_search_boundary": bool(max_lag and abs(lag) == max_lag),
            }
    return best


def _window(data: FloatArray, mask: BoolArray, dt: float, t0: float, window: Window) -> FloatArray | None:
    lo = int(np.ceil((window.start_s - t0) / dt - 1e-9))
    hi = int(np.ceil((window.end_s - t0) / dt - 1e-9))
    if lo < 0 or hi > data.size or hi - lo < 16 or not np.all(mask[lo:hi]):
        return None
    values = data[lo:hi]
    return values if np.all(np.isfinite(values)) and np.ptp(values) > 0 else None


def local_similarity(
    data: FloatArray,
    valid_mask: BoolArray,
    dt_s: tuple[float, ...],
    t0_s: tuple[float, ...],
    coordinates_m: FloatArray,
    protocol: SimilarityProtocol,
) -> tuple[dict[str, Any], ...]:
    """Contrasta cada canal con vecinos geométricos sin usarlo en el consenso de referencia."""
    if data.ndim != 2 or data.shape[0] == 0:
        raise ValueError("Se requiere una matriz no vacía de canales y muestras")
    n = data.shape[0]
    coords = np.asarray(coordinates_m, dtype=float)
    if (
        data.ndim != 2
        or valid_mask.shape != data.shape
        or len(dt_s) != n
        or len(t0_s) != n
        or coords.ndim != 2
        or coords.shape[0] != n
        or coords.shape[1] not in (1, 2, 3)
        or not np.all(np.isfinite(coords))
        or not np.all(np.isfinite(t0_s))
        or not np.all(np.isfinite(dt_s))
        or min(dt_s, default=0) <= 0
    ):
        raise ValueError("Datos, máscaras, tiempos y coordenadas deben ser compatibles y finitos")
    if not np.allclose(dt_s, dt_s[0], rtol=1e-9, atol=0):
        raise ValueError("Similitud requiere muestreo común; no se remuestrea silenciosamente")
    dt = dt_s[0]
    if not np.allclose((np.array(t0_s) - t0_s[0]) / dt, np.round((np.array(t0_s) - t0_s[0]) / dt), atol=1e-7, rtol=0):
        raise ValueError("Los relojes deben compartir la rejilla temporal")
    segments = [_window(data[j], valid_mask[j], dt, t0_s[j], protocol.arrival) for j in range(n)]
    distances = np.linalg.norm(coords[:, None, :] - coords[None, :, :], axis=2)
    pairs: dict[tuple[int, int], dict[str, Any] | None] = {}

    def pair(j: int, k: int) -> dict[str, Any] | None:
        key = (min(j, k), max(j, k))
        if key not in pairs:
            a, b = segments[key[0]], segments[key[1]]
            max_lag_s = min(protocol.max_lag_s, distances[j, k] / protocol.min_apparent_velocity_ms)
            limit = int(np.floor(max_lag_s / dt + 1e-9))
            value = None if a is None or b is None or a.shape != b.shape else lagged_correlation(a, b, limit)
            if value is not None:
                value.update(max_lag_s=limit * dt)
            pairs[key] = value
        result = pairs[key]
        if result is None:
            return None
        lag_samples = result["lag_samples"] * (1 if j < k else -1)
        return {
            **result,
            "lag_samples": lag_samples,
            "lag_s": lag_samples * dt,
            "neighbor_channel_1based": k + 1,
            "distance_m": float(distances[j, k]),
        }

    rows: list[dict[str, Any]] = []
    for j in range(n):
        row: dict[str, Any] = {
            "state": "MISSING",
            "grade": "REGULAR",
            "median_abs_rho": None,
            "neighbor_consensus_rho": None,
            "pairs": [],
            "reasons": [],
            "spectral_median_hz": None,
            "baseline_to_arrival_rms": None,
            "baseline_relative_to_neighbors": None,
            "reference": protocol.reference,
        }
        segment = segments[j]
        if not protocol.comparable_channels:
            row["reasons"] = ["Comparabilidad de componentes/receptores no declarada"]
        elif segment is None:
            row["reasons"] = ["Ventana de llegada incompleta, con huecos o constante"]
        else:
            power = abs(np.fft.rfft((segment - segment.mean()) * np.hanning(segment.size))) ** 2
            frequencies = np.fft.rfftfreq(segment.size, dt)
            row["spectral_median_hz"] = float(frequencies[np.searchsorted(np.cumsum(power), 0.5 * power.sum())])
            centroid = float(np.sum(frequencies * power) / power.sum())
            row["spectral_centroid_hz"] = centroid
            row["spectral_bandwidth_hz"] = float(np.sqrt(np.sum((frequencies - centroid) ** 2 * power) / power.sum()))
            row["arrival_rms_ac"] = float(np.std(segment))
            if protocol.baseline is not None:
                baseline = _window(data[j], valid_mask[j], dt, t0_s[j], protocol.baseline)
                if baseline is not None:
                    row["baseline_to_arrival_rms"] = float(np.std(baseline) / np.std(segment))
            candidates = [
                int(k)
                for k in np.argsort(distances[j], kind="stable")
                if k != j and 0 < distances[j, k] <= protocol.neighbor_radius_m
            ]
            neighbors = candidates[: protocol.max_neighbors]
            comparisons = [p for k in neighbors if (p := pair(j, k)) is not None]
            row["pairs"] = comparisons
            supported = [p["neighbor_channel_1based"] - 1 for p in comparisons]
            consensus = [p["abs_rho"] for a, b in combinations(supported, 2) if (p := pair(a, b)) is not None]
            if len(comparisons) < protocol.min_neighbors or not consensus:
                row["reasons"] = ["Vecinos comparables insuficientes; sin decisión local"]
            else:
                rho = float(np.median([p["abs_rho"] for p in comparisons]))
                consensus_rho = float(np.median(consensus))
                # Un vecino defectuoso no debe degradar a todos sus vecinos sanos.
                # Exigir una mayoría coherente de >=min_neighbors, sin usar el canal objetivo.
                coherent: tuple[int, ...] = ()
                for size in range(len(supported), max(protocol.min_neighbors - 1, len(supported) // 2), -1):
                    for subset in combinations(supported, size):
                        values = [p["abs_rho"] for a, b in combinations(subset, 2) if (p := pair(a, b)) is not None]
                        if len(values) == size * (size - 1) // 2 and min(values) >= protocol.neighbor_consensus_min:
                            coherent = subset
                            consensus_rho = float(np.median(values))
                            break
                    if coherent:
                        break
                low_fraction = sum(p["abs_rho"] < protocol.bad_below_rho for p in comparisons) / len(comparisons)
                row.update(
                    state="VALID",
                    median_abs_rho=rho,
                    neighbor_consensus_rho=consensus_rho,
                    low_correlation_fraction=low_fraction,
                    consensus_channels_1based=[k + 1 for k in coherent],
                )
                if not coherent:
                    row["reasons"] = ["Vecinos sin consenso: cambio lateral o referencia heterogénea; revisar"]
                elif rho < protocol.bad_below_rho and low_fraction >= protocol.bad_neighbor_fraction_min:
                    row["grade"] = "MALA"
                    row["reasons"] = [
                        f"Anomalía local de forma: correlación {rho:.3f}; vecinos coherentes {consensus_rho:.3f}"
                    ]
                elif rho < protocol.warn_below_rho:
                    row["reasons"] = [f"Similitud local intermedia: correlación {rho:.3f}; revisar"]
                else:
                    row["grade"] = "BUENA"
                    row["reasons"] = [f"Forma consistente con vecinos: correlación {rho:.3f}"]
        rows.append(row)
    for row in rows:
        row["actions"] = (
            []
            if row["grade"] == "BUENA"
            else [
                "Comparar ventanas/ramas de llegada y réplicas; verificar orden, coordenadas, ganancia y acople en campo"
            ]
        )
        neighbor_rms = [rows[p["neighbor_channel_1based"] - 1].get("arrival_rms_ac") for p in row["pairs"]]
        positive_rms = [v for v in neighbor_rms if v is not None and v > 0]
        row["local_amplitude_ratio"] = (
            row["arrival_rms_ac"] / float(np.median(positive_rms))
            if row.get("arrival_rms_ac") is not None and len(positive_rms) >= protocol.min_neighbors
            else None
        )
        ratios = [rows[p["neighbor_channel_1based"] - 1]["baseline_to_arrival_rms"] for p in row["pairs"]]
        valid = [r for r in ratios if r is not None and r > 0]
        if row["baseline_to_arrival_rms"] is not None and len(valid) >= protocol.min_neighbors:
            relative = row["baseline_to_arrival_rms"] / float(np.median(valid))
            row["baseline_relative_to_neighbors"] = relative
            if relative > protocol.baseline_ratio_warn:
                row["reasons"].append(
                    f"Energía relativa de línea base {relative:.1f}× la de los vecinos; no es SNR validada"
                )
                if row["grade"] == "BUENA":
                    row["grade"] = "REGULAR"
    return tuple(rows)
