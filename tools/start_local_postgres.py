"""Start an isolated workspace cluster using installed PostgreSQL binaries."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin", type=Path, default=Path("C:/Program Files/PostgreSQL/18/bin"))
    parser.add_argument("--port", type=int, default=55432)
    args = parser.parse_args()
    local = ROOT / ".local"
    local.mkdir(exist_ok=True)
    cluster = local / "postgres"
    cluster.mkdir(exist_ok=True)
    secret_path = cluster / "connection.json"
    if secret_path.exists():
        secret = json.loads(secret_path.read_bytes())
        if secret["port"] != args.port:
            raise ValueError("El cluster ya tiene otro puerto configurado")
    else:
        secret = {"password": secrets.token_urlsafe(32), "port": args.port}
        secret_path.write_text(json.dumps(secret), encoding="utf-8")
        os.chmod(secret_path, 0o600)
    password_file = cluster / "init-password.txt"
    data = cluster / "data"
    if not (data / "PG_VERSION").exists():
        password_file.write_text(secret["password"], encoding="utf-8")
        os.chmod(password_file, 0o600)
        try:
            subprocess.run([str(args.bin / "initdb.exe"), "-D", str(data), "-U", "geoqc_local",
                            "--encoding=UTF8", "--locale=C", "--auth=scram-sha-256",
                            "--pwfile", str(password_file)], check=True)
        finally:
            password_file.unlink(missing_ok=True)
    ctl = str(args.bin / "pg_ctl.exe")
    state = subprocess.run([ctl, "-D", str(data), "status"], capture_output=True, check=False)
    if state.returncode:
        subprocess.run([ctl, "-D", str(data), "-l", str(cluster / "postgres.log"),
                        "-o", f"-h 127.0.0.1 -p {args.port}", "-w", "-t", "20", "start"], check=True)
    common = {"host": "127.0.0.1", "port": args.port, "user": "geoqc_local", "password": secret["password"]}
    with psycopg.connect(make_conninfo(**common, dbname="postgres"), autocommit=True) as conn:
        if conn.execute("SELECT 1 FROM pg_database WHERE datname='geoqc_local'").fetchone() is None:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier("geoqc_local")))
    config = local / "backend.json"
    if not config.exists():
        config.write_text(json.dumps({"dsn": make_conninfo(**common, dbname="geoqc_local"),
                                      "storage_root": str(local / "artifacts")}, indent=2), encoding="utf-8")
        os.chmod(config, 0o600)
    print(f"Instancia local disponible en 127.0.0.1:{args.port}; configuración: {config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
