from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

from geoqc.core.evidence import canonical_hash
from geoqc.masw.adapter import capture_engine_reference
from geoqc.masw.diagnostic_quality import UsabilityPolicy
from geoqc_app.config import Settings
from geoqc_app.db import Connection, Database
from geoqc_app.errors import AppError
from geoqc_app.log_context import REQUEST_ID
from geoqc_app.models import AcquisitionCreate, Reopening, ReviewWrite, RevisionCreate, RunCreate, UploadCancellation
from geoqc_app.storage import ArtifactStore, Blob

OPERATOR, REVIEWER = "FIELD_OPERATOR", "OFFICE_REVIEWER"
LOG = logging.getLogger(__name__)


def jsonable(value: Any) -> Any:
    def encode(item: Any) -> str:
        if isinstance(item, UUID):
            return str(item)
        if isinstance(item, datetime):
            return item.isoformat()
        raise TypeError("Tipo no serializable")
    return json.loads(json.dumps(value, default=encode, allow_nan=False))


@dataclass(frozen=True)
class Actor:
    id: UUID


@dataclass(frozen=True)
class Reply:
    body: dict[str, Any]
    status: int = 200
    etag: str | None = None


def one(conn: Connection, query: Any, params: Any = ()) -> dict[str, Any]:
    row = conn.execute(query, params).fetchone()
    if row is None:
        raise AppError(404, "NOT_FOUND", "Recurso no encontrado")
    return row


def etag(row: dict[str, Any]) -> str:
    return f'"review-{row["id"]}-v{row["version"]}"'


