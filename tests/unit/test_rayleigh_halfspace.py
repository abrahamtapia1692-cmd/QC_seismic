"""V-E3-4 — Rayleigh en semiespacio homogéneo (SDD v1.3, E3.3).

Origen de cada constante (ver SDD: "ninguna constante citada de tabla sin derivación"):
  LITERATURE  : valores clásicos independientes del código (forma cerrada o valor conocido).
  REGRESSION  : valores autogenerados por este solver; sirven para detectar regresiones,
                NO como verdad independiente.
"""

import math

import numpy as np
import pytest

from geoqc.core.physics import (
    kappa2_from_nu,
    rayleigh_cubic,
    rayleigh_radical_residual,
    rayleigh_ratio,
    rayleigh_xi,
)
from geoqc.synth.modal import rayleigh_halfspace_factory, rayleigh_halfspace_velocity

pytestmark = pytest.mark.vid("V-E3-4")

NUS = np.linspace(0.0, 0.5, 501)

LITERATURE = {0.0: 0.8740, 0.25: 0.9194, 0.5: 0.9553}  # tol 1e-4
REGRESSION = {0.30: 0.927413, 0.35: 0.935013, 0.40: 0.942195, 0.45: 0.948960}  # tol 1e-5


def viktorov(nu: float) -> float:
    return (0.862 + 1.14 * nu) / (1.0 + nu)


# ---------------------------------------------------------------- valores de referencia
def test_closed_form_nu_025_exact():
    """ν=0.25 ⇒ κ²=1/3 ⇒ ξ = 2 − 2/√3 (raíces de la cúbica: 2∓2/√3 y 4)."""
    xi_exact = 2.0 - 2.0 / math.sqrt(3.0)
    assert rayleigh_cubic(xi_exact, 1.0 / 3.0) == pytest.approx(0.0, abs=1e-13)
    assert rayleigh_xi(0.25) == pytest.approx(xi_exact, abs=1e-13)
    assert rayleigh_ratio(0.25) == pytest.approx(math.sqrt(xi_exact), abs=1e-13)


@pytest.mark.parametrize("nu,expected", LITERATURE.items())
def test_literature_values(nu, expected):
    assert rayleigh_ratio(nu) == pytest.approx(expected, abs=1e-4)


@pytest.mark.parametrize("nu,expected", REGRESSION.items())
def test_regression_values(nu, expected):
    assert rayleigh_ratio(nu) == pytest.approx(expected, abs=1e-5)


def test_errata_values_are_rejected():
    """Los dos valores erróneos que circularon para ν=0.45 NO deben coincidir con el solver."""
    r = rayleigh_ratio(0.45)
    assert abs(r - 0.9674) > 1e-2  # v1.0 (inadmisible: > cota física 0.95531)
    assert abs(r - 0.9503) > 5e-4  # valor "de tabla" de la revisión 1 (no existe)


# ---------------------------------------------------------------- estructura de la cúbica
def test_bracket_is_guaranteed_P0_negative_P1_equals_one():
    for nu in NUS[::25]:
        k2 = kappa2_from_nu(nu)
        assert rayleigh_cubic(0.0, k2) == pytest.approx(-16.0 * (1.0 - k2), abs=1e-13)
        assert rayleigh_cubic(0.0, k2) < 0.0
        assert rayleigh_cubic(1.0, k2) == pytest.approx(1.0, abs=1e-12)


def test_exactly_one_root_in_unit_interval():
    for nu in NUS[::10]:
        k2 = kappa2_from_nu(nu)
        roots = np.roots([1.0, -8.0, 8.0 * (3.0 - 2.0 * k2), -16.0 * (1.0 - k2)])
        real = roots[np.abs(roots.imag) < 1e-9].real
        inside = real[(real > 0.0) & (real < 1.0)]
        assert inside.size == 1
        assert inside[0] == pytest.approx(rayleigh_xi(nu), abs=1e-9)


def test_independent_radical_form_residual():
    """Verificación independiente: el mismo ξ satisface la forma con radicales."""
    for nu in NUS[::10]:
        xi, k2 = rayleigh_xi(nu), kappa2_from_nu(nu)
        assert abs(rayleigh_radical_residual(xi, k2)) < 1e-10


def test_trivial_root_of_radical_form_is_not_returned():
    """Regresión: la forma con radicales tiene la raíz espuria ξ=0; el solver nunca la devuelve."""
    for nu in NUS[::10]:
        k2 = kappa2_from_nu(nu)
        assert rayleigh_radical_residual(0.0, k2) == pytest.approx(0.0, abs=1e-13)  # existe...
        assert rayleigh_xi(nu) > 0.7  # ...y no se elige


