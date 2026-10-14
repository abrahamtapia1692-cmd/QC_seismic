import numpy as np
import pytest

from geoqc.core.evidence import canonical_hash
from geoqc.masw.contracts import CurveCalibration, MASWProtocol
from geoqc.masw.report import masw_diagnostics
from geoqc.masw.statistics import estimator_hash
from geoqc.qc.contracts import Window
from tests.synthetic.e5_support import shot, wilson


@pytest.mark.vid("V-E5-11")
@pytest.mark.parametrize("snr_db", [10, 20])
def test_waveform_to_calibrated_curve_independent_holdout(snr_db, record_property):
    f, x, t = np.array([8.0, 16.0, 32.0]), np.arange(24) * 2, np.arange(2000) * 0.001
    protocol = MASWProtocol(
        signal=Window(start_s=0, end_s=2),
        frequencies_hz=tuple(f),
        velocities_ms=tuple(np.arange(150, 251)),
        directions=(1,),
        window="RECTANGULAR",
        ridge_penalty=0,
        domain_id=f"waveform-bin-plane-SNR{snr_db}",
        provenance="independent waveform integration holdout",
    )
    cosine, sine = np.cos(2 * np.pi * f[:, None] * t), np.sin(2 * np.pi * f[:, None] * t)
    clean = np.exp(-2j * np.pi * f[:, None] * x / 200)
    result = masw_diagnostics(shot(clean.real.T @ cosine - clean.imag.T @ sine, x=x), protocol)
    errors = []
    for role, seed in (("TRAIN", 9500 + snr_db), ("HOLDOUT", 10500 + snr_db)):
        rng = np.random.default_rng(seed)
        if role == "HOLDOUT":
            calibration = CurveCalibration(
                protocol_hash=canonical_hash(protocol.model_dump(mode="json")),
                estimator_hash=estimator_hash(),
                geometry_hash=result["geometry_hash"],
                dt_s=0.001,
                n_active=24,
                domain_id=protocol.domain_id,
                training_ref=f"waveform synthetic seed{9500 + snr_db}, n1000",
                frequencies_hz=tuple(f),
                errors_ms=tuple(map(tuple, errors)),
                direction=1,
            )
            intervals = []
            hold_errors = []
        for _ in range(1000):
            noise = (rng.normal(size=clean.shape) + 1j * rng.normal(size=clean.shape)) / np.sqrt(
                2 * 10 ** (snr_db / 10)
            )
            u = clean + noise
            waveform = shot(u.real.T @ cosine - u.imag.T @ sine, x=x)
            result = masw_diagnostics(waveform, protocol, curve_calibration=None if role == "TRAIN" else calibration)
            curve = result["curves"][0]
            if role == "TRAIN":
                errors.append(np.array(curve["velocities_ms"]) - 200)
            else:
                assert curve["precision_validity"] == "CALIBRATED" and not result["eligible_for_acceptance"]
                intervals.append(curve["precision"]["interval95_ms"])
                hold_errors.append(np.array(curve["precision"]["velocities_ms"]) - 200)
    bounds = np.array(intervals)
    counts = np.sum((bounds[:, :, 0] <= 200) & (bounds[:, :, 1] >= 200), axis=0)
    assert np.max(abs(counts / 1000 - 0.95)) <= 0.025
    record_property(
        "waveform_precision_holdout",
        {
            "snr_db": snr_db,
            "train_n": 1000,
            "holdout_n": 1000,
            "train_seed": 9500 + snr_db,
            "holdout_seed": 10500 + snr_db,
            "coverage95": (counts / 1000).tolist(),
            "wilson95": [wilson(int(k), 1000) for k in counts],
            "corrected_bias_ms": np.mean(hold_errors, axis=0).tolist(),
            "pipeline": "real waveform -> physical window -> FFT -> signed phase-shift -> DP penalty0 -> q refinement -> empirical intervals",
            "geometry_hash": result["geometry_hash"],
            "sigma_not_fwhm": True,
        },
    )
