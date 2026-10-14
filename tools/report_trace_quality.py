"""Genera un dosier por canal: campo preservado, ejemplo E2 y controles sintéticos."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import sys
from datetime import UTC, datetime
from html import escape
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoqc.core.config import load_config  # noqa: E402
from geoqc.core.models import Acquisition, Geometry, Shot  # noqa: E402
from geoqc.io.binary import parse_seg2  # noqa: E402
from geoqc.io.readers import read_shot  # noqa: E402
from geoqc.qc import common_qc  # noqa: E402
from geoqc.qc.contracts import QCProtocol, SimilarityProtocol, Window  # noqa: E402
from geoqc.qc.noise import (  # noqa: E402
    NoiseProtocol,
    digital_integrity,
    low_frequency_coherence,
    noise_diagnostics,
    samples_in_window,
)
from geoqc.qc.quality import (  # noqa: E402
    COLORS,
    DISPLAY_COLORS,
    TraceQualityPolicy,
    aggregate_quality,
    assess_quality,
    trace_quality,
)
from geoqc.qc.similarity import local_similarity  # noqa: E402

POLICY = TraceQualityPolicy()
METHOD = (
    "Por traza: buena si hay integridad completa, SNR ≥12 dB, clipping ≤0.1 % y ninguna alerta; "
    "mala si es cero/constante, sin soporte válido, SNR <6 dB o clipping ≥1 %; regular en los demás casos, "
    "con revisión pendiente. Gris/no evaluable si solo falta evidencia. SNR = 10 log10((Ptotal − Pruido)/Pruido), con ventanas independientes "
    "y estacionariedad verificada. Entre 6 y <12 dB o clipping >0.1 % y <1 %: regular. "
    "Umbrales de traza locales provisionales, editables en quality_policy del protocolo QC."
)
AGGREGATION = (
    "Por registro y conjunto: buenas / todas las trazas. Buena ≥90 %; regular ≥75 % y <90 %; mala <75 %. "
    "Los faltantes generan un intervalo posible: si cruza un corte, el resultado es NO EVALUABLE. "
    "Se decide antes de redondear. Las regulares no cuentan como buenas. Los conjuntos suman trazas, "
    "sin promediar porcentajes de registros. Cada traza de cada disparo cuenta una vez; "
    "no representa un sensor físico independiente."
)
LIMITATION = (
    "Diagnóstico sin certificación. Chevremont incluye SNR condicional de ventana (marcada con *), "
    "medida sin necesitar escala ADC: el supuesto pendiente es la transferencia del ruido a la señal. "
    "No equivale a SNR validada del primer arribo. Clipping conserva su incertidumbre por rails/stack. "
    "En Oysand no se inventa pretrigger ni se usa coda como ruido. Los faltantes no demuestran mala adquisición."
)


SIMILARITY_METHOD = (
    "Chevremont: correlación normalizada de la llegada [0,0.18) s con hasta cuatro vecinos a ≤2.1 m. "
    "Se retira la media y se permite desfase ≤distancia/100 m/s, con tope de 20 ms, sin filtrar ni "
    "alterar amplitudes originales. Anomalía local roja si mediana |ρ|<0.5, al menos 75 % de vecinos "
    "tienen |ρ|<0.5 y existe una mayoría de al menos tres vecinos coherentes entre sí (cada par ≥0.8). "
    "Una correlación ≥0.8 indica forma compatible, pero no sustituye SNR o clipping ni prueba "
    "consistencia física. La línea base [-0.25,-0.05) s aporta un contraste de energía sin SNR validada. "
    "Oysand no usa este protocolo TRS: la dispersión MASW requiere su propia ventana y comparabilidad."
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def synthetic_shot(good: int) -> tuple[Shot, QCProtocol, list[str]]:
    """Fallas conocidas, aplicadas a muestras; las etiquetas no entran al clasificador."""
    n, samples, dt = 20, 1000, 0.001
    time = np.arange(samples) * dt - 0.25
    rng = np.random.default_rng(20261010)
    data = rng.normal(0, 0.005, (n, samples))
    signal = (time >= 0) & (time < 0.5)
    expected = ["BUENA"] * good + ["REGULAR"] + ["MALA"] * (n - good - 1)
    for j, grade in enumerate(expected):
        amplitude = 0.1 if grade == "BUENA" else 0.022 if grade == "REGULAR" else 0.006
        data[j, signal] += amplitude * np.sin(2 * np.pi * 40 * time[signal] + j / 10)
    data[-1] = 0  # Canal muerto en todos los escenarios.
    if good < 18:
        data[-2, signal] = np.sign(np.sin(2 * np.pi * 40 * time[signal]))  # Rails conocidos.
    shot = Shot(
        id=f"control-{good}-de-20",
        data=data,
        valid_mask=np.ones_like(data, dtype=bool),
        mask_reasons=("",) * n,
        dt_s=(dt,) * n,
        t0_s=(-0.25,) * n,
        geometry=Geometry(
            xr=np.arange(n) * 2.0 + 2,
            yr=np.zeros(n),
            zr=np.zeros(n),
            xs=0,
            ys=0,
            zs=0,
            uncertainty_m=(0.01,) * n,
            crs="local-SI",
            provenance=("Control sintético con semilla 20261010",),
        ),
        acquisition=Acquisition(
            technique="MASW",
            wave="RAYLEIGH",
            component="Z",
            source_type="synthetic",
            receiver_ids=tuple(f"r{j + 1}" for j in range(n)),
            adc_rails=(-1, 1),
            stack_kind="RAW",
        ),
        input_hashes=(hashlib.sha256(data.tobytes()).hexdigest(),),
        headers_json='{"synthetic":true}',
    )
    protocol = QCProtocol(
        analysis=Window(start_s=-0.25, end_s=0.75),
        noise=Window(start_s=-0.25, end_s=-0.05),
        signal=Window(start_s=0, end_s=0.5),
        noise_independent=True,
        noise_stationarity="VERIFIED",
        stationarity_ref="Ruido iid conocido: semilla 20261010, sigma 0.005",
        rail_scale_to_data=1,
        provenance="tools/report_trace_quality.py; controles sintéticos sin calibración de campo",
    )
    return shot, protocol, expected


def qc_record(shot: Shot, protocol: QCProtocol, *, site: str, kind: str, source: str) -> dict:
    result = common_qc(shot, protocol, load_config(ROOT / "configs/vs30_sitio.yaml"))
    return {
        "id": shot.id,
        "site": site,
        "kind": kind,
        "source": source,
        "traces": result["traces"],
        "quality": result["data_quality"],
        "assessment": result["data_assessment"],
        "protocol": result["protocol"],
        "input_hashes": shot.input_hashes,
        "data": shot.data,
        "dt": shot.dt_s,
        "t0": shot.t0_s,
    }


def field_records() -> tuple[list[dict], dict[str, str]]:
    manifest_path = ROOT / "examples/field/download_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    hashes = {"examples/field/download_manifest.json": sha256(manifest_path)}
    similarity_path = ROOT / "examples/field/similarity_protocol.json"
    similarity_protocol = SimilarityProtocol.model_validate_json(similarity_path.read_text(encoding="utf-8"))
    hashes[similarity_path.relative_to(ROOT).as_posix()] = sha256(similarity_path)
    noise_path = ROOT / "examples/field/noise_protocol.json"
    noise_protocol = NoiseProtocol.model_validate_json(noise_path.read_text(encoding="utf-8"))
    hashes[noise_path.relative_to(ROOT).as_posix()] = sha256(noise_path)
    geometry_lines = (
        (ROOT / "examples/field/raw/chevremont/example/Chevremont/chevremont.geometry")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    coordinates = np.loadtxt(geometry_lines[geometry_lines.index("RECEIVERS") + 1 :])
    records = []
    for entry in manifest["files"]:
        path = ROOT / entry["path"]
        digest = sha256(path)
        if digest != entry["sha256"]:
            raise ValueError(f"Original modificado: {entry['path']}")
        hashes[entry["path"]] = digest
        if path.suffix.lower() == ".dat":
            data = np.loadtxt(path, skiprows=5).T
            import re

            header = path.read_text(encoding="utf-8").splitlines()[1]
            match = re.search(r"Measurement frequency \(Hz\): ([\d.]+)", header)
            if match is None:
                raise ValueError(f"Frecuencia de muestreo ausente: {path}")
            dt = (1 / float(match[1]),) * data.shape[0]
            t0 = (0.0,) * data.shape[0]
            site = "Oysand"
        elif path.suffix.lower() == ".sg2":
            decoded = parse_seg2(path.read_bytes())
            if any(t is None for t in decoded.t0_s):
                raise ValueError(f"DELAY ausente: {path}")
            data = np.stack(decoded.traces)
            dt, t0 = decoded.dt_s, decoded.t0_s
            site = "Chevremont"
        else:
            continue
        similarities = None
        if site == "Chevremont":
            if [int(h["CHANNEL_NUMBER"]) for h in decoded.headers["trace_headers"]] != list(range(1, len(data) + 1)):
                raise ValueError("Orden de canales incompatible con geometría local")
            similarities = local_similarity(
                data, np.isfinite(data), tuple(dt), tuple(t0), coordinates, similarity_protocol
            )
        traces = []
        for j, values in enumerate(data):
            valid = values[np.isfinite(values)]
            stats = {
                "state": "VALID" if valid.size >= 2 else "MISSING",
                "valid_samples": int(valid.size),
                "dead": bool(valid.size and np.all(valid == 0)),
                "constant": bool(valid.size and np.ptp(valid) == 0),
                "rms_ac": float(np.std(valid)) if valid.size else None,
            }
            trace = {
                "channel_1based": j + 1,
                "receiver_id": f"canal-{j + 1}",
                "valid_fraction": float(np.isfinite(values).mean()),
                "statistics": stats,
                "snr": {
                    "state": "MISSING",
                    "value": None,
                    "reason": "Ventanas independientes y estacionariedad sin verificar",
                },
                "clip": {"state": "MISSING", "value": None, "reason": "Rails/escala ADC desconocidos"},
            }
            if similarities is not None:
                trace["similarity"] = similarities[j]
                trace["noise_diagnostics"] = noise_diagnostics(
                    values, np.isfinite(values), dt[j], t0[j], noise_protocol
                )
                trace["snr"] = trace["noise_diagnostics"]["snr"]
                neighbor = j - 1 if j else 1
                a = samples_in_window(values, np.isfinite(values), dt[j], t0[j], noise_protocol.noise)
                b = samples_in_window(
                    data[neighbor], np.isfinite(data[neighbor]), dt[neighbor], t0[neighbor], noise_protocol.noise
                )
                if a is not None and b is not None:
                    trace["noise_diagnostics"]["low_coherence"] = low_frequency_coherence(
                        a, b, dt[j], noise_protocol.low_band_hz
                    )
            trace["integrity"] = digital_integrity(values, dt[j])
            trace["quality"] = trace_quality(trace, POLICY)
            traces.append(trace)
        records.append(
            {
                "id": path.stem,
                "site": site,
                "kind": "CAMPO",
                "source": entry["path"],
                "traces": traces,
                "quality": aggregate_quality(t["quality"]["grade"] for t in traces),
                "assessment": assess_quality(t["quality"] for t in traces),
                "notes": ["Clipping no certificado: rails/escala desconocidos y/o impactos apilados."]
                + (
                    ["Papel del canal 1 como trigger pendiente. Sin pretrigger documentado: no se estima SNR."]
                    if site == "Oysand"
                    else [
                        "SNR * condicional: ruido [-0.75,-0.05) s, señal [0,0.18) s. No es SNR validada del primer arribo.",
                        "LF 1–15 Hz: duración insuficiente para banda completa y coherencia fiable; obtener toma de ruido más larga.",
                        "Acción: registrar rails, escalas y golpes individuales; validar reloj y referencia de ruido.",
                    ]
                ),
                "input_hashes": [digest],
                "data": data,
                "dt": dt,
                "t0": t0,
                "protocol": {
                    "analysis": "Registro completo: integridad; SNR y clipping pendientes",
                    "similarity": similarity_protocol.model_dump(mode="json") if similarities else None,
                    "noise_diagnostics": noise_protocol.model_dump(mode="json") if similarities else None,
                },
            }
        )
    return records, hashes


def trace_figure(record: dict):
    data, traces = record["data"], record["traces"]
    has_similarity = any("similarity" in t for t in traces)
    fig, (ax, metrics) = plt.subplots(
        1, 2, figsize=(14, max(6, len(traces) * 0.18)), gridspec_kw={"width_ratios": [4, 1]}, constrained_layout=True
    )
    for j, trace in enumerate(traces):
        values = data[j].copy()
        finite = np.isfinite(values)
        centered = values - np.mean(values[finite]) if finite.any() else values
        peak = np.max(abs(centered[finite])) if finite.any() else 0
        normalized = centered / peak if peak else centered
        time = record["t0"][j] + np.arange(values.size) * record["dt"][j]
        color = trace["quality"].get("assessment_color", trace["quality"]["color"])
        ax.plot(time, j + 1 + 0.4 * normalized, color=color, lw=0.6)
        ax.text(time[-1], j + 1, f"  {j + 1}", color=color, va="center", fontsize=6)
        value = trace.get("similarity", {}).get("median_abs_rho") if has_similarity else trace["snr"].get("value")
        if value is not None:
            metrics.scatter(value, j + 1, color=color, s=14)
    ax.set(
        xlabel="Tiempo del archivo (s)",
        ylabel="Canal (1-based)",
        ylim=(len(traces) + 1, 0),
        yticks=np.arange(1, len(traces) + 1),
    )
    ax.tick_params(axis="y", labelsize=7)
    ax.grid(alpha=0.12)
    ax.legend(
        handles=[Line2D([0], [0], color=c, label=g.replace("_", " ").capitalize()) for g, c in DISPLAY_COLORS.items()],
        loc="upper right",
        ncol=3,
        fontsize=8,
    )
    low = record["protocol"]["similarity"]["bad_below_rho"] if has_similarity else POLICY.snr_bad_below_db
    high = record["protocol"]["similarity"]["warn_below_rho"] if has_similarity else POLICY.snr_good_min_db
    metrics.axvline(low, color=COLORS["MALA"], ls="--", lw=1)
    metrics.axvline(high, color=COLORS["BUENA"], ls="--", lw=1)
    metrics.set(
        xlabel="Similitud local |ρ|" if has_similarity else "SNR neta (dB)", ylim=(len(traces) + 1, 0), yticks=[]
    )
    if has_similarity:
        metrics.set_xlim(0, 1)
    elif all(t["snr"].get("value") is None for t in traces):
        metrics.text(0.5, 0.5, "SNR no evaluable\nFalta evidencia", ha="center", transform=metrics.transAxes)
    quality = record["quality"]
    fig.suptitle(
        f"{record['site']} · {record['id']}\n{record['assessment']['grade'].replace('_', ' ')} · "
        f"{quality['counts']['BUENA']} buenas demostradas; {quality['counts']['MALA']} malas; "
        f"{record['assessment']['pending_traces']} pendientes\n"
        "Amplitud normalizada por canal para visualizar; evaluación sobre muestras originales",
        fontsize=11,
    )
    return fig


def anomaly_figure(record: dict):
    """Ampliación de anomalías detectadas automáticamente, sin IDs de canal preseleccionados."""
    bad = [t for t in record["traces"] if t.get("similarity", {}).get("grade") == "MALA"]
    fig, axes = plt.subplots(len(bad), 3, figsize=(15, 3.5 * len(bad)), squeeze=False, constrained_layout=True)
    settings = record["protocol"]["similarity"]
    start, end = settings["arrival"]["start_s"], settings["arrival"]["end_s"]
    for row, trace in enumerate(bad):
        j = trace["channel_1based"] - 1
        similarity = trace["similarity"]
        for k, lag, sign, color in [
            (p["neighbor_channel_1based"] - 1, p["lag_s"], np.sign(p["signed_rho"]), "#94a3b8")
            for p in similarity["pairs"]
        ] + [(j, 0.0, 1, COLORS["MALA"])]:
            time = record["t0"][k] + np.arange(record["data"].shape[1]) * record["dt"][k]
            lo = int(np.ceil((start - record["t0"][k]) / record["dt"][k] - 1e-9))
            hi = int(np.ceil((end - record["t0"][k]) / record["dt"][k] - 1e-9))
            values = record["data"][k, lo:hi]
            centered = values - np.mean(values)
            rms = np.std(values)
            axes[row, 0].plot(
                time[lo:hi] + lag,
                sign * centered / max(abs(centered)),
                color=color,
                lw=1,
                label=f"Canal {k + 1}" if k == j else None,
            )
            power = abs(np.fft.rfft(centered * np.hanning(centered.size))) ** 2
            frequencies = np.fft.rfftfreq(centered.size, record["dt"][k])
            axes[row, 1].plot(frequencies, power / power.sum(), color=color, lw=1)
            baseline = settings.get("baseline")
            if baseline:
                mask = (time >= baseline["start_s"]) & (time < baseline["end_s"])
                base = record["data"][k, mask]
                axes[row, 2].plot(time[mask], (base - base.mean()) / rms, color=color, lw=0.8)
        axes[row, 0].set(
            xlim=(start, end),
            xlabel="Tiempo (s); desfase/signo optimizados solo para comparar",
            ylabel="Amplitud normalizada",
            title=f"Canal {j + 1}: |ρ|={similarity['median_abs_rho']:.3f}",
        )
        axes[row, 0].legend(fontsize=8)
        axes[row, 1].set(
            xlim=(0, 200),
            xlabel="Frecuencia (Hz)",
            ylabel="Fracción de potencia por bin",
            title=f"Frecuencia mediana: {similarity['spectral_median_hz']:.1f} Hz",
        )
        relative = similarity["baseline_relative_to_neighbors"]
        axes[row, 2].set(
            xlabel="Tiempo de línea base (s)",
            ylabel="Amplitud / RMS de llegada",
            title="Línea base relativa: " + (f"{relative:.1f}× vecinos" if relative is not None else "no evaluable"),
        )
    fig.suptitle(
        f"{record['site']} · {record['id']} · anomalías de forma\nRojo: canal observado. Gris: vecinos. "
        "La similitud no identifica por sí sola la causa física.",
        fontsize=12,
    )
    return fig


def summary_figure(records: list[dict]):
    fig, ax = plt.subplots(figsize=(13, 8), constrained_layout=True)
    positions = np.arange(len(records))
    left = np.zeros(len(records))
    for grade, color in DISPLAY_COLORS.items():
        widths = np.array(
            [
                100 * sum(t["quality"]["assessment_grade"] == grade for t in r["traces"]) / len(r["traces"])
                for r in records
            ]
        )
        ax.barh(positions, widths, left=left, color=color, label=grade.replace("_", " ").capitalize())
        left += widths
    ax.axvline(75, color="#334155", ls="--", lw=1)
    ax.axvline(90, color="#334155", ls=":", lw=1)
    ax.set(
        yticks=positions,
        yticklabels=[f"{r['site']} · {r['id']}" for r in records],
        xlim=(0, 100),
        xlabel="Porcentaje de trazas por categoría",
        title="Calidad por registro · límites en 75 % y 90 %",
    )
    ax.tick_params(axis="y", labelsize=8)
    ax.invert_yaxis()
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), ncol=3)
    return fig


def pdf_table(
    pdf: PdfPages, title: str, rows: list[list[str]], headers: list[str], notes: list[str] | None = None
) -> None:
    import textwrap

    for start in range(0, len(rows), 24):
        fig, ax = plt.subplots(figsize=(11.7, 8.3))
        ax.axis("off")
        ax.set_title(title, fontsize=12, pad=20)
        if notes:
            ax.text(0, 0.99, "\n".join(textwrap.fill(note, 125) for note in notes), va="top", fontsize=7)
        table = ax.table(
            cellText=rows[start : start + 24],
            colLabels=headers,
            loc="upper center",
            cellLoc="left",
            colWidths=[0.07, 0.1, 0.1, 0.73],
            bbox=[0, 0, 1, 0.80] if notes else None,
        )
        table.auto_set_font_size(False)
        table.set_fontsize(7)
        table.scale(1, 1.5)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)


def badge(grade: str) -> str:
    return f'<strong style="color:{DISPLAY_COLORS[grade]}">{grade.replace("_", " ").capitalize()}</strong>'


def image_html(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f'<img alt="{escape(path.stem)}" src="data:image/png;base64,{encoded}">'


def html_report(report: dict, output: Path) -> str:
    summary = []
    sections = []
    for record in report["records"]:
        q = record["quality"]
        counts = q["counts"]
        assessment = record["assessment"]
        reviews = sum(t["quality"]["assessment_grade"] == "REGULAR" for t in record["traces"])
        not_evaluable = sum(t["quality"]["assessment_grade"] == "NO_EVALUABLE" for t in record["traces"])
        summary.append(
            f'<tr><td><a href="#{escape(record["id"])}">{escape(record["site"])} · '
            f"{escape(record['id'])}</a></td><td>{counts['BUENA']}</td><td>{reviews}</td>"
            f"<td>{counts['MALA']}</td><td>{not_evaluable}</td>"
            f"<td>{assessment['good_percent_bounds'][0]:.2f}–{assessment['good_percent_bounds'][1]:.2f} %</td>"
            f"<td>{badge(assessment['grade'])}</td></tr>"
        )
        rows = []
        for t in record["traces"]:
            clip = t["clip"].get("value")
            similarity = t.get("similarity", {})
            rows.append(
                f'<tr data-grade="{t["quality"]["assessment_grade"]}"><td>{t["channel_1based"]} · '
                f"{escape(t['receiver_id'])}</td><td>{badge(t['quality']['assessment_grade'])}</td>"
                f"<td>{trace_snr_display(t)}</td><td>{'—' if clip is None else f'{100 * clip:.3f} %'}</td>"
                f"<td>{100 * t['valid_fraction']:.2f} %</td>"
                f"<td>{snr_display(similarity.get('median_abs_rho'))}</td>"
                f"<td>{snr_display(similarity.get('neighbor_consensus_rho'))}</td>"
                f"<td>{escape(trace_reasons(t))}</td></tr>"
            )
        sections.append(
            f'<section id="{escape(record["id"])}"><h2>{escape(record["site"])} · '
            f"{escape(record['id'])}</h2><p>{badge(assessment['grade'])} · "
            f"{counts['MALA']} malas detectadas; {assessment['pending_traces']} pendientes · "
            f'{record["kind"]}</p><p class="source">{escape(record["source"])}</p>'
            + "<ul>"
            + "".join(f"<li>{escape(note)}</li>" for note in record.get("notes", []))
            + "</ul>"
            + f"{image_html(output / record['plot'])}"
            + (image_html(output / record["anomaly_plot"]) if record.get("anomaly_plot") else "")
            + (image_html(output / record["noise_plot"]) if record.get("noise_plot") else "")
            + "<details open><summary>Diagnóstico por canal</summary>"
            "<table><thead><tr><th>Canal / ID</th><th>Calidad</th><th>SNR (dB)</th><th>Clipping</th>"
            "<th>Muestras válidas</th><th>|ρ| local</th><th>Consenso vecinos</th><th>Motivos</th></tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table></details></section>"
        )
    groups = "".join(
        f"<li>{escape(g['site'])}: {badge(g['assessment']['grade'])} · "
        f"{g['quality']['counts']['BUENA']} buenas demostradas; {g['assessment']['demonstrated_bad_traces']} malas; "
        f"{g['assessment']['pending_traces']} pendientes de {g['quality']['total_traces']} trazas</li>"
        for g in report["groups"]
    )
    return (
        """<!doctype html><html lang="es"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Dosier de calidad por traza</title>
