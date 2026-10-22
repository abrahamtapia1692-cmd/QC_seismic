from __future__ import annotations

import argparse
import hashlib
import json
import logging
import secrets
import time
from pathlib import Path
from uuid import UUID

import uvicorn

from geoqc_app.api import create_app
from geoqc_app.config import Settings
from geoqc_app.errors import AppError
from geoqc_app.export_worker import ExportWorker
from geoqc_app.maintenance import reconcile
from geoqc_app.service import Service
from geoqc_app.worker import Worker


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="geoqc-app")
    parser.add_argument("--config", type=Path, default=Path(".local/backend.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    sub.add_parser("bootstrap")
    expiry = sub.add_parser("expire-uploads")
    expiry.add_argument("--limit", type=int, default=100)
    maintenance = sub.add_parser("reconcile")
    maintenance.add_argument("--apply", action="store_true")
    maintenance.add_argument("--minimum-age-hours", type=float, default=24)
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8000)
    worker = sub.add_parser("worker")
    worker.add_argument("--once", action="store_true")
    export_worker = sub.add_parser("export-worker")
    export_worker.add_argument("--once", action="store_true")
    token = sub.add_parser("token")
    token.add_argument("--user-id", type=UUID, required=True)
    token.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = Settings.load(args.config)
    service = Service(settings)
    if args.command == "migrate":
        service.db.migrate()
    elif args.command == "bootstrap":
        output = args.config.parent / "credentials.json"
        with output.open("x", encoding="utf-8") as file:
            credentials = service.bootstrap()
            json.dump(credentials, file, indent=2)
        print(f"Credenciales locales escritas en {output}; vigencia de 8 horas")
    elif args.command == "token":
        with args.output.open("x", encoding="utf-8") as file:
            raw = secrets.token_urlsafe(32)
            with service.db.connect() as conn:
                row = conn.execute("SELECT id FROM app_users WHERE id=%s AND active", (args.user_id,)).fetchone()
                if row is None:
                    raise ValueError("Usuario inexistente o inactivo")
                conn.execute("INSERT INTO access_tokens(digest,user_id,expires_at) "
                             "VALUES (%s,%s,clock_timestamp()+interval '8 hours')",
                             (hashlib.sha256(raw.encode()).hexdigest(), args.user_id))
            json.dump({"user_id": str(args.user_id), "token": raw}, file)
        print(f"Token escrito en {args.output}")
    elif args.command == "serve":
        uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port)
    elif args.command == "reconcile":
        try:
            report = reconcile(service, apply=args.apply, minimum_age_seconds=args.minimum_age_hours * 3600)
        except AppError as exc:
            print(json.dumps({"code": exc.code, "message": str(exc)}, ensure_ascii=False))
            return 2
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(report, indent=2))
    elif args.command == "expire-uploads":
        try:
            count = service.expire_uploads(limit=args.limit)
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps({"expired": count}))
    else:
        runner = ExportWorker(service) if args.command == "export-worker" else Worker(service)
        if args.once:
            runner.run_once()
        else:
            while True:
                if not runner.run_once():
                    time.sleep(0.5)
    return 0
