"""Conservative reconciliation for the single-database local artifact store."""
from __future__ import annotations

import math
import re
import time
from typing import Any

from geoqc_app.errors import AppError
from geoqc_app.service import Service
from geoqc_app.storage import Blob


def reconcile(service: Service, *, apply: bool = False, minimum_age_seconds: float = 86400) -> dict[str, Any]:
    if not math.isfinite(minimum_age_seconds) or minimum_age_seconds < 3600:
        raise ValueError("La retención mínima de blobs huérfanos es una hora")
    report: dict[str, Any] = {"mode": "APPLY" if apply else "REPORT", "referenced": 0,
                              "integrity_errors": [], "orphan_candidates": [], "deleted": [], "retained": []}
    cutoff = time.time() - minimum_age_seconds
    with service.db.connect() as conn:
        # All command/reference writes take the corresponding shared lock through commit.
        service.storage_lock(conn, exclusive=True)
        active = conn.execute(
            "SELECT (SELECT count(*) FROM upload_sessions WHERE state='UPLOADING') + "
            "(SELECT count(*) FROM processing_runs WHERE state IN "
            "('QUEUED','VALIDATING','RUNNING','RETRY_WAIT')) + "
            "(SELECT count(*) FROM exports WHERE state IN ('PENDING','RUNNING')) AS n"
        ).fetchone()
        report["open_operations"] = active["n"] if active else 0
        if apply and report["open_operations"]:
            raise AppError(409, "MAINTENANCE_BUSY", "Hay cargas o trabajos abiertos; solo se permite el informe")
        rows = conn.execute("SELECT storage_key,sha256,size_bytes FROM artifacts").fetchall()
        referenced = {row["storage_key"] for row in rows}
        report["referenced"] = len(referenced)
        for row in rows:
            try:
                service.store.verify(Blob(row["storage_key"], row["sha256"], row["size_bytes"]))
            except (OSError, AppError):
                report["integrity_errors"].append(row["storage_key"])
        # Do not delete anything if even one referenced original/result is unavailable.
        if apply and report["integrity_errors"]:
            raise AppError(409, "MAINTENANCE_INTEGRITY", "Artefactos referenciados requieren reparación")
        folder = service.store.root / "blobs"
        if folder.is_symlink() or folder.resolve() != folder:
            raise AppError(409, "UNSAFE_STORAGE_PATH", "Directorio de blobs incompatible")
        for path in sorted(folder.iterdir()):
            if path.name in referenced:
                continue
            if (not re.fullmatch(r"[a-f0-9]{32}", path.name) or path.is_symlink()
                    or not path.is_file() or path.resolve().parent != folder
                    or path.stat().st_mtime > cutoff):
                report["retained"].append(path.name)
                continue
            report["orphan_candidates"].append(path.name)
            if apply:
                path.unlink()
                report["deleted"].append(path.name)
    # Attempts and temporary uploads are deliberately outside the deletion protocol.
    return report
