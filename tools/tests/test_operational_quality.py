"""Independent sample faults, metadata abstentions, invariance and holdout controls."""
import copy
import json

import numpy as np
import pytest

from geoqc.io.readers import read_shot
from geoqc.qc.adapter import TraceQCRequest, trace_qc
from geoqc.qc.contracts import SimilarityProtocol, Window
from geoqc.qc.operational import OperationalPolicy, aggregate_screening, line_persistence, morphology
from tools.build_km_demo import demo_trace_qc
from tools.report_trace_quality import synthetic_shot
from tools.tests.test_app_trs import DEMO


def scenario():
    shot, protocol, _ = synthetic_shot(18)
    shot = shot.model_copy(update={"acquisition": shot.acquisition.model_copy(update={
        "technique": "TRS", "wave": "P", "adc_rails": None})})
    protocol = protocol.model_copy(update={"noise_independent": False, "noise_stationarity": "UNKNOWN",
                                           "stationarity_ref": None, "rail_scale_to_data": None})
    return shot, TraceQCRequest(protocol=protocol, operational_policy=OperationalPolicy(reference="Independent test scenario"))


def test_opt_in_preserves_strict_results_metadata_and_samples():
    shot, request = scenario()
    before = shot.data.copy()
    strict = trace_qc(shot, request.model_copy(update={"operational_policy": None}))
    result = trace_qc(shot, request)
    for actual, expected in zip(result["traces"], strict["traces"], strict=True):
        assert actual["quality"] == expected["quality"]
        assert actual["snr"] == expected["snr"]
        assert actual["clip"] == expected["clip"]
    assert result["data_assessment"] == strict["data_assessment"]
    assert result["traces"][0]["operational_quality"]["grade"] == "BUENA"
    assert result["traces"][0]["operational_quality"]["coverage_fraction"] == .75
    assert result["traces"][-1]["operational_quality"]["grade"] == "MALA"
    assert result["traces"][0]["quality"]["assessment_grade"] == "NO_EVALUABLE"
    assert not request.protocol.noise_independent and shot.acquisition.adc_rails is None
    np.testing.assert_array_equal(before, shot.data)
    json.dumps(result, allow_nan=False)


def test_no_reference_zero_noise_and_partial_windows_do_not_produce_good():
    shot, request = scenario()
    for protocol in [request.protocol.model_copy(update={"noise": None}),
                     request.protocol.model_copy(update={"noise": Window(start_s=-2, end_s=-1)})]:
        out = trace_qc(shot, request.model_copy(update={"protocol": protocol}))
        assert out["traces"][0]["operational_quality"]["grade"] == "NO_EVALUABLE"
    data = shot.data.copy()
    data[0, :200] = 0
    out = trace_qc(shot.model_copy(update={"data": data}), request)
    assert out["traces"][0]["operational_quality"]["estimated_contrast"]["state"] == "CENSORED"
    assert out["traces"][0]["operational_quality"]["grade"] != "BUENA"


def test_variable_noise_plateau_and_gaps_trigger_review_without_inventing_adc():
    shot, request = scenario()
    data = shot.data.copy()
    data[0, :50] *= 10
    data[1, 400:410] = 1
    mask = shot.valid_mask.copy()
    mask[2, 300] = False
    out = trace_qc(shot.model_copy(update={"data": data, "valid_mask": mask}), request)
    for t in out["traces"][:3]:
        assert t["operational_quality"]["grade"] == "REGULAR"
    assert out["traces"][1]["operational_quality"]["morphology"]["candidate"]
    assert not out["traces"][1]["operational_quality"]["morphology"]["adc_rails_estimated"]


def test_common_gain_invariance_and_no_empty_support_pass():
    shot, request = scenario()
    original = trace_qc(shot, request)
    scaled = trace_qc(shot.model_copy(update={"data": shot.data * 1000}), request)
    assert [t["operational_quality"]["grade"] for t in original["traces"]] == [
        t["operational_quality"]["grade"] for t in scaled["traces"]]
    np.testing.assert_allclose(original["traces"][0]["operational_quality"]["estimated_contrast"]["db_bounds"],
                               scaled["traces"][0]["operational_quality"]["estimated_contrast"]["db_bounds"], atol=1e-10)
    assert aggregate_screening([], request.operational_policy.id)["grade"] == "NO_EVALUABLE"


