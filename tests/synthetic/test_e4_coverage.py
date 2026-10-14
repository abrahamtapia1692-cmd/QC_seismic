import numpy as np
import pytest
from scipy.stats import spearmanr

from geoqc.trs.contracts import Grid2D, Ray
from geoqc.trs.coverage import angular_metrics, assess_roi, ray_coverage, siddon_segments
from geoqc.trs.inversion import linear_resolution
from tests.synthetic.e4_support import record


def independent_rectangles(points, grid):
    """Slab intersection por celda, independiente de cruces ordenados de Siddon."""
    result = np.zeros(np.prod(grid.shape))
    nz, nx = grid.shape
    for a, b in zip(points, points[1:], strict=False):
        a, b = np.array(a), np.array(b)
        d = b - a
        length = np.linalg.norm(d)
        if length == 0:
            continue
        for i in range(nz):
            for j in range(nx):
                low = np.array([grid.x_edges_m[j], grid.z_edges_m[i]])
                high = np.array([grid.x_edges_m[j + 1], grid.z_edges_m[i + 1]])
                lo, hi = 0.0, 1.0
                valid = True
                for axis in (0, 1):
                    if d[axis] == 0:
                        # Lado positivo para borde interno; máximo a última celda.
                        if not low[axis] <= a[axis] <= high[axis] or (
                            a[axis] == high[axis]
                            and high[axis] != (grid.x_edges_m[-1] if axis == 0 else grid.z_edges_m[-1])
                        ):
                            valid = False
                            break
                    else:
                        entry, exit = sorted([(low[axis] - a[axis]) / d[axis], (high[axis] - a[axis]) / d[axis]])
                        lo, hi = max(lo, entry), min(hi, exit)
                if valid and hi > lo:
                    result[i * nx + j] += (hi - lo) * length
    return result


@pytest.mark.vid("V-E4-18")
def test_siddon_independent_conservation_and_corners(record_property):
    rng = np.random.default_rng(41800)
    grid = Grid2D(x_edges_m=(0, 1, 2, 4), z_edges_m=(0, 1, 3), reference="nonuniform rectangle cells")
    cases = [
        ((0, 0), (4, 3)),
        ((0, 1), (4, 1)),
        ((1, 0), (1, 3)),
        ((-1, 0), (5, 0)),
        ((4, 0), (4, 3)),
        ((0, 0), (1, 1), (2, 0), (4, 3)),
        ((2, 1), (2, 1)),
        ((-1, -1), (-2, -2)),
    ]
    cases += [tuple(map(tuple, rng.uniform([-1, -1], [5, 4], size=(2, 2)))) for _ in range(200)]
    max_error = 0
    for points in cases:
        actual = np.zeros(np.prod(grid.shape))
        for cell, length, _ in siddon_segments(points, grid):
            actual[cell] += length
        reference = independent_rectangles(points, grid)
        np.testing.assert_allclose(actual, reference, rtol=1e-10, atol=1e-12)
        np.testing.assert_array_equal(actual > 0, reference > 0)
        max_error = max(max_error, float(max(abs(actual - reference))))
    record(
        record_property,
        "siddon_validation",
        {"cases": len(cases), "max_cell_length_error_m": max_error, "rtol": 1e-10, "atol_m": 1e-12},
    )


@pytest.mark.vid("V-E4-19")
def test_angular_exact_and_empty():
    span, a = angular_metrics(np.radians([0, 60, 120]))
    assert span == pytest.approx(120) and a == pytest.approx(1)
    assert angular_metrics(np.array([0])) == (0, 0)
    assert angular_metrics(np.array([])) == (None, None)
    uniform = np.arange(200) * np.pi / 200
    assert angular_metrics(uniform)[0] == pytest.approx(180 - 180 / 200)
    assert angular_metrics(uniform)[1] == pytest.approx(1)
    # Repetir una dirección no crea span y la ponderación modifica el tensor.
    assert angular_metrics(np.zeros(200)) == (0, 0)
    assert angular_metrics(np.radians([0, 60, 120]), np.array([100, 1, 1]))[1] < 0.05


