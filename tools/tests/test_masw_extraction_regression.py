"""Frozen pre-extraction fingerprints, not a comparison of two wrappers of the same code."""

import json
from pathlib import Path

from geoqc.core.evidence import canonical_hash
from tools.report_masw_quality import compare_records, load_records


def test_oysand_matches_the_snapshot_captured_before_extraction():
    baseline = json.loads((
        Path(__file__).resolve().parents[2] / "tests/fixtures/app_adapter/oysand_before_extraction.json"
    ).read_text(encoding="utf-8"))
    records, arrays, inputs = load_records()
    assert inputs == baseline["inputs"]
    assert len(records) == 4 and sum(record["channels"] for record in records) == 96
    assert {record["id"] for record in records} == set(baseline["records"])
    for record in records:
        expected = baseline["records"][record["id"]]
        assert canonical_hash(record) == expected["summary_digest"]
        assert {key: canonical_hash(value) for key, value in arrays[record["id"]].items()} == expected["array_digests"]
    assert canonical_hash(compare_records(records, arrays)) == baseline["comparisons_digest"]