def test_stricter_coverage_requires_similarity_and_detects_local_shape_candidate():
    shot, request = scenario()
    similarity = SimilarityProtocol(arrival=request.protocol.signal, neighbor_radius_m=4.1,
                                   min_apparent_velocity_ms=100, max_lag_s=.02,
                                   comparable_channels=False, reference="Synthetic relative-shape scenario")
    request = request.model_copy(update={"protocol": request.protocol.model_copy(update={"similarity": similarity}),
                                          "operational_policy": request.operational_policy.model_copy(update={"minimum_coverage": 1.0})})
    data = shot.data.copy()
    data[8] = np.random.default_rng(991).normal(0, .05, data.shape[1])
    out = trace_qc(shot.model_copy(update={"data": data}), request)
    assert out["traces"][8]["operational_quality"]["grade"] != "BUENA"
    assert not request.protocol.similarity.comparable_channels
    assert out["traces"][8]["similarity"]["state"] == "MISSING"
    assert out["traces"][8]["operational_quality"]["estimated_similarity"]["state"] == "ESTIMATED"
    assert out["traces"][0]["operational_quality"]["grade"] != "BUENA"  # edge has insufficient neighbors


def test_no_noise_only_holdout_trace_is_good_under_declared_scenario():
    shot, request = scenario()
    # Seeds differ from the construction controls; no thresholds selected on KM.
    for seed in (71, 198, 205, 472, 909):
        rng = np.random.default_rng(seed)
        data = rng.normal(0, .05, shot.data.shape)
        out = trace_qc(shot.model_copy(update={"data": data}), request)
        assert all(t["operational_quality"]["grade"] != "BUENA" for t in out["traces"])


def test_km_estimates_keep_original_abstentions_and_uncalibrated_scope():
    shot = read_shot(DEMO / "km40_f1_trs_exploratory.sgy")
    request = TraceQCRequest.model_validate(demo_trace_qc(operational=True))
    raw = copy.deepcopy(request.model_dump(mode="json"))
    out = trace_qc(shot, request)
    assert len(out["traces"]) == 24
    assert all(t["operational_quality"]["estimated_contrast"]["state"] == "ESTIMATED" for t in out["traces"])
    assert all(t["snr"]["state"] == "MISSING" for t in out["traces"])
    assert all(t["similarity"]["state"] == "MISSING" for t in out["traces"])
    assert out["data_assessment"]["grade"] == "NO_EVALUABLE"
    assert not out["operational_assessment"]["eligible_for_acceptance"]
    assert request.model_dump(mode="json") == raw
    assert sum(out["operational_assessment"]["counts"].values()) == 24


def test_morphology_does_not_equate_every_observed_maximum_with_saturation():
    smooth = np.sin(np.arange(1000) * .1)
    assert not morphology(smooth, 3)["candidate"]
    clipped = np.clip(smooth, -.8, .8)
    assert morphology(clipped, 3)["candidate"]
    with pytest.raises(ValueError):
        OperationalPolicy(reference="test", contrast_good_db=3)


def test_line_alert_requires_support_and_persistence_beyond_single_block():
    shot, request = scenario()
    protocol = request.protocol.model_copy(update={"noise": Window(start_s=-.25, end_s=0)})
    data = np.random.default_rng(512).normal(0, 1e-4, shot.data.shape)
    wave = .02 * np.sin(2 * np.pi * 50 * np.arange(250) * shot.dt_s[0])
    data[0, :250] += wave
    trace = {"noise_diagnostics": {"lines": [{"nominal_hz": 50}]}}
    full = line_persistence(shot.model_copy(update={"data": data}), 0, protocol, trace, request.operational_policy)
    assert full[0]["persistent_candidate"] and full[0]["cause"] == "UNIDENTIFIED"
    data[0, 63:250] -= wave[63:250]
    single = line_persistence(shot.model_copy(update={"data": data}), 0, protocol, trace, request.operational_policy)
    assert not single[0]["persistent_candidate"]


@pytest.mark.parametrize("good,expected", [(18, "BUENA"), (15, "REGULAR"), (14, "MALA")])
def test_operational_spread_keeps_requested_integer_boundaries(good, expected):
    rows = [{"operational_quality": {"grade": "BUENA" if i < good else "REGULAR",
             "coverage_fraction": .75, "domains": {"integrity": "SUPPORTED"}}} for i in range(20)]
    assert aggregate_screening(rows, "test")["grade"] == expected
    rows[-1]["operational_quality"]["grade"] = "NO_EVALUABLE"
    out = aggregate_screening(rows, "test")
    assert out["total_traces"] == 20 and out["pending_traces"] == 1
