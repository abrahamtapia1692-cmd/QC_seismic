import numpy as np
import pytest
from scipy.signal import butter, sosfilt, sosfreqz

from geoqc.masw.contracts import MASWProtocol
from geoqc.masw.transform import (
    fk_reference,
    phase_shift,
    shot_spectrum,
    spatial_kernel,
    tau_p_reference,
    uniform_fwhm,
    velocity_fwhm,
)
from geoqc.qc.contracts import Window
from tests.synthetic.e5_support import shot


@pytest.mark.vid("V-E5-1")
def test_common_window_phase_and_channel_muting(record_property):
    x = np.arange(24) * 2
    t = np.arange(4000) * 0.001
    data = np.cos(2 * np.pi * 5 * (t[None, :] - x[:, None] / 100))
    original = shot(data, x=x)
    protocol = MASWProtocol(
        signal=Window(start_s=0, end_s=4),
        frequencies_hz=(5, 10),
        velocities_ms=(90, 100, 110),
        provenance="controlled exact bin",
    )
    common = shot_spectrum(original, protocol)["spectrum"][0]
    raw = np.fft.rfft(data)[..., 20]
    phase_error = np.max(abs(np.angle(common / raw)))
    assert phase_error < 1e-3
    # Filtro causal común con historia explícita; descarta transitorio calentando4s.
    extended_time = np.arange(-4000, 4000) * 0.001
    extended = np.cos(2 * np.pi * 5 * (extended_time[None, :] - x[:, None] / 100))
    sos = butter(4, [2, 20], btype="bandpass", fs=1000, output="sos")
    filtered = sosfilt(sos, extended, axis=1)[:, 4000:]
    filtered_spectrum = shot_spectrum(shot(filtered, x=x), protocol)["spectrum"][0]
    transfer = sosfreqz(sos, worN=[5], fs=1000)[1][0]
    filter_phase_error = float(np.max(abs(np.angle(filtered_spectrum / (common * transfer)))))
    assert filter_phase_error < 1e-3
    muted = data.copy()
    for j in range(24):
        muted[j, : 2000 + j * 20] = 0
    changed = shot_spectrum(shot(muted, x=x), protocol)["spectrum"][0]
    relative = np.angle(changed / common)
    assert np.ptp(relative) > 0.001
    assert np.array_equal(original.data, data)
    q = np.linspace(0.02, 0.08, 2001)
    widths = []
    for spectrum in (common, changed):
        profile = phase_shift(spectrum[None, :], [5], x, 5 / q)["coherence"][0]
        active = np.flatnonzero(profile >= profile.max() / 2)
        widths.append(float(q[active[-1]] - q[active[0]]))
    record_property(
        "preprocessing",
        {
            "common_phase_error_rad": float(phase_error),
            "channel_muting_phase_spread_rad": float(np.ptp(relative)),
            "common_causal_filter_phase_error_rad": filter_phase_error,
            "observed_halfmaximum_q_width_before_after": widths,
            "peak_before_ms": 100,
            "peak_after_ms": int(np.argmax(phase_shift(changed[None, :], [5], x, np.arange(80, 121))["coherence"]))
            + 80,
            "kernel_full_fwhm_q": uniform_fwhm(24, 2),
            "muting_changes_frequency_support": True,
        },
    )


@pytest.mark.vid("V-E5-2")
def test_plane_wave_sign_and_exact_alignment():
    x = np.arange(24) * 2
    u = np.exp(-2j * np.pi * 5 * x / 100)[None, :]
    c = np.arange(80, 121)
    positive = phase_shift(u, [5], x, c)["coherence"][0]
    negative = phase_shift(u, [5], x, c, direction=-1)["coherence"][0]
    assert positive[20] == pytest.approx(1, abs=1e-6)
    assert np.argmax(positive) == 20 and negative[20] < 0.1


@pytest.mark.vid("V-E5-3")
def test_finite_kernel_exact_velocity_boundaries(record_property):
    amplitude, power = uniform_fwhm(24, 2), uniform_fwhm(24, 2, power=True)
    assert amplitude * 48 == pytest.approx(1.2074756732, abs=5e-10)
    assert power * 48 == pytest.approx(0.8865573942, abs=5e-10)
    rows = []
    for ratio in (0.25, 0.5, 1):
        wavelength, c0 = 48 * ratio, 200
        for width, is_power in ((amplitude, False), (power, True)):
            limits = velocity_fwhm(c0 / wavelength, c0, width)
            if limits["finite"]:
                for boundary in limits["c_bounds_ms"]:
                    value = spatial_kernel(c0 / wavelength / boundary - 1 / wavelength, np.arange(24) * 2)
                    assert value ** (2 if is_power else 1) == pytest.approx(0.5, abs=1e-10)
            rows.append({"lambda_over_aperture": ratio, "power": is_power, **limits})
    assert rows[-2]["relative_width"] > 1.8  # aproximación universal 0.886 no aplica
    assert not velocity_fwhm(1, 200, amplitude)["finite"]
    record_property(
        "finite_kernel", {"amplitude_scaled": amplitude * 48, "power_scaled": power * 48, "boundaries": rows}
    )


