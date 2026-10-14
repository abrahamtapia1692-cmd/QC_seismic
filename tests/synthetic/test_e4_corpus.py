import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from geoqc.synth.trs import two_layer_times
from geoqc.trs.branches import layered_first_times
from geoqc.trs.contracts import TRSProtocol
from geoqc.trs.inversion import invert_two_layer
from geoqc.trs.report import trs_diagnostics
from tests.synthetic.e4_support import TIME, pick_protocol, record, trs_shot, wilson


@pytest.mark.vid("V-E4-16")
def test_registered_performance_and_quality_separation(record_property):
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", PYTHONUTF8="1")
    completed = subprocess.run(
        [sys.executable, str(root / "tools/benchmark_trs.py")],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["channels"] * result["shots"] == 288
    assert result["quality_affected_by_runtime"] is False
    assert [entry["run"] for entry in result["runs"]] == ["FIRST", "WARM"]
    record(record_property, "registered_performance", result)


@pytest.mark.vid("V-E4-17")
def test_three_hundred_independently_labeled_scenarios(record_property):
    rng = np.random.default_rng(41700)
    counts = {"recoverable": 0, "ambiguous": 0, "unacceptable": 0}
    results = []
    x = np.linspace(1, 120, 120)
    for index in range(300):
        kind = ("recoverable", "ambiguous", "unacceptable")[index % 3]
        if kind == "recoverable":
            v1 = rng.uniform(280, 320)
            v2 = rng.uniform(1400, 1600)
            h = rng.uniform(4.5, 5.5)
            data = np.array(two_layer_times(x, v1, v2, h).first_s) + rng.normal(0, 0.0005, 120)
            estimate = invert_two_layer(
                x,
                data,
                sigma_s=np.full(120, 0.0005),
                initial_v1_v2_h=(300, 1500, 5),
                max_evaluations=80,
                horizontal_model_verified=True,
                roi_ref="known recoverable two-layer family",
            )
            good = estimate["state"] == "VALID" and max(abs(np.array(estimate["velocities_ms"]) / [v1, v2] - 1)) <= 0.10
            counts[kind] += int(good)
        elif kind == "ambiguous":
            h = rng.uniform(4.5, 5.5)
            middle = rng.uniform(0.2, 0.5)
            data = layered_first_times(x, (300, 600, 1500), (h, middle))
            heq = (
                (2 * h / 300 * np.sqrt(1 - (300 / 1500) ** 2) + 2 * middle / 600 * np.sqrt(1 - (600 / 1500) ** 2))
                * 300
                / (2 * np.sqrt(1 - (300 / 1500) ** 2))
            )
            equivalent = np.array(two_layer_times(x, 300, 1500, heq).first_s)
            np.testing.assert_allclose(data, equivalent, atol=1e-15)
            estimate = invert_two_layer(
                x,
                data,
                sigma_s=np.full(120, 0.0005),
                initial_v1_v2_h=(300, 1500, 5),
                max_evaluations=80,
                horizontal_model_verified=True,
                roi_ref="first-arrival equivalent family",
            )
            counts[kind] += int(
                estimate["eligible_for_acceptance"] is False and estimate["resolution_state"] == "LOCAL_PARAMETRIC_ONLY"
            )
        else:
            noisy = rng.normal(0, 0.01, (24, TIME.size))
            noisy[0] = 0
            protocol = TRSProtocol(picking=pick_protocol(), provenance="dead mandatory trace independent label")
            estimate = trs_diagnostics(trs_shot(noisy), protocol)
            counts[kind] += int(estimate["picks"][0]["arrival"]["confidence"] == "MISSING")
            assert estimate["evidence_status"] == "INCOMPLETE"
        assert estimate["eligible_for_acceptance"] is False
        results.append({"class": kind, "acceptance": False})
    assert counts["recoverable"] >= 95 and counts["ambiguous"] == 100 and counts["unacceptable"] == 100
    record(
        record_property,
        "trs_scenario_corpus",
        {
            "n": 300,
            "per_stratum": 100,
            "diagnostic_success": counts,
            "wilson95": {key: wilson(value, 100) for key, value in counts.items()},
            "acceptance_enabled_count": 0,
            "ambiguity": "equivalent first arrivals; local two-layer fit can pass without identifying true layer count",
        },
    )
