"""Ejemplo causal TRS, calibración train independiente y diagnóstico reproducible."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoqc.core.evidence import canonical_hash  # noqa: E402
from geoqc.io.readers import read_shot  # noqa: E402
from geoqc.io.writers import write_segy  # noqa: E402
from geoqc.synth.trs import two_layer_times  # noqa: E402
from geoqc.trs.contracts import PickCalibration, TRSProtocol  # noqa: E402
from geoqc.trs.picking import estimator_hash, pick_trace  # noqa: E402
from geoqc.trs.report import trs_diagnostics  # noqa: E402
from tests.synthetic.e4_support import DT, pick_protocol, realization, trs_shot  # noqa: E402


def main() -> None:
    folder = ROOT / "examples/e4"
    folder.mkdir(parents=True, exist_ok=True)
    settings = TRSProtocol(
        picking=pick_protocol(20),
        branch_error_model="GAUSSIAN_CANDIDATE",
        horizontal_two_layers_verified=True,
        geological_model_ref="synthetic 300/1500m/s,h5 known generator",
        initial_v1_v2_h=(315, 1400, 5.3),
        max_evaluations=5,
        roi_ref="synthetic horizontal 0..10m",
        source_clock_correction_s=0.03,
        time_correction_ref="known synthetic source latency +30ms",
        provenance="examples/e4, declared synthetic domain only",
    )
    rng = np.random.default_rng(4420)
    errors = []
    for _ in range(2000):
        samples, onset = realization(rng, 20)
        pick = pick_trace(trs_shot(samples), 0, settings.picking)
        if pick.onset_s is not None:
            errors.append(pick.onset_s - onset)
    calibration = PickCalibration(
        domain_id=settings.picking.domain_id,
        protocol_hash=canonical_hash(settings.picking),
        estimator_hash=estimator_hash(),
        dt_s=DT,
        errors_s=tuple(errors),
        training_ref="train seed4420,n2000,requirements_e4.md",
    )
    (folder / "calibration.json").write_text(calibration.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (folder / "protocol.json").write_text(settings.model_dump_json(indent=2) + "\n", encoding="utf-8")
    waveform = folder / "causal_trs.sgy"
    if not waveform.exists():
        rng = np.random.default_rng(202610054)
        receivers = np.linspace(3, 24, 24)
        arrivals = np.array(two_layer_times(receivers, 300, 1500, 5).first_s) + 0.03
        data = []
        for onset in arrivals:
            samples, _ = realization(rng, 20, onset=float(onset))
            data.append(samples)
        write_segy(waveform, trs_shot(np.array(data), receiver_x=receivers))
    report = trs_diagnostics(read_shot(waveform), settings, calibration)
    (folder / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "example": "examples/e4/causal_trs.sgy",
                "calibration": "SYNTHETIC_ONLY",
                "identified_picks": sum(row["arrival"]["onset_s"] is not None for row in report["picks"]),
                "eligible_for_acceptance": report["eligible_for_acceptance"],
            }
        )
    )


if __name__ == "__main__":
    main()
