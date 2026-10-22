"""Typed, headless MASW dossier adapter for trusted local CLI/worker callers.

This module neither loads datasets/policies at import nor renders artifacts.
The runner supplies provenance; this is not an authorization boundary.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Any, Literal, Self

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from geoqc import __version__
from geoqc.core.config import unique_json_pairs
from geoqc.core.evidence import canonical_hash
from geoqc.core.models import Digest, Shot
from geoqc.masw.contracts import MASWProtocol
from geoqc.masw.diagnostic_quality import UsabilityPolicy
from geoqc.masw.dossier_analysis import USABILITY_GRADES, analyze_spectra, band_rows
from geoqc.masw.report import uncalibrated_masw_diagnostics
from geoqc.masw.statistics import estimator_hash
from geoqc.masw.transform import shot_spectrum

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]


class AdapterModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False, validate_default=True)


class RuntimeVersion(AdapterModel):
    name: Text
    version: Text


class EngineReference(AdapterModel):
    package_version: Text
    code_hash: Digest
    masw_estimator_hash: Digest
    runtime: tuple[RuntimeVersion, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_runtime(self) -> Self:
        if len({item.name for item in self.runtime}) != len(self.runtime):
            raise ValueError("Versiones de entorno duplicadas")
        return self


class ReceiverExclusion(AdapterModel):
    shot_id: Text
    receiver_id: Text


class MASWAdapterInput(AdapterModel):
    schema_version: Literal["app-masw-input-0.1"] = "app-masw-input-0.1"
    acquisition_revision_id: Text
    shots: tuple[Shot, ...] = Field(min_length=1, max_length=4)
    protocol: MASWProtocol
    usability_policy: UsabilityPolicy
    sensitivity_exclusions: tuple[ReceiverExclusion, ...] = Field(min_length=1, max_length=4)
    engine_reference: EngineReference
    scope: Literal["LOCAL_MASW_DIAGNOSTIC_ONLY"] = "LOCAL_MASW_DIAGNOSTIC_ONLY"

    @model_validator(mode="after")
    def supported_inputs(self) -> Self:
        ids = tuple(shot.id for shot in self.shots)
        exclusions = {item.shot_id: item.receiver_id for item in self.sensitivity_exclusions}
        if len(set(ids)) != len(ids) or len(exclusions) != len(self.sensitivity_exclusions):
            raise ValueError("Identificadores de tiros/exclusiones duplicados")
        if set(exclusions) != set(ids):
            raise ValueError("Se requiere una exclusión de sensibilidad explícita por tiro")
        if self.protocol.mode_identity != "APPARENT":
            raise ValueError("El adaptador local inicial solo admite identidad APPARENT")
        if self.protocol.weights is not None and any(weight != 1 for weight in self.protocol.weights):
            raise ValueError("La política de usabilidad inicial requiere pesos iguales unitarios")
        if len(self.protocol.frequencies_hz) > 256 or len(self.protocol.velocities_ms) > 512:
            raise ValueError("Rejillas exceden el alcance local: 256 frecuencias / 512 velocidades")
        for shot in self.shots:
            channels, samples = shot.data.shape
            if shot.acquisition.technique != "MASW":
                raise ValueError("El adaptador requiere tiros MASW")
            if not 3 <= channels <= 64 or samples > 65536:
                raise ValueError("Alcance local: 3..64 canales y hasta 65536 muestras por canal")
            if exclusions[shot.id] not in shot.acquisition.receiver_ids:
                raise ValueError("La exclusión debe identificar un receptor físico del tiro")
            if np.unique(shot.geometry.xr).size != channels:
                raise ValueError("El adaptador requiere coordenadas x distintas")
        return self


class MASWAdapterResult(AdapterModel):
    """Immutable JSON envelope; to_document returns an independent mutable copy."""

    schema_version: Literal["app-masw-result-0.1"] = "app-masw-result-0.1"
    scientific_json: str
    scientific_digest: Digest

    @model_validator(mode="after")
    def verified_content(self) -> Self:
        body = json.loads(self.scientific_json, object_pairs_hook=unique_json_pairs)
        if not isinstance(body, dict) or body.get("schema_version") != "app-masw-dossier-0.1":
            raise ValueError("Contenido de dosier incompatible")
        if body.get("eligible_for_acceptance") is not False or body.get("sufficiency") != {
            "status": "NOT_DEMONSTRATED"
        }:
            raise ValueError("El resultado local no habilita aceptación ni suficiencia")
        if canonical_hash(body) != self.scientific_digest:
            raise ValueError("Digest científico incompatible con el contenido")
        return self

    def to_document(self) -> dict[str, Any]:
        body: dict[str, Any] = json.loads(self.scientific_json)
        return body | {"scientific_digest": self.scientific_digest}

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_document(), ensure_ascii=False, indent=indent, allow_nan=False)


def capture_engine_reference() -> EngineReference:
    """Explicit runner-side I/O; never called implicitly during scientific calculation."""
    package = Path(__file__).resolve().parents[1]
    source_hashes = {
        path.relative_to(package).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(package.rglob("*.py"))
    }
    runtime = {
        "python": platform.python_version(),
        "platform": sys.platform,
        "machine": platform.machine(),
        **{name: version(name) for name in ("numpy", "scipy", "pydantic")},
    }
    return EngineReference(
        package_version=__version__,
        code_hash=canonical_hash(source_hashes),
        masw_estimator_hash=estimator_hash(),
        runtime=tuple(RuntimeVersion(name=name, version=value) for name, value in sorted(runtime.items())),
    )


def _record_diagnostics(shot: Shot, request: MASWAdapterInput, excluded_receiver: str) -> dict[str, Any]:
    protocol, policy = request.protocol, request.usability_policy
    native = uncalibrated_masw_diagnostics(
        shot, protocol, estimator_reference=request.engine_reference.masw_estimator_hash
    )
    observed = shot_spectrum(shot, protocol)
    alternate_window = "RECTANGULAR" if protocol.window == "HANN" else "HANN"
    alternate = shot_spectrum(
        shot, MASWProtocol.model_validate(protocol.model_dump() | {"window": alternate_window})
    )
    f, x, c = observed["frequencies_hz"], observed["x_m"], np.asarray(protocol.velocities_ms)
    receiver_ids = shot.acquisition.receiver_ids
    excluded_index = receiver_ids.index(excluded_receiver)
    df = 1 / (observed["window_samples"] * shot.dt_s[0])
    directions = []
    for direction in protocol.directions:
        evaluated = analyze_spectra(
            observed["spectrum"], alternate["spectrum"], f, x, c,
            policy=policy, slope_scale_ms_per_hz=protocol.ridge_slope_scale_ms_per_hz,
            penalty=protocol.ridge_penalty, excluded_channel_index=excluded_index, direction=direction,
        )
        points = []
        for index, quality in enumerate(evaluated["usability"]):
            item = quality.model_dump(mode="json")
            # Publish support in physical channel order, independently of the
            # signed frame used internally to assess a propagation direction.
            item["active_channel_ids"] = sorted(item["active_channel_ids"])
            # Convert the local signed-q frame back to the physical x convention.
            if item["competitor_q_m_inv"] is not None:
                item["competitor_q_m_inv"] *= direction
            grid_index = int(evaluated["indices"][index])
            if grid_index in (0, c.size - 1) and item["grade"] == "UTILIZABLE":
                item["grade"], item["reasons"] = "REVISAR", ["GRID_EDGE"]
            supported = len(item["active_channel_ids"]) >= 2
            velocity = float(evaluated["ridge_ms"][index]) if supported else None
            item.update(
                receiver_ids=[receiver_ids[i - 1] for i in item["active_channel_ids"]],
                grid_velocity_ms=velocity,
                signed_q_m_inv=None if velocity is None else float(direction * f[index] / velocity),
                sensitivity_velocities_ms=[
                    float(value) if np.isfinite(value) else None
                    for value in evaluated["variant_velocities_ms"][:, index]
                ],
            )
            points.append(item)
        bands = band_rows(
            [
                dict(frequency_hz=p["frequency_hz"], state=p["grade"], reasons=p["reasons"],
                     support_ids=p["receiver_ids"])
                for p in points
            ],
            df,
        )
        directions.append(dict(
            direction=direction, points=points, bands=bands,
            counts={grade: sum(p["grade"] == grade for p in points) for grade in USABILITY_GRADES},
        ))
    time = shot.t0_s[0] + np.arange(shot.data.shape[1]) * shot.dt_s[0]
    selected = (time >= protocol.signal.start_s) & (time < protocol.signal.end_s)
    traces = []
    for index, receiver in enumerate(receiver_ids):
        data, mask = shot.data[index, selected], shot.valid_mask[index, selected]
        complete = bool(mask.all())
        traces.append(dict(
            receiver_id=receiver, channel_index_0based=index,
            valid_fraction=float(mask.mean()), exclusion_reason=observed["excluded"][index],
            rms_ac_native=float(np.sqrt(np.mean((data - data.mean()) ** 2))) if complete else None,
            constant=bool(np.ptp(data) == 0) if complete else None,
            zero=bool(np.all(data == 0)) if complete else None,
        ))
    return dict(
        shot_id=shot.id, amplitude_unit=shot.acquisition.amplitude_unit,
        trace_observations=traces,
        native_diagnostics=native,
        apparent_usability=dict(
            ridge_estimator="GRID_DP_NO_SUBBIN_REFINEMENT",
            native_ridge_estimator="CORE_DP_WITH_PEAK_REFINEMENT",
            base_window=protocol.window, alternative_window=alternate_window,
            sensitivity_excluded_receiver_id=excluded_receiver,
            sensitivity_variant_order=["EXCLUDE_RECEIVER", "ALTERNATIVE_WINDOW", "UNPENALIZED_PEAK"],
            exclusions_do_not_identify_trigger=True,
            directions=directions,
            bin_counts_are_not_quality_percentages=True,
        ),
    )


def build_masw_dossier(request: MASWAdapterInput) -> MASWAdapterResult:
    """Run the same typed calculation from CLI or a future worker, without I/O.

    Revalidate serialized inputs: model_copy and model_construct are not trusted
    scientific entry points. Provenance is supplied by the trusted runner.
    """
    request = MASWAdapterInput.model_validate(request.model_dump(mode="json"))
    exclusions = {item.shot_id: item.receiver_id for item in request.sensitivity_exclusions}
    records = [_record_diagnostics(shot, request, exclusions[shot.id]) for shot in request.shots]
    body = dict(
        schema_version="app-masw-dossier-0.1", method="MASW", scope=request.scope,
        acquisition_revision_id=request.acquisition_revision_id,
        input_manifest=dict(
            shots=[
                dict(
                    shot_id=shot.id, input_hashes=list(shot.input_hashes), scientific_shot_hash=canonical_hash(shot),
                    geometry_hash=canonical_hash(shot.geometry), acquisition_hash=canonical_hash(shot.acquisition),
                    headers_hash=canonical_hash(shot.headers_json),
                    sensitivity_excluded_receiver_id=exclusions[shot.id],
                )
                for shot in request.shots
            ],
            protocol_hash=canonical_hash(request.protocol),
            usability_policy_hash=canonical_hash(request.usability_policy),
        ),
        protocol=request.protocol.model_dump(mode="json"),
        usability_policy=request.usability_policy.model_dump(mode="json"),
        engine_reference=request.engine_reference.model_dump(mode="json"),
        diagnostic_quality=records,
        scientific_status="DIAGNOSTIC_ONLY_INCOMPLETE_EVIDENCE",
        missing_evidence=sorted({
            reason for record in records for reason in record["native_diagnostics"]["missing_requirements"]
        }),
        sufficiency={"status": "NOT_DEMONSTRATED"},
        eligible_for_acceptance=False,
    )
    return MASWAdapterResult(
        scientific_json=json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        scientific_digest=canonical_hash(body),
    )
