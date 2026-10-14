import numpy as np
import pytest
from pydantic import ValidationError

from geoqc.core.evidence import canonical_hash
from geoqc.core.models import Shot
from geoqc.trs.branches import fit_branches
from geoqc.trs.contracts import Grid2D, PickCalibration, Ray, TRSProtocol
from geoqc.trs.coverage import ray_coverage
from geoqc.trs.forward import point_source_forward
from geoqc.trs.inversion import normalized_misfit
from geoqc.trs.picking import aic_curve, estimator_hash, pick_trace
from geoqc.trs.reciprocity import reciprocal_pair
from tests.synthetic.e4_support import DT, pick_protocol, realization, trs_shot
from tests.synthetic.test_e4_models import observation


@pytest.mark.vid("V-E4-2")
def test_mask_and_calibration_domain_are_enforced():
    data, _ = realization(np.random.default_rng(40002), 20)
    source = trs_shot(data)
    protocol = pick_protocol(20)
    mask = source.valid_mask.copy()
    mask[0, 300] = False
    excluded = Shot.model_validate(source.model_dump() | {"valid_mask": mask, "mask_reasons": ("missing sample",)})
    assert pick_trace(excluded, 0, protocol).confidence == "MISSING"
    calibration = PickCalibration(
        domain_id=protocol.domain_id,
        protocol_hash=canonical_hash(protocol),
        estimator_hash=estimator_hash(),
        dt_s=DT,
        errors_s=tuple(np.linspace(0, DT, 500)),
        training_ref="test only",
    )
    for field, value in [
        ("domain_id", "other"),
        ("protocol_hash", "b" * 64),
        ("estimator_hash", "c" * 64),
        ("dt_s", DT * 2),
    ]:
        changed = PickCalibration.model_validate(calibration.model_dump() | {field: value})
        assert pick_trace(source, 0, protocol, changed).confidence == "AMBIGUOUS"
    with pytest.raises(ValueError):
        aic_curve(np.zeros(32))
    with pytest.raises(ValidationError):
        TRSProtocol(picking=protocol, horizontal_two_layers_verified=True, provenance="unverified")


@pytest.mark.vid("V-E4-5")
def test_reciprocal_physical_pairs_and_covariance():
    with pytest.raises(ValueError, match="pares"):
        reciprocal_pair(observation("A", "B"), observation("A", "B"), tolerance_s=0.001, detectable_effect_s=0.002)
    with pytest.raises(ValueError, match="Covarianza"):
        reciprocal_pair(
            observation("A", "B"), observation("B", "A"), covariance_s2=1, tolerance_s=0.001, detectable_effect_s=0.002
        )


@pytest.mark.vid("V-E4-9")
def test_heterogeneous_known_sigmas_and_noiseless_bic():
    x = np.arange(1, 41, dtype=float)
    y = 0.01 + x / 1000
    y[-1] += 0.01
    sigmas = np.full(40, 0.0001)
    sigmas[-1] = 1
    fitted = fit_branches(x, y, sigma_s=sigmas, max_segments=1)
    assert fitted["selected"]["parameters"] == 2
    assert fitted["selected"]["velocities_ms"][0] == pytest.approx(1000, rel=1e-5)
    exact = fit_branches(x, 0.01 + x / 1000, max_segments=3)
    assert exact["selected"]["segments"] == 1 and np.isfinite(exact["selected"]["bic"])
    with pytest.raises(ValueError, match="repetidos"):
        fit_branches(np.ones(10), np.ones(10))


@pytest.mark.vid("V-E4-13")
def test_forward_source_outside_domain_is_not_snapped():
    with pytest.raises(ValueError, match="Fuente fuera"):
        point_source_forward(np.ones((3, 3)) * 1000, spacing_m=1, source_xz_m=(-0.1, 0))


@pytest.mark.vid("V-E4-14")
def test_misfit_full_covariance_and_singular_abstention():
    data = np.array([1, 2, 3.0])
    predicted = data + np.array([0.1, -0.1, 0.2])
    covariance = np.array([[1, 0.5, 0], [0.5, 1, 0], [0, 0, 1]]) * 0.01
    reference = (data - predicted) @ np.linalg.inv(covariance) @ (data - predicted) / 3
    assert normalized_misfit(data, predicted, covariance)["Q"] == pytest.approx(reference)
    with pytest.raises(ValueError, match="positiva"):
        normalized_misfit(data, predicted, np.ones((3, 3)))


@pytest.mark.vid("V-E4-18")
def test_ray_ids_and_independent_resolution_evidence():
    grid = Grid2D(x_edges_m=(0, 1), z_edges_m=(0, 1), reference="one cell")
    ray = Ray(observation_id="one", points_xz_m=((0, 0), (1, 1)))
    altered = Ray(observation_id="one", points_xz_m=((0, 1), (1, 0)))
    with pytest.raises(ValueError, match="contradictorio"):
        ray_coverage((ray, altered), grid, roi_ref="ROI", topography_ref="flat", ray_model_ref="fixed")
    with pytest.raises(ValueError, match="independiente"):
        ray_coverage((ray,), grid, roi_ref="ROI", topography_ref="flat", ray_model_ref="fixed", resolved_mask=(True,))
