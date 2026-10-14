from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from geoqc.core.models import FrozenModel, Nonnegative, Positive
from geoqc.qc.quality import TraceQualityPolicy


class Window(FrozenModel):
    """Intervalo físico [start,end), relativo a la misma referencia que Shot.t0_s."""

    start_s: float
    end_s: float

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.start_s >= self.end_s:
            raise ValueError("Ventana debe tener duración positiva")
        return self


class SimilarityProtocol(FrozenModel):
    """Comparabilidad local declarada; los límites son diagnósticos, no calibrados."""

    arrival: Window
    baseline: Window | None = None
    neighbor_radius_m: Positive
    min_apparent_velocity_ms: Positive
    max_lag_s: Positive
    max_neighbors: int = Field(default=4, ge=3, le=8, strict=True)
    min_neighbors: int = Field(default=3, ge=2, strict=True)
    bad_below_rho: float = Field(default=0.5, gt=0, lt=1)
    warn_below_rho: float = Field(default=0.8, gt=0, lt=1)
    neighbor_consensus_min: float = Field(default=0.8, gt=0, le=1)
    bad_neighbor_fraction_min: float = Field(default=0.75, gt=0.5, le=1)
    baseline_ratio_warn: Positive = 5.0
    comparable_channels: bool
    reference: str = Field(min_length=1)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.bad_below_rho >= self.warn_below_rho or self.min_neighbors > self.max_neighbors:
            raise ValueError("Límites de similitud/vecinos incoherentes")
        if self.max_lag_s > (self.arrival.end_s - self.arrival.start_s) / 4:
            raise ValueError("El desfase máximo debe conservar al menos 75% de solape")
        if self.baseline is not None and (
            max(self.arrival.start_s, self.baseline.start_s) < min(self.arrival.end_s, self.baseline.end_s)
        ):
            raise ValueError("Ventanas de llegada y línea base deben ser disjuntas")
        return self


class QCProtocol(FrozenModel):
    """Supuestos declarados por el operador, nunca inferidos desde amplitudes."""

    analysis: Window
    noise: Window | None = None
    signal: Window | None = None
    noise_independent: bool = False
    noise_stationarity: Literal["VERIFIED", "UNKNOWN", "REJECTED"] = "UNKNOWN"
    stationarity_ref: str | None = None
    expected_relative_amplitude: tuple[Positive, ...] | None = None
    amplitude_model_ref: str | None = None
    log_mad_limit: Positive = 3.5
    amplitude_ratio_bounds: tuple[Positive, Positive] = (0.4, 2.5)
    rail_tolerance: Nonnegative = 0.0
    # Rails expresados en la unidad del waveform RAW; conversión de ganancia explícita.
    rail_scale_to_data: Positive | tuple[Positive, ...] | None = None
    frequency_band_hz: tuple[Positive, Positive] | None = None
    antialias_verified: bool | None = None
    nyquist_margin: float = Field(default=0.8, gt=0, le=1)
    min_group_velocity_ms: Positive | None = None
    group_velocity_verified: bool = False
    group_velocity_ref: str | None = None
    wavelet_duration_s: Nonnegative = 0.0
    post_margin_s: Nonnegative = 0.0
    guard_s: Nonnegative = 0.0
    mains_hz: Positive | None = None
    mains_search_hz: Positive = 1.0
    line_power_ratio: Positive = 20.0
    welch_segment_samples: int = Field(default=256, ge=8, strict=True)
    provenance: str = Field(min_length=1)
    quality_policy: TraceQualityPolicy = TraceQualityPolicy()
    similarity: SimilarityProtocol | None = None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.frequency_band_hz is not None and self.frequency_band_hz[0] >= self.frequency_band_hz[1]:
            raise ValueError("Banda creciente requerida")
        if self.amplitude_ratio_bounds[0] >= 1 or self.amplitude_ratio_bounds[1] <= 1:
            raise ValueError("Límites de amplitud deben rodear uno")
        if self.expected_relative_amplitude is not None and not self.amplitude_model_ref:
            raise ValueError("Normalización de amplitud requiere procedencia del modelo/gain")
        if self.noise_stationarity == "VERIFIED" and not self.stationarity_ref:
            raise ValueError("Estacionariedad verificada requiere evidencia externa")
        if self.group_velocity_verified and (self.min_group_velocity_ms is None or not self.group_velocity_ref):
            raise ValueError("Velocidad de grupo verificada requiere valor y referencia externa")
        if self.noise is not None and self.signal is not None:
            if max(self.noise.start_s, self.signal.start_s) < min(self.noise.end_s, self.signal.end_s):
                raise ValueError("Ventanas de ruido y señal deben ser disjuntas")
        return self


class Diagnostic(FrozenModel):
    id: str
    state: Literal["VALID", "MISSING", "INVALID", "MODEL_INAPPLICABLE", "AMBIGUOUS", "CENSORED"]
    value: float | None = None
    unit: str
    reason: str
    flagged: bool | None = None
    details_json: str = "{}"


class RepeatProtocol(FrozenModel):
    dt_s: Positive
    max_lag_s: Positive
    frequency_band_hz: tuple[Positive, Positive]
    same_source: bool
    comparable_acquisition: bool
    reference: str = Field(min_length=1)
    min_abs_correlation: float = Field(default=0.8, gt=0, le=1)
    ambiguity_ratio: float = Field(default=0.98, gt=0, le=1)

    @model_validator(mode="after")
    def band(self) -> Self:
        lo, hi = self.frequency_band_hz
        if not lo < hi < 1 / (2 * self.dt_s):
            raise ValueError("Banda de repetición fuera de Nyquist")
        return self
