from pathlib import Path

import numpy as np
import pytest

from geoqc.synth.trs import gradient_time, two_layer_times
from geoqc.trs.contracts import Grid2D
from geoqc.trs.coverage import siddon_segments
from geoqc.trs.forward import point_source_forward, solve_eikonal
from geoqc.trs.reference import pygimli_forward
from tests.synthetic.e4_support import record

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.vid("V-E4-13")
def test_smooth_plane_front_order_and_picking_budget(record_property):
    errors = []
    for h in (1, 0.5, 0.25):
        x = np.arange(0, 20 + h / 2, h)
        z = np.arange(0, 20 + h / 2, h)
        velocity = np.broadcast_to((1000 + 50 * x)[None, :], (z.size, x.size))
        times = solve_eikonal(velocity, spacing_m=h, initial_times_s={(i, 0): 0 for i in range(z.size)})
        exact = np.broadcast_to((np.log((1000 + 50 * x) / 1000) / 50)[None, :], times.shape)
        interior = (x >= 5) & (x <= 15)
        errors.append(
            float(
                np.max(
                    abs(
                        times[round(5 / h) : round(15 / h) + 1, interior]
                        - exact[round(5 / h) : round(15 / h) + 1, interior]
                    )
                )
            )
        )
    order = np.log2(np.array(errors[:-1]) / errors[1:])
    assert min(order) >= 0.9
    assert errors[-1] <= 0.00025
    record(
        record_property,
        "smooth_convergence",
        {
            "h_m": [1, 0.5, 0.25],
            "linf_error_s": errors,
            "observed_order": order.tolist(),
            "analytic": "T=log((1000+50x)/1000)/50, planar initial front x=0",
            "interior_xz_m": [5, 15, 5, 15],
            "budget_s": 0.00025,
        },
    )


@pytest.mark.vid("V-E4-13")
def test_point_gradient_independent_pygimli_and_horizon(record_property):
    expected = gradient_time((0, 0), (20, 0), v0=1000, gradient=100)
    fmm_errors, reference_errors, rows = [], [], []
    for h in (0.5, 0.25, 0.125):
        x, z = np.arange(0, 25 + h / 2, h), np.arange(0, 15 + h / 2, h)
        speed = np.broadcast_to((1000 + 100 * z)[:, None], (z.size, x.size))
        times = point_source_forward(speed, spacing_m=h, source_xz_m=(0, 0))
        fmm = times[0, round(20 / h)]
        reference = pygimli_forward(
            {
                "x_edges_m": x.tolist(),
                "z_edges_m": z.tolist(),
                "source_xz_m": [0, 0],
                "receivers_xz_m": [[20, 0]],
                "model": {"kind": "gradient", "v0_ms": 1000, "gradient_s_inv": 100},
                "secondary_nodes": 3,
                "include_ray_paths": h == 0.5,
            },
            python=ROOT / ".venv-gimli/Scripts/python.exe",
            adapter=ROOT / "tools/pygimli_reference.py",
        )
        pgtime = reference["times_s"][0]
        if "rays_xz_m" in reference:
            points = np.asarray(reference["rays_xz_m"][0])
            # El solver puede devolver el camino en cualquiera de los dos sentidos.
            np.testing.assert_allclose(np.sort(points[[0, -1]], axis=0), [[0, 0], [20, 0]], atol=1e-10)
            assert np.max(points[:, 1]) > 3  # trayectoria curvada, distinta de la recta superficial
            path_length = float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())
            intersections = siddon_segments(
                tuple(map(tuple, points)),
                Grid2D(x_edges_m=tuple(x), z_edges_m=tuple(z), reference=f"pygimli-gradient-h{h}"),
            )
            assert sum(segment[1] for segment in intersections) == pytest.approx(path_length, rel=1e-10)
            reference["ray_siddon_length_m"] = sum(segment[1] for segment in intersections)
            reference["ray_polyline_length_m"] = path_length
        fmm_errors.append(float(abs(fmm - expected)))
        reference_errors.append(abs(pgtime - expected))
        rows.append({"h_m": h, "analytic_s": expected, "fmm_s": float(fmm), "pygimli": reference})
    assert fmm_errors[-1] < fmm_errors[0]
    # Refinamiento angular separado: el error firmado puede cancelar el error espacial.
    angular = pygimli_forward(
        {
            "x_edges_m": x.tolist(),
            "z_edges_m": z.tolist(),
            "source_xz_m": [0, 0],
            "receivers_xz_m": [[20, 0]],
            "model": {"kind": "gradient", "v0_ms": 1000, "gradient_s_inv": 100},
            "secondary_nodes": 4,
        },
        python=ROOT / ".venv-gimli/Scripts/python.exe",
        adapter=ROOT / "tools/pygimli_reference.py",
    )
    angular_error = abs(angular["times_s"][0] - expected)
    assert angular_error < reference_errors[-1] and angular_error <= 0.00025
    assert fmm_errors[-1] <= 0.00025 and reference_errors[-1] <= 0.00025
    h = 0.125
    z = np.arange(0, 30 + h / 2, h)
    expanded = point_source_forward(
        np.broadcast_to((1000 + 100 * z)[:, None], (z.size, 201)), spacing_m=h, source_xz_m=(0, 0)
    )
    assert abs(expanded[0, 160] - rows[-1]["fmm_s"]) < 1e-7
    record(
        record_property,
        "independent_forward",
        {
            "mesh_study": rows,
            "fmm_abs_error_s": fmm_errors,
            "reference_abs_error_s": reference_errors,
            "angular_refinement": angular,
            "angular_refined_error_s": angular_error,
            "horizon_expanded_change_s": float(abs(expanded[0, 160] - rows[-1]["fmm_s"])),
            "budget_s": 0.00025,
            "reference_nonmonotonicity": "cell sampling and angular path error can cancel at fixed secNodes",
        },
    )


@pytest.mark.vid("V-E4-13")
def test_subnode_source_boundary_and_interface(record_property):
    errors = []
    for h in (0.25, 0.125, 0.0625):
        coordinates = np.arange(0, 20 + h / 2, h)
        speed = np.full((coordinates.size, coordinates.size), 1000.0)
        times = point_source_forward(speed, spacing_m=h, source_xz_m=(0.13, 2.13))
        exact = np.hypot(20 - 0.13, 8 - 2.13) / 1000
        errors.append(float(abs(times[round(8 / h), round(20 / h)] - exact)))
    assert errors[-1] < errors[0] and errors[-1] <= 0.00025
    h = 0.03125
    x = np.arange(0, 20 + h / 2, h)
    z = np.arange(0, 8 + h / 2, h)
    speed = np.broadcast_to(np.where(z < 5, 300, 1500)[:, None], (z.size, x.size))
    computed = point_source_forward(speed, spacing_m=h, source_xz_m=(0, 0))[0, -1]
    expected = two_layer_times(np.array([20.0]), 300, 1500, 5).first_s[0]
    assert abs(computed - expected) <= 0.00025
    record(
        record_property,
        "subnode_and_interface",
        {
            "subnode_errors_s": errors,
            "subnode_h_m": [0.25, 0.125, 0.0625],
            "interface_h_m": h,
            "interface_time_s": float(computed),
            "interface_analytic_s": expected,
            "interface_abs_error_s": float(abs(computed - expected)),
            "budget_s": 0.00025,
        },
    )
