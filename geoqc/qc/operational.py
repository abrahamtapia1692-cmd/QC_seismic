"""Opt-in sample-based TRS screening, independent of instrument certification.

Thresholds are declared local scenarios, not instrument specifications or calibrated
error probabilities. Neither metadata nor the strict QC outcome is overwritten.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Self

import numpy as np
from pydantic import Field, model_validator
from scipy.signal import periodogram

from geoqc.core.models import FloatArray, FrozenModel, Shot
from geoqc.qc.contracts import QCProtocol, SimilarityProtocol
from geoqc.qc.noise import samples_in_window
from geoqc.qc.quality import DISPLAY_COLORS, aggregate_quality
from geoqc.qc.similarity import local_similarity


class OperationalPolicy(FrozenModel):
    id: str = "TRS_SAMPLE_SCREENING_V1_DRAFT"
    minimum_coverage: float = Field(default=0.75, ge=0.75, le=1)
    contrast_good_db: float = 12.0
    contrast_review_db: float = 6.0
    max_reference_power_ratio: float = Field(default=4.0, gt=1)
    reference_blocks: int = Field(default=4, ge=3, le=16, strict=True)
    plateau_min_run: int = Field(default=3, ge=3, strict=True)
    line_persistence_min_fraction: float = Field(default=0.75, gt=0.5, le=1)
    line_prominence_db: float = Field(default=10, gt=0)
    reference: str = Field(min_length=1)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.contrast_review_db >= self.contrast_good_db:
            raise ValueError("Los umbrales de contraste deben ser crecientes")
        return self


def morphology(values: FloatArray, minimum_run: int) -> dict[str, Any]:
    """Repeated *exact* observed extrema: candidate plateau, never inferred ADC rails."""
    if values.size < 16 or not np.all(np.isfinite(values)):
        return {"state": "MISSING", "reason": "Ventana sin soporte finito suficiente"}
    if np.ptp(values) == 0:
        return {"state": "MEASURED", "candidate": False, "longest_run": int(values.size),
                "plateau_fraction": 0.0, "reason": "Traza constante; falla evaluada por integridad"}
    longest, count = 0, 0
    for extreme in (float(values.min()), float(values.max())):
        flagged = values == extreme
        boundaries = np.flatnonzero(np.diff(np.r_[False, flagged, False].astype(int)))
        lengths = boundaries[1::2] - boundaries[::2]
        longest = max(longest, int(lengths.max(initial=0)))
        count += int(lengths[lengths >= minimum_run].sum())
    return {"state": "MEASURED", "candidate": bool(count), "longest_run": longest,
            "plateau_fraction": count / int(values.size), "adc_rails_estimated": False,
            "reason": "Mesetas en extremos observados; revisar saturación, cuantización o procesamiento"
            if count else "Sin mesetas extremas detectadas; esto no demuestra ausencia de clipping físico"}


def contrast(shot: Shot, channel: int, protocol: QCProtocol, policy: OperationalPolicy) -> dict[str, Any]:
    """Contrast envelope over *all* fixed reference blocks; not a confidence interval."""
    if protocol.noise is None or protocol.signal is None:
        return {"state": "MISSING", "reason": "Se requieren ventanas de referencia y señal explícitas"}
    noise = samples_in_window(shot.data[channel], shot.valid_mask[channel], shot.dt_s[channel],
                              shot.t0_s[channel], protocol.noise)
    signal = samples_in_window(shot.data[channel], shot.valid_mask[channel], shot.dt_s[channel],
                               shot.t0_s[channel], protocol.signal)
    if noise is None or signal is None or len(noise) < policy.reference_blocks * 16:
        return {"state": "MISSING", "reason": "Ventanas incompletas o bloques de referencia demasiado cortos"}
    # Normalize both windows by a common finite amplitude to avoid overflow and
    # retain invariance to a common fixed gain. No quiet-block selection.
    amplitude = max(float(np.max(np.abs(noise))), float(np.max(np.abs(signal))))
    if amplitude == 0:
        return {"state": "CENSORED", "reason": "Referencia sin potencia AC resoluble"}
    n, s = noise / amplitude, signal / amplitude
    powers = [float(np.var(block)) for block in np.array_split(n, policy.reference_blocks)]
    signal_power = float(np.var(s))
    if min(powers) <= 0:
        return {"state": "CENSORED", "reason": "Al menos un bloque tiene potencia AC cero; no se genera contraste infinito"}
    low_net, high_net = signal_power / max(powers) - 1, signal_power / min(powers) - 1
    bounds = [float(10 * np.log10(x)) if x > 0 else None for x in (low_net, high_net)]
    ratio = max(powers) / min(powers)
    return {"state": "ESTIMATED", "db_bounds": bounds, "net_power_resolved": [low_net > 0, high_net > 0],
            "reference_power_ratio": ratio, "reference_stable": ratio <= policy.max_reference_power_ratio,
            "normalized_block_powers": powers, "normalization_amplitude": amplitude,
            "reference_kind": "PRE_SIGNAL" if protocol.noise.end_s <= protocol.signal.start_s else "POST_SIGNAL",
            "noise_independence_verified": False, "interval_kind": "REFERENCE_BLOCK_SENSITIVITY_NOT_CI",
            "reason": "Contraste condicional usando todos los bloques; no valida transferencia del ruido ni SNR del arribo"}


def estimated_similarity(shot: Shot, protocol: SimilarityProtocol | None) -> tuple[dict[str, Any], ...]:
    if protocol is None:
        return tuple({"state": "MISSING", "reason": "Escenario de vecindario no declarado"} for _ in shot.data)
    if shot.acquisition.technique != "TRS":
        return tuple({"state": "MISSING", "reason": "Se requiere TRS y componente declarada"} for _ in shot.data)
    # This private scenario enables computation only; it does not assert physical
    # comparability in the source protocol, strict output, or evidence metadata.
    scenario = protocol.model_copy(update={"comparable_channels": True})
    coordinates = np.column_stack((shot.geometry.xr, shot.geometry.yr, shot.geometry.zr))
    try:
        rows = local_similarity(shot.data, shot.valid_mask, shot.dt_s, shot.t0_s, coordinates, scenario)
    except ValueError:
        return tuple({"state": "MISSING", "reason": "Sin soporte común de reloj, ventanas o geometría"} for _ in shot.data)
    return tuple(row | {"state": "ESTIMATED" if row["state"] == "VALID" else row["state"],
                        "quality_applicable": bool(row.get("consensus_channels_1based")),
                        "instrumental_comparability_verified": protocol.comparable_channels,
                        "scope": "LOCAL_SHAPE_SCENARIO_NOT_INSTRUMENT_DIAGNOSIS"} for row in rows)


def line_persistence(shot: Shot, j: int, protocol: QCProtocol, trace: dict[str, Any],
                     policy: OperationalPolicy) -> list[dict[str, Any]]:
    """Test reported candidates on every fixed reference block, without filtering."""
    if protocol.noise is None:
        return []
    values = samples_in_window(shot.data[j], shot.valid_mask[j], shot.dt_s[j], shot.t0_s[j], protocol.noise)
    if values is None or len(values) < policy.reference_blocks * 16:
        return []
    output = []
    for line in trace.get("noise_diagnostics", {}).get("lines", []):
        prominences: list[float | None] = []
        nominal = line["nominal_hz"]
        for block in np.array_split(values, policy.reference_blocks):
            amplitude = float(np.max(np.abs(block)))
            if amplitude == 0 or len(block) * shot.dt_s[j] * nominal < 3:
                prominences.append(None)
                continue
            f, power = periodogram(block / amplitude, fs=1 / shot.dt_s[j], window="hann", scaling="density")
            df = f[1] - f[0]
            peak = power[abs(f - nominal) <= df]
            background = power[(abs(f - nominal) >= 3 * df) & (abs(f - nominal) <= 6 * df)]
            if not peak.size or background.size < 3 or np.median(background) <= 0 or peak.max() <= 0:
                prominences.append(None)
            else:
                prominences.append(float(10 * np.log10(peak.max() / np.median(background))))
        supported = all(v is not None for v in prominences)
        fraction = sum(v is not None and v >= policy.line_prominence_db for v in prominences) / policy.reference_blocks
        output.append({"nominal_hz": nominal, "block_prominence_db": prominences,
                       "fraction": fraction, "state": "ESTIMATED" if supported else "INSUFFICIENT_SUPPORT",
                       "persistent_candidate": supported and fraction >= policy.line_persistence_min_fraction,
                       "cause": "UNIDENTIFIED"})
    return output


def screen_traces(shot: Shot, protocol: QCProtocol, traces: list[dict[str, Any]],
                  policy: OperationalPolicy) -> None:
    similarities = estimated_similarity(shot, protocol.similarity)
    for j, trace in enumerate(traces):
        signal_contrast = contrast(shot, j, protocol, policy)
        analysis = samples_in_window(shot.data[j], shot.valid_mask[j], shot.dt_s[j], shot.t0_s[j], protocol.analysis)
        shape = morphology(analysis, policy.plateau_min_run) if analysis is not None else {
            "state": "MISSING", "reason": "Ventana de análisis incompleta"}
        similarity = similarities[j]
        persistence = line_persistence(shot, j, protocol, trace, policy)
        domains: dict[str, str] = {"integrity": "MISSING", "morphology": "MISSING",
                                   "contrast": "MISSING", "similarity": "MISSING"}
        failures = list(trace["quality"]["demonstrated_failures"])
        warnings: list[str] = []
        stats = trace["statistics"]
        if stats["state"] == "VALID":
            domains["integrity"] = "SUPPORTED"
        if trace["valid_fraction"] < 1:
            warnings.append("Muestras inválidas: revisar integridad y ventanas")
        if shape["state"] == "MEASURED":
            domains["morphology"] = "SUPPORTED"
            if shape["candidate"]:
                warnings.append(shape["reason"])
        if signal_contrast["state"] == "ESTIMATED":
            domains["contrast"] = "ESTIMATED"
            low, high = signal_contrast["db_bounds"]
            if not signal_contrast["reference_stable"]:
                warnings.append("Referencia variable entre bloques; contraste sensible al ruido")
            if low is None or low < policy.contrast_good_db:
                warnings.append("Contraste condicional bajo" if high is None or high < policy.contrast_review_db
                                else "Contraste intermedio o sensible a los bloques de referencia")
        if similarity["state"] == "ESTIMATED" and similarity["quality_applicable"]:
            domains["similarity"] = "ESTIMATED"
            if similarity["grade"] != "BUENA":
                warnings.extend(similarity["reasons"])
            if any(pair["at_search_boundary"] for pair in similarity.get("pairs", [])):
                warnings.append("Máximo de correlación en límite de desfase; revisar escenario")
        # Retain observed alerts, but an isolated narrow spectral candidate is
        # diagnostic evidence, not an automatic proof of unusable acquisition.
        warnings.extend(trace.get("integrity", {}).get("alerts", []))
        warnings.extend(r for r in trace["quality"]["review_reasons"]
                        if not r.startswith("Líneas espectrales candidatas próximas a red/armónicos"))
        if any(p["persistent_candidate"] for p in persistence):
            warnings.append("Línea candidata persistente entre bloques; revisar su efecto, sin atribuir causa eléctrica")
        supported = sum(v != "MISSING" for v in domains.values())
        coverage = supported / len(domains)
        eligible = coverage >= policy.minimum_coverage and all(
            domains[k] != "MISSING" for k in ("integrity", "morphology", "contrast"))
        grade = "MALA" if failures else "REGULAR" if warnings else "BUENA" if eligible else "NO_EVALUABLE"
        reasons = failures + list(dict.fromkeys(warnings))
        if not eligible:
            reasons.append("Cobertura insuficiente para declarar buena bajo esta política diagnóstica")
        trace["operational_quality"] = {
            "grade": grade, "color": DISPLAY_COLORS[grade], "policy_id": policy.id,
            "scope": "CONDITIONAL_SAMPLE_SCREENING_NOT_FIELD_ACCEPTANCE", "coverage_fraction": coverage,
            "domains": domains, "minimum_coverage": policy.minimum_coverage,
            "reasons": reasons or ["Comprobaciones disponibles dentro del escenario diagnóstico declarado"],
            "strict_grade": trace["quality"]["assessment_grade"],
            "missing_metadata": list(trace["quality"]["missing_evidence"]),
            "estimated_contrast": signal_contrast, "morphology": shape,
            "line_persistence": persistence,
            "estimated_similarity": similarity, "eligible_for_acceptance": False,
        }


def aggregate_screening(traces: list[dict[str, Any]], policy_id: str) -> dict[str, Any]:
    rows = [t["operational_quality"] for t in traces]
    grades = [r["grade"] for r in rows]
    counts = {k: grades.count(k) for k in DISPLAY_COLORS}
    lower = aggregate_quality(g if g != "NO_EVALUABLE" else "REGULAR" for g in grades)
    upper = aggregate_quality(g if g != "NO_EVALUABLE" else "BUENA" for g in grades)
    grade = lower["grade"] if rows and lower["grade"] == upper["grade"] else "NO_EVALUABLE"
    return {"grade": grade, "color": DISPLAY_COLORS[grade], "policy_id": policy_id,
            "scope": "CONDITIONAL_SAMPLE_SCREENING_NOT_FIELD_ACCEPTANCE", "total_traces": len(rows),
            "counts": counts, "good_percent_bounds": [lower["good_percent"], upper["good_percent"]],
            "mean_coverage_fraction": sum(r["coverage_fraction"] for r in rows) / len(rows) if rows else None,
            "domain_support_counts": dict(Counter(k for r in rows for k, v in r["domains"].items() if v != "MISSING")),
            "pending_traces": counts["NO_EVALUABLE"], "reason": "Calificación por proporción de buenas diagnósticas; no identifica averías ni certifica aceptación",
            "acceptance_status": "NOT_CERTIFIED", "eligible_for_acceptance": False}
