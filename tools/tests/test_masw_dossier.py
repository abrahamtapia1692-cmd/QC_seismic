import json

import numpy as np
import pytest

from tools.report_masw_quality import (
    PROTOCOL,
    analyze,
    band_rows,
    classify_support,
    compare_records,
    load_records,
    verify_inputs,
)


def test_planar_signal_and_zero_do_not_share_validity():
    dt = 0.001
    t = np.arange(2000) * dt
    x = np.arange(24) * 2.0
    wave = np.cos(2 * np.pi * 10 * (t[None, :] - x[:, None] / 200))
    result, arrays = analyze(wave, dt, x, "plane", PROTOCOL)
    j = np.argmin(abs(arrays["frequencies_hz"] - 10))
    assert abs(arrays["ridge_ms"][j] - 200) <= 1
    assert arrays["coherence"][j].max() > 0.999
    assert result["eligible_for_acceptance"] is False
    zero, za = analyze(np.zeros_like(wave), dt, x, "zero", PROTOCOL)
    assert all(p["velocity_ms"] is None for p in zero["points"])
    assert all(p["state"] == "NO_SUPPORT" for p in zero["points"])
    assert zero["acquisition_grade"] == "MALA"
    assert not za["candidate_mask"].any()


@pytest.mark.parametrize(
    "c,edge,active,expected",
    [
        (40, False, True, "REVIEW"),
        (41, False, True, "PENDING"),
        (41, True, True, "REVIEW"),
        (41, False, False, "NO_SUPPORT"),
    ],
)
def test_spatial_boundary(c, edge, active, expected):
    state, reasons = classify_support(10, c, 2, edge=edge, observed=active, uniform_complete=True)
    assert state == expected
    if expected == "PENDING":
        assert "EVIDENCE_PENDING" in reasons


def test_incomplete_support_cannot_use_uniform_nyquist():
    state, reasons = classify_support(10, 200, 2, edge=False, observed=True, uniform_complete=False)
    assert state == "REVIEW" and "KERNEL_REVIEW" in reasons


def test_bands_preserve_gaps_and_support():
    points = [
        dict(frequency_hz=f, state=s, reasons=[s], support_ids=[support])
        for f, s, support in [
            (5, "PENDING", "a"),
            (6, "PENDING", "a"),
            (7, "REVIEW", "a"),
            (8, "PENDING", "a"),
            (9, "PENDING", "b"),
            (12, "PENDING", "b"),
        ]
    ]
    assert [r["f_bounds_hz"] for r in band_rows(points, 1)] == [[5, 6], [7, 7], [8, 8], [9, 9], [12, 12]]


def test_nonfinite_samples_are_rejected():
    with pytest.raises(ValueError):
        analyze(np.full((24, 100), np.nan), 0.001, np.arange(24) * 2, "bad", PROTOCOL)


def test_manifest_detects_tampering(tmp_path):
    path = tmp_path / "data.dat"
    path.write_text("changed", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"files": [{"path": "data.dat", "sha256": "a" * 64}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        verify_inputs(tmp_path, manifest, [path])


def test_field_records_keep_all_channels_and_missing_evidence():
    records, arrays, inputs = load_records()
    assert len(records) == len(arrays) == 4
    assert sum(len(r["traces"]) for r in records) == 96
    assert inputs
    for r in records:
        assert r["evidence_status"] == "INCOMPLETE"
        assert r["overall_grade"] == "EVALUACION_PARCIAL"
        assert r["objective_grade"] == "NO_EVALUABLE"
        assert r["usability_bands"]
        assert not r["eligible_for_acceptance"]
        assert r["mode_identity"] == "APPARENT"
        assert r["missing_evidence"] and r["bands"]
    comparisons = compare_records(records, arrays)
    assert len(comparisons) == 6
    assert all(c["uncertainty_status"] == "NOT_CALIBRATED" for c in comparisons)
    assert all(c["common_bins"] > 0 for c in comparisons)


def test_no_common_support_is_not_zero_disagreement():
    arrays = {
        key: dict(
            frequencies_hz=np.array([5.0, 6.0]),
            ridge_ms=np.array([100.0, 100.0]),
            candidate_mask=np.array([False, False]),
        )
        for key in ("a", "b")
    }
    result = compare_records([{"id": "a"}, {"id": "b"}], arrays)[0]
    assert result["common_bins"] == 0 and result["median_abs_delta_ms"] is None


def test_end_to_end_artifacts_and_digest(tmp_path, monkeypatch):
    import csv
    import hashlib
    import sys

    from geoqc.core.evidence import canonical_hash
    from tools.report_masw_quality import main

    monkeypatch.setattr(sys, "argv", ["report_masw_quality", "--output", str(tmp_path)])
    main()
    report = json.loads((tmp_path / "dossier.json").read_text(encoding="utf-8"))
    assert report["study"]["traces"] == 96 and not report["study"]["eligible_for_acceptance"]
    assert report["study"]["planned_position_coverage_percent"] is None
    body = {k: v for k, v in report.items() if k not in ("scientific_digest", "generated_at_utc", "artifact_hashes")}
    assert canonical_hash(body) == report["scientific_digest"]
    for name, digest in report["artifact_hashes"].items():
        assert hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() == digest
    assert (tmp_path / "dossier.pdf").read_bytes().startswith(b"%PDF")
    html = (tmp_path / "dossier.html").read_text(encoding="utf-8")
    assert html.count("data:image/png;base64,") == 11
    assert 'src="http' not in html
    assert "EVALUACIÓN PARCIAL" in html and "Nyquist" in html
    assert report["schema_version"] == "masw-dossier-2.0"
    assert report["study"]["objective_grade"] == "NO_EVALUABLE"
    traces = list(csv.DictReader((tmp_path / "traces.csv").read_text(encoding="utf-8-sig").splitlines()))
    assert len(traces) == 96
