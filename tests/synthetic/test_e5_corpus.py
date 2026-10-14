import numpy as np
import pytest

from geoqc.masw.contracts import MASWProtocol
from geoqc.masw.report import masw_diagnostics
from geoqc.qc.contracts import Window
from tests.synthetic.e5_support import shot, wilson


@pytest.mark.vid("V-E5-15")
def test_three_hundred_objective_labeled_scenarios_and_missing_evidence(record_property):
    rng = np.random.default_rng(715)
    x, t = np.arange(24) * 2 + 6, np.arange(2000) * 0.001
    protocol = MASWProtocol(
        signal=Window(start_s=0, end_s=2),
        frequencies_hz=(8, 12, 16, 20, 24, 28, 32),
        velocities_ms=tuple(np.arange(100, 401, 5)),
        directions=(1,),
        window="RECTANGULAR",
        provenance="300 objective-label spectral synthetic scenarios",
    )
    rows = []
    for kind in ("OBSERVABLE_CONSTANT_HALFSPACE", "FUNDAMENTAL_ABSENT", "NO_OBSERVED_BAND"):
        errors = []
        false_accepts = 0
        missing = 0
        for _ in range(100):
            velocity = rng.uniform(180, 240)
            observed = velocity if kind != "FUNDAMENTAL_ABSENT" else velocity * 1.4
            data = sum(np.cos(2 * np.pi * f * (t[None, :] - x[:, None] / observed)) for f in protocol.frequencies_hz)
            data += rng.normal(0, 0.05, data.shape)
            if kind == "NO_OBSERVED_BAND":
                data[:] = 0
            result = masw_diagnostics(shot(data, x=x), protocol)
            diagnostic = result["curves"][0]
            if kind == "NO_OBSERVED_BAND":
                assert diagnostic["velocities_ms"] == [None] * 7 and diagnostic["near_geometry"] is None
                errors.append(None)
            else:
                estimate = np.median(diagnostic["velocities_ms"])
                errors.append(float(abs(estimate / velocity - 1)))
            false_accepts += int(result["eligible_for_acceptance"])
            missing += int(
                diagnostic["mode_identity"] != "CONFIRMED" or diagnostic["precision_validity"] != "CALIBRATED"
            )
            assert not result["eligible_for_acceptance"] and diagnostic["validated_bands"] == []
            if kind == "NO_OBSERVED_BAND":
                assert diagnostic["diagnostic_bands"] == [] and diagnostic["mode_identity"] == "UNKNOWN"
        if kind == "OBSERVABLE_CONSTANT_HALFSPACE":
            assert max(errors) < 0.03
        if kind == "FUNDAMENTAL_ABSENT":
            assert min(errors) > 0.2
        rows.append(
            {
                "truth_label": kind,
                "n": 100,
                "objective": "relative error of homogeneous Rayleigh/Vs30 scaling; missing true fundamental",
                "error_relative": errors,
                "error_observed_n": sum(value is not None for value in errors),
                "missing_evidence": missing,
                "false_accepts": false_accepts,
                "false_accept_wilson": wilson(false_accepts, 100),
            }
        )
    record_property(
        "masw_objective_corpus",
        {
            "n": 300,
            "seed": 715,
            "strata": rows,
            "labeling": "independent generated true velocity/error and fundamental availability, not lambda/kappa rule",
            "field_acceptance_enabled": False,
        },
    )


@pytest.mark.vid("V-E5-21")
def test_coherent_traffic_significance_does_not_establish_active_event(record_property):
    from geoqc.masw.statistics import iid_threshold
    from geoqc.masw.transform import phase_shift

    x = np.arange(24) * 2
    traffic = np.exp(-2j * np.pi * 16 * x / 220)[None, :]
    coherence = phase_shift(traffic, [16], x, [200, 220, 240])["coherence"][0, 1]
    threshold = iid_threshold(24, 0.05, hypotheses=100)["threshold"]
    assert coherence > threshold
    t = np.arange(2000) * 0.001
    data = np.cos(2 * np.pi * 16 * (t[None, :] - x[:, None] / 220))
    protocol = MASWProtocol(
        signal=Window(start_s=0, end_s=2),
        frequencies_hz=(16, 20),
        velocities_ms=(200, 220, 240),
        active_event_ref=None,
        provenance="coherent traffic, no active source evidence",
    )
    result = masw_diagnostics(shot(data, x=x), protocol)
    assert not result["eligible_for_acceptance"]
    assert all(curve["band_controls"]["active_event"] == "MISSING" for curve in result["curves"])
    record_property(
        "coherent_noise",
        {
            "coherence": float(coherence),
            "iid_threshold": threshold,
            "event_evidence": "MISSING",
            "source_identity_inferred": False,
            "eligible_for_acceptance": False,
        },
    )
