from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from geoqc.core.evidence import canonical_hash
from geoqc.core.models import Shot
from geoqc.masw.contracts import CurveCalibration, MASWProtocol, PeakCalibration
from geoqc.masw.curves import contiguous_bands, near_ratios, refine_peak_velocities, ridge_path
from geoqc.masw.r1 import SUPPLEMENT_HASH, ModalApproval, ModalEvidence, resolve_modes
from geoqc.masw.statistics import empirical_max_threshold, estimator_hash, uncertainty_from_errors
from geoqc.masw.transform import phase_shift, shot_spectrum


def masw_diagnostics(
    shot: Shot,
    protocol: MASWProtocol,
    *,
    peak_calibration: PeakCalibration | None = None,
    curve_calibration: CurveCalibration | None = None,
    modal_evidence: Mapping[str, ModalEvidence] | None = None,
    modal_approvals: Mapping[str, ModalApproval] | None = None,
) -> dict[str, Any]:
    observed = shot_spectrum(shot, protocol)
    f, c = observed["frequencies_hz"], np.array(protocol.velocities_ms)
    protocol_hash, code_hash = canonical_hash(protocol.model_dump(mode="json")), estimator_hash()
    geometry_hash = canonical_hash(
        {
            "x_m": observed["x_m"].tolist(),
            "weights": observed["weights"].tolist(),
            "receiver_ids": shot.acquisition.receiver_ids,
        }
    )
    curves = []
    for direction in protocol.directions:
        transformed = phase_shift(
            observed["spectrum"], f, observed["x_m"], c, direction=direction, weights=observed["weights"]
        )
        score, n = transformed["coherence"], transformed["n_active"]
        path = ridge_path(
            score, f, c, slope_scale_ms_per_hz=protocol.ridge_slope_scale_ms_per_hz, penalty=protocol.ridge_penalty
        )
        velocities = refine_peak_velocities(score, f, c, path)
        support = [
            tuple(shot.acquisition.receiver_ids[j] for j in np.flatnonzero(row)) for row in transformed["active"]
        ]
        support_hashes = tuple(canonical_hash(ids) for ids in support)

        def compatible(
            calibration: PeakCalibration | CurveCalibration | None,
            counts: Any = n,
            support_refs: tuple[str, ...] = support_hashes,
        ) -> bool:
            return (
                calibration is not None
                and calibration.protocol_hash == protocol_hash
                and calibration.estimator_hash == code_hash
                and protocol.domain_id == calibration.domain_id
                and calibration.geometry_hash == geometry_hash
                and calibration.dt_s == shot.dt_s[0]
                and all(int(count) == calibration.n_active for count in counts)
                and len(set(support_refs)) == 1
            )

        peak_ok = compatible(peak_calibration)
        curve_ok = (
            compatible(curve_calibration)
            and curve_calibration is not None
            and curve_calibration.direction == direction
            and np.array_equal(curve_calibration.frequencies_hz, f)
        )
        threshold = (
            None
            if not peak_ok or peak_calibration is None
            else empirical_max_threshold(peak_calibration.maximum_scores, peak_calibration.alpha)
        )
        precision = None
        precision_reason = "INCOMPATIBLE_OR_MISSING_CALIBRATION"
        if curve_ok and curve_calibration is not None:
            try:
                precision = uncertainty_from_errors(velocities, curve_calibration.errors_ms)
                precision_reason = "COMPATIBLE_DECLARED_TRAINING_DOMAIN"
            except ValueError as exc:
                curve_ok = False
                precision_reason = str(exc)
        point_score = score[np.arange(f.size), path]
        observed_mask = (n >= 2) & (point_score > 0)
        modal = resolve_modes(
            reference=protocol.mode_evidence_ref,
            requested=protocol.mode_identity,
            shot_hash=canonical_hash(shot),
            protocol_hash=protocol_hash,
            estimator_hash=code_hash,
            domain_id=protocol.domain_id,
            direction=direction,
            frequencies_hz=tuple(f.tolist()),
            support_hashes=support_hashes,
            observed=tuple(bool(v) for v in observed_mask),
            evidence=modal_evidence,
            approvals=modal_approvals,
        )
        # Se presenta cresta observada, incluso sin confianza; no se inventa banda validada.
        max_gap = float(np.min(np.diff(f))) * 1.01
        bands = contiguous_bands(f, observed_mask, max_gap_hz=max_gap, support_refs=support_hashes)
        active_positions = np.flatnonzero(observed["weights"] > 0)
        radial = shot.geometry.horizontal_offsets_m[active_positions]
        geometry = near_ratios(radial, velocities / f) if radial.size and np.all(observed_mask) else None
        curves.append(
            {
                "direction": direction,
                "frequencies_hz": f.tolist(),
                "velocities_ms": [
                    float(v) if valid else None for v, valid in zip(velocities, observed_mask, strict=True)
                ],
                "point_reasons": [
                    "OBSERVED_DIAGNOSTIC_ONLY" if valid else "NO_OBSERVED_ENERGY_OR_SUPPORT" for valid in observed_mask
                ],
                "coherence": point_score.tolist(),
                "coherence_is_modal_energy": False,
                **modal,
                "n_active": n.tolist(),
                "support": support,
                "point_provenance": [f"{shot.id}:d{direction}:f{frequency:g}" for frequency in f],
                "precision": precision,
                "precision_validity": "CALIBRATED" if curve_ok else "UNCALIBRATED",
                "precision_reason": precision_reason,
                "significance": {
                    "threshold": threshold,
                    "null_unit": "MAXIMUM_OVER_COMPLETE_PROTOCOL_GRID",
                    "validity": "CALIBRATED" if peak_ok else "UNCALIBRATED",
                    "exceeds": None if threshold is None else (point_score > threshold).tolist(),
                },
                "near_geometry": geometry,
                "diagnostic_bands": bands,
                "validated_bands": [],
                "band_controls": {
                    "data": observed_mask.tolist(),
                    "net_snr": "UNKNOWN",
                    "relative_response": "UNKNOWN",
                    "alias": "UNRESOLVED_REAL_KERNEL",
                    "nearfield_bias": "UNCALIBRATED",
                    "mode": modal["mode_identity"],
                    "active_event": "REFERENCED" if protocol.active_event_ref else "MISSING",
                },
                "nearfield_calibration_ref": protocol.nearfield_calibration_ref,
            }
        )
    return {
        "schema_version": "1.4-r1",
        "specification_version": "1.4",
        "document_revision": "MASW-R1",
        "supplement_hash": SUPPLEMENT_HASH,
        "input_protocol_schema_version": protocol.schema_version,
        "scientific_shot_hash": canonical_hash(shot),
        "shot_id": shot.id,
        "technique": "MASW",
        "curves": curves,
        "preprocessing": {
            "window": protocol.window,
            "window_samples": observed["window_samples"],
            "original_preserved": True,
            "channel_exclusions": observed["excluded"],
        },
        "protocol_hash": protocol_hash,
        "estimator_hash": code_hash,
        "geometry_hash": geometry_hash,
        "input_hashes": shot.input_hashes,
        "scope": "DECLARED_SYNTHETIC_MASW_DIAGNOSTIC_ONLY",
        "eligible_for_acceptance": False,
        "operator_decision": "PENDING",
        "vs30_sufficiency": "NOT_ESTABLISHED",
        "missing_requirements": [
            *(["verified_modal_identity"] if any(c["mode_identity"] != "CONFIRMED" for c in curves) else []),
            "observed_net_snr",
            "relative_instrument_response",
            "alias_identification",
            "compatible_nearfield_calibration",
            "site_resolution",
            "G9_field_validation",
        ],
        "calibration_refs": [cal.training_ref for cal in (peak_calibration, curve_calibration) if cal is not None],
    }
