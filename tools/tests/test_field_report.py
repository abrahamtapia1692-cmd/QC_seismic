"""Tooling checks; separate from the scientific acceptance obligations in tests/conftest.py."""

import json
from pathlib import Path

import pytest

from tools.report_field_quality import coverage_color, overall_color, reading_color, sha256, verify_evidence

ROOT = Path(__file__).resolve().parents[2]
CRITERIA = json.loads((ROOT / "examples/field/quality_criteria.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "onsets,total,color",
    [(0, 0, "GRAY"), (0, 10, "RED"), (4, 10, "RED"), (5, 10, "AMBER"), (7, 10, "AMBER"), (8, 10, "GREEN")],
)
def test_coverage_includes_abstentions_and_boundaries(onsets, total, color):
    assert coverage_color(onsets, total, CRITERIA) == color


def test_coverage_is_configurable_and_rejects_invalid_counts():
    criteria = {"trs_onset_coverage": {"green_min": 0.6, "amber_min": 0.3}}
    assert coverage_color(4, 10, criteria) == "AMBER"
    with pytest.raises(ValueError, match="count"):
        coverage_color(11, 10, criteria)


@pytest.mark.parametrize(
    "colors,unresolved,expected",
    [
        (["GREEN", "GREEN"], False, "GREEN"),
        (["GREEN", "GREEN"], True, "AMBER"),
        (["GREEN", "GRAY"], False, "AMBER"),
        (["RED", "GRAY"], True, "RED"),
        (["GRAY"], True, "GRAY"),
        ([], True, "GRAY"),
    ],
)
def test_missing_evidence_cannot_turn_green(colors, unresolved, expected):
    assert overall_color(colors, unresolved=unresolved) == expected


def test_nonfinite_sample_fraction_and_failed_checks_prevent_green():
    qc = {"finite_fraction": float("nan"), "constant_channels_1based": [], "zero_channels_1based": []}
    assert reading_color(qc, [{"passed": True}]) == "RED"
    qc["finite_fraction"] = 1
    assert reading_color(qc, [{"passed": False}]) == "RED"
    assert reading_color(qc, []) == "GRAY"


def test_modified_source_refuses_historical_report(tmp_path):
    source = tmp_path / "shot.bin"
    source.write_bytes(b"original")
    manifest = {"repositories": [], "files": [{"path": "shot.bin", "sha256": sha256(source)}]}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="stale or modified"):
        verify_evidence(tmp_path, {"download_manifest": "manifest.json", "repositories": [], "code_sha256": {}})
