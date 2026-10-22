"""Immutable detail paging, scientific fidelity, HTTP cache and access checks."""
from __future__ import annotations

import copy
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from geoqc.core.evidence import canonical_hash
from geoqc_app.api import create_app
from geoqc_app.cursors import CursorSigner
from geoqc_app.dossiers import MAX_PAGE_BYTES, NATIVE_VECTORS, Dossiers, detail_page, encoded
from geoqc_app.errors import AppError
from geoqc_app.storage import ArtifactStore
from tools.tests.test_app_backend import ROOT
from tools.tests.test_app_backend import backend as backend
from tools.tests.test_app_backend import published as published


@pytest.fixture
def document():
    return json.loads((ROOT / "evidence/app_local/adapter/runs/20261015T045324Z_2750c032/e5_dossier.json").read_bytes())


def resign(document):
    document["scientific_digest"] = canonical_hash({k: v for k, v in document.items() if k != "scientific_digest"})


def collect(document, *, collection="points", limit=3, **kwargs):
    identifier, signer, cursor = uuid.uuid4(), CursorSigner(b"x" * 32), None
    rows, pages = [], []
    while True:
        reply = detail_page(document, identifier, signer, collection=collection, cursor=cursor, limit=limit, **kwargs)
        body = reply.body
        pages.append(body)
        rows.extend(body[collection.replace("-", "_")])
        cursor = body["next_cursor"]
        if cursor is None:
            return rows, pages


def test_all_grid_points_are_preserved_without_duplicates(document):
    actual, pages = collect(document, record_index=0)
    expected = [{"direction": group["direction"], "index": i, "value": value}
                for group in document["diagnostic_quality"][0]["apparent_usability"]["directions"]
                for i, value in enumerate(group["points"])]
    assert actual == expected
    assert all(page["scientific_digest"] == document["scientific_digest"] for page in pages)
    assert all(page["eligible_for_acceptance"] is False and page["sufficiency"] == {"status": "NOT_DEMONSTRATED"}
               for page in pages)
    assert pages[0]["units"]["signed_q_m_inv"] == "1/m"
    assert pages[0]["units"]["grid_velocity_ms"] == "m/s"
    assert "sensitivity_variant_order" in pages[0]["context"]


def test_native_refined_values_keep_their_original_fields(document):
    actual, _ = collect(document, collection="native-points", record_index=0, limit=2)
    curves = document["diagnostic_quality"][0]["native_diagnostics"]["curves"]
    assert len(actual) == sum(len(curve["frequencies_hz"]) for curve in curves)
    for point in actual:
        curve = curves[point["curve_index"]]
        index = point["index"]
        assert point["values"] == {key: curve[key][index] for key in NATIVE_VECTORS}
        assert point["frequency_hz"] == curve["frequencies_hz"][index]
        assert point["significance"]["validity"] == curve["significance"]["validity"]
        assert point["band_controls"]["data"] == curve["band_controls"]["data"][index]


def test_record_summaries_page_four_shots_without_frequency_arrays(document):
    record = document["diagnostic_quality"][0]
    document["diagnostic_quality"] = [copy.deepcopy(record) for _ in range(4)]
    for index, value in enumerate(document["diagnostic_quality"]):
        value["shot_id"] = f"projection-fixture-{index}"
    resign(document)
    rows, pages = collect(document, collection="records", limit=1)
    assert [row["record_index"] for row in rows] == list(range(4))
    assert [row["shot_id"] for row in rows] == [f"projection-fixture-{i}" for i in range(4)]
    assert all(page["total_items"] == 4 for page in pages)
    assert all("curves" not in row["native_diagnostics"] for row in rows)
    assert all("directions" not in row["apparent_usability"] for row in rows)
    assert rows[0]["directions"][0]["counts"] == record["apparent_usability"]["directions"][0]["counts"]


def test_frequency_direction_filter_and_empty_range(document):
    rows, _ = collect(document, record_index=0, direction=-1, frequency_min_hz=12, frequency_max_hz=20)
    expected = [{"direction": group["direction"], "index": i, "value": value}
                for group in document["diagnostic_quality"][0]["apparent_usability"]["directions"] if group["direction"] == -1
                for i, value in enumerate(group["points"]) if 12 <= value["frequency_hz"] <= 20]
    assert rows == expected
    rows, pages = collect(document, record_index=0, frequency_min_hz=100000)
    assert rows == [] and pages[0]["total_items"] == 0 and pages[0]["next_cursor"] is None


