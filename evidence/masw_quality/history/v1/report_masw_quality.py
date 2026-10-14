"""Dosier Oysand reproducible desde originales; diagnóstico multicanal sin aceptación."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import importlib.metadata
import json
import platform
import re
import sys
from datetime import UTC, datetime
from html import escape
from itertools import combinations
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.colors import ListedColormap  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from geoqc.core.evidence import canonical_hash  # noqa: E402
from geoqc.masw.curves import ridge_path  # noqa: E402
from geoqc.masw.transform import phase_shift  # noqa: E402

PROTOCOL = {
    "id": "OYSAND_MASW_DOSSIER_V1_DRAFT",
    "frequency_min_hz": 5.0,
    "frequency_max_hz": 70.0,
    "velocity_min_ms": 60.0,
    "velocity_max_ms": 400.0,
    "velocity_step_ms": 1.0,
    "slope_scale_ms_per_hz": 30.0,
    "penalty": 0.02,
    "window": "HANN_FULL_RECORD_DC_REMOVED",
    "sensitivity": ["RECTANGULAR_FULL_RECORD", "DROP_CHANNEL_1_PRESERVE_COORDINATES"],
    "coherence_threshold": None,
    "empirical_calibration": "NOT_VALIDATED",
    "required_target_band_hz": None,
    "planned_positions": None,
}
MISSING = [
    "Ruido independiente y SNR neto por banda",
    "Respuesta instrumental, unidades de amplitud y rails/escala ADC",
    "Papel del canal 1 (el header lo menciona como trigger)",
    "Significancia frente a ruido del sitio e identidad modal verificada",
    "Sesgo de campo cercano y aplicabilidad del modelo",
    "Incertidumbre de velocidades y comparación entre offsets",
    "Objetivo, plan de posiciones, resolución y validación de campo G9",
]
REASONS = {
    "EVIDENCE_PENDING": "Faltan ruido, respuesta, modo y calibración",
    "SPATIAL_NYQUIST": "Cresta en/fuera del dominio Nyquist uniforme",
    "GRID_EDGE": "Cresta en borde de la rejilla de velocidades",
    "KERNEL_REVIEW": "Soporte incompleto/irregular: evaluar kernel real",
    "NO_SUPPORT": "Menos de dos canales con amplitud espectral no nula",
}
STATE_LABEL = {"PENDING": "Pendiente", "REVIEW": "Revisión", "NO_SUPPORT": "Sin soporte"}
STATE_COLOR = {"PENDING": "#64748b", "REVIEW": "#b77900", "NO_SUPPORT": "#b91c1c"}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_inputs(root, manifest_path, paths):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {r["path"]: r["sha256"] for r in manifest["files"]}
    actual = {}
    for path in paths:
        key = path.relative_to(root).as_posix()
        actual[key] = sha256(path)
        if expected.get(key) != actual[key]:
            raise ValueError(f"Original ausente del manifiesto o hash modificado: {key}")
    return actual


def classify_support(f, c, dx, *, edge, observed, uniform_complete):
    if not observed:
        return "NO_SUPPORT", ["NO_SUPPORT"]
    reasons = []
    if not uniform_complete:
        reasons.append("KERNEL_REVIEW")
    elif c <= 2 * dx * f:
        reasons.append("SPATIAL_NYQUIST")
    if edge:
        reasons.append("GRID_EDGE")
    return ("REVIEW" if reasons else "PENDING"), reasons + ["EVIDENCE_PENDING"]


def band_rows(points, df):
    groups = []
    for p in points:
        identity = (p["state"], p["reasons"], p["support_ids"])
        if (
            not groups
            or groups[-1]["identity"] != identity
            or p["frequency_hz"] - groups[-1]["f_bounds_hz"][1] > df * (1 + 1e-9)
        ):
            groups.append(
                {
                    "identity": identity,
                    "f_bounds_hz": [p["frequency_hz"], p["frequency_hz"]],
                    "state": p["state"],
                    "reasons": p["reasons"],
                    "support_ids": p["support_ids"],
                    "bins": 0,
                }
            )
        groups[-1]["f_bounds_hz"][1] = p["frequency_hz"]
        groups[-1]["bins"] += 1
    return [{k: v for k, v in g.items() if k != "identity"} for g in groups]


def analyze(data, dt, x, record_id, protocol):
    data, x = np.asarray(data, float), np.asarray(x, float)
    if (
        data.ndim != 2
        or data.shape[0] < 3
        or data.shape[1] < 32
        or x.shape != (data.shape[0],)
        or not np.isfinite(dt)
        or dt <= 0
        or not np.all(np.isfinite(data))
        or not np.all(np.isfinite(x))
        or np.any(np.diff(x) <= 0)
    ):
        raise ValueError("Registro finito canales×muestras, dt positivo y coordenadas crecientes requeridos")
    centered = data - data.mean(axis=1, keepdims=True)
    all_f = np.fft.rfftfreq(data.shape[1], dt)
    selection = (all_f >= protocol["frequency_min_hz"]) & (all_f <= protocol["frequency_max_hz"])
    f = all_f[selection]
    if f.size < 2:
        raise ValueError("Registro sin soporte de frecuencia para el protocolo")
    c = np.arange(
        protocol["velocity_min_ms"],
        protocol["velocity_max_ms"] + protocol["velocity_step_ms"] / 2,
        protocol["velocity_step_ms"],
    )
    spectrum = np.fft.rfft(centered * np.hanning(data.shape[1]), axis=1).T[selection]
    result = phase_shift(spectrum, f, x, c, direction=1)
    reverse = phase_shift(spectrum, f, x, c, direction=-1)["coherence"]

    def path(score):
        return np.asarray(
            ridge_path(
                score, f, c, slope_scale_ms_per_hz=protocol["slope_scale_ms_per_hz"], penalty=protocol["penalty"]
            ),
            dtype=int,
        )

    index = path(result["coherence"])
    ridge = c[index]
    dropped = phase_shift(spectrum[:, 1:], f, x[1:], c)["coherence"]
    rectangular = np.fft.rfft(centered, axis=1).T[selection]
    rectangle_scores = phase_shift(rectangular, f, x, c)["coherence"]
    drop_ridge, rectangle_ridge = c[path(dropped)], c[path(rectangle_scores)]
    dx = float(x[1] - x[0])
    uniform = np.allclose(np.diff(x), dx, rtol=1e-12, atol=0)
    points = []
    for j, frequency in enumerate(f):
        observed = bool(result["n_active"][j] >= 2)
        complete = bool(uniform and result["active"][j].all())
        state, reasons = classify_support(
            frequency, ridge[j], dx, edge=index[j] in (0, c.size - 1), observed=observed, uniform_complete=complete
        )
        points.append(
            {
                "frequency_hz": float(frequency),
                "velocity_ms": float(ridge[j]) if observed else None,
                "coherence": float(result["coherence"][j, index[j]]) if observed else None,
                "state": state,
                "grade": "REGULAR" if state == "REVIEW" else "NO_EVALUABLE",
                "reasons": reasons,
                "support_ids": (np.flatnonzero(result["active"][j]) + 1).tolist(),
                "uniform_complete_support": complete,
                "mode_identity": "APPARENT" if observed else "UNKNOWN",
                "sigma_ms": None,
                "validated": False,
                "drop_channel_1_velocity_ms": float(drop_ridge[j])
                if np.count_nonzero(abs(spectrum[j, 1:])) >= 2
                else None,
                "rectangular_velocity_ms": float(rectangle_ridge[j]) if observed else None,
            }
        )
    traces = [
        {
            "channel_1based": i + 1,
            "rms_ac_native": float(np.sqrt(np.mean(row**2))),
            "constant": bool(np.ptp(data[i]) == 0),
            "zero": bool(np.all(data[i] == 0)),
            "grade": "MALA" if np.ptp(data[i]) == 0 else "NO_EVALUABLE",
            "reason": "Canal constante" if np.ptp(data[i]) == 0 else "Muestras finitas; SNR y clipping pendientes",
        }
        for i, row in enumerate(centered)
    ]
    candidate = np.array([p["state"] == "PENDING" for p in points])
    summary = {
        "id": record_id,
        "channels": data.shape[0],
        "samples": data.shape[1],
        "dt_s": dt,
        "duration_samples_s": data.shape[1] * dt,
        "last_sample_s": (data.shape[1] - 1) * dt,
        "aperture_m": float(np.ptp(x)),
        "dx_m": dx,
        "frequency_bin_hz": 1 / (data.shape[1] * dt),
        "traces": traces,
        "points": points,
        "bands": band_rows(points, float(f[1] - f[0])),
        "sample_integrity": "PASS",
        "amplitude_unit": "UNKNOWN",
        "mode_identity": "APPARENT",
        "acquisition_grade": "MALA" if any(t["constant"] for t in traces) else "NO_EVALUABLE",
        "overall_grade": "MALA" if all(t["constant"] for t in traces) else "NO_EVALUABLE",
        "evidence_status": "INCOMPLETE",
        "eligible_for_acceptance": False,
        "missing_evidence": MISSING,
        "validated_bands": [],
        "candidate_bins": int(candidate.sum()),
        "review_bins": sum(p["state"] == "REVIEW" for p in points),
        "no_support_bins": sum(p["state"] == "NO_SUPPORT" for p in points),
        "bin_counts_are_not_quality_percentages": True,
    }
    arrays = dict(
        data=data,
        x_m=x,
        frequencies_hz=f,
        velocities_ms=c,
        coherence=result["coherence"],
        reverse_coherence=reverse,
        ridge_ms=ridge,
        drop_ridge_ms=drop_ridge,
        rectangular_ridge_ms=rectangle_ridge,
        candidate_mask=candidate,
        fourier_magnitude=np.abs(spectrum),
        n_active=result["n_active"],
    )
    return summary, arrays


def load_records():
    folder = ROOT / "examples/field/raw/oysand/examples/Data"
    dataset = folder / "Oysand_example_dataset.csv"
    rows = list(csv.DictReader(dataset.read_text(encoding="utf-8-sig").splitlines()))
    paths = [folder.parent / row["file_name"] for row in rows]
    inputs = verify_inputs(ROOT, ROOT / "examples/field/download_manifest.json", [dataset, *paths])
    records, arrays = [], {}
    for row, path in zip(rows, paths, strict=True):
        lines = path.read_text(encoding="utf-8").splitlines()
        fs = float(re.search(r"Measurement frequency \(Hz\): ([\d.]+)", lines[1])[1])
        dx = float(re.search(r"dx = ([\d.]+) m", lines[2])[1])
        offset = float(re.search(r"x1 = ([\d.]+) m", lines[2])[1])
        data = np.loadtxt(path, skiprows=int(row["header_lines"])).T
        if (
            data.shape[0] != int(row["n"])
            or dx != float(row["dx"])
            or offset != float(row["x1"])
            or row["direction"] != "forward"
            or row["profile"] != "P1"
        ):
            raise ValueError("Cabecera/dataset incompatibles con protocolo Oysand P1")
        record, values = analyze(data, 1 / fs, offset + np.arange(data.shape[0]) * dx, row["record_id"], PROTOCOL)
        record.update(
            offset_m=offset,
            site=row["site"],
            profile=row["profile"],
            direction="forward",
            source_file=path.relative_to(ROOT).as_posix(),
            input_hash=inputs[path.relative_to(ROOT).as_posix()],
        )
        records.append(record)
        arrays[record["id"]] = values
    return records, arrays, inputs


def compare_records(records, arrays):
    comparisons = []
    for a, b in combinations(records, 2):
        aa, bb = arrays[a["id"]], arrays[b["id"]]
        f, ia, ib = np.intersect1d(aa["frequencies_hz"], bb["frequencies_hz"], return_indices=True)
        mask = aa["candidate_mask"][ia] & bb["candidate_mask"][ib]
        delta = aa["ridge_ms"][ia[mask]] - bb["ridge_ms"][ib[mask]]
        comparisons.append(
            {
                "a": a["id"],
                "b": b["id"],
                "common_bins": int(mask.sum()),
                "common_frequencies_hz": f[mask].tolist(),
                "median_abs_delta_ms": float(np.median(abs(delta))) if delta.size else None,
                "max_abs_delta_ms": float(np.max(abs(delta))) if delta.size else None,
                "uncertainty_status": "NOT_CALIBRATED",
                "consistency_grade": "NO_EVALUABLE",
                "scope": "Diferencias entre offsets en soporte candidato; no repetibilidad ni error contra verdad",
            }
        )
    return comparisons


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in row.items()}
            )


def footer(fig):
    fig.text(
        0.02,
        0.015,
        "GeoQC · MASW diagnóstico | APPARENT · sin aceptación de campo/Vs30 | Originales conservados",
        fontsize=9,
        color="#475569",
    )


def summary_figure(records, comparisons):
    fig = plt.figure(figsize=(11.7, 8.3), facecolor="white")
    fig.text(0.06, 0.91, "OYSAND / P1", fontsize=26, weight="bold", color="#0f172a")
    fig.text(0.06, 0.86, "Dosier de calidad diagnóstica MASW", fontsize=19)
    fig.text(0.06, 0.78, "4 registros · 96 trazas · 1 sitio / perfil", fontsize=17, color="#0369a1")
    fig.text(0.06, 0.71, "Evaluación integral: NO EVALUABLE     Evidencia: INCOMPLETE", fontsize=14, color="#64748b")
    fig.text(
        0.06,
        0.65,
        "Integridad de muestras: PASS en los cuatro registros. No se encontraron canales constantes.",
        fontsize=11,
    )
    table = [[r["id"], f"{r['offset_m']:g}", r["candidate_bins"], r["review_bins"], "Pendiente"] for r in records]
    ax = fig.add_axes((0.06, 0.39, 0.88, 0.23))
    ax.axis("off")
    t = ax.table(
        cellText=table,
        colLabels=["Registro", "Offset (m)", "Bins candidatos*", "Bins en revisión", "Evaluación"],
        loc="center",
        cellLoc="center",
    )
    t.auto_set_font_size(False)
    t.set_fontsize(11)
    t.scale(1, 1.7)
    fig.text(
        0.06,
        0.36,
        "* Interiores a rejilla y Nyquist regular; NO son bandas validadas ni porcentajes de calidad.",
        fontsize=10,
    )
    notes = [
        "Plan de posiciones y banda objetivo: desconocidos. Cobertura porcentual del estudio: no calculable.",
        "Faltan SNR independiente, instrumento, identidad modal, incertidumbre y campo cercano.",
        "Los offsets aportan observaciones distintas; no equivalen a cuatro sitios ni a réplicas idénticas.",
        "Acciones: verificar canal trigger/ADC y geometría; adquirir ruido independiente y réplicas comparables.",
        "Después: resolver bandas/modos, justificar el objetivo y evaluar resolución. No se calcula Vs30.",
    ]
    for i, note in enumerate(notes):
        fig.text(0.06, 0.29 - i * 0.046, note, fontsize=10)
    footer(fig)
    return fig


def comparison_figure(records, arrays, comparisons):
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    fig.subplots_adjust(left=0.07, right=0.96, top=0.89, bottom=0.13, hspace=0.42, wspace=0.28)
    for record in records:
        a = arrays[record["id"]]
        f = a["frequencies_hz"]
        mask = a["candidate_mask"]
        (line,) = axes[0, 0].plot(f, a["ridge_ms"], alpha=0.25)
        axes[0, 0].plot(
            f,
            np.where(mask, a["ridge_ms"], np.nan),
            color=line.get_color(),
            label=f"{record['id']} · {record['offset_m']:g} m",
        )
        axes[1, 0].plot(f, np.where(mask, abs(a["drop_ridge_ms"] - a["ridge_ms"]), np.nan), label=record["id"])
    axes[0, 0].set(
        title="Curvas aparentes: trazo fuerte = soporte candidato", xlabel="Frecuencia (Hz)", ylabel="c aparente (m/s)"
    )
    axes[0, 0].legend(fontsize=9)
    axes[1, 0].set(
        title="Sensibilidad al excluir canal 1 · no es incertidumbre", xlabel="Frecuencia (Hz)", ylabel="|Δc| (m/s)"
    )
    state_value = {"PENDING": 0, "REVIEW": 1, "NO_SUPPORT": 2}
    matrix = [[state_value[p["state"]] for p in r["points"]] for r in records]
    f = arrays[records[0]["id"]]["frequencies_hz"]
    axes[0, 1].imshow(
        matrix,
        aspect="auto",
        interpolation="nearest",
        extent=[f[0], f[-1], len(records) - 0.5, -0.5],
        cmap=ListedColormap([STATE_COLOR[s] for s in state_value]),
        vmin=0,
        vmax=2,
    )
    axes[0, 1].set(
        yticks=range(len(records)),
        yticklabels=[r["id"] for r in records],
        xlabel="Frecuencia (Hz)",
        title="Gris: pendiente · ámbar: revisión · rojo: sin soporte",
    )
    axes[1, 1].axis("off")
    table = [
        [f"{c['a']} / {c['b']}", c["common_bins"], fmt(c["median_abs_delta_ms"]), fmt(c["max_abs_delta_ms"])]
        for c in comparisons
    ]
    tb = axes[1, 1].table(
        cellText=table, colLabels=["Par", "Bins comunes", "Mediana |Δc|", "Máx. |Δc|"], loc="center", cellLoc="center"
    )
    tb.auto_set_font_size(False)
    tb.set_fontsize(10)
    tb.scale(1, 1.8)
    axes[1, 1].set_title("Diferencias en m/s · sin prueba de significancia", pad=12)
    fig.suptitle("Oysand / P1 — comparación entre offsets y soporte por frecuencia", fontsize=17)
    footer(fig)
    return fig


def record_figure(record, a):
    fig, axes = plt.subplots(2, 3, figsize=(16, 10))
    fig.subplots_adjust(left=0.06, right=0.95, bottom=0.12, top=0.89, wspace=0.35, hspace=0.4)
    data = a["data"] - a["data"].mean(axis=1, keepdims=True)
    scale = np.max(abs(data), axis=1)
    time = np.arange(data.shape[1]) * record["dt_s"]
    for j, row in enumerate(data):
        axes[0, 0].plot(time, j + 1 + 0.4 * row / (scale[j] or 1), lw=0.4, color="#0f172a")
    axes[0, 0].set(
        title="Trazas normalizadas solo para visualizar", xlabel="Tiempo desde inicio del archivo (s)", ylabel="Canal"
    )
    axes[0, 0].invert_yaxis()
    axes[0, 1].bar(
        np.arange(1, len(record["traces"]) + 1), [t["rms_ac_native"] for t in record["traces"]], color="#0369a1"
    )
    axes[0, 1].set(title="RMS AC · amplitudes nativas", xlabel="Canal", ylabel="Unidad no documentada")
    f, c = a["frequencies_hz"], a["velocities_ms"]
    for ax, key, title in (
        (axes[0, 2], "coherence", "Coherencia I · dirección +1"),
        (axes[1, 2], "reverse_coherence", "Coherencia I · dirección −1"),
    ):
        im = ax.pcolormesh(f, c, a[key].T, shading="auto", vmin=0, vmax=1, cmap="viridis", rasterized=True)
        ax.plot(f, 2 * record["dx_m"] * f, "--", color="#fb923c", lw=1, label="c = 2 f dx")
        ax.set(title=title, xlabel="Frecuencia (Hz)", ylabel="Velocidad (m/s)", ylim=(c[0], c[-1]))
        fig.colorbar(im, ax=ax, label="I (no energía modal)", fraction=0.045)
    axes[0, 2].plot(f, a["ridge_ms"], color="white", lw=1, label="Cresta aparente")
    axes[0, 2].legend(fontsize=8)
    for key, label in (
        ("ridge_ms", "Hann · 24 ch"),
        ("drop_ridge_ms", "Hann · sin canal 1"),
        ("rectangular_ridge_ms", "Rectangular · 24 ch"),
    ):
        axes[1, 0].plot(f, np.where(a["n_active"] >= 2, a[key], np.nan), lw=1, label=label)
    axes[1, 0].set(title="Sensibilidad del procesamiento", xlabel="Frecuencia (Hz)", ylabel="c aparente (m/s)")
    axes[1, 0].legend(fontsize=8)
    axes[1, 1].plot(f, np.median(a["fourier_magnitude"], axis=1), color="#0369a1")
    axes[1, 1].set(
        title="Mediana de |FFT| por frecuencia", xlabel="Frecuencia (Hz)", ylabel="Amplitud DFT nativa · no PSD/SNR"
    )
    fig.suptitle(
        f"{record['id']} · offset {record['offset_m']:g} m · 24 canales × dx 2 m · L = 46 m\n"
        "Calidad integral NO EVALUABLE · modo APPARENT · evidencia INCOMPLETE",
        fontsize=16,
    )
    footer(fig)
    return fig


def geometry_figure(records):
    fig, axes = plt.subplots(2, 1, figsize=(14, 9), gridspec_kw={"height_ratios": [1, 1.3]})
    fig.subplots_adjust(top=0.87, bottom=0.16, hspace=0.5, left=0.1, right=0.95)
    for j, r in enumerate(records):
        receivers = np.arange(r["channels"]) * r["dx_m"]
        axes[0].plot([-r["offset_m"], receivers[-1]], [j, j], color="#cbd5e1")
        axes[0].scatter(receivers, np.full(receivers.size, j), marker="v", s=24, color="#0369a1")
        axes[0].scatter([-r["offset_m"]], [j], marker="*", s=140, color="#b77900")
    axes[0].set(
        yticks=range(len(records)),
        yticklabels=[r["id"] for r in records],
        xlabel="Coordenada relativa al primer receptor de CADA registro (m)",
        title="Estrella: fuente · triángulos: receptores · no es un mapa georreferenciado",
    )
    axes[1].axis("off")
    rows = [
        [
            r["id"],
            f"{b['f_bounds_hz'][0]:.2f}–{b['f_bounds_hz'][1]:.2f}",
            STATE_LABEL[b["state"]],
            "Evidencia pendiente" if b["state"] == "PENDING" else "Revisar muestreo espacial / rejilla",
        ]
        for r in records
        for b in r["bands"]
    ]
    table = axes[1].table(
        cellText=rows,
        colLabels=["Registro", "Intervalo (Hz)", "Estado", "Interpretación"],
        loc="center",
        cellLoc="center",
        colWidths=[0.12, 0.2, 0.18, 0.5],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 1.7)
    fig.suptitle("Geometría declarada y bandas diagnósticas", fontsize=18)
    fig.text(
        0.1,
        0.08,
        "Límites en centros de bins: resolución FFT ≈0.454 Hz. Los intervalos pendientes NO son bandas validadas.",
        fontsize=10,
    )
    footer(fig)
    return fig


def fmt(value):
    return "—" if value is None else f"{value:.2f}"


def render_html(report, output):
    def picture(name, alt):
        encoded = base64.b64encode((output / name).read_bytes()).decode("ascii")
        return f'<img alt="{escape(alt)}" src="data:image/png;base64,{encoded}">'

    blocks = []
    for record in report["records"]:
        bands = "".join(
            f"<tr><td>{b['f_bounds_hz'][0]:.2f}–{b['f_bounds_hz'][1]:.2f}</td>"
            f'<td style="color:{STATE_COLOR[b["state"]]}">{STATE_LABEL[b["state"]]}</td>'
            f"<td>{escape('; '.join(REASONS[r] for r in b['reasons']))}</td></tr>"
            for b in record["bands"]
        )
        blocks.append(
            f'<section class="record" data-record="{record["id"]}"><h2>{record["id"]} · offset {record["offset_m"]:g} m</h2>'
            f"<p><b>NO EVALUABLE</b> · adquisición pendiente · modo APPARENT · sin bandas validadas.</p>"
            + picture(f"{record['id']}.png", f"Registro, espectros y dispersión {record['id']}")
            + "<details><summary>Ver bandas y motivos</summary><table><thead><tr><th>Centros de bins (Hz)</th>"
            "<th>Estado diagnóstico</th><th>Motivos</th></tr></thead><tbody>"
            + bands
            + "</tbody></table></details></section>"
        )
    missing = "".join(f"<li>{escape(text)}</li>" for text in MISSING)
    return (
        """<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Oysand · Dosier MASW</title><style>
