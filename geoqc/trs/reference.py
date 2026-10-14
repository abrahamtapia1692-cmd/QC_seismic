from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def pygimli_forward(request: dict[str, Any], *, python: Path, adapter: Path, timeout_s: float = 120) -> dict[str, Any]:
    """Adapter de referencia explícito; no instala ni sustituye solver si falta."""
    if not python.is_file() or not adapter.is_file():
        raise ValueError("Referencia pyGIMLi no instalada o adapter ausente")
    with tempfile.TemporaryDirectory(prefix="geoqc-pygimli-") as temp:
        folder = Path(temp)
        input_path, output_path = folder / "request.json", folder / "response.json"
        input_path.write_text(json.dumps(request, allow_nan=False), encoding="utf-8")
        result = subprocess.run(
            [str(python.resolve()), "-X", "utf8", str(adapter.resolve()), str(input_path), str(output_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_s,
            check=False,
        )
        if result.returncode != 0 or not output_path.is_file():
            raise ValueError(f"Referencia pyGIMLi falló ({result.returncode}): {result.stderr[-3000:]}")
        response: dict[str, Any] = json.loads(output_path.read_text(encoding="utf-8"))
        return response