@pytest.mark.vid("V-E4-20")
def test_roi_states_mesh_refinement_duplicates_and_surface_depth(record_property):
    grid = Grid2D(x_edges_m=(0, 1, 2, 3, 4), z_edges_m=(0, 1, 2), reference="ROI")
    rays = tuple(Ray(observation_id=str(j), points_xz_m=((0, j / 10), (4, j / 10))) for j in range(10))
    base = ray_coverage(rays, grid, roi_ref="ROI", topography_ref="flat", ray_model_ref="homogeneous straight")
    duplicate = ray_coverage(
        rays + rays, grid, roi_ref="ROI", topography_ref="flat", ray_model_ref="homogeneous straight"
    )
    assert base == duplicate
    assert all(h == 0 for h in base.hits[4:])
    assert assess_roi(base, (True,) * 8, resolution_verified=False)["evidence_status"] == "INCOMPLETE"
    resolution_cases = []
    for number_vertical, status in [(4, "PASS"), (2, "WARN"), (0, "FAIL")]:
        vertical = tuple(
            Ray(observation_id=f"vertical-{j}", points_xz_m=((j + 0.5, 0), (j + 0.5, 1)))
            for j in range(number_vertical)
        )
        arrangement = vertical if vertical else rays
        matrix = np.array([independent_rectangles(ray.points_xz_m, grid)[:4] for ray in arrangement])
        resolution = linear_resolution(matrix, sigma_s=np.full(len(arrangement), 1e-5), damping=0)
        # La máscara procede de sensibilidad y error conocido, no del estado esperado.
        diagonal = np.diag(resolution["resolution_matrix"])
        relative_sigma = np.sqrt(np.diag(resolution["noise_covariance"])) / 0.001
        resolved = tuple(bool(value) for value in ((diagonal > 0.95) & (relative_sigma < 0.05))) + (False,) * 4
        coverage = ray_coverage(
            arrangement,
            grid,
            roi_ref="upper row",
            topography_ref="flat",
            ray_model_ref="homogeneous straight",
            resolved_mask=resolved,
            resolution_ref="independent slab-intersection matrix; known iid 10us noise; fixed straight rays",
        )
        report = assess_roi(coverage, (True,) * 4 + (False,) * 4, resolution_verified=True)
        assert report["quality_status"] == status and report["eligible_for_acceptance"] is False
        resolution_cases.append(
            {
                "vertical_observations": number_vertical,
                "state": status,
                "matrix_m": matrix.tolist(),
                "rank": resolution["rank"],
                "resolution_diagonal": diagonal.tolist(),
                "resolved_mask": resolved,
            }
        )
    off_end = Ray(observation_id="offend", points_xz_m=((-10, 0), (20, 0)))
    surface = ray_coverage(
        (off_end,), grid, roi_ref="deep row", topography_ref="flat", ray_model_ref="surface homogeneous"
    )
    assert surface.hits[4:] == (0,) * 4
    refined = Grid2D(
        x_edges_m=tuple(np.arange(0, 4.01, 0.5)), z_edges_m=tuple(np.arange(0, 2.01, 0.5)), reference="refined"
    )
    finer = ray_coverage(rays, refined, roi_ref="ROI", topography_ref="flat", ray_model_ref="same")
    assert sum(finer.dws_m) == pytest.approx(sum(base.dws_m))
    # Los hits por celda cambian con el tamaño; se conserva la unión física por padre.
    assert finer.hits[0] + finer.hits[8] == base.hits[0]
    assert max(finer.hits) == 5 and max(base.hits) == 10
    record(record_property, "independent_roi_states", resolution_cases)


@pytest.mark.vid("V-E4-21")
def test_coverage_resolution_error_association_with_confounders(record_property):
    rng = np.random.default_rng(42100)
    grid = Grid2D(x_edges_m=(0, 1, 2), z_edges_m=(0, 1), reference="two-cell ROI")
    families = []
    for family in range(3):
        coverage_scores, errors, resolutions, empirical_errors, velocity_errors = [], [], [], [], []
        # 100 realizaciones por familia, geometría base independiente y ruido fijo.
        for trial in range(100):
            n = 4 + 2 * (trial % 20)
            starts = rng.uniform(0.1, 0.9, n)
            ends = rng.uniform(0.1, 0.9, n)
            if family == 1:
                ends = np.clip(starts + rng.normal(0, 0.15, n), 0, 1)
            rays = [((0, float(a)), (2, float(b))) for a, b in zip(starts, ends, strict=True)]
            # Observaciones verticales independientes rompen degeneración izquierda/derecha.
            vertical_count = max(1, n // 4)
            rays += [((float(x), 0), (float(x), 1)) for x in rng.uniform(0, 2, vertical_count)]
            matrix = np.array([independent_rectangles(points, grid) for points in rays])
            sigma = np.full(len(rays), 1e-5)
            system = linear_resolution(matrix, sigma_s=sigma, damping=0)
            slowness = np.array([1 / (1000 + family * 100), 1 / (1100 + family * 100)])
            values = matrix @ slowness + rng.normal(0, sigma)
            operator = np.array(system["operator"])
            estimated = operator @ (values / sigma)
            # Error esperado de ruido, separando variación de realización y sesgo.
            expected_rmse = np.sqrt(np.trace(np.array(system["noise_covariance"])) / 2)
            independent_noise = rng.normal(0, sigma[:, None], (len(rays), 200))
            recovered = operator @ ((matrix @ slowness)[:, None] / sigma[:, None] + independent_noise / sigma[:, None])
            empirical_errors.append(float(np.sqrt(np.mean((recovered - slowness[:, None]) ** 2))))
            velocity_errors.append(float(np.sqrt(np.mean(((1 / recovered) / (1 / slowness[:, None]) - 1) ** 2))))
            coverage_scores.append(len(rays))
            errors.append(expected_rmse)
            resolutions.append(np.diag(system["resolution_matrix"]).tolist())
            assert np.all(np.isfinite(estimated))
        rho = float(spearmanr(coverage_scores, errors).statistic)
        empirical_rho = float(spearmanr(coverage_scores, empirical_errors).statistic)
        boot = []
        for _ in range(300):
            indices = rng.integers(0, 100, 100)
            boot.append(float(spearmanr(np.array(coverage_scores)[indices], np.array(errors)[indices]).statistic))
        ci = np.quantile(boot, [0.025, 0.975]).tolist()
        assert rho <= -0.5
        assert empirical_rho <= -0.5
        families.append(
            {
                "family": family,
                "n": 100,
                "spearman": rho,
                "empirical_spearman": empirical_rho,
                "noise_replicas_per_geometry": 200,
                "velocity_relative_rmse_mean": float(np.mean(velocity_errors)),
                "bootstrap_ci95": ci,
                "resolution_diagonal_min": float(np.min(resolutions)),
                "error_estimand": "expected and measured RMSE from independent noise realizations; fixed straight-ray model",
                "confounders": "fixed ray model, known cells/sigma; variable ray directions and count; no nonlinear uniqueness",
            }
        )
    record(record_property, "roi_association", families)
