import json

import numpy as np

from geoqc.core.models import Acquisition, Geometry, Shot
from geoqc.qc.contracts import Window
from geoqc.trs.contracts import PickProtocol

DT = 0.00025
TIME = np.arange(800) * DT - 0.025


def trs_shot(data, *, dt=DT, t0=-0.025, receiver_x=None, source_x=0):
    data = np.atleast_2d(data)
    n = data.shape[0]
    receivers = np.arange(n) + 1.0 if receiver_x is None else receiver_x
    return Shot(
        id="synthetic-trs",
        data=data,
        valid_mask=np.ones_like(data, dtype=bool),
        mask_reasons=("",) * n,
        dt_s=(dt,) * n,
        t0_s=(t0,) * n,
        geometry=Geometry(
            xr=receivers,
            yr=np.zeros(n),
            zr=np.zeros(n),
            xs=source_x,
            ys=0,
            zs=0,
            uncertainty_m=(0.01,) * n,
            crs="local-SI",
            provenance=("synthetic",),
        ),
        acquisition=Acquisition(
            technique="TRS",
            wave="P",
            component="Z",
            source_type="known synthetic causal source",
            receiver_ids=tuple(f"r{j}" for j in range(n)),
        ),
        input_hashes=("a" * 64,),
        headers_json='{"scope":"synthetic only"}',
    )


def pick_protocol(db=None):
    return PickProtocol(
        search=Window(start_s=0, end_s=0.16),
        noise=Window(start_s=-0.025, end_s=-0.005),
        domain_id=None if db is None else f"gated-damped-P-80Hz-iidGaussian-SNR{db}",
        provenance="docs/requirements_e4.md",
    )


def realization(rng, db, onset=None):
    onset = rng.uniform(0.035, 0.08) if onset is None else onset
    u = TIME - onset
    clean = np.where(u >= 0, np.exp(-np.maximum(u, 0) / 0.04) * np.cos(2 * np.pi * 80 * u), 0)
    support = (u >= 0) & (u < 0.025)
    sigma = np.sqrt(np.mean(clean[support] ** 2) / 10 ** (db / 10))
    return clean + rng.normal(0, sigma, TIME.size), onset


def record(record_property, name, data):
    record_property(name, json.dumps(data, ensure_ascii=False, allow_nan=False))


def wilson(success, count):
    z = 1.959963984540054
    p = success / count
    center = (p + z * z / (2 * count)) / (1 + z * z / count)
    half = z * np.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / (1 + z * z / count)
    return [max(0, float(center - half)), min(1, float(center + half))]
