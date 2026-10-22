from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from geoqc.core.models import FrozenModel, Nonnegative, Positive
from geoqc.qc.contracts import Window


class PickProtocol(FrozenModel):
    search: Window
    noise: Window
    band_hz: tuple[Positive, Positive] = (40, 160)
    sta_s: Positive = 0.002
    lta_s: Positive = 0.02
    trigger_ratio: Positive = 8
    refine_pre_s: Positive = 0.012
    refine_post_s: Positive = 0.025
    minimum_segment_samples: int = Field(default=8, ge=2, strict=True)
    variance_floor_fraction: float = Field(default=1e-8, gt=0, lt=1)
    min_sustained_s: Positive = 0.015
    preprocessing: Literal["RAW_DC_REMOVED"] = "RAW_DC_REMOVED"
    noise_position: Literal["PRE_SEARCH", "DECLARED_POST_SIGNAL"] = Field(
        default="PRE_SEARCH", exclude_if=lambda value: value == "PRE_SEARCH"
    )
    domain_id: str | None = None
    provenance: str = Field(min_length=1)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.sta_s >= self.lta_s or self.band_hz[0] >= self.band_hz[1]:
            raise ValueError("STA<LTA y banda ordenada requeridos")
        if self.noise_position == "PRE_SEARCH" and self.noise.end_s > self.search.start_s:
            raise ValueError("Ruido debe preceder la ventana de búsqueda")
        if self.noise_position == "DECLARED_POST_SIGNAL" and self.noise.start_s < self.search.end_s:
            raise ValueError("Referencia posterior de ruido no debe solaparse con búsqueda")
        return self


class PickCalibration(FrozenModel):
    domain_id: str = Field(min_length=1)
    protocol_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    estimator_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    dt_s: Positive
    errors_s: tuple[float, ...]
    training_ref: str = Field(min_length=1)
    scope: Literal["DECLARED_SYNTHETIC_DOMAIN_ONLY"] = "DECLARED_SYNTHETIC_DOMAIN_ONLY"

    @model_validator(mode="after")
    def sufficient(self) -> Self:
        if len(self.errors_s) < 500:
            raise ValueError("Calibración sintética requiere al menos 500 errores independientes")
        return self


class TRSProtocol(FrozenModel):
    picking: PickProtocol
    branch_error_model: Literal["UNKNOWN", "GAUSSIAN_CANDIDATE"] = "UNKNOWN"
    horizontal_two_layers_verified: bool = False
    geological_model_ref: str | None = None
    initial_v1_v2_h: tuple[Positive, Positive, Positive] = (300, 1500, 5)
    max_evaluations: int = Field(default=5, ge=1, le=500, strict=True)
    max_segments: int = Field(default=2, ge=1, le=3, strict=True)
    roi_ref: str | None = None
    source_clock_correction_s: float = 0
    time_correction_ref: str | None = None
    provenance: str = Field(min_length=1)

    @model_validator(mode="after")
    def explicit_models(self) -> Self:
        if self.initial_v1_v2_h[0] >= self.initial_v1_v2_h[1]:
            raise ValueError("Modelo inicial V1<V2")
        if self.horizontal_two_layers_verified and (not self.geological_model_ref or not self.roi_ref):
            raise ValueError("Modelo verificado requiere referencia geológica y ROI")
        if self.source_clock_correction_s != 0 and not self.time_correction_ref:
            raise ValueError("Corrección de fuente/clock requiere referencia externa")
        return self


class ReciprocalObservation(FrozenModel):
    source_id: str = Field(min_length=1)
    receiver_id: str = Field(min_length=1)
    time_s: Nonnegative
    sigma_s: Nonnegative
    source_delay_s: float = 0
    clock_delay_s: float = 0
    error_model_ref: str = Field(min_length=1)


class Ray(FrozenModel):
    observation_id: str = Field(min_length=1)
    points_xz_m: tuple[tuple[float, float], ...]
    weight: Positive = 1

    @model_validator(mode="after")
    def points(self) -> Self:
        if len(self.points_xz_m) < 2:
            raise ValueError("Rayo necesita al menos dos vértices")
        return self


class Grid2D(FrozenModel):
    x_edges_m: tuple[float, ...]
    z_edges_m: tuple[float, ...]
    reference: str = Field(min_length=1)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        for values in (self.x_edges_m, self.z_edges_m):
            if len(values) < 2 or any(b <= a for a, b in zip(values, values[1:], strict=False)):
                raise ValueError("Bordes de malla crecientes, con al menos una celda")
        return self

    @property
    def shape(self) -> tuple[int, int]:
        return len(self.z_edges_m) - 1, len(self.x_edges_m) - 1
