"""E1: formatos y metadatos verificables antes de crear un Shot."""

import json
import struct
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from geoqc.core.models import Acquisition, Geometry, Shot
from geoqc.io.errors import IngestError
from geoqc.io.geometry import compare_geometry, geometry_diagnostics, split_sides
from geoqc.io.readers import read_shot, try_read_shot
from geoqc.io.writers import write_segy


def fixture_shot(n=3, ns=32, dt=0.001, x=None):
    x = tuple(6.0 + 2 * j for j in range(n)) if x is None else x
    geometry = Geometry(
        xr=x,
        yr=(0.0,) * n,
        zr=(0.25,) * n,
        xs=0.0,
        ys=0.0,
        zs=0.5,
        uncertainty_m=(0.01,) * n,
        crs="local-SI",
        provenance=("survey",),
    )
    data = np.random.default_rng(41).normal(size=(n, ns))
    return Shot(
        id="synthetic-io",
        data=data,
        valid_mask=np.ones_like(data, dtype=bool),
        mask_reasons=("",) * n,
        dt_s=(dt,) * n,
        t0_s=(-0.1,) * n,
        geometry=geometry,
        acquisition=Acquisition(
            technique="MASW",
            wave="RAYLEIGH",
            component="Z",
            source_type="test-source",
            receiver_ids=tuple(f"r{j}" for j in range(n)),
        ),
        input_hashes=("a" * 64,),
        headers_json='{"fixture":"not field data"}',
    )


@pytest.mark.vid("V-E1-1")
@pytest.mark.parametrize(
    "encoding,endian,revision", [("IBM", ">", 0), ("IBM", ">", 1), ("IEEE", ">", 1), ("IBM", "<", 1), ("IEEE", "<", 1)]
)
def test_segy_roundtrip_supported_encodings(tmp_path, encoding, endian, revision):
    source = fixture_shot()
    path = tmp_path / "data.sgy"
    write_segy(path, source, encoding=encoding, endian=endian, revision=revision)
    restored = read_shot(path)
    assert np.allclose(restored.data, source.data, rtol=1e-6, atol=1e-12)
    assert restored.dt_s == source.dt_s
    assert np.array_equal(restored.geometry.xr, source.geometry.xr)
    assert restored.t0_s == source.t0_s
    assert restored.acquisition.receiver_ids == source.acquisition.receiver_ids
    assert len(restored.input_hashes) == 2
    headers = json.loads(restored.headers_json)
    assert headers["format"] == "SEG-Y"
    assert headers["endian"] == endian
    for original, decoded, bound in zip(
        source.data, restored.data, headers["quantization"]["sample_half_ulp_upper_bound"], strict=True
    ):
        assert np.max(abs(original - decoded)) <= bound


@pytest.mark.vid("V-E1-1")
def test_nonrepresentable_metadata_records_quantization(tmp_path):
    source = fixture_shot(dt=0.0010004, x=(6.0004, 8.0004, 10.0004))
    path = tmp_path / "quantized.sgy"
    write_segy(path, source, coordinate_scalar=-1000)
    restored = read_shot(path)
    assert max(abs(np.asarray(restored.dt_s) - source.dt_s)) <= 0.5e-6
    assert np.max(abs(restored.geometry.xr - source.geometry.xr)) <= 0.0005
    headers = json.loads(restored.headers_json)
    assert headers["quantization"]["dt_step_s"] == 1e-6
    assert (
        headers["quantization"]["coordinate_step_m"] == (0.001,) * 3
        or headers["quantization"]["coordinate_step_m"] == [0.001] * 3
    )


@pytest.mark.vid("V-E1-2")
@pytest.mark.parametrize("body", [b"", b"junk", b"\x55\x3a", bytes(3600)])
def test_invalid_file_has_actionable_failure(tmp_path, body):
    path = tmp_path / "bad.sgy"
    path.write_bytes(body)
    failure = try_read_shot(path)
    assert not isinstance(failure, Shot)
    assert failure.error_code
    assert failure.action_ids
    with pytest.raises(IngestError):
        read_shot(path)


