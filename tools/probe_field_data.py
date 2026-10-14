"""Exploratory real-data diagnostics, without manufacturing acquisition sidecars.

The picking adapter deliberately carries only waveform samples and header time.
It is not a validated Shot and cannot authorize field acceptance. Unknown units,
response, geometry uncertainty and source timing remain unknown in the report.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import re
import sys
import warnings
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from obspy import read as obspy_read  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from geoqc.core.models import Shot  # noqa: E402
from geoqc.io.binary import parse_seg2  # noqa: E402
from geoqc.io.readers import try_read_shot  # noqa: E402
from geoqc.masw.curves import ridge_path  # noqa: E402
from geoqc.masw.transform import fk_reference, phase_shift  # noqa: E402
from geoqc.trs.contracts import PickProtocol  # noqa: E402
from geoqc.trs.picking import pick_shot  # noqa: E402

RAW = ROOT / "examples/field/raw"
OUT = ROOT / "evidence/field"


def save_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def save_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def sample_qc(data: np.ndarray) -> dict[str, Any]:
    finite = np.isfinite(data)
    if not np.all(finite):
        raise ValueError("Nonfinite samples: exploratory transforms must not conceal gaps")
    rms = np.sqrt(np.mean((data - data.mean(axis=1, keepdims=True)) ** 2, axis=1))
    return {
        "channels": int(data.shape[0]),
        "samples_per_channel": int(data.shape[1]),
        "finite_fraction": float(finite.mean()),
        "constant_channels_1based": (np.flatnonzero(np.ptp(data, axis=1) == 0) + 1).tolist(),
        "zero_channels_1based": (np.flatnonzero(np.all(data == 0, axis=1)) + 1).tolist(),
        "rms_ac_native_units": rms.tolist(),
        "amplitude_unit": "UNKNOWN",
        "clipping_status": "UNKNOWN_ADC_RAILS",
    }


def oysand(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    folder = RAW / "oysand/examples/Data"
    composite = np.loadtxt(folder / "Oysand_dc.txt", skiprows=1)
    reference_f = composite[:, 1] / composite[:, 0]
    sort = np.argsort(reference_f)
    reference_f, reference_c = reference_f[sort], composite[sort, 1]
    fig, axes = plt.subplots(2, 4, figsize=(17, 8), constrained_layout=True)
    results = []
    for i, offset in enumerate((10, 15, 20, 30)):
        path = folder / f"Oysand_dx_2m_x1_{offset}m_forward.dat"
        lines = path.read_text(encoding="utf-8").splitlines()
        fs = float(re.search(r"Measurement frequency \(Hz\): ([\d.]+)", lines[1])[1])
        dx = float(re.search(r"dx = ([\d.]+) m", lines[2])[1])
        x1 = float(re.search(r"x1 = ([\d.]+) m", lines[2])[1])
        data = np.loadtxt(path, skiprows=5).T
        checks.append(
            {
                "id": f"oysand_{offset}_shape_metadata",
                "passed": bool(data.shape[0] == 24 and fs == 1000 and dx == 2 and x1 == offset),
            }
        )
        stats = sample_qc(data)
        x = x1 + np.arange(data.shape[0]) * dx
        dt = 1 / fs
        time = np.arange(data.shape[1]) * dt
        centered = data - data.mean(axis=1, keepdims=True)
        u = np.fft.rfft(centered * np.hanning(data.shape[1]), axis=1).T
        all_f = np.fft.rfftfreq(data.shape[1], dt)
        selection = (all_f >= 5) & (all_f <= 70)
        f, u = all_f[selection], u[selection]
        c = np.arange(60.0, 401.0)
        scores = phase_shift(u, f, x, c, direction=1)["coherence"]
        reverse = phase_shift(u, f, x, c, direction=-1)["coherence"]
        indices = ridge_path(scores, f, c)
        ridge = c[list(indices)]
        without_first = phase_shift(u[:, 1:], f, x[1:], c, direction=1)["coherence"]
        without_first_ridge = c[list(ridge_path(without_first, f, c))]
        # Independent amplitude-weighted Fourier stack: a different estimator.
        fk = np.vstack([fk_reference(u[j : j + 1], f[j : j + 1], x, f[j] / c)[0] for j in range(f.size)])
        fk_peak = c[np.argmax(fk, axis=1)]
        spatially_unaliased = ridge > 2 * dx * f
        in_reference = (f >= reference_f.min()) & (f <= reference_f.max())
        comparison = spatially_unaliased & in_reference
        delta = ridge[comparison] - np.interp(f[comparison], reference_f, reference_c)
        rows = [
            {
                "frequency_hz": float(f[j]),
                "apparent_ridge_ms": float(ridge[j]),
                "coherence": float(scores[j, indices[j]]),
                "fk_peak_ms": float(fk_peak[j]),
                "spatially_unaliased_candidate": bool(spatially_unaliased[j]),
                "on_velocity_grid_boundary": bool(indices[j] in (0, c.size - 1)),
                "mode_identity": "APPARENT",
                "calibration": "UNCALIBRATED",
            }
            for j in range(f.size)
        ]
        save_csv(OUT / f"oysand_{offset}m_ridge.csv", rows)
        np.savez_compressed(
            OUT / f"oysand_{offset}m_spectra.npz",
            frequencies_hz=f,
            velocities_ms=c,
            coherence=scores,
            reverse_coherence=reverse,
            fk_power=fk,
        )
        checks.append(
            {
                "id": f"oysand_{offset}_transform_finite_bounded",
                "passed": bool(np.all(np.isfinite(scores)) and np.min(scores) >= 0 and np.max(scores) <= 1),
            }
        )
        checks.append({"id": f"oysand_{offset}_ridge_complete", "passed": len(indices) == f.size})
        results.append(
            {
                "file": path.relative_to(ROOT).as_posix(),
                "offset_m": x1,
                "receiver_spacing_m": dx,
                "fs_hz": fs,
                "qc": stats,
                "duration_s": data.shape[1] * dt,
                "last_sample_time_s": float(time[-1]),
                "aperture_m": float(np.ptp(x)),
                "fft_window": "HANN_FULL_RECORD_DC_REMOVED",
                "frequency_bounds_hz": [float(f.min()), float(f.max())],
                "velocity_grid_ms": [float(c.min()), float(c.max()), 1],
                "ridge_coherence_median": float(np.median(scores[np.arange(f.size), indices])),
                "forward_max_coherence_median": float(np.median(scores.max(axis=1))),
                "reverse_max_coherence_median": float(np.median(reverse.max(axis=1))),
                "spatially_unaliased_ridge_bins": int(spatially_unaliased.sum()),
                "channel_1_sensitivity": {
                    "scope": "Drop only channel 1; preserve coordinates; trigger role is unresolved",
                    "median_absolute_ridge_shift_ms": float(np.median(abs(without_first_ridge - ridge))),
                    "max_absolute_ridge_shift_ms": float(np.max(abs(without_first_ridge - ridge))),
                },
                "comparison_to_upstream_composite": {
                    "scope": "Same-site composite curve; not independent ground truth or per-shot labels",
                    "bins": int(comparison.sum()),
                    "median_absolute_difference_ms": float(np.median(abs(delta))) if delta.size else None,
                    "rmse_ms": float(np.sqrt(np.mean(delta**2))) if delta.size else None,
                },
                "limitations": [
                    "Amplitude unit, response and geometry uncertainty not documented",
                    "Channel 1 is mentioned as trigger; keep upstream 24-channel convention provisionally",
                    "Spatial aliasing flags are geometric and do not validate modal identity",
                    "No field confidence intervals, significance or Vs30 acceptance",
                ],
            }
        )
        scale = np.max(abs(centered), axis=1)
        normalized = centered / np.where(scale > 0, scale, 1)[:, None]
        axes[0, i].pcolormesh(
            time, np.arange(1, 25), normalized, cmap="seismic", vmin=-1, vmax=1, shading="auto", rasterized=True
        )
        axes[0, i].set(xlabel="Tiempo desde inicio del archivo (s)", ylabel="Canal", title=f"Oysand: offset {offset} m")
        axes[1, i].pcolormesh(f, c, scores.T, cmap="viridis", vmin=0, vmax=1, shading="auto", rasterized=True)
        axes[1, i].plot(f[spatially_unaliased], ridge[spatially_unaliased], "w.", ms=2, label="Ridge aparente")
        axes[1, i].plot(reference_f, reference_c, color="tomato", lw=1.2, label="Compuesta del repositorio")
        axes[1, i].plot(f, 2 * dx * f, "--", color="orange", lw=1, label="Limite espacial c=2f dx")
        axes[1, i].set(xlabel="Frecuencia (Hz)", ylabel="Velocidad (m/s)", ylim=(60, 400))
        if i == 0:
            axes[1, i].legend(fontsize=7)
    fig.suptitle("Oysand: registros reales y dispersion exploratoria; sin calibracion de campo")
    fig.savefig(OUT / "oysand_masw.png", dpi=140)
    fig.savefig(OUT / "oysand_masw.svg")
    plt.close(fig)
    return results


def read_geometry(path: Path) -> tuple[dict[str, tuple[float, float]], np.ndarray]:
    sources, receivers = {}, []
    section = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] in ("SOURCES", "RECEIVERS"):
            section = parts[0]
        elif section == "SOURCES":
            sources[parts[0]] = (float(parts[1]), float(parts[2]))
        elif section == "RECEIVERS":
            receivers.append([float(parts[0]), float(parts[1])])
    return sources, np.asarray(receivers)


def read_sgt(path: Path) -> tuple[np.ndarray, np.ndarray]:
    lines = path.read_text(encoding="utf-8").splitlines()
    ns = int(lines[0].split()[0])
    sensors = np.asarray([[float(v) for v in line.split()] for line in lines[2 : 2 + ns]])
    nr = int(lines[2 + ns].split()[0])
    rows = np.asarray([[float(v) for v in line.split()] for line in lines[4 + ns : 4 + ns + nr]])
    if sensors.shape != (ns, 2) or rows.shape != (nr, 4):
        raise ValueError("SGT shape inconsistent with header")
    if np.any(rows[:, :2] != np.floor(rows[:, :2])) or np.any(rows[:, :2] < 1) or np.any(rows[:, :2] > ns):
        raise ValueError("SGT sensor indices must be valid 1-based integers")
    return sensors, rows


def chevremont(checks: list[dict[str, Any]]) -> dict[str, Any]:
    folder = RAW / "chevremont/example/Chevremont"
    sources, receivers = read_geometry(folder / "chevremont.geometry")
    sensors, annotations = read_sgt(folder / "test.sgt")
    protocol = PickProtocol(
        search={"start_s": 0, "end_s": 0.18},
        noise={"start_s": -0.25, "end_s": -0.05},
        domain_id="chevremont-exploratory-header-clock",
        provenance="Fixed exploratory protocol, not optimized to labels; header DELAY relative to source is unverified",
    )
    save_json(OUT / "chevremont_pick_protocol.json", protocol.model_dump(mode="json"))
    fig, axes = plt.subplots(2, 4, figsize=(17, 8), constrained_layout=True)
    results, pick_rows, comparison = [], [], []
    for i, (name, (sx, sz)) in enumerate(sources.items()):
        path = folder / name
        decoded = parse_seg2(path.read_bytes())
        data = np.stack(decoded.traces)
        checks.append({"id": f"{name}_geometry_channel_count", "passed": data.shape[0] == len(receivers)})
        checks.append(
            {
                "id": f"{name}_acquisition_channel_order",
                "passed": [int(h["CHANNEL_NUMBER"]) for h in decoded.headers["trace_headers"]]
                == list(range(1, data.shape[0] + 1)),
            }
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            other = obspy_read(str(path), format="SEG2")
        same = len(other) == len(decoded.traces) and all(
            np.array_equal(a, b.data) and dt == b.stats.delta
            for a, b, dt in zip(decoded.traces, other, decoded.dt_s, strict=True)
        )
        checks.append({"id": f"{name}_decode_vs_obspy", "passed": same})
        if any(t is None for t in decoded.t0_s) or not np.allclose(decoded.dt_s, decoded.dt_s[0]):
            raise ValueError("Exploratory timing needs explicit DELAY and equal sample intervals")
        # Structural adapter for array-only picking; never invent units/geometry certainty.
        adapter = SimpleNamespace(
            data=data,
            valid_mask=np.isfinite(data),
            dt_s=decoded.dt_s,
            t0_s=decoded.t0_s,
            acquisition=SimpleNamespace(technique="TRS", wave="P"),
        )
        picks = pick_shot(cast(Shot, adapter), protocol)
        failures = try_read_shot(path)
        checks.append(
            {
                "id": f"{name}_missing_sidecar_rejected",
                "passed": getattr(failures, "error_code", None) == "METADATA_MISSING",
            }
        )
        for j, pick in enumerate(picks):
            pick_rows.append(
                {
                    "file": name,
                    "source_x_m": sx,
                    "channel_1based": j + 1,
                    "receiver_x_m": float(receivers[j, 0]),
                    "onset_s": pick.onset_s,
                    "confidence": pick.confidence,
                    "reason": pick.reason,
                }
            )
        matched = 0
        for s, g, t, err in annotations:
            sp, gp = sensors[int(s) - 1], sensors[int(g) - 1]
            if not np.allclose(sp, [sx, sz], atol=0.011, rtol=0):
                continue
            channel_matches = np.flatnonzero(np.all(abs(receivers - gp) <= 0.011, axis=1))
            if channel_matches.size != 1:
                raise ValueError("Annotation does not map uniquely by source/receiver coordinates")
            channel = int(channel_matches[0])
            pick = picks[channel]
            comparison.append(
                {
                    "file": name,
                    "channel_1based": channel + 1,
                    "source_x_m": sx,
                    "receiver_x_m": float(receivers[channel, 0]),
                    "upstream_pick_s": float(t),
                    "upstream_err_s_unverified": float(err),
                    "automatic_onset_s": pick.onset_s,
                    "difference_ms": None if pick.onset_s is None else float(1000 * (pick.onset_s - t)),
                    "confidence": pick.confidence,
                    "reason": pick.reason,
                }
            )
            matched += 1
        time = float(decoded.t0_s[0]) + np.arange(data.shape[1]) * decoded.dt_s[0]
        visible = (time >= -0.02) & (time <= 0.2)
        centered = data - data.mean(axis=1, keepdims=True)
        scale = np.max(abs(centered[:, visible]), axis=1)
        image = centered[:, visible] / np.where(scale > 0, scale, 1)[:, None]
        ax = axes.flat[i]
        ax.pcolormesh(
            time[visible],
            np.arange(1, data.shape[0] + 1),
            image,
            cmap="seismic",
            vmin=-1,
            vmax=1,
            shading="auto",
            rasterized=True,
        )
        for j, pick in enumerate(picks):
            if pick.onset_s is not None:
                ax.plot(pick.onset_s, j + 1, "o", ms=3, color="lime")
        for row in comparison:
            if row["file"] == name:
                ax.plot(row["upstream_pick_s"], row["channel_1based"], ".", ms=4, color="gold")
        ax.set(title=f"Fuente x={sx:g} m", xlabel="Tiempo segun DELAY (s)", ylabel="Canal")
        headers = decoded.headers["trace_headers"]
        results.append(
            {
                "file": path.relative_to(ROOT).as_posix(),
                "source_xz_m": [sx, sz],
                "qc": sample_qc(data),
                "dt_s": decoded.dt_s[0],
                "header_delay_s": decoded.t0_s[0],
                "stack_headers": sorted({h.get("STACK", "MISSING") for h in headers}),
                "header_receiver_location_unique_count": len({h.get("RECEIVER_LOCATION") for h in headers}),
                "source_clock": "HEADER_DELAY_ASSUMPTION_UNVERIFIED",
                "wave": "P_ASSUMED_FOR_EXPLORATORY_PICKING_NOT_VERIFIED",
                "decoder_matches_obspy": same,
                "obspy_warnings": sorted({str(w.message) for w in caught}),
                "native_ingestion_error": getattr(failures, "error_code", None),
                "pick_states": dict(Counter(p.confidence for p in picks)),
                "pick_reasons": dict(Counter(p.reason for p in picks)),
                "matched_upstream_annotations": matched,
            }
        )
        save_json(OUT / f"chevremont_{int(sx)}m_headers.json", decoded.headers)
    axes.flat[7].axis("off")
    axes.flat[7].text(
        0,
        0.8,
        "Verde: onset automatico sin calibrar\nAmarillo: picks del repositorio\n"
        "DELAY -0.8 s usado provisionalmente\nUnidades y reloj de fuente sin verificar\n"
        "Abstenciones se conservan",
        transform=axes.flat[7].transAxes,
    )
    fig.suptitle("Chevremont: primeros arribos exploratorios; no aceptacion de campo")
    fig.savefig(OUT / "chevremont_trs.png", dpi=140)
    fig.savefig(OUT / "chevremont_trs.svg")
    plt.close(fig)
    save_csv(OUT / "chevremont_picks.csv", pick_rows)
    save_csv(OUT / "chevremont_annotation_comparison.csv", comparison)
    usable = [r["difference_ms"] for r in comparison if r["difference_ms"] is not None]
    matched_total = sum(r["matched_upstream_annotations"] for r in results)
    checks.append({"id": "all_sgt_annotations_mapped_by_coordinates", "passed": matched_total == len(annotations)})
    return {
        "shots": results,
        "annotation_count": len(annotations),
        "compared_onsets": len(usable),
        "conditional_mean_absolute_difference_ms": float(np.mean(abs(np.asarray(usable)))) if usable else None,
        "conditional_median_absolute_difference_ms": float(np.median(abs(np.asarray(usable)))) if usable else None,
        "conditional_median_signed_difference_ms": float(np.median(usable)) if usable else None,
        "annotation_scope": "43 labels from one source only; human/reference annotation, not independent truth",
        "geometry": {"receivers": receivers.tolist(), "vertical_span_m": float(np.ptp(receivers[:, 1]))},
        "limitations": [
            "Source clock and component/wave identity unverified",
            "UNITS NONE; no response, ADC rails or geometric uncertainty",
            "STACK 3; raw single-impact acquisitions unavailable",
            "Current horizontal layered inversion not verified for this site",
            "Conditional annotation differences require both abstention counts and verified timing",
        ],
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT / "examples/field/download_manifest.json").read_text(encoding="utf-8"))
    checks = []
    for item in manifest["files"]:
        path = ROOT / item["path"]
        checks.append(
            {"id": "sha256:" + item["path"], "passed": hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]}
        )
    if not all(c["passed"] for c in checks):
        raise ValueError("Download integrity check failed")
    masw = oysand(checks)
    trs = chevremont(checks)
    modules = [
        Path(__file__),
        ROOT / "geoqc/io/binary.py",
        ROOT / "geoqc/trs/picking.py",
        ROOT / "geoqc/masw/transform.py",
        ROOT / "geoqc/masw/curves.py",
    ]
    report = {
        "status": "EXPLORATORY_UNCALIBRATED",
        "eligible_for_acceptance": False,
        "executed_at_utc": datetime.now(UTC).isoformat(),
        "download_manifest": "examples/field/download_manifest.json",
        "repositories": manifest["repositories"],
        "checks": checks,
        "dependencies": {
            name: importlib.metadata.version(name) for name in ("numpy", "scipy", "pydantic", "obspy", "matplotlib")
        },
        "code_sha256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in modules},
        "oysand": masw,
        "chevremont": trs,
    }
    save_json(OUT / "results.json", report)
    print(
        json.dumps(
            {
                "checks_passed": sum(c["passed"] for c in checks),
                "checks_total": len(checks),
                "oysand_shapes": [(r["offset_m"], r["qc"]["channels"], r["qc"]["samples_per_channel"]) for r in masw],
                "chevremont_pick_states": {r["source_xz_m"][0]: r["pick_states"] for r in trs["shots"]},
                "compared_onsets": trs["compared_onsets"],
                "annotation_count": trs["annotation_count"],
                "conditional_mean_absolute_difference_ms": trs["conditional_mean_absolute_difference_ms"],
            },
            indent=2,
        )
    )
    if not all(c["passed"] for c in checks):
        raise SystemExit("Exploratory checks failed; inspect results.json")


if __name__ == "__main__":
    main()
