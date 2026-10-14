"""Build an exploratory field report from preserved probe evidence, without rerunning algorithms."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import math
from collections import Counter
from datetime import UTC, datetime
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABELS = {"GREEN": "Verde", "AMBER": "Amarillo", "RED": "Rojo", "GRAY": "No evaluable"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def coverage_color(onsets: int, total: int, criteria: dict) -> str:
    if total <= 0:
        return "GRAY"
    if not 0 <= onsets <= total:
        raise ValueError("Onset count must lie between zero and the total channel count")
    limits = criteria["trs_onset_coverage"]
    green, amber = limits["green_min"], limits["amber_min"]
    if not 0 <= amber <= green <= 1:
        raise ValueError("Invalid coverage limits")
    fraction = onsets / total
    return "GREEN" if fraction >= green else "AMBER" if fraction >= amber else "RED"


def overall_color(colors: list[str], *, unresolved: bool) -> str:
    if not colors or all(color == "GRAY" for color in colors):
        return "GRAY"
    if "RED" in colors:
        return "RED"
    if unresolved or "GRAY" in colors or "AMBER" in colors:
        return "AMBER"
    return "GREEN"


def reading_color(qc: dict, technical_checks: list[dict]) -> str:
    finite = qc.get("finite_fraction")
    if finite is None or not technical_checks:
        return "GRAY"
    if not math.isfinite(finite) or finite < 1 or not all(item["passed"] for item in technical_checks):
        return "RED"
    if qc["constant_channels_1based"] or qc["zero_channels_1based"]:
        return "AMBER"
    return "GREEN"


def verify_evidence(root: Path, results: dict) -> dict[str, str]:
    """Refuse stale source/code snapshots instead of showing historical green checks as current."""
    manifest_path = root / results["download_manifest"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["repositories"] != results["repositories"]:
        raise ValueError("Probe and download repository snapshots differ")
    hashes = {entry["path"]: entry["sha256"] for entry in manifest["files"]}
    hashes.update(results["code_sha256"])
    for relative, expected in hashes.items():
        if sha256(root / relative) != expected:
            raise ValueError(f"Evidence is stale or modified: {relative}; rerun the probe after review")
    artifacts = [
        "evidence/field/results.json",
        results["download_manifest"],
        "examples/field/quality_criteria.json",
        "tools/report_field_quality.py",
        "evidence/field/chevremont_picks.csv",
        "evidence/field/chevremont_annotation_comparison.csv",
        "evidence/field/oysand_masw.png",
        "evidence/field/chevremont_trs.png",
    ]
    artifacts += [f"evidence/field/oysand_{int(item['offset_m'])}m_ridge.csv" for item in results["oysand"]]
    hashes.update({relative: sha256(root / relative) for relative in artifacts})
    return hashes


def make_records(root: Path, results: dict, criteria: dict) -> list[dict]:
    checks = results["checks"]
    records = []
    for index, item in enumerate(results["oysand"], 1):
        offset = int(item["offset_m"])
        curve = read_csv(root / f"evidence/field/oysand_{offset}m_ridge.csv")
        unaliased = [row for row in curve if row["spatially_unaliased_candidate"] == "True"]
        if len(unaliased) != item["spatially_unaliased_ridge_bins"]:
            raise ValueError("Ridge CSV does not match probe evidence")
        technical = [check for check in checks if check["id"].startswith(f"oysand_{offset}_")]
        reading = reading_color(item["qc"], technical)
        process = "AMBER" if unaliased else "RED"
        comparison = item["comparison_to_upstream_composite"]
        if comparison["bins"] <= 0:
            reference = "GRAY"
            detail = "Sin bins comparables con la compuesta."
        else:
            reference = "AMBER"
            detail = (
                f"{comparison['bins']} bins comparados: mediana absoluta "
                f"{comparison['median_absolute_difference_ms']:.2f} m/s; "
                f"RMS {comparison['rmse_ms']:.2f} m/s. Referencia compuesta del mismo sitio; "
                "sin etiquetas individuales ni umbral de exactitud calibrado."
            )
        support = [float(row["frequency_hz"]) for row in unaliased]
        records.append(
            {
                "id": f"oysand-r{index}",
                "site": "Oysand",
                "profile": "P1",
                "technique": "MASW",
                "file": item["file"],
                "label": f"r{index} · offset {offset} m",
                "unit": "Registro multicanal; no sitio independiente",
                "stack_count": None,
                "channels": item["qc"]["channels"],
                "samples_per_channel": item["qc"]["samples_per_channel"],
                "fs_hz": item["fs_hz"],
                "reading": reading,
                "processing": process,
                "reference": reference,
                "overall": overall_color([reading, process, reference], unresolved=True),
                "eligible_for_acceptance": False,
                "processing_detail": (
                    f"{len(unaliased)}/{len(curve)} bins candidatos sin alias espacial. "
                    "Identidad modal aparente y papel del canal trigger pendientes."
                ),
                "reference_detail": detail,
                "metrics": {
                    "candidate_bins": len(curve),
                    "unaliased_candidate_bins": len(unaliased),
                    "candidate_support_frequencies_hz": support,
                    "compared_bins": comparison["bins"],
                    "median_absolute_difference_m_per_s": comparison["median_absolute_difference_ms"],
                    "rms_difference_m_per_s": comparison["rmse_ms"],
                },
                "next_action": "Confirmar canal 1/trigger y modo; comparar sensibilidad a ventanas en la banda admisible.",
            }
        )
    picks = read_csv(root / "evidence/field/chevremont_picks.csv")
    annotations = read_csv(root / "evidence/field/chevremont_annotation_comparison.csv")
    if len(annotations) != results["chevremont"]["annotation_count"]:
        raise ValueError("Annotation CSV does not match probe evidence")
    for item in results["chevremont"]["shots"]:
        filename = Path(item["file"]).name
        shot_picks = [row for row in picks if row["file"] == filename]
        states = Counter(row["confidence"] for row in shot_picks)
        n = item["qc"]["channels"]
        if len(shot_picks) != n or dict(states) != item["pick_states"]:
            raise ValueError(f"Pick CSV does not match probe evidence: {filename}")
        onsets = sum(bool(row["onset_s"]) for row in shot_picks)
        labels = [row for row in annotations if row["file"] == filename]
        if len(labels) != item["matched_upstream_annotations"]:
            raise ValueError(f"Annotation mapping does not match probe evidence: {filename}")
        differences = [float(row["difference_ms"]) for row in labels if row["difference_ms"]]
        mean_abs = sum(abs(value) for value in differences) / len(differences) if differences else None
        technical = [check for check in checks if check["id"].startswith(f"{filename}_")]
        reading = reading_color(item["qc"], technical)
        process = coverage_color(onsets, n, criteria)
        detail = "Sin anotaciones del repositorio para esta fuente; coincidencia no evaluable."
        if labels:
            detail = (
                (
                    f"{len(differences)}/{len(labels)} anotaciones con onset comparable; "
                    f"{len(labels) - len(differences)} abstenciones. "
                    f"Diferencia absoluta media condicional: {mean_abs:.2f} ms. "
                    "Reloj y definición de llegada sin adjudicar; exactitud no evaluable."
                )
                if differences
                else (f"{len(labels)} anotaciones, sin onsets comparables; exactitud no evaluable.")
            )
        records.append(
            {
                "id": f"chevremont-{filename.removesuffix('.sg2')}",
                "site": "Chevremont",
                "profile": "Línea local",
                "technique": "TRS",
                "file": item["file"],
                "label": f"Fuente {item['source_xz_m'][0]:g} m · {filename}",
                "unit": "Registro multicanal apilado de 3 impactos; impactos originales no disponibles",
                "stack_count": 3,
                "channels": n,
                "samples_per_channel": item["qc"]["samples_per_channel"],
                "fs_hz": 1 / item["dt_s"],
                "reading": reading,
                "processing": process,
                "reference": "GRAY",
                "overall": overall_color([reading, process, "GRAY"], unresolved=True),
                "eligible_for_acceptance": False,
                "processing_detail": f"{onsets}/{n} onsets ({100 * onsets / n:.1f} %); {n - onsets} abstenciones. "
                "Onsets exploratorios sin calibrar; protocolo fijo aplicado sin ajuste a etiquetas.",
                "reference_detail": detail,
                "metrics": {
                    "onsets": onsets,
                    "abstentions": n - onsets,
                    "pick_states": dict(states),
                    "onset_coverage": onsets / n,
                    "reference_annotations": len(labels),
                    "compared_annotations": len(differences),
                    "annotation_abstentions": len(labels) - len(differences),
                    "conditional_mean_absolute_difference_milliseconds": mean_abs,
                },
                "next_action": "Adjudicar tiempo de fuente y primeras llegadas; completar sidecar antes de ingesta formal.",
            }
        )
    return records


def badge(color: str) -> str:
    return f'<span class="badge {color.lower()}">{LABELS[color]}</span>'


def markdown_report(report: dict) -> str:
    lines = [
        "# Semáforo diagnóstico de datos de campo",
        "",
        "Criterio local **FIELD_DIAGNOSTIC_V1 · borrador sin calibrar**. No habilita aceptación de campo ni Vs30.",
        "",
        "Un mini conjunto es un registro multicanal, formado por varias trazas. "
        "Los 11 registros pertenecen a **dos sitios**, no a 11 sitios independientes.",
        "",
        "- **Oysand / P1:** r1–r4, offsets 10/15/20/30 m, 24 trazas por registro; referencia MASW compuesta del sitio.",
        "- **Chevremont:** siete fuentes 0–60 m, 48 trazas por registro, cada archivo apila 3 impactos. "
        "Solo la fuente 0 m tiene 43 anotaciones TRS.",
        "",
        "Verde = dimensión comprobada; amarillo = revisión; rojo = problema según criterio diagnóstico; "
        "gris = evidencia insuficiente. El rojo TRS describe cobertura del procesamiento actual, "
        "no prueba que la adquisición sea mala.",
        "",
        "| Registro | Técnica | Lectura | Proceso | Referencia | Diagnóstico |",
        "|---|---|---|---|---|---|",
    ]
    for record in report["records"]:
        labels = [LABELS[record[key]] for key in ("reading", "processing", "reference", "overall")]
        lines.append(f"| {record['site']} · {record['label']} | {record['technique']} | " + " | ".join(labels) + " |")
    lines += [
        "",
        "## Reglas y alcance",
        "",
        "Lectura: hashes verificados, comprobaciones técnicas por registro y muestras finitas; "
        "canales cero o constantes impiden verde. No certifica respuesta instrumental o saturación.",
        "",
        "TRS: cobertura = onsets / todas las trazas del registro. Verde ≥80 %, amarillo ≥50 % y <80 %, "
        "rojo <50 %. Límites locales provisionales para disponibilidad, no exactitud. "
        "Cambiar los límites requiere editar y versionar `examples/field/quality_criteria.json`.",
        "",
        "MASW: soporte candidato c > 2·f·dx; soporte vacío rojo, soporte parcial o modo sin verificar amarillo. "
        "La curva compuesta permite diferencias numéricas, sin un umbral de aceptación calibrado. "
        "No se asignan las listas de curvas del repositorio a disparos sin una correspondencia documentada.",
        "",
        "Referencia TRS: sin etiquetas o sin reloj/definición de onset verificados, gris. "
        "No se convierte `err` del SGT en incertidumbre calibrada. "
        "El promedio de diferencias siempre se acompaña de cobertura y abstenciones.",
        "",
        "Diagnóstico: peor dimensión evaluada; faltantes obligatorios impiden verde. "
        "Aceptación de campo, inversión y Vs30 permanecen pendientes.",
        "",
        "## Detalle por registro",
        "",
    ]
    for record in report["records"]:
        lines += [
            f"### {record['site']} · {record['label']}",
            "",
            f"Archivo: `{record['file']}`. {record['channels']} canales × "
            f"{record['samples_per_channel']} muestras; {record['fs_hz']:g} Hz.",
            "",
            record["unit"] + ".",
            "",
            record["processing_detail"],
            "",
            record["reference_detail"],
            "",
            "Siguiente revisión: " + record["next_action"],
            "",
        ]
    lines += [
        "## Trazabilidad",
        "",
        f"Probe: {report['probe_executed_at_utc']}. Reporte: {report['generated_at_utc']}.",
        "",
        f"{report['checks_passed']}/{report['checks_total']} comprobaciones técnicas del probe pasan. "
        "Los hashes de originales y código se verifican nuevamente al generar el reporte.",
        "",
        "[Reporte interactivo](quality_report.html) · [Datos del reporte](quality_report.json) · "
        "[Resultados del probe](results.json)",
        "",
    ]
    return "\n".join(lines)


def html_report(report: dict, evidence: Path) -> str:
    rows = []
    for record in report["records"]:
        cells = "".join(f"<td>{badge(record[key])}</td>" for key in ("reading", "processing", "reference", "overall"))
        detail = (
            f"<strong>{escape(record['unit'])}.</strong><p>{escape(record['processing_detail'])}</p>"
            f"<p>{escape(record['reference_detail'])}</p><p>Siguiente revisión: "
            f"{escape(record['next_action'])}</p><code>{escape(record['file'])}</code>"
        )
        rows.append(
            f'<tr data-site="{record["site"]}" data-color="{record["overall"]}">'
            f"<td><strong>{escape(record['site'])}</strong><br>{escape(record['label'])}"
            f"<details><summary>Ver evidencia</summary>{detail}</details></td>"
            f"<td>{record['technique']}<br><small>{record['channels']} × "
            f"{record['samples_per_channel']}<br>{record['fs_hz']:g} Hz</small></td>{cells}</tr>"
        )
    plots = []
    for filename, title in [
        ("oysand_masw.png", "Oysand: registros y dispersión aparente"),
        ("chevremont_trs.png", "Chevremont: onsets y anotaciones"),
    ]:
        encoded = base64.b64encode((evidence / filename).read_bytes()).decode("ascii")
        plots.append(
            f'<details class="plot"><summary>{title}</summary>'
            f'<img alt="{title}" src="data:image/png;base64,{encoded}"></details>'
        )
    counts = Counter(record["overall"] for record in report["records"])
    cards = "".join(
        f'<div class="card">{badge(color)}<b>{counts[color]}</b><span>registros</span></div>' for color in LABELS
    )
    trs = [record for record in report["records"] if record["technique"] == "TRS"]
    annotated = [record for record in trs if record["metrics"]["reference_annotations"]]
    total_annotations = sum(record["metrics"]["reference_annotations"] for record in annotated)
    compared = sum(record["metrics"]["compared_annotations"] for record in annotated)
    weighted_difference = (
        (
            sum(
                record["metrics"]["conditional_mean_absolute_difference_milliseconds"]
                * record["metrics"]["compared_annotations"]
                for record in annotated
                if record["metrics"]["compared_annotations"]
            )
            / compared
        )
        if compared
        else None
    )
    trs_comparison = (
        (
            f"Solo {compared} tienen onset: diferencia media absoluta {weighted_difference:.2f} ms "
            f"y {total_annotations - compared} abstenciones."
        )
        if compared
        else "Sin onsets comparables."
    )
    lower = f"{100 * report['criteria']['trs_onset_coverage']['amber_min']:g}"
    upper = f"{100 * report['criteria']['trs_onset_coverage']['green_min']:g}"
    return (
        """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Calidad diagnóstica · datos de campo</title><style>
