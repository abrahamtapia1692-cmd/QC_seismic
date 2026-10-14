import numpy as np
import pytest
from scipy.special import i0e

from geoqc.core.physics import rayleigh_halfspace_velocity
from geoqc.masw.curves import near_ratios
from geoqc.synth.nearfield import lamb_surface, surface_admittance


def apparent(spectrum, f, x):
    return np.array(
        [
            -2 * np.pi * frequency / np.polyfit(x, np.unwrap(np.angle(row)), 1)[0]
            for row, frequency in zip(spectrum, f, strict=True)
        ]
    )


@pytest.mark.vid("V-E3-8")
def test_full_lamb_green_integration_tail_reference_far_limit_and_static(record_property):
    f, x = np.array([8.0, 16.0, 32.0]), 60 + np.arange(24) * 2
    meshes = []
    waves = []
    for dk in (0.002, 0.001, 0.0005):
        wave = lamb_surface(f, x, vp_ms=400, vs_ms=200, dk_m_inv=dk, kmax_m_inv=12)
        waves.append(wave["spectrum"])
        meshes.append(apparent(wave["spectrum"], f, x))
    adaptive = lamb_surface(f, x, vp_ms=400, vs_ms=200, adaptive=True, kmax_m_inv=12)
    ref = apparent(adaptive["spectrum"], f, x)
    errors = [np.max(abs(values - ref) / ref) for values in meshes]
    assert errors[-1] < 0.002 and errors[-1] < errors[0]
    assert np.linalg.norm(waves[-1] - adaptive["spectrum"]) / np.linalg.norm(adaptive["spectrum"]) < 0.002
    expanded = lamb_surface(f, x, vp_ms=400, vs_ms=200, dk_m_inv=0.0005, kmax_m_inv=16)
    tail = np.max(abs(apparent(expanded["spectrum"], f, x) - meshes[-1]) / ref)
    assert tail < 0.0002
    cR = rayleigh_halfspace_velocity(200, 1 / 3)
    far = lamb_surface(f, 120 + np.arange(24) * 2, vp_ms=400, vs_ms=200, dk_m_inv=0.0005)["spectrum"]
    farc = apparent(far, f, 120 + np.arange(24) * 2)
    assert np.max(abs(farc - cR) / cR) < 0.01
    # Límite estático independiente Boussinesq con carga gaussiana finita.
    radius = 0.5
    static_r = np.array([1.0, 2.0, 4.0])
    static = lamb_surface([0.01], static_r, vp_ms=400, vs_ms=200, adaptive=True, kmax_m_inv=16)["spectrum"][0]
    # z positivo hacia abajo: presión normal positiva produce desplazamiento positivo.
    expected = (
        (1 - 1 / 3) / (2 * np.pi * 1800 * 200**2) * np.sqrt(np.pi / 2) / radius * i0e(static_r**2 / (4 * radius**2))
    )
    assert np.max(abs(static - expected) / abs(expected)) < 0.002
    # Las tracciones deducidas de los potenciales satisfacen libre tangencial y normal impuesto.
    k, omega = 0.5, 2 * np.pi * 16 * (1 - 0.02j)
    p, q = np.sqrt(k * k - (omega / 400) ** 2), np.sqrt(k * k - (omega / 200) ** 2)
    denominator = (2 * k * k - (omega / 200) ** 2) ** 2 - 4 * k * k * p * q
    A = -(2 * k * k - (omega / 200) ** 2) / (1800 * 200**2 * denominator)
    B = 2j * k * p * A / (2 * k * k - (omega / 200) ** 2)
    shear = 1800 * 200**2 * (-2j * k * p * A + (q * q + k * k) * B)
    normal = 1800 * 200**2 * ((2 * k * k - (omega / 200) ** 2) * A + 2j * k * q * B)
    assert abs(shear) < 1e-12 and normal == pytest.approx(-1, abs=1e-12)
    assert -p * A - 1j * k * B == pytest.approx(surface_admittance(k, omega, vp_ms=400, vs_ms=200, rho_kg_m3=1800))
    record_property(
        "full_green_convergence",
        {
            "dk_m_inv": [0.002, 0.001, 0.0005],
            "velocity_ms": [v.tolist() for v in meshes],
            "adaptive_reference_ms": ref.tolist(),
            "velocity_relative_errors": [float(e) for e in errors],
            "adaptive_absolute_integration_error": adaptive["integration_error"],
            "kmax_expanded_change": float(tail),
            "far_velocity_ms": farc.tolist(),
            "far_analytic_ms": cR,
            "static_relative_error": float(np.max(abs(static - expected) / abs(expected))),
            "source": "Gaussian surface normal traction radius0.5m",
            "body_waves": "P/S branch points included",
            "surface_boundary": "sigma_xz=0,sigma_zz=-load",
            "domain": "homogeneous axisymmetric halfspace, Z",
        },
    )


@pytest.mark.vid("V-E5-10")
def test_near_bias_both_ratios_model_source_holdout_and_unknown_layered(record_property):
    f = np.array([8.0, 16.0, 32.0])
    rows = []
    for vp, vs, radius, role in ((400, 200, 0.5, "CALIBRATION"), (540, 260, 0.8, "HOLDOUT")):
        nu = (vp * vp - 2 * vs * vs) / (2 * (vp * vp - vs * vs))
        truth = rayleigh_halfspace_velocity(vs, nu)
        for x1 in (0.5, 2, 6, 20, 60):
            x = x1 + np.arange(24) * 2
            wave = lamb_surface(f, x, vp_ms=vp, vs_ms=vs, source_radius_m=radius, dk_m_inv=0.0005)
            measured = apparent(wave["spectrum"], f, x)
            bias = (measured - truth) / truth
            ratios = near_ratios(x, truth / f)
            rows.append(
                {
                    "role": role,
                    "vp": vp,
                    "vs": vs,
                    "source_radius_m": radius,
                    "x1_m": x1,
                    "near_ratio": ratios["near_offset_ratio"],
                    "NACD_center": ratios["NACD_center"],
                    "delta_c_over_c": bias.tolist(),
                    "target5pct": (abs(bias) <= 0.05).tolist(),
                    "target2pct": (abs(bias) <= 0.02).tolist(),
                }
            )
        # Objetivo lejano medido en modelos/fuentes distintos; no presume límite universal por ratio.
        assert np.max(abs(bias)) < 0.02
    close = np.array(rows[0]["delta_c_over_c"])
    assert np.max(abs(close)) > 0.002  # sesgo físico mayor que presupuesto numérico E3-8
    record_property(
        "nearfield_bias",
        {
            "study": rows,
            "layered_validity": "UNCALIBRATED",
            "unknown_reason": "homogeneous Green does not validate stratified body/surface interference",
            "thresholds_promoted_to_field": False,
        },
    )
