"""Ejemplo auditable de supresión candidata y estabilidad del picker real; originales separados."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from geoqc.core.models import Acquisition, Geometry, Shot  # noqa: E402
from geoqc.qc.noise import filter_candidate  # noqa: E402
from geoqc.trs.contracts import PickProtocol  # noqa: E402
from geoqc.trs.picking import pick_trace  # noqa: E402


def main() -> None:
    output = ROOT / "evidence/trace_quality"
    output.mkdir(parents=True, exist_ok=True)
    dt = 0.001
    time = np.arange(6000) * dt - 3
    u = np.maximum(time - 0.2, 0)
    clean = np.exp(-u / 0.05) * np.sin(2 * np.pi * 80 * u)
    raw = clean + 0.04 * np.sin(2 * np.pi * 59.95 * time) + 0.04 * np.sin(2 * np.pi * 3 * time)
    raw += np.random.default_rng(812).normal(0, 0.003, time.size)
    original = raw.copy()
    shot = Shot(
        id="filter-review-synthetic",
        data=raw[None, :],
        valid_mask=np.ones((1, time.size), dtype=bool),
        mask_reasons=("",),
        dt_s=(dt,),
        t0_s=(-3,),
        geometry=Geometry(
            xr=[2], yr=[0], zr=[0], xs=0, ys=0, zs=0, uncertainty_m=(0.01,), crs="local-SI", provenance=("synthetic",)
        ),
        acquisition=Acquisition(
            technique="TRS",
            wave="P",
            component="Z",
            source_type="synthetic",
            receiver_ids=("r1",),
            adc_rails=(-2, 2),
            stack_kind="RAW",
        ),
        input_hashes=(hashlib.sha256(raw.tobytes()).hexdigest(),),
        headers_json='{"synthetic":true}',
    )
    protocol = PickProtocol(
        search={"start_s": 0, "end_s": 0.5},
        noise={"start_s": -2.9, "end_s": -0.1},
        provenance="Fixed synthetic filter test; no field validation",
    )
    picks = []

    def pick(values):
        candidate = Shot.model_validate(shot.model_dump() | {"data": values[None, :]})
        result = pick_trace(candidate, 0, protocol)
        picks.append(result.model_dump(mode="json"))
        return result.onset_s

    filtered, audit = filter_candidate(raw, dt, highpass_hz=10, notch_hz=(59.95,), pick=pick)
    np.testing.assert_array_equal(raw, original)
    audit.update(
        known_onset_s=0.2,
        pick_details=picks,
        seed=812,
        waveform="filter_candidate.npz",
        scope="Synthetic demonstration only; frequency known from injection, not fitted to the arrival",
        field_filtering="NOT_APPLIED; evidence, band and pick stability require review",
        protocol=protocol.model_dump(mode="json"),
        code_sha256={
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (Path(__file__), ROOT / "geoqc/qc/noise.py", ROOT / "geoqc/trs/picking.py")
        },
    )
    np.savez_compressed(output / "filter_candidate.npz", time_s=time, raw=raw, candidate=filtered, clean_known=clean)
    (output / "filter_validation.json").write_text(
        json.dumps(audit, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8"
    )
    fig, axes = plt.subplots(2, 1, figsize=(12, 6), constrained_layout=True)
    for ax, limits in zip(axes, [(-0.5, 0.8), (0.15, 0.3)], strict=True):
        ax.plot(time, raw, color="#94a3b8", lw=0.8, label="Original sintético")
        ax.plot(time, filtered, color="#2563eb", lw=1, label="Candidato HP10 + notch59.95")
        ax.plot(time, clean, color="#16803c", lw=0.8, label="Señal verdadera conocida")
        ax.axvline(0.2, color="black", ls="--", lw=0.8, label="Inicio causal conocido")
        ax.set(xlim=limits, xlabel="Tiempo (s)", ylabel="Amplitud")
        ax.legend(fontsize=8)
    fig.suptitle(
        f"Supresión experimental · estabilidad del picker: {audit['pick_stability']}\n"
        f"Pick original: {audit['pick_before_s']}; candidato: {audit['pick_after_s']}. "
        "El acuerdo entre picks no demuestra exactitud."
    )
    fig.savefig(output / "filter_validation.png", dpi=130)
    plt.close(fig)
    print(
        json.dumps(
            {key: audit[key] for key in ("status", "pick_stability", "pick_before_s", "pick_after_s", "pick_delta_s")}
        )
    )


if __name__ == "__main__":
    main()
