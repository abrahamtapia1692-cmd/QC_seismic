"""Exploratory stack diagnostics; signal similarity cannot certify shot count."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoqc.io.binary import parse_seg2  # noqa: E402


def rms(data: np.ndarray) -> np.ndarray:
    centered = data - data.mean(axis=1, keepdims=True)
    return np.sqrt(np.mean(centered**2, axis=1))


def median_finite(values: np.ndarray) -> float | None:
    valid = values[np.isfinite(values)]
    return float(np.median(valid)) if valid.size else None


def compare(previous: np.ndarray, current: np.ndarray, index: int) -> dict[str, Any]:
    if previous.shape != current.shape or previous.ndim != 2 or previous.shape[1] < 4:
        raise ValueError("Comparación requiere formas iguales y al menos cuatro muestras")
    a = previous - previous.mean(axis=1, keepdims=True)
    b = current - current.mean(axis=1, keepdims=True)
    aa, bb, ab = (np.sum(x, axis=1) for x in (a*a, b*b, a*b))
    valid = (aa > 0) & (bb > 0)
    correlation = np.full(aa.shape, np.nan)
    correlation[valid] = ab[valid] / np.sqrt(aa[valid] * bb[valid])
    ratio = np.full(aa.shape, np.nan)
    ratio[valid] = np.sqrt(bb[valid] / aa[valid])
    slope = np.zeros(aa.shape)
    np.divide(ab, aa, out=slope, where=aa > 0)
    residual = b - slope[:, None] * a
    relative_residual = np.full(aa.shape, np.nan)
    relative_residual[valid] = np.sqrt(np.sum(residual[valid]**2, axis=1) / bb[valid])
    return {
        "valid_channel_count": int(valid.sum()),
        "median_correlation": median_finite(correlation),
        "median_rms_ratio_current_over_previous": median_finite(ratio),
        "median_relative_residual_after_per_channel_gain_fit": median_finite(relative_residual),
        "hypothetical_new_hit_rms_if_cumulative_sum": median_finite(rms(current - previous)),
        "hypothetical_new_hit_rms_if_cumulative_mean_starting_at_one":
            median_finite(rms((index + 1) * current - index * previous)),
        "stack_count_inferred": None,
    }


def analyze(site: str, output: Path) -> dict[str, Any]:
    inventory_path = ROOT / "examples/km_app/preparation/inventory.json"
    inventory = json.loads(inventory_path.read_bytes())
    selected = [r for r in inventory["records"] if r["path"].startswith(site + "/")
                and r["category"] == "ACTIVE_TRS_FOLDER"]
    if not selected or output.exists():
        raise ValueError("Se requiere un sitio inventariado y un directorio de salida nuevo")
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in selected:
        groups[Path(record["path"]).parent.name].append(record)
    results = []
    f1_plot = None
    for group, records in sorted(groups.items(), key=lambda pair: int(pair[0][1:])):
        records.sort(key=lambda r: (r["file_header"]["ACQUISITION_DATE"], r["file_header"]["ACQUISITION_TIME"]))
        arrays, summaries, times, dts, starts = [], [], [], [], []
        for record in records:
            raw = (ROOT / record["path"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != record["sha256"]:
                raise ValueError("Original cambiado respecto al inventario: " + record["path"])
            waveform = parse_seg2(raw)
            data = np.stack(waveform.traces)
            arrays.append(data)
            dts.append(waveform.dt_s)
            starts.append(waveform.t0_s)
            header = waveform.headers["file_header"]
            times.append(datetime.fromisoformat(header["ACQUISITION_DATE"] + "T" + header["ACQUISITION_TIME"]))
            summaries.append({"path": record["path"], "sha256": record["sha256"],
                              "acquisition_time": header["ACQUISITION_TIME"],
                              "median_channel_rms_stored_units": median_finite(rms(data)),
                              "stack_header_values": sorted(set(record["stack_raw"]))})
        pairs = []
        for index in range(1, len(arrays)):
            if dts[index] != dts[index-1] or starts[index] != starts[index-1]:
                raise ValueError("Tiempos de canal incompatibles; no se realinean automáticamente")
            previous, current = arrays[index-1], arrays[index]
            tail = previous.shape[1] // 2
            pairs.append({"previous": index-1, "current": index,
                          "elapsed_seconds": (times[index] - times[index-1]).total_seconds(),
                          "full_record": compare(previous, current, index),
                          "last_half_record_not_verified_noise": compare(previous[:, tail:], current[:, tail:], index)})
        results.append({"source_folder": group, "record_count": len(records), "records": summaries, "pairs": pairs})
        if group == "F1":
            f1_plot = arrays, summaries, pairs, dts[0][0]
    result = {
        "scope": "EXPLORATORY_STACK_HYPOTHESES_NOT_ACQUISITION_CERTIFICATION", "site": site,
        "inventory_sha256": hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
        "notes": [note for note in inventory["notes"] if note["path"].startswith(site + "/")],
        "record_count": len(selected), "source_count": len(groups),
        "records_per_source_distribution": dict(Counter(len(records) for records in groups.values())),
        "stack_kind": "UNKNOWN", "stack_count": None,
        "limitations": ["One record can equal one hit or a hidden sum/mean of hits.",
                        "High correlation also occurs between independent hits with the same wavefield.",
                        "Hammer strength, gain and coupling confound amplitude trends.",
                        "The late window is not certified noise; residual signal can dominate.",
                        "Cumulative mean calculations assume count starts at one and uninterrupted export.",
                        "No automatic classification or confidence probability is calibrated."],
        "groups": results,
    }
    output.mkdir(parents=True)
    (output / "analysis.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                                          encoding="utf-8")
    if f1_plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        arrays, summaries, pairs, dt = f1_plot
        channel = int(np.argmax(rms(arrays[0])))
        fig, axes = plt.subplots(3, 1, figsize=(10, 9), constrained_layout=True)
        for i, data in enumerate(arrays):
            row = data[channel] - data[channel].mean()
            scale = np.max(np.abs(row))
            axes[0].plot(np.arange(row.size)*dt, row/scale if scale else row, alpha=.7, label=f"Registro {i+1}")
        axes[0].set(title=f"{site} / F1 / canal {channel+1}: amplitud normalizada", xlabel="Tiempo nominal (s)")
        axes[0].legend()
        axes[1].plot(range(1, len(arrays)+1), [r["median_channel_rms_stored_units"] for r in summaries], "o-")
        axes[1].set(xlabel="Registro en orden cronológico", ylabel="RMS mediana (unidad de archivo)")
        axes[2].plot(range(2, len(arrays)+1), [p["full_record"]["median_correlation"] for p in pairs], "o-", label="Registro completo")
        axes[2].plot(range(2, len(arrays)+1), [p["last_half_record_not_verified_noise"]["median_correlation"] for p in pairs], "o-", label="Mitad final; no certificada como ruido")
        axes[2].set(xlabel="Registro comparado con el anterior", ylabel="Correlación mediana", ylim=(-1.05, 1.05))
        axes[2].legend()
        fig.savefig(output / "f1_comparison.svg")
        plt.close(fig)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", default="KM 40+672")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.site, args.output)
    print(json.dumps({key: result[key] for key in ("site", "record_count", "source_count",
                                                  "records_per_source_distribution", "stack_kind")}, indent=2))


if __name__ == "__main__":
    main()
