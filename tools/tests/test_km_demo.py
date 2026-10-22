"""The assumed KM demo remains visibly exploratory through real worker processing."""
import json
from uuid import UUID

import numpy as np

from geoqc.io.readers import read_shot
from geoqc.masw.contracts import MASWProtocol
from geoqc.masw.transform import shot_spectrum
from geoqc_app.dossiers import Dossiers
from geoqc_app.models import AcquisitionCreate, RevisionCreate, RunCreate
from geoqc_app.worker import Worker
from tools.build_km_demo import ASSUMPTIONS
from tools.tests.test_app_backend import ROOT
from tools.tests.test_app_backend import backend as backend

DEMO = ROOT / "examples/km_app/demo_flat_f1"


def test_demo_has_explicit_assumptions_original_headers_and_exact_fft_window():
    shot = read_shot(DEMO / "km40_f1_exploratory.sgy")
    manifest = json.loads((DEMO / "manifest.json").read_bytes())
    protocol = MASWProtocol.model_validate(json.loads((DEMO / "protocol.json").read_bytes()))
    assert manifest["field_metadata_verified"] is False
    assert manifest["samples_unchanged"] is True
    assert np.all(shot.geometry.zr == 0) and shot.geometry.zs == 0
    assert shot.geometry.uncertainty_m == (0,) * 24
    assert shot.geometry.xs == -15 and shot.geometry.xr[-1] == 115
    assert ASSUMPTIONS in shot.geometry.provenance
    assert protocol.provenance == ASSUMPTIONS
    assert shot_spectrum(shot, protocol)["window_samples"] == 16000
    original = json.loads(json.loads(shot.headers_json)["context"]["original_headers_json"])
    assert original["trace_headers"][0]["STACK"] == "0"
    assert original["trace_headers"][0]["DESCALING_FACTOR"] == "1000"


def test_demo_is_processed_by_real_worker_without_losing_assumptions(backend):
    service, credentials, operator, _ = backend
    acquisition = service.create_acquisition(operator, AcquisitionCreate(
        project_id=credentials["project_id"], name="KM F1 EXPLORATORY ASSUMPTIONS"), "km-acquisition")
    acquisition_id = UUID(acquisition.body["id"])
    upload = UUID(service.create_upload(operator, acquisition_id, "km-upload").body["id"])
    for kind, filename in (("waveform", "km40_f1_exploratory.sgy"),
                           ("sidecar", "km40_f1_exploratory.sgy.json")):
        service.attach_part(operator, upload, kind, service.store.put((DEMO / filename).read_bytes()))
    service.complete_upload(operator, upload, "km-complete")
    revision = service.create_revision(operator, acquisition_id, RevisionCreate(uploads=(upload,)), "km-revision")
    run = service.create_run(operator, RunCreate(
        revision_id=revision.body["id"], protocol=json.loads((DEMO / "protocol.json").read_bytes()),
        excluded_receiver_ids=("ch24",)), "km-run")
    assert Worker(service).run_once()
    published = service.get(operator, "processing_runs", UUID(run.body["id"]))
    assert published["state"] == "SUCCEEDED", published["error_code"]
    _, document, _ = Dossiers(service).load(operator, UUID(published["dossier_id"]))
    assert document["protocol"]["provenance"] == ASSUMPTIONS
    assert document["eligible_for_acceptance"] is False
    assert document["sufficiency"] == {"status": "NOT_DEMONSTRATED"}
    assert document["diagnostic_quality"][0]["amplitude_unit"] == "V"
