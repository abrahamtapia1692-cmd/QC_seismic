"""Transactional export jobs; all scientific records remain immutable."""
from __future__ import annotations

import uuid
from typing import Any, cast
from uuid import UUID

from psycopg.types.json import Jsonb

from geoqc_app.db import Connection
from geoqc_app.errors import AppError
from geoqc_app.models import ExportCreate
from geoqc_app.render_exports import MEDIA_TYPES, renderer_reference
from geoqc_app.service import Actor, Reply, Service, jsonable, one
from geoqc_app.storage import Blob


class Exports:
    def __init__(self, service: Service) -> None:
        self.service = service

    def create(self, actor: Actor, dossier_id: UUID, request: ExportCreate, key: str) -> Reply:
        service = self.service
        dossier = service.get(actor, "dossiers", dossier_id)
        project = UUID(dossier["project_id"])
        reference = renderer_reference(request.format)
        def action(conn: Connection) -> Reply:
            identifier = uuid.uuid4()
            conn.execute("INSERT INTO exports(id,project_id,dossier_id,format,renderer_reference,max_attempts) "
                         "VALUES (%s,%s,%s,%s,%s,%s)",
                         (identifier, project, dossier_id, request.format, Jsonb(reference), service.settings.max_attempts))
            service.event(conn, project, identifier, "EXPORT_PENDING", {"id": identifier, "dossier_id": dossier_id})
            return Reply({"id": identifier, "state": "PENDING", "dossier_id": dossier_id}, 202)
        # An export is a derived read: any current member allowed to read this dossier may request it.
        return service.command(actor, project, None, f"export:create:{dossier_id}", key,
                               request.model_dump(mode="json"), action)

    def retry(self, actor: Actor, export_id: UUID, key: str) -> Reply:
        service = self.service
        export = service.get(actor, "exports", export_id)
        project = UUID(export["project_id"])
        def action(conn: Connection) -> Reply:
            current = one(conn, "SELECT * FROM exports WHERE id=%s FOR UPDATE", (export_id,))
            if current["state"] != "FAILED":
                raise AppError(409, "EXPORT_NOT_FAILED", "Solo una exportación fallida admite reintento")
            if current["attempt"] >= current["max_attempts"]:
                raise AppError(409, "EXPORT_RETRIES_EXHAUSTED", "Presupuesto de intentos agotado; cree otra exportación")
            conn.execute("UPDATE exports SET state='PENDING',error_code=NULL WHERE id=%s", (export_id,))
            service.event(conn, project, export_id, "EXPORT_PENDING", {"id": export_id, "retry": True})
            return Reply({"id": export_id, "state": "PENDING"}, 202)
        return service.command(actor, project, None, f"export:retry:{export_id}", key, {}, action)

    def claim(self) -> dict[str, Any] | None:
        service = self.service
        with service.db.connect() as conn:
            row = conn.execute("SELECT * FROM exports WHERE state='PENDING' OR "
                               "(state='RUNNING' AND lease_until<clock_timestamp()) "
                               "ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1").fetchone()
            if row is None:
                return None
            if row["token"] is not None:
                conn.execute("UPDATE export_attempts SET state='EXPIRED',finished_at=clock_timestamp() WHERE token=%s",
                             (row["token"],))
            if row["attempt"] >= row["max_attempts"]:
                conn.execute("UPDATE exports SET state='FAILED',token=NULL,lease_until=NULL," 
                             "error_code='EXPORT_RETRIES_EXHAUSTED' WHERE id=%s", (row["id"],))
                service.event(conn, row["project_id"], row["id"], "EXPORT_FAILED", {"code": "EXPORT_RETRIES_EXHAUSTED"})
                return None
            token = uuid.uuid4()
            updated = one(conn, "UPDATE exports SET state='RUNNING',attempt=attempt+1,token=%s,error_code=NULL,"
                          "lease_until=clock_timestamp()+%s*interval '1 second' WHERE id=%s RETURNING *",
                          (token, service.settings.lease_seconds, row["id"]))
            conn.execute("INSERT INTO export_attempts(export_id,number,token,state) VALUES (%s,%s,%s,'ACTIVE')",
                         (row["id"], updated["attempt"], token))
            service.event(conn, row["project_id"], row["id"], "EXPORT_RUNNING", {"id": row["id"], "attempt": updated["attempt"]})
            return updated

    def heartbeat(self, export_id: UUID, token: UUID) -> bool:
        service = self.service
        with service.db.connect() as conn:
            return conn.execute("UPDATE exports SET lease_until=clock_timestamp()+%s*interval '1 second' "
                                "WHERE id=%s AND token=%s AND state='RUNNING' AND lease_until>clock_timestamp() RETURNING id",
                                (service.settings.lease_seconds, export_id, token)).fetchone() is not None

    def inputs(self, export: dict[str, Any]) -> dict[str, Any]:
        service = self.service
        with service.db.connect() as conn:
            row = one(conn, "SELECT d.scientific_digest,a.storage_key,a.sha256,a.size_bytes FROM dossiers d "
                      "JOIN artifacts a ON a.id=d.artifact_id WHERE d.id=%s", (export["dossier_id"],))
        return {"source": {"key": row["storage_key"], "sha256": row["sha256"], "size": row["size_bytes"]},
                "scientific_digest": row["scientific_digest"], "format": export["format"],
                "renderer_reference": export["renderer_reference"], "storage_root": str(service.store.root)}

    def publish(self, export_id: UUID, token: UUID, blob: Blob) -> dict[str, Any]:
        service = self.service
        with service.db.connect() as conn:
            service.storage_lock(conn)
            row = conn.execute("SELECT * FROM exports WHERE id=%s AND token=%s AND state='RUNNING' "
                               "AND lease_until>clock_timestamp() FOR UPDATE", (export_id, token)).fetchone()
            if row is None:
                raise AppError(409, "LEASE_LOST", "El intento de exportación ya no puede publicar")
            service.store.verify(blob)
            source = one(conn, "SELECT d.scientific_digest,a.* FROM dossiers d "
                         "JOIN artifacts a ON a.id=d.artifact_id WHERE d.id=%s", (row["dossier_id"],))
            service.store.verify(Blob(source["storage_key"], source["sha256"], source["size_bytes"]))
            artifact = service.insert_artifact(conn, row["project_id"], blob, "export_" + row["format"].lower())
            manifest = {"schema_version": "geoqc-export-manifest-1", "dossier_id": str(row["dossier_id"]),
                        "scientific_digest": source["scientific_digest"], "format": row["format"],
                        "renderer_reference": row["renderer_reference"],
                        "source": {"artifact_id": str(source["id"]), "sha256": source["sha256"]},
                        "artifact": {"id": str(artifact), "sha256": blob.sha256, "size_bytes": blob.size,
                                     "media_type": MEDIA_TYPES[row["format"]]}}
            updated = conn.execute("UPDATE exports SET state='READY',token=NULL,lease_until=NULL,artifact_id=%s,manifest=%s "
                                   "WHERE id=%s AND token=%s AND lease_until>clock_timestamp() RETURNING id",
                                   (artifact, Jsonb(manifest), export_id, token)).fetchone()
            if updated is None:
                raise AppError(409, "LEASE_LOST", "El lease venció antes de confirmar la exportación")
            conn.execute("UPDATE export_attempts SET state='SUCCEEDED',finished_at=clock_timestamp() WHERE token=%s",
                         (token,))
            service.event(conn, row["project_id"], export_id, "EXPORT_READY", {"id": export_id, "artifact_id": artifact})
            return cast(dict[str, Any], jsonable(manifest))

    def fail(self, export_id: UUID, token: UUID, code: str) -> bool:
        service = self.service
        with service.db.connect() as conn:
            row = conn.execute("SELECT * FROM exports WHERE id=%s AND token=%s AND state='RUNNING' "
                               "AND lease_until>clock_timestamp() FOR UPDATE", (export_id, token)).fetchone()
            if row is None:
                return False
            conn.execute("UPDATE exports SET state='FAILED',token=NULL,lease_until=NULL,error_code=%s WHERE id=%s",
                         (code, export_id))
            conn.execute("UPDATE export_attempts SET state='FAILED',error_code=%s,finished_at=clock_timestamp() WHERE token=%s",
                         (code, token))
            service.event(conn, row["project_id"], export_id, "EXPORT_FAILED", {"id": export_id, "code": code})
            return True
