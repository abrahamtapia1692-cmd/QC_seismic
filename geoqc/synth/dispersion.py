"""Dos forwards Rayleigh: Dunkin (disba/CPS) y FEM vertical propio, sin compartir secular."""

from __future__ import annotations

from typing import Self

import numpy as np
import numpy.typing as npt
from pydantic import model_validator
from scipy.optimize import brentq
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import eigsh

from geoqc.core.models import Array, FrozenModel, Nonnegative, Positive


class LayeredModel(FrozenModel):
    # h[m], Vp[m/s], Vs[m/s], rho[kg/m3]; última h=0 representa semiespacio.
    layers: tuple[tuple[Nonnegative, Positive, Positive, Positive], ...]

    @model_validator(mode="after")
    def elastic_domain(self) -> Self:
        if not self.layers or self.layers[-1][0] != 0 or any(layer[0] <= 0 for layer in self.layers[:-1]):
            raise ValueError("Espesores positivos y última capa h=0 requerida")
        if any(vp * vp <= 4 * vs * vs / 3 for _, vp, vs, _ in self.layers):
            raise ValueError("Estabilidad isótropa requiere mu>0 y K>0")
        return self


class PhaseCurve(FrozenModel):
    frequencies_hz: Array
    velocities_ms: Array
    method: str
    mode_index: int = 0
    numerical_settings: tuple[str, ...]

    @model_validator(mode="after")
    def coherent_branch(self) -> Self:
        f, c = self.frequencies_hz, self.velocities_ms
        if (
            f.ndim != 1
            or f.size == 0
            or c.shape != f.shape
            or not np.all(np.isfinite(f))
            or not np.all(np.isfinite(c))
            or np.any(f <= 0)
            or np.any(c <= 0)
            or np.any(np.diff(f) <= 0)
            or self.mode_index < 0
        ):
            raise ValueError("Rama requiere f/c positivas finitas alineadas, f creciente y modo no negativo")
        return self


def _frequencies(value: npt.ArrayLike) -> npt.NDArray[np.float64]:
    f = np.asarray(value, dtype=np.float64)
    if f.ndim != 1 or f.size == 0 or not np.all(np.isfinite(f)) or np.any(f <= 0) or np.any(np.diff(f) <= 0):
        raise ValueError("Banda explícita positiva finita estrictamente creciente requerida")
    return f


def phase_disba(model: LayeredModel, frequencies_hz: npt.ArrayLike, *, dc_ms: float = 0.005) -> PhaseCurve:
    from disba import PhaseDispersion

    f = _frequencies(frequencies_hz)
    if not np.isfinite(dc_ms) or dc_ms <= 0:
        raise ValueError("Paso de búsqueda positivo finito")
    layers = np.asarray(model.layers, dtype=np.float64)
    # disba usa km, km/s, g/cm3, segundos; f creciente implica periodos invertidos.
    solver = PhaseDispersion(
        layers[:, 0] / 1000,
        layers[:, 1] / 1000,
        layers[:, 2] / 1000,
        layers[:, 3] / 1000,
        algorithm="dunkin",
        dc=dc_ms / 1000,
    )
    periods = (1 / f)[::-1].copy()
    result = solver(periods, mode=0, wave="rayleigh")
    returned = np.asarray(result.period, dtype=np.float64)
    if returned.shape != periods.shape or not np.allclose(returned, periods, rtol=1e-12, atol=0):
        raise ValueError("Forward perdió puntos/mode cutoffs: no excluir silenciosamente parte de la banda")
    velocities = np.asarray(result.velocity, dtype=np.float64)[::-1] * 1000
    if not np.all(np.isfinite(velocities)) or np.any(velocities <= 0):
        raise ValueError("Forward devolvió velocidades inválidas")
    return PhaseCurve(
        frequencies_hz=f,
        velocities_ms=velocities,
        method="disba 0.7 Dunkin; port of CPS/surf96",
        numerical_settings=(f"dc_ms={dc_ms}", "SI->km/km_s/g_cm3; t=1/f; no omitted points"),
    )


