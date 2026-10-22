"""Separate, bounded rendering process with durable export lease and fencing."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
import time
from typing import Any

import psutil

from geoqc_app.errors import AppError
from geoqc_app.exports import Exports
from geoqc_app.service import Service

LOG = logging.getLogger(__name__)


class ExportWorker:
    def __init__(self, service: Service) -> None:
        self.service, self.exports = service, Exports(service)

    def run_once(self) -> bool:
        while self.service.dispatch_one():
            pass
        export = self.exports.claim()
        if export is None:
            return False
        self.execute(export)
        while self.service.dispatch_one():
            pass
        return True

    def execute(self, export: dict[str, Any]) -> None:
        service, settings, jobs = self.service, self.service.settings, self.exports
        folder = service.store.root / "export_attempts" / str(export["id"]) / str(export["token"])
        process: subprocess.Popen[bytes] | None = None
        started, last_heartbeat = time.monotonic(), 0.0
        LOG.info("export_started project=%s export=%s attempt=%s token=%s",
                 export["project_id"], export["id"], export["attempt"], export["token"])
        try:
            folder.mkdir(parents=True, exist_ok=False)
            path = folder / "input.json"
            path.write_text(json.dumps(jobs.inputs(export), allow_nan=False), encoding="utf-8")
            environment = os.environ.copy()
            environment.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", PYTHONUTF8="1")
            with (folder / "stderr.log").open("wb") as errors:
                process = subprocess.Popen([sys.executable, "-X", "utf8", "-m", "geoqc_app.render_exports", str(path)],
                                           stdout=subprocess.DEVNULL, stderr=errors, env=environment,
                                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                monitor = psutil.Process(process.pid)
                while process.poll() is None:
                    if time.monotonic() - started > settings.calculation_timeout_seconds:
                        jobs.fail(export["id"], export["token"], "EXPORT_TIMEOUT")
                        return
                    try:
                        if monitor.memory_info().rss > settings.memory_limit_mib * 1024**2:
                            jobs.fail(export["id"], export["token"], "EXPORT_MEMORY_LIMIT")
                            return
                    except psutil.NoSuchProcess:
                        continue
                    if time.monotonic() - last_heartbeat >= settings.heartbeat_seconds:
                        if not jobs.heartbeat(export["id"], export["token"]):
                            return
                        last_heartbeat = time.monotonic()
                    time.sleep(0.1)
            if not jobs.heartbeat(export["id"], export["token"]):
                return
            outcome_path = folder / "outcome.json"
            if not outcome_path.exists():
                jobs.fail(export["id"], export["token"], "EXPORT_PROCESS_FAILED")
                return
            outcome = json.loads(outcome_path.read_bytes())
            if outcome["state"] != "READY":
                jobs.fail(export["id"], export["token"], outcome["code"])
                return
            result = folder / "rendered.bin"
            if result.stat().st_size > 64 * 1024**2:
                jobs.fail(export["id"], export["token"], "EXPORT_TOO_LARGE")
                return
            content = result.read_bytes()
            if hashlib.sha256(content).hexdigest() != outcome["sha256"]:
                raise AppError(409, "EXPORT_OUTPUT_INTEGRITY", "Exportación incompatible con su manifiesto")
            jobs.publish(export["id"], export["token"], service.store.put(content))
        except AppError as exc:
            if exc.code != "LEASE_LOST":
                jobs.fail(export["id"], export["token"], exc.code)
        except OSError:
            jobs.fail(export["id"], export["token"], "EXPORT_IO")
        except (ValueError, KeyError, TypeError):
            jobs.fail(export["id"], export["token"], "EXPORT_INVALID_RESULT")
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            LOG.info("export_stopped project=%s export=%s attempt=%s token=%s duration_seconds=%.3f",
                     export["project_id"], export["id"], export["attempt"], export["token"], time.monotonic() - started)
