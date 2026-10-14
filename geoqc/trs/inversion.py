from __future__ import annotations

import math

import numpy as np
from scipy.optimize import least_squares

from geoqc.core.models import FloatArray
from geoqc.trs.branches import layered_first_times


def normalized_misfit(observed_s: FloatArray, predicted_s: FloatArray, covariance_s2: FloatArray) -> dict[str, object]:
    d, f, c = np.asarray(observed_s), np.asarray(predicted_s), np.asarray(covariance_s2)
    if d.ndim != 1 or d.size == 0 or d.shape != f.shape or c.shape != (d.size, d.size):
        raise ValueError("Dimensiones d/f/C_d incompatibles")
    if not all(np.all(np.isfinite(a)) for a in (d, f, c)) or not np.allclose(c, c.T, atol=0, rtol=1e-12):
        raise ValueError("Datos finitos y covarianza simétrica")
    try:
        lower = np.linalg.cholesky(c)
    except np.linalg.LinAlgError as exc:
        raise ValueError("C_d debe ser definida positiva; no se oculta singularidad") from exc
    residual = d - f
    whitened = np.linalg.solve(lower, residual)
    return {
        "Q": float(np.mean(whitened**2)),
        "rms_s": float(np.sqrt(np.mean(residual**2))),
        "bias_s": float(np.mean(residual)),
        "residuals_s": residual.tolist(),
        "reason": "Misfit normalizado por n, no chi² reducido con DOF garantizados",
    }


def invert_two_layer(
    offsets_m: FloatArray,
    times_s: FloatArray,
    *,
    sigma_s: FloatArray,
    initial_v1_v2_h: tuple[float, float, float],
    max_evaluations: int = 5,
    horizontal_model_verified: bool,
    roi_ref: str,
) -> dict[str, object]:
    if not horizontal_model_verified:
        return {
            "state": "MODEL_INAPPLICABLE",
            "reason": "Modelo horizontal de dos capas no verificado",
            "eligible_for_acceptance": False,
        }
    x, y, s = np.asarray(offsets_m, dtype=float), np.asarray(times_s, dtype=float), np.asarray(sigma_s, dtype=float)
    if x.ndim != 1 or x.shape != y.shape or x.shape != s.shape or x.size < 12 or not roi_ref:
        raise ValueError("Inversión requiere observaciones suficientes, sigmas y ROI")
    if not all(np.all(np.isfinite(a)) for a in (x, y, s)) or np.any(x < 0) or np.any(s <= 0):
        raise ValueError("Offsets>=0 y sigmas>0 finitos")
    v1, v2, h = initial_v1_v2_h
    if not all(math.isfinite(v) for v in (v1, v2, h)) or not 0 < v1 < v2 or h <= 0 or max_evaluations < 1:
        raise ValueError("Modelo inicial 0<V1<V2,h>0 y presupuesto positivo")

    def decode(parameters: FloatArray) -> tuple[float, float, float]:
        first, contrast, thickness = np.exp(parameters)
        return float(first), float(first + contrast), float(thickness)

    def residual(parameters: FloatArray) -> FloatArray:
        first, second, thickness = decode(parameters)
        return np.asarray((layered_first_times(x, (first, second), (thickness,)) - y) / s, dtype=float)

    result = least_squares(
        residual,
        np.log([v1, v2 - v1, h]),
        max_nfev=max_evaluations,
        bounds=(np.log([1, 1, 0.001]), np.log([10000, 20000, 1000])),
        ftol=1e-10,
        xtol=1e-10,
        gtol=1e-10,
    )
    first, second, thickness = decode(result.x)
    crossover = 2 * thickness * math.sqrt((second + first) / (second - first))
    branch_counts = [int(np.count_nonzero(x < crossover)), int(np.count_nonzero(x >= crossover))]
    singular_values = np.linalg.svd(result.jac, compute_uv=False)
    identifiable = min(branch_counts) >= 5 and singular_values[-1] > singular_values[0] * 1e-6
    converged = bool(result.success)
    state = "VALID" if identifiable and converged else "NOT_CONVERGED" if identifiable else "MODEL_INAPPLICABLE"
    predicted = layered_first_times(x, (first, second), (thickness,))
    misfit = normalized_misfit(y, predicted, np.diag(s**2))
    covariance = np.linalg.pinv(result.jac.T @ result.jac) if identifiable else None
    return {
        "state": state,
        "converged": converged,
        "evaluations": int(result.nfev),
        "budget": max_evaluations,
        "velocities_ms": [first, second] if identifiable else None,
        "thickness_m": thickness if identifiable else None,
        "misfit": misfit,
        "branch_observations": branch_counts,
        "jacobian_singular_values": singular_values.tolist(),
        "log_parameter_covariance": None if covariance is None else covariance.tolist(),
        "roi_ref": roi_ref,
        "resolution_state": "LOCAL_PARAMETRIC_ONLY" if identifiable else "UNIDENTIFIABLE",
        "eligible_for_acceptance": False,
        "reason": "Convergencia no acredita unicidad; presupuesto agotado no implica adquisición mala",
    }


def linear_resolution(length_matrix_m: FloatArray, *, sigma_s: FloatArray, damping: float) -> dict[str, object]:
    a, s = np.asarray(length_matrix_m), np.asarray(sigma_s)
    if a.ndim != 2 or s.shape != (a.shape[0],) or min(a.shape) < 1 or np.any(s <= 0) or damping < 0:
        raise ValueError("Matriz de longitudes/sigmas/regularización inválidas")
    if not np.all(np.isfinite(a)) or not np.all(np.isfinite(s)) or not math.isfinite(damping):
        raise ValueError("Sistema finito requerido")
    weighted = a / s[:, None]
    normal = weighted.T @ weighted
    inverse = np.linalg.pinv(normal + damping * np.eye(a.shape[1]))
    operator = inverse @ weighted.T
    resolution = operator @ weighted
    covariance = operator @ operator.T
    return {
        "operator": operator.tolist(),
        "resolution_matrix": resolution.tolist(),
        "noise_covariance": covariance.tolist(),
        "rank": int(np.linalg.matrix_rank(weighted)),
        "reason": "Resolución lineal condicionada a rayos fijos y damping; no unicidad no lineal",
    }
