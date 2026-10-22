"""Native QC fidelity, conservative fallbacks, display reductions and HTTP bounds."""
import copy
import io
import json
from uuid import UUID

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pypdf import PdfReader

from geoqc.core.evidence import canonical_hash
from geoqc.io.readers import read_shot
from geoqc.qc.adapter import TraceQCRequest, trace_qc, waveform_preview
from geoqc.qc.contracts import SimilarityProtocol
from geoqc.qc.noise import noise_diagnostics
from geoqc.qc.quality import assess_quality
from geoqc.qc.report import common_qc
from geoqc.trs.adapter import build_trs_dossier
from geoqc.trs.contracts import TRSProtocol
from geoqc_app.api import create_app
from geoqc_app.dossiers import Dossiers
from geoqc_app.models import RunCreate
from geoqc_app.render_exports import render_export
from geoqc_app.worker import Worker
from tools.build_km_demo import demo_trace_qc
from tools.report_trace_quality import synthetic_shot
from tools.tests.test_app_backend import backend as backend
from tools.tests.test_app_trs import DEMO, enqueue
from tools.tests.test_app_web import browser as browser
from tools.tests.test_app_web import web as web


@pytest.fixture(scope="module")
def km_qc_dossier():
    shot = read_shot(DEMO / "km40_f1_trs_exploratory.sgy")
    return build_trs_dossier((shot,), TRSProtocol.model_validate_json((DEMO / "protocol.json").read_bytes()),
                             "offline-km-qc", {"scope": "OFFLINE_EXAMPLE"},
                             TraceQCRequest.model_validate(demo_trace_qc()))


@pytest.mark.parametrize("format", ["HTML", "PDF"])
def test_export_presents_published_trace_and_spread_assessments(km_qc_dossier, format):
    before = copy.deepcopy(km_qc_dossier)
    rendered = render_export(km_qc_dossier, format)
    text = rendered.decode("utf-8") if format == "HTML" else "\n".join(
        p.extract_text() for p in PdfReader(io.BytesIO(rendered)).pages)
    assert "Calificación por traza y tendido" in text
    assert "Conjunto de registros: " + km_qc_dossier["trace_qc_assessment"]["grade"] in text
    for trace in km_qc_dossier["diagnostic_quality"][0]["trace_qc"]["traces"]:
        assert f"{trace['receiver_id']}: {trace['quality']['assessment_grade']}" in text
    assert "Evidencia pendiente:" in text
    assert "NOT_REQUESTED_REQUIRES_PHYSICAL_PAIRS" in text
    assert km_qc_dossier == before


def test_qc_summary_escapes_identifiers_and_reads_historical_dossiers(km_qc_dossier):
    document = copy.deepcopy(km_qc_dossier)
    document["diagnostic_quality"][0]["shot_id"] = "<script>km</script>"
    document["scientific_digest"] = canonical_hash({k: v for k, v in document.items() if k != "scientific_digest"})
    rendered = render_export(document, "HTML").decode("utf-8")
    assert "<script>" not in rendered
    assert "&lt;script&gt;km&lt;/script&gt;" in rendered
    del document["diagnostic_quality"][0]["trace_qc"]
    del document["trace_qc_assessment"]
    document["scientific_digest"] = canonical_hash({k: v for k, v in document.items() if k != "scientific_digest"})
    assert "histórico sin QC por traza" in render_export(document, "HTML").decode("utf-8")


def test_portable_qc_report_renders_same_criteria_charts_and_filters_offline(km_qc_dossier, browser, tmp_path):
    path = tmp_path / "km-report.html"
    path.write_bytes(render_export(km_qc_dossier, "HTML"))
    with browser.new_context() as context:
        page = context.new_page()
        errors, network = [], []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: network.append(r.url) if r.url.startswith(("http:", "https:")) else None)
        page.goto(path.as_uri())
        page.locator(".qc-criteria").wait_for()
        assert "≥12 dB" in page.locator(".qc-criteria").inner_text()
        assert page.locator(".qc-chart").count() == 7
        assert page.locator(".qc-gather svg").count() == 1
        assert page.locator(".qc-overview tbody tr").count() == 1
        assert "Sin verificar" in page.locator(".qc-criteria").inner_text()
        page.get_by_label("Filtrar canales por calidad", exact=True).select_option("MALA")
        assert page.locator(".qc-table tbody tr:visible").count() == 0
        page.get_by_label("Filtrar canales por calidad", exact=True).select_option("")
        assert page.locator(".qc-table tbody tr:visible").count() == 24
        page.get_by_label("Canal QC", exact=True).select_option("ch11")
        assert "ch11" in page.locator(".qc-inspected").inner_text()
        assert page.locator(".qc-spectrum svg").count() == 1
        assert page.locator("#fallback").is_hidden()
        assert errors == [] and network == []


