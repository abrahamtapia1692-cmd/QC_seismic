"""Render a pinned scientific snapshot; never run or alter the scientific engine."""
from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import sys
import textwrap
from collections.abc import Iterator
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from geoqc.core.evidence import canonical_hash
from geoqc_app.errors import AppError
from geoqc_app.quality_exports import resource_hashes
from geoqc_app.storage import ArtifactStore, Blob

MEDIA_TYPES = {"CSV": "text/csv", "HTML": "text/html", "PDF": "application/pdf"}
RENDERER_VERSION = "geoqc-export-1"
WARNING = "DRAFT - DIAGNOSTIC ONLY - NOT_DEMONSTRATED - eligible_for_acceptance=false"


def renderer_reference(format: str) -> dict[str, Any]:
    dependencies: dict[str, str | None] = {}
    if format == "PDF":
        try:
            dependencies["reportlab"] = version("reportlab")
        except PackageNotFoundError:
            dependencies["reportlab"] = None
    return {"version": RENDERER_VERSION, "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "quality_code_sha256": hashlib.sha256(Path(__file__).with_name("quality_exports.py").read_bytes()).hexdigest(),
            "projection_code_sha256": hashlib.sha256(Path(__file__).with_name("trs_details.py").read_bytes()).hexdigest(),
            "resources": resource_hashes() if format in ("HTML", "PDF") else {},
            "dependencies": dependencies}


def validate_document(document: dict[str, Any]) -> None:
    body = {key: value for key, value in document.items() if key != "scientific_digest"}
    if canonical_hash(body) != document["scientific_digest"]:
        raise AppError(409, "EXPORT_SOURCE_INTEGRITY", "Digest del dosier incompatible")
    if (document["schema_version"] not in ("app-masw-dossier-0.1", "app-trs-dossier-0.1")
            or document["eligible_for_acceptance"] is not False
            or document["sufficiency"] != {"status": "NOT_DEMONSTRATED"}):
        raise AppError(422, "EXPORT_SCHEMA_UNSUPPORTED", "Dosier fuera del perfil diagnóstico local")


