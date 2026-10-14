"""Decodificación explícita SEG-Y rev0/1 y SEG-2 rev1; sin adivinar metadatos."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from geoqc.io.errors import IngestError


@dataclass(frozen=True)
class WaveformFile:
    traces: tuple[npt.NDArray[np.float64], ...]
    dt_s: tuple[float, ...]
    t0_s: tuple[float | None, ...]
    coordinates: tuple[tuple[float, float, float, float, float, float] | None, ...]
    headers: dict[str, Any]


def scalar_factor(scalar: int) -> float:
    return float(scalar) if scalar > 0 else 1.0 / abs(scalar) if scalar < 0 else 1.0


def decode_ibm(raw: bytes, endian: str) -> npt.NDArray[np.float64]:
    words = np.frombuffer(raw, dtype=endian + "u4")
    mantissa = (words & 0x00FFFFFF).astype(np.float64)
    exponent = ((words >> 24) & 0x7F).astype(np.int32) - 64
    result = np.ldexp(mantissa / 2**24, exponent * 4)
    return np.asarray(np.where(words >> 31, -result, result), dtype=np.float64)


def _u16(raw: bytes, offset: int, endian: str) -> int:
    return int(struct.unpack_from(endian + "H", raw, offset)[0])


def _i16(raw: bytes, offset: int, endian: str) -> int:
    return int(struct.unpack_from(endian + "h", raw, offset)[0])


def _i32(raw: bytes, offset: int, endian: str) -> int:
    return int(struct.unpack_from(endian + "i", raw, offset)[0])


def parse_segy(raw: bytes) -> WaveformFile:
    if len(raw) < 3600:
        raise IngestError("TRUNCATED", "SEG-Y requiere cabeceras textual de 3200 y binaria de 400 bytes")
    candidates = [
        endian for endian in (">", "<") if _u16(raw, 3224, endian) in (1, 5) and _u16(raw, 3500, endian) in (0, 256)
    ]
    if len(candidates) != 1:
        raise IngestError("FORMAT_UNSUPPORTED", "Sin combinación inequívoca de revisión 0/1, formato IBM/IEEE y endian")
    endian = candidates[0]
    code, revision = _u16(raw, 3224, endian), _u16(raw, 3500, endian) // 256
    dt, ns = _u16(raw, 3216, endian), _u16(raw, 3220, endian)
    fixed, extended = _u16(raw, 3502, endian), _i16(raw, 3504, endian)
    if dt == 0 or ns == 0 or fixed not in (0, 1):
        raise IngestError("HEADER_INVALID", "dt/ns binarios positivos y flag de longitud 0/1 requeridos")
    if code == 5 and revision == 0:
        raise IngestError("FORMAT_UNSUPPORTED", "IEEE se habilita en rev1; rev0 soporta IBM")
    if extended < 0:
        raise IngestError("FORMAT_UNSUPPORTED", "Cabeceras extendidas con conteo -1 fuera del alcance habilitado")
    cursor = 3600 + extended * 3200
    if cursor >= len(raw):
        raise IngestError("TRUNCATED", "Sin trazas completas tras las cabeceras extendidas")
    measurement = _u16(raw, 3254, endian)
    unit_factor = 1.0 if measurement == 1 else 0.3048 if measurement == 2 else None
    traces, dts, delays, coords, headers, coord_steps, delay_steps, amplitude_bounds = [], [], [], [], [], [], [], []
    while cursor < len(raw):
        if len(raw) - cursor < 240:
            raise IngestError("TRUNCATED", "Cabecera de traza incompleta")
        header = raw[cursor : cursor + 240]
        count, interval = _u16(header, 114, endian), _u16(header, 116, endian)
        if count == 0 or interval == 0 or (fixed == 1 and (count != ns or interval != dt)):
            raise IngestError("HEADER_INCONSISTENT", "dt/ns de traza inválidos o incompatibles con fixed_length")
        start, stop = cursor + 240, cursor + 240 + 4 * count
        if stop > len(raw):
            raise IngestError("TRUNCATED", "Muestras de traza incompletas")
        payload = raw[start:stop]
        data = (
            decode_ibm(payload, endian)
            if code == 1
            else np.asarray(np.frombuffer(payload, dtype=endian + "f4"), dtype=np.float64)
        )
        amplitude_bound: float | None
        if code == 1:
            words = np.frombuffer(payload, dtype=endian + "u4")
            exponents = (((words >> 24) & 0x7F).astype(np.int32) - 64) * 4 - 25
            amplitude_bound = float(np.max(np.where(words & 0x00FFFFFF, np.ldexp(np.ones(count), exponents), 0.0)))
        else:
            finite = abs(data[np.isfinite(data)])
            _, exponents = np.frexp(finite)
            amplitude_bound = (
                float(np.max(np.maximum(np.ldexp(np.ones(finite.size), exponents - 25), 2.0**-150)))
                if finite.size
                else None
            )
        amplitude_bounds.append(amplitude_bound)
        coordinate_factor = scalar_factor(_i16(header, 70, endian))
        elevation_factor = scalar_factor(_i16(header, 68, endian))
        time_factor = scalar_factor(_i16(header, 214, endian)) if revision else 1.0
        coordinates = None
        if _u16(header, 88, endian) == 1 and unit_factor is not None:
            sx, sy, rx, ry = (_i32(header, pos, endian) * coordinate_factor * unit_factor for pos in (72, 76, 80, 84))
            sz = (_i32(header, 44, endian) - _i32(header, 48, endian)) * elevation_factor * unit_factor
            rz = _i32(header, 40, endian) * elevation_factor * unit_factor
            coordinates = (rx, ry, rz, sx, sy, sz)
        traces.append(data)
        dts.append(interval / 1e6)
        delays.append(_i16(header, 108, endian) * time_factor / 1000)
        coords.append(coordinates)
        headers.append(header.hex())
        coord_steps.append(None if unit_factor is None else coordinate_factor * unit_factor)
        delay_steps.append(time_factor / 1000)
        cursor = stop
    return WaveformFile(
        tuple(traces),
        tuple(dts),
        tuple(delays),
        tuple(coords),
        {
            "format": "SEG-Y",
            "endian": endian,
            "revision": revision,
            "sample_format_code": code,
            "text_header_hex": raw[:3200].hex(),
            "binary_header_hex": raw[3200:3600].hex(),
            "extended_header_hex": raw[3600 : 3600 + extended * 3200].hex(),
            "trace_header_hex": headers,
            "measurement_system": measurement,
            "quantization": {
                "dt_step_s": 1e-6,
                "coordinate_step_m": coord_steps,
                "t0_step_s": delay_steps,
                "sample_half_ulp_upper_bound": amplitude_bounds,
            },
        },
    )


def _free_form(raw: bytes, endian: str, terminator: bytes) -> dict[str, str]:
    cursor, parsed = 0, {}
    while cursor < len(raw):
        if len(raw) - cursor < 2:
            raise IngestError("HEADER_INVALID", "Bloque de strings SEG-2 incompleto")
        size = _u16(raw, cursor, endian)
        if size == 0:
            break
        if size < 3 or cursor + size > len(raw):
            raise IngestError("HEADER_INVALID", "Longitud de string SEG-2 inválida")
        body = raw[cursor + 2 : cursor + size]
        if not body.endswith(terminator):
            raise IngestError("HEADER_INVALID", "String SEG-2 sin terminador declarado")
        text = body[: -len(terminator)].decode("ascii").strip()
        fields = text.split(None, 1)
        if not fields or fields[0] in parsed:
            raise IngestError("HEADER_INVALID", "String SEG-2 vacío o clave duplicada")
        parsed[fields[0]] = fields[1] if len(fields) == 2 else ""
        cursor += size
    return parsed


def parse_seg2(raw: bytes) -> WaveformFile:
    if len(raw) < 32:
        raise IngestError("TRUNCATED", "Descriptor SEG-2 incompleto")
    endian = "<" if raw[:2] == b"\x55\x3a" else ">" if raw[:2] == b"\x3a\x55" else ""
    if not endian or _u16(raw, 2, endian) != 1:
        raise IngestError("FORMAT_UNSUPPORTED", "SEG-2 rev1 con firma/endian reconocido requerido")
    pointer_size, n = _u16(raw, 4, endian), _u16(raw, 6, endian)
    if n == 0 or pointer_size < n * 4 or 32 + pointer_size > len(raw) or raw[8] not in (1, 2):
        raise IngestError("HEADER_INVALID", "Punteros/número de trazas/terminador SEG-2 inválidos")
    terminator = raw[9 : 9 + raw[8]]
    pointers = struct.unpack_from(endian + "I" * n, raw, 32)
    if sorted(set(pointers)) != list(pointers) or pointers[0] < 32 + pointer_size:
        raise IngestError("HEADER_INVALID", "Punteros SEG-2 duplicados, desordenados o fuera del bloque")
    file_header = _free_form(raw[32 + pointer_size : pointers[0]], endian, terminator)
    traces, dts, delays, all_headers, descriptors, trace_freeform = [], [], [], [], [], []
    for j, pointer in enumerate(pointers):
        if pointer + 32 > len(raw):
            raise IngestError("TRUNCATED", "Descriptor de traza SEG-2 ausente")
        descriptor = raw[pointer : pointer + 32]
        block, data_size, count = (
            _u16(descriptor, 2, endian),
            int(struct.unpack_from(endian + "I", descriptor, 4)[0]),
            int(struct.unpack_from(endian + "I", descriptor, 8)[0]),
        )
        code = descriptor[12]
        if _u16(descriptor, 0, endian) != 0x4422 or block < 32 or count == 0:
            raise IngestError("HEADER_INVALID", "Descriptor/forma de traza SEG-2 inválidos")
        formats = {1: "i2", 2: "i4", 4: "f4", 5: "f8"}
        if code not in formats:
            raise IngestError("FORMAT_UNSUPPORTED", f"Código SEG-2 {code} no habilitado; soportados 1,2,4,5")
        dtype = np.dtype(endian + formats[code])
        stop = pointer + block + data_size
        limit = pointers[j + 1] if j + 1 < len(pointers) else len(raw)
        if data_size != count * dtype.itemsize or stop > limit:
            raise IngestError("TRUNCATED", "Tamaño de muestras SEG-2 incompatible o incompleto")
        header = file_header | _free_form(raw[pointer + 32 : pointer + block], endian, terminator)
        trace_freeform.append(raw[pointer + 32 : pointer + block].hex())
        if "SAMPLE_INTERVAL" not in header:
            raise IngestError("METADATA_MISSING", "SAMPLE_INTERVAL ausente")
        dt = float(header["SAMPLE_INTERVAL"])
        delay = float(header["DELAY"]) if "DELAY" in header else None
        if not np.isfinite(dt) or dt <= 0 or (delay is not None and not np.isfinite(delay)):
            raise IngestError("HEADER_INVALID", "dt/delay SEG-2 no finitos o dt no positivo")
        traces.append(np.asarray(np.frombuffer(raw[pointer + block : stop], dtype=dtype), dtype=np.float64))
        dts.append(dt)
        delays.append(delay)
        all_headers.append(header)
        descriptors.append(descriptor.hex())
    return WaveformFile(
        tuple(traces),
        tuple(dts),
        tuple(delays),
        (None,) * n,
        {
            "format": "SEG-2",
            "endian": endian,
            "revision": 1,
            "file_descriptor_hex": raw[: 32 + pointer_size].hex(),
            "file_free_form_hex": raw[32 + pointer_size : pointers[0]].hex(),
            "file_header": file_header,
            "trace_headers": all_headers,
            "trace_freeform_hex": trace_freeform,
            "trace_descriptor_hex": descriptors,
        },
    )