body{font:16px/1.6 system-ui,sans-serif;background:#edf2f7;color:#172337;margin:0}
main{max-width:1250px;margin:auto;padding:30px}header,section{background:white;padding:25px;margin:20px 0;border-radius:12px}
h1{font-size:34px;margin:0}h2{color:#0369a1}img{width:100%;height:auto}table{border-collapse:collapse;width:100%;font-size:14px}
td,th{text-align:left;border-bottom:1px solid #dbe3ed;padding:9px}summary{cursor:pointer;font-weight:600}select,button{padding:10px;font:inherit}
.status{display:inline-block;padding:5px 14px;border-radius:20px;background:#e2e8f0;font-weight:bold}.note{border-left:4px solid #b77900;padding-left:15px}
@media print{body{background:white}main{padding:0}section{break-inside:avoid}button,select,label{display:none}}
</style><main><header><h1>Oysand / P1 · Dosier MASW</h1><p>4 registros · 96 trazas · offsets 10, 15, 20 y 30 m</p>
<span class="status">NO EVALUABLE · evidencia INCOMPLETE</span>
<p>Integridad de muestras comprobada; calidad integral de adquisición, bandas validadas y suficiencia del objetivo pendientes.</p>
<p class="note">Los faltantes no demuestran mala adquisición. La coherencia no es energía modal ni confirma el modo fundamental.
Este dosier conserva originales y no habilita aceptación de campo ni Vs30.</p><button onclick="window.print()">Imprimir</button></header>
"""
        + "<section><h2>Síntesis del estudio</h2>"
        + picture("summary.png", "Síntesis y acciones")
        + "</section>"
        + "<section><h2>Comparación entre offsets</h2>"
        + picture("comparison.png", "Curvas y matriz de soporte")
        + "<p>Gris: evidencia pendiente. Ámbar: revisión por muestreo/borde de rejilla. El trazo fuerte solo identifica "
        "candidatos interiores a rejilla y Nyquist regular; no demuestra ausencia de alias. Diferencias en m/s, sin intervalos "
        "calibrados; no se unen curvas ni se atribuye una causa.</p></section>"
        + "<section><h2>Geometría y bandas</h2>"
        + picture("geometry.png", "Esquema relativo y bandas diagnósticas")
        + "</section>"
        + '<label for="record">Mostrar registro: </label><select id="record"><option value="all">Todos</option>'
        + "".join(f"<option>{r['id']}</option>" for r in report["records"])
        + "</select>"
        + "".join(blocks)
        + "<section><h2>Evidencias pendientes y siguiente adquisición</h2><ul>"
        + missing
        + "</ul>"
        + "<p>Verificar canal trigger, respuesta/ADC y geometría. Adquirir ventanas de ruido independiente y réplicas comparables; "
        "definir objetivo y plan de posiciones antes de cuantificar cobertura. Revisar bandas/modos y sensibilidad antes de invertir.</p>"
        + "<p>Ventana Hann de registro completo, media retirada, sin filtro adicional ni padding. Análisis exploratorio 5–70 Hz, "
        "60–400 m/s, paso 1 m/s; sensibilidad rectangular y sin canal 1. No se elige la variante que produzca mejor calificación.</p>"
        + f"<p>Digest científico: <code>{report['scientific_digest']}</code><br>Generado: {escape(report['generated_at_utc'])}</p></section>"
        + """</main><script>document.getElementById('record').addEventListener('change',e=>{
document.querySelectorAll('.record').forEach(s=>s.hidden=e.target.value!=='all'&&s.dataset.record!==e.target.value);});</script></html>"""
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/masw_quality")
    args = parser.parse_args()
    output = args.output.resolve()
    records, arrays, inputs = load_records()
    comparisons = compare_records(records, arrays)
    source_paths = [
        Path(__file__),
        ROOT / "docs/requirements_masw_dossier.md",
        ROOT / "examples/field/download_manifest.json",
        *sorted((ROOT / "geoqc").rglob("*.py")),
    ]
    code = {p.relative_to(ROOT).as_posix(): sha256(p) for p in source_paths}
    report = {
        "schema_version": "masw-dossier-1.0",
        "specification_version": "1.4",
        "document_revision": "MASW-R1",
        "site": "Oysand",
        "profile": "P1",
        "scope": "FIELD_DIAGNOSTIC_EXERCISE_ONLY",
        "records": records,
        "comparisons": comparisons,
        "protocol": PROTOCOL,
        "study": {
            "records": 4,
            "traces": 96,
            "sites": 1,
            "profiles": 1,
            "overall_grade": "NO_EVALUABLE",
            "evidence_status": "INCOMPLETE",
            "planned_position_coverage_percent": None,
            "target_band_coverage_percent": None,
            "eligible_for_acceptance": False,
        },
        "input_hashes": inputs,
        "code_hashes": code,
        "config_hash": canonical_hash(PROTOCOL),
        "code_hash": canonical_hash(code),
        "seed": None,
        "randomness": "NONE",
        "platform": platform.platform(),
        "versions": {
            "python": platform.python_version(),
            **{name: importlib.metadata.version(name) for name in ("numpy", "scipy", "matplotlib", "pydantic")},
        },
    }
    report["scientific_digest"] = canonical_hash(report)
    report["generated_at_utc"] = datetime.now(UTC).isoformat()
    output.mkdir(parents=True, exist_ok=True)
    with PdfPages(output / "dossier.pdf") as pdf:
        for name, fig in [
            ("summary", summary_figure(records, comparisons)),
            ("comparison", comparison_figure(records, arrays, comparisons)),
            ("geometry", geometry_figure(records)),
        ]:
            fig.savefig(output / f"{name}.png", dpi=140)
            pdf.savefig(fig)
            plt.close(fig)
        for record in records:
            fig = record_figure(record, arrays[record["id"]])
            fig.savefig(output / f"{record['id']}.png", dpi=140)
            pdf.savefig(fig)
            plt.close(fig)
            np.savez_compressed(output / f"{record['id']}_spectra.npz", **arrays[record["id"]])
    write_csv(
        output / "points.csv", [dict(record=r["id"], offset_m=r["offset_m"], **p) for r in records for p in r["points"]]
    )
    write_csv(output / "bands.csv", [dict(record=r["id"], **b) for r in records for b in r["bands"]])
    write_csv(output / "traces.csv", [dict(record=r["id"], **t) for r in records for t in r["traces"]])
    write_csv(output / "comparisons.csv", comparisons)
    # Revalidación tras análisis: no hubo cambios en los insumos durante el cálculo.
    verify_inputs(ROOT, ROOT / "examples/field/download_manifest.json", [ROOT / key for key in inputs])
    (output / "dossier.html").write_text(render_html(report, output), encoding="utf-8")
    report["artifact_hashes"] = {
        p.name: sha256(p)
        for p in sorted(output.iterdir())
        if p.is_file() and p.suffix in (".png", ".pdf", ".html", ".csv", ".npz")
    }
    (output / "dossier.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"output": str(output), "study": report["study"], "comparisons": comparisons}, ensure_ascii=False, indent=2
        )
    )


if __name__ == "__main__":
    main()
