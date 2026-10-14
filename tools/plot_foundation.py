"""Figuras reproducibles desde las propiedades numéricas registradas por pytest."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    directory = root / "evidence/e1_e3"
    payload = json.loads((directory / "execution.json").read_text(encoding="utf-8"))
    comparisons = []
    eikonal = None
    for result in payload["results"]:
        for node in result["tests"]:
            for name, value in node.get("scientific_properties", []):
                if name == "forward_comparison":
                    comparisons.append(value)
                elif name == "eikonal_convergence":
                    eikonal = value
    if len(comparisons) != 3 or eikonal is None:
        raise ValueError("Se requieren resultados registrados de los tres perfiles y del eikonal")
    fig, axes = plt.subplots(2, 3, figsize=(12, 6.5), sharex="col", gridspec_kw={"height_ratios": [3, 1.3]})
    labels = ("Dos capas", "Gradación", "Vs invertido")
    for column, (item, label) in enumerate(zip(comparisons, labels, strict=True)):
        frequency = np.asarray(item["frequencies_hz"])
        external, fem = np.asarray(item["disba_ms"]), np.asarray(item["fem_ms"])
        axes[0, column].semilogx(frequency, external, "-", color="#155e75", label="Dunkin / disba")
        axes[0, column].semilogx(frequency, fem, "o", color="#dc7c28", markersize=5, label="FEM propio")
        axes[0, column].set_title(label)
        axes[0, column].set_ylabel("c [m/s]")
        axes[1, column].semilogx(frequency, 100 * abs(fem - external) / external, "o-", color="#155e75")
        axes[1, column].axhline(0.5, linestyle="--", color="#9f1239", label="Límite 0.5 %")
        axes[1, column].set_ylim(0, 0.55)
        axes[1, column].set_ylabel("Diferencia [%]")
        axes[1, column].set_xlabel("f [Hz]")
        for row in (0, 1):
            axes[row, column].grid(alpha=0.2)
    axes[0, 0].legend(frameon=False, fontsize=8)
    fig.suptitle("Referencia Rayleigh fundamental — banda y perfiles sintéticos declarados")
    fig.tight_layout()
    fig.savefig(directory / "dispersion_comparison.svg")
    fig.savefig(directory / "dispersion_comparison.png", dpi=160)
    plt.close(fig)
    fig, axis = plt.subplots(figsize=(6, 4))
    axis.loglog(eikonal["grid_h_m"], 100 * np.asarray(eikonal["relative_errors"]), "o-", color="#155e75")
    axis.axhline(1.0, linestyle="--", color="#9f1239", label="Límite de referencia 1 %")
    axis.set(
        xlabel="Paso de malla [m]",
        ylabel="Error respecto a fórmula [%]",
        title="Eikonal independiente: refinamiento de malla",
    )
    axis.grid(alpha=0.2)
    axis.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(directory / "eikonal_convergence.svg")
    plt.close(fig)
    print("Figuras guardadas en evidence/e1_e3")


if __name__ == "__main__":
    main()
