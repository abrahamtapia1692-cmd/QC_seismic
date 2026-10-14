from __future__ import annotations

import math

import numpy as np

from geoqc.core.models import Coverage, FloatArray
from geoqc.trs.contracts import Grid2D, Ray


def angular_metrics(angles_radians: FloatArray, weights: FloatArray | None = None) -> tuple[float | None, float | None]:
    angles = np.asarray(angles_radians, dtype=float)
    if angles.ndim != 1 or not np.all(np.isfinite(angles)):
        raise ValueError("Ángulos finitos 1D")
    if not angles.size:
        return None, None
    w = np.ones_like(angles) if weights is None else np.asarray(weights, dtype=float)
    if w.shape != angles.shape or np.any(w <= 0) or not np.all(np.isfinite(w)):
        raise ValueError("Pesos positivos por dirección")
    directions = np.sort(np.mod(angles, np.pi))
    gaps = np.diff(np.r_[directions, directions[0] + np.pi])
    span = float(np.pi - np.max(gaps))
    vectors = np.column_stack([np.cos(angles), np.sin(angles)])
    tensor = (vectors.T * w) @ vectors / np.sum(w)
    eigenvalues = np.linalg.eigvalsh(tensor)
    anisotropy = float(max(0, eigenvalues[0]) / eigenvalues[1])
    return math.degrees(span), min(anisotropy, 1)


def siddon_segments(points_xz_m: tuple[tuple[float, float], ...], grid: Grid2D) -> list[tuple[int, float, float]]:
    """(flat cell,length,angle); bordes internos asignados al lado positivo."""
    segments = []
    xedges, zedges = np.asarray(grid.x_edges_m), np.asarray(grid.z_edges_m)
    nz, nx = grid.shape
    if len(points_xz_m) < 2 or not np.all(np.isfinite(points_xz_m)):
        raise ValueError("Polilínea finita con al menos dos vértices")
    for start, end in zip(points_xz_m, points_xz_m[1:], strict=False):
        a, delta = np.array(start), np.array(end) - start
        length = float(np.linalg.norm(delta))
        if length == 0:
            continue
        fractions = [0.0, 1.0]
        for axis, edges in enumerate((xedges, zedges)):
            if delta[axis] != 0:
                fractions.extend(((edges - a[axis]) / delta[axis]).tolist())
        cuts = np.unique(np.clip(np.asarray(fractions), 0, 1))
        for lo, hi in zip(cuts, cuts[1:], strict=False):
            midpoint = a + delta * (lo + hi) / 2
            if not xedges[0] <= midpoint[0] <= xedges[-1] or not zedges[0] <= midpoint[1] <= zedges[-1]:
                continue
            j = min(int(np.searchsorted(xedges, midpoint[0], side="right") - 1), nx - 1)
            i = min(int(np.searchsorted(zedges, midpoint[1], side="right") - 1), nz - 1)
            segments.append((i * nx + j, length * float(hi - lo), math.atan2(delta[1], delta[0]) % math.pi))
    return segments


