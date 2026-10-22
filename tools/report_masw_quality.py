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
from pathlib import Path
from textwrap import fill

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.colors import ListedColormap  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from geoqc.core.evidence import canonical_hash  # noqa: E402
from geoqc.masw.diagnostic_quality import UsabilityPolicy  # noqa: E402
from geoqc.masw.dossier_analysis import analyze_observed_record  # noqa: E402
from geoqc.masw.dossier_analysis import band_rows as band_rows  # noqa: E402
from geoqc.masw.dossier_analysis import classify_support as classify_support  # noqa: E402
from geoqc.masw.dossier_analysis import compare_records as compare_records  # noqa: E402
from geoqc.masw.dossier_analysis import usability_bands as usability_bands  # noqa: E402

USABILITY_POLICY = UsabilityPolicy.model_validate_json(
    (ROOT / "configs/masw_usability_v1.json").read_text(encoding="utf-8")
)

PROTOCOL = {
    "id": "OYSAND_MASW_DOSSIER_V2_DRAFT",
    "frequency_min_hz": 5.0,
    "frequency_max_hz": 70.0,
    "velocity_min_ms": 60.0,
    "velocity_max_ms": 400.0,
    "velocity_step_ms": 1.0,
    "slope_scale_ms_per_hz": 30.0,
    "penalty": 0.02,
    "window": "HANN_FULL_RECORD_DC_REMOVED",
    "sensitivity": ["RECTANGULAR_FULL_RECORD", "DROP_CHANNEL_1_PRESERVE_COORDINATES", "UNPENALIZED_PEAK"],
    "usability_policy": USABILITY_POLICY.model_dump(mode="json"),
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
USE_COLOR = {"UTILIZABLE": "#16803c", "REVISAR": "#b77900", "NO_UTILIZABLE": "#b91c1c", "NO_EVALUABLE": "#64748b"}
USE_LABEL = {
    "UTILIZABLE": "Utilizable*",
    "REVISAR": "Revisar",
    "NO_UTILIZABLE": "Sin soporte útil",
    "NO_EVALUABLE": "No evaluable",
}
USE_REASON = {
    "LOW_COHERENCE": "Coherencia de la cresta baja",
    "LOW_CONTRAST": "Contraste cresta–fondo bajo (no SNR)",
    "COMPETING_PEAK": "Otro máximo espacial compite con la cresta",
    "PROCESSING_SENSITIVE": "Velocidad sensible a las variantes de procesamiento",
    "NO_SPECTRAL_SUPPORT": "Menos de dos fases con soporte de amplitud",
    "KERNEL_UNSUPPORTED": "Soporte irregular/incompleto: control de kernel no aplicable",
    "NYQUIST_LIMIT": "Cresta fuera/en el límite espacial de Nyquist",
    "LOBE_AT_NYQUIST": "Lóbulo principal alcanza el límite de Nyquist",
    "DIRECTION_UNRESOLVED": "Lóbulo principal alcanza q=0: dirección no resuelta",
    "VARIANTS_MISSING": "Falta soporte en una variante",
    "METRIC_MISSING": "Atributo no evaluable",
    "GRID_EDGE": "Cresta en borde de rejilla de velocidad",
    "INTERNAL_CHECKS_PASSED": "Controles internos satisfechos bajo política diagnóstica DRAFT",
}


def usable_ranges(record):
    return (
        "; ".join(
            f"{b['f_bounds_hz'][0]:.2f}–{b['f_bounds_hz'][1]:.2f}"
            for b in record["usability_bands"]
            if b["state"] == "UTILIZABLE"
        )
        or "Ninguno"
    )


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


def analyze(data, dt, x, record_id, protocol):
    """Compatibility wrapper preserving the historical exploratory report."""
    return analyze_observed_record(data, dt, x, record_id, protocol, missing_evidence=MISSING)


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
        "GeoQC · utilidad de cresta aparente / política DRAFT | objetivo Vs30 pendiente | originales conservados",
        fontsize=9,
        color="#475569",
    )


