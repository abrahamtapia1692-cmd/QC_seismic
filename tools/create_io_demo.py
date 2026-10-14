"""Crear un ejemplo sintético de ingesta; no es un registro de campo."""

import hashlib
from pathlib import Path

import numpy as np

from geoqc.core.models import Acquisition, Geometry, Shot
from geoqc.core.physics import rayleigh_halfspace_velocity
from geoqc.io.writers import write_segy
from geoqc.synth.wavelets import causal_pulse


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    x = 6.0 + 2 * np.arange(24)
    time = -0.1 + 0.001 * np.arange(2048)
    c = rayleigh_halfspace_velocity(250.0, 0.4)
    data = np.stack([causal_pulse(time, 40.0, onset_s=float(offset / c)).samples for offset in x])
    geometry = Geometry(
        xr=x,
        yr=np.zeros(24),
        zr=np.zeros(24),
        xs=0.0,
        ys=0.0,
        zs=0.0,
        uncertainty_m=(0.0,) * 24,
        crs="SYNTHETIC_LOCAL_SI",
        provenance=("exact synthetic geometry",),
    )
    shot = Shot(
        id="SYNTHETIC_IO_DEMO",
        data=data,
        valid_mask=np.ones_like(data, dtype=bool),
        mask_reasons=("",) * 24,
        dt_s=(0.001,) * 24,
        t0_s=(-0.1,) * 24,
        geometry=geometry,
        acquisition=Acquisition(
            technique="MASW",
            wave="RAYLEIGH",
            component="Z",
            source_type="synthetic pulse",
            receiver_ids=tuple(f"DEMO-R{j + 1:02}" for j in range(24)),
            amplitude_unit="counts",
            stack_kind="RAW",
        ),
        input_hashes=(hashlib.sha256(data.tobytes(order="C")).hexdigest(),),
        headers_json='{"data_kind":"SYNTHETIC_DEMO","source_digest_kind":"generated_float64_matrix_bytes","field_acceptance":false,"model":"translated causal pulses at analytic halfspace velocity; not full Green"}',
    )
    folder = root / "examples/e1"
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / "synthetic_ieee.sgy"
    write_segy(output, shot)
    print(output)


if __name__ == "__main__":
    main()
