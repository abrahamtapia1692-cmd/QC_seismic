"""Errores de formato, precedencia y valores faltantes con consecuencias científicas."""

import hashlib
import json
import struct

import numpy as np
import pytest

from geoqc.core.models import Shot
from geoqc.io.binary import parse_seg2, parse_segy
from geoqc.io.errors import IngestError
from geoqc.io.geometry import compare_geometry, geometry_diagnostics, geometry_from_csv
from geoqc.io.readers import read_shot
from geoqc.io.writers import encode_ibm, write_segy
from tests.unit.test_e1 import fixture_shot
from tests.unit.test_e1_formats import seg2_fixture


def update_context(path, changes):
    metadata = path.with_suffix(path.suffix + ".json")
    payload = json.loads(metadata.read_text(encoding="utf-8")) | changes
    metadata.write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.vid("V-E1-2")
@pytest.mark.parametrize(
    "changes,code",
    [
        ({"waveform_sha256": "f" * 64}, "SIDECAR_MISMATCH"),
        ({"provenance": ""}, "METADATA_MISSING"),
        ({"geometry_policy": "SIDECAR", "geometry": None}, "GEOMETRY_MISSING"),
        ({"time_reference": "SIDECAR_AUTHORITATIVE", "t0_s": None}, "TIME_REFERENCE_MISSING"),
        ({"header_crs": None}, "GEOMETRY_MISSING"),
        ({"acquisition": {"amplitude_unit": "counts"}}, "INVALID_CONTENT"),
        ({"valid_mask": [[True]], "mask_reasons": [""]}, "MASK_INCONSISTENT"),
    ],
)
def test_sidecar_inconsistencies_have_typed_errors(tmp_path, changes, code):
    path = tmp_path / "fixture.sgy"
    write_segy(path, fixture_shot())
    update_context(path, changes)
    with pytest.raises(IngestError, match=code):
        read_shot(path)


@pytest.mark.vid("V-E1-2")
@pytest.mark.parametrize(
    "offset,fmt,value", [(3504, "h", -1), (3502, "H", 3), (3216, "H", 0), (3220, "H", 0), (3224, "H", 2)]
)
def test_binary_header_rejection_is_not_a_byte_order_repair(tmp_path, offset, fmt, value):
    path = tmp_path / "bad.sgy"
    write_segy(path, fixture_shot())
    raw = bytearray(path.read_bytes())
    struct.pack_into(">" + fmt, raw, offset, value)
    with pytest.raises(IngestError):
        parse_segy(bytes(raw))


@pytest.mark.vid("V-E1-2")
def test_rev0_ieee_and_truncated_header_rejected(tmp_path):
    path = tmp_path / "bad.sgy"
    write_segy(path, fixture_shot())
    raw = bytearray(path.read_bytes())
    struct.pack_into(">H", raw, 3500, 0)
    with pytest.raises(IngestError, match="FORMAT_UNSUPPORTED"):
        parse_segy(bytes(raw))
    struct.pack_into(">H", raw, 3500, 256)
    with pytest.raises(IngestError, match="TRUNCATED"):
        parse_segy(bytes(raw[:3600]))
    with pytest.raises(IngestError, match="TRUNCATED"):
        parse_segy(bytes(raw[:3601]))


@pytest.mark.vid("V-E1-2")
@pytest.mark.parametrize(
    "mutation", ["pointers", "signature", "code", "count", "size", "string", "terminator", "interval"]
)
def test_seg2_corruption_typed(tmp_path, mutation):
    path = tmp_path / "bad.seg2"
    seg2_fixture(path)
    raw = bytearray(path.read_bytes())
    if mutation == "pointers":
        struct.pack_into("<I", raw, 32, 0)
    elif mutation == "signature":
        struct.pack_into("<H", raw, 46, 0)
    elif mutation == "code":
        raw[46 + 12] = 3
    elif mutation == "count":
        struct.pack_into("<I", raw, 46 + 8, 0)
    elif mutation == "size":
        struct.pack_into("<I", raw, 46 + 4, 2**32 - 1)
    elif mutation == "string":
        struct.pack_into("<H", raw, 46 + 32, 65535)
    elif mutation == "terminator":
        raw[46 + 32 + 2 + len("SAMPLE_INTERVAL 0.001")] = 65
    else:
        raw = raw.replace(b"SAMPLE_INTERVAL 0.001", b"SAMPLE_INTERVAL 0.000")
    with pytest.raises(IngestError):
        parse_seg2(bytes(raw))


@pytest.mark.vid("V-E1-3")
def test_masked_nonfinite_data_roundtrip_and_per_channel_dt(tmp_path):
    source = fixture_shot()
    data, mask = source.data.copy(), source.valid_mask.copy()
    data[0, 0] = np.nan
    mask[0, 0] = False
    masked = Shot.model_validate(
        source.model_dump()
        | {"data": data, "valid_mask": mask, "mask_reasons": ("CORRUPT", "", ""), "dt_s": (0.001, 0.002, 0.003)}
    )
    path = tmp_path / "masked.sgy"
    write_segy(path, masked)
    restored = read_shot(path)
    assert restored.dt_s == (0.001, 0.002, 0.003)
    assert np.array_equal(restored.valid_mask, mask)
    assert np.array_equal(restored.data, data.astype(np.float32).astype(np.float64), equal_nan=True)
    assert np.allclose(restored.data[mask], data[mask], rtol=1e-6, atol=1e-12)
    assert "CORRUPT" in restored.mask_reasons[0]