def test_bands_and_trace_observations_keep_support_and_missing_values(document):
    record = document["diagnostic_quality"][0]
    traces, _ = collect(document, collection="traces", record_index=0, limit=5)
    assert traces == record["trace_observations"]
    bands, _ = collect(document, collection="bands", record_index=0, limit=2)
    assert bands == [{"direction": group["direction"], "index": i, "value": value}
                     for group in record["apparent_usability"]["directions"] for i, value in enumerate(group["bands"])]
    first = record["apparent_usability"]["directions"][0]["points"][0]
    first.update(grid_velocity_ms=None, grade="NO_EVALUABLE", reasons=["NO_VALID_SUPPORT"])
    resign(document)
    points, _ = collect(document, record_index=0, limit=1)
    assert points[0]["value"]["grid_velocity_ms"] is None
    assert points[0]["value"]["reasons"] == ["NO_VALID_SUPPORT"]


def test_page_byte_budget_reduces_items_without_losing_positions(document):
    group = document["diagnostic_quality"][0]["apparent_usability"]["directions"][0]
    value = group["points"][0]
    group["points"] = [dict(value, frequency_hz=float(i + 1), reasons=["x" * 10000]) for i in range(100)]
    document["diagnostic_quality"][0]["apparent_usability"]["directions"] = [group]
    resign(document)
    rows, pages = collect(document, record_index=0, limit=100)
    assert [row["index"] for row in rows] == list(range(100))
    assert len(pages) > 1 and all(len(encoded(page)) <= MAX_PAGE_BYTES for page in pages)
    group["points"][0]["reasons"] = ["x" * MAX_PAGE_BYTES]
    resign(document)
    with pytest.raises(AppError) as error:
        collect(document, record_index=0, limit=1)
    assert error.value.code == "DETAIL_ITEM_TOO_LARGE"


def test_cursor_binds_digest_dossier_collection_and_filters(document):
    identifier, signer = uuid.uuid4(), CursorSigner(b"x" * 32)
    first = detail_page(document, identifier, signer, collection="points", record_index=0, limit=1)
    cursor = first.body["next_cursor"]
    altered = copy.deepcopy(document)
    altered["scientific_digest"] = "f" * 64
    cases = [lambda: detail_page(document, uuid.uuid4(), signer, collection="points", record_index=0, cursor=cursor),
             lambda: detail_page(altered, identifier, signer, collection="points", record_index=0, cursor=cursor),
             lambda: detail_page(document, identifier, signer, collection="bands", record_index=0, cursor=cursor),
             lambda: detail_page(document, identifier, signer, collection="points", record_index=0, cursor=cursor, direction=1),
             lambda: detail_page(document, identifier, signer, collection="points", record_index=0, cursor=cursor, frequency_min_hz=8)]
    for call in cases:
        with pytest.raises(AppError) as error:
            call()
        assert error.value.code == "INVALID_DETAIL_CURSOR"
    # Page size may change; the cursor remains an immutable collection position.
    second = detail_page(document, identifier, signer, collection="points", record_index=0, cursor=cursor, limit=2)
    assert len(second.body["points"]) == 2 and second.body["points"][0]["index"] == 1


@pytest.mark.parametrize("cursor", ["", "garbage", "a.b.c", "x" * 2049, "a." + "0" * 64])
def test_malformed_cursors_fail_safely(document, cursor):
    with pytest.raises(AppError) as error:
        detail_page(document, uuid.uuid4(), CursorSigner(b"x" * 32), cursor=cursor)
    assert error.value.code == "INVALID_DETAIL_CURSOR"


def test_cursor_key_creation_is_atomic_and_restart_stable(tmp_path):
    barrier = Barrier(4)
    def key(_):
        store = ArtifactStore(tmp_path)
        barrier.wait()
        return store.cursor_key()
    with ThreadPoolExecutor(max_workers=4) as executor:
        keys = list(executor.map(key, range(4)))
    assert len(set(keys)) == 1 and len(keys[0]) == 32
    assert ArtifactStore(tmp_path).cursor_key() == keys[0]
    assert not list(tmp_path.glob("*.writing"))


def dossier_id(backend, published):
    return uuid.UUID(backend[0].get(backend[2], "processing_runs", published[0])["dossier_id"])


