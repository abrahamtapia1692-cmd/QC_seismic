"""Transactional local backend checks against an isolated PostgreSQL schema."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, replace
from importlib.resources import files
from pathlib import Path
from threading import Barrier

import httpx2
import psutil
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from geoqc_app.api import create_app
from geoqc_app.calculate import preflight_segy
from geoqc_app.config import Settings
from geoqc_app.errors import AppError
from geoqc_app.maintenance import reconcile
from geoqc_app.models import AcquisitionCreate, Reopening, ReviewWrite, RevisionCreate, RunCreate, UploadCancellation
from geoqc_app.service import Service
from geoqc_app.storage import ArtifactStore
from geoqc_app.worker import Worker

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def backend(tmp_path):
    # Explicitly configured real database: never replace transactional checks with mocks.
    settings = Settings.load(ROOT / ".local/backend.json")
    settings = Settings(dsn=settings.dsn, storage_root=tmp_path, schema="test_" + uuid.uuid4().hex)
    service = Service(settings)
    service.db.migrate()
    credentials = service.bootstrap()
    operator = service.authenticate(credentials["operator"]["token"])
    reviewer = service.authenticate(credentials["reviewer"]["token"])
    try:
        yield service, credentials, operator, reviewer
    finally:
        # Only the unique schema created by this fixture is removed.
        with service.db.connect() as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(settings.schema)))


def queued(backend):
    service, credentials, operator, _ = backend
    acquisition = service.create_acquisition(operator, AcquisitionCreate(
        project_id=credentials["project_id"], name="E5 integration"), "acquisition")
    acquisition_id = uuid.UUID(acquisition.body["id"])
    upload_id = uuid.UUID(service.create_upload(operator, acquisition_id, "upload").body["id"])
    for kind, filename in (("waveform", "masw_plane.sgy"), ("sidecar", "masw_plane.sgy.json")):
        blob = service.store.put((ROOT / "examples/e5" / filename).read_bytes())
        service.attach_part(operator, upload_id, kind, blob)
    completed = service.complete_upload(operator, upload_id, "complete")
    assert service.complete_upload(operator, upload_id, "complete") == completed
    revision = service.create_revision(operator, acquisition_id, RevisionCreate(uploads=(upload_id,)), "revision")
    request = RunCreate(revision_id=revision.body["id"],
                        protocol=json.loads((ROOT / "examples/e5/protocol.json").read_bytes()),
                        excluded_receiver_ids=("r0",))
    run = service.create_run(operator, request, "run")
    assert service.create_run(operator, request, "run") == run
    return uuid.UUID(run.body["id"]), acquisition_id, upload_id


@pytest.fixture
def published(backend):
    run_id, acquisition_id, upload_id = queued(backend)
    service = backend[0]
    assert Worker(service).run_once()
    run = service.get(backend[2], "processing_runs", run_id)
    assert run["state"] == "SUCCEEDED", run
    with service.db.connect() as conn:
        review = conn.execute("SELECT id FROM review_cases WHERE dossier_id=%s", (run["dossier_id"],)).fetchone()
    return run_id, acquisition_id, upload_id, review["id"]


def decision(reply):
    return ReviewWrite(verdict="ACCEPTED", scope="Diagnóstico MASW", justification="Revisión técnica E5",
                       caveats=("Sintético; suficiencia no demostrada",),
                       scientific_digest=reply.body["scientific_digest"])


def open_upload(backend, *, key="open", with_parts=False):
    service, credentials, operator, _ = backend
    acquisition = service.create_acquisition(operator, AcquisitionCreate(
        project_id=credentials["project_id"], name=key), key)
    acquisition_id = uuid.UUID(acquisition.body["id"])
    upload = service.create_upload(operator, acquisition_id, key)
    assert service.create_upload(operator, acquisition_id, key) == upload
    identifier = uuid.UUID(upload.body["id"])
    if with_parts:
        for kind, name in (("waveform", "masw_plane.sgy"), ("sidecar", "masw_plane.sgy.json")):
            blob = service.store.put((ROOT / "examples/e5" / name).read_bytes())
            service.attach_part(operator, identifier, kind, blob)
    return identifier, acquisition_id


def set_expired(service, upload_id):
    with service.db.connect() as conn:
        conn.execute("UPDATE upload_sessions SET expires_at=clock_timestamp()-interval '1 second' WHERE id=%s",
                     (upload_id,))


def test_upload_cancellation_http_idempotency_and_admission(backend, monkeypatch):
    service, credentials, operator, _ = backend
    upload_id, acquisition_id = open_upload(backend, with_parts=True)
    request = {"reason": "Registro interrumpido en campo"}
    headers = {"Authorization": "Bearer " + credentials["operator"]["token"], "Idempotency-Key": "cancel-upload"}
    with TestClient(create_app(service.settings)) as client:
        url = f"/v1/upload-sessions/{upload_id}/cancellations"
        first = client.post(url, headers=headers, json=request)
        assert first.status_code == 200, first.text
        assert first.json()["state"] == "CANCELLED"
        assert client.post(url, headers=headers, json=request).json() == first.json()
        assert client.post(url, headers=headers, json={"reason": "different"}).status_code == 409

        def never_allocate(_):
            raise AssertionError("A closed upload must be rejected before reserving disk")
        monkeypatch.setattr(client.app.state.service.store, "begin", never_allocate)
        result = client.put(f"/v1/upload-sessions/{upload_id}/waveform", headers=headers, content=b"late bytes")
        assert result.status_code == 409 and result.json()["code"] == "UPLOAD_FINALIZED"
    with pytest.raises(AppError):
        service.complete_upload(operator, upload_id, "complete-cancelled")
    with pytest.raises(AppError):
        service.create_revision(operator, acquisition_id, RevisionCreate(uploads=(upload_id,)), "cancelled-revision")
    with service.db.connect() as conn:
        row = conn.execute("SELECT * FROM upload_sessions WHERE id=%s", (upload_id,)).fetchone()
        assert row["closed_at"] is not None and row["cancellation_reason"] == request["reason"]
        assert conn.execute("SELECT count(*) AS n FROM outbox WHERE event_type='UPLOAD_CANCELLED'"
                            ).fetchone()["n"] == 1
    assert not reconcile(service, apply=True)["integrity_errors"]


def test_upload_cancellation_enforces_role_and_project(backend):
    service, credentials, _, _ = backend
    upload_id, _ = open_upload(backend)
    outsiders = service.bootstrap()
    with TestClient(create_app(service.settings)) as client:
        for token, status in ((credentials["reviewer"]["token"], 403), (credentials["admin"]["token"], 403),
                              (outsiders["operator"]["token"], 404)):
            response = client.post(f"/v1/upload-sessions/{upload_id}/cancellations", json={"reason": "x"}, headers={
                "Authorization": "Bearer " + token, "Idempotency-Key": "forbidden"})
            assert response.status_code == status
    assert service.get(backend[2], "upload_sessions", upload_id)["state"] == "UPLOADING"


def test_expired_upload_rejects_writes_before_sweep_and_unblocks_maintenance(backend):
    service, _, operator, _ = backend
    upload_id, _ = open_upload(backend, with_parts=True)
    set_expired(service, upload_id)
    blob = service.store.put((ROOT / "examples/e5/masw_plane.sgy").read_bytes())
    for operation in (lambda: service.attach_part(operator, upload_id, "waveform", blob),
                      lambda: service.complete_upload(operator, upload_id, "expired-complete"),
                      lambda: service.cancel_upload(operator, upload_id, UploadCancellation(reason="late"), "late")):
        with pytest.raises(AppError) as error:
            operation()
        assert error.value.code == "UPLOAD_EXPIRED"
    assert service.expire_uploads() == 1
    assert Service(service.settings).expire_uploads() == 0
    row = service.get(operator, "upload_sessions", upload_id)
    assert row["state"] == "EXPIRED" and row["closed_at"] is not None
    with service.db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM outbox WHERE event_type='UPLOAD_EXPIRED'"
                            ).fetchone()["n"] == 1
    assert not reconcile(service, apply=True)["integrity_errors"]


def test_parallel_expiry_is_bounded_and_keeps_future_sessions(backend):
    service = backend[0]
    for index in range(5):
        upload_id, _ = open_upload(backend, key=f"old-{index}")
        set_expired(service, upload_id)
    future, _ = open_upload(backend, key="future")
    assert service.expire_uploads(limit=2) == 2
    barrier = Barrier(2)

    def expire(_):
        barrier.wait()
        return Service(service.settings).expire_uploads(limit=2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sum(executor.map(expire, range(2))) == 3
    assert service.get(backend[2], "upload_sessions", future)["state"] == "UPLOADING"
    with service.db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM outbox WHERE event_type='UPLOAD_EXPIRED'"
                            ).fetchone()["n"] == 5


def test_worker_expires_sessions_without_scientific_jobs(backend):
    service = backend[0]
    upload_id, _ = open_upload(backend)
    set_expired(service, upload_id)
    assert Worker(service).run_once() is False
    assert service.get(backend[2], "upload_sessions", upload_id)["state"] == "EXPIRED"
    changes = service.changes(backend[3], uuid.UUID(backend[1]["project_id"]), None, 100)
    assert sum(row["event_type"] == "UPLOAD_EXPIRED" for row in changes["changes"]) == 1


def test_upload_complete_and_cancel_have_only_one_winner(backend):
    service, _, operator, _ = backend
    upload_id, _ = open_upload(backend, with_parts=True)
    barrier = Barrier(2)

    def close(operation):
        barrier.wait()
        try:
            if operation == "complete":
                return service.complete_upload(operator, upload_id, "racing-complete").body["state"]
            return service.cancel_upload(operator, upload_id, UploadCancellation(reason="Interrupted"),
                                         "racing-cancel").body["state"]
        except AppError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(close, ("complete", "cancel")))
    assert results.count("UPLOAD_FINALIZED") == 1
    assert sum(state in ("VERIFIED", "CANCELLED") for state in results) == 1
    with service.db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM outbox WHERE event_type IN ('UPLOAD_VERIFIED','UPLOAD_CANCELLED')"
                            ).fetchone()["n"] == 1


@pytest.mark.parametrize("closure", ["cancel", "expire"])
def test_http_transfer_closed_mid_stream_is_not_attached(backend, monkeypatch, closure):
    service, credentials, operator, _ = backend
    upload_id, _ = open_upload(backend)
    with TestClient(create_app(service.settings)) as client:
        store = client.app.state.service.store
        begin = store.begin

        def begin_and_close(limit):
            writer = begin(limit)
            original_write = writer.write
            def write(chunk):
                if closure == "cancel":
                    service.cancel_upload(operator, upload_id, UploadCancellation(reason="During transfer"), "midstream")
                else:
                    set_expired(service, upload_id)
                original_write(chunk)
            writer.write = write
            return writer
        monkeypatch.setattr(store, "begin", begin_and_close)
        response = client.put(f"/v1/upload-sessions/{upload_id}/waveform", content=b"a waveform", headers={
            "Authorization": "Bearer " + credentials["operator"]["token"]})
    assert response.status_code == 409
    assert response.json()["code"] == ("UPLOAD_EXPIRED" if closure == "expire" else "UPLOAD_FINALIZED")
    assert service.get(operator, "upload_sessions", upload_id)["waveform_id"] is None
    with service.db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM artifacts").fetchone()["n"] == 0


def test_deadline_is_rechecked_after_artifact_verification(backend, monkeypatch):
    service, _, operator, _ = backend
    upload_id, _ = open_upload(backend, with_parts=True)
    with service.db.connect() as conn:
        conn.execute("UPDATE upload_sessions SET expires_at=clock_timestamp()+interval '1 second' WHERE id=%s",
                     (upload_id,))
    original = service.store.verify
    def delayed_verification(blob):
        time.sleep(1.1)
        return original(blob)
    monkeypatch.setattr(service.store, "verify", delayed_verification)
    with pytest.raises(AppError) as error:
        service.complete_upload(operator, upload_id, "crossed-deadline")
    assert error.value.code == "UPLOAD_EXPIRED"
    assert service.expire_uploads() == 1


def test_verified_upload_keeps_identical_replay_after_deadline(backend):
    service, credentials, operator, _ = backend
    upload_id, _ = open_upload(backend)
    with TestClient(create_app(service.settings)) as client:
        headers = {"Authorization": "Bearer " + credentials["operator"]["token"]}
        for kind, name in (("waveform", "masw_plane.sgy"), ("sidecar", "masw_plane.sgy.json")):
            attached = client.put(f"/v1/upload-sessions/{upload_id}/{kind}", headers=headers,
                                  content=(ROOT / "examples/e5" / name).read_bytes())
            assert attached.status_code == 200, attached.text
            assert uuid.UUID(attached.json()["artifact_id"])
        completed = client.post(f"/v1/upload-sessions/{upload_id}/complete", headers=headers | {
            "Idempotency-Key": "verified"})
        assert completed.status_code == 200, completed.text
        original = service.get(operator, "upload_sessions", upload_id)
        set_expired(service, upload_id)
        assert service.expire_uploads() == 0
        response = client.put(f"/v1/upload-sessions/{upload_id}/waveform", headers=headers,
                              content=(ROOT / "examples/e5/masw_plane.sgy").read_bytes())
        assert response.status_code == 200, response.text
        assert response.json()["artifact_id"] == original["waveform_id"]
        assert client.post(f"/v1/upload-sessions/{upload_id}/complete", headers=headers | {
            "Idempotency-Key": "another-completion"}).json()["state"] == "VERIFIED"
        cancelled = client.post(f"/v1/upload-sessions/{upload_id}/cancellations", json={"reason": "Too late"},
                                headers=headers | {"Idempotency-Key": "cancel-verified"})
        assert cancelled.status_code == 409
    with service.db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM artifacts").fetchone()["n"] == 2


def test_upload_ttl_configuration_only_changes_new_sessions(backend):
    service = backend[0]
    first, acquisition_id = open_upload(backend)
    original = service.get(backend[2], "upload_sessions", first)
    configured = Service(replace(service.settings, upload_ttl_seconds=120))
    repeated = configured.create_upload(backend[2], acquisition_id, "open")
    assert repeated.body["id"] == str(first)
    assert repeated.body["expires_at"] == original["expires_at"]
    new = configured.create_upload(backend[2], acquisition_id, "new-ttl")
    with service.db.connect() as conn:
        row = conn.execute("SELECT expires_at-created_at AS duration FROM upload_sessions WHERE id=%s",
                           (uuid.UUID(new.body["id"]),)).fetchone()
        assert 119 <= row["duration"].total_seconds() <= 121


def test_upload_lifecycle_migration_preserves_v1_originals(backend):
    original = backend[0]
    legacy = Service(replace(original.settings, schema="legacy_" + uuid.uuid4().hex,
                             storage_root=original.store.root / "legacy-store"))
    try:
        with legacy.db.connect() as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(legacy.settings.schema)))
            conn.execute("CREATE TABLE schema_versions(version integer PRIMARY KEY)")
            conn.execute(files("geoqc_app").joinpath("sql/001_initial.sql").read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_versions VALUES(1)")
        credentials = legacy.bootstrap()
        actor = legacy.authenticate(credentials["operator"]["token"])
        acquisition = legacy.create_acquisition(actor, AcquisitionCreate(project_id=credentials["project_id"],
                                                                          name="Legacy metadata"), "legacy")
        identifiers = [uuid.uuid4(), uuid.uuid4()]
        blob = legacy.store.put(b"legacy original bytes")
        with legacy.db.connect() as conn:
            artifact = legacy.insert_artifact(conn, uuid.UUID(credentials["project_id"]), blob, "waveform")
            for identifier, state in zip(identifiers, ("UPLOADING", "VERIFIED"), strict=True):
                conn.execute("INSERT INTO upload_sessions(id,project_id,acquisition_id,waveform_id,state,created_at) "
                             "VALUES (%s,%s,%s,%s,%s,clock_timestamp()-interval '2 days')",
                             (identifier, uuid.UUID(credentials["project_id"]), uuid.UUID(acquisition.body["id"]),
                              artifact, state))
        legacy.db.migrate()
        legacy.db.migrate()
        assert legacy.expire_uploads() == 1
        with legacy.db.connect() as conn:
            rows = conn.execute("SELECT * FROM upload_sessions ORDER BY state").fetchall()
            assert [row["state"] for row in rows] == ["EXPIRED", "VERIFIED"]
            assert all(row["waveform_id"] == artifact for row in rows)
            assert all((row["expires_at"] - row["created_at"]).total_seconds() == 86400 for row in rows)
            assert [row["version"] for row in conn.execute("SELECT version FROM schema_versions ORDER BY version")
                    ] == [1, 2, 3]
        assert legacy.store.verify(blob).read_bytes() == b"legacy original bytes"
    finally:
        with legacy.db.connect() as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(legacy.settings.schema)))


def test_e5_http_and_review_idempotency(backend, published):
    service, credentials, _, reviewer = backend
    run_id, _, _, review_id = published
    with TestClient(create_app(service.settings)) as client:
        headers = {"Authorization": "Bearer " + credentials["reviewer"]["token"]}
        response = client.get(f"/v1/processing-runs/{run_id}", headers=headers)
        assert response.status_code == 200
        dossier = client.get("/v1/dossiers/" + response.json()["dossier_id"], headers=headers)
        assert dossier.status_code == 200, dossier.text
        assert dossier.json()["summary"]["eligible_for_acceptance"] is False
        reply = service.review(reviewer, review_id)
        body = decision(reply).model_dump(mode="json")
        assert client.put(f"/v1/review-cases/{review_id}", headers=headers | {
            "Idempotency-Key": "missing-precondition"}, json=body).status_code == 428
        headers |= {"If-Match": reply.etag, "Idempotency-Key": "decision"}
        first = client.put(f"/v1/review-cases/{review_id}", headers=headers, json=body)
        assert first.status_code == 200, first.text
        assert client.put(f"/v1/review-cases/{review_id}", headers=headers, json=body).json() == first.json()
        assert client.get("/v1/dossiers/" + response.json()["dossier_id"], headers=headers).json() == dossier.json()


def test_concurrent_review_has_one_winner(backend, published):
    service, _, _, reviewer = backend
    review_id = published[3]
    reply = service.review(reviewer, review_id)
    other = service.bootstrap()
    other_reviewer = service.authenticate(other["reviewer"]["token"])
    with service.db.connect() as conn:
        conn.execute("INSERT INTO memberships VALUES (%s,%s,%s)",
                     (uuid.UUID(backend[1]["project_id"]), other_reviewer.id, ["OFFICE_REVIEWER"]))
    barrier = Barrier(2)

    def write(key):
        barrier.wait()
        try:
            actor = reviewer if key == "review-a" else other_reviewer
            return service.write_review(actor, review_id, decision(reply), reply.etag, key).status
        except AppError as exc:
            return exc.status

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(write, ("review-a", "review-b"))) == [200, 412]
    assert len(service.review(reviewer, review_id).body["history"]) == 1


def test_expired_attempt_cannot_publish_or_heartbeat(backend):
    run_id, _, _ = queued(backend)
    service = backend[0]
    first = service.claim()
    with service.db.connect() as conn:
        conn.execute("UPDATE processing_runs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",
                     (run_id,))
    second = Service(service.settings).claim()
    assert second["attempt"] == 2 and first["token"] != second["token"]
    assert not service.heartbeat(run_id, first["token"])
    assert not service.fail(run_id, first["token"], "OLD_ATTEMPT", transient=False)
    Worker(service).execute(second)
    assert service.get(backend[2], "processing_runs", run_id)["state"] == "SUCCEEDED"
    result_path = service.store.root / "attempts" / str(run_id) / str(second["token"]) / "dossier.json"
    content = result_path.read_bytes()
    with pytest.raises(AppError) as error:
        service.publish(run_id, first["token"], json.loads(content), service.store.put(content))
    assert error.value.code == "LEASE_LOST"


def test_cancellation_fences_worker(backend):
    run_id, _, _ = queued(backend)
    service, _, operator, _ = backend
    attempt = service.claim()
    service.cancel(operator, run_id, "cancel")
    assert not service.heartbeat(run_id, attempt["token"])
    assert service.claim() is None


def test_restart_preserves_decision_and_outbox(backend, published):
    service, _, _, reviewer = backend
    review_id = published[3]
    reply = service.review(reviewer, review_id)
    service.write_review(reviewer, review_id, decision(reply), reply.etag, "review")
    restarted = Service(service.settings)
    assert restarted.review(reviewer, review_id).body["state"] == "DECIDED"
    assert restarted.dispatch_one()
    while restarted.dispatch_one():
        pass
    changes = restarted.changes(reviewer, uuid.UUID(backend[1]["project_id"]), None, 100)
    assert sum(row["event_type"] == "REVIEW_DECIDED" for row in changes["changes"]) == 1
    reopening = Reopening(expected_version="2", reason="Nueva revisión humana")
    reopened = restarted.reopen(reviewer, review_id, reopening, "reopen")
    assert reopened.body["version"] == "3"
    assert restarted.reopen(reviewer, review_id, reopening, "reopen") == reopened
    assert all(isinstance(entry["version"], str)
               for entry in restarted.review(reviewer, review_id).body["history"])


def test_new_revision_supersedes_review(backend, published):
    service, _, operator, reviewer = backend
    _, acquisition_id, upload_id, review_id = published
    reply = service.review(reviewer, review_id)
    service.create_revision(operator, acquisition_id, RevisionCreate(uploads=(upload_id,)), "new-revision")
    with pytest.raises(AppError, match="vigente") as error:
        service.write_review(reviewer, review_id, decision(reply), reply.etag, "old-review")
    assert error.value.code == "RESULT_SUPERSEDED"


def test_authorization_and_idempotency_scope(backend):
    service, credentials, operator, _ = backend
    run_id, _, _ = queued(backend)
    outsider = service.bootstrap()
    actor = service.authenticate(outsider["operator"]["token"])
    with pytest.raises(AppError) as error:
        service.get(actor, "processing_runs", run_id)
    assert error.value.status == 404
    admin = service.authenticate(credentials["admin"]["token"])
    with pytest.raises(AppError) as error:
        service.create_acquisition(admin, AcquisitionCreate(project_id=credentials["project_id"], name="x"), "x")
    assert error.value.status == 403
    with pytest.raises(AppError) as error:
        service.create_acquisition(operator, AcquisitionCreate(project_id=credentials["project_id"], name="changed"),
                                   "acquisition")
    assert error.value.code == "IDEMPOTENCY_MISMATCH"


def test_worker_input_io_failure_is_retryable(backend, monkeypatch):
    run_id, _, _ = queued(backend)
    service = backend[0]
    attempt = service.claim()

    def unavailable(_):
        raise OSError("Injected failure before starting scientific subprocess")

    monkeypatch.setattr(service, "execution_inputs", unavailable)
    Worker(service).execute(attempt)
    row = service.get(backend[2], "processing_runs", run_id)
    assert row["state"] == "RETRY_WAIT" and row["error_code"] == "WORKER_IO"
    with service.db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM dossiers WHERE run_id=%s", (run_id,)).fetchone()["n"] == 0


def test_artifact_failure_does_not_publish(backend, monkeypatch):
    run_id, _, _ = queued(backend)
    service = backend[0]
    attempt = service.claim()

    def unavailable(_):
        raise OSError("Injected disk failure")

    monkeypatch.setattr(service.store, "put", unavailable)
    Worker(service).execute(attempt)
    assert service.get(backend[2], "processing_runs", run_id)["state"] == "RETRY_WAIT"
    with service.db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM dossiers WHERE run_id=%s", (run_id,)).fetchone()["n"] == 0


def test_upload_integrity_and_finalization(backend):
    _, _, upload_id = queued(backend)
    service, _, operator, _ = backend
    blob = service.store.put(b"replacement")
    with pytest.raises(AppError) as error:
        service.attach_part(operator, upload_id, "waveform", blob)
    assert error.value.code == "UPLOAD_FINALIZED"
    service.store.path(blob.key).write_bytes(b"corrupt")
    with pytest.raises(AppError) as error:
        service.store.verify(blob)
    assert error.value.code == "ARTIFACT_INTEGRITY"


def test_preflight_rejects_excess_channels_before_ingest(tmp_path):
    raw = (ROOT / "examples/e5/masw_plane.sgy").read_bytes()
    import struct
    count = struct.unpack_from(">H", raw, 3600 + 114)[0]
    trace = raw[3600:3600 + 240 + 4 * count]
    path = tmp_path / "too_many.sgy"
    path.write_bytes(raw[:3600] + trace * 65)
    with pytest.raises(AppError) as error:
        preflight_segy(path)
    assert error.value.code == "INPUT_LIMIT"


def test_invalid_http_request_has_safe_error_envelope(backend):
    service, credentials, _, _ = backend
    with TestClient(create_app(service.settings)) as client:
        response = client.post("/v1/acquisitions", json={"project_id": "bad", "name": "x"}, headers={
            "Authorization": "Bearer " + credentials["operator"]["token"], "Idempotency-Key": "bad"})
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_REQUEST"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_reconciliation_preserves_references_and_recent_blobs(backend, published):
    service = backend[0]
    old = service.store.put(b"abandoned old blob")
    recent = service.store.put(b"possibly in transit")
    os.utime(service.store.path(old.key), (time.time() - 7200,) * 2)
    report = reconcile(service, minimum_age_seconds=3600)
    assert report["orphan_candidates"] == [old.key]
    assert service.store.path(old.key).exists()
    applied = reconcile(service, apply=True, minimum_age_seconds=3600)
    assert applied["deleted"] == [old.key]
    assert service.store.verify(recent).exists()
    assert not reconcile(service)["integrity_errors"]
    assert service.get(backend[2], "processing_runs", published[0])["state"] == "SUCCEEDED"


def test_reconciliation_refuses_open_work_and_corrupt_references(backend):
    _, _, upload_id = queued(backend)
    service = backend[0]
    with pytest.raises(AppError) as error:
        reconcile(service, apply=True)
    assert error.value.code == "MAINTENANCE_BUSY"
    run = service.claim()
    service.cancel(backend[2], run["id"], "cancel")
    upload = service.get(backend[2], "upload_sessions", upload_id)
    with service.db.connect() as conn:
        artifact = conn.execute("SELECT storage_key FROM artifacts WHERE id=%s", (upload["waveform_id"],)).fetchone()
    service.store.path(artifact["storage_key"]).write_bytes(b"corrupt original")
    assert reconcile(service)["integrity_errors"] == [artifact["storage_key"]]
    with pytest.raises(AppError) as error:
        reconcile(service, apply=True)
    assert error.value.code == "MAINTENANCE_INTEGRITY"


def test_storage_root_cannot_be_shared_between_schemas(backend):
    service = backend[0]
    with pytest.raises(ValueError, match="otra base o esquema"):
        Service(replace(service.settings, schema="another_schema"))


def test_storage_binding_is_atomic_during_parallel_startup(tmp_path):
    barrier = Barrier(4)

    def bind(_):
        store = ArtifactStore(tmp_path)
        barrier.wait()
        store.bind("same-database-schema")

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(bind, range(4)))
    assert json.loads((tmp_path / "namespace.json").read_bytes()) == {"namespace": "same-database-schema"}
    assert not list(tmp_path.glob("*.writing"))
    with pytest.raises(ValueError):
        ArtifactStore(tmp_path).bind("different-database-schema")


@pytest.mark.parametrize("minimum_age", [float("nan"), float("inf"), -1, 3599])
def test_reconciliation_rejects_invalid_retention(backend, minimum_age):
    with pytest.raises(ValueError):
        reconcile(backend[0], apply=True, minimum_age_seconds=minimum_age)


def test_maintenance_serializes_new_commands_before_reference_snapshot(backend):
    service, credentials, operator, _ = backend
    with ThreadPoolExecutor(max_workers=1) as executor:
        with service.db.connect() as maintenance:
            service.storage_lock(maintenance, exclusive=True)
            backend_pid = maintenance.info.backend_pid
            future = executor.submit(service.create_acquisition, operator,
                                     AcquisitionCreate(project_id=credentials["project_id"], name="After maintenance"),
                                     "maintenance-race")
            def blocked():
                with service.db.connect() as observer:
                    return observer.execute("SELECT EXISTS(SELECT 1 FROM pg_stat_activity "
                                            "WHERE %s=ANY(pg_blocking_pids(pid))) AS waiting",
                                            (backend_pid,)).fetchone()["waiting"]
            wait_until(blocked)
            assert not future.done()
            assert maintenance.execute("SELECT count(*) AS n FROM acquisitions").fetchone()["n"] == 0
            maintenance.commit()
        assert future.result(timeout=10).status == 201


def test_http_command_logs_correlate_without_credentials(backend, caplog):
    service, credentials, _, _ = backend
    with caplog.at_level("INFO"), TestClient(create_app(service.settings)) as client:
        response = client.post("/v1/acquisitions", json={"project_id": credentials["project_id"], "name": "Logging"},
                               headers={"Authorization": "Bearer " + credentials["operator"]["token"],
                                        "Idempotency-Key": "private-command-key"})
    assert response.status_code == 201
    command = next(record.message for record in caplog.records if "command_confirmed" in record.message)
    assert response.headers["X-Request-ID"] in command
    assert credentials["project_id"] in command and response.json()["id"] in command
    assert "private-command-key" not in caplog.text
    assert credentials["operator"]["token"] not in caplog.text


def test_parallel_dispatchers_preserve_cursor_without_duplicates(backend):
    queued(backend)
    service, credentials, _, reviewer = backend
    with service.db.connect() as conn:
        count = conn.execute("SELECT count(*) AS n FROM outbox").fetchone()["n"]
    barrier = Barrier(3)

    def dispatch(_):
        barrier.wait()
        other = Service(service.settings)
        while other.dispatch_one():
            pass

    with ThreadPoolExecutor(max_workers=3) as executor:
        list(executor.map(dispatch, range(3)))
    project = uuid.UUID(credentials["project_id"])
    cursor, sequences, events = None, [], []
    while True:
        page = service.changes(reviewer, project, cursor, 2)
        if not page["changes"]:
            break
        cursor = page["cursor"]
        sequences.extend(row["sequence"] for row in page["changes"])
        events.extend(row["event_id"] for row in page["changes"])
    assert sequences == list(range(1, count + 1))
    assert len(set(events)) == count
    assert not service.dispatch_one()


def wait_until(predicate, *, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for process state")


@contextmanager
def app_process(service, *arguments):
    configuration = asdict(service.settings)
    configuration["storage_root"] = str(configuration["storage_root"])
    path = service.store.root / "process-config.json"
    path.write_text(json.dumps(configuration), encoding="utf-8")
    environment = os.environ.copy()
    environment.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", PYTHONUTF8="1")
    with (service.store.root / (arguments[0] + ".log")).open("ab") as logfile:
        process = subprocess.Popen([sys.executable, "-X", "utf8", "-m", "geoqc_app", "--config", str(path),
                                    *arguments], cwd=ROOT, env=environment, stdout=logfile, stderr=logfile,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            yield process
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)


def test_real_api_restart_after_committed_response_is_lost(backend, published):
    service, credentials, _, reviewer = backend
    review_id = published[3]
    original = service.review(reviewer, review_id)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    with httpx2.Client(base_url=f"http://127.0.0.1:{port}", timeout=2, trust_env=False) as client:
        def ready():
            try:
                return client.get("/health").status_code == 200
            except httpx2.TransportError:
                return False

        headers = {"Authorization": "Bearer " + credentials["reviewer"]["token"],
                   "If-Match": original.etag, "Idempotency-Key": "lost-response"}
        body = decision(original).model_dump(mode="json")
        with app_process(service, "serve", "--port", str(port)) as process:
            wait_until(ready)
            # Headers prove commit; deliberately do not consume the response body.
            with client.stream("PUT", f"/v1/review-cases/{review_id}", headers=headers, json=body) as response:
                assert response.status_code == 200
                process.kill()
                process.wait(timeout=10)
        with app_process(service, "serve", "--port", str(port)):
            wait_until(ready)
            response = client.put(f"/v1/review-cases/{review_id}", headers=headers, json=body)
            assert response.status_code == 200, response.text
            assert response.json()["version"] == "2"
            current = client.get(f"/v1/review-cases/{review_id}", headers=headers).json()
            assert len(current["history"]) == 1
            with service.db.connect() as conn:
                assert conn.execute("SELECT count(*) AS n FROM outbox WHERE event_type='REVIEW_DECIDED'"
                                    ).fetchone()["n"] == 1


def test_real_worker_death_recovers_after_natural_lease_expiry(backend):
    run_id, _, _ = queued(backend)
    service = Service(replace(backend[0].settings, lease_seconds=3, heartbeat_seconds=0.4))
    children = []
    try:
        with app_process(service, "worker", "--once") as process:
            def started():
                nonlocal children
                children = psutil.Process(process.pid).children()
                run = service.get(backend[2], "processing_runs", run_id)
                return run if children and run["token"] else None
            abandoned = wait_until(started)
            process.kill()
            process.wait(timeout=10)
        # Do not manipulate database timestamps: allow the actual lease to expire.
        def expired():
            with service.db.connect() as conn:
                return conn.execute("SELECT lease_until<clock_timestamp() AS expired FROM processing_runs WHERE id=%s",
                                    (run_id,)).fetchone()["expired"]
        wait_until(expired)
        with app_process(service, "worker", "--once") as replacement:
            assert replacement.wait(timeout=40) == 0
        run = service.get(backend[2], "processing_runs", run_id)
        assert run["state"] == "SUCCEEDED" and run["attempt"] == 2
        assert not service.heartbeat(run_id, uuid.UUID(abandoned["token"]))
        with service.db.connect() as conn:
            attempts = conn.execute("SELECT state FROM processing_attempts WHERE run_id=%s ORDER BY number",
                                    (run_id,)).fetchall()
            assert [row["state"] for row in attempts] == ["EXPIRED", "SUCCEEDED"]
            assert conn.execute("SELECT count(*) AS n FROM dossiers WHERE run_id=%s", (run_id,)).fetchone()["n"] == 1
    finally:
        for child in children:
            try:
                if child.is_running():
                    child.kill()
                    child.wait(timeout=10)
            except psutil.NoSuchProcess:
                pass
