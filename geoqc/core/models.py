"""Contratos v1.4; arrays independientes respaldados por bytes inmutables."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Self

import numpy as np
import numpy.typing as npt
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    WithJsonSchema,
    field_validator,
    model_validator,
)

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]
Quality = Literal["PASS", "WARN", "FAIL"]
Applicability = Literal["APPLICABLE", "NOT_APPLICABLE", "UNKNOWN"]
Validity = Literal["VALID", "MISSING", "INVALID", "MODEL_INAPPLICABLE", "COMPUTATION_ERROR", "UNCALIBRATED"]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


def _float_array(value: Any) -> FloatArray:
    a = np.asarray(value, dtype=np.float64)
    return np.frombuffer(a.tobytes(order="C"), dtype=np.float64).reshape(a.shape)


def _bool_array(value: Any) -> BoolArray:
    a = np.asarray(value)
    if a.dtype != np.bool_:
        raise ValueError("La máscara debe contener booleanos, no códigos numéricos")
    return np.frombuffer(a.tobytes(order="C"), dtype=np.bool_).reshape(a.shape)


def _serialize_float(value: FloatArray) -> Any:
    a = value.astype(object)
    a[~np.isfinite(value)] = None
    return a.tolist()


def _serialize_bool(value: BoolArray) -> Any:
    return value.tolist()


Array = Annotated[
    FloatArray,
    BeforeValidator(_float_array),
    PlainSerializer(_serialize_float),
    WithJsonSchema({"type": "array", "items": {}}),
]
Mask = Annotated[
    BoolArray,
    BeforeValidator(_bool_array),
    PlainSerializer(_serialize_bool),
    WithJsonSchema({"type": "array", "items": {}}),
]


class FrozenModel(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", arbitrary_types_allowed=True, allow_inf_nan=False, validate_default=True
    )
    schema_version: Literal["1.4"] = "1.4"


class Acquisition(FrozenModel):
    technique: Literal["MASW", "TRS"]
    wave: Literal["RAYLEIGH", "P"]
    component: Literal["Z", "X", "Y"]
    receiver_ids: tuple[str, ...]
    source_type: Annotated[str, Field(min_length=1)]
    orientation_degrees: tuple[float, float] | None = None
    trigger_ref: str | None = None
    response_ref: str | None = None
    calibration_ref: str | None = None
    adc_rails: tuple[float, float] | None = None
    gain: Positive | None = None
    amplitude_unit: Literal["counts", "V", "m", "m/s", "m/s2"] = "counts"
    stack_count: Annotated[int, Field(ge=1, strict=True)] = 1
    stack_kind: Literal["RAW", "SUM", "MEAN", "UNKNOWN"] = "UNKNOWN"
    replica_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def coherent_acquisition(self) -> Self:
        if not self.receiver_ids or len(set(self.receiver_ids)) != len(self.receiver_ids):
            raise ValueError("Se requieren identificadores físicos únicos de receptor")
        if any(not receiver.strip() for receiver in self.receiver_ids):
            raise ValueError("Identificador de receptor vacío")
        if self.technique == "MASW" and (self.wave != "RAYLEIGH" or self.component != "Z"):
            raise ValueError("El perfil inicial MASW requiere Rayleigh vertical")
        if self.technique == "TRS" and self.wave != "P":
            raise ValueError("El perfil inicial TRS modela ondas P")
        if self.adc_rails is not None and self.adc_rails[0] >= self.adc_rails[1]:
            raise ValueError("Rails ADC deben estar ordenados")
        return self


class Geometry(FrozenModel):
    xr: Array
    yr: Array
    zr: Array
    xs: float
    ys: float
    zs: float
    uncertainty_m: tuple[Nonnegative, ...]
    crs: Annotated[str, Field(min_length=1)]
    provenance: tuple[str, ...]
    permutation: tuple[int, ...] | None = None

    @model_validator(mode="after")
    def coherent_coordinates(self) -> Self:
        n = self.xr.size
        if n < 1 or any(a.shape != (n,) or not np.all(np.isfinite(a)) for a in (self.xr, self.yr, self.zr)):
            raise ValueError("Coordenadas finitas 1D y con igual número de receptores")
        if len(self.uncertainty_m) != n or not self.provenance:
            raise ValueError("Falta incertidumbre o procedencia de geometría")
        if self.permutation is not None and sorted(self.permutation) != list(range(n)):
            raise ValueError("Permutación debe ser biyectiva")
        return self

    @property
    def horizontal_offsets_m(self) -> FloatArray:
        return np.hypot(self.xr - self.xs, self.yr - self.ys)

    @property
    def mean_horizontal_offset_m(self) -> float:
        return float(np.mean(self.horizontal_offsets_m))

    @property
    def aperture_m(self) -> float:
        return float(np.ptp(self.xr))

    @property
    def uniform_effective_aperture_m(self) -> float | None:
        if self.xr.size < 2 or not np.all(self.yr == self.yr[0]) or not np.all(self.zr == self.zr[0]):
            return None
        delta = np.diff(self.xr)
        if np.any(delta <= 0) or not np.allclose(delta, delta[0], rtol=1e-12, atol=0):
            return None
        return float(self.xr.size * delta[0])


class Shot(FrozenModel):
    id: Annotated[str, Field(min_length=1)]
    data: Array
    valid_mask: Mask
    mask_reasons: tuple[str, ...]
    dt_s: tuple[Positive, ...]
    t0_s: tuple[float, ...]
    geometry: Geometry
    acquisition: Acquisition
    input_hashes: tuple[Digest, ...]
    headers_json: str

    @field_validator("headers_json")
    @classmethod
    def canonical_headers(cls, value: str) -> str:
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("Cabeceras deben ser un objeto JSON")
        return json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

    @model_validator(mode="after")
    def coherent_shot(self) -> Self:
        if self.data.ndim != 2 or min(self.data.shape) < 1 or self.valid_mask.shape != self.data.shape:
            raise ValueError("Datos y máscara deben tener igual forma (canales,muestras)")
        n = self.data.shape[0]
        if (
            any(len(v) != n for v in (self.dt_s, self.t0_s, self.mask_reasons, self.acquisition.receiver_ids))
            or self.geometry.xr.size != n
        ):
            raise ValueError("Geometría, tiempos y receptores no coinciden con los canales")
        if np.any(self.valid_mask & ~np.isfinite(self.data)):
            raise ValueError("NaN/Inf debe quedar enmascarado")
        if any(not reason for reason, mask in zip(self.mask_reasons, self.valid_mask, strict=True) if not np.all(mask)):
            raise ValueError("Todo canal con muestras excluidas requiere motivo")
        if not self.input_hashes:
            raise ValueError("Se requiere hash del dato original")
        return self


class Metric(FrozenModel):
    id: str
    unit: str
    scope: Literal["trace", "shot", "technique", "survey"] = "shot"
    support_refs: tuple[str, ...] = ()
    value: float | None = None
    uncertainty: Nonnegative | None = None
    applicability: Applicability
    validity: Validity
    reason: Annotated[str, Field(min_length=1)]
    direction: Literal["higher_is_better", "lower_is_better"] | None = None
    threshold_ref: str | None = None
    mandatory: bool
    critical: bool
    calibration_ref: str | None = None
    quality_status: Quality | None = None
    action_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def coherent_validity(self) -> Self:
        if self.validity != "VALID" or self.applicability != "APPLICABLE":
            if self.quality_status is not None:
                raise ValueError("Una métrica no válida/aplicable no puede declarar calidad PASS/WARN/FAIL")
        elif self.value is None:
            raise ValueError("Estimación VALID requiere valor y su incertidumbre o motivo explícito")
        return self


class ArrivalPick(FrozenModel):
    onset_s: float | None
    sigma_s: Nonnegative | None
    bias_s: float | None
    confidence: Literal["CALIBRATED", "UNCALIBRATED", "MISSING", "AMBIGUOUS"]
    reason: str
    window_s: tuple[float, float]
    preprocessing_ref: str
    shared_error_refs: tuple[str, ...] = ()
    interval_s: tuple[float, float] | None = None

    @model_validator(mode="after")
    def coherent_pick(self) -> Self:
        lo, hi = self.window_s
        if lo >= hi or not self.reason or not self.preprocessing_ref:
            raise ValueError("Ventana ordenada, motivo y preprocessing requeridos")
        if self.onset_s is not None and not lo <= self.onset_s <= hi:
            raise ValueError("Onset fuera de la ventana de búsqueda")
        if self.confidence == "MISSING" and self.onset_s is not None:
            raise ValueError("MISSING no puede contener onset")
        if self.confidence == "CALIBRATED" and (self.onset_s is None or self.sigma_s is None or self.bias_s is None):
            raise ValueError("CALIBRATED requiere onset, incertidumbre y sesgo")
        if self.interval_s is not None:
            left, right = self.interval_s
            if left > right or self.onset_s is None or not left <= self.onset_s <= right:
                raise ValueError("Intervalo no contiene el onset")
        return self


class DispersionCurve(FrozenModel):
    frequencies_hz: tuple[Positive, ...]
    velocities_ms: tuple[Positive, ...]
    sigma_ms: tuple[Nonnegative | None, ...]
    valid_mask: tuple[bool, ...]
    reasons: tuple[str, ...]
    mode_identity: Literal["CONFIRMED", "APPARENT", "UNKNOWN"]
    point_provenance: tuple[str, ...]
    resolution_ref: str | None = None
    covariance_ref: str | None = None
    band_refs: tuple[str, ...] = ()
    mode_uncertainty_reason: str = "NOT_ESTIMATED"

    @model_validator(mode="after")
    def coherent_curve(self) -> Self:
        n = len(self.frequencies_hz)
        if any(
            len(a) != n
            for a in (self.velocities_ms, self.sigma_ms, self.valid_mask, self.reasons, self.point_provenance)
        ):
            raise ValueError("Campos de curva deben tener igual tamaño")
        if any(b <= a for a, b in zip(self.frequencies_hz, self.frequencies_hz[1:], strict=False)):
            raise ValueError("Frecuencias deben estar ordenadas y ser únicas")
        if any(
            not reason or not provenance for reason, provenance in zip(self.reasons, self.point_provenance, strict=True)
        ):
            raise ValueError("Cada punto requiere estado y procedencia")
        if any(valid and reason != "VALID" for valid, reason in zip(self.valid_mask, self.reasons, strict=True)):
            raise ValueError("La máscara no puede aceptar puntos inválidos")
        return self


class Coverage(FrozenModel):
    roi_ref: str
    mesh_ref: str
    topography_ref: str
    ray_model_ref: str
    hits: tuple[Annotated[int, Field(ge=0)], ...]
    dws_m: tuple[Nonnegative, ...]
    angular_span_degrees: tuple[Annotated[float, Field(ge=0, le=180)] | None, ...]
    anisotropy: tuple[Annotated[float, Field(ge=0, le=1)] | None, ...]
    resolved_mask: tuple[bool, ...]
    limitations: tuple[str, ...]

    @model_validator(mode="after")
    def coherent_coverage(self) -> Self:
        n = len(self.hits)
        if any(len(v) != n for v in (self.dws_m, self.angular_span_degrees, self.anisotropy, self.resolved_mask)):
            raise ValueError("Cobertura por celda debe tener tamaños compatibles")
        for hits, span, anisotropy, resolved in zip(
            self.hits, self.angular_span_degrees, self.anisotropy, self.resolved_mask, strict=True
        ):
            if hits == 0 and (span is not None or anisotropy is not None or resolved):
                raise ValueError("Celda sin rayos tiene ángulos desconocidos")
        return self


class QCReport(FrozenModel):
    scope: Literal["trace", "shot", "technique", "survey"]
    metrics: tuple[Metric, ...]
    quality_status: Quality | None
    evidence_status: Literal["COMPLETE", "INCOMPLETE", "OUT_OF_SCOPE"]
    diagnostic_mode: Literal[True] = True
    missing_requirement_ids: tuple[str, ...]
    satisfied_requirement_ids: tuple[str, ...]
    config_hash: Digest
    data_hashes: tuple[Digest, ...]
    code_hash: Digest
    calibration_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    operator_decision: Literal["PENDING"] = "PENDING"

    @model_validator(mode="after")
    def coherent_report(self) -> Self:
        if set(self.missing_requirement_ids) & set(self.satisfied_requirement_ids):
            raise ValueError("Requisito simultáneamente satisfecho y faltante")
        if self.evidence_status == "COMPLETE" and self.missing_requirement_ids:
            raise ValueError("COMPLETE no puede tener requisitos faltantes")
        if self.evidence_status == "COMPLETE" and any(
            m.mandatory and (m.validity != "VALID" or m.applicability == "UNKNOWN") for m in self.metrics
        ):
            raise ValueError("COMPLETE incompatible con métrica obligatoria ausente/inválida")
        valid_quality = [m.quality_status for m in self.metrics if m.quality_status is not None]
        expected = (
            "FAIL"
            if "FAIL" in valid_quality
            else "WARN"
            if "WARN" in valid_quality
            else "PASS"
            if valid_quality
            else None
        )
        if self.quality_status != expected:
            raise ValueError("Estado de calidad incoherente con comprobaciones válidas")
        return self

    @property
    def eligible_for_acceptance(self) -> bool:
        # E0 solo permite diagnósticos. La derivación operativa corresponde a E6/G9.
        return False


class IngestFailure(FrozenModel):
    path: str
    data_hash: Digest | None
    error_code: str
    reason: str
    action_ids: tuple[str, ...]