@pytest.mark.vid("V-E5-4")
def test_signed_aliases_real_masked_irregular_kernel(record_property):
    x = np.arange(24) * 2
    q = np.linspace(-0.25, 0.25, 6001)
    aliased = 1 / 3
    u = np.exp(-2j * np.pi * aliased * x)[None, :]
    fk = fk_reference(u, [5], x, q)[0]
    assert q[np.argmax(fk)] == pytest.approx(aliased - 0.5, abs=1e-4)
    safe = 1 / 6
    fk = fk_reference(np.exp(-2j * np.pi * safe * x)[None, :], [5], x, q)[0]
    assert q[np.argmax(fk)] == pytest.approx(safe, abs=1e-4)
    mask = np.arange(24) % 2 == 0
    assert spatial_kernel(0.25, x[mask]) == pytest.approx(1, abs=1e-12)
    irregular = x + np.sin(np.arange(24)) * 0.3
    assert spatial_kernel(0.25, irregular) < 0.95
    record_property(
        "alias",
        {
            "q_true": aliased,
            "q_alias": aliased - 0.5,
            "signed_search": [-0.25, 0.25],
            "masked_alias_coherence": float(spatial_kernel(0.25, x[mask])),
            "irregular_alias_coherence": float(spatial_kernel(0.25, irregular)),
        },
    )


@pytest.mark.vid("V-E5-5")
def test_phase_fk_time_domain_tau_p_independent_references(record_property):
    x = np.arange(24) * 2
    t = np.arange(3000) * 0.001
    rows = []
    for velocity in (150, 200, 300):
        u = t[None, :] - 0.4 - x[:, None] / velocity
        data = np.exp(-0.5 * (u / 0.09) ** 2) * np.cos(2 * np.pi * 20 * u)
        spectrum = np.fft.rfft(data).T
        f = np.fft.rfftfreq(t.size, 0.001)
        band = (f >= 12) & (f <= 28)
        c = np.arange(100, 351)
        phase = c[np.argmax(phase_shift(spectrum[band], f[band], x, c)["coherence"], axis=1)]
        q = np.arange(0.03, 0.3, 0.0001)
        power = fk_reference(spectrum[band], f[band], x, q)
        fk = f[band] / q[np.argmax(power, axis=1)]
        p = 1 / c[::-1]
        stack = tau_p_reference(data, 0.001, x, p)
        tau = 1 / p[np.argmax(np.max(abs(stack), axis=1))]
        assert np.median(abs(phase - velocity) / velocity) < 0.02
        assert np.median(abs(fk - phase) / velocity) < 0.02
        assert abs(tau - velocity) / velocity < 0.02
        rows.append(
            {
                "true_ms": velocity,
                "phase_median_ms": float(np.median(phase)),
                "fk_median_ms": float(np.median(fk)),
                "tau_p_ms": float(tau),
                "band_hz": [12, 28],
            }
        )
    record_property("independent_transformers", rows)


@pytest.mark.vid("V-E5-6")
def test_metamorphic_support_preserving_properties():
    rng = np.random.default_rng(656)
    f, x, c = [8, 16], np.arange(24) * 2, np.arange(100, 301)
    u = rng.normal(size=(2, 24)) + 1j * rng.normal(size=(2, 24))
    u[:, 5] = 0
    w = rng.uniform(0.5, 1.5, 24)
    original = phase_shift(u, f, x, c, weights=w)["coherence"]
    perm = rng.permutation(24)
    np.testing.assert_allclose(
        original, phase_shift(u[:, perm], f, x[perm], c, weights=w[perm])["coherence"], atol=1e-14
    )
    np.testing.assert_allclose(original, phase_shift(u * 3 * np.exp(0.2j), f, x, c, weights=w)["coherence"], atol=1e-14)
    np.testing.assert_allclose(original, phase_shift(u, f, -x, c, direction=-1, weights=w)["coherence"], atol=1e-14)
    keep = np.arange(24) != 5
    np.testing.assert_allclose(
        original, phase_shift(u[:, keep], f, x[keep], c, weights=w[keep])["coherence"], atol=1e-14
    )
