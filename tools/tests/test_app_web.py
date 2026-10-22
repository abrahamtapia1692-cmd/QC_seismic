"""Real Chromium sessions against the local API, PostgreSQL and scientific worker."""
from __future__ import annotations

import json
import socket
import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright

from geoqc_app.api import create_app
from geoqc_app.export_worker import ExportWorker
from geoqc_app.models import Reopening, ReviewWrite
from geoqc_app.worker import Worker
from tools.tests.test_app_backend import ROOT
from tools.tests.test_app_backend import backend as backend
from tools.tests.test_app_backend import published as published


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        yield instance
        instance.close()


@pytest.fixture
def web(backend, browser):
    service = backend[0]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(create_app(service.settings), log_level="critical", access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started, "Local API did not start"
            with browser.new_context(base_url=f"http://127.0.0.1:{listener.getsockname()[1]}") as context:
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                yield page, context, errors
                assert errors == []
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive()


def connect(page, token):
    page.goto("/")
    page.locator("#token").fill(token)
    page.get_by_role("button", name="Conectar", exact=True).click()
    expect(page.locator("#connection")).to_contain_text("Token cargado")
    expect(page.locator("#token")).to_have_value("")


def open_published(page, backend, published):
    service, credentials, operator, _ = backend
    run = service.get(operator, "processing_runs", published[0])
    connect(page, credentials["reviewer"]["token"])
    page.locator("#dossier-id").fill(run["dossier_id"])
    page.get_by_role("button", name="Abrir", exact=True).click()
    expect(page.locator("#review-state")).to_contain_text("PENDING")
    return run["dossier_id"]


def fill_review(page, text="Control técnico E5"):
    page.locator("#scope").fill("Diagnóstico local")
    page.locator("#justification").fill(text)
    page.locator("#caveats").fill("Sintético; suficiencia no demostrada")


def test_web_shell_is_packaged_and_data_still_requires_authentication(backend):
    with TestClient(create_app(backend[0].settings)) as client:
        for path, content_type in (("/", "text/html"), ("/app.js", "javascript"), ("/style.css", "text/css"),
                                   ("/transport.js", "javascript"), ("/repository.js", "javascript"),
                                   ("/usecases.js", "javascript"), ("/trs-visuals.js", "javascript"),
                                   ("/trs-visuals.css", "text/css"), ("/trace-quality.js", "javascript")):
            response = client.get(path)
            assert response.status_code == 200
            assert content_type in response.headers["content-type"]
        assert client.get("/v1/processing-runs/00000000-0000-0000-0000-000000000000").status_code == 401
        assert client.get("/.local/credentials.json").status_code == 404


def test_browser_upload_lost_response_worker_and_download(web, backend, tmp_path):
    page, _, _ = web
    service, credentials, _, _ = backend
    connect(page, credentials["operator"]["token"])
    calls = []

    def lose_first_response(route):
        calls.append(route.request.headers["idempotency-key"])
        if len(calls) == 1:
            result = route.fetch()
            assert result.status == 201
            route.abort("failed")
        else:
            route.continue_()

    page.route("**/v1/acquisitions", lose_first_response)
    page.locator("#project").fill(credentials["project_id"])
    page.locator("#name").fill("E5 desde Chromium")
    page.locator("#waveform-0").set_input_files(ROOT / "examples/e5/masw_plane.sgy")
    page.locator("#sidecar-0").set_input_files(ROOT / "examples/e5/masw_plane.sgy.json")
    page.locator("#protocol").set_input_files(ROOT / "examples/e5/protocol.json")
    page.locator("#exclusions").fill("r0")
    page.locator("#upload-submit").click()
    expect(page.locator("#message")).to_contain_text("Puedes reintentar")
    page.locator("#upload-submit").click()
    expect(page.locator("#upload-progress")).to_contain_text("Carga confirmada", timeout=15000)
    assert calls[0] == calls[1]
    assert Worker(service).run_once()
    expect(page.locator("#review-section")).to_be_visible(timeout=15000)
    expect(page.locator("#run-status")).to_contain_text("SUCCEEDED")
    with page.expect_download() as download:
        page.locator("#download-science").click()
    output = tmp_path / "science.json"
    download.value.save_as(output)
    document = json.loads(output.read_bytes())
    assert document["sufficiency"]["status"] == "NOT_DEMONSTRATED"
    assert document["eligible_for_acceptance"] is False
    page.get_by_text("Exportación derivada", exact=True).click()
    page.locator("#export-submit").click()
    expect(page.locator("#export-status")).to_contain_text("PENDING")
    assert ExportWorker(service).run_once()
    expect(page.locator("#export-status")).to_contain_text("READY", timeout=10000)
    with page.expect_download() as export_download:
        page.locator("#export-download").click()
    csv_path = tmp_path / "export.csv"
    export_download.value.save_as(csv_path)
    assert document["scientific_digest"] in csv_path.read_text(encoding="utf-8-sig")
    with service.db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM acquisitions").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM processing_runs").fetchone()["n"] == 1
    assert page.evaluate("Object.keys(localStorage).length + Object.keys(sessionStorage).length") == 0
    page.reload()
    expect(page.locator("#connection")).to_have_text("Sin conexión")


