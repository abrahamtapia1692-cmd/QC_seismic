"""Un Shot requiere fuente, receptores, geometría y referencia temporal verificadas."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import ValidationError

from geoqc.core.config import unique_json_pairs
from geoqc.core.models import Geometry, IngestFailure, Shot
from geoqc.io.binary import WaveformFile, parse_seg2, parse_segy
from geoqc.io.contracts import IngestContext
from geoqc.io.errors import IngestError
from geoqc.io.geometry import compare_geometry


def _header_geometry(decoded: WaveformFile, context: IngestContext) -> Geometry | None:
    if any(coordinate is None for coordinate in decoded.coordinates):
        return None
    coordinates = np.asarray(decoded.coordinates, dtype=np.float64)
    if context.header_coordinate_uncertainty_m is None or not context.header_crs:
        return None
    if not np.all(coordinates[:, 3:] == coordinates[0, 3:]):
        raise IngestError("GEOMETRY_INCONSISTENT", "Las trazas no pertenecen a una misma posición de fuente")
    return Geometry(
        xr=coordinates[:, 0],
        yr=coordinates[:, 1],
        zr=coordinates[:, 2],
        xs=coordinates[0, 3],
        ys=coordinates[0, 4],
        zs=coordinates[0, 5],
        uncertainty_m=context.header_coordinate_uncertainty_m,
        crs=context.header_crs,
        provenance=("SEG-Y coordinates/scalars/measurement_system", context.provenance),
    )


def read_shot(path: Path, *, sidecar: Path | None = None) -> Shot:
    try:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if not raw:
            raise IngestError("EMPTY_FILE", "Archivo vacío", "REEXPORT_OR_RECOVER")
        decoded = parse_seg2(raw) if raw[:2] in (b"\x55\x3a", b"\x3a\x55") else parse_segy(raw)
        metadata_path = sidecar if sidecar is not None else path.with_suffix(path.suffix + ".json")
        if not metadata_path.exists():
            raise IngestError(
                "METADATA_MISSING",
                "Se requiere sidecar con adquisición/geometría/tiempo explícitos",
                "SUPPLY_ACQUISITION_SIDECAR",
            )
        metadata_raw = metadata_path.read_bytes()
        metadata = json.loads(metadata_raw, object_pairs_hook=unique_json_pairs)
        if (
            isinstance(metadata, dict)
            and isinstance(metadata.get("acquisition"), dict)
            and "amplitude_unit" not in metadata["acquisition"]
        ):
            raise IngestError(
                "METADATA_MISSING",
                "Unidad de amplitud ausente; no se infiere desde muestras float",
                "DECLARE_AMPLITUDE_UNIT",
            )
        context = IngestContext.model_validate(metadata)
        if context.waveform_sha256 is not None and context.waveform_sha256 != digest:
            raise IngestError(
                "SIDECAR_MISMATCH", "SHA-256 del waveform no corresponde al sidecar", "MATCH_SIDECAR_TO_WAVEFORM"
            )
        if not context.provenance.strip():
            raise IngestError("METADATA_MISSING", "La convención de adquisición requiere procedencia")
        n = len(decoded.traces)
        if len(context.acquisition.receiver_ids) != n:
            raise IngestError("METADATA_INCONSISTENT", "Receptores físicos no coinciden con trazas")
        header_geometry = _header_geometry(decoded, context)
        geometry = header_geometry if context.geometry_policy == "HEADER" else context.geometry
        if geometry is None:
            raise IngestError(
                "GEOMETRY_MISSING",
                "Falta geometría SI/CRS/incertidumbre según precedencia declarada",
                "SUPPLY_SURVEY_AND_PRECEDENCE",
            )
        if context.time_reference == "SOURCE_INITIATION_VERIFIED":
            if any(delay is None for delay in decoded.t0_s):
                raise IngestError(
                    "TIME_REFERENCE_MISSING", "DELAY ausente; no se inventa t0=0", "VERIFY_TRIGGER_CONVENTION"
                )
            t0 = tuple(float(delay) for delay in decoded.t0_s if delay is not None)
        else:
            if context.t0_s is None:
                raise IngestError("TIME_REFERENCE_MISSING", "La autoridad sidecar requiere t0_s por canal")
            t0 = context.t0_s
        ns = max(trace.size for trace in decoded.traces)
        data, mask = np.full((n, ns), np.nan), np.zeros((n, ns), dtype=bool)
        reasons = []
        for j, trace in enumerate(decoded.traces):
            data[j, : trace.size] = trace
            mask[j, : trace.size] = np.isfinite(trace)
            reason = []
            if trace.size != ns:
                reason.append("PADDED_LENGTH")
            if not np.all(np.isfinite(trace)):
                reason.append("NONFINITE_SAMPLE")
            reasons.append(";".join(reason))
        if context.valid_mask is not None:
            if context.valid_mask.shape != mask.shape or context.mask_reasons is None or len(context.mask_reasons) != n:
                raise IngestError("MASK_INCONSISTENT", "Máscara/motivos de sidecar incompatibles con waveform")
            mask &= context.valid_mask
            reasons = [
                ";".join(filter(None, (reason, extra)))
                for reason, extra in zip(reasons, context.mask_reasons, strict=True)
            ]
        headers: dict[str, Any] = dict(decoded.headers)
        headers["context"] = context.model_dump(mode="json", exclude={"valid_mask"})
        headers["trace_sample_counts"] = [int(trace.size) for trace in decoded.traces]
        headers["geometry_comparison"] = compare_geometry(geometry, context.geometry, tolerance_m=0.1).model_dump(
            mode="json"
        )
        return Shot(
            id=context.shot_id,
            data=data,
            valid_mask=mask,
            mask_reasons=tuple(reasons),
            dt_s=decoded.dt_s,
            t0_s=t0,
            geometry=geometry,
            acquisition=context.acquisition,
            input_hashes=(digest, hashlib.sha256(metadata_raw).hexdigest()),
            headers_json=json.dumps(headers, ensure_ascii=False, allow_nan=False),
        )
    except IngestError:
        raise
    except OSError as exc:
        raise IngestError("FILE_ACCESS", str(exc), "LOCATE_OR_UNLOCK_FILE") from exc
    except (ValueError, TypeError, IndexError, OverflowError, ValidationError) as exc:
        raise IngestError("INVALID_CONTENT", str(exc), "CHECK_HEADER_UNITS_AND_SIDECAR") from exc


def try_read_shot(path: Path, *, sidecar: Path | None = None) -> Shot | IngestFailure:
    try:
        return read_shot(path, sidecar=sidecar)
    except IngestError as exc:
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            digest = None
        return exc.failure(path, digest)
