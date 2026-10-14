from typing import Literal

from geoqc.core.models import Acquisition, Digest, FrozenModel, Geometry, Mask, Nonnegative


class IngestContext(FrozenModel):
    shot_id: str
    acquisition: Acquisition
    geometry_policy: Literal["HEADER", "SIDECAR"]
    geometry: Geometry | None = None
    header_coordinate_uncertainty_m: tuple[Nonnegative, ...] | None = None
    header_crs: str | None = None
    time_reference: Literal["SOURCE_INITIATION_VERIFIED", "SIDECAR_AUTHORITATIVE"]
    t0_s: tuple[float, ...] | None = None
    waveform_sha256: Digest | None = None
    valid_mask: Mask | None = None
    mask_reasons: tuple[str, ...] | None = None
    provenance: str
    original_headers_json: str | None = None