def _fem_omega(model: LayeredModel, k: float, ppd: int, depth_lengths: float) -> float:
    max_vs = max(layer[2] for layer in model.layers)
    hmax = min(layer[2] for layer in model.layers) / max_vs / (k * ppd)
    bottom = 0.0
    elements = []
    rho_scale = model.layers[0][3]
    for height, vp, vs, rho in model.layers:
        thickness = height if height else depth_lengths / k
        count = max(1, math_ceil(thickness / hmax))
        h = thickness / count
        elements.extend([(h, vp, vs, rho / rho_scale)] * count)
        bottom += thickness
    n = len(elements) + 1
    if n > 20000:
        raise ValueError("Presupuesto de referencia FEM excedido; no es un límite físico")
    B = np.array([[-0.5, 0.5], [-0.5, 0.5]])
    h, vp, vs, rho = np.asarray(elements, dtype=np.float64).T
    mu = (rho * vs * vs)[:, None, None]
    lam = (rho * (vp * vp - 2 * vs * vs))[:, None, None]
    H = h[:, None, None] * np.array([[2.0, 1.0], [1.0, 2.0]]) / 6
    G = np.array([[1.0, -1.0], [-1.0, 1.0]]) / h[:, None, None]
    coupling = k * (lam * B - mu * B.T)
    local = np.zeros((n - 1, 4, 4))
    local_mass = np.zeros_like(local)
    local[:, :2, :2] = (lam + 2 * mu) * k * k * H + mu * G
    local[:, 2:, 2:] = (lam + 2 * mu) * G + mu * k * k * H
    local[:, :2, 2:] = coupling
    local[:, 2:, :2] = coupling.transpose(0, 2, 1)
    local_mass[:, :2, :2] = local_mass[:, 2:, 2:] = rho[:, None, None] * H
    indices = 2 * np.arange(n - 1)[:, None] + np.array([0, 2, 1, 3])
    rows, cols = np.repeat(indices, 4, axis=1).ravel(), np.tile(indices, (1, 4)).ravel()
    K = coo_matrix((local.ravel(), (rows, cols)), shape=(2 * n, 2 * n)).tocsc()[:-2, :-2]
    M = coo_matrix((local_mass.ravel(), (rows, cols)), shape=(2 * n, 2 * n)).tocsc()[:-2, :-2]
    # Superficie libre natural; base Dirichlet. Refinar dz y expandir profundidad por separado.
    eigenvalues = eigsh(
        K, k=1, M=M, sigma=0.0, which="LM", v0=np.linspace(1.0, 2.0, 2 * n - 2), tol=1e-10, return_eigenvectors=False
    )
    value = float(eigenvalues[0])
    if not np.isfinite(value) or value <= 0:
        raise ValueError("Autovalor FEM no físico; revisar malla/dominio")
    return float(np.sqrt(value))


def math_ceil(value: float) -> int:
    return int(np.ceil(value))


def phase_fem(
    model: LayeredModel, frequencies_hz: npt.ArrayLike, *, points_per_decay: int = 40, depth_decay_lengths: float = 16.0
) -> PhaseCurve:
    f = _frequencies(frequencies_hz)
    if (
        type(points_per_decay) is not int
        or points_per_decay < 4
        or not np.isfinite(depth_decay_lengths)
        or depth_decay_lengths < 4
    ):
        raise ValueError("FEM requiere ppd>=4 y profundidad>=4/k")
    lo, hi = 0.5 * min(layer[2] for layer in model.layers), 0.9999 * model.layers[-1][2]
    velocities = []
    for frequency in f:
        omega = 2 * np.pi * frequency

        def residual(c: float, omega: float = float(omega)) -> float:
            return float(_fem_omega(model, float(omega / c), points_per_decay, depth_decay_lengths) / omega - 1)

        velocity = float(brentq(residual, lo, hi, xtol=1e-5, rtol=1e-10))
        velocities.append(velocity)
    return PhaseCurve(
        frequencies_hz=f,
        velocities_ms=np.asarray(velocities, dtype=np.float64),
        method="GeoQC linear vertical FEM variational plane strain",
        numerical_settings=(
            f"points_per_decay={points_per_decay}",
            f"halfspace_depth={depth_decay_lengths}/k",
            "fundamental lowest eigenbranch; bottom Dirichlet; surface natural free; SI",
        ),
    )
