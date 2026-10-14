"""Ejemplo MASW SEG-Y reproducible, sin declarar calibración de campo."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoqc.core.models import Acquisition, Geometry, Shot  # noqa: E402
from geoqc.io.readers import read_shot  # noqa: E402
from geoqc.io.writers import write_segy  # noqa: E402
from geoqc.masw.contracts import MASWProtocol  # noqa: E402
from geoqc.masw.report import masw_diagnostics  # noqa: E402
from geoqc.qc.contracts import Window  # noqa: E402


def main() -> None:
    folder = ROOT / "examples/e5"
    folder.mkdir(parents=True, exist_ok=True)
    waveform = folder / "masw_plane.sgy"
    if not waveform.exists():
        x, t = np.arange(24) * 2 + 6, np.arange(4000) * 0.001
        rng = np.random.default_rng(202610056)
        data = sum(np.cos(2 * np.pi * f * (t[None, :] - x[:, None] / 200)) for f in np.arange(8, 33, 2))
        data += rng.normal(0, 0.1, data.shape)
        shot = Shot(
            id="e5-masw-synthetic-demo",
            data=data,
            valid_mask=np.ones_like(data, dtype=bool),
            mask_reasons=("",) * 24,
            dt_s=(0.001,) * 24,
            t0_s=(0.0,) * 24,
            geometry=Geometry(
                xr=x,
                yr=np.zeros(24),
                zr=np.zeros(24),
                xs=0,
                ys=0,
                zs=0,
                uncertainty_m=(0.01,) * 24,
                crs="local-SI",
                provenance=("synthetic x=6+2j",),
            ),
            acquisition=Acquisition(
                technique="MASW",
                wave="RAYLEIGH",
                component="Z",
                source_type="declared multisine plane wave",
                receiver_ids=tuple(f"r{i}" for i in range(24)),
                amplitude_unit="m",
                stack_kind="RAW",
            ),
            input_hashes=("d" * 64,),
            headers_json="{}",
        )
        write_segy(waveform, shot)
    protocol = MASWProtocol(
        signal=Window(start_s=0, end_s=4),
        frequencies_hz=tuple(np.arange(8, 33, 2)),
        velocities_ms=tuple(np.arange(100, 401, 2)),
        window="HANN",
        directions=(1, -1),
        provenance="synthetic multisine 200m/s; no real mode/calibration",
        domain_id="demo-plane-24ch",
    )
    (folder / "protocol.json").write_text(protocol.model_dump_json(indent=2) + "\n", encoding="utf-8")
    report = masw_diagnostics(read_shot(waveform), protocol)
    (folder / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "channels": 24,
                "directions": len(report["curves"]),
                "eligible_for_acceptance": False,
                "precision": "UNCALIBRATED",
                "example": "examples/e5/masw_plane.sgy",
            }
        )
    )


if __name__ == "__main__":
    main()
