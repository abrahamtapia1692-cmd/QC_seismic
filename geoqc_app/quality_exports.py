"""Portable QC report reuses the application's read-only visual renderer."""
from __future__ import annotations

import base64
import hashlib
import html
import json
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Any

from geoqc_app.trs_details import record_projection, trace_projection

WEB = Path(__file__).parent / "web"
RESOURCES = ("trace-quality.js", "trs-visuals.js", "style.css", "trs-visuals.css")


def resource_hashes() -> dict[str, str]:
    return {name: hashlib.sha256((WEB / name).read_bytes()).hexdigest() for name in RESOURCES}


def quality_html(document: dict[str, Any], warning: str, fallback: str) -> bytes:
    """No remote requests, credentials, recomputation, or untrusted HTML insertion."""
    records = document["diagnostic_quality"]
    display = {"records": [record_projection(r, i) for i, r in enumerate(records)],
               "details": [{"arrivals": r["diagnostics"]["picks"], "branches": r["diagnostics"]["branches"],
                            "qc-traces": [trace_projection(t) for t in r.get("trace_qc", {}).get("traces", [])]}
                           for r in records]}
    payload = json.dumps(display, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c")
    qc = (WEB / "trace-quality.js").read_text(encoding="utf-8").replace("export function ", "function ")
    trs = "\n".join(line for line in (WEB / "trs-visuals.js").read_text(encoding="utf-8").splitlines()
                    if not line.startswith("import ")).replace("export function ", "function ")
    script = ("'use strict';\nconst {renderTraceQuality,renderQualityOverview}=(()=>{\n" + qc
              + "\nreturn {renderTraceQuality,renderQualityOverview};})();\n(()=>{\n" + trs
              + "\nconst snapshot=" + payload + ";\n"
              "const request=async(path)=>{const match=path.match(/records\\/(\\d+)\\/(arrivals|branches|qc-traces)/);"
              "if(!match)throw new Error('Colección fuera del snapshot');"
              "const collection=match[2],items=snapshot.details[Number(match[1])][collection];"
              "return {body:{collection,[collection.replaceAll('-','_')]:items,total_items:items.length,next_cursor:null}};};"
              "renderTRSDashboard(document.getElementById('report'),snapshot.records,request,'offline',()=>true);"
              "document.getElementById('print-report').onclick=()=>window.print();"
              "document.getElementById('fallback').hidden=true;})();")
    # Only this exact, packaged renderer can execute. All record strings use textContent.
    digest = base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode("ascii")
    styles = "\n".join((WEB / name).read_text(encoding="utf-8") for name in ("style.css", "trs-visuals.css"))
    science = html.escape(json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True))
    return ("<!doctype html><html lang='es'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; "
            "style-src 'unsafe-inline'; script-src 'sha256-" + digest + "'\">"
            "<title>GeoQC - dosier TRS · calidad por traza</title><style>" + styles
            + "\n.export-toolbar{display:flex;justify-content:space-between;align-items:center}"
            "@media print{.export-toolbar,#scientific-json{display:none}}</style></head><body><main>"
            "<div class='export-toolbar'><h1>Dosier TRS · calidad por traza</h1>"
            "<button id='print-report' type='button'>Imprimir / guardar PDF</button></div>"
            "<aside class='notice'>" + html.escape(warning) + "</aside>"
            "<p>Calificación por traza y tendido (diagnóstica). Snapshot autónomo; la revisión humana se consulta por separado.</p>"
            "<p class='digest'>Digest científico: " + html.escape(document["scientific_digest"]) + "</p>"
            "<div id='report'></div><div id='fallback'><p>Resumen accesible sin JavaScript.</p>" + fallback + "</div>"
            "<details id='scientific-json'><summary>JSON científico completo, protocolos y procedencia</summary><pre>"
            + science + "</pre></details></main><script type='text/javascript'>" + script + "</script></body></html>"
            ).encode("utf-8")


