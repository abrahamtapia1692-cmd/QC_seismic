import numpy as np
import pytest
from pydantic import ValidationError

from geoqc.masw.diagnostic_quality import UsabilityPolicy, assess_ridges, classify_metrics

POLICY = UsabilityPolicy()


def plane(direction=1):
    x = np.arange(24) * 2.0
    f = np.array([10.0])
    u = np.exp(-2j * np.pi * direction * f[:, None] * x / 200.0)
    return x, f, u


def test_plane_is_extractable_but_does_not_identify_wave_or_accept():
    x, f, u = plane()
    result = assess_ridges(u, f, x, [200.0], [[200.0], [200.0]], POLICY)[0]
    assert result.grade == "UTILIZABLE"
    assert result.coherence == pytest.approx(1)
    assert result.contrast > 0.8
    assert result.competitor_ratio < 0.3
    assert result.mode_identity == "APPARENT" and not result.eligible_for_acceptance
    # La misma fase podría representar ruido coherente: no identifica su origen.
    assert result.source_attribution == "NOT_ESTABLISHED"


def test_competing_signed_waves_cannot_be_declared_unambiguous():
    x, f, u = plane()
    standing = u + u.conj() + 0.01j
    result = assess_ridges(standing, f, x, [200.0], [[200.0]], POLICY)[0]
    assert result.grade == "REVISAR"
    assert "COMPETING_PEAK" in result.reasons


def test_iid_phases_and_zero_controls():
    x, f, u = plane()
    rng = np.random.Generator(np.random.PCG64(20261013))
    accepted = 0
    for _ in range(32):
        noise = np.exp(1j * rng.uniform(-np.pi, np.pi, u.shape))
        result = assess_ridges(noise, f, x, [200.0], [[200.0]], POLICY)[0]
        accepted += result.grade == "UTILIZABLE"
    assert accepted == 0  # Solo esta cohorte fijada, no garantía de falso PASS.
    result = assess_ridges(u * 0, f, x, [200.0], [[200.0]], POLICY)[0]
    assert result.grade == "NO_UTILIZABLE" and result.coherence is None


@pytest.mark.parametrize(
    "key,at,bad",
    [
        ("coherence", 0.60, 0.599),
        ("contrast", 0.25, 0.249),
        ("competitor_ratio", 0.80, 0.801),
        ("sensitivity_rel", 0.05, 0.051),
    ],
)
def test_policy_boundaries_and_unknown(key, at, bad):
    metrics = dict(coherence=1.0, contrast=0.9, competitor_ratio=0.1, sensitivity_rel=0.0)
    assert classify_metrics(metrics | {key: at}, POLICY) == ()
    assert classify_metrics(metrics | {key: bad}, POLICY)
    assert "METRIC_MISSING" in classify_metrics(metrics | {key: None}, POLICY)


def test_invariance_and_q_grid_convergence():
    x, f, u = plane()
    baseline = assess_ridges(u, f, x, [200.0], [[200.0]], POLICY)[0]
    perm = np.arange(24)[::-1]
    changed = assess_ridges(u[:, perm] * 8 * np.exp(0.3j), f, x[perm], [200.0], [[200.0]], POLICY)[0]
    assert changed.coherence == pytest.approx(baseline.coherence)
    assert changed.competitor_ratio == pytest.approx(baseline.competitor_ratio)
    fine = assess_ridges(u, f, x, [200.0], [[200.0]], UsabilityPolicy(q_samples_per_null=48))[0]
    assert fine.grade == baseline.grade
    assert abs(fine.competitor_ratio - baseline.competitor_ratio) < 0.005


def test_irregular_geometry_and_missing_variants_are_not_silent_pass():
    x, f, u = plane()
    x[4] += 0.3
    irregular = assess_ridges(u, f, x, [200.0], [[200.0]], POLICY)[0]
    assert irregular.grade == "NO_EVALUABLE" and "KERNEL_UNSUPPORTED" in irregular.reasons
    x, f, u = plane()
    missing = assess_ridges(u, f, x, [200.0], np.empty((0, 1)), POLICY)[0]
    assert missing.grade == "NO_EVALUABLE"
    assert "VARIANTS_MISSING" in missing.reasons


def test_spectral_gap_and_grid_limits():
    x, f, u = plane()
    u[0, 4] = 0
    gap = assess_ridges(u, f, x, [200.0], [[200.0]], POLICY)[0]
    assert gap.grade != "UTILIZABLE" and "KERNEL_UNSUPPORTED" in gap.reasons
    x, f, u = plane()
    aliased = assess_ridges(u, f, x, [40.0], [[40.0]], POLICY)[0]
    assert "NYQUIST_LIMIT" in aliased.reasons
    zero_q = assess_ridges(u, f, x, [1000.0], [[1000.0]], POLICY)[0]
    assert "DIRECTION_UNRESOLVED" in zero_q.reasons


@pytest.mark.parametrize(
    "kwargs", [{"coherence_min": -1}, {"sensitivity_max_rel": float("nan")}, {"q_samples_per_null": 2}, {"unknown": 3}]
)
def test_invalid_policy_rejected(kwargs):
    with pytest.raises(ValidationError):
        UsabilityPolicy(**kwargs)
