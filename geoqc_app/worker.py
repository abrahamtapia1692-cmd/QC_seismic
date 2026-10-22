from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from typing import Any

import psutil

from geoqc_app.errors import AppError
from geoqc_app.service import Service

LOG = logging.getLogger(__name__)


class Worker:
    def __init__(self, service: Service) -> None:
        self.service = service

    def run_once(self) -> bool:
        self.service.expire_uploads()
        while self.service.dispatch_one():
            pass
        run = self.service.claim()
        if run is None:
            return False
        self.execute(run)
        while self.service.dispatch_one():
            pass
        return True

    def execute(self, run: dict[str, Any]) -> None:
        service, settings = self.service, self.service.settings
        LOG.info("attempt_started project=%s run=%s attempt=%s token=%s",
                 run["project_id"], run["id"], run["attempt"], run["token"])
        folder = service.store.root / "attempts" / str(run["id"]) / str(run["token"])
        input_path = folder / "input.json"
        environment = os.environ.copy()
        environment.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", PYTHONUTF8="1")
        started, last_heartbeat = time.monotonic(), 0.0
        process: subprocess.Popen[bytes] | None = None
        try:
            folder.mkdir(parents=True, exist_ok=False)
            input_path.write_text(json.dumps(service.execution_inputs(run), allow_nan=False), encoding="utf-8")
            with (folder / "stderr.log").open("wb") as errors:
                process = subprocess.Popen(
                    [sys.executable, "-X", "utf8", "-m", "geoqc_app.calculate", str(input_path)],
                    stdout=subprocess.DEVNULL, stderr=errors, env=environment,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                monitor = psutil.Process(process.pid)
                while process.poll() is None:
                    elapsed = time.monotonic() - started
                    if elapsed > settings.calculation_timeout_seconds:
                        service.fail(run["id"], run["token"], "CALCULATION_TIMEOUT", transient=False)
                        return
                    try:
                        if monitor.memory_info().rss > settings.memory_limit_mib * 1024**2:
                            service.fail(run["id"], run["token"], "MEMORY_LIMIT", transient=False)
                            return
                    except psutil.NoSuchProcess:
                        continue
                    if time.monotonic() - last_heartbeat >= settings.heartbeat_seconds:
                        if not service.heartbeat(run["id"], run["token"], running=(folder / "phase.json").exists()):
                            return
                        last_heartbeat = time.monotonic()
                    time.sleep(0.1)
            if not service.heartbeat(run["id"], run["token"], running=(folder / "phase.json").exists()):
                return
            outcome_path = folder / "outcome.json"
            if not outcome_path.exists():
                service.fail(run["id"], run["token"], "CALCULATION_PROCESS_FAILED", transient=True)
                return
            outcome = json.loads(outcome_path.read_bytes())
            if outcome["state"] != "SUCCEEDED":
                service.fail(run["id"], run["token"], outcome["code"], transient=outcome["transient"])
                return
            result_path = folder / "dossier.json"
            if result_path.stat().st_size > 64 * 1024**2:
                service.fail(run["id"], run["token"], "RESULT_TOO_LARGE", transient=False)
                return
            content = result_path.read_bytes()
            blob = service.store.put(content)
            service.publish(run["id"], run["token"], json.loads(content), blob)
        except AppError as exc:
            if exc.code != "LEASE_LOST":
                service.fail(run["id"], run["token"], exc.code, transient=False)
        except OSError:
            service.fail(run["id"], run["token"], "WORKER_IO", transient=True)
        except (ValueError, KeyError, TypeError):
            service.fail(run["id"], run["token"], "INVALID_WORKER_RESULT", transient=False)
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            LOG.info("attempt_stopped project=%s run=%s attempt=%s token=%s duration_seconds=%.3f",
                     run["project_id"], run["id"], run["attempt"], run["token"], time.monotonic() - started)