def draw_quality_pdf(canvas: Any, document: dict[str, Any], warning: str) -> None:
    """Human report with native metrics and vector plots; full arrays stay in JSON/HTML."""
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, Table, TableStyle

    width, y, page = 530, 760.0, 0
    style = ParagraphStyle("QC", fontName="Helvetica", fontSize=9, leading=12, spaceAfter=5)
    palette = {"BUENA": "#16803c", "REGULAR": "#b77900", "MALA": "#dc2626", "NO_EVALUABLE": "#64748b"}

    def new_page() -> None:
        nonlocal y, page
        if page:
            canvas.showPage()
        page += 1
        canvas.setFillColor(colors.HexColor("#173e43"))
        canvas.setFont("Helvetica-Bold", 13)
        canvas.drawString(32, 810, "GeoQC - TRS | Calidad por traza y tendido")
        canvas.setFont("Helvetica", 7)
        canvas.drawString(32, 795, warning)
        canvas.drawString(32, 782, "Digest: " + document["scientific_digest"])
        canvas.drawRightString(562, 22, str(page))
        y = 760

    def ensure(height: float) -> None:
        if y - height < 40:
            new_page()

    def text(value: Any, heading: bool = False) -> None:
        nonlocal y
        if len(str(value)) > 1800:
            for part in textwrap.wrap(str(value), width=1800, replace_whitespace=False, drop_whitespace=False):
                text(part, heading)
            return
        current = ParagraphStyle("heading", parent=style, fontName="Helvetica-Bold", fontSize=12, leading=15) if heading else style
        paragraph = Paragraph(html.escape(str(value)).replace("\n", "<br/>"), current)
        _, height = paragraph.wrap(width, 700)
        ensure(height + 10)
        paragraph.drawOn(canvas, 32, y - height)
        y -= height + 10

    def rows(headers: list[str], data: list[list[Any]], widths: list[float] | None = None) -> None:
        nonlocal y
        col_widths = widths or [width / len(headers)] * len(headers)
        header = [Paragraph(html.escape(h), style) for h in headers]

        def row(values: list[Any], is_header: bool = False) -> None:
            nonlocal y
            cells = values if is_header else [Paragraph(html.escape(str(v if v is not None else "Sin valor")), style) for v in values]
            t = Table([cells], colWidths=col_widths)
            t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eaf1ee") if is_header else colors.white),
                                   ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#d7e2df")),
                                   ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
            _, height = t.wrap(width, 700)
            if y - height < 40:
                new_page()
                if not is_header:
                    row(header, True)
            t.drawOn(canvas, 32, y - height)
            y -= height

        row(header, True)
        for values in data:
            row(values)
        y -= 12

    def number(value: Any) -> str:
        return f"{value:.5g}" if isinstance(value, (int, float)) else "Sin valor"

    def chart(title: str, traces: list[dict[str, Any]], series: list[tuple[str, Callable[[dict[str, Any]], Any], str]], unit: str) -> None:
        nonlocal y
        ensure(215)
        text(title, True)
        values = [v for t in traces for _, get, _ in series if isinstance(v := get(t), (int, float))]
        if not values:
            text("Sin valores evaluables con este protocolo; no se representan como cero.")
            return
        bottom, height = y - 135, 120
        low, high = min(0, min(values)), max(values)
        span = high - low or 1
        canvas.setFont("Helvetica", 7)
        for i in range(5):
            v = low + span * i / 4
            yy = bottom + height * i / 4
            canvas.setStrokeColor(colors.HexColor("#dfe8e5"))
            canvas.line(85, yy, 555, yy)
            canvas.setFillColor(colors.HexColor("#476567"))
            canvas.drawRightString(78, yy - 2, number(v))
        for i, t in enumerate(traces):
            x = 85 + 470 * i / max(1, len(traces) - 1)
            if i == 0 or i == len(traces) - 1 or (i + 1) % 4 == 0:
                canvas.setFillColor(colors.HexColor("#476567"))
                canvas.drawCentredString(x, bottom - 12, str(t.get("channel_1based", i + 1)))
            for _, get, color in series:
                v = get(t)
                if not isinstance(v, (int, float)):
                    continue
                canvas.setFillColor(colors.HexColor(color or palette[t["quality"]["assessment_grade"]]))
                canvas.circle(x, bottom + height * (v - low) / span, 2.5, stroke=0, fill=1)
        y = bottom - 22
        text("Canal | " + unit + " | " + "; ".join(name for name, _, _ in series))

    new_page()
    text("Calificación por traza y tendido (diagnóstica)", True)
    text("Verde: buena. Amarillo: revisión. Rojo: mala. Gris: no evaluable. Política DRAFT; límites provisionales locales.")
    operational = document.get("operational_assessment")
    if operational:
        text("Calificación diagnóstica condicional del conjunto: " + operational["grade"], True)
        text(f"Política {operational['policy_id']}. Cobertura media {100 * operational['mean_coverage_fraction']:.2f} %. "
             "La cobertura es disponibilidad de comprobaciones, no confianza estadística. No certifica aceptación de campo.")
        text("Conteos diagnósticos: " + json.dumps(operational["counts"], ensure_ascii=False))
    a = document.get("trace_qc_assessment")
    if a:
        text(f"Conjunto de registros: {a['grade']} | {a['total_traces']} trazas")
        text(f"Intervalo de buenas: {a['good_percent_bounds'][0]:g}-{a['good_percent_bounds'][1]:g} %. "
             f"Fallas demostradas: {a['demonstrated_bad_traces']}. Evidencia pendiente: {a['pending_traces']}.")
    text("Porcentaje bueno = 100 x buenas / total. BUENA: >=90 %; REGULAR: >=75 % y <90 %; MALA: <75 %. "
         "Todas las trazas permanecen en el denominador. El conjunto suma trazas; no promedia porcentajes. "
         "Si los extremos posibles cambian de categoría, la evaluación es NO_EVALUABLE. Las abstenciones del picker no califican la adquisición.")
    summary = []
    for record in document["diagnostic_quality"]:
        qc = record.get("trace_qc")
        if qc:
            a = qc["data_assessment"]
            counts = {k: sum(t["quality"]["assessment_grade"] == k for t in qc["traces"]) for k in palette}
            summary.append([record["shot_id"], *counts.values(), a["grade"]])
    rows(["Registro", "Buenas", "Revisión", "Malas", "No evaluables", "Evaluación"], summary, [180, 48, 48, 48, 65, 141])
    for record in document["diagnostic_quality"]:
        new_page()
        text("Registro / tendido: " + record["shot_id"], True)
        qc = record.get("trace_qc")
        if not qc:
            text("Dosier histórico sin QC por traza; requiere otra ejecución.")
            continue
        traces, protocol = qc["traces"], qc["request"]["protocol"]
        policy = protocol["quality_policy"]
        if qc.get("operational_assessment"):
            op = qc["operational_assessment"]
            declared = qc["request"]["operational_policy"]
            text("Calificación diagnóstica del tendido: " + op["grade"], True)
            text(f"Mínimo de cobertura {100 * declared['minimum_coverage']:g} %. Dominios: integridad, morfología, "
                 "contraste y similitud. Integridad, morfología y contraste son necesarios para declarar buena. "
                 f"Contraste bueno si todo el intervalo alcanza {declared['contrast_good_db']:g} dB; "
                 f"ruido estable si máximo/mínimo <= {declared['max_reference_power_ratio']:g}. "
                 "El intervalo es sensibilidad entre bloques, no un intervalo de confianza.")
            text("Mesetas extremas de al menos " + str(declared["plateau_min_run"]) + " muestras generan revisión; "
                 "no son límites ADC estimados. Sin consenso de vecinos, la similitud no es un criterio de falla. "
                 "Una línea aislada no basta: se comprueba persistencia entre bloques. "
                 "La evaluación estricta y sus faltantes permanecen separados.")
            rows(["Canal", "Diagnóstica", "Cobertura", "Motivos"], [[t["receiver_id"], t["operational_quality"]["grade"],
                 f"{100 * t['operational_quality']['coverage_fraction']:g} %", "; ".join(t["operational_quality"]["reasons"])]
                 for t in traces], [55, 75, 60, 340])
            chart("Contraste estimado: sensibilidad a bloques", traces, [
                ("Inferior azul", lambda t: t["operational_quality"]["estimated_contrast"].get("db_bounds", [None, None])[0], "#2563eb"),
                ("Superior naranja", lambda t: t["operational_quality"]["estimated_contrast"].get("db_bounds", [None, None])[1], "#d97706")], "dB condicionales")
            chart("Similitud estimada (sin certificar comparabilidad)", traces, [
                ("|rho|", lambda t: t["operational_quality"]["estimated_similarity"].get("median_abs_rho"), "#236763")], "correlación")
        text("Criterios de evaluación y umbrales aplicados", True)
        text("Política: " + policy["id"])
        rows(["Evidencia", "Buena", "Revisión", "Mala / falla"], [
            ["Integridad", "Todas las muestras válidas", "Huecos parciales", "Sin soporte válido"],
            ["Señal", "Variable", "Anomalía con modelo declarado", "Canal muerto o constante"],
            ["SNR válida", f">={policy['snr_good_min_db']:g} dB", f">={policy['snr_bad_below_db']:g} y <{policy['snr_good_min_db']:g} dB", f"<{policy['snr_bad_below_db']:g} dB o neta no resuelta con ruido verificado"],
            ["Clipping", f"<={100 * policy['clip_good_max_fraction']:g} %", f">{100 * policy['clip_good_max_fraction']:g} y <{100 * policy['clip_bad_min_fraction']:g} %", f">={100 * policy['clip_bad_min_fraction']:g} %"],
        ])
        text("Se conserva la peor condición demostrada. Solo faltantes: no evaluable. Una falla demostrada prevalece sobre faltantes. "
             "SNR requiere independencia y estacionariedad; clipping requiere rails/escala y soporte de apilamiento. La SNR condicional no valida el primer arribo.")
        window_rows = [[name, json.dumps(protocol.get(key), ensure_ascii=False)] for name, key in
                       [("Ventana de análisis", "analysis"), ("Ventana de señal", "signal"), ("Referencia de ruido", "noise")]]
        rows(["Condición", "Declaración del protocolo"], window_rows, [150, 380])
        text("Independencia del ruido: " + str(protocol["noise_independent"]) + "; estacionariedad: " + protocol["noise_stationarity"])
        if protocol.get("similarity"):
            text("Similitud: parámetros y comparabilidad declarados en el protocolo", True)
            rows(["Parámetro", "Valor"], [[k, v] for k, v in protocol["similarity"].items() if k not in ("schema_version", "reference")], [220, 310])
        if qc["request"].get("noise"):
            text("Ruido: protocolo y límites de soporte", True)
            rows(["Parámetro", "Valor"], [[k, str(v)] for k, v in qc["request"]["noise"].items() if k not in ("schema_version", "reference", "noise", "signal")], [220, 310])
        new_page()
        text("Diagnóstico gráfico de calidad y ruido", True)
        chart("SNR neta válida por canal", traces, [("SNR válida", lambda t: t["snr"]["value"] if t["snr"]["state"] == "VALID" else None, "")], "dB")
        chart("SNR condicional de ventana", traces, [("No valida el primer arribo", lambda t: t.get("noise_diagnostics", {}).get("snr", {}).get("value"), "")], "dB")
        chart("Clipping confirmado", traces, [("Clipping", lambda t: 100 * t["clip"]["value"] if t["clip"]["state"] == "VALID" and t["clip"]["value"] is not None else None, "")], "%")
        chart("Similitud local y consenso", traces, [("|rho| mediana", lambda t: t.get("similarity", {}).get("median_abs_rho"), "#236763"), ("Consenso", lambda t: t.get("similarity", {}).get("neighbor_consensus_rho"), "#b77900")], "correlación")
        chart("Escalas de ruido: RMS AC y MAD", traces, [("RMS AC azul", lambda t: t.get("noise_diagnostics", {}).get("noise_rms_ac"), "#2563eb"), ("MAD naranja", lambda t: t.get("noise_diagnostics", {}).get("noise_sigma_mad"), "#d97706")], record["amplitude_unit"])
        chart("Ruido LF / potencia total de señal", traces, [("Banda soportada parcial", lambda t: t.get("noise_diagnostics", {}).get("low_frequency", {}).get("noise_power_to_signal_total_power"), "")], "razón de potencias")
        new_page()
        text("Formas de onda por canal", True)
        text("Envolvente min/max de las muestras originales. Centrado y normalización por canal solo para visualizar; sin filtrado, alineación ni corrección de polaridad.")
        for trace in traces:
            ensure(28)
            w = trace["waveform_preview"]
            values = [v for _, v in w["points"] if v is not None]
            center = trace["statistics"].get("dc") or 0
            amplitude = max((abs(v - center) for v in values), default=0) or 1
            canvas.setFillColor(colors.HexColor("#476567"))
            canvas.setFont("Helvetica", 8)
            canvas.drawString(32, y - 10, trace["receiver_id"])
            canvas.setStrokeColor(colors.HexColor(palette[trace["quality"]["assessment_grade"]]))
            path = canvas.beginPath()
            connected = False
            for index, value in w["points"]:
                if value is None:
                    connected = False
                    continue
                x, yy = 90 + index / max(1, w["sample_count"] - 1) * 460, y - 8 + 9 * (value - center) / amplitude
                if connected:
                    path.lineTo(x, yy)
                else:
                    path.moveTo(x, yy)
                connected = True
            canvas.drawPath(path)
            y -= 25
        if traces:
            w = traces[0]["waveform_preview"]
            text(f"Tiempo registrado: {w['t0_s']:g} a {w['t0_s'] + w['sample_count'] * w['dt_s']:g} s (primer canal).")
        new_page()
        text("Diagnóstico por canal: métricas, motivos y acciones", True)
        for t in traces:
            text(f"{t['receiver_id']}: {t['quality']['assessment_grade']}", True)
            text(f"Integridad {100 * t['valid_fraction']:g} %. SNR válida: {t['snr']['state']} / {number(t['snr']['value'])} dB. "
                 f"Clipping: {t['clip']['state']} / {number(t['clip']['value'])} (fracción).")
            text("Motivos: " + "; ".join(t["quality"]["reasons"]))
            if t.get("operational_quality"):
                text("Estimaciones y soporte diagnóstico: " + json.dumps(t["operational_quality"], ensure_ascii=False))
            n, sim = t.get("noise_diagnostics", {}), t.get("similarity", {})
            if n:
                text(f"Ruido: {n['state']}. SNR condicional: {number(n.get('snr', {}).get('value'))} dB. "
                     f"RMS AC: {number(n.get('noise_rms_ac'))}; MAD: {number(n.get('noise_sigma_mad'))} {record['amplitude_unit']}.")
                text("Estacionariedad interna: " + json.dumps(n.get("stationarity"), ensure_ascii=False))
                text("Baja frecuencia: " + json.dumps(n.get("low_frequency"), ensure_ascii=False))
                text("Líneas candidatas: " + json.dumps(n.get("lines"), ensure_ascii=False))
            if sim:
                text("Similitud: " + sim["state"] + "; |rho|=" + number(sim.get("median_abs_rho")) + "; consenso=" + number(sim.get("neighbor_consensus_rho")))
            actions = n.get("actions", []) + sim.get("actions", [])
            if actions:
                text("Acciones: " + "; ".join(actions))
        text("Coherencia LF entre canales contiguos", True)
        for pair in qc.get("noise_coherence", []):
            text(" / ".join(pair["receiver_ids"]) + ": " + json.dumps({k: v for k, v in pair.items() if k != "receiver_ids"}, ensure_ascii=False))
        text("Cobertura metodológica y evidencia pendiente", True)
        rows(["Etapa", "Estado"], [[k, v] for k, v in qc["methodology"].items()], [150, 380])
        for reason in sorted({r for t in traces for r in t["quality"]["missing_evidence"]}):
            text(reason)
        text("Primeros arribos y ramas TRS", True)
        rows(["Receptor", "Offset (m)", "Llegada (s)", "Sigma (s)", "Estado"], [
            [p["receiver_id"], number(p["offset_m"]), number(p["arrival"]["onset_s"]), number(p["arrival"]["sigma_s"]), p["arrival"]["confidence"]]
            for p in record["diagnostics"]["picks"]])
        for branch in record["diagnostics"]["branches"]:
            text("Rama " + branch["side"] + ": " + json.dumps(branch, ensure_ascii=False))
        text("Procedencia y protocolo congelado", True)
        text(json.dumps(qc["request"], ensure_ascii=False, sort_keys=True))
    text("Procedencia de la ejecución", True)
    text(json.dumps({k: document[k] for k in ("acquisition_revision_id", "input_manifest", "engine_reference", "sufficiency", "eligible_for_acceptance")}, ensure_ascii=False, sort_keys=True))
    text("Las matrices, PSD y vectores completos se conservan en el JSON científico y en el HTML autónomo del mismo digest. "
         "Este PDF presenta las gráficas, métricas, motivos y criterios de calidad. La revisión humana se consulta por separado.")
    canvas.showPage()
