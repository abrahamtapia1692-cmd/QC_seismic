import numpy as np
import pytest
from scipy.stats import spearmanr

from geoqc.masw.engineering import ensemble_reference, parameter_resolution, sensitivity, vs30
from geoqc.synth.dispersion import LayeredModel, phase_disba, phase_fem
from tests.synthetic.e5_support import FAMILIES, wilson


@pytest.fixture(scope="module")
def ensemble():
    f = np.array([8.0, 16.0, 32.0])
    models = []
    for family in FAMILIES:
        for scale in (0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3):
            for thickness_scale in (0.5, 1.0, 1.5):
                models.append(
                    LayeredModel(
                        layers=tuple(
                            (h * thickness_scale, vp * scale, vs * scale, rho) for h, vp, vs, rho in family.layers
                        )
                    )
                )
    curves = np.array([phase_disba(model, f).velocities_ms for model in models])
    targets = np.array([vs30(model) for model in models])
    independent = np.array([phase_fem(model, f, points_per_decay=40).velocities_ms for model in FAMILIES])
    return f, models, curves, targets, independent


@pytest.mark.vid("V-E5-14")
def test_sensitivity_convergence_vertical_partition_resolution_and_alternatives(record_property):
    model = FAMILIES[0]
    f = np.array([8.0, 16.0, 32.0])
    kernels = [sensitivity(model, f, relative_step=step) for step in (0.01, 0.005, 0.0025)]
    assert np.max(abs(kernels[-1] - kernels[-2])) < 0.01
    # Divide capa idéntica en dos: suma de derivadas sobre subcapas conserva perturbación común.
    split = LayeredModel(layers=((2.5, 400, 180, 1800), (2.5, 400, 180, 1800), (0, 900, 450, 2000)))
    detailed = sensitivity(split, f, relative_step=0.0025)
    np.testing.assert_allclose(detailed[:, :2].sum(axis=1), kernels[-1][:, 0], atol=0.01)
    resolution = parameter_resolution(kernels[-1], np.eye(3) * 0.01**2, damping=10)
    assert not np.allclose(resolution["resolution"], np.eye(2))
    depth_study = []
    for dz in (5.0, 2.5):
        edges = np.arange(0, 60 + dz / 2, dz)
        blocks = []
        for z in edges[:-1]:
            blocks.append((dz, 400.0, 180.0, 1800.0) if z < 5 else (dz, 900.0, 450.0, 2000.0))
        blocks.append((0.0, 900.0, 450.0, 2000.0))
        vertical = sensitivity(LayeredModel(layers=tuple(blocks)), f, relative_step=0.005)
        masses = abs(vertical)
        normalizer = masses.sum(axis=1)
        roi_fraction = masses[:, : int(30 / dz)].sum(axis=1) / normalizer
        density = masses[:, :-1] / (normalizer[:, None] * dz)
        assert np.allclose(density.sum(axis=1) * dz + masses[:, -1] / normalizer, 1)
        depth_study.append(
            {
                "dz_m": dz,
                "edges_m": edges.tolist(),
                "normalized_density_per_m": density.tolist(),
                "outside60m_mass": (masses[:, -1] / normalizer).tolist(),
                "roi30m_fraction": roi_fraction.tolist(),
                "hypothesis90pct": (roi_fraction >= 0.9).tolist(),
            }
        )
    assert np.max(abs(np.array(depth_study[0]["roi30m_fraction"]) - depth_study[1]["roi30m_fraction"])) < 0.02
    # Alta frecuencia puede ocultar el semiespacio: curvas casi iguales y Vs30 distinto.
    alternatives = [
        LayeredModel(layers=((20, 400, 180, 1800), (0, 900, 450, 2000))),
        LayeredModel(layers=((20, 400, 180, 1800), (0, 2000, 1000, 2100))),
    ]
    high = np.array([phase_disba(m, [64, 96, 128]).velocities_ms for m in alternatives])
    assert np.max(abs(high[1] - high[0]) / high[0]) < 0.005
    targets = [vs30(m) for m in alternatives]
    assert abs(targets[1] - targets[0]) / targets[0] > 0.08
    # Alcance nominal no sustituye Jacobiano/información de objetivos.
    nominal = [(200 / 8) / k for k in (2, 2.5, 3, 3.5)]
    record_property(
        "sensitivity_resolution",
        {
            "steps": [0.01, 0.005, 0.0025],
            "logc_logvs_kernel": kernels[-1].tolist(),
            "split_kernel": detailed.tolist(),
            "resolution": resolution,
            "measure": "parameter log-Vs per layer; summed sublayer derivatives",
            "normalized_abs_sensitivity": (abs(kernels[-1]) / np.sum(abs(kernels[-1]), axis=1, keepdims=True)).tolist(),
            "alternative_vs30_ms": targets,
            "high_band_relative_difference": float(np.max(abs(high[1] - high[0]) / high[0])),
            "nominal_depth_kappa2to3_5": nominal,
            "nominal_depth_is_resolution": False,
            "depth_quadrature_study": depth_study,
        },
    )


