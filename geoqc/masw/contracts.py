from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from geoqc.core.models import Digest, FrozenModel, Nonnegative, Positive
from geoqc.qc.contracts import Window


class MASWProtocol(FrozenModel):
    signal: Window
    frequencies_hz: tuple[Positive, ...]
    velocities_ms: tuple[Positive, ...]
    directions: tuple[Literal[-1, 1], ...] = (1, -1)
    window: Literal["RECTANGULAR", "HANN"] = "HANN"
    weights: tuple[Nonnegative, ...] | None = None
    ridge_slope_scale_ms_per_hz: Positive = 30
    ridge_penalty: Nonnegative = 0.02
    mode_identity: Literal["APPARENT", "UNKNOWN", "CONFIRMED"] = "APPARENT"
    mode_evidence_ref: str | None = None
    active_event_ref: str | None = None
    response_ref: str | None = None
    nearfield_calibration_ref: str | None = None
    domain_id: str | None = None
    provenance: str = Field(min_length=1)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        for values in (self.frequencies_hz, self.velocities_ms):
            if len(values) < 2 or any(b <= a for a, b in zip(values, values[1:], strict=False)):
                raise ValueError("Rejillas positivas crecientes con al menos dos puntos")
        if len(set(self.directions)) != len(self.directions) or not self.directions:
            raise ValueError("Direcciones únicas requeridas")
        if self.mode_identity == "CONFIRMED" and not self.mode_evidence_ref:
            raise ValueError("Identidad confirmada requiere evidencia modal independiente")
        return self


class PeakCalibration(FrozenModel):
    method: Literal["EMPIRICAL_MAXIMUM"] = "EMPIRICAL_MAXIMUM"
    protocol_hash: Digest
    estimator_hash: Digest
    n_active: int = Field(ge=2, strict=True)
    geometry_hash: Digest
    dt_s: Positive
    domain_id: str = Field(min_length=1)
    training_ref: str = Field(min_length=1)
    maximum_scores: tuple[Nonnegative, ...]
    alpha: Positive = 0.05
    scope: Literal["DECLARED_NOISE_DOMAIN_ONLY"] = "DECLARED_NOISE_DOMAIN_ONLY"

    @model_validator(mode="after")
    def empirical(self) -> Self:
        if len(self.maximum_scores) < 1000 or self.alpha >= 1 or max(self.maximum_scores) > 1:
            raise ValueError("Nula requiere >=1000 máximos en [0,1] y alpha<1")
        return self


class CurveCalibration(FrozenModel):
    protocol_hash: Digest
    estimator_hash: Digest
    n_active: int = Field(ge=2, strict=True)
    geometry_hash: Digest
    dt_s: Positive
    direction: Literal[-1, 1] = 1
    domain_id: str = Field(min_length=1)
    training_ref: str = Field(min_length=1)
    frequencies_hz: tuple[Positive, ...]
    errors_ms: tuple[tuple[float, ...], ...]
    scope: Literal["DECLARED_SIGNAL_DOMAIN_ONLY"] = "DECLARED_SIGNAL_DOMAIN_ONLY"

    @model_validator(mode="after")
    def enough(self) -> Self:
        if (
            len(self.frequencies_hz) < 2
            or len(self.errors_ms) < 500
            or any(len(row) != len(self.frequencies_hz) for row in self.errors_ms)
        ):
            raise ValueError("Precisión requiere >=500 errores multivariados alineados por frecuencia")
        if any(b <= a for a, b in zip(self.frequencies_hz, self.frequencies_hz[1:], strict=False)):
            raise ValueError("Frecuencias de calibración crecientes")
        return self
