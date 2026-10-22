"""Real PostgreSQL/export processes and lossless derived-format checks."""
from __future__ import annotations

import copy
import csv
import io
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import psutil
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from pypdf import PdfReader

from geoqc.core.evidence import canonical_hash
from geoqc_app.api import create_app
from geoqc_app.errors import AppError
from geoqc_app.export_worker import ExportWorker
from geoqc_app.exports import Exports
from geoqc_app.maintenance import reconcile
from geoqc_app.models import ExportCreate
from geoqc_app.render_exports import MEDIA_TYPES, WARNING, leaves, render_export
from geoqc_app.service import Service
from tools.tests.test_app_backend import ROOT, app_process, wait_until
from tools.tests.test_app_backend import backend as backend
from tools.tests.test_app_backend import published as published


def source(backend, published):
    service = backend[0]
    run = service.get(backend[2], "processing_runs", published[0])
    with service.db.connect() as conn:
        artifact = conn.execute("SELECT a.* FROM artifacts a JOIN dossiers d ON d.artifact_id=a.id WHERE d.id=%s",
                                (uuid.UUID(run["dossier_id"]),)).fetchone()
    content = service.store.path(artifact["storage_key"]).read_bytes()
    return uuid.UUID(run["dossier_id"]), json.loads(content), content


@pytest.fixture
def document():
    return json.loads((ROOT / "evidence/app_local/adapter/runs/20261015T045324Z_2750c032/e5_dossier.json").read_bytes())


def test_csv_preserves_nulls_types_units_and_provenance(document):
    rendered = render_export(document, "CSV")
    rows = list(csv.DictReader(io.StringIO(rendered.decode("utf-8"))))
    restored = {row["json_pointer"]: json.loads(row["value_json"]) for row in rows}
    assert restored == {path: json.loads(value) for path, value in leaves(document)}
    assert restored["/eligible_for_acceptance"] is False
    assert restored["/sufficiency/status"] == "NOT_DEMONSTRATED"
    assert any("frequency_hz" in path for path in restored)
    assert any(value is None for value in restored.values())
    assert all(row["scientific_digest"] == document["scientific_digest"] for row in rows)


def test_html_escapes_provenance_and_csv_does_not_emit_formula(document):
    document = copy.deepcopy(document)
    malicious = '=HYPERLINK("https://invalid.test")<script>alert(1)</script>'
    document["diagnostic_quality"][0]["shot_id"] = malicious
    document["scientific_digest"] = canonical_hash({k: v for k, v in document.items() if k != "scientific_digest"})
    rendered = render_export(document, "HTML").decode("utf-8")
    assert "<script>" not in rendered and "&lt;script&gt;" in rendered
    assert "Content-Security-Policy" in rendered and WARNING in rendered
    rows = list(csv.DictReader(io.StringIO(render_export(document, "CSV").decode("utf-8"))))
    row = next(row for row in rows if row["json_pointer"] == "/diagnostic_quality/0/shot_id")
    assert json.loads(row["value_json"]) == malicious
    assert not row["value_json"].startswith(("=", "+", "-", "@", "\t", "\r"))


def test_pdf_is_readable_and_keeps_diagnostic_status(document):
    rendered = render_export(document, "PDF")
    reader = PdfReader(io.BytesIO(rendered))
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert len(reader.pages) > 1
    assert document["scientific_digest"] in text
    assert WARNING in text
    assert '"eligible_for_acceptance": false' in text
    assert "NOT_DEMONSTRATED" in text
    assert "missing_evidence" in text and "native_diagnostics" in text


def test_renderer_rejects_modified_science(document):
    document["eligible_for_acceptance"] = True
    with pytest.raises(AppError) as error:
        render_export(document, "HTML")
    assert error.value.code == "EXPORT_SOURCE_INTEGRITY"


@pytest.mark.parametrize("format", ["CSV", "HTML", "PDF"])
def test_http_export_formats_idempotency_and_authorized_download(backend, published, format):
    service, credentials, _, _ = backend
    dossier_id, document, _ = source(backend, published)
    with TestClient(create_app(service.settings)) as client:
        headers = {"Authorization": "Bearer " + credentials["reviewer"]["token"], "Idempotency-Key": "export"}
        url = f"/v1/dossiers/{dossier_id}/exports"
        first = client.post(url, headers=headers, json={"format": format})
        assert first.status_code == 202, first.text
        assert client.post(url, headers=headers, json={"format": format}).json() == first.json()
        identifier = first.json()["id"]
        assert client.get(f"/v1/exports/{identifier}/content", headers=headers).status_code == 409
        with pytest.raises(AppError) as error:
            reconcile(service, apply=True)
        assert error.value.code == "MAINTENANCE_BUSY"
        assert ExportWorker(service).run_once()
        export = client.get(f"/v1/exports/{identifier}", headers=headers).json()
        assert export["state"] == "READY", export
        assert export["manifest"]["scientific_digest"] == document["scientific_digest"]
        assert export["manifest"]["renderer_reference"] == export["renderer_reference"]
        response = client.get(f"/v1/exports/{identifier}/content", headers=headers)
        assert response.status_code == 200 and response.content
        assert response.headers["content-type"].startswith(MEDIA_TYPES[format])
        assert "." + format.lower() in response.headers["content-disposition"]
        with service.db.connect() as conn:
            assert conn.execute("SELECT count(*) AS n FROM exports").fetchone()["n"] == 1
    assert not reconcile(service, apply=True)["integrity_errors"]


