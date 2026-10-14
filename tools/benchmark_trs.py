"""Benchmark registrado: no mide Monte Carlo ni arranque de pyGIMLi externo."""

from __future__ import annotations

import json
import os
import platform
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoqc.synth.trs import two_layer_times  # noqa: E402
from geoqc.trs.contracts import TRSProtocol  # noqa: E402
from geoqc.trs.inversion import invert_two_layer  # noqa: E402
from geoqc.trs.report import trs_diagnostics  # noqa: E402
from tests.synthetic.e4_support import TIME, pick_protocol, trs_shot  # noqa: E402


def benchmark() -> dict:
    rng = np.random.default_rng(41600)
    receivers = np.linspace(1, 72, 24)
    sources = np.linspace(-10, 82, 12)
    protocol = TRSProtocol(
        picking=pick_protocol(),
        branch_error_model="GAUSSIAN_CANDIDATE",
        provenance="synthetic performance, no confidence assignment",
    )
    shots, arrival_tables = [], []
    for source in sources:
        offsets = abs(receivers - source)
        truth = np.array(two_layer_times(offsets, 300, 1500, 5).first_s)
        # Retardo de fuente conocido de 10ms para mantener refinamiento en ventana.
        u = TIME[None, :] - truth[:, None] - 0.01
        clean = np.where(u >= 0, np.exp(-np.maximum(u, 0) / 0.04) * np.cos(2 * np.pi * 80 * u), 0)
        noisy = clean + rng.normal(0, 0.03, clean.shape)
        shots.append(trs_shot(noisy, receiver_x=receivers, source_x=float(source)))
        arrival_tables.append((offsets, truth + rng.normal(0, 0.0005, 24)))
    runtimes = []
    for label in ("FIRST", "WARM"):
        start = time.perf_counter()
        outputs = []
        for shot, (offsets, observed) in zip(shots, arrival_tables, strict=True):
            diagnostic = trs_diagnostics(shot, protocol)
            inverse = invert_two_layer(
                offsets,
                observed,
                sigma_s=np.full(24, 0.0005),
                initial_v1_v2_h=(315, 1400, 5.3),
                max_evaluations=5,
                horizontal_model_verified=True,
                roi_ref="known parametric ROI",
            )
            assert diagnostic["eligible_for_acceptance"] is False and inverse["eligible_for_acceptance"] is False
            outputs.append(inverse["state"])
        elapsed = time.perf_counter() - start
        runtimes.append(
            {
                "run": label,
                "seconds": elapsed,
                "budget_s": 25,
                "performance_status": "WITHIN_BUDGET" if elapsed <= 25 else "WARNING_BUDGET_EXCEEDED",
                "inverse_states": outputs,
            }
        )
    return {
        "channels": 24,
        "shots": 12,
        "runs": runtimes,
        "quality_affected_by_runtime": False,
        "hardware": {
            "cpu_identifier": platform.processor(),
            "registered_reference_cpu": "Intel(R) Core(TM) i5-9400 CPU @ 2.90GHz",
            "registered_reference_physical_cores": 6,
            "logical_cores": os.cpu_count(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "thread_env": {
                name: os.environ.get(name) for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
            },
        },
        "scope": "picking+branch fits by side+12 two-layer diagnostic inversions, independent known-noise arrival tables",
    }


if __name__ == "__main__":
    print(json.dumps(benchmark(), indent=2, allow_nan=False))
