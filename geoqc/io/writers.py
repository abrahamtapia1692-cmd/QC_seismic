"""Exportación SEG-Y de intercambio; cuantización documentada, sidecar obligatorio."""

from __future__ import annotations

import hashlib
import math
import struct
from pathlib import Path
from typing import Literal

import numpy as np
import numpy.typing as npt

from geoqc.core.models import Shot
from geoqc.io.binary import scalar_factor
from geoqc.io.contracts import IngestContext
from geoqc.io.errors import IngestError


def encode_ibm(values: npt.NDArray[np.float64], endian: str) -> bytes:
    words = np.zeros(values.size, dtype=np.uint32)
    for j, value in enumerate(values):
        magnitude = abs(float(value))
        if not math.isfinite(magnitude):
            raise IngestError("UNREPRESENTABLE_SAMPLE", "IBM no representa NaN/Inf")
        if magnitude == 0:
            continue
        _, exponent2 = math.frexp(magnitude)
        exponent16 = (exponent2 + 3) // 4
        mantissa = round(math.ldexp(magnitude, 24 - 4 * exponent16))
        if mantissa >= 2**24:
            mantissa = round(mantissa / 16)
            exponent16 += 1
        characteristic = exponent16 + 64
        if not 0 <= characteristic <= 127 or mantissa < 2**20:
            raise IngestError("UNREPRESENTABLE_SAMPLE", "Amplitud fuera del rango IBM normalizado")
        words[j] = (int(value < 0) << 31) | (characteristic << 24) | mantissa
    return words.astype(endian + "u4").tobytes()


def _quantize(value: float, step: float, bits: int, signed: bool = True) -> int:
    result = round(value / step)
    low, high = (-(2 ** (bits - 1)), 2 ** (bits - 1) - 1) if signed else (1, 2**bits - 1)
    if not low <= result <= high:
        raise IngestError("UNREPRESENTABLE_METADATA", f"{value} fuera del rango representable con paso {step}")
    return result


def write_segy(
    path: Path,
    shot: Shot,
    *,
    encoding: Literal["IBM", "IEEE"] = "IEEE",
    endian: Literal[">", "<"] = ">",
    revision: Literal[0, 1] = 1,
    coordinate_scalar: int = -1000,
) -> Path:
    if endian not in (">", "<") or encoding not in ("IBM", "IEEE") or revision not in (0, 1):
        raise IngestError("FORMAT_UNSUPPORTED", "Combinación de formato/endian/revisión desconocida")
    if encoding == "IEEE" and revision == 0:
        raise IngestError("FORMAT_UNSUPPORTED", "Rev0 habilitada solo para IBM")
    if coordinate_scalar not in (-10000, -1000, -100, -10, -1, 0, 1, 10, 100, 1000, 10000):
        raise IngestError("UNREPRESENTABLE_METADATA", "Escalar fuera del conjunto estándar")
    n, ns = shot.data.shape
    if n > 65535 or ns > 65535:
        raise IngestError("UNREPRESENTABLE_METADATA", "Número de canales/muestras fuera de rev0/1")
    intervals = [_quantize(dt, 1e-6, 16, False) for dt in shot.dt_s]
    fixed = int(len(set(intervals)) == 1)
    textual = (
        (
            "C 1 GEOQC DIAGNOSTIC EXPORT; DELAY IS SOURCE-RELATIVE. MASK/METADATA IN SIDECAR.".ljust(80)
            + "C 2 NONZERO DELAY CAN INCLUDE PRETRIGGER; NOT A FIELD ACCEPTANCE CERTIFICATE.".ljust(80)
        )
        .ljust(3200)
        .encode("ascii")
    )
    binary = bytearray(400)
    for offset, value in (
        (12, n),
        (16, intervals[0]),
        (20, ns),
        (24, 1 if encoding == "IBM" else 5),
        (54, 1),
        (300, revision * 256),
        (302, fixed),
    ):
        struct.pack_into(endian + "H", binary, offset, value)
    output = bytearray(textual) + binary
    factor = scalar_factor(coordinate_scalar)
    geometry = shot.geometry
    for j in range(n):
        header = bytearray(240)
        struct.pack_into(endian + "i", header, 0, j + 1)
        struct.pack_into(endian + "h", header, 28, 1)
        for offset, coordinate in (
            (40, float(geometry.zr[j])),
            (44, geometry.zs),
            (72, geometry.xs),
            (76, geometry.ys),
            (80, float(geometry.xr[j])),
            (84, float(geometry.yr[j])),
        ):
            struct.pack_into(endian + "i", header, offset, _quantize(coordinate, factor, 32))
        for offset, value in (
            (68, coordinate_scalar),
            (70, coordinate_scalar),
            (88, 1),
            (108, _quantize(shot.t0_s[j], 0.001, 16)),
        ):
            struct.pack_into(endian + "h", header, offset, value)
        struct.pack_into(endian + "H", header, 114, ns)
        struct.pack_into(endian + "H", header, 116, intervals[j])
        row = shot.data[j]
        if encoding == "IBM":
            payload = encode_ibm(row, endian)
        else:
            with np.errstate(over="ignore"):
                converted = row.astype(endian + "f4")
            if np.any(np.isfinite(row) & ~np.isfinite(converted)):
                raise IngestError("UNREPRESENTABLE_SAMPLE", "IEEE float32 desborda para esta amplitud")
            payload = converted.tobytes()
        output.extend(header)
        output.extend(payload)
    context = IngestContext(
        shot_id=shot.id,
        acquisition=shot.acquisition,
        geometry_policy="HEADER",
        geometry=geometry,
        header_coordinate_uncertainty_m=geometry.uncertainty_m,
        header_crs=geometry.crs,
        time_reference="SOURCE_INITIATION_VERIFIED",
        waveform_sha256=hashlib.sha256(output).hexdigest(),
        valid_mask=None if shot.valid_mask.all() else shot.valid_mask,
        mask_reasons=shot.mask_reasons,
        provenance="GeoQC export: source-relative delay; SI coordinates; original geometry retained in sidecar",
        original_headers_json=shot.headers_json,
    )
    metadata_path = path.with_suffix(path.suffix + ".json")
    if path.exists() or metadata_path.exists():
        raise IngestError(
            "OUTPUT_EXISTS", "La exportación no sobrescribe archivos existentes", "CHOOSE_NEW_OUTPUT_PATH"
        )
    try:
        # Validación y conversión completas antes de escribir.
        path.write_bytes(output)
        metadata_path.write_text(context.model_dump_json(indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise IngestError("FILE_ACCESS", str(exc), "CHOOSE_WRITABLE_OUTPUT_PATH") from exc
    return path
