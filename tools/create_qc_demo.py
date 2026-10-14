"""Ejemplo reproducible SEG-Y + protocolo + informe diagnóstico de E2."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoqc.core.config import load_config  # noqa: E402
from geoqc.core.models import Acquisition, Geometry, Shot  # noqa: E402
from geoqc.io.readers import read_shot  # noqa: E402
from geoqc.io.writers import write_segy  # noqa: E402
from geoqc.qc import common_qc  # noqa: E402
from geoqc.qc.contracts import QCProtocol, Window  # noqa: E402


def main() -> None:
    folder = ROOT / "examples/e2"
    folder.mkdir(parents=True, exist_ok=True)
    waveform = folder / "common_qc.sgy"
    if waveform.exists():
        print("El ejemplo ya existe; se conserva el waveform y se actualiza su informe.")
    else:
        rng = np.random.default_rng(20261005)
        offsets = np.arange(6) * 2.0 + 6
        time = np.arange(2048) * 0.001 - 0.512
        gains = np.exp(-offsets / 30)
        u = time[None, :] - (0.4 + offsets[:, None] / 200)
        data = 0.6 * gains[:, None] * np.exp(-0.5 * (u / 0.025) ** 2) * np.cos(2 * np.pi * 40 * u)
        data += rng.normal(0, 0.002, data.shape)
        data[4] *= 0.2
        data[5] = 0
        shot = Shot(
            id="e2-common-qc-demo",
            data=data,
            valid_mask=np.ones_like(data, dtype=bool),
            mask_reasons=("",) * 6,
            dt_s=(0.001,) * 6,
            t0_s=(-0.512,) * 6,
            geometry=Geometry(
                xr=offsets,
                yr=np.zeros(6),
                zr=np.zeros(6),
                xs=0,
                ys=0,
                zs=0,
                uncertainty_m=(0.01,) * 6,
                crs="local-SI",
                provenance=("synthetic geometry",),
            ),
            acquisition=Acquisition(
                technique="MASW",
                wave="RAYLEIGH",
                component="Z",
                source_type="synthetic pulse",
                receiver_ids=tuple(f"r{j}" for j in range(6)),
                adc_rails=(-1, 1),
                stack_kind="RAW",
            ),
            input_hashes=("a" * 64,),
            headers_json='{"scope":"synthetic illustration only"}',
        )
        write_segy(waveform, shot)
    settings = QCProtocol(
        analysis=Window(start_s=-0.512, end_s=1.536),
        noise=Window(start_s=-0.512, end_s=-0.128),
        signal=Window(start_s=0, end_s=1.536),
        noise_independent=True,
        noise_stationarity="VERIFIED",
        stationarity_ref="Known iid noise process in create_qc_demo.py, seed 20261005",
        expected_relative_amplitude=tuple(np.exp(-(np.arange(6) * 2 + 6) / 30)),
        amplitude_model_ref="Known synthetic gains exp(-r/30); not field coupling calibration",
        rail_scale_to_data=1,
        frequency_band_hz=(10, 100),
        min_group_velocity_ms=80,
        wavelet_duration_s=0.3,
        mains_hz=50,
        provenance="examples/e2; synthetic protocol",
    )
    (folder / "protocol.json").write_text(settings.model_dump_json(indent=2) + "\n", encoding="utf-8")
    report = common_qc(read_shot(waveform), settings, load_config(ROOT / "configs/vs30_sitio.yaml"))
    (folder / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(json.dumps({"waveform": str(waveform.relative_to(ROOT)), "report": "examples/e2/report.json"}))


if __name__ == "__main__":
    main()
