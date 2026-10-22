"""CLI inicial: validar perfiles y calcular escenarios con geometría explícita."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from geoqc.core.config import load_config, unique_json_pairs
from geoqc.core.models import Geometry, IngestFailure
from geoqc.core.planning import planning
from geoqc.decision import DecisionInput, aggregate
from geoqc.io.readers import try_read_shot
from geoqc.masw.adapter import (
    MASWAdapterInput,
    ReceiverExclusion,
    build_masw_dossier,
    capture_engine_reference,
)
from geoqc.masw.contracts import CurveCalibration, MASWProtocol, PeakCalibration
from geoqc.masw.diagnostic_quality import UsabilityPolicy
from geoqc.masw.report import masw_diagnostics
from geoqc.qc import common_qc
from geoqc.qc.contracts import QCProtocol
from geoqc.trs.contracts import PickCalibration, TRSProtocol
from geoqc.trs.report import trs_diagnostics


def main() -> int:
    parser = argparse.ArgumentParser(prog="geoqc")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate-config", help="Validar un perfil para planificación")
    validate.add_argument("--config", type=Path, required=True)
    plan = sub.add_parser("plan", help="Escenario condicionado; requiere geometría JSON")
    plan.add_argument("--config", type=Path, required=True)
    plan.add_argument("--geometry", type=Path, required=True)
    inspect = sub.add_parser("inspect", help="Leer waveform y metadatos; diagnóstico de ingesta")
    inspect.add_argument("path", type=Path)
    inspect.add_argument("--sidecar", type=Path)
    qc = sub.add_parser("qc", help="QC común diagnóstico con ventanas y supuestos explícitos")
    qc.add_argument("path", type=Path)
    qc.add_argument("--sidecar", type=Path)
    qc.add_argument("--config", type=Path, required=True)
    qc.add_argument("--protocol", type=Path, required=True)
    trs = sub.add_parser("trs", help="Picking y tiempo-distancia TRS diagnóstico")
    trs.add_argument("path", type=Path)
    trs.add_argument("--sidecar", type=Path)
    trs.add_argument("--protocol", type=Path, required=True)
    trs.add_argument("--calibration", type=Path)
    masw = sub.add_parser("masw", help="Coherencia y crestas MASW diagnósticas")
    masw.add_argument("path", type=Path)
    masw.add_argument("--sidecar", type=Path)
    masw.add_argument("--protocol", type=Path, required=True)
    masw.add_argument("--peak-calibration", type=Path)
    masw.add_argument("--curve-calibration", type=Path)
    dossier = sub.add_parser("masw-dossier", help="Dosier MASW local sin renderizado ni aceptación científica")
    dossier.add_argument("path", type=Path)
    dossier.add_argument("--sidecar", type=Path)
    dossier.add_argument("--protocol", type=Path, required=True)
    dossier.add_argument("--policy", type=Path, required=True)
    dossier.add_argument("--revision-id", required=True)
    dossier.add_argument("--sensitivity-receiver", required=True)
    decision = sub.add_parser("decision", help="Agregar requisitos y registros; diagnóstico sin aceptación operativa")
    decision.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "decision":
            decision_input = DecisionInput.model_validate(
                json.loads(args.input.read_text(encoding="utf-8"), object_pairs_hook=unique_json_pairs)
            )
            print(aggregate(decision_input).model_dump_json(indent=2))
            return 0
        if args.command in ("inspect", "qc", "trs", "masw", "masw-dossier"):
            shot = try_read_shot(args.path, sidecar=args.sidecar)
            if isinstance(shot, IngestFailure):
                print(shot.model_dump_json(indent=2))
                return 2
            if args.command == "masw-dossier":
                request = MASWAdapterInput(
                    acquisition_revision_id=args.revision_id,
                    shots=(shot,),
                    protocol=MASWProtocol.model_validate(
                        json.loads(args.protocol.read_text(encoding="utf-8"), object_pairs_hook=unique_json_pairs)
                    ),
                    usability_policy=UsabilityPolicy.model_validate(
                        json.loads(args.policy.read_text(encoding="utf-8"), object_pairs_hook=unique_json_pairs)
                    ),
                    sensitivity_exclusions=(
                        ReceiverExclusion(shot_id=shot.id, receiver_id=args.sensitivity_receiver),
                    ),
                    engine_reference=capture_engine_reference(),
                )
                print(build_masw_dossier(request).to_json())
                return 0
            if args.command == "masw":
                protocol_masw = MASWProtocol.model_validate(
                    json.loads(args.protocol.read_text(encoding="utf-8"), object_pairs_hook=unique_json_pairs)
                )
                peak_calibration = (
                    None
                    if args.peak_calibration is None
                    else PeakCalibration.model_validate(
                        json.loads(
                            args.peak_calibration.read_text(encoding="utf-8"), object_pairs_hook=unique_json_pairs
                        )
                    )
                )
                curve_calibration = (
                    None
                    if args.curve_calibration is None
                    else CurveCalibration.model_validate(
                        json.loads(
                            args.curve_calibration.read_text(encoding="utf-8"), object_pairs_hook=unique_json_pairs
                        )
                    )
                )
                print(
                    json.dumps(
                        masw_diagnostics(
                            shot, protocol_masw, peak_calibration=peak_calibration, curve_calibration=curve_calibration
                        ),
                        ensure_ascii=False,
                        indent=2,
                        allow_nan=False,
                    )
                )
                return 0
            if args.command == "trs":
                protocol_trs = TRSProtocol.model_validate(
                    json.loads(args.protocol.read_text(encoding="utf-8"), object_pairs_hook=unique_json_pairs)
                )
                calibration = (
                    None
                    if args.calibration is None
                    else PickCalibration.model_validate(
                        json.loads(args.calibration.read_text(encoding="utf-8"), object_pairs_hook=unique_json_pairs)
                    )
                )
                result = trs_diagnostics(shot, protocol_trs, calibration)
                print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
                return 0
            if args.command == "qc":
                config = load_config(args.config)
                protocol = QCProtocol.model_validate(
                    json.loads(args.protocol.read_text(encoding="utf-8"), object_pairs_hook=unique_json_pairs)
                )
                result = common_qc(shot, protocol, config)
                print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
                return 0
            result = {
                "shot_id": shot.id,
                "n_channels": shot.data.shape[0],
                "n_samples": shot.data.shape[1],
                "dt_s": shot.dt_s,
                "t0_s": shot.t0_s,
                "receiver_ids": shot.acquisition.receiver_ids,
                "valid_samples_per_channel": shot.valid_mask.sum(axis=1).tolist(),
                "mask_reasons": shot.mask_reasons,
                "input_hashes": shot.input_hashes,
                "scope": "INGEST_DIAGNOSTIC_ONLY",
                "quality_status": None,
                "eligible_for_acceptance": False,
            }
        elif args.command == "validate-config":
            config = load_config(args.config)
            result = {
                "profile": config.profile,
                "profile_state": config.profile_state,
                "config_valid_for": "planning",
                "eligible_for_acceptance": False,
            }
        else:
            config = load_config(args.config)
            geometry = Geometry.model_validate_json(args.geometry.read_text(encoding="utf-8"))
            report = planning(config, geometry)
            result = report.model_dump(mode="json") | {"eligible_for_acceptance": report.eligible_for_acceptance}
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, ValidationError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
