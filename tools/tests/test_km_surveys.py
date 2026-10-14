from pathlib import Path
import json
import numpy as np
import pytest

from tools.report_km_surveys import detect_clipping, estimate_first_arrival

ROOT = Path(__file__).resolve().parents[2]


def test_detect_clipping_synthetic():
    # Normal sine wave -> no clipping
    t = np.linspace(0, 1, 1000)
    normal = np.sin(2 * np.pi * 10 * t)
    assert not detect_clipping(normal)

    # Clipped signal with plateaus at extremes
    clipped = np.clip(normal * 5, -2, 2)
    assert detect_clipping(clipped)

    # Flat zero signal -> not clipping
    assert not detect_clipping(np.zeros(100))


def test_estimate_first_arrival_synthetic():
    dt = 0.000125
    t = np.arange(4000) * dt
    tr = np.random.normal(0, 0.01, size=len(t))
    # Inject impulsive wave starting at t = 0.050 s (sample 400)
    onset_sample = 800  # 0.100 s
    tr[onset_sample:] += np.sin(2 * np.pi * 50 * (t[onset_sample:] - t[onset_sample])) * 2.0
    arrival = estimate_first_arrival(tr, dt, pre_samples=200)
    assert arrival is not None
    assert abs(arrival - 0.100) < 0.010  # within 10 ms


def test_km_surveys_dossiers_exist_and_valid():
    surveys = ["KM_40_672", "KM_44_552", "KM_52_500"]
    for slug in surveys:
        dossier_dir = ROOT / "evidence/surveys" / slug
        assert dossier_dir.exists()
        json_file = dossier_dir / "dossier.json"
        assert json_file.exists()
        data = json.loads(json_file.read_text(encoding="utf-8"))
        assert data["slug"] == slug
        assert data["channels"] == 24
        assert data["trs_shots_count"] > 0
        assert data["integrity_status"] in ("PASS", "ADVERTENCIA")
        assert (dossier_dir / "dossier.pdf").exists()
        assert (dossier_dir / "dossier.html").exists()
        assert (dossier_dir / "traces.csv").exists()
        assert (dossier_dir / "shots.csv").exists()
        assert (dossier_dir / "repeatability.csv").exists()
