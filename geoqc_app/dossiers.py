"""Bounded scientific detail views with digest-bound cursor pagination."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Literal
from uuid import UUID

from geoqc.core.evidence import canonical_hash
from geoqc_app.cursors import CursorSigner
from geoqc_app.errors import AppError
from geoqc_app.service import Actor, Reply, Service, one
from geoqc_app.storage import Blob

Collection = Literal["records", "points", "bands", "traces", "native-points", "arrivals", "branches", "qc-traces"]
DETAIL_SCHEMA = "geoqc-dossier-detail-1"
MAX_PAGE_BYTES = 256 * 1024
NATIVE_VECTORS = ("frequencies_hz", "velocities_ms", "coherence", "mode_labels", "mode_reasons", "n_active",
                  "point_mode_identity", "point_provenance", "point_reasons", "support", "velocity_kind")
UNITS = {"frequency_hz": "Hz", "frequencies_hz": "Hz", "f_bounds_hz": "Hz", "grid_velocity_ms": "m/s",
         "velocities_ms": "m/s", "signed_q_m_inv": "1/m", "competitor_q_m_inv": "1/m",
         "exclusion_radius_q_m_inv": "1/m", "sensitivity_velocities_ms": "m/s", "coherence": "1", "valid_fraction": "1"}


def encoded(document: dict[str, Any]) -> bytes:
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def representation(body: dict[str, Any]) -> Reply:
    if len(encoded(body)) > MAX_PAGE_BYTES:
        raise AppError(413, "DETAIL_ITEM_TOO_LARGE", "Un elemento excede el límite del detalle; consulte el JSON original")
    return Reply(body, etag='"detail-' + hashlib.sha256(encoded(body)).hexdigest() + '"')


def not_modified(value: str | None, etag: str | None) -> bool:
    if value is None or etag is None:
        return False
    return any(part.strip().removeprefix("W/") in (etag, "*") for part in value.split(","))


def record_summary(record: dict[str, Any], index: int) -> dict[str, Any]:
    usability = record["apparent_usability"]
    native = record["native_diagnostics"]
    return {
        "record_index": index, "shot_id": record["shot_id"], "amplitude_unit": record["amplitude_unit"],
        "trace_count": len(record["trace_observations"]),
        "native_diagnostics": {key: value for key, value in native.items() if key != "curves"},
        "native_curves": [{"curve_index": i, "direction": curve["direction"],
                           "point_count": len(curve["frequencies_hz"]),
                           "metadata": {key: value for key, value in curve.items()
                                        if key not in (*NATIVE_VECTORS, "band_controls", "near_geometry", "significance")}}
                          for i, curve in enumerate(native["curves"])],
        "apparent_usability": {key: value for key, value in usability.items() if key != "directions"},
        "directions": [{"direction": direction["direction"], "counts": direction["counts"],
                        "point_count": len(direction["points"]), "band_count": len(direction["bands"])}
                       for direction in usability["directions"]],
    }


def detail_page(document: dict[str, Any], dossier_id: UUID, signer: CursorSigner, *,
                collection: Collection = "records", record_index: int | None = None, cursor: str | None = None,
                limit: int = 50, direction: int | None = None,
                frequency_min_hz: float | None = None, frequency_max_hz: float | None = None) -> Reply:
    if document["schema_version"] == "app-trs-dossier-0.1":
        from geoqc_app.trs_details import project_trs
        return representation(project_trs(document, dossier_id, signer, collection=collection,
                              record_index=record_index, cursor=cursor, limit=limit, direction=direction,
                              frequency_min_hz=frequency_min_hz, frequency_max_hz=frequency_max_hz))
    if collection in ("arrivals", "branches", "qc-traces"):
        raise AppError(422, "MASW_COLLECTION_UNSUPPORTED", "Esta colección corresponde a TRS")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise AppError(422, "INVALID_DETAIL_LIMIT", "Límite requerido entre 1 y 100")
    if direction is not None and (type(direction) is not int or direction not in (-1, 1)):
        raise AppError(422, "INVALID_DIRECTION", "Dirección requerida -1 o 1")
    if any(value is not None and (not math.isfinite(value) or value < 0)
           for value in (frequency_min_hz, frequency_max_hz)):
        raise AppError(422, "INVALID_FREQUENCY_RANGE", "Frecuencias finitas no negativas requeridas")
    if frequency_min_hz is not None and frequency_max_hz is not None and frequency_min_hz > frequency_max_hz:
        raise AppError(422, "INVALID_FREQUENCY_RANGE", "Rango de frecuencias invertido")
    if collection in ("records", "traces") and any(value is not None for value in
                                                   (direction, frequency_min_hz, frequency_max_hz)):
        raise AppError(422, "INVALID_DETAIL_FILTER", "Esta colección no admite filtro de frecuencia o dirección")
    records = document["diagnostic_quality"]
    record = None
    if collection != "records":
        if type(record_index) is not int or not 0 <= record_index < len(records):
            raise AppError(404, "RECORD_NOT_FOUND", "Registro no encontrado en este dosier")
        record = records[record_index]
    binding = {"schema": DETAIL_SCHEMA, "dossier_id": str(dossier_id), "scientific_digest": document["scientific_digest"],
               "collection": collection, "record_index": record_index,
               "direction": direction, "frequency_min_hz": frequency_min_hz, "frequency_max_hz": frequency_max_hz}
    start = signer.decode(cursor, binding)

    def matches(frequency: float) -> bool:
        return ((frequency_min_hz is None or frequency >= frequency_min_hz)
                and (frequency_max_hz is None or frequency <= frequency_max_hz))

    items: list[dict[str, Any]] = []
    context: dict[str, Any] = {}
    if collection == "records":
        items = [record_summary(value, index) for index, value in enumerate(records)]
    elif record is not None:
        context = {"record_index": record_index, "shot_id": record["shot_id"], "amplitude_unit": record["amplitude_unit"],
                   "ridge_estimator": record["apparent_usability"]["ridge_estimator"],
                   "native_ridge_estimator": record["apparent_usability"]["native_ridge_estimator"],
                   "sensitivity_variant_order": record["apparent_usability"]["sensitivity_variant_order"],
                   "sensitivity_excluded_receiver_id": record["apparent_usability"]["sensitivity_excluded_receiver_id"],
                   "exclusions_do_not_identify_trigger": record["apparent_usability"]["exclusions_do_not_identify_trigger"],
                   "bin_counts_are_not_quality_percentages": record["apparent_usability"]["bin_counts_are_not_quality_percentages"]}
        if collection == "traces":
            items = record["trace_observations"]
        elif collection in ("points", "bands"):
            for group in record["apparent_usability"]["directions"]:
                if direction is not None and group["direction"] != direction:
                    continue
                for index, value in enumerate(group[collection]):
                    if collection == "points":
                        supported = matches(value["frequency_hz"])
                    else:
                        low, high = value["f_bounds_hz"]
                        supported = ((frequency_min_hz is None or high >= frequency_min_hz)
                                     and (frequency_max_hz is None or low <= frequency_max_hz))
                    if supported:
                        items.append({"direction": group["direction"], "index": index, "value": value})
        elif collection == "native-points":
            for curve_index, curve in enumerate(record["native_diagnostics"]["curves"]):
                if direction is not None and curve["direction"] != direction:
                    continue
                for index, frequency in enumerate(curve["frequencies_hz"]):
                    if matches(frequency):
                        nested = {name: {key: value[index] if isinstance(value, list) else value
                                         for key, value in curve[name].items()}
                                  for name in ("band_controls", "near_geometry", "significance")}
                        items.append({"curve_index": curve_index, "index": index, "direction": curve["direction"],
                                      "frequency_hz": frequency,
                                      "values": {key: curve[key][index] for key in NATIVE_VECTORS}, **nested})
    if start > len(items):
        raise AppError(422, "INVALID_DETAIL_CURSOR", "Posición fuera de la colección")
    selected = items[start:start + limit]
    while True:
        end = start + len(selected)
        body = {"detail_schema_version": DETAIL_SCHEMA, "dossier_id": str(dossier_id),
                "scientific_digest": document["scientific_digest"], "collection": collection, "context": context,
                "scope": document["scope"], "scientific_status": document["scientific_status"],
                "sufficiency": document["sufficiency"], "eligible_for_acceptance": document["eligible_for_acceptance"],
                "units": UNITS | ({"rms_ac_native": record["amplitude_unit"]} if record is not None else {}),
                "total_items": len(items), collection.replace("-", "_"): selected,
                "next_cursor": signer.encode(binding, end) if end < len(items) else None}
        if len(encoded(body)) <= MAX_PAGE_BYTES:
            return representation(body)
        if len(selected) <= 1:
            raise AppError(413, "DETAIL_ITEM_TOO_LARGE", "Un elemento excede el límite; consulte el JSON original")
        selected.pop()


class Dossiers:
    def __init__(self, service: Service) -> None:
        self.service = service
        self.signer = CursorSigner(service.store.cursor_key())

    def load(self, actor: Actor, dossier_id: UUID) -> tuple[dict[str, Any], dict[str, Any], UUID]:
        service = self.service
        with service.db.connect() as conn:
            dossier = service.resource(conn, actor, "dossiers", dossier_id)
            artifact = one(conn, "SELECT * FROM artifacts WHERE id=%s", (dossier["artifact_id"],))
            review = one(conn, "SELECT id FROM review_cases WHERE dossier_id=%s", (dossier_id,))
        if artifact["size_bytes"] > 64 * 1024**2:
            raise AppError(413, "DOSSIER_TOO_LARGE", "Dosier excede el alcance local")
        path = service.store.verify(Blob(artifact["storage_key"], artifact["sha256"], artifact["size_bytes"]))
        document = json.loads(path.read_bytes())
        if (document["scientific_digest"] != dossier["scientific_digest"] or canonical_hash(
                {key: value for key, value in document.items() if key != "scientific_digest"}) != dossier["scientific_digest"]):
            raise AppError(409, "DOSSIER_INTEGRITY", "Digest científico incompatible")
        if (document["schema_version"], document.get("method")) not in (
                ("app-masw-dossier-0.1", "MASW"), ("app-trs-dossier-0.1", "TRS")):
            raise AppError(422, "DETAIL_SCHEMA_UNSUPPORTED", "Esquema científico no soportado por esta vista")
        return dossier, document, review["id"]

    def header(self, actor: Actor, dossier_id: UUID) -> Reply:
        dossier, document, review_id = self.load(actor, dossier_id)
        with self.service.db.connect() as conn:
            latest = conn.execute(
                "SELECT latest.dossier_id FROM dossiers d JOIN processing_runs r ON r.id=d.run_id "
                "JOIN acquisitions a ON a.id=r.acquisition_id "
                "JOIN processing_runs latest ON latest.id=a.current_run_id "
                "WHERE d.id=%s AND latest.state='SUCCEEDED'", (dossier_id,)).fetchone()
        return representation({"id": str(dossier_id), "scientific_digest": dossier["scientific_digest"],
                               "current_dossier_id": str(latest["dossier_id"]) if latest and latest["dossier_id"] else None,
                               "review_id": str(review_id), "manifest": dossier["manifest"],
                               "summary": {key: document[key] for key in (
                                   "schema_version", "method", "scope", "scientific_status", "missing_evidence",
                                   "sufficiency", "eligible_for_acceptance")}
                               | ({"trace_qc_assessment": document["trace_qc_assessment"]}
                                  if "trace_qc_assessment" in document else {})
                               | ({"operational_assessment": document["operational_assessment"]}
                                  if "operational_assessment" in document else {})})

    def page(self, actor: Actor, dossier_id: UUID, *, collection: Collection = "records", record_index: int | None = None,
             cursor: str | None = None, limit: int = 50, direction: int | None = None,
             frequency_min_hz: float | None = None, frequency_max_hz: float | None = None) -> Reply:
        _, document, _ = self.load(actor, dossier_id)
        return detail_page(document, dossier_id, self.signer, collection=collection, record_index=record_index,
                           cursor=cursor, limit=limit, direction=direction,
                           frequency_min_hz=frequency_min_hz, frequency_max_hz=frequency_max_hz)
