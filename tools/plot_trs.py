"""Figura científica independiente desde resultados ejecutados y ejemplo E4."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoqc.synth.trs import two_layer_times  # noqa: E402


def main() -> None:
    execution = json.loads((ROOT / "evidence/e4/execution.json").read_text(encoding="utf-8"))
    properties = {}
    for result in execution["results"]:
        for test in result["tests"]:
            for name, value in test["scientific_properties"]:
                if name in ("holdout_calibration", "independent_forward"):
                    properties.setdefault(name, []).append(json.loads(value) if isinstance(value, str) else value)
    figure, axes = plt.subplots(1, 3, figsize=(14, 4.5), layout="constrained")
    holdout = sorted(properties["holdout_calibration"], key=lambda row: row["db"])
    for nominal, color in ((68, "#246b85"), (95, "#c25d32")):
        values = np.array([row[f"coverage{nominal}"] for row in holdout])
        ci = np.array([row[f"coverage{nominal}_wilson95"] for row in holdout])
        axes[0].errorbar(
            [row["db"] for row in holdout],
            values,
            yerr=np.array([values - ci[:, 0], ci[:, 1] - values]),
            fmt="o",
            color=color,
            label=f"Intervalo {nominal}%",
        )
        axes[0].axhline(nominal / 100, color=color, linestyle="--", alpha=0.6)
    axes[0].set(
        xlabel="SNR activo declarado (dB)",
        ylabel="Cobertura holdout",
        ylim=(0.60, 1),
        title="6000 picks; train separado",
    )
    axes[0].legend(fontsize=8)
    report = json.loads((ROOT / "examples/e4/report.json").read_text(encoding="utf-8"))
    protocol = json.loads((ROOT / "examples/e4/protocol.json").read_text(encoding="utf-8"))
    usable = [row for row in report["picks"] if row["arrival"]["onset_s"] is not None]
    x = np.array([row["offset_m"] for row in usable])
    times = np.array([row["arrival"]["onset_s"] for row in usable]) - protocol["source_clock_correction_s"]
    uncertainties = np.array([row["arrival"]["sigma_s"] or 0 for row in usable])
    axes[1].errorbar(
        x, times * 1000, yerr=1.96 * uncertainties * 1000, fmt="o", markersize=3, label="Onset corregido; ±1.96 sigma"
    )
    offsets = np.linspace(0, max(x) * 1.1, 300)
    truth = two_layer_times(offsets, 300, 1500, 5)
    axes[1].plot(offsets, np.array(truth.first_s) * 1000, color="#c25d32", label="Referencia dos capas")
    axes[1].set(xlabel="Offset (m)", ylabel="Tiempo (ms)", title="Ejemplo causal; modelo condicionado")
    axes[1].legend(fontsize=7)
    study = properties["independent_forward"][0]
    step = [row["h_m"] for row in study["mesh_study"]]
    axes[2].loglog(step, np.array(study["fmm_abs_error_s"]) * 1000, "o-", label="FMM")
    axes[2].loglog(step, np.array(study["reference_abs_error_s"]) * 1000, "s-", label="pyGIMLi; secNodes=3")
    axes[2].loglog(step[-1], study["angular_refined_error_s"] * 1000, "D", label="pyGIMLi; secNodes=4")
    axes[2].axhline(0.25, color="#666666", linestyle="--", label="Presupuesto 0.25 ms")
    axes[2].set(xlabel="Paso de malla (m)", ylabel="Error absoluto (ms)", title="Gradiente; dos discretizaciones")
    axes[2].legend(fontsize=7)
    for axis in axes:
        axis.grid(alpha=0.2)
    figure.suptitle("GeoQC E4 — dominio sintético declarado; aceptación de campo pendiente", fontsize=11)
    folder = ROOT / "evidence/e4"
    figure.savefig(folder / "validation.svg")
    figure.savefig(folder / "validation.png", dpi=160)
    plt.close(figure)


if __name__ == "__main__":
    main()
