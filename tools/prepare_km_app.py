"""Inventory KM SEG-2 records; convert only with explicitly reviewed metadata."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoqc.io.binary import parse_seg2  # noqa: E402
from geoqc.io.contracts import IngestContext  # noqa: E402
from geoqc.io.readers import read_shot  # noqa: E402
from geoqc.io.writers import write_segy  # noqa: E402
from geoqc.masw.contracts import MASWProtocol  # noqa: E402
from geoqc_app.calculate import preflight_segy  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_document(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as file:
        file.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def describe(path: Path, root: Path) -> dict[str, Any]:
    waveform = parse_seg2(path.read_bytes())
    headers = waveform.headers["trace_headers"]
    return {
        "path": path.relative_to(root).as_posix(), "sha256": sha256(path),
        "bytes": path.stat().st_size, "format": "SEG-2", "channels": len(waveform.traces),
        "samples_per_trace": [trace.size for trace in waveform.traces],
        "dt_s": list(waveform.dt_s), "delay_s": list(waveform.t0_s),
        "file_header": waveform.headers["file_header"],
        "receiver_location_raw": [header.get("RECEIVER_LOCATION") for header in headers],
        "source_location_raw": [header.get("SOURCE_LOCATION") for header in headers],
        "channel_number_raw": [header.get("CHANNEL_NUMBER") for header in headers],
        "descaling_factor_raw": [header.get("DESCALING_FACTOR") for header in headers],
        "stack_raw": [header.get("STACK") for header in headers],
        "category": "PASSIVE_MAM" if "MAM" in path.parts else "ACTIVE_TRS_FOLDER",
        "app_upload_ready": False,
    }


def template(record: dict[str, Any]) -> dict[str, Any]:
    n = record["channels"]
    return {
        "status": "BLOCKED_PENDING_ACQUISITION_METADATA", "confirmed": False, "review_notes": None,
        "source_file": record["path"], "source_sha256": record["sha256"],
        "header_candidates_not_validated": record,
        "context": {
            "shot_id": Path(record["path"]).stem, "waveform_sha256": record["sha256"],
            "acquisition": {
                "technique": None, "wave": None, "component": None, "receiver_ids": None,
                "source_type": None, "amplitude_unit": None, "trigger_ref": None,
                "stack_count": None, "stack_kind": "UNKNOWN",
            },
            "geometry_policy": "SIDECAR",
            "geometry": {"xr": None, "yr": None, "zr": None, "xs": None, "ys": None, "zs": None,
                         "uncertainty_m": [None] * n, "crs": None, "provenance": []},
            "time_reference": None, "t0_s": None, "provenance": None,
        },
    }


def prepare(root: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise ValueError("Elija un directorio nuevo; no se sobrescriben preparaciones")
    records, notes = [], []
    for site in sorted(root.glob("KM *")):
        if not site.is_dir():
            continue
        for path in sorted(site.rglob("*.sg2")):
            records.append(describe(path, root))
        for path in sorted(site.rglob("*.txt")):
            raw = path.read_bytes()
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("cp1252")
            notes.append({"path": path.relative_to(root).as_posix(), "sha256": sha256(path), "text": text})
    if not records:
        raise ValueError("No se encontraron registros KM SEG-2")
    output.mkdir(parents=True)
    selected = []
    for site_name in sorted({Path(record["path"]).parts[0] for record in records}):
        record = next(record for record in records if Path(record["path"]).parts[0] == site_name
                      and record["category"] == "ACTIVE_TRS_FOLDER" and "F1" in Path(record["path"]).parts)
        slug = site_name.replace(" ", "_").replace("+", "_")
        write_document(output / f"{slug}_F1.metadata.template.json", template(record))
        # Signal windows are half-open; include the last sample and keep exact FFT bins.
        end = min(count * dt for count, dt in zip(record["samples_per_trace"], record["dt_s"], strict=True))
        protocol = MASWProtocol(
            signal={"start_s": 0, "end_s": end}, frequencies_hz=tuple(range(8, 82, 2)),
            velocities_ms=tuple(range(100, 1001, 10)), domain_id=slug + "-EXPLORATORY",
            provenance="Exploratory proposed grid/window; not field calibration or validated frequency band. "
                       "Review against acquisition metadata before use.",
        )
        write_document(output / f"{slug}_F1.protocol.draft.json", protocol.model_dump(mode="json"))
        selected.append({"site": site_name, "source": record["path"], "slug": slug})
    result = {"status": "NOT_READY_FOR_KM_UPLOAD", "record_count": len(records),
              "active_count": sum(record["category"] == "ACTIVE_TRS_FOLDER" for record in records),
              "mam_count": sum(record["category"] == "PASSIVE_MAM" for record in records),
              "notes": notes, "selected": selected, "records": records,
              "missing": ["Confirmed technique/wave/component/source and receiver mapping",
                          "Amplitude unit and treatment of DESCALING_FACTOR",
                          "Source-relative timing/trigger convention",
                          "Survey geometry, coordinate system, uncertainty and topography",
                          "Stack semantics; header STACK=0 is not a verified shot count"]}
    write_document(output / "inventory.json", result)
    return result


def convert(metadata: Path, output: Path, root: Path = ROOT, *, technique: str = "MASW") -> None:
    document = json.loads(metadata.read_bytes())
    if document.get("confirmed") is not True or not str(document.get("review_notes") or "").strip():
        raise ValueError("Complete y confirme metadatos con procedencia; la plantilla no es un sidecar válido")
    source = root / document["source_file"]
    if sha256(source) != document["source_sha256"]:
        raise ValueError("El original cambió; hash SEG-2 incompatible")
    context = IngestContext.model_validate(document["context"])
    if context.waveform_sha256 != document["source_sha256"]:
        raise ValueError("El sidecar debe identificar el hash del original SEG-2")
    if technique not in ("MASW", "TRS") or context.acquisition.technique != technique:
        raise ValueError(f"Conversión solicitada {technique}; sidecar declara {context.acquisition.technique}. "
                         "No se cambia una declaración TRS/MASW automáticamente")
    if "MAM" in source.parts:
        raise ValueError("MAM pasivo queda fuera del contrato de esta aplicación")
    shot = read_shot(source, sidecar=_context_file(metadata, context))
    if output.exists() or output.with_suffix(output.suffix + ".json").exists():
        raise ValueError("Elija una salida nueva")
    # Check representability before generating a pair that the app cannot ingest.
    if any(abs(dt / 1e-6 - round(dt / 1e-6)) > 1e-8 for dt in shot.dt_s):
        raise ValueError("El intervalo SEG-2 no se representa exactamente en microsegundos SEG-Y")
    if any(abs(t0 / 0.001 - round(t0 / 0.001)) > 1e-8 for t0 in shot.t0_s):
        raise ValueError("El tiempo inicial no se representa exactamente en milisegundos SEG-Y")
    if not 3 <= shot.data.shape[0] <= 64 or shot.data.shape[1] > 65535:
        raise ValueError("Dimensiones fuera del contrato SEG-Y local")
    if 3600 + shot.data.shape[0] * (240 + 4 * shot.data.shape[1]) > 32 * 1024**2:
        raise ValueError("La salida excedería 32 MiB")
    with np.errstate(over="ignore"):
        representable = shot.data.astype(np.float32).astype(np.float64)
    if not np.array_equal(shot.data, representable, equal_nan=True):
        raise ValueError("IEEE float32 no conserva las muestras exactamente; conversión bloqueada")
    output.parent.mkdir(parents=True, exist_ok=True)
    write_segy(output, shot)
    preflight_segy(output)
    restored = read_shot(output)
    if not np.array_equal(shot.data, restored.data, equal_nan=True):
        raise ValueError("Conversión IEEE no exacta; no usar esta salida sin evaluar la cuantización")


def _context_file(metadata: Path, context: IngestContext) -> Path:
    """Keep the reviewed context as provenance; never overwrite a raw-file sidecar."""
    destination = metadata.with_suffix(".reviewed-sidecar.json")
    content = context.model_dump(mode="json")
    if destination.exists():
        if json.loads(destination.read_bytes()) != content:
            raise ValueError("Ya existe otro contexto revisado; utilice un archivo de metadatos nuevo")
    else:
        write_document(destination, content)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--output", type=Path, required=True)
    conversion = sub.add_parser("convert")
    conversion.add_argument("--metadata", type=Path, required=True)
    conversion.add_argument("--output", type=Path, required=True)
    conversion.add_argument("--technique", choices=("MASW", "TRS"), default="MASW")
    args = parser.parse_args()
    if args.command == "inspect":
        result = prepare(ROOT, args.output)
        print(f"{result['record_count']} registros; {result['active_count']} activos, {result['mam_count']} MAM. "
              f"Plantillas pendientes de confirmación en {args.output}")
    else:
        convert(args.metadata, args.output, technique=args.technique)
        print(f"SEG-Y y sidecar generados y releídos: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