def test_historical_deep_link_opens_current_report_with_authenticated_popup(web, backend):
    from playwright.sync_api import expect

    service, credentials, actor, _ = backend
    first = enqueue(backend)
    _, document, _ = Dossiers(service).load(actor, UUID(first["dossier_id"]))
    request = RunCreate(revision_id=document["acquisition_revision_id"], technique="TRS",
                        protocol=document["protocol"], trace_qc=demo_trace_qc())
    reply = service.create_run(actor, request, "current-qc")
    assert Worker(service).run_once()
    current = service.get(actor, "processing_runs", UUID(reply.body["id"]))
    assert current["state"] == "SUCCEEDED"
    with TestClient(create_app(service.settings)) as client:
        url = f"/v1/dossiers/{current['dossier_id']}/quality-report"
        assert client.get(url).status_code == 401
        response = client.get(url, headers={"Authorization": "Bearer " + credentials["operator"]["token"]})
        assert response.status_code == 200 and "text/html" in response.headers["content-type"]
        assert "Dosier TRS" in response.text
    page, _, _ = web
    page.goto("/?dossier=" + first["dossier_id"])
    expect(page.locator("#dossier-id")).to_have_value(first["dossier_id"])
    page.locator("#token").fill(credentials["operator"]["token"])
    page.get_by_role("button", name="Conectar", exact=True).click()
    expect(page.locator("#historical-result")).to_be_visible()
    page.locator("#open-current-dossier").click()
    expect(page.locator("#dossier-id")).to_have_value(current["dossier_id"])
    expect(page.locator("#historical-result")).to_be_hidden()
    expect(page.locator(".qc-table tbody tr")).to_have_count(24)
    with page.expect_popup() as opened:
        page.locator("#open-quality-report").click()
    popup = opened.value
    expect(popup.locator(".qc-criteria")).to_be_visible()
    expect(popup.locator(".qc-table tbody tr")).to_have_count(24)
    assert popup.evaluate("window.opener === null")
    assert credentials["operator"]["token"] not in popup.url


def test_operational_worker_web_report_and_pdf_preserve_both_assessments(web, backend):
    from playwright.sync_api import expect

    run = enqueue(backend, trace_qc_request=demo_trace_qc(operational=True))
    assert run["state"] == "SUCCEEDED", run["error_code"]
    _, document, _ = Dossiers(backend[0]).load(backend[2], UUID(run["dossier_id"]))
    assert document["trace_qc_assessment"]["grade"] == "NO_EVALUABLE"
    assert document["operational_assessment"]["total_traces"] == 24
    assert not document["eligible_for_acceptance"]
    pdf = PdfReader(io.BytesIO(render_export(document, "PDF")))
    text = "\n".join(page.extract_text() for page in pdf.pages)
    assert "Calificación diagnóstica condicional del conjunto" in text
    assert "no confianza estadística" in " ".join(text.split())
    assert "Contraste estimado" in text and "Estimaciones y soporte" in text
    page, _, _ = web
    page.goto("/?dossier=" + run["dossier_id"])
    page.locator("#token").fill(backend[1]["operator"]["token"])
    page.get_by_role("button", name="Conectar", exact=True).click()
    expect(page.locator(".qc-operational")).to_be_visible()
    expect(page.locator(".qc-operational")).to_contain_text("TRS_SAMPLE_SCREENING_V1_DRAFT")
    expect(page.locator(".qc-chart")).to_have_count(10)
    expect(page.locator(".qc-operational table").last.locator("tbody tr")).to_have_count(24)
    expect(page.locator("#qc-global")).to_contain_text("QC estricto: NO_EVALUABLE")
    expect(page.locator("#qc-global")).to_contain_text("diagnóstica condicional")
    with page.expect_popup() as opened:
        page.locator("#open-quality-report").click()
    expect(opened.value.locator(".qc-operational")).to_be_visible()