class Service:
    def __init__(self, settings: Settings) -> None:
        self.settings, self.db = settings, Database(settings)
        self.store = ArtifactStore(settings.storage_root)
        connection = conninfo_to_dict(settings.dsn)
        self.store.bind(canonical_hash({
            "schema": settings.schema,
            "connection": {key: connection.get(key, "")
                           for key in ("host", "hostaddr", "port", "dbname", "service", "user")},
        }))

    def storage_lock(self, conn: Connection, *, exclusive: bool = False) -> None:
        function = "pg_advisory_xact_lock" if exclusive else "pg_advisory_xact_lock_shared"
        conn.execute(sql.SQL("SELECT {}(hashtextextended(%s,0))").format(sql.Identifier(function)),
                     ("storage:" + str(self.store.root).casefold(),))

    def bootstrap(self) -> dict[str, Any]:
        """Explicit local-development identities; never invoked by API startup."""
        project, organization = uuid.uuid4(), uuid.uuid4()
        credentials: dict[str, Any] = {"project_id": str(project)}
        with self.db.connect() as conn:
            conn.execute("INSERT INTO organizations VALUES (%s,%s)", (organization, "Local development"))
            conn.execute("INSERT INTO projects VALUES (%s,%s,%s)", (project, organization, "MASW local"))
            conn.execute("INSERT INTO project_change_counters(project_id) VALUES (%s)", (project,))
            for name, role in (("operator", OPERATOR), ("reviewer", REVIEWER), ("admin", "PROJECT_ADMIN")):
                user, token = uuid.uuid4(), secrets.token_urlsafe(32)
                conn.execute("INSERT INTO app_users(id,name) VALUES (%s,%s)", (user, name))
                conn.execute("INSERT INTO memberships VALUES (%s,%s,%s)", (project, user, [role]))
                conn.execute(
                    "INSERT INTO access_tokens(digest,user_id,expires_at) "
                    "VALUES (%s,%s,clock_timestamp()+interval '8 hours')",
                    (hashlib.sha256(token.encode()).hexdigest(), user),
                )
                credentials[name] = {"user_id": str(user), "token": token}
        return credentials

    def authenticate(self, token: str) -> Actor:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT u.id FROM access_tokens t JOIN app_users u ON u.id=t.user_id "
                "WHERE t.digest=%s AND NOT t.revoked AND u.active AND t.expires_at>clock_timestamp()",
                (hashlib.sha256(token.encode()).hexdigest(),),
            ).fetchone()
        if row is None:
            raise AppError(401, "UNAUTHENTICATED", "Sesión inválida o vencida")
        return Actor(row["id"])

    def authorize(self, conn: Connection, actor: Actor, project: UUID, role: str | None = None) -> None:
        row = conn.execute(
            "SELECT m.roles FROM memberships m JOIN app_users u ON u.id=m.user_id "
            "WHERE m.project_id=%s AND m.user_id=%s AND u.active FOR SHARE OF m,u",
            (project, actor.id),
        ).fetchone()
        if row is None or (role is not None and role not in row["roles"]):
            raise AppError(403, "FORBIDDEN", "Operación fuera del alcance autorizado")

    def resource(self, conn: Connection, actor: Actor, table: str, resource_id: UUID) -> dict[str, Any]:
        # table is always supplied by this service, never by an HTTP parameter.
        return one(conn, sql.SQL(
            "SELECT r.* FROM {} r WHERE r.id=%s AND EXISTS "
            "(SELECT 1 FROM memberships m JOIN app_users u ON u.id=m.user_id "
            "WHERE m.project_id=r.project_id AND m.user_id=%s AND u.active)"
        ).format(sql.Identifier(table)), (resource_id, actor.id))

    def command(
        self, actor: Actor, project: UUID, role: str | None, operation: str, key: str,
        payload: Any, action: Callable[[Connection], Reply],
    ) -> Reply:
        if not key or len(key) > 128:
            raise AppError(400, "IDEMPOTENCY_KEY_REQUIRED", "Clave de idempotencia requerida (1..128 caracteres)")
        request_hash = canonical_hash(jsonable(payload))
        with self.db.connect() as conn:
            self.storage_lock(conn)
            self.authorize(conn, actor, project, role)
            scope = (actor.id, project, operation, key)
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("|".join(map(str, scope)),))
            saved = conn.execute(
                "SELECT * FROM commands WHERE actor_id=%s AND project_id=%s AND operation=%s AND key=%s", scope
            ).fetchone()
            if saved is not None:
                if saved["request_hash"] != request_hash:
                    raise AppError(409, "IDEMPOTENCY_MISMATCH", "La clave ya identifica otro comando")
                reply = Reply(saved["response"], saved["status"], saved["etag"])
            else:
                result = action(conn)
                body = jsonable(result.body)
                conn.execute("INSERT INTO commands VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                             (*scope, request_hash, Jsonb(body), result.status, result.etag))
                reply = Reply(body, result.status, result.etag)
        # Log only after commit succeeds; keys and arbitrary command text are never emitted.
        LOG.info("command_confirmed request_id=%s project=%s actor=%s operation=%s command=%s resource=%s replay=%s",
                 REQUEST_ID.get(), project, actor.id, operation, hashlib.sha256(key.encode()).hexdigest(),
                 reply.body.get("id", "-"), saved is not None)
        return reply

    def event(self, conn: Connection, project: UUID, aggregate: UUID, kind: str, payload: Any) -> None:
        conn.execute(
            "INSERT INTO outbox(id,project_id,aggregate_id,event_type,payload) VALUES (%s,%s,%s,%s,%s)",
            (uuid.uuid4(), project, aggregate, kind, Jsonb(jsonable(payload))),
        )

    def get(self, actor: Actor, table: str, resource_id: UUID) -> dict[str, Any]:
        with self.db.connect() as conn:
            return cast(dict[str, Any], jsonable(self.resource(conn, actor, table, resource_id)))

    def create_acquisition(self, actor: Actor, request: AcquisitionCreate, key: str) -> Reply:
        def action(conn: Connection) -> Reply:
            identifier = uuid.uuid4()
            conn.execute("INSERT INTO acquisitions(id,project_id,name,created_by) VALUES (%s,%s,%s,%s)",
                         (identifier, request.project_id, request.name, actor.id))
            self.event(conn, request.project_id, identifier, "ACQUISITION_CREATED", {"id": identifier})
            return Reply({"id": identifier, "project_id": request.project_id}, 201)
        return self.command(actor, request.project_id, OPERATOR, "acquisition:create", key,
                            request.model_dump(mode="json"), action)

    def create_upload(self, actor: Actor, acquisition_id: UUID, key: str) -> Reply:
        acquisition = self.get(actor, "acquisitions", acquisition_id)
        project = UUID(acquisition["project_id"])
        def action(conn: Connection) -> Reply:
            identifier = uuid.uuid4()
            row = one(conn, "INSERT INTO upload_sessions(id,project_id,acquisition_id,expires_at) "
                      "VALUES (%s,%s,%s,clock_timestamp()+%s*interval '1 second') RETURNING expires_at",
                      (identifier, project, acquisition_id, self.settings.upload_ttl_seconds))
            self.event(conn, project, identifier, "UPLOAD_CREATED", {"id": identifier})
            return Reply({"id": identifier, "state": "UPLOADING", "expires_at": row["expires_at"]}, 201)
        return self.command(actor, project, OPERATOR, f"upload:create:{acquisition_id}", key, {}, action)

    def require_open_upload(self, conn: Connection, row: dict[str, Any]) -> None:
        if row["state"] == "EXPIRED":
            raise AppError(409, "UPLOAD_EXPIRED", "La sesión de carga venció; cree otra sesión")
        if row["state"] != "UPLOADING":
            raise AppError(409, "UPLOAD_FINALIZED", "La sesión ya está cerrada")
        if not one(conn, "SELECT expires_at>clock_timestamp() AS valid FROM upload_sessions WHERE id=%s",
                   (row["id"],))["valid"]:
            raise AppError(409, "UPLOAD_EXPIRED", "La sesión de carga venció; cree otra sesión")

    def check_upload_transfer(self, actor: Actor, upload_id: UUID) -> None:
        """Admission check only; attachment revalidates after streaming the bytes."""
        with self.db.connect() as conn:
            row = self.resource(conn, actor, "upload_sessions", upload_id)
            self.authorize(conn, actor, row["project_id"], OPERATOR)
            if row["state"] != "VERIFIED":
                self.require_open_upload(conn, row)

    def cancel_upload(self, actor: Actor, upload_id: UUID, request: UploadCancellation, key: str) -> Reply:
        upload = self.get(actor, "upload_sessions", upload_id)
        project = UUID(upload["project_id"])
        def action(conn: Connection) -> Reply:
            row = one(conn, "SELECT * FROM upload_sessions WHERE id=%s FOR UPDATE", (upload_id,))
            if row["state"] == "CANCELLED":
                return Reply({"id": upload_id, "state": "CANCELLED"})
            self.require_open_upload(conn, row)
            updated = conn.execute("UPDATE upload_sessions SET state='CANCELLED',closed_at=clock_timestamp(),"
                                   "cancellation_reason=%s WHERE id=%s AND expires_at>clock_timestamp() RETURNING id",
                                   (request.reason, upload_id)).fetchone()
            if updated is None:
                raise AppError(409, "UPLOAD_EXPIRED", "La sesión de carga venció")
            self.event(conn, project, upload_id, "UPLOAD_CANCELLED", {"id": upload_id, "reason": request.reason})
            return Reply({"id": upload_id, "state": "CANCELLED"})
        return self.command(actor, project, OPERATOR, f"upload:cancel:{upload_id}", key,
                            request.model_dump(mode="json"), action)

    def expire_uploads(self, *, limit: int = 100) -> int:
        """Close a bounded batch using database time and row locks, with durable events."""
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Lote de expiración requerido entre 1 y 1000")
        with self.db.connect() as conn:
            self.storage_lock(conn)
            rows = conn.execute("SELECT * FROM upload_sessions WHERE state='UPLOADING' "
                                "AND expires_at<=clock_timestamp() ORDER BY expires_at,id "
                                "FOR UPDATE SKIP LOCKED LIMIT %s", (limit,)).fetchall()
            for row in rows:
                conn.execute("UPDATE upload_sessions SET state='EXPIRED',closed_at=clock_timestamp() WHERE id=%s",
                             (row["id"],))
                self.event(conn, row["project_id"], row["id"], "UPLOAD_EXPIRED", {"id": row["id"]})
        for row in rows:
            LOG.info("upload_expired project=%s upload=%s", row["project_id"], row["id"])
        return len(rows)

    def attach_part(self, actor: Actor, upload_id: UUID, kind: str, blob: Blob) -> Reply:
        if kind not in ("waveform", "sidecar"):
            raise AppError(404, "NOT_FOUND", "Parte no encontrada")
        with self.db.connect() as conn:
            self.storage_lock(conn)
            upload = self.resource(conn, actor, "upload_sessions", upload_id)
            self.authorize(conn, actor, upload["project_id"], OPERATOR)
            upload = one(conn, "SELECT * FROM upload_sessions WHERE id=%s FOR UPDATE", (upload_id,))
            if upload["state"] != "VERIFIED":
                self.require_open_upload(conn, upload)
            self.store.verify(blob)
            if upload["state"] != "VERIFIED":
                self.require_open_upload(conn, upload)
            previous = upload[kind + "_id"]
            if previous is not None:
                artifact = one(conn, "SELECT * FROM artifacts WHERE id=%s", (previous,))
                if artifact["sha256"] == blob.sha256 and artifact["size_bytes"] == blob.size:
                    return Reply({"artifact_id": previous, "sha256": blob.sha256, "size_bytes": blob.size})
            if upload["state"] != "UPLOADING":
                raise AppError(409, "UPLOAD_FINALIZED", "La sesión ya está cerrada")
            identifier = self.insert_artifact(conn, upload["project_id"], blob, kind)
            updated = conn.execute(sql.SQL("UPDATE upload_sessions SET {}=%s WHERE id=%s "
                                           "AND expires_at>clock_timestamp() RETURNING id").format(
                sql.Identifier(kind + "_id")), (identifier, upload_id)).fetchone()
            if updated is None:
                raise AppError(409, "UPLOAD_EXPIRED", "La sesión de carga venció")
            return Reply({"artifact_id": identifier, "sha256": blob.sha256, "size_bytes": blob.size})

    def insert_artifact(self, conn: Connection, project: UUID, blob: Blob, kind: str) -> UUID:
        identifier = uuid.uuid4()
        conn.execute("INSERT INTO artifacts(id,project_id,storage_key,sha256,size_bytes,kind) "
                     "VALUES (%s,%s,%s,%s,%s,%s)",
                     (identifier, project, blob.key, blob.sha256, blob.size, kind))
        return identifier

    def complete_upload(self, actor: Actor, upload_id: UUID, key: str) -> Reply:
        upload = self.get(actor, "upload_sessions", upload_id)
        project = UUID(upload["project_id"])
        def action(conn: Connection) -> Reply:
            row = one(conn, "SELECT * FROM upload_sessions WHERE id=%s FOR UPDATE", (upload_id,))
            if row["state"] == "VERIFIED":
                return Reply({"id": upload_id, "state": "VERIFIED"})
            self.require_open_upload(conn, row)
            if row["state"] != "UPLOADING" or row["waveform_id"] is None or row["sidecar_id"] is None:
                raise AppError(409, "UPLOAD_INCOMPLETE", "Se requieren waveform y sidecar")
            for part in ("waveform_id", "sidecar_id"):
                artifact = one(conn, "SELECT * FROM artifacts WHERE id=%s", (row[part],))
                self.store.verify(Blob(artifact["storage_key"], artifact["sha256"], artifact["size_bytes"]))
            updated = conn.execute("UPDATE upload_sessions SET state='VERIFIED',closed_at=clock_timestamp() "
                                   "WHERE id=%s AND expires_at>clock_timestamp() RETURNING id", (upload_id,)).fetchone()
            if updated is None:
                raise AppError(409, "UPLOAD_EXPIRED", "La sesión de carga venció")
            self.event(conn, project, upload_id, "UPLOAD_VERIFIED", {"id": upload_id})
            return Reply({"id": upload_id, "state": "VERIFIED"})
        return self.command(actor, project, OPERATOR, f"upload:complete:{upload_id}", key, {}, action)

    def create_revision(self, actor: Actor, acquisition_id: UUID, request: RevisionCreate, key: str) -> Reply:
        acquisition = self.get(actor, "acquisitions", acquisition_id)
        project = UUID(acquisition["project_id"])
        def action(conn: Connection) -> Reply:
            row = one(conn, "SELECT * FROM acquisitions WHERE id=%s FOR UPDATE", (acquisition_id,))
            for identifier in request.uploads:
                upload = self.resource(conn, actor, "upload_sessions", identifier)
                if upload["acquisition_id"] != acquisition_id or upload["state"] != "VERIFIED":
                    raise AppError(409, "INVALID_REVISION_INPUT", "Sesión incompatible o no verificada")
            identifier, number = uuid.uuid4(), row["revision_number"] + 1
            conn.execute("INSERT INTO acquisition_revisions(id,project_id,acquisition_id,number,uploads) "
                         "VALUES (%s,%s,%s,%s,%s)",
                         (identifier, project, acquisition_id, number, Jsonb(list(map(str, request.uploads)))))
            conn.execute("UPDATE acquisitions SET revision_number=%s,current_run_id=NULL WHERE id=%s",
                         (number, acquisition_id))
            self.event(conn, project, identifier, "REVISION_CREATED", {"id": identifier, "number": number})
            return Reply({"id": identifier, "number": number}, 201)
        return self.command(actor, project, OPERATOR, f"revision:create:{acquisition_id}", key,
                            request.model_dump(mode="json"), action)

    def create_run(self, actor: Actor, request: RunCreate, key: str) -> Reply:
        revision = self.get(actor, "acquisition_revisions", request.revision_id)
        project = UUID(revision["project_id"])
        reference = capture_engine_reference().model_dump(mode="json")
        specification = request.model_dump(mode="json") | {
            "engine_reference": reference
        }
        if request.technique == "MASW":
            specification["usability_policy"] = UsabilityPolicy().model_dump(mode="json")
        def action(conn: Connection) -> Reply:
            acquisition = one(conn, "SELECT * FROM acquisitions WHERE id=%s FOR UPDATE",
                              (UUID(revision["acquisition_id"]),))
            if acquisition["revision_number"] != revision["number"]:
                raise AppError(409, "REVISION_SUPERSEDED", "La revisión ya no es vigente")
            if request.technique == "MASW" and len(request.excluded_receiver_ids) != len(revision["uploads"]):
                raise AppError(422, "EXCLUSIONS_MISMATCH", "Una exclusión por tiro requerida")
            identifier = uuid.uuid4()
            conn.execute("INSERT INTO processing_runs(id,project_id,acquisition_id,revision_id,specification,max_attempts) "
                         "VALUES (%s,%s,%s,%s,%s,%s)",
                         (identifier, project, acquisition["id"], request.revision_id,
                          Jsonb(specification), self.settings.max_attempts))
            conn.execute("UPDATE acquisitions SET current_run_id=%s WHERE id=%s", (identifier, acquisition["id"]))
            self.event(conn, project, identifier, "RUN_QUEUED", {"id": identifier})
            return Reply({"id": identifier, "state": "QUEUED"}, 202)
        return self.command(actor, project, OPERATOR, "run:create", key, request.model_dump(mode="json"), action)

    def review(self, actor: Actor, review_id: UUID) -> Reply:
        with self.db.connect() as conn:
            row = self.resource(conn, actor, "review_cases", review_id)
            dossier = one(conn, "SELECT scientific_digest FROM dossiers WHERE id=%s", (row["dossier_id"],))
            history = conn.execute("SELECT actor_id,action,content,version,decided_at FROM review_history "
                                   "WHERE review_id=%s ORDER BY version", (review_id,)).fetchall()
        body = jsonable(row | dossier | {"history": history})
        body["version"] = str(row["version"])
        for entry in body["history"]:
            entry["version"] = str(entry["version"])
        return Reply(body, etag=etag(row))

    def write_review(self, actor: Actor, review_id: UUID, request: ReviewWrite, expected_etag: str, key: str) -> Reply:
        row = self.get(actor, "review_cases", review_id)
        project = UUID(row["project_id"])
        def action(conn: Connection) -> Reply:
            dossier = one(conn, "SELECT d.*,r.acquisition_id,r.revision_id FROM dossiers d "
                          "JOIN processing_runs r ON r.id=d.run_id WHERE d.id=%s", (UUID(row["dossier_id"]),))
            acquisition = one(conn, "SELECT * FROM acquisitions WHERE id=%s FOR UPDATE", (dossier["acquisition_id"],))
            current = one(conn, "SELECT * FROM review_cases WHERE id=%s FOR UPDATE", (review_id,))
            if etag(current) != expected_etag:
                raise AppError(412, "VERSION_MISMATCH", "La revisión cambió", current_version=str(current["version"]))
            if current["state"] != "PENDING":
                raise AppError(409, "REVIEW_DECIDED", "Se requiere reapertura explícita")
            if acquisition["current_run_id"] != dossier["run_id"]:
                raise AppError(409, "RESULT_SUPERSEDED", "El resultado ya no es vigente")
            if request.scientific_digest != dossier["scientific_digest"]:
                raise AppError(409, "DIGEST_MISMATCH", "El dictamen no identifica este resultado")
            updated = one(conn, "UPDATE review_cases SET version=version+1,state='DECIDED' "
                          "WHERE id=%s AND version=%s RETURNING *", (review_id, current["version"]))
            content = request.model_dump(mode="json")
            conn.execute("INSERT INTO review_history(id,project_id,review_id,version,actor_id,action,content) "
                         "VALUES (%s,%s,%s,%s,%s,'DECIDED',%s)",
                         (uuid.uuid4(), project, review_id, updated["version"], actor.id, Jsonb(content)))
            self.event(conn, project, review_id, "REVIEW_DECIDED",
                       {"id": review_id, "version": str(updated["version"]), "verdict": request.verdict})
            return Reply({"id": review_id, "version": str(updated["version"]), "state": "DECIDED"}, etag=etag(updated))
        return self.command(actor, project, REVIEWER, f"review:write:{review_id}", key,
                            request.model_dump(mode="json") | {"if_match": expected_etag}, action)

    def reopen(self, actor: Actor, review_id: UUID, request: Reopening, key: str) -> Reply:
        row = self.get(actor, "review_cases", review_id)
        project = UUID(row["project_id"])
        def action(conn: Connection) -> Reply:
            current = one(conn, "SELECT * FROM review_cases WHERE id=%s FOR UPDATE", (review_id,))
            if current["version"] != int(request.expected_version):
                raise AppError(409, "VERSION_MISMATCH", "La revisión cambió")
            if current["state"] != "DECIDED":
                raise AppError(409, "REVIEW_NOT_DECIDED", "El caso no requiere reapertura")
            updated = one(conn, "UPDATE review_cases SET version=version+1,state='PENDING' WHERE id=%s RETURNING *",
                          (review_id,))
            conn.execute("INSERT INTO review_history(id,project_id,review_id,version,actor_id,action,content) "
                         "VALUES (%s,%s,%s,%s,%s,'REOPENED',%s)",
                         (uuid.uuid4(), project, review_id, updated["version"], actor.id,
                          Jsonb(request.model_dump(mode="json"))))
            self.event(conn, project, review_id, "REVIEW_REOPENED", {"id": review_id, "version": str(updated["version"])})
            return Reply({"id": review_id, "version": str(updated["version"]), "state": "PENDING"}, etag=etag(updated))
        return self.command(actor, project, REVIEWER, f"review:reopen:{review_id}", key,
                            request.model_dump(mode="json"), action)

    def claim(self) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM processing_runs WHERE ((state IN ('QUEUED','RETRY_WAIT') "
                "AND available_at<=clock_timestamp()) OR (state IN ('VALIDATING','RUNNING') "
                "AND lease_until<clock_timestamp())) ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            if row["token"] is not None:
                conn.execute("UPDATE processing_attempts SET state='EXPIRED',finished_at=clock_timestamp() "
                             "WHERE token=%s", (row["token"],))
            if row["attempt"] >= row["max_attempts"]:
                conn.execute("UPDATE processing_runs SET state='FAILED',error_code='RETRIES_EXHAUSTED',token=NULL," 
                             "lease_until=NULL WHERE id=%s", (row["id"],))
                self.event(conn, row["project_id"], row["id"], "RUN_FAILED", {"code": "RETRIES_EXHAUSTED"})
                return None
            token = uuid.uuid4()
            updated = one(conn, "UPDATE processing_runs SET state='VALIDATING',attempt=attempt+1,token=%s," 
                          "lease_until=clock_timestamp()+%s*interval '1 second',error_code=NULL "
                          "WHERE id=%s RETURNING *", (token, self.settings.lease_seconds, row["id"]))
            conn.execute("INSERT INTO processing_attempts(run_id,number,token,state) VALUES (%s,%s,%s,'ACTIVE')",
                         (row["id"], updated["attempt"], token))
            self.event(conn, row["project_id"], row["id"], "RUN_CLAIMED", {"attempt": updated["attempt"]})
            return updated

    def heartbeat(self, run_id: UUID, token: UUID, *, running: bool = False) -> bool:
        with self.db.connect() as conn:
            return conn.execute(
                "UPDATE processing_runs SET lease_until=clock_timestamp()+%s*interval '1 second',"
                "state=CASE WHEN %s THEN 'RUNNING' ELSE state END WHERE id=%s AND token=%s "
                "AND state IN ('VALIDATING','RUNNING') AND lease_until>clock_timestamp() RETURNING id",
                (self.settings.lease_seconds, running, run_id, token),
            ).fetchone() is not None

    def execution_inputs(self, run: dict[str, Any]) -> dict[str, Any]:
        with self.db.connect() as conn:
            revision = one(conn, "SELECT * FROM acquisition_revisions WHERE id=%s", (run["revision_id"],))
            shots = []
            for upload_id in revision["uploads"]:
                upload = one(conn, "SELECT * FROM upload_sessions WHERE id=%s", (UUID(upload_id),))
                parts = {}
                for kind in ("waveform", "sidecar"):
                    artifact = one(conn, "SELECT * FROM artifacts WHERE id=%s", (upload[kind + "_id"],))
                    parts[kind] = {"key": artifact["storage_key"], "sha256": artifact["sha256"],
                                   "size": artifact["size_bytes"]}
                shots.append(parts)
        return cast(dict[str, Any], jsonable({"run_id": run["id"], "revision_id": run["revision_id"],
                         "specification": run["specification"], "shots": shots,
                         "storage_root": str(self.settings.storage_root)}))

    def publish(self, run_id: UUID, token: UUID, document: dict[str, Any], blob: Blob) -> dict[str, Any]:
        scientific_digest = document["scientific_digest"]
        if canonical_hash({k: v for k, v in document.items() if k != "scientific_digest"}) != scientific_digest:
            raise AppError(409, "INVALID_DOSSIER", "Digest científico incompatible")
        if document["eligible_for_acceptance"] is not False or document["sufficiency"] != {"status": "NOT_DEMONSTRATED"}:
            raise AppError(409, "INVALID_DOSSIER", "El perfil local es diagnóstico")
        with self.db.connect() as conn:
            self.storage_lock(conn)
            path = self.store.verify(blob)
            if json.loads(path.read_bytes()) != document:
                raise AppError(409, "INVALID_DOSSIER", "El artefacto no corresponde al documento publicado")
            initial = one(conn, "SELECT acquisition_id FROM processing_runs WHERE id=%s", (run_id,))
            one(conn, "SELECT id FROM acquisitions WHERE id=%s FOR UPDATE", (initial["acquisition_id"],))
            run = conn.execute("SELECT * FROM processing_runs WHERE id=%s AND token=%s "
                               "AND state IN ('VALIDATING','RUNNING') AND lease_until>clock_timestamp() FOR UPDATE",
                               (run_id, token)).fetchone()
            if run is None:
                raise AppError(409, "LEASE_LOST", "El intento ya no puede publicar")
            if document["acquisition_revision_id"] != str(run["revision_id"]):
                raise AppError(409, "INVALID_DOSSIER", "Revisión de entrada incompatible")
            technique = run["specification"].get("technique", "MASW")
            if document.get("method") != technique or document.get("schema_version") != (
                    "app-trs-dossier-0.1" if technique == "TRS" else "app-masw-dossier-0.1"):
                raise AppError(409, "INVALID_DOSSIER", "Dosier incompatible con la técnica solicitada")
            artifact_id = self.insert_artifact(conn, run["project_id"], blob, "scientific_json")
            dossier_id, review_id = uuid.uuid4(), uuid.uuid4()
            manifest = {"artifacts": [{"id": str(artifact_id), "sha256": blob.sha256,
                                       "size_bytes": blob.size, "kind": "scientific_json"}]}
            conn.execute("INSERT INTO dossiers(id,project_id,run_id,artifact_id,scientific_digest,manifest) "
                         "VALUES (%s,%s,%s,%s,%s,%s)",
                         (dossier_id, run["project_id"], run_id, artifact_id, scientific_digest, Jsonb(manifest)))
            conn.execute("INSERT INTO review_cases(id,project_id,dossier_id) VALUES (%s,%s,%s)",
                         (review_id, run["project_id"], dossier_id))
            conn.execute("UPDATE processing_runs SET state='SUCCEEDED',dossier_id=%s,token=NULL,lease_until=NULL "
                         "WHERE id=%s", (dossier_id, run_id))
            conn.execute("UPDATE processing_attempts SET state='SUCCEEDED',finished_at=clock_timestamp() "
                         "WHERE token=%s", (token,))
            self.event(conn, run["project_id"], run_id, "DOSSIER_PUBLISHED",
                       {"run_id": run_id, "dossier_id": dossier_id, "review_id": review_id})
            return {"dossier_id": dossier_id, "review_id": review_id}

    def fail(self, run_id: UUID, token: UUID, code: str, *, transient: bool) -> bool:
        with self.db.connect() as conn:
            run = conn.execute("SELECT * FROM processing_runs WHERE id=%s AND token=%s "
                               "AND state IN ('VALIDATING','RUNNING') AND lease_until>clock_timestamp() FOR UPDATE",
                               (run_id, token)).fetchone()
            if run is None:
                return False
            retry = transient and run["attempt"] < run["max_attempts"]
            state = "RETRY_WAIT" if retry else "FAILED"
            conn.execute("UPDATE processing_runs SET state=%s,error_code=%s,token=NULL,lease_until=NULL," 
                         "available_at=clock_timestamp()+%s*interval '1 second' WHERE id=%s",
                         (state, code, min(2**run["attempt"], 60), run_id))
            conn.execute("UPDATE processing_attempts SET state=%s,error_code=%s,finished_at=clock_timestamp() "
                         "WHERE token=%s", (state, code, token))
            self.event(conn, run["project_id"], run_id, "RUN_" + state, {"code": code})
            return True

    def cancel(self, actor: Actor, run_id: UUID, key: str) -> Reply:
        row = self.get(actor, "processing_runs", run_id)
        project = UUID(row["project_id"])
        def action(conn: Connection) -> Reply:
            run = one(conn, "SELECT * FROM processing_runs WHERE id=%s FOR UPDATE", (run_id,))
            if run["state"] in ("SUCCEEDED", "FAILED"):
                raise AppError(409, "RUN_TERMINAL", "La ejecución ya terminó")
            conn.execute("UPDATE processing_runs SET state='CANCELLED',token=NULL,lease_until=NULL WHERE id=%s", (run_id,))
            if run["token"] is not None:
                conn.execute("UPDATE processing_attempts SET state='CANCELLED',finished_at=clock_timestamp() "
                             "WHERE token=%s", (run["token"],))
            self.event(conn, project, run_id, "RUN_CANCELLED", {"id": run_id})
            return Reply({"id": run_id, "state": "CANCELLED"})
        return self.command(actor, project, OPERATOR, f"run:cancel:{run_id}", key, {}, action)

    def dispatch_one(self) -> bool:
        with self.db.connect() as conn:
            event = conn.execute("SELECT * FROM outbox WHERE dispatched_at IS NULL ORDER BY created_at,id "
                                 "FOR UPDATE SKIP LOCKED LIMIT 1").fetchone()
            if event is None:
                return False
            # This row lock serializes sequence allocation AND commit per project.
            counter = one(conn, "UPDATE project_change_counters SET sequence=sequence+1 "
                          "WHERE project_id=%s RETURNING sequence", (event["project_id"],))
            conn.execute("INSERT INTO change_entries VALUES (%s,%s,%s,%s,%s)",
                         (event["project_id"], counter["sequence"], event["id"], event["event_type"], Jsonb(event["payload"])))
            conn.execute("UPDATE outbox SET dispatched_at=clock_timestamp() WHERE id=%s", (event["id"],))
            return True

    def changes(self, actor: Actor, project: UUID, cursor: str | None, limit: int) -> dict[str, Any]:
        after = 0
        if cursor:
            try:
                decoded = json.loads(base64.urlsafe_b64decode(cursor))
                after = int(decoded["sequence"])
                if decoded["project"] != str(project) or not 0 <= after < 2**63:
                    raise ValueError
            except (ValueError, KeyError, TypeError) as exc:
                raise AppError(422, "INVALID_CURSOR", "Cursor incompatible") from exc
        with self.db.connect() as conn:
            self.authorize(conn, actor, project)
            current = one(conn, "SELECT sequence FROM project_change_counters WHERE project_id=%s", (project,))
            if after > current["sequence"]:
                raise AppError(409, "CURSOR_AHEAD", "Cursor posterior al estado confirmado")
            rows = conn.execute("SELECT sequence,event_id,event_type,payload FROM change_entries "
                                "WHERE project_id=%s AND sequence>%s ORDER BY sequence LIMIT %s",
                                (project, after, limit)).fetchall()
        last = rows[-1]["sequence"] if rows else after
        next_cursor = base64.urlsafe_b64encode(json.dumps({"project": str(project), "sequence": str(last)}).encode()).decode()
        return {"changes": jsonable(rows), "cursor": next_cursor}