def test_two_sessions_converge_and_preserve_conflicting_draft(web, backend, published):
    first, context, _ = web
    identifier = open_published(first, backend, published)
    original_digest = first.locator("#digest").inner_text()
    original_summary = first.locator("#science-summary").inner_text()
    second = context.new_page()
    open_published(second, backend, published)
    fill_review(first, "Primera revisión")
    fill_review(second, "Borrador conservado de la segunda sesión")
    # Delay second's writes until the first has committed, preserving its initial ETag.
    first.locator("#review-submit").click()
    expect(first.locator("#review-state")).to_contain_text("DECIDED")
    expect(second.locator("#review-state")).to_contain_text("DECIDED", timeout=10000)
    expect(second.locator("#conflict")).to_be_visible()
    expect(second.locator("#justification")).to_have_value("Borrador conservado de la segunda sesión")
    expect(second.locator("#review-submit")).to_be_disabled()
    for page in (first, second):
        expect(page.locator("#science-summary")).to_contain_text("NOT_DEMONSTRATED")
        expect(page.locator("#science-summary")).to_contain_text("false")
        expect(page.locator("#review-history")).to_contain_text("Primera revisión")
        assert page.locator("#digest").inner_text() == original_digest
        assert page.locator("#science-summary").inner_text() == original_summary
    service = backend[0]
    before = service.review(backend[3], published[3]).body
    with TestClient(create_app(service.settings)) as client:
        header = client.get(f"/v1/dossiers/{identifier}", headers={"Authorization": "Bearer " + backend[1]["reviewer"]["token"]}).json()
    assert header["summary"]["eligible_for_acceptance"] is False
    assert before["history"][0]["content"]["verdict"] == "ACCEPTED"


def test_http_precondition_failure_preserves_draft_and_reloads_history(web, backend, published):
    page, _, _ = web
    open_published(page, backend, published)
    service, _, _, reviewer = backend
    calls = []

    def concurrent_decision(route):
        if route.request.method == "PUT":
            current = service.review(reviewer, published[3])
            body = ReviewWrite(verdict="REPEAT", scope="Otro revisor", justification="Repetir adquisición",
                               scientific_digest=current.body["scientific_digest"])
            service.write_review(reviewer, published[3], body, current.etag, "concurrent-decision")
            calls.append(route.request.headers["if-match"])
        route.continue_()

    page.route("**/v1/review-cases/*", concurrent_decision)
    fill_review(page, "Texto que debe conservarse tras HTTP 412")
    page.locator("#review-submit").click()
    expect(page.locator("#message")).to_contain_text("VERSION_MISMATCH")
    expect(page.locator("#conflict")).to_be_visible()
    expect(page.locator("#justification")).to_have_value("Texto que debe conservarse tras HTTP 412")
    expect(page.locator("#review-history")).to_contain_text("Repetir adquisición")
    expect(page.locator("#review-submit")).to_be_disabled()
    assert len(calls) == 1
    page.unroute("**/v1/review-cases/*", concurrent_decision)
    current = service.review(reviewer, published[3])
    service.reopen(reviewer, published[3], Reopening(expected_version=current.body["version"],
                                                   reason="Relectura explícita de evidencia"), "reopen-for-draft")
    expect(page.locator("#review-state")).to_contain_text("PENDING", timeout=10000)
    expect(page.locator("#review-submit")).to_be_disabled()
    page.locator("#rebase").click()
    expect(page.locator("#justification")).to_have_value("Texto que debe conservarse tras HTTP 412")
    page.locator("#review-submit").click()
    expect(page.locator("#message")).to_contain_text("Revisión confirmada")
    history = service.review(reviewer, published[3]).body["history"]
    assert len(history) == 3 and history[-1]["content"]["verdict"] == "ACCEPTED"


