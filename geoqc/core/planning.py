"""Escenarios condicionados; nunca certifican banda ni profundidad observada."""

from __future__ import annotations

from typing import Literal

import numpy as np

from geoqc.core.config import ProjectConfig
from geoqc.core.models import FrozenModel, Geometry
from geoqc.core.physics import rayleigh_halfspace_velocity, wavelengths_m


class PlanningReport(FrozenModel):
    status: Literal["FEASIBLE_UNDER_ASSUMPTIONS", "NOT_DEMONSTRATED", "INCOMPATIBLE_WITH_ASSUMPTIONS"]
    nominal_phase_velocity_ms: float
    nominal_low_frequency_hz: float
    nominal_low_frequency_depth_m: float
    aperture_m: float
    uniform_effective_aperture_m: float | None
    nacd_center_at_48m: float
    near_offset_ratio_at_48m: float
    scenario_frequency_band_hz: tuple[float, float]
    scenario_wavelengths_at_band_edges_m: tuple[float, float]
    scenario_nacd_at_band_edges: tuple[float, float]
    scenario_near_offset_ratio_at_band_edges: tuple[float, float]
    scenario_max_frequency_for_target_hz: float
    scenario_uniform_nyquist_frequency_hz: float | None
    assumptions: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def eligible_for_acceptance(self) -> bool:
        return False


class ObservedBand(FrozenModel):
    frequencies_hz: tuple[float, ...]
    wavelengths_m: tuple[float, ...]
    nominal_depth_m: float | None
    reasons: tuple[str, ...]
    source_frequencies_hz: tuple[float, ...]
    source_valid_mask: tuple[bool, ...]
    kappa_z: float

    @property
    def eligible_for_acceptance(self) -> bool:
        return False


def planning(config: ProjectConfig, geometry: Geometry) -> PlanningReport:
    assumptions = config.planning
    c = rayleigh_halfspace_velocity(assumptions.vs_prior_ms, assumptions.nu_prior)
    low = assumptions.nominal_kg * assumptions.fn_hz
    nominal_depth = c / (low * assumptions.kappa_z)
    f0, f1 = assumptions.frequency_band_hz
    l0, l1 = wavelengths_m((f0, f1), (c, c))
    near = float(np.min(geometry.horizontal_offsets_m))
    effective = geometry.uniform_effective_aperture_m
    return PlanningReport(
        status="NOT_DEMONSTRATED",
        nominal_phase_velocity_ms=c,
        nominal_low_frequency_hz=low,
        nominal_low_frequency_depth_m=nominal_depth,
        aperture_m=geometry.aperture_m,
        uniform_effective_aperture_m=geometry.uniform_effective_aperture_m,
        nacd_center_at_48m=geometry.mean_horizontal_offset_m / 48.0,
        near_offset_ratio_at_48m=float(np.min(geometry.horizontal_offsets_m)) / 48.0,
        scenario_frequency_band_hz=(f0, f1),
        scenario_wavelengths_at_band_edges_m=(float(l0), float(l1)),
        scenario_nacd_at_band_edges=(geometry.mean_horizontal_offset_m / l0, geometry.mean_horizontal_offset_m / l1),
        scenario_near_offset_ratio_at_band_edges=(near / l0, near / l1),
        scenario_max_frequency_for_target_hz=c / (assumptions.kappa_z * config.project.z_obj_m),
        scenario_uniform_nyquist_frequency_hz=None if effective is None else c * geometry.xr.size / (2 * effective),
        assumptions=(assumptions.description, "Frecuencia nominal k_g f_n; no es corte físico"),
        reasons=("Falta banda medida y validada respecto al objetivo", "Geometría y prior no demuestran suficiencia"),
    )


def observed_band(
    frequencies_hz: tuple[float, ...],
    velocities_ms: tuple[float, ...],
    valid_mask: tuple[bool, ...],
    reasons: tuple[str, ...],
    *,
    kappa_z: float = 2.5,
) -> ObservedBand:
    n = len(frequencies_hz)
    if any(len(v) != n for v in (velocities_ms, valid_mask, reasons)):
        raise ValueError("Banda debe conservar un estado por punto")
    f = np.asarray(frequencies_hz, dtype=float)
    c = np.asarray(velocities_ms, dtype=float)
    if not np.isfinite(kappa_z) or kappa_z <= 0 or not np.all(np.isfinite(f)) or not np.all(np.isfinite(c)):
        raise ValueError("Magnitudes deben ser finitas y kappa_z positiva")
    if np.any(f <= 0) or np.any(c <= 0) or np.any(np.diff(f) <= 0):
        raise ValueError("Frecuencias positivas crecientes y velocidades positivas requeridas")
    if any(valid and reason != "VALID" for valid, reason in zip(valid_mask, reasons, strict=True)):
        raise ValueError("La máscara no puede aceptar un punto con motivo inválido")
    if any(type(valid) is not bool for valid in valid_mask) or any(not reason for reason in reasons):
        raise ValueError("Éxito booleano y motivo explícito por punto requeridos")
    computed = wavelengths_m(f, c)
    wavelengths = tuple(float(value) for value, valid in zip(computed, valid_mask, strict=True) if valid)
    return ObservedBand(
        frequencies_hz=tuple(freq for freq, valid in zip(frequencies_hz, valid_mask, strict=True) if valid),
        wavelengths_m=wavelengths,
        nominal_depth_m=max(wavelengths) / kappa_z if wavelengths else None,
        reasons=reasons,
        source_frequencies_hz=frequencies_hz,
        source_valid_mask=valid_mask,
        kappa_z=kappa_z,
    )
