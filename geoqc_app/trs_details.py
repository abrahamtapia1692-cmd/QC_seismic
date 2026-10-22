"""Bounded TRS projections preserve native first-arrival and branch values."""
from __future__ import annotations

from collections import Counter
from typing import Any
from uuid import UUID

import numpy as np

from geoqc_app.cursors import CursorSigner
from geoqc_app.errors import AppError


def trace_projection(trace: dict[str, Any]) -> dict[str, Any]:
    """Bound spectra for display; the frozen artifact retains full native vectors."""
    out = dict(trace)
    noise = dict(trace.get("noise_diagnostics", {}))
    spectrum = noise.pop("spectrum", None)
    if spectrum:
        f, p = spectrum["frequency_hz"], spectrum["noise_psd_native_units"]
        indices = [int(group[np.argmax([p[i] for i in group])])
                   for group in np.array_split(np.arange(len(f)), min(512, len(f))) if len(group)]
        noise["spectrum_preview"] = {"method": "MAX_PER_BIN_DISPLAY_ONLY", "native_bins": len(f),
                                     "frequency_hz": [f[i] for i in indices],
                                     "noise_psd_native_units": [p[i] for i in indices]}
    if noise:
        out["noise_diagnostics"] = noise
    if "psd" in out:
        out["psd"] = {k: v for k, v in out["psd"].items() if not isinstance(v, list)}
    return out


def record_projection(record: dict[str, Any], index: int) -> dict[str, Any]:
    """Same bounded record context for the API and standalone HTML report."""
    r = record
    return {"record_index": index, "shot_id": r["shot_id"], "amplitude_unit": r["amplitude_unit"],
            "arrival_count": len(r["diagnostics"]["picks"]),
            "arrival_status_counts": dict(Counter(p["arrival"]["confidence"] for p in r["diagnostics"]["picks"])),
            "missing_requirements": r["diagnostics"]["missing_requirement_ids"],
            "geometry": r["geometry"], "acquisition": r["acquisition"],
            "trace_qc": ({k: v for k, v in r["trace_qc"].items() if k != "traces"}
                         | {"assessment_counts": dict(Counter(
                             t["quality"]["assessment_grade"] for t in r["trace_qc"]["traces"]))}
                         if r.get("trace_qc") else {})}


def project_trs(document: dict[str, Any], dossier_id: UUID, signer: CursorSigner, *, collection: str,
                record_index: int | None, cursor: str | None, limit: int, direction: int | None,
                frequency_min_hz: float | None, frequency_max_hz: float | None) -> dict[str, Any]:
    from geoqc_app.dossiers import MAX_PAGE_BYTES, encoded
    if collection not in ("records", "arrivals", "branches", "qc-traces"):
        raise AppError(422, "TRS_COLLECTION_UNSUPPORTED", "TRS admite registros, llegadas, ramas y QC por traza")
    if direction is not None or frequency_min_hz is not None or frequency_max_hz is not None:
        raise AppError(422, "TRS_FILTER_UNSUPPORTED", "Los filtros de frecuencia/dirección son de MASW")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise AppError(422, "INVALID_DETAIL_LIMIT", "Límite requerido entre 1 y 100")
    records = document["diagnostic_quality"]
    context = {}
    if collection == "records":
        items = [record_projection(r, i) for i, r in enumerate(records)]
    else:
        if type(record_index) is not int or not 0 <= record_index < len(records):
            raise AppError(404, "RECORD_NOT_FOUND", "Registro TRS no encontrado")
        record = records[record_index]
        items = ([trace_projection(t) for t in record.get("trace_qc", {}).get("traces", [])]
                 if collection == "qc-traces" else
                 record["diagnostics"]["picks" if collection == "arrivals" else "branches"])
        context = {"record_index": record_index, "shot_id": record["shot_id"],
                   "amplitude_unit": record["amplitude_unit"], "protocol": document["protocol"]}
    binding = {"schema": "geoqc-trs-detail-1", "dossier_id": str(dossier_id),
               "scientific_digest": document["scientific_digest"], "collection": collection,
               "record_index": record_index}
    start = signer.decode(cursor, binding)
    if start > len(items):
        raise AppError(422, "INVALID_DETAIL_CURSOR", "Posición fuera de colección TRS")
    selected = items[start:start+limit]
    while True:
        end = start + len(selected)
        body = {"detail_schema_version": "geoqc-trs-detail-1", "dossier_id": str(dossier_id),
                "scientific_digest": document["scientific_digest"], "collection": collection,
                "context": context, "units": {"offset_m": "m", "onset_s": "s", "sigma_s": "s", "bias_s": "s"}
                | ({"dt_s": "s", "frequency_hz": "Hz", "snr": "dB", "clip": "1",
                    "valid_fraction": "1", "waveform_amplitude": record["amplitude_unit"]}
                   if collection == "qc-traces" else {}),
                "scope": document["scope"], "scientific_status": document["scientific_status"],
                "sufficiency": document["sufficiency"], "eligible_for_acceptance": False,
                "total_items": len(items), collection.replace("-", "_"): selected,
                "next_cursor": signer.encode(binding, end) if end < len(items) else None}
        if len(encoded(body)) <= MAX_PAGE_BYTES:
            return body
        if len(selected) <= 1:
            raise AppError(413, "DETAIL_ITEM_TOO_LARGE", "Elemento TRS excede el límite del detalle")
        selected.pop()
