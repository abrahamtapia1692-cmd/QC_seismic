"""Exploración física previa al holdout; no escribe gates."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from geoqc.core.physics import rayleigh_halfspace_velocity  # noqa: E402
from geoqc.synth.nearfield import lamb_surface  # noqa: E402

if __name__ == "__main__":
    c = rayleigh_halfspace_velocity(200, 1 / 3)
    f = np.array([8, 16, 32])
    for x1 in (0.5, 2, 6, 20, 60, 120):
        x = x1 + np.arange(24) * 2
        green = lamb_surface(f, x, vp_ms=400, vs_ms=200, dk_m_inv=0.00025)["spectrum"]
        q = -np.array(
            [
                np.polyfit(x, np.unwrap(np.angle(row)), 1)[0] / (2 * np.pi * frequency)
                for row, frequency in zip(green, f, strict=True)
            ]
        )
        print(x1, "c", 1 / q, "bias", (1 / q - c) / c, "truth", c, flush=True)