@pytest.mark.vid("V-E1-2")
@pytest.mark.parametrize("mutation", ["truncated", "dt_zero", "wrong_ns", "missing_context"])
def test_valid_file_corruption_not_silently_repaired(tmp_path, mutation):
    path = tmp_path / "bad.sgy"
    write_segy(path, fixture_shot())
    data = bytearray(path.read_bytes())
    if mutation == "truncated":
        data = data[:-3]
    elif mutation == "dt_zero":
        struct.pack_into(">H", data, 3216, 0)
    elif mutation == "wrong_ns":
        struct.pack_into(">H", data, 3600 + 114, 64)
    else:
        path.with_suffix(".sgy.json").unlink()
    path.write_bytes(data)
    with pytest.raises(IngestError):
        read_shot(path)


@pytest.mark.vid("V-E1-3")
@settings(max_examples=20, deadline=None, derandomize=True)
@given(n=st.integers(1, 96), ns=st.integers(16, 32768), dt_us=st.integers(1, 65535))
def test_shape_and_representable_sampling_property(n, ns, dt_us):
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "property.sgy"
        source = fixture_shot(n, ns, dt_us / 1e6)
        write_segy(path, source)
        restored = read_shot(path)
        assert restored.data.shape == (n, ns)
        assert restored.valid_mask.all()
        assert restored.dt_s == source.dt_s
        assert np.allclose(restored.data, source.data, rtol=1e-6, atol=1e-12)


@pytest.mark.vid("V-E1-3")
@pytest.mark.parametrize("n,ns", [(1, 16), (96, 32768)])
def test_declared_dimension_frontiers_explicitly(tmp_path, n, ns):
    source = fixture_shot(n, ns)
    path = tmp_path / "boundary.sgy"
    write_segy(path, source)
    restored = read_shot(path)
    assert restored.data.shape == (n, ns)
    assert restored.valid_mask.all()
    assert np.allclose(restored.data, source.data, rtol=1e-6, atol=1e-12)


@pytest.mark.vid("V-E1-4")
def test_geometry_irregularity_and_2d_support_are_distinct():
    source = fixture_shot(x=(6.0, 8.0, 11.0)).geometry
    result = geometry_diagnostics(source, nominal_dx_m=2.0)
    assert result.spacing_relative_deviations == (0.0, 0.5)
    assert result.uniform_kernel_applicable is False
    assert result.cause == "NOT_IDENTIFIABLE_FROM_COORDINATES_ALONE"
    topo = Geometry(**(source.model_dump() | {"yr": (0.0, 1.0, 0.0), "zr": (0.0, 0.5, 1.0)}))
    diag = geometry_diagnostics(topo, nominal_dx_m=2.0)
    assert diag.crossline_extent_m == 1.0
    assert diag.elevation_extent_m == 1.0
    assert not diag.uniform_kernel_applicable


@pytest.mark.vid("V-E1-5")
def test_internal_source_split_keeps_signed_offsets_and_ids():
    geo = fixture_shot(x=(-4.0, -2.0, 0.0, 2.0, 4.0), n=5).geometry
    result = split_sides(geo)
    assert result.left_indices == (1, 0)
    assert result.right_indices == (3, 4)
    assert result.coincident_indices == (2,)
    assert result.signed_offsets_m == (-4.0, -2.0, 0.0, 2.0, 4.0)
    assert result.horizontal_distances_m == (4.0, 2.0, 0.0, 2.0, 4.0)


@pytest.mark.vid("V-E1-6")
@pytest.mark.parametrize("offset,expected", [(0.05, "WITHIN_TOLERANCE"), (0.5, "DISCREPANCY")])
def test_geometry_reference_discrepancy_includes_uncertainty(offset, expected):
    reference = fixture_shot().geometry
    measured = Geometry(**(reference.model_dump() | {"xr": reference.xr + offset}))
    result = compare_geometry(measured, reference, tolerance_m=0.1, reference_is_authoritative=True)
    assert result.status == expected
    assert result.maximum_receiver_discrepancy_m == pytest.approx(offset)
    assert result.combined_uncertainty_m == pytest.approx(np.sqrt(2) * 0.01)
    assert compare_geometry(measured, None, tolerance_m=0.1).status == "MISSING"
    assert compare_geometry(measured, reference, tolerance_m=0.1).status == "AUTHORITY_UNCONFIRMED"
