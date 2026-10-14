"""Experimentos de auditoría del SDD v1.3; no implementan el producto.

Ejecutar desde la raíz: python docs/audit_plan_numerics.py
Escribe evidence/audit_plan_v1_3_replay.json; conserva la auditoría histórica.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import scipy
from scipy.integrate import quad
from scipy.optimize import brentq
from scipy.special import j0, j1


ROOT = Path(__file__).resolve().parents[1]
SEED = 20261003


def kluyver_tail(n: int, a: float, t_max: float = 40.0) -> tuple[float, float]:
    r = n * a
    vals = [quad(lambda t: r * j1(r * t) * j0(t) ** n,
                 lo, lo + 0.25, epsabs=1e-13, epsrel=1e-11)
            for lo in np.arange(0.0, t_max, 0.25)]
    return 1.0 - math.fsum(v for v, _ in vals), math.fsum(e for _, e in vals)


def main() -> None:
    out: dict = {
        "id": "AUDIT-SDD-1.3", "status": "FINDINGS_CONFIRMED",
        "audit_date_local": "2026-10-03", "timezone": "America/Mexico_City",
        "seed": SEED,
        "versions": {"python": platform.python_version(), "numpy": np.__version__,
                     "scipy": scipy.__version__},
        "sdd_sha256": hashlib.sha256((ROOT / "SDD_QC_Geofisico_MASW_TRS.md").read_bytes()).hexdigest(),
        "scope": "Experimentos analíticos/numéricos; no cierre de gates ni validación con datos reales",
    }
    spec = importlib.util.spec_from_file_location("audit_existing_physics", ROOT / "physics.py")
    physics = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(physics)
    rayleigh = {}
    for nu in (0.0, 0.25, 0.3, 0.4, 0.45, 0.5):
        k2 = (1 - 2 * nu) / (2 * (1 - nu))
        roots = np.roots([1, -8, 8 * (3 - 2 * k2), -16 * (1 - k2)])
        xi = [float(z.real) for z in roots if abs(z.imag) < 1e-10 and 0 < z.real < 1][0]
        rayleigh[str(nu)] = {"ratio_polynomial_roots": math.sqrt(xi),
                             "ratio_existing_solver": physics.rayleigh_ratio(nu),
                             "absolute_difference": abs(math.sqrt(xi) - physics.rayleigh_ratio(nu))}
    out["rayleigh"] = rayleigh
    c = 180 * rayleigh["0.4"]["ratio_polynomial_roots"]
    out["nominal_geophone_depth_m"] = {"fn_4_5": c / (4.5 * 2.5), "fn_2": c / (2 * 2.5)}
    out["geophone_response"] = {
        str(f): f ** 2 / math.sqrt((4.5 ** 2 - f ** 2) ** 2 + (2 * .7 * 4.5 * f) ** 2)
        for f in (4.5, 3., 2., 1.5)
    }
    out["nacd_definition_counterexample"] = {
        "N": 24, "dx_m": 2, "x1_m": 6, "wavelength_m": 48,
        "x1_over_lambda": 6 / 48, "mean_offset_over_lambda": (6 + 23) / 48,
        "warning": "Corregir la definición no valida automáticamente un umbral de aceptación",
    }

    n, dx = 24, 2.0
    def kernel(q: float) -> float:
        return abs(np.sin(n * np.pi * dx * q) / (n * np.sin(np.pi * dx * q))) if q else 1.
    qa = brentq(lambda q: kernel(q) - .5, 1e-12, 1 / (n * dx) - 1e-12)
    qp = brentq(lambda q: kernel(q) - math.sqrt(.5), 1e-12, 1 / (n * dx) - 1e-12)
    out["dirichlet_width"] = {
        "amplitude_fwhm_times_Ndx": 2 * qa * n * dx,
        "power_fwhm_times_Ndx": 2 * qp * n * dx,
        "widths_in_velocity": [
            {"lambda_over_Ndx": ratio,
             "exact_amplitude_fwhm_over_c": 2 * qa * ratio * n * dx / (1 - (qa * ratio * n * dx) ** 2),
             "exact_power_fwhm_over_c": 2 * qp * ratio * n * dx / (1 - (qp * ratio * n * dx) ** 2),
             "sdd_approximation": .886 * ratio}
            for ratio in (.25, .5, 1.)],
        "sdd_sigma_floor_over_c_for_lambda75_L96": .886 * (75 / 96) / math.sqrt(8 * math.log(2)),
    }
    time = np.arange(1000) / 1000
    wave1 = np.cos(2 * np.pi * 20 * time)
    wave2 = np.cos(2 * np.pi * 20 * time - 2 * np.pi / 3)
    out["clean_wave_raw_neighbor_correlation"] = float(np.corrcoef(wave1, wave2)[0, 1])
    clean_sine = np.sin(2 * np.pi * 5 * time)
    out["clean_sine_false_clipping_fraction_with_estimated_FS"] = float(np.mean(abs(clean_sine) >= .98 * max(abs(clean_sine))))
    offsets = np.arange(n) * dx
    f, velocity = 5., 100.
    spectrum = np.exp(-2j * np.pi * f * offsets / velocity)
    out["reflection_invariance"] = {
        "original_I": float(abs(np.mean(np.exp(2j * np.pi * f * offsets / velocity) * spectrum))),
        "permutation_I": float(abs(np.mean(np.exp(2j * np.pi * f * offsets[::-1] / velocity) * spectrum[::-1]))),
        "reverse_channels_and_negate_x_I": float(abs(np.mean(np.exp(-2j * np.pi * f * offsets[::-1] / velocity) * spectrum[::-1]))),
    }
    out["reciprocity_geometry_counterexample"] = {
        "position_error_m": .5, "velocity_ms": 1500,
        "travel_time_difference_ms": .5 / 1500 * 1000,
        "absolute_tolerance_ms": 1., "sdd_criterion_result": "PASS",
    }
    v1, v2, v3, h1, h2 = 300., 600., 1500., 5., .5
    intercept2 = 2 * h1 * math.sqrt(1 / v1 ** 2 - 1 / v2 ** 2)
    intercept3 = 2 * (h1 * math.sqrt(1 / v1 ** 2 - 1 / v3 ** 2)
                      + h2 * math.sqrt(1 / v2 ** 2 - 1 / v3 ** 2))
    x = np.linspace(0, 200, 20001)
    times3 = np.minimum.reduce([x / v1, x / v2 + intercept2, x / v3 + intercept3])
    equivalent_h = intercept3 / (2 * math.sqrt(1 / v1 ** 2 - 1 / v3 ** 2))
    times2 = np.minimum(x / v1, x / v3 + intercept3)
    out["hidden_layer_nonidentifiability"] = {
        "three_layer_velocities_ms": [v1, v2, v3], "thicknesses_m": [h1, h2],
        "equivalent_two_layer_thickness_m": equivalent_h,
        "intermediate_branch_ever_first": bool(np.any((x / v2 + intercept2) < np.minimum(x / v1, x / v3 + intercept3))),
        "max_time_difference_between_models_s": float(max(abs(times3 - times2))),
        "domain_m": [0, 200],
    }
    out["vs30_acquisition_record_duration"] = {
        "max_offset_m": 134., "c_min_ms": 80., "wavelet_duration_s": .3,
        "required_post_trigger_s_with_zero_margin": 134 / 80 + .3,
        "available_post_trigger_s_if_total_2s_includes_0_1s_pretrigger": 1.9,
    }
    out["false_pass_binomial_bound"] = {
        "bad_independent_sites": 10, "false_pass_observed": 0,
        "one_sided_95_percent_upper_bound": 1 - .05 ** (1 / 10),
        "bad_independent_cases_needed_for_zero_errors_upper_bound_le_0_05": math.ceil(math.log(.05) / math.log(.95)),
    }
    out["kluyver_quantiles"] = []
    for channels in (12, 24, 48):
        quantile = brentq(lambda a: kluyver_tail(channels, a)[0] - .0005, .1, .95, xtol=1e-10)
        tail20, _ = kluyver_tail(channels, quantile, 20)
        tail40, err = kluyver_tail(channels, quantile, 40)
        out["kluyver_quantiles"].append({"N": channels, "quantile_tail_0_0005": quantile,
                                         "tail_t20": tail20, "tail_t40": tail40,
                                         "absolute_truncation_comparison": abs(tail20 - tail40),
                                         "sum_quad_error_estimates": err})
    # La afirmación de dominancia global falla ya en una cola de probabilidad 0.3.
    channels, asymptotic_tail = 12, .3
    a = math.sqrt(-math.log(asymptotic_tail) / channels)
    tail, err = kluyver_tail(channels, a)
    rng = np.random.Generator(np.random.PCG64(SEED))
    total, exceed = 2_000_000, 0
    for _ in range(total // 20_000):
        phases = rng.uniform(0, 2 * np.pi, (20_000, channels))
        lengths = np.hypot(np.cos(phases).sum(axis=1), np.sin(phases).sum(axis=1)) / channels
        exceed += int(np.sum(lengths > a))
    emp = exceed / total
    out["rayleigh_tail_not_always_conservative"] = {
        "N": channels, "threshold_a": a, "rayleigh_tail": asymptotic_tail,
        "kluyver_tail": tail, "quad_error_estimate": err,
        "monte_carlo_tail": emp, "monte_carlo_samples": total,
        "monte_carlo_standard_error": math.sqrt(emp * (1 - emp) / total),
    }
    out["stack_recommendation_example"] = {"current_stacks": 4, "current_snr_db": 6,
                                            "target_snr_db": 12,
                                            "required_stacks_independent_noise": math.ceil(4 * 10 ** ((12 - 6) / 10))}
    out["gate_omissions"] = {"G4": ["V-E4-18", "V-E4-19", "V-E4-20", "V-E4-21"],
                              "G5": ["V-E5-17", "V-E5-17b", "V-E5-18", "V-E5-19", "V-E5-20"],
                              "G6": ["V-E6-4", "V-E6-5"], "G8": ["V-E8-3"]}
    out["original_pytest_collection"] = {"command": "python -m pytest -q -p no:cacheprovider test_rayleigh_halfspace.py",
                                         "exit_code": 1, "error": "ModuleNotFoundError: No module named 'geoqc'",
                                         "note": "Observado durante la auditoría; el script no vuelve a ejecutar pytest"}
    # Reconstrucción temporal del empaquetado descrito, sin modificar los originales.
    with tempfile.TemporaryDirectory(prefix="geoqc_audit_") as temporary:
        stage = Path(temporary)
        for package in ("geoqc", "geoqc/core", "geoqc/synth"):
            target_package = stage / package
            target_package.mkdir(parents=True, exist_ok=True)
            (target_package / "__init__.py").write_text("", encoding="utf-8")
        for source, destination in (("physics.py", "geoqc/core/physics.py"),
                                    ("evidence.py", "geoqc/core/evidence.py"),
                                    ("modal.py", "geoqc/synth/modal.py"),
                                    ("test_rayleigh_halfspace.py", "test_rayleigh_halfspace.py")):
            shutil.copyfile(ROOT / source, stage / destination)
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(stage)
        completed = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                    "-o", "markers=req(id): requisito SDD", "test_rayleigh_halfspace.py"],
                                   cwd=stage, env=environment, capture_output=True, text=True, timeout=60)
        out["supplied_tests_in_temporary_package"] = {
            "exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr,
            "note": "Copias sin cambios; se añadieron solamente directorios y __init__.py temporales. No cierra G0 ni G3."}
    out["input_sha256"] = {name: hashlib.sha256((ROOT / ("docs/archive/pyproject_v0_0_1.toml" if name == "pyproject.toml" else name)).read_bytes()).hexdigest()
                           for name in ("physics.py", "modal.py", "evidence.py", "test_rayleigh_halfspace.py", "pyproject.toml")}
    out["audit_script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    directory = ROOT / "evidence"
    directory.mkdir(exist_ok=True)
    target = directory / "audit_plan_v1_3_replay.json"
    target.write_text(json.dumps(out, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
