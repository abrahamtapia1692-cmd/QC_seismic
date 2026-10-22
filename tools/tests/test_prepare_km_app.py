"""Conversion cannot turn missing KM acquisition metadata into scientific evidence."""
import hashlib
import json

import numpy as np
import pytest

from geoqc.io.readers import read_shot
from tests.unit.test_e1_formats import seg2_fixture
from tools.prepare_km_app import convert, describe, prepare, template


def reviewed_metadata(tmp_path):
    source = tmp_path / "source.sg2"
    seg2_fixture(source)
    context = json.loads(source.with_suffix(".sg2.json").read_bytes())
    context["acquisition"].update(technique="MASW", wave="RAYLEIGH", component="Z")
    document = {"confirmed": True, "review_notes": "Explicit synthetic fixture; not KM field confirmation",
                "source_file": "source.sg2", "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "context": context}
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps(document), encoding="utf-8")
    return source, metadata, document


def test_inventory_keeps_missing_metadata_and_mam_separate(tmp_path):
    folder = tmp_path / "KM test" / "F1"
    folder.mkdir(parents=True)
    seg2_fixture(folder / "active.sg2")
    passive = tmp_path / "KM test" / "MAM"
    passive.mkdir()
    seg2_fixture(passive / "passive.sg2")
    (folder / "Readme.txt").write_bytes("Topografía pendiente".encode("cp1252"))
    result = prepare(tmp_path, tmp_path / "prepared")
    assert result["record_count"] == 2 and result["mam_count"] == 1
    assert result["notes"][0]["text"] == "Topografía pendiente"
    record = result["records"][0]
    assert record["app_upload_ready"] is False
    candidate = template(record)
    assert candidate["context"]["acquisition"]["amplitude_unit"] is None
    assert candidate["context"]["geometry"]["crs"] is None
    assert candidate["context"]["time_reference"] is None
    assert not candidate["confirmed"]
    metadata = tmp_path / "prepared" / "KM_test_F1.metadata.template.json"
    with pytest.raises(ValueError, match="confirme"):
        convert(metadata, tmp_path / "should-not-exist.sgy", tmp_path)
    assert not (tmp_path / "should-not-exist.sgy").exists()


def test_reviewed_conversion_preserves_samples_timing_and_raw_original(tmp_path):
    source, metadata, _ = reviewed_metadata(tmp_path)
    original = source.read_bytes()
    output = tmp_path / "converted.sgy"
    convert(metadata, output, tmp_path)
    restored = read_shot(output)
    assert np.array_equal(restored.data, read_shot(source).data)
    assert restored.dt_s == (0.001,) * 3 and restored.t0_s == (-0.1,) * 3
    assert restored.acquisition.technique == "MASW"
    assert source.read_bytes() == original
    assert json.loads(restored.headers_json)["context"]["original_headers_json"]
    with pytest.raises(ValueError, match="salida nueva"):
        convert(metadata, output, tmp_path)


def test_modified_original_or_trs_declaration_cannot_be_converted(tmp_path):
    source, metadata, document = reviewed_metadata(tmp_path)
    document["context"]["acquisition"].update(technique="TRS", wave="P")
    metadata.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="TRS"):
        convert(metadata, tmp_path / "invalid.sgy", tmp_path)
    source.write_bytes(source.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="original cambió"):
        convert(metadata, tmp_path / "changed.sgy", tmp_path)


def test_describe_does_not_interpret_delay_as_verified_trigger(tmp_path):
    source = tmp_path / "record.sg2"
    seg2_fixture(source)
    record = describe(source, tmp_path)
    assert record["delay_s"] == [-0.1] * 3
    assert template(record)["context"]["time_reference"] is None
