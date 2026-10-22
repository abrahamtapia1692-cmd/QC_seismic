from __future__ import annotations

from importlib.resources import files
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from geoqc_app.config import Settings

Connection = psycopg.Connection[dict[str, Any]]
SCHEMA_VERSION = 3


class Database:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def connect(self) -> Connection:
        conn = psycopg.connect(self.settings.dsn, row_factory=dict_row, connect_timeout=5)
        conn.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(self.settings.schema)))
        conn.execute("SET statement_timeout TO '15s'")
        conn.commit()
        return conn

    def migrate(self) -> None:
        with self.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("migrate:" + self.settings.schema,))
            conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.settings.schema)))
            conn.execute("CREATE TABLE IF NOT EXISTS schema_versions (version integer PRIMARY KEY)")
            for version, filename in ((1, "001_initial.sql"), (2, "002_upload_lifecycle.sql"), (3, "003_exports.sql")):
                applied = conn.execute("SELECT 1 FROM schema_versions WHERE version=%s", (version,)).fetchone()
                if applied is None:
                    conn.execute(files("geoqc_app").joinpath("sql/" + filename).read_text(encoding="utf-8"))
                    conn.execute("INSERT INTO schema_versions VALUES (%s)", (version,))
