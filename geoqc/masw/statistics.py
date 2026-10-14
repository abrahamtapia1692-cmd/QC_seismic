from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy.optimize import brentq
from scipy.special import j0, j1, roots_legendre


@lru_cache(maxsize=1)
def estimator_hash() -> str:
    from importlib.metadata import version

    source = b"".join(path.read_bytes() for path in sorted(Path(__file__).parent.glob("*.py")))
    source += str([(name, version(name)) for name in ("numpy", "scipy", "pydantic")]).encode()
    return hashlib.sha256(source).hexdigest()


def kluyver_cdf(a: float, n: int, *, cutoff: float = 100, order: int = 32) -> float:
    if (
        type(n) is not int
        or n not in (12, 24, 48)
        or not np.isfinite(a)
        or not 0 <= a <= 1
        or cutoff < 50
        or order < 16
    ):
        raise ValueError("Cuadratura validada solo N12/24/48, a en [0,1], corte>=50, orden>=16")
    if a == 0 or a == 1:
        return a
    nodes, weights = roots_legendre(order)
    count = int(np.ceil(cutoff))
    starts = np.arange(count) * cutoff / count
    t = starts[:, None] + (nodes[None, :] + 1) * cutoff / (2 * count)
    radius = a * n
    integral = np.sum(j1(radius * t) * j0(t) ** n * weights[None, :]) * cutoff / (2 * count)
    return float(np.clip(radius * integral, 0, 1))


def iid_threshold(n: int, alpha: float, *, hypotheses: int = 1) -> dict[str, Any]:
    if not 0 < alpha < 1 or type(hypotheses) is not int or hypotheses < 1:
        raise ValueError("alpha en (0,1) y número real de hipótesis >=1")
    threshold = float(brentq(lambda a: kluyver_cdf(a, n) - (1 - alpha / hypotheses), 0, 1, xtol=1e-9))
    return {
        "threshold": threshold,
        "n_active": n,
        "hypotheses": hypotheses,
        "null": "IID_UNIFORM_PHASES_EQUAL_WEIGHTS_ONLY",
        "scope": "BONFERRONI_GRID_TESTS_ONLY",
    }


def empirical_max_threshold(maxima: npt.ArrayLike, alpha: float) -> float:
    a = np.asarray(maxima, float)
    if a.ndim != 1 or a.size < 1000 or not np.all(np.isfinite(a)) or np.any((a < 0) | (a > 1)) or not 0 < alpha < 1:
        raise ValueError("Máximos de nula [0,1], >=1000, alpha en (0,1)")
    # Cuantil con corrección de rango finito; exchangeability es supuesto explícito.
    index = min(a.size - 1, int(np.ceil((a.size + 1) * (1 - alpha))) - 1)
    return float(np.sort(a)[index])


def uncertainty_from_errors(estimate_ms: npt.ArrayLike, errors_ms: npt.ArrayLike) -> dict[str, Any]:
    estimate, errors = np.asarray(estimate_ms, float), np.asarray(errors_ms, float)
    if (
        estimate.ndim != 1
        or np.any(estimate <= 0)
        or errors.ndim != 2
        or errors.shape[1] != estimate.size
        or errors.shape[0] < 500
        or not all(np.all(np.isfinite(a)) for a in (estimate, errors))
    ):
        raise ValueError("Errores train multivariados finitos >=500 por frecuencia")
    bias = errors.mean(axis=0)
    corrected = estimate - bias
    quantiles = np.quantile(errors, [0.025, 0.975], axis=0)
    if np.any(corrected <= 0) or np.any(estimate - quantiles[1] <= 0):
        raise ValueError("Calibración incompatible: corrección o intervalo de velocidad no físico")
    covariance = np.atleast_2d(np.cov(errors, rowvar=False, ddof=1))
    sigma = np.sqrt(np.diag(covariance))
    return {
        "velocities_ms": corrected.tolist(),
        "bias_ms": bias.tolist(),
        "sigma_ms": sigma.tolist(),
        "interval95_ms": np.column_stack((estimate - quantiles[1], estimate - quantiles[0])).tolist(),
        "covariance_ms2": covariance.tolist(),
        "precision_cov": (sigma / corrected).tolist(),
        "repeatability_cov": None,
        "scope": "DECLARED_SIGNAL_DOMAIN_ONLY",
    }
