"""Fixtures binarios explícitos y referencias de otro lector (ObsPy)."""

import hashlib
import json
import struct

import numpy as np
import pytest

from geoqc.io.binary import decode_ibm
from geoqc.io.contracts import IngestContext
from geoqc.io.errors import IngestError
from geoqc.io.geometry import geometry_diagnostics, geometry_from_csv, split_sides
from geoqc.io.readers import read_shot, try_read_shot
from geoqc.io.writers import encode_ibm, write_segy
from tests.unit.test_e1 import fixture_shot


def write_context(path, shot, *, policy="SIDECAR", delay_override=None):
    context = IngestContext(
        shot_id=shot.id,
        acquisition=shot.acquisition,
        geometry_policy=policy,
        geometry=shot.geometry,
        time_reference="SOURCE_INITIATION_VERIFIED" if delay_override is None else "SIDECAR_AUTHORITATIVE",
        t0_s=delay_override,
        provenance="controlled fixture",
        waveform_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    path.with_suffix(path.suffix + ".json").write_text(context.model_dump_json(), encoding="utf-8")


def seg2_fixture(path, *, endian="<", code=4, delay=True):
    source = fixture_shot()
    strings = ["SAMPLE_INTERVAL 0.001"] + (["DELAY -0.1"] if delay else [])
    free = (
        b"".join(struct.pack(endian + "H", len(text) + 3) + text.encode("ascii") + b"\0" for text in strings) + b"\0\0"
    )
    block = 32 + len(free)
    dtype = {1: "i2", 2: "i4", 4: "f4", 5: "f8"}[code]
    values = source.data if code in (4, 5) else np.rint(source.data * 100)
    trace_bytes = []
    for row in values:
        descriptor = bytearray(32)
        payload = row.astype(endian + dtype).tobytes()
        struct.pack_into(endian + "HHII", descriptor, 0, 0x4422, block, len(payload), row.size)
        descriptor[12] = code
        trace_bytes.append(bytes(descriptor) + free + payload)
    descriptor = bytearray(32)
    struct.pack_into(endian + "HHHH", descriptor, 0, 0x3A55, 1, 12, 3)
    descriptor[8:14] = bytes((1, 0, 0, 1, 10, 0))
    pointers = []
    cursor = 46
    for trace in trace_bytes:
        pointers.append(cursor)
        cursor += len(trace)
    raw = bytes(descriptor) + struct.pack(endian + "III", *pointers) + b"\0\0" + b"".join(trace_bytes)
    path.write_bytes(raw)
    write_context(path, source, delay_override=None if delay else (-0.2,) * 3)
    return values


@pytest.mark.vid("V-E1-1")
@pytest.mark.parametrize("encoding", ["IEEE", "IBM"])
def test_export_cross_checked_by_obspy(tmp_path, encoding):
    from obspy.io.segy.segy import _read_segy

    path = tmp_path / "cross.sgy"
    source = fixture_shot()
    write_segy(path, source, encoding=encoding)
    external = _read_segy(str(path), endian=">")
    for expected, trace in zip(source.data, external.traces, strict=True):
        assert np.allclose(trace.data, expected, rtol=1e-6, atol=1e-12)
        assert trace.header.sample_interval_in_ms_for_this_trace == 1000
        assert trace.header.delay_recording_time == -100


@pytest.mark.vid("V-E1-2")
@pytest.mark.parametrize("endian", ["<", ">"])
@pytest.mark.parametrize("code", [1, 2, 4, 5])
def test_seg2_real_binary_structure_and_endian(tmp_path, endian, code):
    path = tmp_path / "fixture.seg2"
    expected = seg2_fixture(path, endian=endian, code=code)
    restored = read_shot(path)
    assert np.allclose(restored.data, expected, rtol=1e-6, atol=1e-12)
    assert restored.dt_s == (0.001,) * 3
    assert restored.t0_s == (-0.1,) * 3
    assert json.loads(restored.headers_json)["format"] == "SEG-2"


@pytest.mark.vid("V-E1-2")
def test_seg2_samples_independently_read_by_obspy(tmp_path):
    import warnings

    from obspy import read

    path = tmp_path / "cross.seg2"
    expected = seg2_fixture(path)
    # ObsPy documenta que su starttime no interpreta DELAY no cero: solo se compara waveform/dt.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Many companies use custom defined SEG2.*", category=UserWarning)
        warnings.filterwarnings("ignore", message="Non-zero value found in Trace.*", category=UserWarning)
        external = read(str(path), format="SEG2")
    assert np.allclose(np.vstack([trace.data for trace in external]), expected, rtol=1e-6, atol=1e-12)


@pytest.mark.vid("V-E1-2")
def test_seg2_missing_delay_requires_explicit_authority(tmp_path):
    path = tmp_path / "missing.seg2"
    seg2_fixture(path, delay=False)
    assert read_shot(path).t0_s == (-0.2,) * 3
    write_context(path, fixture_shot())
    with pytest.raises(IngestError, match="TIME_REFERENCE_MISSING"):
        read_shot(path)


@pytest.mark.vid("V-E1-1")
def test_ibm_known_words_and_dynamic_range():
    words = bytes.fromhex("0000000041100000c11000004120000042100000")
    assert np.array_equal(decode_ibm(words, ">"), (0.0, 1.0, -1.0, 2.0, 16.0))
    values = np.array([0.0, -1.0, 1e-50, 1e50, np.pi])
    assert np.allclose(decode_ibm(encode_ibm(values, ">"), ">"), values, rtol=1e-6, atol=0)
    with pytest.raises(IngestError):
        encode_ibm(np.array([np.nan]), ">")


@pytest.mark.vid("V-E1-2")
def test_missing_file_typed_without_fabricated_digest(tmp_path):
    failure = try_read_shot(tmp_path / "absent.sgy")
    assert failure.error_code == "FILE_ACCESS"
    assert failure.data_hash is None


@pytest.mark.vid("V-E1-4")
def test_csv_maps_physical_ids_and_receiver_outside_explicit_support(tmp_path):
    path = tmp_path / "survey.csv"
    path.write_text("receiver_id,x_m,y_m,z_m,uncertainty_m\nr2,8,0,0,0.02\nr1,6,0,0,0.02\nr3,12,0,0,0.02\n")
    geometry = geometry_from_csv(path, receiver_ids=("r1", "r2", "r3"), source_xyz_m=(0.0, 0.0, 0.0), crs="local")
    assert np.array_equal(geometry.xr, (6.0, 8.0, 12.0))
    assert geometry_diagnostics(geometry, nominal_dx_m=2.0, support_x_m=(6.0, 10.0)).out_of_support_indices == (2,)
    assert geometry_diagnostics(geometry, nominal_dx_m=2.0).out_of_support_indices is None
    with pytest.raises(ValueError):
        geometry_from_csv(path, receiver_ids=("r1", "r2"), source_xyz_m=(0.0, 0.0, 0.0), crs="local")


@pytest.mark.vid("V-E1-5")
def test_side_split_orientation_and_crossline_receivers():
    from geoqc.core.models import Geometry

    geo = Geometry(
        xr=(-1.0, 1.0, 0.0),
        yr=(0.0, 0.0, 1.0),
        zr=(0.0,) * 3,
        xs=0.0,
        ys=0.0,
        zs=0.0,
        uncertainty_m=(0.0,) * 3,
        crs="local",
        provenance=("fixture",),
    )
    result = split_sides(geo)
    assert result.azimuths_degrees == (180.0, 0.0, 90.0)
    assert result.crossline_indices == (2,)
