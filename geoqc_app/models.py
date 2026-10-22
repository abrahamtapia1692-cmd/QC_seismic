from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from geoqc.masw.contracts import MASWProtocol
from geoqc.qc.adapter import TraceQCRequest
from geoqc.trs.contracts import TRSProtocol

Text = Annotated[str, Field(min_length=1, max_length=4000, pattern=r"\S")]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class AcquisitionCreate(RequestModel):
    project_id: UUID
    name: Text


class UploadCreate(RequestModel):
    acquisition_id: UUID


class UploadCancellation(RequestModel):
    reason: Text


class ExportCreate(RequestModel):
    format: Literal["CSV", "HTML", "PDF"]


class RevisionCreate(RequestModel):
    uploads: tuple[UUID, ...] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def unique_uploads(self) -> Self:
        if len(set(self.uploads)) != len(self.uploads):
            raise ValueError("Sesiones duplicadas")
        return self


class RunCreate(RequestModel):
    revision_id: UUID
    technique: Literal["MASW", "TRS"] = Field(default="MASW", exclude_if=lambda value: value == "MASW")
    protocol: MASWProtocol | TRSProtocol
    trace_qc: TraceQCRequest | None = Field(default=None, exclude_if=lambda value: value is None)
    excluded_receiver_ids: tuple[Text, ...] = Field(default=(), max_length=4, exclude_if=lambda value: not value)

    @model_validator(mode="after")
    def supported(self) -> Self:
        if self.technique == "TRS":
            if not isinstance(self.protocol, TRSProtocol) or self.excluded_receiver_ids:
                raise ValueError("TRS requiere protocolo TRS y no usa exclusiones de sensibilidad MASW")
            if self.protocol.horizontal_two_layers_verified:
                raise ValueError("TRS local no declara verificación geológica ni habilita inversión")
            return self
        if self.trace_qc is not None:
            raise ValueError("El QC por traza de este recorrido requiere técnica TRS")
        if not isinstance(self.protocol, MASWProtocol) or not self.excluded_receiver_ids:
            raise ValueError("MASW requiere protocolo MASW y exclusiones explícitas")
        if self.protocol.mode_identity != "APPARENT":
            raise ValueError("El perfil local requiere APPARENT")
        if len(self.protocol.frequencies_hz) > 256 or len(self.protocol.velocities_ms) > 512:
            raise ValueError("Rejillas fuera del alcance local")
        if self.protocol.weights is not None and any(w != 1 for w in self.protocol.weights):
            raise ValueError("El perfil local requiere pesos unitarios")
        return self


class ReviewWrite(RequestModel):
    verdict: Literal["ACCEPTED", "REPEAT", "EXTEND"]
    scope: Text
    justification: Text
    caveats: tuple[Text, ...] = Field(default=(), max_length=32)
    scientific_digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]

    @model_validator(mode="after")
    def accepted_caveats(self) -> Self:
        if self.verdict == "ACCEPTED" and not self.caveats:
            raise ValueError("Aceptación diagnóstica requiere salvedades")
        return self


class Reopening(RequestModel):
    expected_version: Annotated[str, Field(pattern=r"^[1-9][0-9]{0,18}$")]
    reason: Text

    @model_validator(mode="after")
    def bigint_version(self) -> Self:
        if int(self.expected_version) >= 2**63:
            raise ValueError("Versión fuera del rango BIGINT")
        return self
