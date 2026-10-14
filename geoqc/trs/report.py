from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np

from geoqc.core.evidence import canonical_hash
from geoqc.core.models import Shot
from geoqc.trs.branches import fit_branches, horizontal_two_layer_parameters
from geoqc.trs.contracts import PickCalibration, TRSProtocol
from geoqc.trs.inversion import invert_two_layer
from geoqc.trs.picking import pick_shot


def trs_diagnostics(shot: Shot, protocol: TRSProtocol, calibration: PickCalibration | None = None) -> dict[str, Any]:
    if shot.acquisition.technique != "TRS" or shot.acquisition.wave != "P":
        raise ValueError("Diagnóstico TRS exige adquisición TRS/P")
    picks = pick_shot(shot, protocol.picking, calibration)
    missing = [
        "RECIPROCITY_PHYSICAL_PAIRS",
        "ROI_RAY_COVERAGE_AND_RESOLUTION",
        "FIELD_CALIBRATION_G9",
        "HIDDEN_LAYERS_NOT_EXCLUDED",
        "SHARED_CALIBRATION_AND_CLOCK_COVARIANCE",
    ]
    missing += [
        f"{receiver}/TEMPORAL_CONFIDENCE"
        for receiver, pick in zip(shot.acquisition.receiver_ids, picks, strict=True)
        if pick.confidence != "CALIBRATED"
    ]
    offset = shot.geometry.horizontal_offsets_m
    branches: list[dict[str, Any]] = []
    for side, indices in (
        ("LEFT", np.flatnonzero(shot.geometry.xr < shot.geometry.xs)),
        ("RIGHT", np.flatnonzero(shot.geometry.xr > shot.geometry.xs)),
    ):
        valid = [int(j) for j in indices if picks[j].onset_s is not None]
        if len(valid) < 5 or len(np.unique(offset[valid])) != len(valid):
            branches.append(
                {"side": side, "state": "MISSING", "reason": "Menos de cinco offsets únicos con onset por lado"}
            )
            missing.append(f"{side}/BRANCH_SUPPORT")
            continue
        x = np.asarray(offset[valid], dtype=float)
        times = np.asarray([picks[j].onset_s for j in valid], dtype=float) - protocol.source_clock_correction_s
        sigma_values = [picks[j].sigma_s for j in valid]
        all_calibrated = all(sigma is not None and sigma > 0 for sigma in sigma_values)
        sigmas = np.asarray(sigma_values, dtype=float) if all_calibrated else None
        fitted = fit_branches(
            x,
            times,
            sigma_s=sigmas,
            max_segments=protocol.max_segments,
            gaussian_error_model=protocol.branch_error_model == "GAUSSIAN_CANDIDATE",
        )
        parameters = horizontal_two_layer_parameters(fitted, model_verified=protocol.horizontal_two_layers_verified)
        if protocol.horizontal_two_layers_verified and sigmas is not None and len(valid) >= 12:
            inversion = invert_two_layer(
                x,
                times,
                sigma_s=sigmas,
                initial_v1_v2_h=protocol.initial_v1_v2_h,
                max_evaluations=protocol.max_evaluations,
                horizontal_model_verified=True,
                roi_ref=protocol.roi_ref or "",
            )
        else:
            inversion = {
                "state": "MODEL_INAPPLICABLE",
                "reason": "Inversión requiere modelo/ROI y sigmas temporales calibradas",
            }
        branches.append(
            {
                "side": side,
                "receiver_ids": [shot.acquisition.receiver_ids[j] for j in valid],
                "fit": fitted,
                "parameters": parameters,
                "inversion": inversion,
            }
        )
    source = Path(__file__).resolve().parents[1]
    code_hash = canonical_hash(
        {
            p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(source.rglob("*.py"))
        }
    )
    return {
        "schema_version": "1.4",
        "scope": "TRS_DECLARED_DIAGNOSTIC_DOMAIN_ONLY",
        "shot_id": shot.id,
        "picks": [
            {"receiver_id": receiver, "offset_m": float(distance), "arrival": pick.model_dump(mode="json")}
            for receiver, distance, pick in zip(shot.acquisition.receiver_ids, offset, picks, strict=True)
        ],
        "branches": branches,
        "evidence_status": "INCOMPLETE",
        "missing_requirement_ids": missing,
        "eligible_for_acceptance": False,
        "operator_decision": "PENDING",
        "quality_status": None,
        "protocol_hash": canonical_hash(protocol),
        "code_hash": code_hash,
        "data_hashes": shot.input_hashes,
        "calibration_hash": None if calibration is None else canonical_hash(calibration),
        "reason": "Picking/ajustes condicionados; falta soporte de sitio y causas/estratos pueden no ser identificables",
    }