def leaves(value: Any, path: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(value, dict) and value:
        for key in sorted(value):
            escaped = key.replace("~", "~0").replace("/", "~1")
            yield from leaves(value[key], path + "/" + escaped)
    elif isinstance(value, list) and value:
        for index, item in enumerate(value):
            yield from leaves(item, path + "/" + str(index))
    else:
        yield path, json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def trace_quality_summary(document: dict[str, Any]) -> list[str]:
    """Readable projection of published assessments; never classify again on export."""
    if document.get("method") != "TRS":
        return []
    lines = ["Calificación por traza y tendido (diagnóstica)"]

    def assessment(label: str, value: dict[str, Any]) -> None:
        low, high = value["good_percent_bounds"]
        lines.extend([f"{label}: {value['grade']} | {value['total_traces']} trazas",
                      f"Buenas: intervalo {low:g}-{high:g} % | "
                      f"Fallas demostradas: {value['demonstrated_bad_traces']} | "
                      f"Evidencia pendiente: {value['pending_traces']}", value["reason"]])

    if document.get("trace_qc_assessment"):
        assessment("Conjunto de registros", document["trace_qc_assessment"])
    if document.get("operational_assessment"):
        a = document["operational_assessment"]
        lines.extend([f"Calificación diagnóstica condicional del conjunto: {a['grade']}",
                      f"Cobertura media de comprobaciones: {100 * a['mean_coverage_fraction']:.2f} %; no es confianza estadística"])
    lines.append("Cortes: BUENA >=90 %; REGULAR >=75 % y <90 %; MALA <75 % de buenas.")
    lines.append("La evidencia pendiente conserva un intervalo; el picker no califica la adquisición.")
    for record in document["diagnostic_quality"]:
        lines.append("Registro / tendido: " + record["shot_id"])
        qc = record.get("trace_qc")
        if qc is None:
            lines.append("Dosier histórico sin QC por traza; requiere otra ejecución para incorporarlo.")
            continue
        assessment("Evaluación del registro", qc["data_assessment"])
        lines.append("Protocolo QC: " + qc["protocol_source"])
        for trace in qc["traces"]:
            quality = trace["quality"]
            lines.append(f"{trace['receiver_id']}: {quality['assessment_grade']} | "
                         + "; ".join(quality["reasons"]))
            if trace.get("operational_quality"):
                op = trace["operational_quality"]
                lines.append(f"{trace['receiver_id']} diagnóstica: {op['grade']} | " + "; ".join(op["reasons"]))
        lines.append("Cobertura metodológica: " + "; ".join(
            f"{key}: {value}" for key, value in qc["methodology"].items()))
    return lines


def render_export(document: dict[str, Any], format: str) -> bytes:
    validate_document(document)
    method = "TRS" if document["schema_version"] == "app-trs-dossier-0.1" else "MASW"
    if format == "CSV":
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(["scientific_digest", "json_pointer", "value_json"])
        for path, value in leaves(document):
            writer.writerow([document["scientific_digest"], path, value])
        return stream.getvalue().encode("utf-8")
    if format == "HTML":
        content = html.escape(json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True))
        summary = trace_quality_summary(document)
        quality_html = ("<section aria-label='Calificación QC'>" + "".join(
            "<p>" + html.escape(line) + "</p>" for line in summary) + "</section>") if summary else ""
        if method == "TRS" and any(r.get("trace_qc") for r in document["diagnostic_quality"]):
            from geoqc_app.quality_exports import quality_html as render_quality_html
            return render_quality_html(document, WARNING, quality_html)
        description = ("Los primeros arribos, abstenciones y ramas conservan sus campos de origen."
                       if method == "TRS" else
                       "Las curvas nativas refinadas y la usabilidad de rejilla conservan sus campos de origen.")
        return ("<!doctype html><html lang='es'><meta charset='utf-8'>"
                "<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; style-src 'unsafe-inline'\">"
                "<title>GeoQC - dosier " + method + "</title><style>body{font:16px sans-serif;max-width:1100px;margin:2rem auto}"
                "pre{white-space:pre-wrap;overflow-wrap:anywhere}aside{padding:1rem;background:#fff0c2}</style>"
                "<h1>GeoQC - dosier " + method + "</h1><aside>" + WARNING + "</aside>"
                "<p>Snapshot científico completo. La revisión humana se consulta por separado. "
                + description + "</p>" + quality_html + "<pre>" + content + "</pre></html>").encode("utf-8")
    if format == "PDF":
        # Lazy dependency: neither scientific computation nor CSV/HTML require ReportLab.
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen.canvas import Canvas

        stream_bytes = io.BytesIO()
        canvas = Canvas(stream_bytes, pagesize=A4, pageCompression=1, invariant=1)
        canvas.setTitle("GeoQC - " + method + " diagnostic scientific snapshot")
        canvas.setAuthor("GeoQC")
        if method == "TRS" and any(r.get("trace_qc") for r in document["diagnostic_quality"]):
            from geoqc_app.quality_exports import draw_quality_pdf
            draw_quality_pdf(canvas, document, WARNING)
            canvas.save()
            return stream_bytes.getvalue()
        # Escaped Unicode keeps arbitrary identifiers lossless without assuming local fonts.
        content = json.dumps(document, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True)
        lines = [line for original in [*trace_quality_summary(document), *content.splitlines()] for line in
                 (textwrap.wrap(original, width=108, replace_whitespace=False, drop_whitespace=False) or [""])]
        page = 0
        for start in range(0, len(lines), 66):
            page += 1
            canvas.setFont("Helvetica", 9)
            canvas.drawString(32, 815, "GeoQC - " + method + " scientific snapshot - page " + str(page))
            canvas.setFont("Helvetica", 7)
            canvas.drawString(32, 800, WARNING)
            canvas.drawString(32, 789, "scientific_digest: " + document["scientific_digest"])
            canvas.drawString(32, 778, "Scientific JSON only; human review is separate. Unicode uses JSON escapes.")
            text = canvas.beginText(32, 760)
            text.setFont("Courier", 8)
            text.setLeading(10.5)
            for line in lines[start:start + 66]:
                text.textLine(line)
            canvas.drawText(text)
            canvas.showPage()
        canvas.save()
        return stream_bytes.getvalue()
    raise ValueError("Formato de exportación no soportado")


def main(input_path: Path) -> int:
    folder = input_path.parent
    try:
        payload = json.loads(input_path.read_bytes())
        format = payload["format"]
        if renderer_reference(format) != payload["renderer_reference"]:
            raise AppError(409, "EXPORT_RENDERER_MISMATCH", "El renderizador cambió")
        store = ArtifactStore(Path(payload["storage_root"]))
        source = Blob(**payload["source"])
        document = json.loads(store.verify(source).read_bytes())
        if document["scientific_digest"] != payload["scientific_digest"]:
            raise AppError(409, "EXPORT_SOURCE_INTEGRITY", "Dosier incompatible")
        content = render_export(document, format)
        store.verify(source)
        if renderer_reference(format) != payload["renderer_reference"]:
            raise AppError(409, "EXPORT_RENDERER_MISMATCH", "El renderizador cambió durante la exportación")
        if len(content) > 64 * 1024**2:
            raise AppError(422, "EXPORT_TOO_LARGE", "Exportación excede el límite local")
        (folder / "rendered.bin").write_bytes(content)
        outcome: dict[str, Any] = {"state": "READY", "sha256": hashlib.sha256(content).hexdigest()}
    except AppError as exc:
        outcome = {"state": "FAILED", "code": exc.code}
    except ImportError:
        outcome = {"state": "FAILED", "code": "EXPORT_DEPENDENCY_MISSING"}
    except OSError:
        outcome = {"state": "FAILED", "code": "EXPORT_IO"}
    except (ValueError, KeyError, TypeError):
        outcome = {"state": "FAILED", "code": "EXPORT_INVALID_SOURCE"}
    temporary = folder / "outcome.writing"
    temporary.write_text(json.dumps(outcome, allow_nan=False), encoding="utf-8")
    temporary.replace(folder / "outcome.json")
    return 0 if outcome["state"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
