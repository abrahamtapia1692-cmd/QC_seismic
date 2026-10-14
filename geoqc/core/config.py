"""Carga de perfiles DRAFT sin completar información desconocida."""

from __future__ import annotations

import json
import math
from collections.abc import Hashable
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import Field, ValidationError, model_validator
from yaml.nodes import MappingNode, Node

from geoqc.core.errors import ConfigError
from geoqc.core.models import FrozenModel, Positive, Quality


class UniqueKeyLoader(yaml.SafeLoader):
    def construct_mapping(self, node: Node, deep: bool = False) -> dict[Hashable, Any]:
        if not isinstance(node, MappingNode):
            raise ConfigError("Se esperaba un mapping YAML")
        self.flatten_mapping(node)
        result: dict[Hashable, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise ConfigError(f"Clave YAML duplicada o no textual: {key!r}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


MetricId = Literal[
    "clip",
    "snr_db",
    "repeat_rho",
    "jitter_ms",
    "geometry_error_m",
    "nacd_center",
    "near_offset_ratio",
    "repeatability_cov",
    "bandwidth_oct",
]


class Threshold(FrozenModel):
    id: MetricId
    unit: str
    direction: Literal["higher_is_better", "lower_is_better"]
    warn: float
    fail: float
    boundary: Literal["inclusive"]
    mandatory: bool
    critical: bool
    calibration_state: Literal["UNVALIDATED", "CALIBRATED"]
    calibration_ref: str | None = None

    @model_validator(mode="after")
    def coherent_threshold(self) -> Self:
        increasing = self.direction == "lower_is_better"
        if (increasing and self.warn >= self.fail) or (not increasing and self.warn <= self.fail):
            raise ValueError("Umbrales warn/fail incoherentes con direction")
        if self.calibration_state == "CALIBRATED" and not self.calibration_ref:
            raise ValueError("CALIBRATED requiere referencia de evidencia")
        return self

    def diagnostic_classification(self, value: float) -> Quality:
        """Fronteras inclusivas; clasificación candidata, sin elegibilidad operativa."""
        if isinstance(value, bool) or not math.isfinite(value):
            raise ConfigError("Valor finito requerido para comparar umbrales")
        if self.direction == "higher_is_better":
            return "FAIL" if value <= self.fail else "WARN" if value <= self.warn else "PASS"
        return "FAIL" if value >= self.fail else "WARN" if value >= self.warn else "PASS"


def unique_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ConfigError(f"Clave JSON duplicada: {key}")
        result[key] = value
    return result


class Project(FrozenModel):
    z_obj_m: Positive
    targets: tuple[Literal["vs30", "vs_profile", "vp_profile"], ...]
    required_techniques: tuple[Literal["MASW", "TRS"], ...]
    roi_ref: str | None = None

    @model_validator(mode="after")
    def coherent_project(self) -> Self:
        if not self.targets or not self.required_techniques:
            raise ValueError("Se requieren objetivo y técnicas explícitos")
        if "vs30" in self.targets and self.z_obj_m < 30:
            raise ValueError("Vs30 requiere un objetivo que incluya los primeros 30 m")
        if len(set(self.targets)) != len(self.targets) or len(set(self.required_techniques)) != len(
            self.required_techniques
        ):
            raise ValueError("Objetivos/técnicas duplicados")
        return self


class PlanningAssumptions(FrozenModel):
    vs_prior_ms: Positive = 180.0
    nu_prior: float = Field(default=0.4, gt=-1, le=0.5)
    frequency_band_hz: tuple[Positive, Positive] = (2.0, 100.0)
    fn_hz: Positive = 4.5
    damping: Positive = 0.7
    nominal_kg: Positive = 1.0
    kappa_z: Positive = 2.5
    description: str = "Escenario nominal de semiespacio; no demuestra dispersión ni profundidad de campo"

    @model_validator(mode="after")
    def coherent_band(self) -> Self:
        if self.frequency_band_hz[0] >= self.frequency_band_hz[1]:
            raise ValueError("Banda prevista debe tener extremos positivos ordenados")
        return self


class DecisionPolicy(FrozenModel):
    require_calibration: Literal[True] = True
    require_complete_mandatory_evidence: Literal[True] = True
    derive_eligibility: Literal[True] = True


class ProjectConfig(FrozenModel):
    profile: Literal["vs30_sitio", "cimentacion_estandar"]
    profile_state: Literal["DRAFT", "VALIDATED"]
    calibration_ref: str | None = None
    project: Project
    acquisition_ref: str | None = None
    metrics_registry_ref: str | None = None
    validation_manifest_ref: str
    planning: PlanningAssumptions = PlanningAssumptions()
    metrics: tuple[Threshold, ...] = ()
    decision: DecisionPolicy = DecisionPolicy()

    @model_validator(mode="after")
    def coherent_profile(self) -> Self:
        if len({m.id for m in self.metrics}) != len(self.metrics):
            raise ValueError("Métrica duplicada en registro")
        if self.profile == "vs30_sitio" and "vs30" not in self.project.targets:
            raise ValueError("Perfil vs30_sitio requiere target vs30")
        if self.profile_state == "VALIDATED" and not self.calibration_ref:
            raise ValueError("Perfil VALIDATED necesita referencia de calibración")
        return self


def load_config(path: Path, mode: Literal["planning", "acceptance"] = "planning") -> ProjectConfig:
    if mode not in ("planning", "acceptance"):
        raise ConfigError("Modo desconocido")
    try:
        text = path.read_text(encoding="utf-8")
        data = (
            json.loads(text, object_pairs_hook=unique_json_pairs)
            if path.suffix.lower() == ".json"
            else yaml.load(text, Loader=UniqueKeyLoader)
        )
        config = ProjectConfig.model_validate(data)
    except (OSError, ValueError, yaml.YAMLError, ValidationError) as exc:
        raise ConfigError(f"No se pudo validar {path}: {exc}") from exc
    if mode == "acceptance":
        # Un identificador que diga VALIDATED no prueba el registro de G9.
        raise ConfigError("E0 admite planificación/diagnóstico; aceptación necesita evidencia y motor E6/G9")
    return config