@pytest.mark.vid("V-E5-16")
def test_vs30_independent_fem_ensembles_error_ci_and_qc_association(ensemble, record_property):
    f, models, curves, targets, independent = ensemble
    rng = np.random.default_rng(716)
    rows = []
    good_errors = []
    for i, family in enumerate(FAMILIES):
        truth = vs30(family)
        errors, quality, cover = [], [], []
        for trial in range(100):
            noise_fraction = (0.005, 0.01, 0.02, 0.04, 0.08)[trial % 5]
            sigma = independent[i] * noise_fraction
            data = independent[i] + rng.normal(0, sigma)
            result = ensemble_reference(data, sigma, curves, targets)
            error = (result["mean_vs30_ms"] - truth) / truth
            errors.append(error)
            quality.append(1 / noise_fraction)
            cover.append(result["interval95_ms"][0] <= truth <= result["interval95_ms"][1])
            if noise_fraction <= 0.01:
                good_errors.append(abs(error))
        rho = float(spearmanr(quality, abs(np.array(errors))).statistic)
        rows.append(
            {
                "family": i,
                "truth_vs30_ms": truth,
                "errors_relative": errors,
                "quality_score": quality,
                "rho_quality_abs_error": rho,
                "bias_relative": float(np.mean(errors)),
                "within15pct": int(np.sum(abs(np.array(errors)) <= 0.15)),
                "within15pct_wilson": wilson(int(np.sum(abs(np.array(errors)) <= 0.15)), 100),
                "interval_coverage": float(np.mean(cover)),
                "reference": "independent vertical FEM40, disba candidate curves",
            }
        )
    assert np.quantile(good_errors, 0.95) < 0.15
    combined = spearmanr(
        np.concatenate([r["quality_score"] for r in rows]), np.abs(np.concatenate([r["errors_relative"] for r in rows]))
    )
    assert combined.statistic < -0.2
    # Bootstrap por estrato preserva origen de las familias y sentido del score.
    boot = []
    for _ in range(500):
        picks = [rng.integers(0, 100, 100) for _ in rows]
        score = np.concatenate([np.array(row["quality_score"])[idx] for row, idx in zip(rows, picks, strict=True)])
        error = np.concatenate(
            [abs(np.array(row["errors_relative"]))[idx] for row, idx in zip(rows, picks, strict=True)]
        )
        boot.append(float(spearmanr(score, error).statistic))
    record_property(
        "vs30_ensemble_validation",
        {
            "study": rows,
            "models": len(models),
            "frequencies_hz": f.tolist(),
            "good_precision_n": len(good_errors),
            "good_precision_error_p95": float(np.quantile(good_errors, 0.95)),
            "overall_rho": float(combined.statistic),
            "rho_bootstrap95": np.quantile(boot, [0.025, 0.975]).tolist(),
            "scope": "discrete declared families/prior; not field Vs30 profile validation",
            "eligible_for_field_acceptance": False,
        },
    )


@pytest.mark.vid("V-E5-16")
def test_vs30_exact_clipping_no_unobserved_extrapolation():
    model = LayeredModel(layers=((10, 400, 200, 1800), (25, 800, 400, 2000), (0, 1600, 800, 2200)))
    assert vs30(model) == pytest.approx(30 / (10 / 200 + 20 / 400))
    with pytest.raises(ValueError, match="no extrapolar"):
        vs30(model, finite_depth_m=20)