:root{color-scheme:light;--ink:#18313e;--muted:#506777;--line:#d4e0e4}*{box-sizing:border-box}
body{margin:0;background:#f1f5f6;color:var(--ink);font:16px/1.55 system-ui,sans-serif}
main{max-width:1280px;margin:auto;padding:36px 24px}h1{font-size:clamp(26px,4vw,40px);line-height:1.15;margin:0}
h2{font-size:23px}p{max-width:100ch}small,.muted{color:var(--muted)}.eyebrow{letter-spacing:.07em;font-size:13px}
.notice{background:#fff0ce;border-left:5px solid #ac7514;padding:16px 20px;margin:22px 0}
.cards{display:flex;gap:14px;flex-wrap:wrap}.card{background:white;border:1px solid var(--line);border-radius:10px;
padding:18px;min-width:170px;display:grid;gap:4px}.card b{font-size:32px}
.badge{display:inline-block;white-space:nowrap;padding:3px 10px;border-radius:20px;font-size:13px;font-weight:700}
.green{background:#d5f4e3;color:#12613d}.amber{background:#ffecb4;color:#785600}
.red{background:#ffe0df;color:#972d30}.gray{background:#e6e9ee;color:#4d5560}
.toolbar{display:flex;gap:16px;flex-wrap:wrap;margin:24px 0 14px;align-items:center}
select,button{font:inherit;padding:8px 12px;border:1px solid #adc2cd;border-radius:6px;background:white;color:var(--ink)}
.table-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:white}
table{width:100%;border-collapse:collapse}th{text-align:left;background:#eaf0f3;font-size:14px}
td,th{padding:15px 12px;border-bottom:1px solid var(--line);vertical-align:top}td:first-child{min-width:255px}
details{margin-top:8px}summary{cursor:pointer;color:#155c76}details p{font-size:14px}code{font-size:12px;overflow-wrap:anywhere}
.explain{display:grid;grid-template-columns:repeat(auto-fit,minmax(285px,1fr));gap:16px;margin:20px 0}
.explain article{background:white;border:1px solid var(--line);padding:18px;border-radius:8px}
.plot{padding:16px;background:white;border:1px solid var(--line);border-radius:8px;margin:14px 0}.plot img{width:100%;height:auto}
footer{font-size:13px;margin-top:28px;color:var(--muted)}[hidden]{display:none!important}
@media print{body{background:white}main{padding:0}.toolbar{display:none}.cards{gap:8px}.card{min-width:130px}
td,th{padding:8px;font-size:12px}.badge{font-size:11px}details{break-inside:avoid}tr{break-inside:avoid}h2{break-after:avoid}}
</style></head><body><main>
<p class="eyebrow">DATOS DE CAMPO · FIELD_DIAGNOSTIC_V1</p><h1>Semáforo de calidad diagnóstica</h1>
<p>__RECORDS__ registros multicanal · __SITES__ sitios · __TRACES__ trazas. Cada fila representa un registro guardado.
El color resume el resultado del protocolo actual y la evidencia disponible.</p>
<div class="notice"><strong>Borrador sin calibrar.</strong> Los criterios son locales; los repositorios aportan
datos y referencias de procesamiento, sin un semáforo de aceptación adoptado aquí. Ningún registro habilita
aceptación de campo o Vs30. Rojo en TRS significa pocos onsets disponibles con este protocolo.</div>
<div class="cards">__CARDS__</div>
<div class="explain"><article><h2>¿Qué es un mini conjunto?</h2>
<p><strong>Una traza</strong> es un canal. <strong>Un registro</strong> reúne los canales de una adquisición.
<strong>Un sitio/perfil</strong> agrupa varios registros relacionados.</p>
<p>Oysand P1: r1–r4, offsets 10/15/20/30 m, 24 canales cada uno.
Chevremont: fuentes 0–60 m, 48 canales y 3 impactos apilados por archivo; los impactos originales no están disponibles.</p>
<p>Son dos sitios; los 11 registros no son muestras de 11 sitios independientes.</p></article>
<article><h2>¿Qué estamos comparando?</h2><p><strong>MASW:</strong> phase_shift + ridge_path frente a la curva
compuesta de Oysand, en frecuencias comunes con c &gt; 2·f·dx. Se reportan mediana absoluta y RMS en m/s.
La compuesta es del mismo sitio y no tiene etiquetas por registro.</p>
<p><strong>TRS:</strong> STA/LTA + AIC frente a test.sgt, __ANNOTATIONS__ anotaciones exclusivamente de la fuente 0 m.
__TRS_COMPARISON__ El reloj y la definición de llegada
siguen sin verificar; esa diferencia no certifica exactitud.</p></article></div>
<div class="toolbar"><label>Sitio <select id="site"><option value="">Todos</option><option>Oysand</option>
<option>Chevremont</option></select></label><label>Diagnóstico <select id="color"><option value="">Todos</option>
<option value="GREEN">Verde</option><option value="AMBER">Amarillo</option><option value="RED">Rojo</option>
<option value="GRAY">No evaluable</option></select></label><button id="print" type="button">Imprimir / guardar PDF</button>
<span id="visible" aria-live="polite">__RECORDS__ registros visibles</span></div>
<div class="table-wrap"><table><thead><tr><th>Registro / evidencia</th><th>Técnica / tamaño</th><th>Lectura</th>
<th>Proceso</th><th>Referencia</th><th>Diagnóstico</th></tr></thead><tbody>__ROWS__</tbody></table></div>
<h2>Cómo leer cada color</h2><p>Verde: dimensión comprobada. Amarillo: requiere revisión. Rojo: problema según
el criterio diagnóstico. Gris: evidencia insuficiente. Un faltante obligatorio impide un diagnóstico verde.</p>
<div class="explain"><article><strong>Lectura e integridad</strong><p>Hashes actuales, muestras finitas,
comprobaciones técnicas por registro y ausencia de canales cero/constantes. No certifica saturación,
respuesta instrumental, geometría o sincronización.</p></article>
<article><strong>Cobertura TRS: umbrales provisionales</strong><p>Onsets / todas las trazas, incluidas
abstenciones. Verde ≥__UPPER__ %; amarillo ≥__LOWER__ % y &lt;__UPPER__ %; rojo &lt;__LOWER__ %. Evalúa disponibilidad del procesamiento,
sin adjudicar exactitud o calidad de adquisición.</p></article>
<article><strong>Soporte MASW y referencias</strong><p>Soporte candidato vacío: rojo. Soporte parcial o modo
sin verificar: amarillo. Coincidencia con la compuesta sin calibración: amarillo; etiquetas ausentes o
tiempo TRS sin verificar: gris. No se adopta un umbral numérico de exactitud ni se interpreta err como sigma.</p></article></div>
<h2>Figuras de las pruebas</h2>__PLOTS__
<footer>Probe: __PROBE_DATE__. Generado: __REPORT_DATE__. __CHECKS__ comprobaciones técnicas pasan.
Originales y código del probe verificados al generar. Criterios: examples/field/quality_criteria.json.
Pendientes: metadatos de ingesta, calibración de campo G9, incertidumbres e inversión.<br>
Fuentes: MASWavesPy · 8ae34e9a112aad4e68df34f58efde7d500621a89;
SardineReborn · 2d1fdac70d94aa0baa62e82ae5319feacfc4a19b.</footer></main>
<script>
const site = document.getElementById('site'), color = document.getElementById('color');
function filter() { let count = 0; document.querySelectorAll('tbody tr').forEach(row => {
row.hidden = !!((site.value && row.dataset.site !== site.value) || (color.value && row.dataset.color !== color.value));
if (!row.hidden) count++; }); document.getElementById('visible').textContent = count + ' registros visibles'; }
site.addEventListener('change', filter); color.addEventListener('change', filter);
document.getElementById('print').addEventListener('click', () => {document.querySelectorAll('details').forEach(d => d.open = true);
window.print();});
</script></body></html>
""".replace("__CARDS__", cards)
        .replace("__ROWS__", "\n".join(rows))
        .replace("__PLOTS__", "\n".join(plots))
        .replace("__PROBE_DATE__", escape(report["probe_executed_at_utc"]))
        .replace("__REPORT_DATE__", escape(report["generated_at_utc"]))
        .replace("__CHECKS__", f"{report['checks_passed']}/{report['checks_total']}")
        .replace("__RECORDS__", str(report["summary"]["records"]))
        .replace("__SITES__", str(report["summary"]["sites"]))
        .replace("__TRACES__", str(report["summary"]["traces"]))
        .replace("__ANNOTATIONS__", str(total_annotations))
        .replace("__TRS_COMPARISON__", trs_comparison)
        .replace("__UPPER__", upper)
        .replace("__LOWER__", lower)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/field")
    args = parser.parse_args()
    evidence = ROOT / "evidence/field"
    results = json.loads((evidence / "results.json").read_text(encoding="utf-8"))
    criteria = json.loads((ROOT / "examples/field/quality_criteria.json").read_text(encoding="utf-8"))
    hashes = verify_evidence(ROOT, results)
    records = make_records(ROOT, results, criteria)
    report = {
        "schema_version": 1,
        "status": "EXPLORATORY_UNCALIBRATED",
        "eligible_for_acceptance": False,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "probe_executed_at_utc": results["executed_at_utc"],
        "criteria": criteria,
        "repositories": results["repositories"],
        "input_sha256": hashes,
        "checks_passed": sum(check["passed"] for check in results["checks"]),
        "checks_total": len(results["checks"]),
        "records": records,
        "summary": {
            "sites": 2,
            "records": len(records),
            "traces": sum(record["channels"] for record in records),
            "diagnostic_counts": dict(Counter(record["overall"] for record in records)),
        },
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "quality_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output / "quality_report.md").write_text(markdown_report(report), encoding="utf-8")
    (args.output / "quality_report.html").write_text(html_report(report, evidence), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    print(f"Report: {args.output / 'quality_report.html'}")


if __name__ == "__main__":
    main()
