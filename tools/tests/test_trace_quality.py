"""Pruebas de la política local y del dosier, sin declarar un gate científico nuevo."""

import json

import numpy as np
import pytest

from geoqc.qc.quality import COLORS, TraceQualityPolicy, aggregate_quality, trace_quality
from tools.report_trace_quality import field_records, html_report, qc_record, synthetic_shot, trace_figure


@pytest.mark.parametrize(
    "good,total,expected",
    [
        (90, 100, "BUENA"),
        (89, 100, "REGULAR"),
        (899, 1000, "REGULAR"),
        (75, 100, "REGULAR"),
        (74, 100, "MALA"),
        (749, 1000, "MALA"),
        (0, 10, "MALA"),
        (10, 10, "BUENA"),
        (0, 0, None),
    ],
)
def test_percentage_boundaries_without_rounding(good, total, expected):
    summary = aggregate_quality(["BUENA"] * good + ["REGULAR"] * (total - good))
    assert summary["grade"] == expected
    assert summary["total_traces"] == total
    assert summary["good_percent"] == (100 * good / total if total else None)


def valid_trace(snr=20, clip=0):
    return {
        "statistics": {"state": "VALID", "dead": False, "constant": False},
        "valid_fraction": 1,
        "snr": {"state": "VALID", "value": snr},
        "clip": {"state": "VALID", "value": clip},
    }


@pytest.mark.parametrize(
    "snr,clip,expected",
    [
        (12, 0.001, "BUENA"),
        (11.999, 0, "REGULAR"),
        (6, 0, "REGULAR"),
        (5.999, 0, "MALA"),
        (20, 0.001001, "REGULAR"),
        (20, 0.01, "MALA"),
    ],
)
def test_trace_thresholds(snr, clip, expected):
    result = trace_quality(valid_trace(snr, clip), TraceQualityPolicy())
    assert result["grade"] == expected
    assert result["color"] == COLORS[expected]


def test_missing_evidence_cannot_be_good_and_dead_channel_overrides_it():
    trace = valid_trace()
    trace["clip"] = {"state": "MISSING", "reason": "Rails ausentes"}
    result = trace_quality(trace, TraceQualityPolicy())
    assert result["grade"] == "REGULAR"
    assert not result["evidence_complete"]
    trace["statistics"]["dead"] = True
    assert trace_quality(trace, TraceQualityPolicy())["grade"] == "MALA"


def test_gaps_and_amplitude_anomalies_are_reported():
    trace = valid_trace()
    trace["valid_fraction"] = 0.99
    trace["statistics"]["amplitude_anomaly"] = True
    result = trace_quality(trace, TraceQualityPolicy())
    assert result["grade"] == "REGULAR"
    assert len(result["reasons"]) == 2


def test_zero_noise_is_not_infinite_good_snr_but_unresolved_net_signal_is_bad():
    trace = valid_trace()
    trace["snr"] = {"state": "CENSORED", "details_json": '{"noise_power":0}'}
    assert trace_quality(trace, TraceQualityPolicy())["grade"] == "REGULAR"
    trace["snr"]["details_json"] = '{"noise_power":1,"snr_net_ratio":0}'
    assert trace_quality(trace, TraceQualityPolicy())["grade"] == "MALA"


@pytest.mark.parametrize("good,expected_grade", [(18, "BUENA"), (15, "REGULAR"), (14, "MALA")])
def test_waveforms_classify_known_faults_and_aggregate(good, expected_grade):
    shot, protocol, expected = synthetic_shot(good)
    original = shot.data.copy()
    record = qc_record(shot, protocol, site="Test", kind="SINTÉTICO", source="fixture")
    assert [t["quality"]["grade"] for t in record["traces"]] == expected
    assert record["quality"]["grade"] == expected_grade
    np.testing.assert_array_equal(shot.data, original)
    assert record["traces"][-1]["quality"]["grade"] == "MALA"
    json.dumps(record["traces"], allow_nan=False)


def test_group_aggregation_weights_channels_instead_of_records():
    # 9/10 and 1/2: average record percentage is 70%, but actual good fraction is 10/12.
    result = aggregate_quality(["BUENA"] * 9 + ["MALA"] + ["BUENA", "REGULAR"])
    assert result["grade"] == "REGULAR"
    assert result["good_percent"] == pytest.approx(1000 / 12)


def test_invalid_category_and_policy_fail_explicitly():
    with pytest.raises(ValueError):
        aggregate_quality(["UNKNOWN"])
    with pytest.raises(ValueError):
        TraceQualityPolicy(snr_good_min_db=5)
    with pytest.raises(ValueError):
        TraceQualityPolicy(clip_good_max_fraction=0.5)


def test_actual_field_channels_are_preserved_and_missing_evidence_disclosed():
    records, hashes = field_records()
    assert len(records) == 11
    assert sum(len(r["traces"]) for r in records) == 432
    assert hashes
    for record in records:
        bad = 2 if record["site"] == "Chevremont" and record["id"] == "0m" else 0
        assert record["quality"]["counts"] == {"BUENA": 0, "REGULAR": len(record["traces"]) - bad, "MALA": bad}
        assert record["quality"]["grade"] == "MALA"
        assert all(not t["quality"]["evidence_complete"] for t in record["traces"])
        if bad:
            assert [t["channel_1based"] for t in record["traces"] if t["quality"]["grade"] == "MALA"] == [7, 29]
            assert record["traces"][6]["similarity"]["median_abs_rho"] == pytest.approx(0.201, abs=0.001)
            assert record["traces"][28]["similarity"]["median_abs_rho"] == pytest.approx(0.272, abs=0.001)


def test_plots_use_classification_colors_and_html_embeds_them(tmp_path):
    import matplotlib.pyplot as plt

    shot, protocol, _ = synthetic_shot(18)
    record = qc_record(shot, protocol, site="Test", kind="SINTÉTICO", source="<unsafe>")
    fig = trace_figure(record)
    assert [line.get_color() for line in fig.axes[0].lines] == [t["quality"]["color"] for t in record["traces"]]
    fig.savefig(tmp_path / "plot.png")
    fig.savefig(tmp_path / "summary.png")
    plt.close(fig)
    record["plot"] = "plot.png"
    html = html_report({"records": [record], "groups": [], "generated_at_utc": "test"}, tmp_path)
    assert html.count('data-grade="') == 20
    assert "data:image/png;base64," in html
    assert "&lt;unsafe&gt;" in html
    assert "<unsafe>" not in html
