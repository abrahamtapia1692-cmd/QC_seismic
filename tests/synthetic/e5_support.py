import numpy as np
from scipy.stats import norm

from geoqc.core.models import Acquisition, Geometry, Shot
from geoqc.masw.curves import refine_peak_velocities
from geoqc.masw.transform import phase_shift
from geoqc.synth.dispersion import LayeredModel

FAMILIES = (
    LayeredModel(layers=((5, 400, 180, 1800), (0, 900, 450, 2000))),
    LayeredModel(layers=((5, 900, 400, 2000), (7, 500, 220, 1800), (0, 1100, 550, 2100))),
    LayeredModel(layers=((3, 300, 120, 1700), (0, 1200, 600, 2100))),
)


def wilson(k, n, z=None):
    z = norm.ppf(0.975) if z is None else z
    p = k / n
    center = (p + z * z / (2 * n)) / (1 + z * z / n)
    delta = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [float(center - delta), float(center + delta)]


def shot(data, *, x=None, dt=0.001, t0=0):
    data = np.asarray(data, float)
    n = data.shape[0]
    x = np.arange(n) * 2 + 6 if x is None else np.asarray(x)
    return Shot(
        id="e5-synthetic",
        data=data,
        valid_mask=np.ones_like(data, dtype=bool),
        mask_reasons=("",) * n,
        dt_s=(dt,) * n,
        t0_s=(t0,) * n,
        geometry=Geometry(
            xr=x,
            yr=np.zeros(n),
            zr=np.zeros(n),
            xs=0,
            ys=0,
            zs=0,
            uncertainty_m=(0.01,) * n,
            crs="local-SI",
            provenance=("independent synthetic coordinates",),
        ),
        acquisition=Acquisition(
            technique="MASW",
            wave="RAYLEIGH",
            component="Z",
            receiver_ids=tuple(f"r{i}" for i in range(n)),
            source_type="declared synthetic",
            amplitude_unit="m",
            stack_kind="RAW",
        ),
        input_hashes=("c" * 64,),
        headers_json="{}",
    )


def spectral_errors(seed, count, snr_db, *, n=24, dx=2, frequencies=(8, 16, 32), correlation=0):
    rng = np.random.default_rng(seed)
    f, x = np.asarray(frequencies), np.arange(n) * dx
    true_c = np.full(f.size, 200.0)
    signal = np.exp(-2j * np.pi * f[:, None] * x[None, :] / true_c[:, None])
    noise = (rng.normal(size=(count, f.size, n)) + 1j * rng.normal(size=(count, f.size, n))) / np.sqrt(
        2 * 10 ** (snr_db / 10)
    )
    if correlation:
        common = (rng.normal(size=(count, 1, n)) + 1j * rng.normal(size=(count, 1, n))) / np.sqrt(
            2 * 10 ** (snr_db / 10)
        )
        noise = np.sqrt(1 - correlation) * noise + np.sqrt(correlation) * common
    errors = np.zeros((count, f.size))
    for i, frequency in enumerate(f):
        q = frequency / 200 + np.arange(-160, 161) * 0.00005
        c = (frequency / q)[::-1]
        for trial in range(count):
            scores = phase_shift((signal[i] + noise[trial, i])[None, :], [frequency], x, c)["coherence"]
            index = (int(np.argmax(scores)),)
            errors[trial, i] = refine_peak_velocities(scores, [frequency], c, index)[0] - 200
    return errors