def test_http_detail_conditional_cache_and_restart(backend, published):
    service, credentials, _, reviewer = backend
    identifier = dossier_id(backend, published)
    headers = {"Authorization": "Bearer " + credentials["reviewer"]["token"]}
    with TestClient(create_app(service.settings)) as client:
        header = client.get(f"/v1/dossiers/{identifier}", headers=headers)
        assert header.status_code == 200 and header.headers["ETag"]
        assert client.get(f"/v1/dossiers/{identifier}", headers=headers | {
            "If-None-Match": header.headers["ETag"]}).status_code == 304
        url = f"/v1/dossiers/{identifier}/records/0/points"
        first = client.get(url, headers=headers, params={"limit": 1})
        assert first.status_code == 200, first.text
        assert len(first.content) <= MAX_PAGE_BYTES
        cursor = first.json()["next_cursor"]
        cached = client.get(url, headers=headers | {"If-None-Match": '"other", W/' + first.headers["ETag"]}, params={"limit": 1})
        assert cached.status_code == 304 and cached.content == b""
        assert cached.headers["ETag"] == first.headers["ETag"]
        assert "private" in cached.headers["Cache-Control"]
    with TestClient(create_app(service.settings)) as restarted:
        second = restarted.get(url, headers=headers, params={"limit": 1, "cursor": cursor})
        assert second.status_code == 200 and second.json()["points"][0]["index"] == 1
    assert Dossiers(service).signer.key == service.store.cursor_key()
    assert service.review(reviewer, published[3]).body["state"] == "PENDING"


def test_http_invalid_filters_offset_and_tampered_cursor(backend, published):
    service, credentials, _, _ = backend
    identifier = dossier_id(backend, published)
    headers = {"Authorization": "Bearer " + credentials["operator"]["token"]}
    with TestClient(create_app(service.settings)) as client:
        base = f"/v1/dossiers/{identifier}/records"
        assert client.get(base, headers=headers, params={"offset": 0}).json()["code"] == "OFFSET_PAGINATION_REMOVED"
        url = base + "/0/points"
        for query in ({"limit": 101}, {"limit": 0}, {"direction": 0}, {"frequency_min_hz": "nan"},
                      {"frequency_min_hz": "inf"}, {"frequency_min_hz": 12, "frequency_max_hz": 8}):
            assert client.get(url, headers=headers, params=query).status_code == 422
        assert client.get(base + "/9/points", headers=headers).status_code == 404
        first = client.get(url, headers=headers, params={"limit": 1}).json()
        token = first["next_cursor"]
        bad = ("A" if token[0] != "A" else "B") + token[1:]
        assert client.get(url, headers=headers, params={"cursor": bad}).json()["code"] == "INVALID_DETAIL_CURSOR"
        assert client.get(base + "/0/traces", headers=headers, params={"direction": 1}).status_code == 422
        assert client.get(base + "/0/native-points", headers=headers, params={"limit": 2}).status_code == 200
        assert client.get(base + "/0/bands", headers=headers, params={"limit": 2}).status_code == 200


def test_authorization_precedes_cursor_and_conditional_cache(backend, published):
    service, credentials, _, reviewer = backend
    identifier = dossier_id(backend, published)
    other = service.bootstrap()
    with TestClient(create_app(service.settings)) as client:
        url = f"/v1/dossiers/{identifier}/records/0/points"
        allowed = {"Authorization": "Bearer " + credentials["reviewer"]["token"]}
        etag = client.get(url, headers=allowed).headers["ETag"]
        outside = {"Authorization": "Bearer " + other["operator"]["token"], "If-None-Match": etag}
        assert client.get(url, headers=outside, params={"cursor": "malformed"}).status_code == 404
        with service.db.connect() as conn:
            conn.execute("DELETE FROM memberships WHERE user_id=%s", (reviewer.id,))
        assert client.get(url, headers=allowed | {"If-None-Match": etag}).status_code == 404


def test_corrupt_source_cannot_return_cached_304(backend, published):
    service, credentials, _, _ = backend
    identifier = dossier_id(backend, published)
    headers = {"Authorization": "Bearer " + credentials["operator"]["token"]}
    with TestClient(create_app(service.settings)) as client:
        url = f"/v1/dossiers/{identifier}"
        etag = client.get(url, headers=headers).headers["ETag"]
        with service.db.connect() as conn:
            row = conn.execute("SELECT a.storage_key FROM artifacts a JOIN dossiers d ON d.artifact_id=a.id WHERE d.id=%s",
                               (identifier,)).fetchone()
        path = service.store.path(row["storage_key"])
        original = path.read_bytes()
        try:
            path.write_bytes(original + b" ")
            response = client.get(url, headers=headers | {"If-None-Match": etag})
            assert response.status_code == 409 and response.json()["code"] == "ARTIFACT_INTEGRITY"
        finally:
            path.write_bytes(original)
