"""TRS selection, native picking fidelity and real worker/browser integration."""
import io
import json
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect
from pydantic import ValidationError
from pypdf import PdfReader

from geoqc.io.readers import read_shot
from geoqc.trs.contracts import PickProtocol, TRSProtocol
from geoqc.trs.report import trs_diagnostics
from geoqc_app.api import create_app
from geoqc_app.dossiers import Dossiers
from geoqc_app.models import AcquisitionCreate, ReviewWrite, RevisionCreate, RunCreate
from geoqc_app.render_exports import render_export
from geoqc_app.worker import Worker
from tools.tests.test_app_backend import ROOT
from tools.tests.test_app_backend import backend as backend
from tools.tests.test_app_web import browser as browser
from tools.tests.test_app_web import connect
from tools.tests.test_app_web import web as web

DEMO = ROOT / "examples/km_app/demo_trs_f1"


def enqueue(backend, *, technique="TRS", trace_qc_request=None):
    service, credentials, operator, _ = backend
    acquisition = service.create_acquisition(operator, AcquisitionCreate(
        project_id=credentials["project_id"], name="TRS KM F1"), "trs-acquisition")
    acquisition_id = UUID(acquisition.body["id"])
    upload = UUID(service.create_upload(operator, acquisition_id, "trs-upload").body["id"])
    for kind, name in (("waveform", "km40_f1_trs_exploratory.sgy"),
                       ("sidecar", "km40_f1_trs_exploratory.sgy.json")):
        service.attach_part(operator, upload, kind, service.store.put((DEMO / name).read_bytes()))
    service.complete_upload(operator, upload, "trs-complete")
    revision = service.create_revision(operator, acquisition_id, RevisionCreate(uploads=(upload,)), "trs-revision")
    body = {"technique": technique, "protocol": json.loads((DEMO / "protocol.json").read_bytes())}
    if trace_qc_request is not None:
        body["trace_qc"] = trace_qc_request
    if technique == "MASW":
        body.update(protocol=json.loads((ROOT / "examples/e5/protocol.json").read_bytes()),
                    excluded_receiver_ids=["ch24"])
    request = RunCreate(revision_id=revision.body["id"], **body)
    run = service.create_run(operator, request, "trs-run")
    assert service.create_run(operator, request, "trs-run") == run
    assert Worker(service).run_once()
    return service.get(operator, "processing_runs", UUID(run.body["id"]))


def test_trs_worker_preserves_native_arrivals_and_scientific_abstentions(backend):
    service, _, operator, reviewer = backend
    run = enqueue(backend)
    assert run["state"] == "SUCCEEDED", run["error_code"]
    _, document, review_id = Dossiers(service).load(operator, UUID(run["dossier_id"]))
    protocol = TRSProtocol.model_validate(json.loads((DEMO / "protocol.json").read_bytes()))
    shot = read_shot(DEMO / "km40_f1_trs_exploratory.sgy")
    assert document["diagnostic_quality"][0]["diagnostics"] == json.loads(
        json.dumps(trs_diagnostics(shot, protocol), allow_nan=False))
    picks = document["diagnostic_quality"][0]["diagnostics"]["picks"]
    assert len(picks) == 24
    assert any(p["arrival"]["onset_s"] is not None for p in picks)
    assert all(p["arrival"]["sigma_s"] is None for p in picks)
    assert "POST_SIGNAL_NOISE_WINDOW_NOT_FIELD_VALIDATED" in document["missing_evidence"]
    assert document["protocol"]["picking"]["noise_position"] == "DECLARED_POST_SIGNAL"
    before = service.review(reviewer, review_id)
    service.write_review(reviewer, review_id, ReviewWrite(
        verdict="ACCEPTED", scope="TRS diagnóstica", justification="Examinar primeros arribos",
        caveats=("Geometría idealizada, ruido posterior no validado y amplitud provisional",),
        scientific_digest=document["scientific_digest"]), before.etag, "trs-review")
    assert Dossiers(service).load(operator, UUID(run["dossier_id"]))[1] == document


