"""Clasificación diagnóstica por traza y agregación por proporción de trazas buenas."""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from geoqc.core.models import FrozenModel

Grade = Literal["BUENA", "REGULAR", "MALA"]
COLORS: dict[Grade, str] = {"BUENA": "#16803c", "REGULAR": "#b77900", "MALA": "#dc2626"}
DISPLAY_COLORS: dict[str, str] = {key: value for key, value in COLORS.items()}
DISPLAY_COLORS["NO_EVALUABLE"] = "#64748b"


class TraceQualityPolicy(FrozenModel):
    """Umbrales locales iniciales, explícitos y sin calibración de campo."""

    id: str = "TRACE_QUALITY_V1_DRAFT"
    snr_good_min_db: float = 12.0
    snr_bad_below_db: float = 6.0
    clip_good_max_fraction: float = Field(default=0.001, ge=0, le=1)
    clip_bad_min_fraction: float = Field(default=0.01, ge=0, le=1)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.snr_bad_below_db >= self.snr_good_min_db:
            raise ValueError("SNR: el límite malo debe ser menor al bueno")
        if self.clip_good_max_fraction >= self.clip_bad_min_fraction:
            raise ValueError("Clipping: el límite bueno debe ser menor al malo")
        return self


def trace_quality(trace: Mapping[str, Any], policy: TraceQualityPolicy) -> dict[str, Any]:
    """Peor hallazgo por canal; evidencia faltante produce REGULAR, nunca BUENA.

    Una ausencia de onset no se usa como prueba de mala adquisición.
    Las métricas físicas son las calculadas por QC común, sin inferir ventanas.
    """
    failures: list[str] = []
    warnings: list[str] = []
    missing: list[str] = []
    stats = trace.get("statistics", {})
    if stats.get("state") != "VALID":
        failures.append("Sin soporte suficiente de muestras válidas en la ventana de análisis")
    elif stats.get("dead") or stats.get("constant"):
        failures.append("Canal muerto (ceros)" if stats.get("dead") else "Canal constante, sin señal AC")
    if stats.get("amplitude_anomaly"):
        warnings.append("Amplitud anómala respecto al modelo declarado")
    valid_fraction = trace.get("valid_fraction")
    if valid_fraction is None or not math.isfinite(valid_fraction):
        missing.append("Integridad de muestras no evaluada")
    elif valid_fraction < 1:
        warnings.append("Registro con muestras no válidas; se conserva en el denominador")

    for key in ("snr", "clip"):
        item = trace.get(key, {})
        value = item.get("value")
        if key == "snr" and item.get("state") == "CENSORED":
            details = json.loads(item.get("details_json", "{}"))
            if details.get("snr_net_ratio") == 0 and details.get("noise_power", 0) > 0:
                failures.append("Potencia de señal neta no resuelta sobre el ruido verificado")
                continue
        if item.get("state") != "VALID" or value is None or not math.isfinite(value):
            missing.append(f"{key}: {item.get('reason', 'Diagnóstico ausente')}")
            continue
        if key == "snr":
            if value < policy.snr_bad_below_db:
                failures.append(f"SNR {value:.2f} dB < {policy.snr_bad_below_db:g} dB")
            elif value < policy.snr_good_min_db:
                warnings.append(f"SNR {value:.2f} dB < {policy.snr_good_min_db:g} dB")
        elif value >= policy.clip_bad_min_fraction:
            failures.append(f"Clipping {100 * value:.3f} % ≥ {100 * policy.clip_bad_min_fraction:g} %")
        elif value > policy.clip_good_max_fraction:
            warnings.append(f"Clipping {100 * value:.3f} % > {100 * policy.clip_good_max_fraction:g} %")

    if trace.get("mains", {}).get("flagged"):
        warnings.append("Línea espectral de red detectada")
    warnings.extend(trace.get("noise_diagnostics", {}).get("alerts", []))
    warnings.extend(trace.get("integrity", {}).get("alerts", []))
    similarity = trace.get("similarity")
    if similarity is not None:
        if similarity.get("grade") == "MALA" and similarity.get("state") == "VALID":
            failures.extend(similarity["reasons"])
        elif similarity.get("state") != "VALID":
            missing.extend(similarity["reasons"])
        elif similarity.get("grade") == "REGULAR":
            warnings.extend(similarity["reasons"])
    budget = trace.get("time_budget", {})
    if budget.get("band_policy_satisfied") is False:
        warnings.append("Banda solicitada fuera del margen de Nyquist")
    if budget.get("post_sufficient") is False:
        warnings.append("Duración insuficiente para el escenario de propagación declarado")
    grade: Grade = "MALA" if failures else "REGULAR" if warnings or missing else "BUENA"
    assessment_grade = "MALA" if failures else "REGULAR" if warnings else "NO_EVALUABLE" if missing else "BUENA"
    return {
        "grade": grade,
        "color": COLORS[grade],
        "reasons": failures + warnings + missing or ["Integridad, SNR y clipping dentro de los límites declarados"],
        "missing_evidence": missing,
        "evidence_complete": not missing,
        "policy_id": policy.id,
        "assessment_grade": assessment_grade,
        "assessment_color": DISPLAY_COLORS[assessment_grade],
        "demonstrated_failures": failures,
        "review_reasons": warnings,
    }