def summary_figure(records, comparisons):
    fig = plt.figure(figsize=(11.7, 8.3), facecolor="white")
    fig.text(0.06, 0.91, "OYSAND / P1", fontsize=26, weight="bold", color="#0f172a")
    fig.text(0.06, 0.86, "Dosier de calidad diagnóstica MASW", fontsize=19)
    fig.text(0.06, 0.78, "4 registros · 96 trazas · 1 sitio / perfil", fontsize=17, color="#0369a1")
    fig.text(0.06, 0.71, "Dispersión: EVALUACIÓN POR BANDAS     Objetivo Vs30: PENDIENTE", fontsize=13, color="#0369a1")
    fig.text(
        0.06,
        0.65,
        "Integridad de muestras: PASS en los cuatro registros. No se encontraron canales constantes.",
        fontsize=11,
    )
    table = [
        [
            r["id"],
            f"{r['offset_m']:g}",
            r["usability_counts"]["UTILIZABLE"],
            r["usability_counts"]["REVISAR"],
            "Ver bandas",
        ]
        for r in records
    ]
    ax = fig.add_axes((0.06, 0.39, 0.88, 0.23))
    ax.axis("off")
    t = ax.table(
        cellText=table,
        colLabels=["Registro", "Offset (m)", "Utilizables*", "Revisar", "Conclusión"],
        loc="center",
        cellLoc="center",
    )
    t.auto_set_font_size(False)
    t.set_fontsize(11)
    t.scale(1, 1.7)
    fig.text(
        0.06,
        0.36,
        "* Bins que pasan controles internos DRAFT para cresta aparente. No son porcentajes de calidad.",
        fontsize=10,
    )
    notes = [
        "Plan de posiciones y banda objetivo: desconocidos. Cobertura porcentual del estudio: no calculable.",
        "Contraste, picos competidores y sensibilidad se estiman de los datos; no son SNR ni sigma.",
        "Los offsets aportan observaciones distintas; no equivalen a cuatro sitios ni a réplicas idénticas.",
        "Revisar motivos por banda. Metadatos instrumentales pendientes no anulan los controles internos.",
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
        mask = a["usable_mask"]
        (line,) = axes[0, 0].plot(f, a["ridge_ms"], alpha=0.25)
        axes[0, 0].plot(
            f,
            np.where(mask, a["ridge_ms"], np.nan),
            color=line.get_color(),
            label=f"{record['id']} · {record['offset_m']:g} m",
        )
        axes[1, 0].plot(f, np.where(mask, abs(a["drop_ridge_ms"] - a["ridge_ms"]), np.nan), label=record["id"])
    axes[0, 0].set(
        title="Trazo fuerte = utilizable bajo controles internos DRAFT",
        xlabel="Frecuencia (Hz)",
        ylabel="c aparente (m/s)",
    )
    axes[0, 0].legend(fontsize=9)
    axes[1, 0].set(
        title="Sensibilidad al excluir canal 1 · no es incertidumbre", xlabel="Frecuencia (Hz)", ylabel="|Δc| (m/s)"
    )
    state_value = {"UTILIZABLE": 0, "REVISAR": 1, "NO_UTILIZABLE": 2, "NO_EVALUABLE": 3}
    matrix = [[state_value[p["usability"]["grade"]] for p in r["points"]] for r in records]
    f = arrays[records[0]["id"]]["frequencies_hz"]
    axes[0, 1].imshow(
        matrix,
        aspect="auto",
        interpolation="nearest",
        extent=[f[0], f[-1], len(records) - 0.5, -0.5],
        cmap=ListedColormap([USE_COLOR[s] for s in state_value]),
        vmin=0,
        vmax=3,
    )
    axes[0, 1].set(
        yticks=range(len(records)),
        yticklabels=[r["id"] for r in records],
        xlabel="Frecuencia (Hz)",
        title="Verde: utilizable* · ámbar: revisar · gris: no evaluable",
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
        "Utilidad diagnóstica por bandas · modo APPARENT · objetivo Vs30 pendiente",
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
            "Candidato geométrico, no calificación"
            if b["state"] == "PENDING"
            else "Revisar muestreo espacial / rejilla",
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


def usability_figure(record):
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    fig.subplots_adjust(left=0.08, right=0.96, top=0.87, bottom=0.23, hspace=0.45, wspace=0.25)
    f = np.array([p["frequency_hz"] for p in record["points"]])
    quality = [p["usability"] for p in record["points"]]
    policy = record["usability_policy"]
    for ax, key, threshold, title in (
        (axes[0, 0], "coherence", policy["coherence_min"], "Coherencia en cresta · mayor es mejor"),
        (axes[0, 1], "contrast", policy["contrast_min"], "Contraste cresta–fondo · no es SNR"),
        (axes[1, 0], "competitor_ratio", policy["competitor_ratio_max"], "Competidor / cresta · menor es mejor"),
        (
            axes[1, 1],
            "sensitivity_rel",
            policy["sensitivity_max_rel"],
            "Máximo cambio relativo entre variantes · no es sigma",
        ),
    ):
        values = [q[key] if q[key] is not None else np.nan for q in quality]
        ax.plot(f, values, color="#0369a1", lw=1)
        ax.axhline(threshold, color="#b77900", ls="--", label=f"Corte DRAFT {threshold:g}")
        for band in record["usability_bands"]:
            if band["state"] == "UTILIZABLE":
                lo, hi = band["f_bounds_hz"]
                ax.axvspan(lo, hi, color="#16803c", alpha=0.12)
        ax.set(title=title, xlabel="Frecuencia (Hz)", ylabel="Adimensional")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.15)
    fig.suptitle(f"{record['id']} · controles internos de utilidad de la cresta aparente", fontsize=18)
    fig.text(0.08, 0.15, fill("Tramos utilizables* (Hz): " + usable_ranges(record), 115), fontsize=10)
    fig.text(
        0.08,
        0.075,
        "* Política diagnóstica experimental: no identifica modo/origen ni acredita Vs30.\n"
        "Variantes: rectangular, sin canal 1 y máximo sin suavizado DP. Fondo de I(q), no ruido físico.",
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
            f'<td style="color:{USE_COLOR[b["state"]]}">{USE_LABEL[b["state"]]}</td>'
            f"<td>{escape('; '.join(USE_REASON[r] for r in b['reasons']))}</td></tr>"
            for b in record["usability_bands"]
        )
        measurements = "".join(
            f"<tr><td>{p['frequency_hz']:.2f}</td><td>{fmt(p['usability']['coherence'])}</td>"
            f"<td>{fmt(p['usability']['contrast'])}</td><td>{fmt(p['usability']['competitor_ratio'])}</td>"
            f"<td>{fmt(p['usability']['sensitivity_rel'])}</td><td>{USE_LABEL[p['usability']['grade']]}</td></tr>"
            for p in record["points"]
        )
        blocks.append(
            f'<section class="record" data-record="{record["id"]}"><h2>{record["id"]} · offset {record["offset_m"]:g} m</h2>'
            f"<p><b>Evaluación parcial: utilidad de dispersión por bandas</b> · modo APPARENT · objetivo Vs30 pendiente.</p>"
            f"<p>Tramos utilizables* (Hz): <strong>{escape(usable_ranges(record))}</strong></p>"
            + picture(f"{record['id']}.png", f"Registro, espectros y dispersión {record['id']}")
            + picture(f"{record['id']}_usability.png", f"Controles internos {record['id']}")
            + "<details><summary>Ver bandas y motivos</summary><table><thead><tr><th>Centros de bins (Hz)</th>"
            "<th>Estado diagnóstico</th><th>Motivos</th></tr></thead><tbody>"
            + bands
            + "</tbody></table></details><details><summary>Métricas por frecuencia (adimensionales)</summary>"
            "<table><thead><tr><th>Hz</th><th>Coherencia</th><th>Contraste</th><th>Competidor / cresta</th>"
            "<th>Sensibilidad relativa</th><th>Utilidad*</th></tr></thead><tbody>"
            + measurements
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
<span class="status">EVALUACIÓN PARCIAL · utilidad por bandas</span>
<p>Podemos calificar la extracción y estabilidad de crestas aparentes desde los registros.
La suficiencia del objetivo Vs30 permanece pendiente (evidencia INCOMPLETE).</p>
<p class="note">* Utilizable: satisface controles internos bajo una política diagnóstica experimental, sin tasas de error de campo calibradas.
No demuestra identidad modal, origen de la onda ni precisión de Vs30. Contraste no es SNR y sensibilidad no es sigma.
Los faltantes instrumentales se conservan sin anular esta evaluación limitada.</p><button onclick="window.print()">Imprimir</button></header>
"""
        + "<section><h2>Síntesis del estudio</h2>"
        + picture("summary.png", "Síntesis y acciones")
        + "</section>"
        + "<section><h2>Comparación entre offsets</h2>"
        + picture("comparison.png", "Curvas y matriz de soporte")
        + "<p>Verde: utilizable*. Ámbar: revisar. Rojo: sin soporte útil. Gris: controles no evaluables. "
        "El trazo fuerte muestra utilidad interna; no identifica un modo físico. La tabla compara pares en soporte geométrico común, "
        "conservado para comparar con la versión anterior: diferencias en m/s, sin intervalos calibrados ni causa atribuida.</p></section>"
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
        + "<p>Política DRAFT: I ≥0.60; contraste ≥0.25; competidor/cresta ≤0.80; cambio relativo entre variantes ≤0.05. "
        "El buscador de competidores cubre q firmado completo de Nyquist y excluye el lóbulo principal del kernel uniforme. "
        "Los puntos aislados se muestran como tales; no se rellenan huecos ni se promedian colores.</p>"
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
        ROOT / "docs/adr/0003-masw-diagnostic-usability.md",
        ROOT / "configs/masw_usability_v1.json",
        ROOT / "examples/field/download_manifest.json",
        *sorted((ROOT / "geoqc").rglob("*.py")),
    ]
    code = {p.relative_to(ROOT).as_posix(): sha256(p) for p in source_paths}
    report = {
        "schema_version": "masw-dossier-2.0",
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
            "overall_grade": "EVALUACION_PARCIAL",
            "objective_grade": "NO_EVALUABLE",
            "objective_status": "NOT_DEMONSTRATED",
            "records_with_usable_segments": sum(r["usability_counts"]["UTILIZABLE"] > 0 for r in records),
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
            fig = usability_figure(record)
            fig.savefig(output / f"{record['id']}_usability.png", dpi=140)
            pdf.savefig(fig)
            plt.close(fig)
    write_csv(
        output / "points.csv", [dict(record=r["id"], offset_m=r["offset_m"], **p) for r in records for p in r["points"]]
    )
    write_csv(output / "bands.csv", [dict(record=r["id"], **b) for r in records for b in r["bands"]])
    write_csv(output / "usability.csv", [dict(record=r["id"], **p["usability"]) for r in records for p in r["points"]])
    write_csv(
        output / "usability_bands.csv", [dict(record=r["id"], **b) for r in records for b in r["usability_bands"]]
    )
    write_csv(output / "traces.csv", [dict(record=r["id"], **t) for r in records for t in r["traces"]])
    write_csv(output / "comparisons.csv", comparisons)
    # Revalidación tras análisis: no hubo cambios en los insumos durante el cálculo.
    verify_inputs(ROOT, ROOT / "examples/field/download_manifest.json", [ROOT / key for key in inputs])
    if code != {p.relative_to(ROOT).as_posix(): sha256(p) for p in source_paths}:
        raise ValueError("Código/configuración cambiaron durante la generación")
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