def ray_coverage(
    rays: tuple[Ray, ...],
    grid: Grid2D,
    *,
    roi_ref: str,
    topography_ref: str,
    ray_model_ref: str,
    resolved_mask: tuple[bool, ...] | None = None,
    resolution_ref: str | None = None,
) -> Coverage:
    size = math.prod(grid.shape)
    if resolved_mask is not None and (len(resolved_mask) != size or not resolution_ref):
        raise ValueError("Resolución requiere máscara por celda y evidencia independiente")
    hits = np.zeros(size, dtype=int)
    lengths = np.zeros(size)
    angles: list[list[float]] = [[] for _ in range(size)]
    weights: list[list[float]] = [[] for _ in range(size)]
    seen: dict[str, Ray] = {}
    for ray in rays:
        if ray.observation_id in seen:
            if ray != seen[ray.observation_id]:
                raise ValueError("Observación duplicada con geometría/peso contradictorio")
            continue
        seen[ray.observation_id] = ray
        crossed: set[int] = set()
        for cell, length, angle in siddon_segments(ray.points_xz_m, grid):
            lengths[cell] += length * ray.weight
            angles[cell].append(angle)
            weights[cell].append(length * ray.weight)
            crossed.add(cell)
        for cell in crossed:
            hits[cell] += 1
    statistics = [angular_metrics(np.array(a), np.array(w)) for a, w in zip(angles, weights, strict=True)]
    return Coverage(
        roi_ref=roi_ref,
        mesh_ref=grid.reference,
        topography_ref=topography_ref,
        ray_model_ref=ray_model_ref,
        hits=tuple(int(h) for h in hits),
        dws_m=tuple(float(length) for length in lengths),
        angular_span_degrees=tuple(pair[0] for pair in statistics),
        anisotropy=tuple(pair[1] for pair in statistics),
        resolved_mask=(False,) * size if resolved_mask is None else resolved_mask,
        limitations=(
            "Hits/ángulos no demuestran resolución ni unicidad",
            "DWS ponderada; IDs únicos de observación",
            "Bordes internos al lado positivo; borde máximo a última celda",
            "RESOLUTION_UNKNOWN" if resolution_ref is None else f"resolution_ref={resolution_ref}",
        ),
    )


def assess_roi(
    coverage: Coverage,
    roi_mask: tuple[bool, ...],
    *,
    resolution_verified: bool,
    pass_fraction: float = 0.9,
    warn_fraction: float = 0.5,
) -> dict[str, object]:
    roi = np.asarray(roi_mask)
    if roi.dtype != np.bool_ or roi.shape != (len(coverage.hits),) or not np.any(roi):
        raise ValueError("ROI booleano no vacío por celda")
    if not 0 <= warn_fraction < pass_fraction <= 1:
        raise ValueError("Fronteras de fracción ROI incoherentes")
    if not resolution_verified or "RESOLUTION_UNKNOWN" in coverage.limitations:
        return {
            "quality_status": None,
            "evidence_status": "INCOMPLETE",
            "reason": "Resolución independiente ausente",
            "eligible_for_acceptance": False,
        }
    fraction = float(np.mean(np.asarray(coverage.resolved_mask)[roi]))
    status = "PASS" if fraction >= pass_fraction else "WARN" if fraction >= warn_fraction else "FAIL"
    return {
        "quality_status": status,
        "evidence_status": "COMPLETE",
        "resolved_roi_fraction": fraction,
        "eligible_for_acceptance": False,
        "reason": "Estado diagnóstico condicionado a resolución y ROI explícitos",
    }


def survey_plan(
    receiver_x_m: FloatArray, source_x_m: FloatArray, *, crossover_m: float, multiplier: float = 1.5
) -> dict[str, object]:
    receivers, sources = np.asarray(receiver_x_m), np.asarray(source_x_m)
    if receivers.ndim != 1 or sources.ndim != 1 or min(receivers.size, sources.size) < 1:
        raise ValueError("Receptores y fuentes físicos 1D no vacíos")
    if not np.all(np.isfinite(receivers)) or not np.all(np.isfinite(sources)) or crossover_m <= 0 or multiplier <= 0:
        raise ValueError("Geometría/heurística positiva finita")
    if not math.isfinite(crossover_m) or not math.isfinite(multiplier) or len(np.unique(sources)) != sources.size:
        raise ValueError("Fuentes únicas y parámetros finitos")
    return {
        "physical_shot_count": int(sources.size),
        "source_x_m": sources.tolist(),
        "required_offset_heuristic_m": crossover_m * multiplier,
        "shots": [
            {
                "source_x_m": float(source),
                "branch_points_nominal": int(np.count_nonzero(abs(receivers - source) >= crossover_m)),
                "left_receiver_count": int(np.count_nonzero(receivers < source)),
                "right_receiver_count": int(np.count_nonzero(receivers > source)),
            }
            for source in sources
        ],
        "eligible_for_acceptance": False,
        "reason": "Heurística no acredita profundidad/ROI; homogeneidad superficial no crea sensibilidad profunda",
    }