def test_trs_http_detail_cursor_exports_and_method_isolation(backend):
    service, credentials, _, _ = backend
    run = enqueue(backend)
    headers = {"Authorization": "Bearer " + credentials["operator"]["token"]}
    with TestClient(create_app(service.settings)) as client:
        url = f"/v1/dossiers/{run['dossier_id']}"
        header = client.get(url, headers=headers)
        assert header.json()["summary"]["method"] == "TRS"
        assert client.get(url, headers=headers | {"If-None-Match": header.headers["etag"]}).status_code == 304
        all_picks, cursor = [], None
        while True:
            params = {"limit": 5} | ({"cursor": cursor} if cursor else {})
            response = client.get(url + "/records/0/arrivals", headers=headers, params=params)
            assert response.status_code == 200, response.text
            page = response.json()
            assert page["units"]["onset_s"] == "s"
            all_picks.extend(page["arrivals"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
        assert len(all_picks) == len({p["receiver_id"] for p in all_picks}) == 24
        assert client.get(url + "/records/0/points", headers=headers).status_code == 422
        assert client.get(url + "/records/0/arrivals?direction=1", headers=headers).status_code == 422
        assert client.get(url + "/records/0/arrivals").status_code == 401
    document = Dossiers(service).load(backend[2], UUID(run["dossier_id"]))[1]
    assert "dosier TRS" in render_export(document, "HTML").decode()
    assert "GeoQC - TRS" in PdfReader(io.BytesIO(render_export(document, "PDF"))).pages[0].extract_text()
    assert document["scientific_digest"] in render_export(document, "CSV").decode()


def test_method_mismatch_is_rejected_before_publishing(backend):
    run = enqueue(backend, technique="MASW")
    assert run["state"] == "FAILED" and run["dossier_id"] is None


def test_protocols_do_not_silently_change_technique_or_noise_reference():
    protocol = json.loads((DEMO / "protocol.json").read_bytes())
    with pytest.raises(ValidationError):
        RunCreate(revision_id="00000000-0000-0000-0000-000000000001", protocol=protocol,
                  excluded_receiver_ids=["ch24"])
    normal = protocol["picking"] | {"noise_position": "PRE_SEARCH"}
    with pytest.raises(ValidationError, match="preceder"):
        PickProtocol.model_validate(normal)
    overlap = protocol["picking"] | {"noise": {"start_s": 0.2, "end_s": 0.4}}
    with pytest.raises(ValidationError, match="solaparse"):
        PickProtocol.model_validate(overlap)


def test_browser_trs_upload_arrivals_and_wrong_sidecar_before_writes(web, backend):
    page, _, _ = web
    connect(page, backend[1]["operator"]["token"])
    page.locator("#technique").select_option("TRS")
    expect(page.locator("#protocol-label")).to_have_text("Protocolo TRS JSON")
    expect(page.locator("#exclusions-label")).to_be_hidden()
    page.locator("#project").fill(backend[1]["project_id"])
    page.locator("#name").fill("TRS F1 desde Chromium")
    page.locator("#waveform-0").set_input_files(DEMO / "km40_f1_trs_exploratory.sgy")
    page.locator("#sidecar-0").set_input_files(DEMO / "assumptions.json")
    page.locator("#protocol").set_input_files(DEMO / "protocol.json")
    page.locator("#trace-qc").set_input_files(DEMO / "trace_qc.json")
    page.locator("#upload-submit").click()
    expect(page.locator("#message")).to_contain_text("no assumptions.json")
    with backend[0].db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM acquisitions").fetchone()["n"] == 0
    page.locator("#sidecar-0").set_input_files(DEMO / "km40_f1_trs_exploratory.sgy.json")
    page.locator("#upload-submit").click()
    expect(page.locator("#upload-progress")).to_contain_text("Carga confirmada", timeout=15000)
    assert Worker(backend[0]).run_once()
    expect(page.locator("#review-section")).to_be_visible(timeout=15000)
    expect(page.locator("#run-status")).to_contain_text("SUCCEEDED")
    expect(page.locator("#dossier-title")).to_be_in_viewport()
    expect(page.locator("#detail-results article")).to_have_count(1)
    expect(page.locator("#detail-results")).to_contain_text('"shot_id"')
    page.locator("#dossier-form button").click()
    expect(page.locator("#dossier-title")).to_be_in_viewport()
    expect(page.locator("#trs-visuals .trs-pick")).to_have_count(5)
    expect(page.locator("#trs-visuals .qc-table tbody tr")).to_have_count(24)
    expect(page.locator("#trs-visuals .qc-overview")).to_contain_text("Resumen de calidad por registro y tendido")
    expect(page.locator("#trs-visuals .qc-criteria")).to_contain_text("TRACE_QUALITY_V1_DRAFT")
    expect(page.locator("#trs-visuals .qc-criteria")).to_contain_text("≥12 dB")
    expect(page.locator("#trs-visuals .qc-diagnostics .qc-chart")).to_have_count(7)
    expect(page.locator("#trs-visuals .qc-actions")).to_contain_text("requiere pares físicos")
    expect(page.locator("#trs-visuals .qc-table")).to_contain_text("Rails/escala desconocidos")
    page.get_by_label("Filtrar canales por calidad", exact=True).select_option("MALA")
    expect(page.locator("#trs-visuals .qc-table tbody tr:visible")).to_have_count(0)
    page.get_by_label("Filtrar canales por calidad", exact=True).select_option("")
    expect(page.locator("#trs-visuals .qc-table tbody tr:visible")).to_have_count(24)
    expect(page.locator("#trs-visuals .qc-gather svg")).to_be_visible()
    page.get_by_label("Ventana de visualización QC", exact=True).select_option("search")
    expect(page.locator("#trs-visuals .qc-gather svg")).to_contain_text("500")
    page.get_by_label("Canal QC", exact=True).select_option("ch11")
    expect(page.locator("#trs-visuals .qc-inspected")).to_contain_text("ch11")
    expect(page.locator("#trs-visuals .qc-inspected")).to_contain_text("SNR: MISSING")
    expect(page.locator("#trs-visuals .qc-spectrum svg")).to_be_visible()
    expect(page.locator("#trs-visuals .trs-arrivals-table tbody tr")).to_have_count(24)
    expect(page.locator("#trs-visuals .trs-pick-counts")).to_contain_text("17 Ambiguo")
    expect(page.locator("#trs-visuals .trs-pick-counts")).to_contain_text("2 Sin llegada")
    expect(page.locator('#trs-visuals .trs-arrivals-table tr[data-receiver="ch01"]')).to_contain_text("10,375")
    expect(page.locator('#trs-visuals .trs-arrivals-table tr[data-receiver="ch11"]')).to_contain_text("—")
    page.locator('#trs-visuals .trs-receivers button', has_text="ch11").click()
    expect(page.locator("#trs-visuals .trs-selection")).to_contain_text("ch11 · AMBIGUOUS")
    page.locator('#trs-visuals .trs-pick[data-receiver="ch01"]').focus()
    page.keyboard.press("Enter")
    expect(page.locator("#trs-visuals .trs-selection")).to_contain_text("ch01 · UNCALIBRATED")
    page.locator("#technical-details > summary").click()
    page.locator("#collection").select_option("arrivals")
    page.locator("#detail-form button").click()
    expect(page.locator("#detail-results article")).to_have_count(24)
    expect(page.locator("#detail-results")).to_contain_text('"onset_s"')
    expect(page.locator("#frequency-min")).to_be_disabled()


@pytest.mark.parametrize("server_rejection", [False, True])
def test_browser_project_validation_preserves_files_and_allows_correction(web, backend, server_rejection):
    page, _, _ = web
    connect(page, backend[1]["operator"]["token"])
    page.locator("#technique").select_option("TRS")
    page.locator("#project").fill(backend[1]["project_id"] if server_rejection else "a-token-is-not-a-project")
    page.locator("#name").fill("TRS corregido")
    page.locator("#trace-qc").set_input_files(DEMO / "trace_qc.json")
    page.locator("#waveform-0").set_input_files(DEMO / "km40_f1_trs_exploratory.sgy")
    page.locator("#sidecar-0").set_input_files(DEMO / "km40_f1_trs_exploratory.sgy.json")
    page.locator("#protocol").set_input_files(DEMO / "protocol.json")
    if server_rejection:
        page.route("**/v1/acquisitions", lambda route: route.fulfill(
            status=422, json={"code": "INVALID_REQUEST", "message": "Solicitud incompatible con el contrato"}))
    page.locator("#upload-submit").click()
    expect(page.locator("#message")).to_contain_text("INVALID_REQUEST" if server_rejection else "Proyecto debe ser un UUID")
    expect(page.locator("#project")).to_be_enabled()
    expect(page.locator("#upload-submit")).to_have_text("Cargar y procesar")
    assert page.locator("#waveform-0").evaluate("input => input.files[0].name") == "km40_f1_trs_exploratory.sgy"
    with backend[0].db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM acquisitions").fetchone()["n"] == 0
    page.unroute("**/v1/acquisitions")
    page.locator("#project").fill(backend[1]["project_id"])
    page.locator("#upload-submit").click()
    expect(page.locator("#upload-progress")).to_contain_text("Carga confirmada", timeout=15000)
    with backend[0].db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM acquisitions").fetchone()["n"] == 1
