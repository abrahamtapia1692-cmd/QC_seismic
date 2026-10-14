import json
import subprocess
import sys

import numpy as np
import pytest

from geoqc.core.evidence import canonical_hash
from geoqc.core.models import Shot
from geoqc.io.writers import write_segy
from geoqc.masw.contracts import CurveCalibration, MASWProtocol, PeakCalibration
from geoqc.masw.report import masw_diagnostics
from geoqc.masw.statistics import estimator_hash, kluyver_cdf
from geoqc.masw.transform import phase_shift, shot_spectrum
from geoqc.qc.contracts import Window
from geoqc.synth.nearfield import lamb_surface
from tests.synthetic.e5_support import shot


def fixture():
    x, t = np.arange(24) * 2, np.arange(2000) * 0.001
    data = sum(np.cos(2 * np.pi * f * (t[None, :] - x[:, None] / 200)) for f in (8, 16, 32))
    waveform = shot(data, x=x)
    protocol = MASWProtocol(
        signal=Window(start_s=0, end_s=2),
        frequencies_hz=(8, 16, 32),
        velocities_ms=tuple(np.arange(150, 251)),
        directions=(1, -1),
        domain_id="e5-domain-test",
        provenance="test calibration compatible",
    )
    observed = shot_spectrum(waveform, protocol)
    common = {
        "protocol_hash": canonical_hash(protocol.model_dump(mode="json")),
        "estimator_hash": estimator_hash(),
        "n_active": 24,
        "domain_id": protocol.domain_id,
        "training_ref": "independent synthetic fixture distribution",
        "geometry_hash": canonical_hash(
            {
                "x_m": observed["x_m"].tolist(),
                "weights": observed["weights"].tolist(),
                "receiver_ids": waveform.acquisition.receiver_ids,
            }
        ),
        "dt_s": 0.001,
    }
    return waveform, protocol, common


@pytest.mark.vid("V-E5-20")
def test_calibration_identity_geometry_clock_support_and_direction():
    waveform, protocol, common = fixture()
    peak = PeakCalibration(**common, maximum_scores=tuple(np.linspace(0.1, 0.5, 1000)))
    precision = CurveCalibration(
        **common,
        frequencies_hz=(8, 16, 32),
        errors_ms=tuple(map(tuple, np.random.default_rng(520).normal(0, 1, (500, 3)))),
    )
    result = masw_diagnostics(waveform, protocol, peak_calibration=peak, curve_calibration=precision)
    assert result["curves"][0]["precision_validity"] == "CALIBRATED"
    assert result["curves"][1]["precision_validity"] == "UNCALIBRATED"
    assert all(row["significance"]["validity"] == "CALIBRATED" for row in result["curves"])
    assert not result["eligible_for_acceptance"]
    for change in (
        {"n_active": 48},
        {"estimator_hash": "0" * 64},
        {"protocol_hash": "0" * 64},
        {"domain_id": "other"},
        {"geometry_hash": "0" * 64},
        {"dt_s": 0.002},
    ):
        wrong = PeakCalibration.model_validate(peak.model_dump() | change)
        changed = masw_diagnostics(waveform, protocol, peak_calibration=wrong)
        assert all(row["significance"]["validity"] == "UNCALIBRATED" for row in changed["curves"])
    data = np.array(waveform.data)
    data[3] = 0
    missing = Shot.model_validate(waveform.model_dump() | {"data": data})
    changed = masw_diagnostics(missing, protocol, peak_calibration=peak, curve_calibration=precision)
    assert changed["curves"][0]["n_active"] == [23, 23, 23]
    assert changed["curves"][0]["precision_validity"] == "UNCALIBRATED"


@pytest.mark.vid("V-E5-15")
def test_cli_json_diagnostic_and_invalid_protocol(tmp_path):
    waveform, protocol, _ = fixture()
    path = tmp_path / "wave.sgy"
    write_segy(path, waveform)
    config = tmp_path / "protocol.json"
    config.write_text(protocol.model_dump_json(), encoding="utf-8")
    command = [sys.executable, "-X", "utf8", "-m", "geoqc", "masw", str(path), "--protocol", str(config)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert not report["eligible_for_acceptance"] and len(report["curves"]) == 2
    config.write_text('{"frequencies_hz":[16,8]}', encoding="utf-8")
    invalid = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
    assert invalid.returncode == 2


@pytest.mark.vid("V-E5-6")
def test_invalid_transform_inputs_masked_windows_and_non_aligned_clocks():
    waveform, protocol, _ = fixture()
    with pytest.raises(ValueError):
        phase_shift(np.ones((1, 24)), [8], np.arange(24), [0])
    with pytest.raises(ValueError):
        phase_shift(np.ones((1, 24)), [8], np.arange(24), [200], weights=-np.ones(24))
    bad_clock = Shot.model_validate(waveform.model_dump() | {"dt_s": (0.002,) + (0.001,) * 23})
    with pytest.raises(ValueError, match="Relojes"):
        shot_spectrum(bad_clock, protocol)
    mask = np.array(waveform.valid_mask)
    mask[0, 100] = False
    masked = Shot.model_validate(waveform.model_dump() | {"valid_mask": mask, "mask_reasons": ("drop",) + ("",) * 23})
    observed = shot_spectrum(masked, protocol)
    assert observed["weights"][0] == 0 and observed["excluded"][0] == "MASKED_WINDOW"


@pytest.mark.vid("V-E5-17")
def test_null_domain_rejects_unvalidated_low_n():
    for n in (4, 16, 1000):
        with pytest.raises(ValueError, match="N12/24/48"):
            kluyver_cdf(0.5, n)


@pytest.mark.vid("V-E5-15")
def test_all_masked_channels_yield_missing_band_not_estimated_confidence():
    waveform, protocol, _ = fixture()
    masked = Shot.model_validate(
        waveform.model_dump() | {"valid_mask": np.zeros_like(waveform.valid_mask), "mask_reasons": ("no samples",) * 24}
    )
    result = masw_diagnostics(masked, protocol)
    assert all(row["diagnostic_bands"] == [] and row["n_active"] == [0, 0, 0] for row in result["curves"])
    assert not result["eligible_for_acceptance"]
    assert all(row["velocities_ms"] == [None, None, None] and row["near_geometry"] is None for row in result["curves"])


@pytest.mark.vid("V-E5-11")
def test_nonphysical_calibration_abstains_without_negative_velocity():
    waveform, protocol, common = fixture()
    calibration = CurveCalibration(**common, frequencies_hz=(8, 16, 32), errors_ms=((500.0, 500.0, 500.0),) * 500)
    result = masw_diagnostics(waveform, protocol, curve_calibration=calibration)
    curve = result["curves"][0]
    assert curve["precision_validity"] == "UNCALIBRATED" and curve["precision"] is None
    assert "no físico" in curve["precision_reason"]
    assert all(value > 0 for value in curve["velocities_ms"])
    assert not result["eligible_for_acceptance"]


@pytest.mark.vid("V-E3-8")
def test_green_domain_and_numerical_budget_errors():
    with pytest.raises(ValueError):
        lamb_surface([8], [2], vp_ms=150, vs_ms=200)
    with pytest.raises(ValueError):
        lamb_surface([8], [0], vp_ms=400, vs_ms=200)
    with pytest.raises(ValueError, match="Presupuesto"):
        lamb_surface([8], [2], vp_ms=400, vs_ms=200, dk_m_inv=1e-7)
