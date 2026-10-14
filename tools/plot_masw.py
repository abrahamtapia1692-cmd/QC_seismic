"""Figura científica independiente del código de los tests."""

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from geoqc.io.readers import read_shot  # noqa: E402
from geoqc.masw.contracts import MASWProtocol  # noqa: E402
from geoqc.masw.transform import phase_shift, shot_spectrum  # noqa: E402


def main():
    execution = json.loads((ROOT / "evidence/e5/execution.json").read_text(encoding="utf-8"))
    props = {}
    for result in execution["results"]:
        for test in result["tests"]:
            for name, value in test["scientific_properties"]:
                props.setdefault(name, []).append(value)
    protocol = MASWProtocol.model_validate_json((ROOT / "examples/e5/protocol.json").read_text(encoding="utf-8"))
    spectrum = shot_spectrum(read_shot(ROOT / "examples/e5/masw_plane.sgy"), protocol)
    image = phase_shift(
        spectrum["spectrum"],
        spectrum["frequencies_hz"],
        spectrum["x_m"],
        protocol.velocities_ms,
        weights=spectrum["weights"],
    )["coherence"]
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.8), constrained_layout=True)
    axes[0].pcolormesh(
        spectrum["frequencies_hz"], protocol.velocities_ms, image.T, vmin=0, vmax=1, cmap="viridis", shading="nearest"
    )
    axes[0].axhline(200, color="white", linestyle="--", label="Verdad sintética")
    axes[0].set(xlabel="Frecuencia (Hz)", ylabel="Velocidad (m/s)", title="Coherencia phase-shift; d=+1")
    axes[0].legend(fontsize=8)
    for row in props["curve_precision_holdout"]:
        axes[1].plot(row["frequencies_hz"], row["coverage95"], "o-", label=f"SNR {row['snr_db']} dB")
    axes[1].axhline(0.95, color="#666666", linestyle="--")
    axes[1].set(
        xlabel="Frecuencia (Hz)",
        ylabel="Cobertura del intervalo 95%",
        ylim=(0.90, 1),
        title="Holdout de precisión declarado",
    )
    axes[1].legend(fontsize=8)
    study = props["nearfield_bias"][0]["study"]
    for role in ("CALIBRATION", "HOLDOUT"):
        rows = [row for row in study if row["role"] == role]
        axes[2].plot(
            [row["near_ratio"][0] for row in rows], [100 * row["delta_c_over_c"][0] for row in rows], "o-", label=role
        )
    axes[2].axhline(-2, color="#666666", linestyle="--")
    axes[2].set(
        xlabel="Offset próximo / lambda; 8 Hz", ylabel="Sesgo de velocidad (%)", title="Green homogéneo completo P/S/R"
    )
    axes[2].legend(fontsize=8)
    for axis in axes:
        axis.grid(alpha=0.2)
    fig.suptitle("GeoQC E5 — dominios sintéticos declarados; aceptación de campo pendiente", fontsize=11)
    fig.savefig(ROOT / "evidence/e5/validation.svg")
    fig.savefig(ROOT / "evidence/e5/validation.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
