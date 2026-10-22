"""Isolated scientific child; only the trusted worker constructs its input paths."""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path
from typing import Any

from geoqc.core.models import Shot
from geoqc.io.errors import IngestError
from geoqc.io.readers import read_shot
from geoqc.masw.adapter import (
    EngineReference,
    MASWAdapterInput,
    ReceiverExclusion,
    build_masw_dossier,
    capture_engine_reference,
)
from geoqc.masw.contracts import MASWProtocol
from geoqc.masw.diagnostic_quality import UsabilityPolicy
from geoqc.qc.adapter import TraceQCRequest
from geoqc.trs.adapter import build_trs_dossier
from geoqc.trs.contracts import TRSProtocol
from geoqc_app.errors import AppError
from geoqc_app.storage import ArtifactStore, Blob


def write_json(path: Path, content: Any) -> None:
    temporary = path.with_suffix(".writing")
    temporary.write_text(json.dumps(content, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def preflight_segy(path: Path) -> None:
    """Bound trace dimensions before the scientific reader allocates arrays."""
    size = path.stat().st_size
    if size > 32 * 1024**2:
        raise AppError(422, "INPUT_LIMIT", "Waveform excede el límite local")
    with path.open("rb") as stream:
        header = stream.read(3600)
        if len(header) < 3600:
            raise AppError(422, "FORMAT_UNSUPPORTED", "Cabecera SEG-Y incompleta")
        candidates = [endian for endian in (">", "<")
                      if struct.unpack_from(endian + "H", header, 3224)[0] in (1, 5)
                      and struct.unpack_from(endian + "H", header, 3500)[0] in (0, 256)]
        if len(candidates) != 1:
            raise AppError(422, "FORMAT_UNSUPPORTED", "SEG-Y rev0/1 requerido")
        endian = candidates[0]
        extended = struct.unpack_from(endian + "h", header, 3504)[0]
        if extended < 0:
            raise AppError(422, "FORMAT_UNSUPPORTED", "Conteo de cabeceras extendidas no soportado")
        cursor, channels = 3600 + extended * 3200, 0
        while cursor < size:
            stream.seek(cursor)
            trace = stream.read(240)
            if len(trace) != 240:
                raise AppError(422, "TRUNCATED", "Cabecera de traza incompleta")
            samples = struct.unpack_from(endian + "H", trace, 114)[0]
            channels += 1
            if channels > 64 or not 0 < samples <= 65536:
                raise AppError(422, "INPUT_LIMIT", "Dimensiones fuera del alcance local")
            cursor += 240 + 4 * samples
        if cursor != size:
            raise AppError(422, "TRUNCATED", "Muestras incompletas")
        if channels < 3:
            raise AppError(422, "INPUT_LIMIT", "El perfil local requiere al menos tres canales")


def calculate(input_path: Path) -> int:
    folder = input_path.parent
    try:
        payload = json.loads(input_path.read_bytes())
        store = ArtifactStore(Path(payload["storage_root"]))
        specification = payload["specification"]
        reference = capture_engine_reference()
        if reference.model_dump(mode="json") != specification["engine_reference"]:
            raise AppError(409, "ENGINE_MISMATCH", "La ejecución requiere otra versión de motor")
        shots = []
        for record in payload["shots"]:
            waveform = store.verify(Blob(**record["waveform"]))
            sidecar = store.verify(Blob(**record["sidecar"]))
            preflight_segy(waveform)
            shots.append(read_shot(waveform, sidecar=sidecar))
        write_json(folder / "phase.json", {"phase": "RUNNING"})
        if specification.get("technique", "MASW") == "TRS":
            document = build_trs_dossier(tuple(shots), TRSProtocol.model_validate(specification["protocol"]),
                                         payload["revision_id"], reference.model_dump(mode="json"),
                                         TraceQCRequest.model_validate(specification["trace_qc"])
                                         if specification.get("trace_qc") else None)
        else:
            document = masw_document(shots, specification, payload["revision_id"], reference)
        for record in payload["shots"]:
            for kind in ("waveform", "sidecar"):
                store.verify(Blob(**record[kind]))
        if capture_engine_reference().code_hash != reference.code_hash:
            raise AppError(409, "ENGINE_MISMATCH", "El motor cambió durante el cálculo")
        write_json(folder / "dossier.json", document)
        write_json(folder / "outcome.json", {"state": "SUCCEEDED"})
        return 0
    except AppError as exc:
        write_json(folder / "outcome.json", {"state": "FAILED", "code": exc.code, "transient": False})
    except IngestError as exc:
        write_json(folder / "outcome.json", {"state": "FAILED", "code": exc.code,
                                             "transient": exc.code == "FILE_ACCESS"})
    except ValueError:
        write_json(folder / "outcome.json", {"state": "FAILED", "code": "VALIDATION_FAILED", "transient": False})
    except OSError:
        write_json(folder / "outcome.json", {"state": "FAILED", "code": "CALCULATION_IO", "transient": True})
    return 2


def masw_document(shots: list[Shot], specification: dict[str, Any], revision_id: str,
                  reference: EngineReference) -> dict[str, Any]:
    request = MASWAdapterInput(
        acquisition_revision_id=revision_id, shots=tuple(shots),
        protocol=MASWProtocol.model_validate(specification["protocol"]),
        usability_policy=UsabilityPolicy.model_validate(specification["usability_policy"]),
        sensitivity_exclusions=tuple(
            ReceiverExclusion(shot_id=shot.id, receiver_id=receiver)
            for shot, receiver in zip(shots, specification["excluded_receiver_ids"], strict=True)
        ),
        engine_reference=reference,
    )
    return build_masw_dossier(request).to_document()


if __name__ == "__main__":
    raise SystemExit(calculate(Path(sys.argv[1])))