def test_export_disk_failure_retry_preserves_science_and_review(backend, published, monkeypatch):
    service, _, _, reviewer = backend
    jobs = Exports(service)
    dossier_id, _, original_content = source(backend, published)
    before_run = service.get(backend[2], "processing_runs", published[0])
    before_review = service.review(reviewer, published[3])
    identifier = uuid.UUID(jobs.create(reviewer, dossier_id, ExportCreate(format="HTML"), "failed-export").body["id"])
    original_put = service.store.put
    def unavailable(_):
        raise OSError("Injected output disk failure")
    monkeypatch.setattr(service.store, "put", unavailable)
    assert ExportWorker(service).run_once()
    export = service.get(reviewer, "exports", identifier)
    assert export["state"] == "FAILED" and export["artifact_id"] is None and export["error_code"] == "EXPORT_IO"
    monkeypatch.setattr(service.store, "put", original_put)
    retried = jobs.retry(reviewer, identifier, "retry")
    assert jobs.retry(reviewer, identifier, "retry") == retried
    assert ExportWorker(service).run_once()
    assert service.get(reviewer, "exports", identifier)["state"] == "READY"
    assert service.get(backend[2], "processing_runs", published[0]) == before_run
    assert service.review(reviewer, published[3]) == before_review
    assert source(backend, published)[2] == original_content
    with service.db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM processing_attempts").fetchone()["n"] == 1
        attempts = conn.execute("SELECT state FROM export_attempts ORDER BY number").fetchall()
        assert [row["state"] for row in attempts] == ["FAILED", "SUCCEEDED"]


def test_export_claims_are_exclusive_and_expired_token_cannot_publish(backend, published):
    service, _, _, reviewer = backend
    jobs = Exports(service)
    dossier_id = source(backend, published)[0]
    identifier = uuid.UUID(jobs.create(reviewer, dossier_id, ExportCreate(format="CSV"), "export").body["id"])
    barrier = Barrier(2)
    def claim(_):
        barrier.wait()
        return Exports(Service(service.settings)).claim()
    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed = [row for row in executor.map(claim, range(2)) if row is not None]
    assert len(claimed) == 1
    first = claimed[0]
    with service.db.connect() as conn:
        conn.execute("UPDATE exports SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s", (identifier,))
    second = jobs.claim()
    assert second["attempt"] == 2
    assert not jobs.heartbeat(identifier, first["token"])
    assert not jobs.fail(identifier, first["token"], "STALE")
    with pytest.raises(AppError) as error:
        jobs.publish(identifier, first["token"], service.store.put(b"stale output"))
    assert error.value.code == "LEASE_LOST"
    ExportWorker(service).execute(second)
    assert service.get(reviewer, "exports", identifier)["state"] == "READY"


def test_export_retry_budget_and_renderer_mismatch(backend, published):
    service, _, _, reviewer = backend
    jobs = Exports(service)
    identifier = uuid.UUID(jobs.create(reviewer, source(backend, published)[0], ExportCreate(format="HTML"), "export").body["id"])
    reference = service.get(reviewer, "exports", identifier)["renderer_reference"]
    reference["code_sha256"] = "0" * 64
    with service.db.connect() as conn:
        conn.execute("UPDATE exports SET renderer_reference=%s WHERE id=%s", (Jsonb(reference), identifier))
    for attempt in range(service.settings.max_attempts):
        assert ExportWorker(service).run_once()
        row = service.get(reviewer, "exports", identifier)
        assert row["state"] == "FAILED" and row["error_code"] == "EXPORT_RENDERER_MISMATCH"
        if attempt + 1 < service.settings.max_attempts:
            jobs.retry(reviewer, identifier, f"retry-{attempt}")
    with pytest.raises(AppError) as error:
        jobs.retry(reviewer, identifier, "exhausted")
    assert error.value.code == "EXPORT_RETRIES_EXHAUSTED"


def test_export_timeout_does_not_fail_scientific_run(backend, published):
    service = Service(replace(backend[0].settings, calculation_timeout_seconds=0.001))
    jobs = Exports(service)
    identifier = uuid.UUID(jobs.create(backend[3], source(backend, published)[0], ExportCreate(format="PDF"), "timeout").body["id"])
    assert ExportWorker(service).run_once()
    row = service.get(backend[3], "exports", identifier)
    assert row["state"] == "FAILED" and row["error_code"] == "EXPORT_TIMEOUT" and row["artifact_id"] is None
    assert service.get(backend[2], "processing_runs", published[0])["state"] == "SUCCEEDED"


