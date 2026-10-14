"""Geometría observada: irregularidad no equivale a error de posición."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Literal

import numpy as np

from geoqc.core.models import FrozenModel, Geometry


class GeometryDiagnostics(FrozenModel):
    spacing_relative_deviations: tuple[float, ...]
    crossline_extent_m: float
    elevation_extent_m: float
    uniform_kernel_applicable: bool
    cause: Literal["NOT_IDENTIFIABLE_FROM_COORDINATES_ALONE"] = "NOT_IDENTIFIABLE_FROM_COORDINATES_ALONE"
    diagnostic_only: Literal[True] = True
    out_of_support_indices: tuple[int, ...] | None = None


def geometry_diagnostics(
    geometry: Geometry, *, nominal_dx_m: float, support_x_m: tuple[float, float] | None = None
) -> GeometryDiagnostics:
    if not np.isfinite(nominal_dx_m) or nominal_dx_m <= 0:
        raise ValueError("Espaciamiento nominal positivo finito requerido")
    differences = np.diff(geometry.xr)
    outside = None
    if support_x_m is not None:
        lo, hi = support_x_m
        if not np.isfinite((lo, hi)).all() or lo > hi:
            raise ValueError("Soporte de x finito ordenado requerido")
        outside = tuple(int(j) for j in np.flatnonzero((geometry.xr < lo) | (geometry.xr > hi)))
    return GeometryDiagnostics(
        spacing_relative_deviations=tuple(float(v) for v in abs(differences - nominal_dx_m) / nominal_dx_m),
        crossline_extent_m=float(np.ptp(geometry.yr)),
        elevation_extent_m=float(np.ptp(geometry.zr)),
        uniform_kernel_applicable=geometry.uniform_effective_aperture_m is not None,
        out_of_support_indices=outside,
    )


class SideSplit(FrozenModel):
    left_indices: tuple[int, ...]
    right_indices: tuple[int, ...]
    coincident_indices: tuple[int, ...]
    signed_offsets_m: tuple[float, ...]
    horizontal_distances_m: tuple[float, ...]
    crossline_indices: tuple[int, ...]
    azimuths_degrees: tuple[float | None, ...]


def split_sides(geometry: Geometry) -> SideSplit:
    signed = geometry.xr - geometry.xs
    radial = geometry.horizontal_offsets_m
    order = np.argsort(radial, kind="stable")
    return SideSplit(
        left_indices=tuple(int(j) for j in order if signed[j] < 0),
        right_indices=tuple(int(j) for j in order if signed[j] > 0),
        coincident_indices=tuple(int(j) for j in order if radial[j] == 0),
        signed_offsets_m=tuple(float(v) for v in signed),
        horizontal_distances_m=tuple(float(v) for v in radial),
        crossline_indices=tuple(int(j) for j in order if signed[j] == 0 and radial[j] != 0),
        azimuths_degrees=tuple(
            float(np.degrees(np.arctan2(y, x)) % 360) if r > 0 else None
            for x, y, r in zip(signed, geometry.yr - geometry.ys, radial, strict=True)
        ),
    )


class GeometryComparison(FrozenModel):
    status: Literal[
        "WITHIN_TOLERANCE", "DISCREPANCY", "UNCERTAINTY_OVERLAPS_TOLERANCE", "MISSING", "AUTHORITY_UNCONFIRMED"
    ]
    maximum_receiver_discrepancy_m: float | None
    source_discrepancy_m: float | None
    combined_uncertainty_m: float | None
    reason: str
    diagnostic_only: Literal[True] = True


def compare_geometry(
    measured: Geometry, reference: Geometry | None, *, tolerance_m: float, reference_is_authoritative: bool = False
) -> GeometryComparison:
    if not np.isfinite(tolerance_m) or tolerance_m < 0:
        raise ValueError("Tolerancia finita no negativa")
    if reference is None:
        return GeometryComparison(
            status="MISSING",
            maximum_receiver_discrepancy_m=None,
            source_discrepancy_m=None,
            combined_uncertainty_m=None,
            reason="Referencia ausente",
        )
    if reference.crs != measured.crs or reference.xr.size != measured.xr.size:
        raise ValueError("Comparar requiere igual CRS y correspondencia de receptores")
    distances = np.sqrt(
        (measured.xr - reference.xr) ** 2 + (measured.yr - reference.yr) ** 2 + (measured.zr - reference.zr) ** 2
    )
    sigmas = np.hypot(measured.uncertainty_m, reference.uncertainty_m)
    source_distance = float(
        np.linalg.norm(
            np.array((measured.xs, measured.ys, measured.zs)) - np.array((reference.xs, reference.ys, reference.zs))
        )
    )
    if not reference_is_authoritative:
        status: Literal[
            "WITHIN_TOLERANCE", "DISCREPANCY", "UNCERTAINTY_OVERLAPS_TOLERANCE", "AUTHORITY_UNCONFIRMED"
        ] = "AUTHORITY_UNCONFIRMED"
    elif np.all(distances + sigmas <= tolerance_m):
        status = "WITHIN_TOLERANCE"
    elif np.any(distances - sigmas > tolerance_m):
        status = "DISCREPANCY"
    else:
        status = "UNCERTAINTY_OVERLAPS_TOLERANCE"
    if reference_is_authoritative and source_distance > tolerance_m:
        status = "DISCREPANCY"
    return GeometryComparison(
        status=status,
        maximum_receiver_discrepancy_m=float(np.max(distances)),
        source_discrepancy_m=source_distance,
        combined_uncertainty_m=float(np.max(sigmas)),
        reason="Diferencia euclídea; incertidumbres independientes combinadas por RSS (1 sigma), no intervalo de confianza",
    )


def geometry_from_csv(
    path: Path, *, receiver_ids: tuple[str, ...], source_xyz_m: tuple[float, float, float], crs: str
) -> Geometry:
    """CSV SI unido por ID físico; orden no implica permutación del waveform."""
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        expected = {"receiver_id", "x_m", "y_m", "z_m", "uncertainty_m"}
        if reader.fieldnames is None or set(reader.fieldnames) != expected or len(reader.fieldnames) != len(expected):
            raise ValueError("Columnas CSV requeridas: receiver_id,x_m,y_m,z_m,uncertainty_m")
        records = {}
        for row in reader:
            receiver = row["receiver_id"]
            if not receiver or receiver in records or None in row:
                raise ValueError("Fila CSV incompleta, ID duplicado o columnas adicionales")
            records[receiver] = row
    if set(records) != set(receiver_ids) or len(set(receiver_ids)) != len(receiver_ids):
        raise ValueError("CSV y adquisición requieren igual conjunto único de receptores")
    ordered = [records[receiver] for receiver in receiver_ids]
    return Geometry(
        xr=np.asarray([float(row["x_m"]) for row in ordered]),
        yr=np.asarray([float(row["y_m"]) for row in ordered]),
        zr=np.asarray([float(row["z_m"]) for row in ordered]),
        xs=source_xyz_m[0],
        ys=source_xyz_m[1],
        zs=source_xyz_m[2],
        uncertainty_m=tuple(float(row["uncertainty_m"]) for row in ordered),
        crs=crs,
        provenance=(f"CSV SI: {path.name}",),
    )
