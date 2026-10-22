import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from importlib.resources import files
from typing import Annotated, Any, Literal, TypeAlias
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from geoqc_app.config import Settings
from geoqc_app.db import SCHEMA_VERSION
from geoqc_app.dossiers import Dossiers, not_modified
from geoqc_app.errors import AppError
from geoqc_app.exports import Exports
from geoqc_app.log_context import REQUEST_ID
from geoqc_app.models import (
    AcquisitionCreate,
    ExportCreate,
    Reopening,
    ReviewWrite,
    RevisionCreate,
    RunCreate,
    UploadCancellation,
    UploadCreate,
)
from geoqc_app.render_exports import MEDIA_TYPES, render_export
from geoqc_app.service import Actor, Reply, Service, jsonable, one
from geoqc_app.storage import Blob

LOG = logging.getLogger(__name__)


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="GeoQC local diagnostic API", version="0.1")
    service = Service(settings)
    exports = Exports(service)
    dossiers = Dossiers(service)
    app.state.service = service
    bearer = HTTPBearer(auto_error=False)

    @app.middleware("http")
    async def request_id(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request.state.request_id = uuid.uuid4().hex
        token = REQUEST_ID.set(request.state.request_id)
        started = time.monotonic()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request.state.request_id
            response.headers["Cache-Control"] = "private, no-cache"
            LOG.info("http_completed request_id=%s method=%s route=%s status=%s duration_ms=%.1f",
                     request.state.request_id, request.method, getattr(request.scope.get("route"), "path", "-"),
                     response.status_code, (time.monotonic() - started) * 1000)
            return response
        finally:
            REQUEST_ID.reset(token)

    @app.exception_handler(AppError)
    async def application_error(request: Request, exc: AppError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else {}
        return JSONResponse(status_code=exc.status, headers=headers, content={
            "code": exc.code, "message": str(exc), "request_id": request.state.request_id,
            "details": exc.details,
        })

    @app.exception_handler(psycopg.Error)
    async def database_error(request: Request, exc: psycopg.Error) -> JSONResponse:
        LOG.error("database_failure request_id=%s sqlstate=%s", request.state.request_id, exc.sqlstate)
        return JSONResponse(status_code=503, content={
            "code": "DATABASE_UNAVAILABLE", "message": "Operación no confirmada; reintente con la misma clave",
            "request_id": request.state.request_id,
        })

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={
            "code": "INVALID_REQUEST", "message": "Solicitud incompatible con el contrato",
            "request_id": request.state.request_id,
            "details": {"fields": [{"location": list(error["loc"]), "type": error["type"]}
                                   for error in exc.errors()]},
        })

    @app.exception_handler(OSError)
    async def storage_error(request: Request, exc: OSError) -> JSONResponse:
        LOG.error("storage_failure request_id=%s errno=%s", request.state.request_id, exc.errno)
        return JSONResponse(status_code=503, content={
            "code": "STORAGE_UNAVAILABLE", "message": "Almacenamiento local no disponible",
            "request_id": request.state.request_id,
        })

    def actor(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> Actor:
        if credentials is None:
            raise AppError(401, "UNAUTHENTICATED", "Autenticación requerida")
        return service.authenticate(credentials.credentials)

    def key(value: Annotated[str | None, Header(alias="Idempotency-Key")] = None) -> str:
        if not value or len(value) > 128:
            raise AppError(400, "IDEMPOTENCY_KEY_REQUIRED", "Clave de idempotencia requerida (1..128 caracteres)")
        return value

    CurrentActor: TypeAlias = Annotated[Actor, Depends(actor)]
    CommandKey: TypeAlias = Annotated[str, Depends(key)]

    def response(reply: Reply) -> JSONResponse:
        return JSONResponse(jsonable(reply.body), status_code=reply.status,
                            headers={"ETag": reply.etag} if reply.etag else {})

    def conditional(reply: Reply, if_none_match: str | None) -> Response:
        if not_modified(if_none_match, reply.etag):
            return Response(status_code=304, headers={"ETag": reply.etag} if reply.etag else {})
        return response(reply)

    @app.get("/health")
    def health() -> dict[str, str]:
        with service.db.connect() as conn:
            if one(conn, "SELECT max(version) AS version FROM schema_versions")["version"] != SCHEMA_VERSION:
                raise AppError(503, "SCHEMA_NOT_READY", "Se requieren migraciones del backend")
        return {"status": "ok", "scope": "LOCAL_DIAGNOSTIC_ONLY"}

    @app.post("/v1/acquisitions")
    def create_acquisition(body: AcquisitionCreate, who: CurrentActor, command_key: CommandKey) -> JSONResponse:
        return response(service.create_acquisition(who, body, command_key))

    @app.post("/v1/upload-sessions")
    def create_upload(body: UploadCreate, who: CurrentActor, command_key: CommandKey) -> JSONResponse:
        return response(service.create_upload(who, body.acquisition_id, command_key))

    @app.get("/v1/upload-sessions/{identifier}")
    def get_upload(identifier: UUID, who: CurrentActor) -> dict[str, Any]:
        return service.get(who, "upload_sessions", identifier)

    @app.put("/v1/upload-sessions/{identifier}/{kind}")
    async def upload_part(identifier: UUID, kind: str, request: Request, who: CurrentActor) -> JSONResponse:
        if kind not in ("waveform", "sidecar"):
            raise AppError(404, "NOT_FOUND", "Parte no encontrada")
        await run_in_threadpool(service.check_upload_transfer, who, identifier)
        limit = 32 * 1024**2 if kind == "waveform" else 1024**2
        writer = await run_in_threadpool(service.store.begin, limit)
        try:
            async for chunk in request.stream():
                await run_in_threadpool(writer.write, chunk)
            blob = await run_in_threadpool(writer.finish)
        except BaseException:
            await run_in_threadpool(writer.abort)
            raise
        return response(await run_in_threadpool(service.attach_part, who, identifier, kind, blob))

    @app.post("/v1/upload-sessions/{identifier}/complete")
    def complete_upload(identifier: UUID, who: CurrentActor, command_key: CommandKey) -> JSONResponse:
        return response(service.complete_upload(who, identifier, command_key))

    @app.post("/v1/upload-sessions/{identifier}/cancellations")
    def cancel_upload(identifier: UUID, body: UploadCancellation, who: CurrentActor,
                      command_key: CommandKey) -> JSONResponse:
        return response(service.cancel_upload(who, identifier, body, command_key))

    @app.post("/v1/acquisitions/{identifier}/revisions")
    def create_revision(identifier: UUID, body: RevisionCreate, who: CurrentActor, command_key: CommandKey) -> JSONResponse:
        return response(service.create_revision(who, identifier, body, command_key))

    @app.post("/v1/processing-runs")
    def create_run(body: RunCreate, who: CurrentActor, command_key: CommandKey) -> JSONResponse:
        return response(service.create_run(who, body, command_key))

    @app.get("/v1/processing-runs/{identifier}")
    def get_run(identifier: UUID, who: CurrentActor) -> dict[str, Any]:
        row = service.get(who, "processing_runs", identifier)
        return {name: row[name] for name in (
            "id", "project_id", "revision_id", "state", "attempt", "error_code", "dossier_id", "created_at"
        )}

    @app.post("/v1/processing-runs/{identifier}/cancellations")
    def cancel(identifier: UUID, who: CurrentActor, command_key: CommandKey) -> JSONResponse:
        return response(service.cancel(who, identifier, command_key))

    @app.get("/v1/dossiers/{identifier}")
    def get_dossier(identifier: UUID, who: CurrentActor,
                    if_none_match: Annotated[str | None, Header()] = None) -> Response:
        return conditional(dossiers.header(who, identifier), if_none_match)

    @app.get("/v1/dossiers/{identifier}/quality-report")
    def quality_report(identifier: UUID, who: CurrentActor) -> Response:
        _, document, _ = dossiers.load(who, identifier)
        if document.get("method") != "TRS" or not all(
                r.get("trace_qc") for r in document["diagnostic_quality"]):
            raise AppError(409, "TRACE_QC_NOT_INCLUDED", "Este dosier no contiene QC por traza; abra el resultado de una ejecución con QC")
        content = render_export(document, "HTML")
        if len(content) > 64 * 1024**2:
            raise AppError(413, "QUALITY_REPORT_TOO_LARGE", "Informe excede el límite local de 64 MiB")
        return Response(content, media_type="text/html", headers={
            "Content-Disposition": 'inline; filename="geoqc-trs-quality.html"'})

    @app.get("/v1/dossiers/{identifier}/records")
    def dossier_records(identifier: UUID, who: CurrentActor,
                        cursor: Annotated[str | None, Query(max_length=2048)] = None,
                        limit: Annotated[int, Query(ge=1, le=100)] = 50,
                        offset: Annotated[int | None, Query(deprecated=True)] = None,
                        if_none_match: Annotated[str | None, Header()] = None) -> Response:
        if offset is not None:
            raise AppError(422, "OFFSET_PAGINATION_REMOVED", "Use next_cursor; offset ya no está soportado")
        return conditional(dossiers.page(who, identifier, cursor=cursor, limit=limit), if_none_match)

    @app.get("/v1/dossiers/{identifier}/records/{record_index}/{collection}")
    def record_details(identifier: UUID, record_index: int,
                       collection: Literal["points", "bands", "traces", "native-points", "arrivals", "branches", "qc-traces"],
                       who: CurrentActor,
                       cursor: Annotated[str | None, Query(max_length=2048)] = None,
                       limit: Annotated[int, Query(ge=1, le=100)] = 50,
                       direction: int | None = None, frequency_min_hz: float | None = None,
                       frequency_max_hz: float | None = None,
                       if_none_match: Annotated[str | None, Header()] = None) -> Response:
        return conditional(dossiers.page(who, identifier, collection=collection, record_index=record_index,
                                         cursor=cursor, limit=limit, direction=direction,
                                         frequency_min_hz=frequency_min_hz, frequency_max_hz=frequency_max_hz), if_none_match)

    @app.get("/v1/artifacts/{identifier}/content")
    def artifact_content(identifier: UUID, who: CurrentActor) -> FileResponse:
        with service.db.connect() as conn:
            artifact = service.resource(conn, who, "artifacts", identifier)
        path = service.store.verify(Blob(artifact["storage_key"], artifact["sha256"], artifact["size_bytes"]))
        return FileResponse(path, media_type="application/octet-stream", filename=str(identifier))

    @app.post("/v1/dossiers/{identifier}/exports")
    def create_export(identifier: UUID, body: ExportCreate, who: CurrentActor, command_key: CommandKey) -> JSONResponse:
        return response(exports.create(who, identifier, body, command_key))

    @app.get("/v1/exports/{identifier}")
    def get_export(identifier: UUID, who: CurrentActor) -> dict[str, Any]:
        row = service.get(who, "exports", identifier)
        return {name: row[name] for name in (
            "id", "project_id", "dossier_id", "format", "state", "attempt", "max_attempts", "error_code",
            "artifact_id", "manifest", "renderer_reference", "created_at"
        )}

    @app.post("/v1/exports/{identifier}/retries")
    def retry_export(identifier: UUID, who: CurrentActor, command_key: CommandKey) -> JSONResponse:
        return response(exports.retry(who, identifier, command_key))

    @app.get("/v1/exports/{identifier}/content")
    def export_content(identifier: UUID, who: CurrentActor) -> FileResponse:
        with service.db.connect() as conn:
            row = service.resource(conn, who, "exports", identifier)
            if row["state"] != "READY":
                raise AppError(409, "EXPORT_NOT_READY", "La exportación todavía no está lista")
            artifact = one(conn, "SELECT * FROM artifacts WHERE id=%s", (row["artifact_id"],))
        path = service.store.verify(Blob(artifact["storage_key"], artifact["sha256"], artifact["size_bytes"]))
        return FileResponse(path, media_type=MEDIA_TYPES[row["format"]],
                            filename="geoqc-" + str(identifier) + "." + row["format"].lower())

    @app.get("/v1/review-cases/{identifier}")
    def get_review(identifier: UUID, who: CurrentActor,
                   if_none_match: Annotated[str | None, Header()] = None) -> Response:
        reply = service.review(who, identifier)
        if reply.etag is not None and if_none_match == reply.etag:
            return Response(status_code=304, headers={"ETag": reply.etag})
        return response(reply)

    @app.put("/v1/review-cases/{identifier}")
    def write_review(identifier: UUID, body: ReviewWrite, who: CurrentActor, command_key: CommandKey,
                     if_match: Annotated[str | None, Header()] = None) -> JSONResponse:
        if if_match is None:
            raise AppError(428, "PRECONDITION_REQUIRED", "If-Match requerido")
        return response(service.write_review(who, identifier, body, if_match, command_key))

    @app.post("/v1/review-cases/{identifier}/reopenings")
    def reopen(identifier: UUID, body: Reopening, who: CurrentActor, command_key: CommandKey) -> JSONResponse:
        return response(service.reopen(who, identifier, body, command_key))

    @app.get("/v1/projects/{identifier}/changes")
    def changes(identifier: UUID, who: CurrentActor, cursor: str | None = None,
                limit: Annotated[int, Query(ge=1, le=100)] = 50) -> dict[str, Any]:
        return service.changes(who, identifier, cursor, limit)

    # Public application shell; every data route above still authenticates its actor.
    app.mount("/", StaticFiles(directory=str(files("geoqc_app").joinpath("web")), html=True), name="web")
    return app
