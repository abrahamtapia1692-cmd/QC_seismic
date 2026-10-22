"""Application contracts outside the scientific VID manifest; no gate approval."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from geoqc.core.evidence import canonical_hash
from geoqc.core.models import Shot
from geoqc.io.errors import IngestError
from geoqc.io.readers import read_shot
from geoqc.masw.adapter import (
    MASWAdapterInput,
    MASWAdapterResult,
    ReceiverExclusion,
    build_masw_dossier,
    capture_engine_reference,
)
from geoqc.masw.contracts import MASWProtocol
from geoqc.masw.diagnostic_quality import UsabilityPolicy
from geoqc.masw.report import masw_diagnostics
from tests.synthetic.e5_support import shot as synthetic_shot

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def request_e5():
    shot = read_shot(ROOT / "examples/e5/masw_plane.sgy")
    return MASWAdapterInput(
        acquisition_revision_id="local-e5-revision-1",
        shots=(shot,),
        protocol=MASWProtocol.model_validate_json((ROOT / "examples/e5/protocol.json").read_text()),
        usability_policy=UsabilityPolicy.model_validate_json(
            (ROOT / "configs/masw_usability_v1.json").read_text()
        ),
        sensitivity_exclusions=(ReceiverExclusion(shot_id=shot.id, receiver_id="r0"),),
        engine_reference=capture_engine_reference(),
    )


def with_shot(request, shot):
    return MASWAdapterInput.model_validate(request.model_dump() | {
        "shots": (shot,),
        "sensitivity_exclusions": (ReceiverExclusion(shot_id=shot.id, receiver_id=shot.acquisition.receiver_ids[0]),),
    })


def test_e5_native_results_preserved_and_dimensions_separated(request_e5):
    original = request_e5.shots[0].data.copy()
    result = build_masw_dossier(request_e5)
    document = result.to_document()
    record = document["diagnostic_quality"][0]
    assert record["native_diagnostics"] == json.loads(json.dumps(
        masw_diagnostics(request_e5.shots[0], request_e5.protocol), allow_nan=False
    ))
    assert document["sufficiency"] == {"status": "NOT_DEMONSTRATED"}
    assert document["eligible_for_acceptance"] is False
    assert document["missing_evidence"]
    assert record["amplitude_unit"] == "m"
    assert all(curve["validated_bands"] == [] for curve in record["native_diagnostics"]["curves"])
    assert record["apparent_usability"]["ridge_estimator"] != record["apparent_usability"]["native_ridge_estimator"]
    assert len(record["trace_observations"]) == 24
    assert document["input_manifest"]["shots"][0]["input_hashes"] == list(request_e5.shots[0].input_hashes)
    np.testing.assert_array_equal(original, request_e5.shots[0].data)
    body = {k: v for k, v in document.items() if k != "scientific_digest"}
    assert canonical_hash(body) == result.scientific_digest


def test_result_and_serialized_worker_request_are_repeatable(request_e5):
    result = build_masw_dossier(request_e5)
    worker_request = MASWAdapterInput.model_validate_json(request_e5.model_dump_json())
    assert build_masw_dossier(worker_request) == result
    assert MASWAdapterResult.model_validate_json(result.model_dump_json()) == result
    modified = result.to_document()
    modified["diagnostic_quality"].clear()
    assert result.to_document()["diagnostic_quality"]
    with pytest.raises(ValidationError, match="Digest"):
        MASWAdapterResult(scientific_json=result.scientific_json, scientific_digest="a" * 64)
    with pytest.raises(ValidationError):
        result.scientific_json = "{}"


def test_cli_same_science_as_callable_from_any_working_directory(request_e5, tmp_path):
    policy = ROOT / "configs/masw_usability_v1.json"
    expected = build_masw_dossier(request_e5).to_document()
    completed = subprocess.run([
        sys.executable, "-m", "geoqc", "masw-dossier", str(ROOT / "examples/e5/masw_plane.sgy"),
        "--protocol", str(ROOT / "examples/e5/protocol.json"), "--policy", str(policy),
        "--revision-id", request_e5.acquisition_revision_id, "--sensitivity-receiver", "r0",
    ], capture_output=True, text=True, encoding="utf-8", cwd=tmp_path, check=False)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == expected
    assert list(tmp_path.iterdir()) == []


def test_import_is_headless_and_does_not_read_policies_or_examples(tmp_path):
    completed = subprocess.run([
        sys.executable, "-c",
        "import sys\n"
        "def audit(event, args):\n"
        "    if event == 'open' and isinstance(args[0], str):\n"
        "        parts = args[0].replace(chr(92), '/').split('/')\n"
        "        if 'configs' in parts or 'examples' in parts:\n"
        "            raise AssertionError('unexpected dataset/policy read')\n"
        "sys.addaudithook(audit)\nimport geoqc.masw.adapter\n"
        "assert 'matplotlib' not in sys.modules\nassert 'tools.report_masw_quality' not in sys.modules\n"
        "print('headless')",
    ], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "headless"


def test_serialized_calculation_does_not_read_or_write_files(request_e5, tmp_path):
    code = (
        "import sys\nfrom unittest.mock import patch\n"
        "from geoqc.masw.adapter import MASWAdapterInput, build_masw_dossier\n"
        "request = MASWAdapterInput.model_validate_json(sys.stdin.buffer.read())\n"
        "with patch('pathlib.Path.read_bytes', side_effect=AssertionError('read bytes')), "
        "patch('pathlib.Path.read_text', side_effect=AssertionError('read text')), "
        "patch('builtins.open', side_effect=AssertionError('open')):\n"
        "    result = build_masw_dossier(request)\n"
        "print(result.scientific_digest)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], input=request_e5.model_dump_json(),
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == build_masw_dossier(request_e5).scientific_digest
    assert list(tmp_path.iterdir()) == []


def test_independent_plane_and_negative_direction(request_e5):
    dt, channels, samples = 0.002, 8, 1000
    x = 11 + np.arange(channels) * 1.5
    time = np.arange(samples) * dt
    data = np.cos(2 * np.pi * 12 * (time[None, :] + x[:, None] / 180))
    shot = synthetic_shot(data, x=x, dt=dt, t0=-0.2)
    protocol = MASWProtocol(
        signal={"start_s": -0.2, "end_s": 1.8}, frequencies_hz=(10, 12, 14),
        velocities_ms=tuple(range(100, 261, 2)), directions=(-1, 1), provenance="independent negative plane",
    )
    request = MASWAdapterInput.model_validate(with_shot(request_e5, shot).model_dump() | {"protocol": protocol})
    result = build_masw_dossier(request).to_document()
    negative, positive = result["diagnostic_quality"][0]["apparent_usability"]["directions"]
    point = negative["points"][1]
    assert point["grid_velocity_ms"] == pytest.approx(180, abs=2)
    assert point["signed_q_m_inv"] < 0
    assert point["coherence"] > 0.99
    assert point["coherence"] > positive["points"][1]["coherence"]
    assert point["receiver_ids"] == list(shot.acquisition.receiver_ids)
    assert not result["eligible_for_acceptance"]


def test_masked_channel_remains_visible_without_imputing_signal(request_e5):
    original = request_e5.shots[0]
    data, mask = original.data.copy(), original.valid_mask.copy()
    data[4, 200], mask[4, 200] = np.nan, False
    reasons = list(original.mask_reasons)
    reasons[4] = "NONFINITE_SAMPLE"
    shot = Shot.model_validate(original.model_dump() | {"data": data, "valid_mask": mask, "mask_reasons": reasons})
    result = build_masw_dossier(with_shot(request_e5, shot)).to_document()
    record = result["diagnostic_quality"][0]
    trace = record["trace_observations"][4]
    assert trace["rms_ac_native"] is None and trace["constant"] is None
    assert trace["exclusion_reason"] == "MASKED_WINDOW"
    assert trace["valid_fraction"] < 1
    for direction in record["apparent_usability"]["directions"]:
        assert all(p["grade"] != "UTILIZABLE" for p in direction["points"])
        assert all("r4" not in p["receiver_ids"] for p in direction["points"])
    result_json = json.dumps(result, allow_nan=False)
    assert "NaN" not in result_json


def test_zero_record_does_not_create_usable_curves(request_e5):
    original = request_e5.shots[0]
    zero = Shot.model_validate(original.model_dump() | {"data": np.zeros_like(original.data)})
    result = build_masw_dossier(with_shot(request_e5, zero)).to_document()
    record = result["diagnostic_quality"][0]
    assert all(trace["zero"] for trace in record["trace_observations"])
    for direction in record["apparent_usability"]["directions"]:
        assert all(point["grid_velocity_ms"] is None for point in direction["points"])
        assert all(point["grade"] == "NO_UTILIZABLE" for point in direction["points"])


def test_irregular_geometry_does_not_inherit_uniform_kernel(request_e5):
    original = request_e5.shots[0]
    x = original.geometry.xr.copy()
    x[4] += 0.3
    geometry = original.geometry.model_dump() | {"xr": x}
    shot = Shot.model_validate(original.model_dump() | {"geometry": geometry})
    result = build_masw_dossier(with_shot(request_e5, shot)).to_document()
    for direction in result["diagnostic_quality"][0]["apparent_usability"]["directions"]:
        assert all(p["grade"] == "NO_EVALUABLE" for p in direction["points"])
        assert all("KERNEL_UNSUPPORTED" in p["reasons"] for p in direction["points"])


@pytest.mark.parametrize("change", [
    {"sensitivity_exclusions": ()},
    {"sensitivity_exclusions": ({"shot_id": "other", "receiver_id": "r0"},)},
    {"extra": "forbidden"},
])
def test_request_rejects_ambiguous_or_unknown_fields(request_e5, change):
    with pytest.raises(ValidationError):
        MASWAdapterInput.model_validate(request_e5.model_dump() | change)


def test_unaligned_clocks_and_nonunit_weights_rejected(request_e5):
    original = request_e5.shots[0]
    shot = Shot.model_validate(original.model_dump() | {"dt_s": (0.002, *original.dt_s[1:])})
    with pytest.raises(ValueError, match="Relojes"):
        build_masw_dossier(with_shot(request_e5, shot))
    with pytest.raises(ValidationError, match="pesos"):
        MASWAdapterInput.model_validate(request_e5.model_dump() | {
            "protocol": request_e5.protocol.model_dump() | {"weights": (0.5,) * 24}
        })
    # model_copy bypasses pydantic validators; the public entry must revalidate.
    forged = request_e5.model_copy(update={"sensitivity_exclusions": ()})
    with pytest.raises(ValidationError):
        build_masw_dossier(forged)


def test_missing_sidecar_is_not_inferred_from_known_dataset(tmp_path):
    target = tmp_path / "unknown.sgy"
    target.write_bytes((ROOT / "examples/e5/masw_plane.sgy").read_bytes())
    with pytest.raises(IngestError, match="sidecar"):
        read_shot(target)


def test_manifest_changes_when_metadata_or_policy_changes(request_e5):
    baseline = build_masw_dossier(request_e5)
    original = request_e5.shots[0]
    shot = Shot.model_validate(original.model_dump() | {"headers_json": '{"note":"corrected"}'})
    changed = build_masw_dossier(with_shot(request_e5, shot))
    assert baseline.scientific_digest != changed.scientific_digest
    assert baseline.to_document()["input_manifest"] != changed.to_document()["input_manifest"]
    policy_request = MASWAdapterInput.model_validate(request_e5.model_dump() | {
        "usability_policy": request_e5.usability_policy.model_dump() | {"sensitivity_max_rel": 0.04}
    })
    assert build_masw_dossier(policy_request).scientific_digest != baseline.scientific_digest


def test_multiple_shots_preserve_selection_order(request_e5):
    first = request_e5.shots[0]
    second = Shot.model_validate(first.model_dump() | {"id": "second-shot"})
    request = MASWAdapterInput.model_validate(request_e5.model_dump() | {
        "shots": (second, first),
        "sensitivity_exclusions": (
            ReceiverExclusion(shot_id=first.id, receiver_id="r0"),
            ReceiverExclusion(shot_id=second.id, receiver_id="r1"),
        ),
    })
    result = build_masw_dossier(request).to_document()
    assert [r["shot_id"] for r in result["diagnostic_quality"]] == [second.id, first.id]
    assert [r["shot_id"] for r in result["input_manifest"]["shots"]] == [second.id, first.id]
    with pytest.raises(ValidationError, match="duplicados"):
        MASWAdapterInput.model_validate(request.model_dump() | {"shots": (first, first)})
