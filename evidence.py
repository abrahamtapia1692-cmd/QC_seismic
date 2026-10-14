"""Escritura de evidencia por subetapa (SDD §0.5)."""
from __future__ import annotations

import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy
import scipy


def _git_hash() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:  # noqa: BLE001
        return "no-git"


def write_evidence(directory: Path, vid: str, status: str, metrics: dict, tolerances: dict, seed: int | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": vid, "status": status, "metrics": metrics, "tolerances": tolerances, "seed": seed,
        "git_hash": _git_hash(),
        "versions": {"python": platform.python_version(), "numpy": numpy.__version__, "scipy": scipy.__version__},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    out = directory / f"{vid}.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return out
