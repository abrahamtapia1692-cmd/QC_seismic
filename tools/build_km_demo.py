"""Build a KM40/F1 upload example with visible, unverified exploratory assumptions."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoqc.io.binary import parse_seg2  # noqa: E402
from geoqc.io.contracts import IngestContext  # noqa: E402
from geoqc.io.readers import read_shot  # noqa: E402
from geoqc.masw.contracts import MASWProtocol  # noqa: E402
from geoqc.masw.transform import shot_spectrum  # noqa: E402
from geoqc.qc.adapter import TraceQCRequest  # noqa: E402
from geoqc.trs.contracts import TRSProtocol  # noqa: E402
from tools.prepare_km_app import convert, sha256, write_document  # noqa: E402

ASSUMPTIONS = (
    "EXPLORATORY DEMO ONLY; NOT VERIFIED FIELD METADATA. "
    "All source/receiver elevations are assumed 0 m, not measured. "
    "Coordinate uncertainties are set to 0 m only to omit geometric uncertainty from this model, "
    "not to claim perfect positioning. "
    "One unstacked hit per file and stored samples in V are hypotheses; original STACK=0 is retained. "
    "Channel-to-receiver correspondence follows SEG-2 CHANNEL_NUMBER and trace order, not an independent survey. "
    "TRS acquisition is reused for apparent MASW exploration, not certified as a MASW field campaign. "
    "User confirms vertical geophones, DAQLink 4, hammer switch, no pretrigger, "
    "and F1 at x=-15 m before receiver 1; receiver spacing 5 m comes from field notes."
)


def demo_trace_qc(*, operational: bool = False) -> dict:
    """Explicit exploratory windows; no invented independence or comparability."""
    noise = {"start_s": 1.5, "end_s": 2.0}
    signal = {"start_s": 0.0, "end_s": 0.5}
    provenance = ("KM40 F1 EXPLORATORY: analysis [0,2) s; signal [0,0.5) s and posterior "
                  "reference [1.5,2) s reuse the declared picking windows. "
                  "Reference assumed signal-free; independence and transfer to signal NOT verified. "
                  "No ADC rails/scale verified. No instrumental comparability verified. "
                  "No filtering or calibration of first-arrival accuracy.")
    body = {
        "protocol": {"analysis": {"start_s": 0, "end_s": 2}, "signal": signal, "noise": noise,
                     "noise_independent": False, "noise_stationarity": "UNKNOWN",
                     "frequency_band_hz": [40, 160], "provenance": provenance,
                     "similarity": {"arrival": signal, "neighbor_radius_m": 10.1,
                                    "min_apparent_velocity_ms": 100, "max_lag_s": 0.02,
                                    "comparable_channels": False, "reference": provenance +
                                    " Neighborhood/lag are draft scenarios; do not assert comparability."}},
        "noise": {"noise": noise, "signal": signal, "reference_kind": "POST_SIGNAL", "reference": provenance},
    }
    if operational:
        body["operational_policy"] = {
            "reference": "docs/trs_operational_quality.md; fixed declared windows; local screening thresholds, "
                         "not field-calibrated acceptance. Metadata and strict QC preserved."}
    return TraceQCRequest.model_validate(body).model_dump(mode="json")


def build(output: Path, technique: str = "MASW") -> None:
    if output.exists():
        raise ValueError("Elija un directorio nuevo; no se sobrescribe un ejemplo")
    partial = ROOT / "examples/km_app/preparation/KM_40_672_F1.metadata.in_progress.json"
    document = json.loads(partial.read_bytes())
    source = ROOT / document["source_file"]
    if sha256(source) != document["source_sha256"]:
        raise ValueError("El original no coincide con el inventario")
    waveform = parse_seg2(source.read_bytes())
    n = len(waveform.traces)
    ids = [f'ch{int(header["CHANNEL_NUMBER"]):02d}' for header in waveform.headers["trace_headers"]]
    context = document["context"]
    assumptions = ASSUMPTIONS if technique == "MASW" else ASSUMPTIONS.replace(
        "TRS acquisition is reused for apparent MASW exploration, not certified as a MASW field campaign.",
        "TRS first-arrival exploration; no verified geological model or temporal calibration. "
        "The post-signal noise reference window is assumed signal-free, not validated in the field.")
    context["shot_id"] = f"KM40_F1_{technique}_EXPLORATORY_ASSUMPTIONS"
    context["acquisition"].update(technique=technique, wave="P" if technique == "TRS" else "RAYLEIGH", receiver_ids=ids,
                                  amplitude_unit="V", stack_count=1, stack_kind="RAW")
    context["geometry"].update(zr=[0.0]*n, zs=0.0, uncertainty_m=[0.0]*n)
    context["geometry"]["provenance"].append(assumptions)
    context["provenance"] = assumptions + " " + context["provenance"]
    context = IngestContext.model_validate(context).model_dump(mode="json")
    document.update(context=context, status="EXPLORATORY_ASSUMPTIONS_ONLY", confirmed=True,
                    confirmation_scope="EXPLICIT_DEMO_CONFIGURATION_NOT_FIELD_VERIFICATION",
                    field_metadata_verified=False, assumptions=assumptions,
                    review_notes="User requests zero elevations/uncertainty for testing. " + assumptions)
    output.mkdir(parents=True)
    metadata = output / "assumptions.json"
    write_document(metadata, document)
    target = output / ("km40_f1_trs_exploratory.sgy" if technique == "TRS" else "km40_f1_exploratory.sgy")
    convert(metadata, target, technique=technique)
    # The generic writer selects header geometry and generic export provenance.
    # Keep this demo's assumed geometry and nominal switch timing authoritative.
    sidecar = target.with_suffix(target.suffix + ".json")
    exported = IngestContext.model_validate(json.loads(sidecar.read_bytes()) | {
        "geometry_policy": "SIDECAR", "provenance": context["provenance"],
        "time_reference": "SIDECAR_AUTHORITATIVE", "t0_s": context["t0_s"],
    })
    sidecar.write_text(exported.model_dump_json(indent=2) + "\n", encoding="utf-8")
    restored = read_shot(target)
    original = np.stack(waveform.traces)
    if not np.array_equal(original, restored.data):
        raise ValueError("Las muestras cambiaron")
    draft = ROOT / "examples/km_app/preparation/KM_40_672_F1.protocol.draft.json"
    protocol: MASWProtocol | TRSProtocol
    if technique == "TRS":
        protocol = TRSProtocol.model_validate({
            "picking": {"search": {"start_s": 0, "end_s": 0.5},
                        "noise": {"start_s": 1.5, "end_s": 2.0},
                        "noise_position": "DECLARED_POST_SIGNAL", "domain_id": "KM40-F1-EXPLORATORY-TRS",
                        "provenance": assumptions},
            "branch_error_model": "UNKNOWN", "horizontal_two_layers_verified": False,
            "provenance": assumptions,
        })
        window_samples = None
    else:
        protocol = MASWProtocol.model_validate(json.loads(draft.read_bytes()) | {
        "signal": {"start_s": 0.0, "end_s": original.shape[1] * restored.dt_s[0]},
        "domain_id": "KM40-F1-EXPLORATORY-ASSUMED-FLAT-SINGLE-HIT-VOLTS",
            "provenance": assumptions,
        })
        window_samples = shot_spectrum(restored, protocol)["window_samples"]
    write_document(output / "protocol.json", protocol.model_dump(mode="json"))
    if technique == "TRS":
        write_document(output / "trace_qc.json", demo_trace_qc())
        write_document(output / "trace_qc_operational.json", demo_trace_qc(operational=True))
    manifest = {
        "scope": "LOADABLE_EXPLORATORY_EXAMPLE_NOT_FIELD_VALIDATION",
        "technique": technique, "assumptions": assumptions,
        "original": {"path": document["source_file"], "sha256": sha256(source)},
        "waveform": target.name, "sidecar": target.name + ".json", "protocol": "protocol.json",
        "trace_qc": "trace_qc.json" if technique == "TRS" else None,
        "sensitivity_receiver": ids[-1] if technique == "MASW" else None,
        "sensitivity_note": ("Last-channel exclusion is a sensitivity variant, not a bad-channel finding."
                             if technique == "MASW" else "Not applicable to TRS; no receiver exclusion requested."),
        "samples_unchanged": True, "channels": n, "samples_per_channel": original.shape[1],
        "window_samples": window_samples, "field_metadata_verified": False,
        "sufficiency": "NOT_DEMONSTRATED", "eligible_for_acceptance": False,
        "sha256": {path.name: sha256(path) for path in sorted(output.glob("*")) if path.is_file()},
    }
    write_document(output / "manifest.json", manifest)
    print(f"Ejemplo exploratorio {technique} generado: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--technique", choices=("MASW", "TRS"), default="MASW")
    args = parser.parse_args()
    build(args.output, args.technique)


if __name__ == "__main__":
    main()