<style>body{font:15px/1.5 system-ui;background:#f3f6f8;color:#18313e;margin:0}
main{max-width:1250px;margin:auto;padding:28px}section,.panel{background:white;border:1px solid #d6e1e6;
padding:22px;border-radius:10px;margin:20px 0}h1{font-size:34px}h2{font-size:22px}img{width:100%;height:auto}
table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:8px;text-align:left;border-bottom:1px solid #ddd}
th{background:#edf3f5}a{color:#126283}.notice{border-left:4px solid #b77900;padding:12px;background:#fff4d6}
.source{overflow-wrap:anywhere;font-size:12px}button,select{font:inherit;padding:8px}summary{cursor:pointer}
@media print{body{background:white}main{padding:0}.toolbar{display:none}section{break-before:page}
tr,img{break-inside:avoid}details{display:block}h2{break-after:avoid}}
</style><main><h1>Dosier de calidad por traza</h1>
<p>Verde: buena · Amarillo: revisión · Rojo: mala · Gris: no evaluable</p>
<div class="toolbar"><button onclick="window.print()">Imprimir / guardar PDF</button>
<label>Mostrar canales <select id="grade"><option value="">Todos</option><option value="BUENA">Buenos</option>
<option value="REGULAR">Regulares</option><option value="MALA">Malos</option>
<option value="NO_EVALUABLE">No evaluables</option></select></label></div>
"""
        + f'<p>{escape(AGGREGATION)}</p><p class="notice">{escape(LIMITATION)}</p>'
        + (
            '<div class="panel"><h2>Conjuntos</h2><ul>' + groups + "</ul>"
            "<p>Campo, ejemplo E2 y controles sintéticos se reportan por separado.</p></div>"
            '<div class="panel"><h2>Resumen por registro</h2><table><thead><tr><th>Registro</th><th>Buenas</th>'
            "<th>Revisión</th><th>Malas</th><th>No evaluables</th><th>Intervalo % buenas</th><th>Evaluación</th></tr></thead><tbody>"
            + "".join(summary)
            + "</tbody></table>"
            + image_html(output / "summary.png")
            + "<p>Una traza en revisión puede tener evidencia pendiente. "
            "El intervalo conserva todas las trazas en el denominador y permite resolver los faltantes sin inventar buenas.</p></div>"
            '<div class="panel"><h2>Criterios de evaluación</h2><p>'
            + escape(METHOD)
            + "</p>"
            + "<p>"
            + escape(SIMILARITY_METHOD)
            + "</p><p>Referencia del método: "
            '<a href="https://docs.obspy.org/packages/autogen/obspy.signal.cross_correlation.correlate_template.html">'
            "correlación cruzada normalizada (ObsPy)</a>. Los umbrales son locales.</p>"
            "<p>Controles conocidos: 18/20 → buena (90 %); 15/20 → regular (75 %); 14/20 → mala (70 %). "
            "Los colores se calculan de las muestras, sin consultar las etiquetas esperadas.</p></div>"
            + "".join(sections)
            + f"<footer>Generado: {escape(report['generated_at_utc'])}. "
            "Originales verificados por SHA-256. JSON: protocolos, motivos y hashes. CSV: todos los canales. "
            "PDF: resumen, gráficas y diagnóstico por canal.</footer></main>"
            '<script>document.getElementById("grade").addEventListener("change",e=>{'
            'document.querySelectorAll("tr[data-grade]").forEach(r=>{r.hidden=!!e.target.value && '
            "r.dataset.grade!==e.target.value;});});"
            'window.addEventListener("beforeprint",()=>{document.querySelectorAll("details").forEach(d=>d.open=true);});'
            "</script></html>"
        )
    )


def snr_display(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def trace_snr_display(trace: dict) -> str:
    return snr_display(trace["snr"].get("value")) + (" *" if trace["snr"]["state"] == "CONDITIONAL" else "")


def trace_reasons(trace: dict) -> str:
    quality = trace["quality"]
    reasons = quality.get("demonstrated_failures", []) + quality.get("review_reasons", [])
    if quality["missing_evidence"]:
        reasons = reasons + ["Evidencia pendiente: ver notas del registro"]
    actions = trace.get("noise_diagnostics", {}).get("actions", []) + trace.get("similarity", {}).get("actions", [])
    return "; ".join(reasons + actions) or "Comprobaciones completas dentro de límites"


def noise_figure(record: dict):
    fig, axes = plt.subplots(2, 2, figsize=(13, 7), constrained_layout=True)
    for trace in record["traces"]:
        channel = trace["channel_1based"]
        d = trace["noise_diagnostics"]
        color = trace["quality"]["assessment_color"]
        if d["snr"].get("value") is not None:
            axes[0, 0].plot(channel, d["snr"]["value"], ".", color=color)
        for key, marker, label in [("noise_rms_ac", "o", "RMS"), ("noise_sigma_mad", "+", "MAD gaussiana")]:
            if d.get(key, 0) > 0:
                axes[0, 1].plot(
                    channel,
                    d[key],
                    marker,
                    color="#2563eb" if key == "noise_rms_ac" else "#f97316",
                    ms=4,
                    label=label if channel == 1 else None,
                )
        lf = d.get("low_frequency", {})
        if lf.get("noise_power_to_signal_total_power") is not None:
            axes[1, 0].plot(channel, lf["noise_power_to_signal_total_power"], ".", color=color)
        for line in d.get("lines", []):
            axes[1, 1].plot(channel, line["estimated_hz"], "x", color="#9333ea")
    axes[0, 0].set(title="SNR condicional de ventana (*), no del primer arribo", ylabel="dB")
    axes[0, 0].axhline(6, ls="--", color="red", lw=0.6)
    axes[0, 0].axhline(12, ls="--", color="green", lw=0.6)
    axes[0, 1].set(title="Escalas distintas: potencia total y dispersión robusta", ylabel="Unidad nativa", yscale="log")
    axes[0, 1].legend(fontsize=8)
    axes[1, 0].set(title="Ruido LF / potencia total de señal; banda parcial", ylabel="Razón de potencias")
    axes[1, 1].set(title="Líneas candidatas; interpolación sin precisión certificada", ylabel="Hz", ylim=(0, 320))
    if not any(t["noise_diagnostics"].get("lines") for t in record["traces"]):
        axes[1, 1].text(0.5, 0.5, "Sin candidatos con este protocolo", ha="center", transform=axes[1, 1].transAxes)
    for ax in axes.flat:
        ax.set_xlabel("Canal")
        ax.grid(alpha=0.15)
    fig.suptitle(
        f"{record['site']} · {record['id']} · diagnóstico de ruido\n"
        "Sin notch/HP automático en originales. Los indicadores no identifican viento, red o acople por sí solos."
    )
    return fig


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/trace_quality")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    records, hashes = field_records()
    waveform = ROOT / "examples/e2/common_qc.sgy"
    protocol_path = ROOT / "examples/e2/protocol.json"
    protocol = QCProtocol.model_validate_json(protocol_path.read_text(encoding="utf-8"))
    records.append(
        qc_record(
            read_shot(waveform),
            protocol,
            site="Ejemplo E2",
            kind="SINTÉTICO",
            source=waveform.relative_to(ROOT).as_posix(),
        )
    )
    for path in (waveform, waveform.with_suffix(".sgy.json"), protocol_path, ROOT / "configs/vs30_sitio.yaml"):
        hashes[path.relative_to(ROOT).as_posix()] = sha256(path)
    validation = []
    for good in (18, 15, 14):
        shot, protocol, expected = synthetic_shot(good)
        np.savez_compressed(output / f"{shot.id}.npz", data=shot.data, dt_s=shot.dt_s, t0_s=shot.t0_s)
        record = qc_record(
            shot, protocol, site="Controles conocidos", kind="SINTÉTICO", source=f"{shot.id}.npz · semilla 20261010"
        )
        observed = [t["quality"]["grade"] for t in record["traces"]]
        validation.append(
            {"record": shot.id, "expected": expected, "observed": observed, "passed": expected == observed}
        )
        records.append(record)
    groups = [
        {
            "site": site,
            "quality": aggregate_quality(
                t["quality"]["grade"] for r in records if r["site"] == site for t in r["traces"]
            ),
            "assessment": assess_quality(t["quality"] for r in records if r["site"] == site for t in r["traces"]),
        }
        for site in dict.fromkeys(r["site"] for r in records)
    ]
    report = {
        "schema_version": 3,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "status": "DIAGNOSTIC_UNCALIBRATED",
        "eligible_for_acceptance": False,
        "method": METHOD,
        "similarity_method": SIMILARITY_METHOD,
        "aggregation": AGGREGATION,
        "limitations": LIMITATION,
        "policy": POLICY.model_dump(mode="json"),
        "input_sha256": hashes,
        "code_sha256": {
            p.relative_to(ROOT).as_posix(): sha256(p) for p in [Path(__file__), *sorted((ROOT / "geoqc").rglob("*.py"))]
        },
        "groups": groups,
        "synthetic_validation": validation,
        "records": records,
    }
    with PdfPages(output / "dossier.pdf") as pdf:
        import textwrap

        fig, ax = plt.subplots(figsize=(11.7, 8.3))
        ax.axis("off")
        text = "DOSIER DE CALIDAD POR TRAZA\n\n" + "\n\n".join(
            textwrap.fill(p, 105) for p in (AGGREGATION, METHOD, LIMITATION)
        )
        text += "\n\n" + "\n".join(
            f"{g['site']}: {g['assessment']['grade']} · {g['assessment']['demonstrated_bad_traces']} malas; "
            f"{g['assessment']['pending_traces']} pendientes"
            for g in groups
        )
        ax.text(0, 1, text, va="top", fontsize=11, linespacing=1.5)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)
        fig, ax = plt.subplots(figsize=(11.7, 8.3))
        ax.axis("off")
        ax.text(
            0,
            1,
            "CONSISTENCIA LOCAL DE FORMAS\n\n" + textwrap.fill(SIMILARITY_METHOD, 100),
            va="top",
            fontsize=12,
            linespacing=1.7,
        )
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)
        fig = summary_figure(records)
        fig.savefig(output / "summary.png", dpi=130)
        pdf.savefig(fig)
        plt.close(fig)
        for index, record in enumerate(records):
            record["plot"] = f"traces_{index + 1:02d}.png"
            fig = trace_figure(record)
            fig.savefig(output / record["plot"], dpi=125)
            pdf.savefig(fig)
            plt.close(fig)
            if any("noise_diagnostics" in t for t in record["traces"]):
                record["noise_plot"] = f"noise_{index + 1:02d}.png"
                fig = noise_figure(record)
                fig.savefig(output / record["noise_plot"], dpi=125)
                pdf.savefig(fig)
                plt.close(fig)
            if any(t.get("similarity", {}).get("grade") == "MALA" for t in record["traces"]):
                record["anomaly_plot"] = f"anomalies_{index + 1:02d}.png"
                fig = anomaly_figure(record)
                fig.savefig(output / record["anomaly_plot"], dpi=140)
                pdf.savefig(fig)
                plt.close(fig)
            rows = []
            for t in record["traces"]:
                reasons = textwrap.wrap(trace_reasons(t), 85)
                # Una fila por motivo envuelto para conservar todo el diagnóstico en PDF.
                for line_index, reason in enumerate(reasons):
                    rows.append(
                        [
                            str(t["channel_1based"]) if line_index == 0 else "",
                            t["quality"]["assessment_grade"] if line_index == 0 else "",
                            trace_snr_display(t) if line_index == 0 else "",
                            reason,
                        ]
                    )
            pdf_table(
                pdf,
                f"{record['site']} · {record['id']} · motivos",
                rows,
                ["Canal", "Calidad", "SNR (dB)", "Motivo"],
                record.get("notes"),
            )
    serializable = [{k: v for k, v in r.items() if k not in ("data", "dt", "t0")} for r in records]
    report["records"] = serializable
    with (output / "traces.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "site",
                "record",
                "channel_1based",
                "receiver_id",
                "grade",
                "snr_db",
                "clip_fraction",
                "valid_fraction",
                "reasons",
                "evidence_complete",
                "similarity_grade",
                "median_abs_rho",
                "neighbor_consensus_rho",
                "spectral_median_hz",
                "baseline_relative_to_neighbors",
                "assessment_grade",
                "snr_state",
                "noise_sigma_mad",
                "low_frequency_state",
                "line_candidates_hz",
            ]
        )
        for r in records:
            for t in r["traces"]:
                writer.writerow(
                    [
                        r["site"],
                        r["id"],
                        t["channel_1based"],
                        t["receiver_id"],
                        t["quality"]["grade"],
                        t["snr"].get("value"),
                        t["clip"].get("value"),
                        t["valid_fraction"],
                        "; ".join(t["quality"]["reasons"]),
                        t["quality"]["evidence_complete"],
                        *[
                            t.get("similarity", {}).get(key)
                            for key in (
                                "grade",
                                "median_abs_rho",
                                "neighbor_consensus_rho",
                                "spectral_median_hz",
                                "baseline_relative_to_neighbors",
                            )
                        ],
                        t["quality"]["assessment_grade"],
                        t["snr"]["state"],
                        t.get("noise_diagnostics", {}).get("noise_sigma_mad"),
                        t.get("noise_diagnostics", {}).get("low_frequency", {}).get("state"),
                        json.dumps([line["estimated_hz"] for line in t.get("noise_diagnostics", {}).get("lines", [])]),
                    ]
                )
    save_json(output / "dossier.json", report)
    (output / "dossier.html").write_text(html_report(report, output), encoding="utf-8")
    print(
        json.dumps(
            {"records": len(records), "groups": groups, "synthetic_validation": validation},
            ensure_ascii=True,
            indent=2,
        )
    )
    print(f"Dosier: {output / 'dossier.html'}")
    if not all(v["passed"] for v in validation):
        raise SystemExit("Validación sintética fallida: revisar etiquetas y métricas del dosier")


if __name__ == "__main__":
    main()