@pytest.mark.vid("V-E1-3")
def test_variable_length_trace_is_padded_only_under_invalid_mask(tmp_path):
    path = tmp_path / "variable.sgy"
    write_segy(path, fixture_shot())
    raw = bytearray(path.read_bytes())
    struct.pack_into(">H", raw, 3502, 0)
    struct.pack_into(">H", raw, 3600 + 2 * (240 + 128) + 114, 16)
    path.write_bytes(raw[:-64])
    update_context(path, {"waveform_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    restored = read_shot(path)
    assert restored.data.shape == (3, 32)
    assert restored.valid_mask[2, :16].all()
    assert not restored.valid_mask[2, 16:].any()
    assert np.isnan(restored.data[2, 16:]).all()
    assert restored.mask_reasons[2] == "PADDED_LENGTH"


@pytest.mark.vid("V-E1-2")
def test_source_headers_inconsistent_cannot_construct_single_shot(tmp_path):
    path = tmp_path / "mixed.sgy"
    write_segy(path, fixture_shot())
    raw = bytearray(path.read_bytes())
    struct.pack_into(">i", raw, 3600 + (240 + 128) + 72, 1000)
    path.write_bytes(raw)
    update_context(path, {"waveform_sha256": hashlib.sha256(raw).hexdigest()})
    with pytest.raises(IngestError, match="GEOMETRY_INCONSISTENT"):
        read_shot(path)


@pytest.mark.vid("V-E1-1")
def test_feet_scalars_delay_and_extended_header_conversion(tmp_path):
    path = tmp_path / "feet.sgy"
    write_segy(path, fixture_shot())
    raw = bytearray(path.read_bytes())
    struct.pack_into(">H", raw, 3254, 2)
    for j in range(3):
        struct.pack_into(">h", raw, 3600 + j * (240 + 128) + 214, -10)
    parsed = parse_segy(bytes(raw))
    assert parsed.coordinates[0][0] == pytest.approx(6.0 * 0.3048)
    assert parsed.t0_s == (-0.01,) * 3
    struct.pack_into(">h", raw, 3504, 1)
    extended = bytes(raw[:3600]) + b" " * 3200 + bytes(raw[3600:])
    assert len(parse_segy(extended).traces) == 3


@pytest.mark.vid("V-E1-2")
@pytest.mark.parametrize("kwargs", [{"revision": 0}, {"endian": "?"}, {"encoding": "INT"}, {"coordinate_scalar": 7}])
def test_writer_rejects_unsupported_format_before_writing(tmp_path, kwargs):
    path = tmp_path / "not_created.sgy"
    with pytest.raises(IngestError):
        write_segy(path, fixture_shot(), **kwargs)
    assert not path.exists()


@pytest.mark.vid("V-E1-2")
def test_writer_protects_existing_and_out_of_range_data(tmp_path):
    path = tmp_path / "existing.sgy"
    write_segy(path, fixture_shot())
    original = path.read_bytes()
    with pytest.raises(IngestError, match="OUTPUT_EXISTS"):
        write_segy(path, fixture_shot())
    assert path.read_bytes() == original
    for magnitude in (1e-100, 1e100):
        with pytest.raises(IngestError):
            encode_ibm(np.array([magnitude]), ">")
    source = fixture_shot(dt=1.0)
    with pytest.raises(IngestError, match="UNREPRESENTABLE_METADATA"):
        write_segy(tmp_path / "overflow.sgy", source)


@pytest.mark.vid("V-E1-2")
def test_absent_amplitude_unit_is_not_defaulted_from_waveform(tmp_path):
    path = tmp_path / "missing_unit.sgy"
    write_segy(path, fixture_shot())
    metadata = path.with_suffix(path.suffix + ".json")
    context = json.loads(metadata.read_text(encoding="utf-8"))
    del context["acquisition"]["amplitude_unit"]
    metadata.write_text(json.dumps(context), encoding="utf-8")
    with pytest.raises(IngestError, match="METADATA_MISSING"):
        read_shot(path)


@pytest.mark.vid("V-E1-6")
def test_uncertainty_overlap_and_crs_mismatch_are_distinct():
    from geoqc.core.models import Geometry

    reference = fixture_shot().geometry
    measured = Geometry.model_validate(reference.model_dump() | {"xr": reference.xr + 0.1})
    assert (
        compare_geometry(measured, reference, tolerance_m=0.1, reference_is_authoritative=True).status
        == "UNCERTAINTY_OVERLAPS_TOLERANCE"
    )
    changed_crs = Geometry.model_validate(reference.model_dump() | {"crs": "other"})
    with pytest.raises(ValueError):
        compare_geometry(changed_crs, reference, tolerance_m=0.1)
    with pytest.raises(ValueError):
        compare_geometry(measured, reference, tolerance_m=-0.1)


@pytest.mark.vid("V-E1-4")
def test_invalid_csv_and_spacing_inputs_rejected(tmp_path):
    geo = fixture_shot().geometry
    with pytest.raises(ValueError):
        geometry_diagnostics(geo, nominal_dx_m=0.0)
    with pytest.raises(ValueError):
        geometry_diagnostics(geo, nominal_dx_m=2.0, support_x_m=(1.0, -1.0))
    path = tmp_path / "bad.csv"
    for body in ("x,y\n1,2\n", "receiver_id,x_m,y_m,z_m,uncertainty_m\nr1,1,0,0,0\nr1,2,0,0,0\n"):
        path.write_text(body)
        with pytest.raises(ValueError):
            geometry_from_csv(path, receiver_ids=("r1",), source_xyz_m=(0.0, 0.0, 0.0), crs="local")
