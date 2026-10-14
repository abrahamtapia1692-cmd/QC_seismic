"""Diagnostic union preserving observations and full joint covariance."""

from __future__ import annotations

from typing import Any

import numpy as np

from geoqc.core.evidence import canonical_hash
from geoqc.core.models import DispersionCurve
from geoqc.masw.r1 import CurveR1, JointCovariance, migrate_curve, numerical_tolerance


def merge_curves(
    curves: tuple[DispersionCurve | CurveR1, ...],
    *,
    covariance: JointCovariance | None = None,
    compatibility_sigma: float | None = None,
) -> dict[str, Any]:
    if compatibility_sigma is not None and (not np.isfinite(compatibility_sigma) or compatibility_sigma <= 0):
        raise ValueError("Criterio de comparación positivo finito requerido")
    sources = tuple(
        migrate_curve(c) if isinstance(c, DispersionCurve) else CurveR1.model_validate(c.model_dump()) for c in curves
    )
    points: dict[float, list[dict[str, Any]]] = {}
    unique: dict[str, dict[str, Any]] = {}
    for curve in sources:
        for i, frequency in enumerate(curve.frequencies_hz):
            row: dict[str, Any] = {
                "point_id": curve.point_ids[i],
                "frequency_hz": frequency,
                "velocity_ms": curve.velocities_ms[i],
                "sigma_ms": curve.sigma_ms[i],
                "valid": curve.valid_mask[i],
                "reason": curve.reasons[i],
                "mode_identity": curve.mode_identity,
                "declared_mode_identity": curve.declared_mode_identity,
                "mode_label": curve.mode_labels[i],
                "support_ref": curve.support_refs[i],
                "provenance": curve.point_provenance[i],
                "band_refs": curve.band_refs,
                "covariance_ref": curve.covariance_ref,
                "velocity_kind": curve.velocity_kind,
            }
            point_id = curve.point_ids[i]
            if point_id in unique and row != unique[point_id]:
                raise ValueError("Una identidad de observación tiene contenidos incompatibles")
            duplicate = point_id in unique
            unique[point_id] = row
            points.setdefault(frequency, []).append(row | {"duplicate_of": point_id if duplicate else None})
    matrix = None
    indices: dict[str, int] = {}
    tolerance = 0.0
    if covariance is not None:
        covariance = JointCovariance.model_validate(covariance.model_dump())
        if set(covariance.point_ids) != set(unique):
            raise ValueError("Covarianza no corresponde exactamente a las identidades de observación")
        matrix = np.asarray(covariance.matrix)
        tolerance = numerical_tolerance(matrix)
        indices = {point_id: i for i, point_id in enumerate(covariance.point_ids)}
        for point_id, row in unique.items():
            sigma = row["sigma_ms"]
            if sigma is not None and abs(matrix[indices[point_id], indices[point_id]] - sigma**2) > tolerance:
                raise ValueError("Diagonal de covarianza incompatible con sigma de la curva")
    output = []
    contrasts: list[np.ndarray[Any, Any]] = []
    contrast_ids = []
    for frequency, rows in sorted(points.items()):
        usable = [row for row in rows if row["valid"] and row["duplicate_of"] is None]
        pair_results = []
        for j, left in enumerate(usable):
            for right in usable[j + 1 :]:
                compatible: bool | None = None
                reason = "UNKNOWN_MODALITY_SUPPORT_COVARIANCE_OR_CRITERION"
                variance = None
                delta = left["velocity_ms"] - right["velocity_ms"]
                known = all(row["mode_label"] is not None and row["support_ref"] is not None for row in (left, right))
                mismatch = (
                    left["mode_label"] is not None
                    and right["mode_label"] is not None
                    and left["mode_label"] != right["mode_label"]
                ) or (
                    left["support_ref"] is not None
                    and right["support_ref"] is not None
                    and left["support_ref"] != right["support_ref"]
                )
                if mismatch:
                    compatible, reason = False, "INCOMPATIBLE_MODE_OR_SUPPORT"
                elif known and matrix is not None:
                    contrast = np.zeros(len(indices))
                    contrast[indices[left["point_id"]]] = 1
                    contrast[indices[right["point_id"]]] = -1
                    variance = float(contrast @ matrix @ contrast)
                    if variance < -2 * tolerance:
                        raise ValueError("Varianza de diferencia negativa fuera de tolerancia numérica")
                    variance = max(0.0, variance)
                    contrasts.append(contrast)
                    contrast_ids.append([left["point_id"], right["point_id"]])
                    if variance <= 2 * tolerance:
                        roundoff = 64 * np.finfo(float).eps * max(abs(left["velocity_ms"]), abs(right["velocity_ms"]))
                        compatible = bool(abs(delta) <= roundoff)
                        reason = "DETERMINISTIC_DIFFERENCE"
                    elif compatibility_sigma is not None:
                        compatible = bool(abs(delta) <= compatibility_sigma * np.sqrt(variance))
                        reason = "POINTWISE_DECLARED_CRITERION_ONLY"
                pair_results.append(
                    {
                        "point_ids": [left["point_id"], right["point_id"]],
                        "compatible": compatible,
                        "reason": reason,
                        "difference_ms": delta,
                        "variance_difference_ms2": variance,
                    }
                )
        states = [pair["compatible"] for pair in pair_results]
        state = (
            False
            if any(value is False for value in states)
            else True
            if states and all(value is True for value in states)
            else None
        )
        output.append(
            {
                "frequency_hz": frequency,
                "contributions": rows,
                "compatible_overlap": state,
                "compatibility_status": "INCOMPATIBLE"
                if state is False
                else "POINTWISE_COMPATIBLE"
                if state
                else "UNKNOWN",
                "reason": "NO_INDEPENDENT_OVERLAP" if not states else "SEE_PAIRWISE_REASONS",
                "pairwise": pair_results,
            }
        )
    joint = None
    if contrasts and matrix is not None and covariance is not None:
        transform = np.asarray(contrasts)
        values = np.array([unique[point_id]["velocity_ms"] for point_id in covariance.point_ids])
        delta_vector = transform @ values
        delta_cov = transform @ matrix @ transform.T
        eigenvalues, eigenvectors = np.linalg.eigh((delta_cov + delta_cov.T) / 2)
        rank_tolerance = max(numerical_tolerance(delta_cov), tolerance * float(np.linalg.norm(transform, 2) ** 2))
        positive = eigenvalues > rank_tolerance
        projections = eigenvectors.T @ delta_vector
        roundoff = 64 * np.finfo(float).eps * max(transform.shape) * float(np.linalg.norm(values))
        null_inconsistent = bool(np.linalg.norm(projections[~positive]) > roundoff)
        joint = {
            "contrast_point_ids": contrast_ids,
            "difference_ms": delta_vector.tolist(),
            "difference_covariance": delta_cov.tolist(),
            "rank": int(np.sum(positive)),
            "mahalanobis_squared": None
            if null_inconsistent
            else float(np.sum(projections[positive] ** 2 / eigenvalues[positive])),
            "nullspace_inconsistent": null_inconsistent,
            "rank_tolerance_ms2": rank_tolerance,
            "acceptance_status": "NOT_CALIBRATED_FOR_JOINT_DECISION",
        }
    return {
        "schema_version": "1.4-r1",
        "document_revision": "MASW-R1",
        "points": output,
        "source_curves": [c.model_dump(mode="json") for c in sources],
        "unique_observation_count": len(unique),
        "covariance": None if covariance is None else covariance.model_dump(mode="json"),
        "covariance_hash": None if covariance is None else canonical_hash(covariance),
        "overlap_statistic": joint,
        "interpolated_points": [],
        "eligible_for_acceptance": False,
        "comparison_sigma": compatibility_sigma,
        "limitations": [
            "Mode labels and support are declared comparison hypotheses; this union does not authenticate them",
            "Pointwise comparison is not a calibrated simultaneous test or evidence of site resolution",
            "Observations and covariance retained without averaging or adding independent samples",
        ],
    }
