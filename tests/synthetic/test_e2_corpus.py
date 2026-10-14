"""Corpus de etiquetas externas al detector: 1200 realizaciones, 12 clases."""

import json

import numpy as np
import pytest

from geoqc.qc.channels import channel_statistics, clipping
from geoqc.qc.contracts import Window
from geoqc.qc.spectral import mains_line, snr
from geoqc.qc.timing import compare_repeats, time_budget

from .test_e2 import protocol, record, repeat_protocol, shot, wilson


@pytest.mark.vid("V-E2-10")
def test_labeled_corpus(record_property):
    rng = np.random.default_rng(22100)
    time = np.arange(4096) * 0.001
    kinds = [
        "clean",
        "dead",
        "constant",
        "clip",
        "hum",
        "noise",
        "polarity",
        "delay",
        "amplitude",
        "combined",
        "ambiguous_dt",
        "ambiguous_geometry",
    ]
    faults = ["dead", "constant", "clip", "hum", "noise", "polarity", "delay", "amplitude"]
    counts = {name: {"tp": 0, "fp": 0, "positive": 0, "negative": 0} for name in faults}
    abstentions = {"ambiguous_dt": 0, "ambiguous_geometry": 0}
    for index in range(1200):
        kind = kinds[index % len(kinds)]
        # La verdad proviene del experimento continuo y de operaciones aquí registradas.
        frequency = rng.uniform(35, 45)
        width = rng.uniform(0.022, 0.028)
        center = rng.uniform(2.95, 3.05)
        u = time - center
        clean = 0.6 * np.exp(-0.5 * (u / width) ** 2) * np.cos(2 * np.pi * frequency * u)
        data = np.tile(clean, (8, 1)) + rng.normal(0, 0.0005, (8, time.size))
        truth = {name: False for name in faults}
        rails = (-1, 1)
        dt = 0.001
        offsets = np.arange(8) + 1.0
        if kind in ("dead", "combined"):
            data[0] = 0
            truth["dead"], truth["constant"] = True, True
        if kind == "constant":
            data[0] = 0.3
            truth["constant"] = True
        if kind in ("clip", "combined"):
            rails = (-0.18, 0.18)
            # Un ADC común limita todos los canales del registro a los mismos rails.
            data = np.clip(data, *rails)
            truth["clip"] = True
        if kind == "hum":
            data[0] += 0.1 * np.sin(2 * np.pi * 50 * time + rng.uniform(0, 2 * np.pi))
            truth["hum"] = True
            truth["noise"] = True
        if kind == "noise":
            data[0] += rng.normal(0, 0.1, time.size)
            truth["noise"] = True
        if kind == "polarity":
            data[0] *= -1
            truth["polarity"] = True
        if kind == "delay":
            lag = rng.uniform(0.003, 0.005)
            delayed = time - center - lag
            data[0] = 0.6 * np.exp(-0.5 * (delayed / width) ** 2) * np.cos(2 * np.pi * frequency * delayed)
            truth["delay"] = True
        if kind == "amplitude":
            data[0] *= 0.2
            truth["amplitude"] = True
        if kind == "ambiguous_dt":
            dt *= 1.05
        if kind == "ambiguous_geometry":
            offsets[0] += 0.3
        assert np.all((data >= rails[0]) & (data <= rails[1]))
        source = shot(data, rails=rails, dt=dt, offsets=offsets)
        p = protocol(
            4096 * dt,
            signal=Window(start_s=2.048 * (dt / 0.001), end_s=4096 * dt),
            noise=Window(start_s=0, end_s=2.048 * (dt / 0.001)),
            noise_independent=True,
            noise_stationarity="VERIFIED",
            stationarity_ref="known stationary experiment",
            rail_scale_to_data=1,
            mains_hz=50,
        )
        stats = channel_statistics(source, p)
        # Modelo de amplitud relativo declarado por el experimento.
        ap = protocol(4096 * dt, expected_relative_amplitude=(1,) * 8, amplitude_model_ref="equal physical gains")
        amplitudes = channel_statistics(source, ap)
        clip_channel = 1 if kind == "combined" else 0
        clip = clipping(source, clip_channel, p)
        line = mains_line(source, 0, p)
        signal_noise = snr(source, 0, p)
        repeated = compare_repeats(clean, data[0], repeat_protocol(dt_s=dt))
        flags = {
            "dead": stats[0]["dead"],
            "constant": stats[0]["constant"],
            "clip": clip.state == "VALID" and clip.value > 1e-3,
            "hum": line.flagged is True,
            "noise": signal_noise.state == "VALID" and signal_noise.value < 5,
            "polarity": repeated.state == "VALID" and repeated.flagged is True,
            "delay": repeated.state == "VALID" and abs(repeated.value) > 0.002,
            # Excluir casos con evidencia explícita que hace el modelo inaplicable.
            "amplitude": amplitudes[0]["amplitude_anomaly"] is True,
        }
        # El corpus evalúa amplitud solo cuando no hay fallas que invaliden comparabilidad.
        eligible = {name: True for name in faults}
        eligible["amplitude"] = kind not in ("dead", "constant", "noise", "hum", "combined", "clip")
        for name in faults:
            if not eligible[name]:
                continue
            entry = counts[name]
            entry["positive" if truth[name] else "negative"] += 1
            entry["tp" if truth[name] else "fp"] += int(flags[name])
        if kind in abstentions:
            # No existe detector universal de dt/geometría sin reloj/levantamiento externo.
            assert source.headers_json == '{"fixture":"independent labels outside headers"}'
            assert (
                time_budget(source, 0, p)["timebase_accuracy_state"]
                == "NOT_IDENTIFIABLE_WITHOUT_EXTERNAL_CLOCK_REFERENCE"
            )
            abstentions[kind] += 1
        json.dumps(
            {
                "clip": clip.model_dump(mode="json"),
                "snr": signal_noise.model_dump(mode="json"),
                "repeat": repeated.model_dump(mode="json"),
            },
            allow_nan=False,
        )
    results = {}
    for name, entry in counts.items():
        recall, fpr = entry["tp"] / entry["positive"], entry["fp"] / entry["negative"]
        results[name] = {
            **entry,
            "recall": recall,
            "fpr": fpr,
            "recall_wilson95": wilson(entry["tp"], entry["positive"]),
            "fpr_wilson95": wilson(entry["fp"], entry["negative"]),
        }
    record(
        record_property,
        "labeled_corpus",
        {
            "n": 1200,
            "classes": {kind: 100 for kind in kinds},
            "unit": "independent realization",
            "fault_results": results,
            "not_identifiable": abstentions,
            "domain": "known equal gains/rails/replica waveform; amplitude only on comparable transient traces",
        },
    )
    for name, entry in results.items():
        assert entry["recall"] >= 0.95, (name, entry)
        assert entry["fpr"] <= 0.05, (name, entry)
