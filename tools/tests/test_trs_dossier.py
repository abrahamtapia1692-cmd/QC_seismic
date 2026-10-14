"""Pruebas unitarias y de integración para el generador de dosieres TRS."""

from pathlib import Path
import json
import numpy as np
import pytest

from tools.report_trs_dossier import (
    detect_clipping_fraction,
    pick_first_arrival,
    infer_source_station_name,
)

ROOT = Path(__file__).resolve().parents[2]


def test_detect_clipping_fraction_synthetic():
    # Onda senoidal continua sin mesetas
    t = np.linspace(0, 1, 1000)
    sine = np.sin(2 * np.pi * 10 * t)
    assert detect_clipping_fraction(sine) == 0.0

    # Onda recortada con mesetas consecutivas en extremos
    clipped = np.clip(sine * 5.0, -2.0, 2.0)
    frac = detect_clipping_fraction(clipped)
    assert frac > 0.05  # al menos 5% de muestras en meseta

    # Señal plana de ceros
    assert detect_clipping_fraction(np.zeros(200)) == 0.0


def test_pick_first_arrival_synthetic():
    dt = 0.000125  # 8000 Hz
    t = np.arange(3000) * dt
    noise = np.random.normal(0, 0.005, size=len(t))
    # Inyectar pulso impulsivo a partir de la muestra 300 (0.0375 s)
    pulse_start = 300
    noise[pulse_start:] += np.sin(2 * np.pi * 60 * (t[pulse_start:] - t[pulse_start])) * 0.5
    pick = pick_first_arrival(noise, dt, pre_trigger_samples=150)
    assert pick is not None
    # Con pre-trigger de 150 muestras, el arribo esperado es (300 - 150) * dt = 150 * dt = 0.01875 s
    expected_t = (pulse_start - 150) * dt
    assert abs(pick - expected_t) < 0.005  # margen de 5 ms


def test_infer_source_station_name():
    p1 = Path("KM 40+672/Datos/Sismica/F1/250122_205932.sg2")
    assert infer_source_station_name(p1) == "F01"

    p11 = Path("KM 52+500/Datos/Sísmica/TRS/F11/250123_140000.sg2")
    assert infer_source_station_name(p11) == "F11"

    p_none = Path("KM 40+672/Datos/test.sg2")
    assert infer_source_station_name(p_none) == "F_UNKNOWN"


@pytest.mark.parametrize("slug", ["KM_40_672", "KM_44_552", "KM_52_500"])
def test_trs_dossiers_structure_and_deliverables(slug):
    trs_dir = ROOT / "evidence/trs" / slug
    assert trs_dir.exists(), f"El directorio {trs_dir} debe existir"

    json_file = trs_dir / "dossier_trs.json"
    assert json_file.exists(), f"{json_file} debe existir"
    data = json.loads(json_file.read_text(encoding="utf-8"))

    assert data["slug"] == slug
    assert data["channels"] == 24
    assert data["total_traces"] > 0
    assert data["pick_coverage_percent"] > 90.0
    assert data["objective_sufficiency"] == "PENDIENTE"
    assert data["acceptance_status"] == "NOT_CERTIFIED"
    assert "spread_quality" in data
    assert data["spread_quality"]["grade"] in ("BUENA", "REGULAR", "MALA")

    # Archivos entregables requeridos
    assert (trs_dir / "dossier_trs.pdf").exists()
    assert (trs_dir / "dossier_trs.html").exists()
    assert (trs_dir / "traces_trs.csv").exists()
    assert (trs_dir / "picks_trs.csv").exists()
    assert (trs_dir / "reciprocity_trs.csv").exists()
    assert (trs_dir / "repeatability_trs.csv").exists()
    assert (trs_dir / "summary_trs.csv").exists()
