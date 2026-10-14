import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from geoqc.core.config import Threshold, load_config
from geoqc.qc import common_qc
from geoqc.qc.channels import channel_statistics, clipping
from geoqc.qc.contracts import QCProtocol, Window
from geoqc.qc.spectral import mains_line, noise_psd, snr
from geoqc.qc.timing import compare_repeats, repeatability, time_budget
from tests.synthetic.test_e2 import protocol, pulse, repeat_protocol, shot


@pytest.mark.vid("V-E2-1")
def test_masked_post_does_not_satisfy_duration():
    data = np.ones((1, 2000))
    mask = np.ones_like(data, dtype=bool)
    mask[:, 500:] = False
    p = protocol(2, min_group_velocity_ms=1, wavelet_duration_s=0)
    result = time_budget(shot(data, mask=mask, offsets=[1]), 0, p)
    assert result["post_sufficient"] is False
    assert result["post_available_s"] == 0.5
    assert result["usable_s"] is None
    assert time_budget(shot(data, t0=0.1), 0, p)["post_sufficient"] is False


@pytest.mark.vid("V-E2-2")
def test_missing_amplitude_model_is_not_channel_anomaly():
    data = np.tile(np.sin(np.arange(100) * 0.1), (3, 1))
    data[0] *= 0.2
    assert all(row["amplitude_anomaly"] is None for row in channel_statistics(shot(data), protocol(0.1)))
    mask = np.zeros_like(data, dtype=bool)
    assert all(row["state"] == "MISSING" for row in channel_statistics(shot(data, mask=mask), protocol(0.1)))
    with pytest.raises(ValueError, match="coincide"):
        channel_statistics(shot(data), protocol(0.1, expected_relative_amplitude=(1,), amplitude_model_ref="invalid"))


@pytest.mark.vid("V-E2-3")
def test_clipping_scale_and_window_abstentions():
    source = shot(np.ones(100) * 3, rails=(-1, 1))
    assert clipping(source, 0, protocol(0.1, rail_scale_to_data=1)).state == "INVALID"
    assert clipping(source, 0, protocol(0.2, rail_scale_to_data=1)).state == "MISSING"
    with pytest.raises(ValueError, match="Tolerancia"):
        clipping(source, 0, protocol(0.1, rail_scale_to_data=1, rail_tolerance=1))
    data = np.tile(np.r_[np.zeros(99), 1.0], (3, 1)) * np.array([1, 2, 3])[:, None]
    source = shot(data, rails=(-1, 1))
    scaled = protocol(0.1, rail_scale_to_data=(1, 2, 3))
    assert all(clipping(source, channel, scaled).value == 0.01 for channel in range(3))
    with pytest.raises(ValueError, match="canal"):
        clipping(source, 0, protocol(0.1, rail_scale_to_data=(1, 2)))


@pytest.mark.vid("V-E2-4")
def test_stationarity_and_psd_support_abstentions():
    source = shot(np.arange(1000))
    p = protocol(1, noise=Window(start_s=0, end_s=0.1), signal=Window(start_s=0.2, end_s=1), noise_independent=True)
    assert snr(source, 0, p).state == "MODEL_INAPPLICABLE"
    assert noise_psd(source, 0, p)["state"] == "MODEL_INAPPLICABLE"
    verified = QCProtocol.model_validate(
        p.model_dump() | {"noise_stationarity": "VERIFIED", "stationarity_ref": "test"}
    )
    assert noise_psd(source, 0, verified)["state"] == "MISSING"
    assert noise_psd(source, 0, protocol(1))["state"] == "MISSING"


@pytest.mark.vid("V-E2-5")
def test_lines_missing_and_alias_domain():
    source = shot(np.zeros(4096))
    assert mains_line(source, 0, protocol(4.096)).state == "MISSING"
    assert mains_line(source, 0, protocol(4.096, mains_hz=499)).state == "MODEL_INAPPLICABLE"
    assert mains_line(source, 0, protocol(4.096, mains_hz=50)).flagged is False


@pytest.mark.vid("V-E2-7")
def test_repeat_domain_and_censoring():
    time = np.arange(1024) * 0.001
    p = repeat_protocol()
    assert compare_repeats(np.ones(1024), np.ones(1024), p).state == "MISSING"
    assert compare_repeats(pulse(time), pulse(time, 0.05), p).state == "AMBIGUOUS"
    assert (
        compare_repeats(pulse(time), pulse(time), repeat_protocol(comparable_acquisition=False)).state
        == "MODEL_INAPPLICABLE"
    )
    with pytest.raises(ValueError, match="forma"):
        repeatability(pulse(time), pulse(time), p)


@pytest.mark.vid("V-E2-10")
def test_protocol_rejects_unsupported_claims():
    with pytest.raises(ValidationError):
        protocol(1, noise=Window(start_s=0, end_s=0.6), signal=Window(start_s=0.5, end_s=1))
    with pytest.raises(ValidationError):
        protocol(1, noise_stationarity="VERIFIED")
    with pytest.raises(ValidationError):
        protocol(1, expected_relative_amplitude=(1, 1))
    with pytest.raises(ValidationError):
        protocol(1, frequency_band_hz=(100, 10))
    with pytest.raises(ValidationError):
        protocol(1, amplitude_ratio_bounds=(2, 3))
    with pytest.raises(ValidationError):
        repeat_protocol(frequency_band_hz=(10, 600))
    with pytest.raises(ValidationError):
        protocol(1, group_velocity_verified=True, min_group_velocity_ms=80)


@pytest.mark.vid("V-E2-10")
def test_draft_threshold_report_remains_incomplete():
    config = load_config(Path("configs/vs30_sitio.yaml"))
    threshold = Threshold(
        id="clip",
        unit="fraction",
        direction="lower_is_better",
        warn=1e-4,
        fail=1e-3,
        boundary="inclusive",
        mandatory=True,
        critical=True,
        calibration_state="UNVALIDATED",
    )
    config = type(config).model_validate(config.model_dump() | {"metrics": (threshold,)})
    p = protocol(1, rail_scale_to_data=1)
    report = common_qc(shot(np.zeros((3, 1000)), rails=(-1, 1)), p, config)
    assert report["report"]["quality_status"] == "PASS"
    assert report["report"]["evidence_status"] == "INCOMPLETE"
    assert report["eligible_for_acceptance"] is False
    json.dumps(report, allow_nan=False)
    wrong = type(threshold).model_validate(threshold.model_dump() | {"unit": "percent"})
    with pytest.raises(ValueError, match="Unidad"):
        common_qc(
            shot(np.zeros((3, 1000)), rails=(-1, 1)),
            p,
            type(config).model_validate(config.model_dump() | {"metrics": (wrong,)}),
        )
