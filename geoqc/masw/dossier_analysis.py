"""Pure dossier calculations; legacy array entry is exploratory, not validated ingestion."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import combinations
from typing import Any

import numpy as np
import numpy.typing as npt

from geoqc.masw.curves import ridge_path
from geoqc.masw.diagnostic_quality import UsabilityPolicy, assess_ridges
from geoqc.masw.transform import phase_shift

USABILITY_GRADES = ("UTILIZABLE", "REVISAR", "NO_UTILIZABLE", "NO_EVALUABLE")


def usability_bands(points: list[dict[str, Any]], df: float) -> list[dict[str, Any]]:
    """Sin interpolación ni unión de huecos; conservar todos los motivos por segmento."""
    proxy = [
        dict(
            frequency_hz=p["frequency_hz"],
            state=p["usability"]["grade"],
            reasons=p["usability"]["reasons"],
            support_ids=p["usability"]["active_channel_ids"],
        )
        for p in points
    ]
    return band_rows(proxy, df)


def classify_support(
    f: float, c: float, dx: float, *, edge: bool, observed: bool, uniform_complete: bool
) -> tuple[str, list[str]]:
    if not observed:
        return "NO_SUPPORT", ["NO_SUPPORT"]
    reasons = []
    if not uniform_complete:
        reasons.append("KERNEL_REVIEW")
    elif c <= 2 * dx * f:
        reasons.append("SPATIAL_NYQUIST")
    if edge:
        reasons.append("GRID_EDGE")
    return ("REVIEW" if reasons else "PENDING"), reasons + ["EVIDENCE_PENDING"]


def band_rows(points: list[dict[str, Any]], df: float) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for p in points:
        identity = (p["state"], p["reasons"], p["support_ids"])
        if (
            not groups
            or groups[-1]["identity"] != identity
            or p["frequency_hz"] - groups[-1]["f_bounds_hz"][1] > df * (1 + 1e-9)
        ):
            groups.append(
                {
                    "identity": identity,
                    "f_bounds_hz": [p["frequency_hz"], p["frequency_hz"]],
                    "state": p["state"],
                    "reasons": p["reasons"],
                    "support_ids": p["support_ids"],
                    "bins": 0,
                }
            )
        groups[-1]["f_bounds_hz"][1] = p["frequency_hz"]
        groups[-1]["bins"] += 1
    return [{k: v for k, v in g.items() if k != "identity"} for g in groups]


def analyze_spectra(
    spectrum: npt.NDArray[np.complex128],
    rectangular: npt.NDArray[np.complex128],
    f: npt.NDArray[np.float64],
    x: npt.NDArray[np.float64],
    c: npt.NDArray[np.float64],
    *,
    policy: UsabilityPolicy,
    slope_scale_ms_per_hz: float,
    penalty: float,
    excluded_channel_index: int,
    direction: int,
) -> dict[str, Any]:
    """Grid DP and fixed sensitivity variants, independent of paths and renderers.

    rectangular is the alternative-window spectrum (Hann when the base is
    rectangular). The excluded channel is an explicit sensitivity experiment,
    not an assertion that a receiver is the trigger.
    """
    if x.size < 3 or not 0 <= excluded_channel_index < x.size:
        raise ValueError("Sensibilidad requiere >=3 canales y una exclusión explícita válida")
    if rectangular.shape != spectrum.shape:
        raise ValueError("Variantes espectrales alineadas requeridas")
    result = phase_shift(spectrum, f, x, c, direction=direction)
    reverse = phase_shift(spectrum, f, x, c, direction=-direction)["coherence"]

    def path(score: npt.ArrayLike) -> npt.NDArray[np.int64]:
        return np.asarray(
            ridge_path(
                score, f, c, slope_scale_ms_per_hz=slope_scale_ms_per_hz, penalty=penalty
            ),
            dtype=int,
        )

    index = path(result["coherence"])
    ridge = c[index]
    keep = np.arange(x.size) != excluded_channel_index
    dropped = phase_shift(spectrum[:, keep], f, x[keep], c, direction=direction)["coherence"]
    rectangle_scores = phase_shift(rectangular, f, x, c, direction=direction)["coherence"]
    drop_ridge, rectangle_ridge = c[path(dropped)], c[path(rectangle_scores)]
    unpenalized_ridge = c[np.argmax(result["coherence"], axis=1)]
    variants = np.vstack((drop_ridge, rectangle_ridge, unpenalized_ridge))
    # Una variante sin soporte de amplitud no demuestra estabilidad por conservar
    # una velocidad elegida de un espectro normalizado casi cero.
    for k, variant_spectrum in enumerate((spectrum[:, keep], rectangular, spectrum)):
        magnitude = abs(variant_spectrum)
        support = (magnitude > magnitude.max(axis=0) * policy.amplitude_floor_rel) & (magnitude > 0)
        variants[k, support.sum(axis=1) < 2] = np.nan
    internal = assess_ridges(spectrum, f, direction * x, ridge, variants, policy)
    return dict(
        transformed=result, reverse_coherence=reverse, indices=index,
        ridge_ms=ridge, drop_ridge_ms=drop_ridge, alternative_ridge_ms=rectangle_ridge,
        unpenalized_ridge_ms=unpenalized_ridge, usability=internal, variant_velocities_ms=variants,
    )


def analyze_observed_record(
    data: npt.ArrayLike,
    dt: float,
    x: npt.ArrayLike,
    record_id: str,
    protocol: Mapping[str, Any],
    *,
    missing_evidence: Sequence[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    data, x = np.asarray(data, float), np.asarray(x, float)
    if (
        data.ndim != 2
        or data.shape[0] < 3
        or data.shape[1] < 32
        or x.shape != (data.shape[0],)
        or not np.isfinite(dt)
        or dt <= 0
        or not np.all(np.isfinite(data))
        or not np.all(np.isfinite(x))
        or np.any(np.diff(x) <= 0)
    ):
        raise ValueError("Registro finito canales×muestras, dt positivo y coordenadas crecientes requeridos")
    centered = data - data.mean(axis=1, keepdims=True)
    all_f = np.fft.rfftfreq(data.shape[1], dt)
    selection = (all_f >= protocol["frequency_min_hz"]) & (all_f <= protocol["frequency_max_hz"])
    f = all_f[selection]
    if f.size < 2:
        raise ValueError("Registro sin soporte de frecuencia para el protocolo")
    c = np.arange(
        protocol["velocity_min_ms"],
        protocol["velocity_max_ms"] + protocol["velocity_step_ms"] / 2,
        protocol["velocity_step_ms"],
    )
    spectrum = np.fft.rfft(centered * np.hanning(data.shape[1]), axis=1).T[selection]
    evaluated = analyze_spectra(
        spectrum, np.fft.rfft(centered, axis=1).T[selection], f, x, c,
        policy=UsabilityPolicy.model_validate(protocol["usability_policy"]),
        slope_scale_ms_per_hz=protocol["slope_scale_ms_per_hz"],
        penalty=protocol["penalty"], excluded_channel_index=0, direction=1,
    )
    result, reverse = evaluated["transformed"], evaluated["reverse_coherence"]
    index, ridge = evaluated["indices"], evaluated["ridge_ms"]
    drop_ridge, rectangle_ridge = evaluated["drop_ridge_ms"], evaluated["alternative_ridge_ms"]
    unpenalized_ridge, internal = evaluated["unpenalized_ridge_ms"], evaluated["usability"]
    policy = UsabilityPolicy.model_validate(protocol["usability_policy"])
    dx = float(x[1] - x[0])
    uniform = np.allclose(np.diff(x), dx, rtol=1e-12, atol=0)
    points = []
    for j, frequency in enumerate(f):
        observed = bool(result["n_active"][j] >= 2)
        complete = bool(uniform and result["active"][j].all())
        state, reasons = classify_support(
            frequency, ridge[j], dx, edge=index[j] in (0, c.size - 1), observed=observed, uniform_complete=complete
        )
        points.append(
            {
                "frequency_hz": float(frequency),
                "velocity_ms": float(ridge[j]) if observed else None,
                "coherence": float(result["coherence"][j, index[j]]) if observed else None,
                "state": state,
                "grade": "REGULAR" if state == "REVIEW" else "NO_EVALUABLE",
                "reasons": reasons,
                "support_ids": (np.flatnonzero(result["active"][j]) + 1).tolist(),
                "uniform_complete_support": complete,
                "mode_identity": "APPARENT" if observed else "UNKNOWN",
                "sigma_ms": None,
                "validated": False,
                "drop_channel_1_velocity_ms": float(drop_ridge[j])
                if np.count_nonzero(abs(spectrum[j, 1:])) >= 2
                else None,
                "rectangular_velocity_ms": float(rectangle_ridge[j]) if observed else None,
            }
        )
        usability = internal[j].model_dump(mode="json")
        if index[j] in (0, c.size - 1) and usability["grade"] == "UTILIZABLE":
            usability["grade"] = "REVISAR"
            usability["reasons"] = ["GRID_EDGE"]
        points[-1]["usability"] = usability
    traces = [
        {
            "channel_1based": i + 1,
            "rms_ac_native": float(np.sqrt(np.mean(row**2))),
            "constant": bool(np.ptp(data[i]) == 0),
            "zero": bool(np.all(data[i] == 0)),
            "grade": "MALA" if np.ptp(data[i]) == 0 else "NO_EVALUABLE",
            "reason": "Canal constante" if np.ptp(data[i]) == 0 else "Muestras finitas; SNR y clipping pendientes",
        }
        for i, row in enumerate(centered)
    ]
    candidate = np.array([p["state"] == "PENDING" for p in points])
    summary = {
        "id": record_id,
        "channels": data.shape[0],
        "samples": data.shape[1],
        "dt_s": dt,
        "duration_samples_s": data.shape[1] * dt,
        "last_sample_s": (data.shape[1] - 1) * dt,
        "aperture_m": float(np.ptp(x)),
        "dx_m": dx,
        "frequency_bin_hz": 1 / (data.shape[1] * dt),
        "traces": traces,
        "points": points,
        "bands": band_rows(points, float(f[1] - f[0])),
        "sample_integrity": "PASS",
        "amplitude_unit": "UNKNOWN",
        "mode_identity": "APPARENT",
        "acquisition_grade": "MALA" if any(t["constant"] for t in traces) else "NO_EVALUABLE",
        "overall_grade": "SIN_SOPORTE" if all(t["constant"] for t in traces) else "EVALUACION_PARCIAL",
        "objective_grade": "NO_EVALUABLE",
        "diagnostic_assessment": "EVALUACION_PARCIAL",
        "objective_status": "NOT_DEMONSTRATED",
        "usability_policy": policy.model_dump(mode="json"),
        "usability_bands": usability_bands(points, float(f[1] - f[0])),
        "usability_counts": {grade: sum(p["usability"]["grade"] == grade for p in points) for grade in USABILITY_GRADES},
        "evidence_status": "INCOMPLETE",
        "eligible_for_acceptance": False,
        "missing_evidence": list(missing_evidence),
        "validated_bands": [],
        "candidate_bins": int(candidate.sum()),
        "review_bins": sum(p["state"] == "REVIEW" for p in points),
        "no_support_bins": sum(p["state"] == "NO_SUPPORT" for p in points),
        "bin_counts_are_not_quality_percentages": True,
    }
    arrays = dict(
        data=data,
        x_m=x,
        frequencies_hz=f,
        velocities_ms=c,
        coherence=result["coherence"],
        reverse_coherence=reverse,
        ridge_ms=ridge,
        drop_ridge_ms=drop_ridge,
        rectangular_ridge_ms=rectangle_ridge,
        candidate_mask=candidate,
        fourier_magnitude=np.abs(spectrum),
        n_active=result["n_active"],
        unpenalized_ridge_ms=unpenalized_ridge,
        usable_mask=np.array([p["usability"]["grade"] == "UTILIZABLE" for p in points]),
    )
    return summary, arrays


def compare_records(
    records: Sequence[Mapping[str, Any]], arrays: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    comparisons = []
    for a, b in combinations(records, 2):
        aa, bb = arrays[a["id"]], arrays[b["id"]]
        f, ia, ib = np.intersect1d(aa["frequencies_hz"], bb["frequencies_hz"], return_indices=True)
        mask = aa["candidate_mask"][ia] & bb["candidate_mask"][ib]
        delta = aa["ridge_ms"][ia[mask]] - bb["ridge_ms"][ib[mask]]
        comparisons.append(
            {
                "a": a["id"],
                "b": b["id"],
                "common_bins": int(mask.sum()),
                "common_frequencies_hz": f[mask].tolist(),
                "median_abs_delta_ms": float(np.median(abs(delta))) if delta.size else None,
                "max_abs_delta_ms": float(np.max(abs(delta))) if delta.size else None,
                "uncertainty_status": "NOT_CALIBRATED",
                "consistency_grade": "NO_EVALUABLE",
                "scope": "Diferencias entre offsets en soporte candidato; no repetibilidad ni error contra verdad",
            }
        )
    return comparisons
