"""Reproduce an offline TRS sample-screening report and optional sensitivity audit."""
from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path
from typing import Any

from geoqc.core.evidence import canonical_hash
from geoqc.io.readers import read_shot
from geoqc.masw.adapter import capture_engine_reference
from geoqc.qc.adapter import TraceQCRequest, trace_qc
from geoqc.trs.adapter import build_trs_dossier
from geoqc.trs.contracts import TRSProtocol
from geoqc_app.render_exports import render_export


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--waveform", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--trace-qc", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sensitivity", action="store_true")
    args = parser.parse_args()
    shot = read_shot(args.waveform)
    protocol = TRSProtocol.model_validate_json(args.protocol.read_bytes())
    request = TraceQCRequest.model_validate_json(args.trace_qc.read_bytes())
    if request.operational_policy is None:
        parser.error("Se requiere un perfil con operational_policy explícita")
    document = build_trs_dossier((shot,), protocol, "OFFLINE_SAMPLE_SCREENING_EXAMPLE",
                                  capture_engine_reference().model_dump(mode="json"), request)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "dossier.json").write_text(json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2),
                                             encoding="utf-8")
    for kind in ("HTML", "PDF", "CSV"):
        (args.output / ("dossier." + kind.lower())).write_bytes(render_export(document, kind))
    if args.sensitivity:
        rows: list[dict[str, Any]] = []
        variants = [("base", {}), ("contrast_10", {"contrast_good_db": 10}),
                    ("contrast_15", {"contrast_good_db": 15}), ("coverage_100", {"minimum_coverage": 1}),
                    ("blocks_3", {"reference_blocks": 3}), ("blocks_8", {"reference_blocks": 8}),
                    ("power_ratio_2", {"max_reference_power_ratio": 2}),
                    ("power_ratio_8", {"max_reference_power_ratio": 8})]
        for name, updates in variants:
            policy = type(request.operational_policy).model_validate(
                request.operational_policy.model_dump(mode="json") | updates)
            result = trace_qc(shot, request.model_copy(update={"operational_policy": policy}))
            assessment = result["operational_assessment"]
            rows.append({"variant": name, "policy": policy.model_dump(mode="json"),
                         "policy_hash": canonical_hash(policy), "assessment": assessment})
        (args.output / "sensitivity.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(["variant", "grade", "good", "review", "bad", "not_evaluable", "coverage"])
        for row in rows:
            a = row["assessment"]
            writer.writerow([row["variant"], a["grade"], *a["counts"].values(), a["mean_coverage_fraction"]])
        (args.output / "sensitivity.csv").write_text(stream.getvalue(), encoding="utf-8", newline="")
    print("Informe offline generado; no modifica resultados publicados: " + str(args.output))


if __name__ == "__main__":
    main()