def test_explicit_qc_reuses_native_quality_and_preserves_samples():
    shot, protocol, _ = synthetic_shot(18)
    data = shot.data.copy()
    similarity = SimilarityProtocol(arrival={"start_s": 0, "end_s": 0.5}, neighbor_radius_m=5,
                                   min_apparent_velocity_ms=100, max_lag_s=0.02,
                                   comparable_channels=True, reference="Explicit synthetic comparability")
    protocol = protocol.model_copy(update={"similarity": similarity})
    native = common_qc(shot, protocol)
    integrated = trace_qc(shot, TraceQCRequest(protocol=protocol))
    for actual, expected in zip(integrated["traces"], native["traces"], strict=True):
        assert {k: actual[k] for k in expected} == expected
    assert integrated["data_assessment"] == native["data_assessment"]
    assert integrated["traces"][-1]["quality"]["assessment_grade"] == "MALA"
    np.testing.assert_array_equal(shot.data, data)
    for j, trace in enumerate(integrated["traces"]):
        assert len(trace["waveform_preview"]["points"]) <= 256
        for index, value in trace["waveform_preview"]["points"]:
            assert value == shot.data[j, index]


def test_missing_metadata_is_not_bad_acquisition_or_picker_confidence():
    shot = read_shot(DEMO / "km40_f1_trs_exploratory.sgy")
    result = trace_qc(shot)
    assert result["protocol_source"] == "FULL_RECORD_INTEGRITY_ONLY"
    assert result["data_assessment"]["grade"] == "NO_EVALUABLE"
    assert result["data_assessment"]["demonstrated_bad_traces"] == 0
    assert result["data_assessment"]["good_percent_bounds"] == [0, 100]
    assert all(t["snr"]["state"] == "MISSING" for t in result["traces"])
    assert all(t["clip"]["state"] != "VALID" for t in result["traces"])


def test_posterior_noise_stays_conditional_and_masked_preview_breaks():
    shot = read_shot(DEMO / "km40_f1_trs_exploratory.sgy")
    request = TraceQCRequest.model_validate(demo_trace_qc())
    result = trace_qc(shot, request)
    native = noise_diagnostics(shot.data[0], shot.valid_mask[0], shot.dt_s[0], shot.t0_s[0], request.noise)
    assert result["traces"][0]["noise_diagnostics"] == native
    assert native["snr"]["state"] == "CONDITIONAL"
    assert not native["stationarity"]["transfer_to_signal_verified"]
    assert all(t["snr"]["state"] != "VALID" for t in result["traces"])
    assert all(t["similarity"]["state"] == "MISSING" for t in result["traces"])
    assert all(p["state"] == "MISSING" for p in result["noise_coherence"])
    mask = shot.valid_mask.copy()
    mask[0, 40] = False
    masked = shot.model_copy(update={"valid_mask": mask})
    assert waveform_preview(masked, 0)["points"][0][1] is None


def test_invalid_cross_method_or_mismatched_windows_fail_validation():
    request = demo_trace_qc()
    request["noise"]["noise"]["start_s"] = 1.6
    with pytest.raises(ValidationError, match="mismas ventanas"):
        TraceQCRequest.model_validate(request)
    with pytest.raises(ValidationError, match="requiere técnica TRS"):
        RunCreate(revision_id="00000000-0000-0000-0000-000000000001",
                  protocol=json.loads((DEMO.parents[1] / "e5/protocol.json").read_bytes()),
                  excluded_receiver_ids=["r0"], trace_qc=demo_trace_qc())


def test_worker_qc_snapshot_projection_pagination_and_immutable_digest(backend):
    run = enqueue(backend, trace_qc_request=demo_trace_qc())
    assert run["state"] == "SUCCEEDED", run["error_code"]
    service, credentials, actor, _ = backend
    _, document, _ = Dossiers(service).load(actor, UUID(run["dossier_id"]))
    qc = document["diagnostic_quality"][0]["trace_qc"]
    assert qc["protocol_source"] == "DECLARED"
    assert document["trace_qc_assessment"] == assess_quality(t["quality"] for t in qc["traces"])
    assert not document["eligible_for_acceptance"]
    headers = {"Authorization": "Bearer " + credentials["operator"]["token"]}
    with TestClient(create_app(service.settings)) as client:
        url = f"/v1/dossiers/{run['dossier_id']}/records/0/qc-traces"
        rows, cursor = [], None
        while True:
            response = client.get(url, params={"limit": 100} | ({"cursor": cursor} if cursor else {}), headers=headers)
            assert response.status_code == 200, response.text
            assert len(response.content) <= 256 * 1024
            page = response.json()
            rows.extend(page["qc_traces"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
        assert [r["receiver_id"] for r in rows] == [t["receiver_id"] for t in qc["traces"]]
        assert rows[0]["quality"] == qc["traces"][0]["quality"]
        assert len(rows[0]["noise_diagnostics"]["spectrum_preview"]["frequency_hz"]) <= 512
        assert "spectrum" not in rows[0]["noise_diagnostics"]
        assert client.get(url).status_code == 401
    assert Dossiers(service).load(actor, UUID(run["dossier_id"]))[1] == document
