from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from geoqc.synth.dispersion import LayeredModel, phase_disba


def vs30(model: LayeredModel, *, finite_depth_m: float | None = None) -> float:
    if finite_depth_m is not None and finite_depth_m < 30:
        raise ValueError("Perfil observado no alcanza 30 m; no extrapolar semiespacio")
    remaining, integral = 30.0, 0.0
    for height, _, vs, _ in model.layers:
        used = remaining if height == 0 else min(remaining, height)
        integral += used / vs
        remaining -= used
        if remaining <= 0:
            return 30 / integral
    raise ValueError("Falta soporte vertical a 30 m")


def sensitivity(model: LayeredModel, frequencies_hz: npt.ArrayLike, *, relative_step: float = 0.005) -> Any:
    if not 0 < relative_step <= 0.05:
        raise ValueError("Paso de derivada debe ser (0,0.05]")
    columns = []
    for i, layer in enumerate(model.layers):
        curves = []
        for sign in (-1, 1):
            layers = list(model.layers)
            height, vp, vs, rho = layer
            layers[i] = (height, vp, vs * np.exp(sign * relative_step), rho)
            curves.append(phase_disba(LayeredModel(layers=tuple(layers)), frequencies_hz).velocities_ms)
        columns.append((np.log(curves[1]) - np.log(curves[0])) / (2 * relative_step))
    return np.column_stack(columns)


def parameter_resolution(jacobian: npt.ArrayLike, covariance: npt.ArrayLike, *, damping: float) -> dict[str, Any]:
    j, cov = np.asarray(jacobian, float), np.asarray(covariance, float)
    if (
        j.ndim != 2
        or cov.shape != (j.shape[0], j.shape[0])
        or damping < 0
        or not np.isfinite(damping)
        or not all(np.all(np.isfinite(a)) for a in (j, cov))
        or not np.allclose(cov, cov.T)
    ):
        raise ValueError("Jacobiano, covarianza simétrica y damping válidos requeridos")
    chol = np.linalg.cholesky(cov)
    a = np.linalg.solve(chol, j)
    inverse = np.linalg.pinv(a.T @ a + damping**2 * np.eye(j.shape[1])) @ a.T
    return {
        "resolution": (inverse @ a).tolist(),
        "covariance": (inverse @ inverse.T).tolist(),
        "rank": int(np.linalg.matrix_rank(a)),
        "scope": "LOCAL_DECLARED_PARAMETRIZATION_AND_PRIOR",
    }


def ensemble_reference(
    observed_ms: npt.ArrayLike, sigma_ms: npt.ArrayLike, model_curves_ms: npt.ArrayLike, model_vs30_ms: npt.ArrayLike
) -> dict[str, Any]:
    y, sigma = np.asarray(observed_ms, float), np.asarray(sigma_ms, float)
    curves, values = np.asarray(model_curves_ms, float), np.asarray(model_vs30_ms, float)
    if (
        y.ndim != 1
        or sigma.shape != y.shape
        or curves.shape != (values.size, y.size)
        or values.size < 2
        or np.any(sigma <= 0)
        or np.any(values <= 0)
        or not all(np.all(np.isfinite(v)) for v in (y, sigma, curves, values))
    ):
        raise ValueError("Ensamble requiere modelos/curvas y ruido explícito alineados")
    chi = np.sum(((curves - y) / sigma) ** 2, axis=1)
    weights = np.exp(-0.5 * (chi - np.min(chi)))
    weights /= weights.sum()
    order = np.argsort(values)
    cumulative = np.cumsum(weights[order])
    lo, hi = np.interp([0.025, 0.975], cumulative, values[order])
    return {
        "mean_vs30_ms": float(weights @ values),
        "interval95_ms": [float(lo), float(hi)],
        "weights": weights.tolist(),
        "minimum_chi2": float(chi.min()),
        "scope": "DISCRETE_SYNTHETIC_ENSEMBLE_WITH_DECLARED_PRIOR",
        "eligible_for_acceptance": False,
    }