def assess_quality(qualities: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Intervalo por evidencia faltante, conservando todas las trazas y los cortes 90/75.

    No se inventan buenas ni se excluyen los faltantes del denominador. Una falla
    observada sigue siendo mala aunque falten otras métricas del mismo canal.
    """
    rows = list(qualities)
    lower = aggregate_quality(row["grade"] for row in rows)
    pending = sum(not row["evidence_complete"] and row["grade"] != "MALA" for row in rows)
    good = lower["counts"]["BUENA"]
    possible_grades: list[Grade] = ["BUENA"] * (good + pending)
    possible_grades.extend(["REGULAR"] * (len(rows) - good - pending))
    upper = aggregate_quality(possible_grades)
    decision = lower["grade"] if rows and lower["grade"] == upper["grade"] else "NO_EVALUABLE"
    return {
        "grade": decision,
        "color": DISPLAY_COLORS[decision],
        "total_traces": len(rows),
        "demonstrated_bad_traces": lower["counts"]["MALA"],
        "pending_traces": pending,
        "complete_traces": sum(row["evidence_complete"] for row in rows),
        "good_percent_bounds": [lower["good_percent"], upper["good_percent"]],
        "reason": "Los extremos posibles con la evidencia faltante caen en categorías distintas"
        if decision == "NO_EVALUABLE"
        else "La categoría no cambia dentro del intervalo de evidencia pendiente",
        "acceptance_status": "NOT_CERTIFIED",
    }


def aggregate_quality(grades: Iterable[Grade]) -> dict[str, Any]:
    """Sin redondear antes de decidir; REGULAR es [75,90), incluidos decimales."""
    counts = Counter(grades)
    if set(counts) - set(COLORS):
        raise ValueError("Categoría de traza desconocida")
    total = sum(counts.values())
    good = counts["BUENA"]
    grade: Grade | None = (
        None
        if not total
        else "BUENA"
        if 100 * good >= 90 * total
        else ("REGULAR" if 100 * good >= 75 * total else "MALA")
    )
    return {
        "grade": grade,
        "color": COLORS[grade] if grade else "#64748b",
        "total_traces": total,
        "counts": {key: counts[key] for key in COLORS},
        "good_percent": 100 * good / total if total else None,
        "rule": "BUENA: ≥90 %; REGULAR: ≥75 % y <90 %; MALA: <75 % de trazas BUENAS",
        "denominator": "Todas las trazas, incluidas las de evidencia incompleta; sin ponderación por muestras",
    }
