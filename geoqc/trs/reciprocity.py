from __future__ import annotations

import math

from scipy.stats import norm

from geoqc.trs.contracts import ReciprocalObservation


def reciprocal_pair(
    ab: ReciprocalObservation,
    ba: ReciprocalObservation,
    *,
    covariance_s2: float = 0,
    tolerance_s: float,
    detectable_effect_s: float,
    minimum_power: float = 0.8,
    alpha: float = 0.05,
) -> dict[str, object]:
    if ab.source_id != ba.receiver_id or ab.receiver_id != ba.source_id or ab.source_id == ab.receiver_id:
        raise ValueError("Se requieren pares físicos A→B y B→A distintos")
    if not all(math.isfinite(v) for v in (covariance_s2, tolerance_s, detectable_effect_s, minimum_power, alpha)):
        raise ValueError("Parámetros de reciprocidad finitos requeridos")
    if tolerance_s < 0 or detectable_effect_s <= 0 or not 0 < minimum_power <= 1 or not 0 < alpha < 1:
        raise ValueError("Tolerancia/efecto/potencia/alpha fuera de dominio")
    if abs(covariance_s2) > ab.sigma_s * ba.sigma_s + 1e-24:
        raise ValueError("Covarianza no admisible para sigmas declaradas")
    delta = (ab.time_s - ab.source_delay_s - ab.clock_delay_s) - (ba.time_s - ba.source_delay_s - ba.clock_delay_s)
    variance = ab.sigma_s**2 + ba.sigma_s**2 - 2 * covariance_s2
    sigma = math.sqrt(max(variance, 0))
    critical = float(norm.ppf(1 - alpha / 2))
    if sigma == 0:
        z, discrepancy, power = None, delta != 0, 1.0
    else:
        z = delta / sigma
        discrepancy = abs(z) > critical
        standardized = detectable_effect_s / sigma
        power = float(norm.cdf(-critical - standardized) + norm.sf(critical - standardized))
    reliable = power >= minimum_power
    return {
        "pair": [ab.source_id, ab.receiver_id],
        "delta_orientation": "A_TO_B_MINUS_B_TO_A",
        "delta_s": delta,
        "sigma_delta_s": sigma,
        "covariance_s2": covariance_s2,
        "z": z,
        "operational_within_tolerance": abs(delta) <= tolerance_s,
        "statistical_discrepancy": discrepancy,
        "alpha": alpha,
        "detectable_effect_s": detectable_effect_s,
        "power": power,
        "evidence_status": "COMPLETE" if reliable else "INCOMPLETE",
        "cause_candidates": ["SOURCE_DELAY", "CLOCK", "GEOMETRY", "PICK_BIAS", "MODEL_MISMATCH"],
        "eligible_for_acceptance": False,
        "error_model_refs": [ab.error_model_ref, ba.error_model_ref],
    }