def test_review_response_lost_after_commit_retries_exact_command(web, backend, published):
    page, _, _ = web
    open_published(page, backend, published)
    calls = []

    def lose_first_response(route):
        if route.request.method != "PUT":
            return route.continue_()
        calls.append((route.request.headers["idempotency-key"], route.request.headers["if-match"], route.request.post_data))
        if len(calls) == 1:
            response = route.fetch()
            assert response.status == 200
            route.abort("failed")
        else:
            route.continue_()

    page.route("**/v1/review-cases/*", lose_first_response)
    fill_review(page, "Réponse perdue <script>alert(1)</script>")
    page.locator("#review-submit").click()
    expect(page.locator("#review-submit")).to_have_text("Reintentar la misma revisión")
    expect(page.locator("#justification")).to_be_disabled()
    page.locator("#review-submit").click()
    expect(page.locator("#message")).to_contain_text("Revisión confirmada")
    expect(page.locator("#review-history")).to_contain_text("<script>alert(1)</script>")
    assert len(calls) == 2 and calls[0] == calls[1]
    assert len(backend[0].review(backend[3], published[3]).body["history"]) == 1


def test_detail_cursor_filters_conditional_reads_and_mobile(web, backend, published):
    page, _, _ = web
    open_published(page, backend, published)
    responses = []
    page.on("response", lambda response: responses.append(response.status) if "/v1/review-cases/" in response.url else None)
    page.locator("#collection").select_option("points")
    page.locator("#detail-form button").click()
    expect(page.locator("#detail-results article")).to_have_count(25)
    expect(page.locator("#detail-results")).to_contain_text('"frequency_hz"')
    first_page = page.locator("#detail-results").inner_text()
    page.locator("#next-page").click()
    expect(page.locator("#detail-results")).not_to_have_text(first_page)
    page.locator("#frequency-min").fill("100000")
    page.locator("#detail-form button").click()
    expect(page.locator("#detail-results")).to_have_text("Sin elementos para este filtro.")
    page.locator("#collection").select_option("traces")
    expect(page.locator("#frequency-min")).to_be_disabled()
    page.locator("#detail-form button").click()
    expect(page.locator("#detail-results article")).to_have_count(24)
    page.screenshot(path=str(ROOT / "evidence/app_local/web_desktop.png"))
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path=str(ROOT / "evidence/app_local/web_mobile.png"))
    page.wait_for_function("document.querySelector('#connection').textContent.includes('Lectura confirmada')")
    # At least one unchanged review poll must use the representation cached in this tab.
    deadline = time.monotonic() + 8
    while 304 not in responses and time.monotonic() < deadline:
        page.wait_for_timeout(100)
    assert 304 in responses
    assert page.evaluate("Object.keys(localStorage).length + Object.keys(sessionStorage).length") == 0


def test_unknown_scientific_state_blocks_review(web, backend, published):
    page, _, _ = web
    connect(page, backend[1]["reviewer"]["token"])
    run = backend[0].get(backend[2], "processing_runs", published[0])

    def future_schema(route):
        response = route.fetch()
        body = response.json()
        body["summary"]["scientific_status"] = "FUTURE_UNKNOWN_STATUS"
        route.fulfill(response=response, json=body)

    page.route(f"**/v1/dossiers/{run['dossier_id']}", future_schema)
    page.locator("#dossier-id").fill(run["dossier_id"])
    page.get_by_role("button", name="Abrir", exact=True).click()
    expect(page.locator("#unsupported")).to_be_visible()
    expect(page.locator("#science-summary")).to_contain_text("FUTURE_UNKNOWN_STATUS")
    expect(page.locator("#review-submit")).to_be_disabled()
    assert not backend[0].review(backend[3], published[3]).body["history"]