# ---------------------------------------------------------------- propiedades físicas
def test_strictly_increasing_in_nu():
    r = np.array([rayleigh_ratio(nu) for nu in NUS])
    assert np.all(np.diff(r) > 0.0)


def test_physical_bounds():
    r = np.array([rayleigh_ratio(nu) for nu in NUS])
    assert np.all((r > 0.86) & (r < 0.96))
    assert rayleigh_ratio(0.5) < 1.0
    assert rayleigh_ratio(0.5) == pytest.approx(0.95531, abs=1e-4)  # cota superior admisible
    assert rayleigh_ratio(0.45) < rayleigh_ratio(0.5)


def test_viktorov_agreement():
    """Viktorov es una aproximación con dominio acotado: ≤2e-3 solo para ν≥0.25 (medido:
    desde ν≈0.237); en ν=0 el error es 0.012 (errata SDD v1.3: v1.2 afirmaba ≤2e-3 en [0,0.5])."""
    for nu in NUS:
        d = abs(rayleigh_ratio(nu) - viktorov(nu))
        assert d < 1.3e-2
        if nu >= 0.25:
            assert d < 2e-3


def test_continuity_at_nu_half():
    r_half = rayleigh_ratio(0.5)
    prev = None
    for eps in np.logspace(-2, -10, 9):
        d = abs(rayleigh_ratio(0.5 - eps) - r_half)
        assert d <= 0.3 * eps + 1e-12  # pendiente dr/dν ≈ 0.13 ⇒ sin salto
        if prev is not None:
            assert d <= prev + 1e-13  # converge monótonamente
        prev = d


@pytest.mark.parametrize("k", [0.5, 2.0, 7.3])
def test_linear_scaling_in_vs(k):
    assert rayleigh_halfspace_velocity(k * 200.0, 0.3) == pytest.approx(
        k * rayleigh_halfspace_velocity(200.0, 0.3), rel=1e-12
    )


def test_solver_tolerance_is_respected():
    assert rayleigh_xi(0.3, tol=1e-6) == pytest.approx(rayleigh_xi(0.3, tol=1e-14), abs=2e-6)


@pytest.mark.parametrize("tol", [0.0, -1.0, 1.0, float("nan"), float("inf"), True])
def test_invalid_tolerance_raises(tol):
    with pytest.raises(ValueError):
        rayleigh_xi(0.3, tol=tol)


# ---------------------------------------------------------------- validación de entradas y fábrica
@pytest.mark.parametrize("nu", [0.5 + 1e-9, 0.7, -1.0, -2.0, float("nan"), float("inf")])
def test_invalid_nu_raises(nu):
    with pytest.raises(ValueError):
        rayleigh_ratio(nu)


@pytest.mark.parametrize("vs", [0.0, -100.0, float("nan"), float("inf")])
def test_invalid_vs_raises(vs):
    with pytest.raises(ValueError):
        rayleigh_halfspace_velocity(vs, 0.3)


def test_factory_constant_curve_and_validation():
    curve = rayleigh_halfspace_factory(250.0, 0.35)
    f = np.array([1.0, 5.0, 20.0, 80.0])
    c = curve(f)
    assert c.shape == f.shape and np.allclose(c, 250.0 * rayleigh_ratio(0.35), rtol=1e-12)
    for bad in (np.array([0.0, 1.0]), np.array([-1.0]), np.array([np.nan])):
        with pytest.raises(ValueError):
            curve(bad)


def test_property_based_random_inputs():
    from hypothesis import given, settings
    from hypothesis import strategies as st

    @settings(max_examples=300, deadline=None, derandomize=True)
    @given(nu=st.floats(0.0, 0.5), vs=st.floats(30.0, 4000.0))
    def prop(nu, vs):
        c = rayleigh_halfspace_velocity(vs, nu)
        assert 0.86 * vs < c < 0.96 * vs
        assert abs(rayleigh_radical_residual((c / vs) ** 2, kappa2_from_nu(nu))) < 1e-9

    prop()


# La evidencia de V-E3-4 se deriva de esta suite por tools/check_e0.py.
# Un test no se autodeclara PASSED escribiendo un JSON.


def test_auxetic_domain_against_alternative_polynomial_solver():
    for nu in np.linspace(-0.999, 0.0, 101):
        k2 = kappa2_from_nu(nu)
        roots = np.roots([1.0, -8.0, 8.0 * (3.0 - 2.0 * k2), -16.0 * (1.0 - k2)])
        physical = roots[(np.abs(roots.imag) < 1e-9) & (roots.real > 0) & (roots.real < 1)].real
        assert physical.size == 1
        xi = rayleigh_xi(nu)
        assert xi == pytest.approx(physical[0], abs=1e-11)
        assert abs(rayleigh_radical_residual(xi, k2)) < 1e-11