def test_expiring_publication_rolls_back_artifact_and_manifest(backend, published, monkeypatch):
    service = backend[0]
    jobs = Exports(service)
    identifier = uuid.UUID(jobs.create(backend[3], source(backend, published)[0], ExportCreate(format="HTML"), "publication").body["id"])
    attempt = jobs.claim()
    blob = service.store.put(b"a rendered output")
    original_verify = service.store.verify
    def delayed_verification(value):
        import time
        time.sleep(0.6)
        return original_verify(value)
    monkeypatch.setattr(service.store, "verify", delayed_verification)
    with service.db.connect() as conn:
        conn.execute("UPDATE exports SET lease_until=clock_timestamp()+interval '0.5 second' WHERE id=%s", (identifier,))
    with pytest.raises(AppError) as error:
        jobs.publish(identifier, attempt["token"], blob)
    assert error.value.code == "LEASE_LOST"
    with service.db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM artifacts WHERE kind LIKE 'export_%%'").fetchone()["n"] == 0
    row = service.get(backend[3], "exports", identifier)
    assert row["state"] == "RUNNING" and row["manifest"] is None and row["artifact_id"] is None


def test_export_rejects_corrupt_source_and_can_retry_after_repair(backend, published):
    service = backend[0]
    jobs = Exports(service)
    dossier_id, _, content = source(backend, published)
    identifier = uuid.UUID(jobs.create(backend[3], dossier_id, ExportCreate(format="CSV"), "integrity").body["id"])
    attempt = jobs.claim()
    path = service.store.path(jobs.inputs(attempt)["source"]["key"])
    path.write_bytes(content + b" ")
    try:
        ExportWorker(service).execute(attempt)
        row = service.get(backend[3], "exports", identifier)
        assert row["state"] == "FAILED" and row["error_code"] == "ARTIFACT_INTEGRITY"
    finally:
        path.write_bytes(content)
    jobs.retry(backend[3], identifier, "repaired")
    assert ExportWorker(service).run_once()
    assert service.get(backend[3], "exports", identifier)["state"] == "READY"


def test_export_authorization_applies_to_create_read_retry_and_download(backend, published):
    service, credentials, _, reviewer = backend
    dossier_id = source(backend, published)[0]
    identifier = Exports(service).create(reviewer, dossier_id, ExportCreate(format="CSV"), "export").body["id"]
    outsiders = service.bootstrap()
    with TestClient(create_app(service.settings)) as client:
        headers = {"Authorization": "Bearer " + outsiders["operator"]["token"], "Idempotency-Key": "outside"}
        assert client.post(f"/v1/dossiers/{dossier_id}/exports", headers=headers, json={"format": "PDF"}).status_code == 404
        assert client.get(f"/v1/exports/{identifier}", headers=headers).status_code == 404
        assert client.post(f"/v1/exports/{identifier}/retries", headers=headers).status_code == 404
        assert client.get(f"/v1/exports/{identifier}/content", headers=headers).status_code == 404
        with service.db.connect() as conn:
            conn.execute("DELETE FROM memberships WHERE user_id=%s", (reviewer.id,))
        headers["Authorization"] = "Bearer " + credentials["reviewer"]["token"]
        assert client.post(f"/v1/dossiers/{dossier_id}/exports", headers=headers, json={"format": "CSV"}).status_code == 404


def test_real_export_worker_death_recovers_without_recomputing_science(backend, published):
    service = Service(replace(backend[0].settings, lease_seconds=3, heartbeat_seconds=0.4))
    jobs = Exports(service)
    dossier_id = source(backend, published)[0]
    identifier = uuid.UUID(jobs.create(backend[3], dossier_id, ExportCreate(format="PDF"), "export").body["id"])
    children = []
    try:
        with app_process(service, "export-worker", "--once") as process:
            def started():
                nonlocal children
                children = psutil.Process(process.pid).children()
                row = service.get(backend[3], "exports", identifier)
                return row if children and row["state"] == "RUNNING" else None
            abandoned = wait_until(started)
            process.kill()
            process.wait(timeout=10)
        def expired():
            with service.db.connect() as conn:
                return conn.execute("SELECT lease_until<clock_timestamp() AS expired FROM exports WHERE id=%s",
                                    (identifier,)).fetchone()["expired"]
        wait_until(expired)
        with app_process(service, "export-worker", "--once") as replacement:
            assert replacement.wait(timeout=40) == 0
        row = service.get(backend[3], "exports", identifier)
        assert row["state"] == "READY" and row["attempt"] == 2
        assert not jobs.heartbeat(identifier, uuid.UUID(abandoned["token"]))
        with service.db.connect() as conn:
            assert conn.execute("SELECT count(*) AS n FROM processing_attempts").fetchone()["n"] == 1
            attempts = conn.execute("SELECT state FROM export_attempts ORDER BY number").fetchall()
            assert [row["state"] for row in attempts] == ["EXPIRED", "SUCCEEDED"]
    finally:
        for child in children:
            try:
                if child.is_running():
                    child.kill()
                    child.wait(timeout=10)
            except psutil.NoSuchProcess:
                pass
