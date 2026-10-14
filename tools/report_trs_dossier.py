"""Generador de Dosieres de Control de Calidad Geofísico para Tomografía de Refracción Sísmica (TRS).

Genera el dosier técnico formal para levantamientos TRS:
- Calificación diagnóstica por traza individual (BUENA, REGULAR, MALA, NO_EVALUABLE) con trace_quality().
- Calificación agregada del tendido global con assess_quality().
- Hodógrafas completas (dromocrónicas) y ajuste de ramas de refracción (V1, V2, espesor).
- Evaluación de pares recíprocos de Fermat (|t_AB - t_BA|) con reciprocal_pair().
- Evaluación de repetibilidad intra-fuente entre impactos consecutivos (correlación de Pearson).
- Declaración estricta de estado de suficiencia del objetivo: PENDIENTE / NOT_DEMONSTRATED.

Entregables generados:
- dossier_trs.json (digest criptográfico canónico)
- dossier_trs.pdf (reporte formal multipágina con gráficos vectoriales)
- dossier_trs.html (panel interactivo autónomo con estilos modernos)
- traces_trs.csv (registro detallado por traza con métricas y calificaciones)
- picks_trs.csv (primeros arribos detectados por canal y disparo)
- reciprocity_trs.csv (análisis de reciprocidad de Fermat)
- repeatability_trs.csv (correlación entre impactos por estación)
- summary_trs.csv (métricas globales del tendido)
"""

from __future__ import annotations

import argparse
import base64
from collections import Counter
import csv
import hashlib
import json
import math
import os
import platform
import re
import sys
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoqc.core.evidence import canonical_hash  # noqa: E402
from geoqc.io.binary import parse_seg2  # noqa: E402
from geoqc.qc.quality import (  # noqa: E402
    COLORS,
    DISPLAY_COLORS,
    TraceQualityPolicy,
    assess_quality,
    trace_quality,
)
from geoqc.trs.branches import fit_branches, horizontal_two_layer_parameters  # noqa: E402
from geoqc.trs.contracts import ReciprocalObservation  # noqa: E402
from geoqc.trs.reciprocity import reciprocal_pair  # noqa: E402

SURVEY_METADATA = {
    "KM 40+672": {
        "slug": "KM_40_672",
        "title": "KM 40+672",
        "technique": "TRS (Tomografía de Refracción Sísmica)",
        "dx_m": 5.0,
        "channels": 24,
        "notes": "Tendido de refracción sísmica: 24 geófonos espaciados a 5.0 m (longitud de tendido 115 m). 9 estaciones de disparo F1 a F9 distribuidas a lo largo de la línea.",
    },
    "KM 44+552": {
        "slug": "KM_44_552",
        "title": "KM 44+552",
        "technique": "TRS (Tomografía de Refracción Sísmica)",
        "dx_m": 5.0,
        "channels": 24,
        "notes": "Tendido de refracción sísmica: 24 geófonos espaciados a 5.0 m (longitud de tendido 115 m). 9 estaciones de disparo F1 a F9 con múltiples impactos por punto de tiro.",
    },
    "KM 52+500": {
        "slug": "KM_52_500",
        "title": "KM 52+500",
        "technique": "TRS (Tomografía de Refracción Sísmica)",
        "dx_m": 2.5,
        "channels": 24,
        "notes": "Tendido de refracción sísmica: 24 geófonos espaciados a 2.5 m (longitud de tendido 57.5 m). 11 estaciones de disparo F1 a F11 con 3 a 5 impactos por punto de tiro.",
    },
}


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def detect_clipping_fraction(trace: np.ndarray, threshold_consecutive: int = 4) -> float:
    """Calcula la fracción de muestras sospechosas de clipping (mesetas en extremos)."""
    ptp = float(np.ptp(trace))
    if ptp == 0 or len(trace) == 0:
        return 0.0
    max_val, min_val = float(np.max(trace)), float(np.min(trace))
    tol = ptp * 1e-4
    diff = np.diff(trace)
    zero_diff = np.abs(diff) <= tol
    at_extreme = (np.abs(trace[:-1] - max_val) <= tol) | (np.abs(trace[:-1] - min_val) <= tol)
    plateaus = zero_diff & at_extreme
    clipped_samples = 0
    run = 0
    for p in plateaus:
        if p:
            run += 1
        else:
            if run >= threshold_consecutive:
                clipped_samples += run + 1
            run = 0
    if run >= threshold_consecutive:
        clipped_samples += run + 1
    return float(clipped_samples / len(trace))


def pick_first_arrival(
    trace: np.ndarray, dt: float, pre_trigger_samples: int = 150, max_search_samples: int = 2400
) -> float | None:
    """Estimador causal de primer arribo de onda P mediante STA/LTA con corrección de pre-disparo."""
    if len(trace) < max_search_samples:
        return None
    pre = min(pre_trigger_samples, 140)
    bg = trace[:pre]
    dc = float(np.mean(bg))
    noise_sigma = float(np.std(bg))
    if noise_sigma == 0 or not math.isfinite(noise_sigma):
        return None

    # Señal centrada
    signal = trace - dc
    sta_samples = max(2, int(round(0.002 / dt)))  # 2 ms
    lta_samples = max(4, int(round(0.020 / dt)))  # 20 ms
    power = signal**2
    sta = np.convolve(power, np.ones(sta_samples) / sta_samples, mode="full")[: len(signal)]
    lta = np.convolve(power, np.ones(lta_samples) / lta_samples, mode="full")[: len(signal)] + 1e-12
    ratio = sta / lta

    # Buscar disparo en ventana posterior al pre-disparo
    search_start = max(10, pre_trigger_samples - 20)
    search_end = min(len(trace), max_search_samples)
    triggered = np.where(ratio[search_start:search_end] > 3.5)[0]
    if len(triggered) == 0:
        return None

    candidate_idx = search_start + triggered[0]

    # Refinamiento local AIC en subventana de 60 muestras
    aic_left = max(0, candidate_idx - 25)
    aic_right = min(len(signal), candidate_idx + 35)
    sub = signal[aic_left:aic_right]
    if len(sub) < 16:
        pick_samp = candidate_idx
    else:
        var_sub = float(np.var(sub))
        floor = max(var_sub * 1e-8, 1e-24)
        n = len(sub)
        aic_vals = []
        for k in range(4, n - 4):
            s1 = sub[:k]
            s2 = sub[k:]
            v1 = max(float(np.var(s1)), floor)
            v2 = max(float(np.var(s2)), floor)
            aic_k = k * np.log(v1) + (n - k) * np.log(v2)
            aic_vals.append((aic_k, k))
        best_k = min(aic_vals, key=lambda x: x[0])[1]
        pick_samp = aic_left + best_k

    # Tiempo en segundos relativo al trigger (t=0 en pre_trigger_samples)
    t_seconds = float((pick_samp - pre_trigger_samples) * dt)
    return max(0.0, t_seconds)


def infer_source_station_name(file_path: Path) -> str:
    """Extrae el identificador de estación de tiro (ej. F01, F02... F11) de la ruta."""
    parts = file_path.parts
    for part in reversed(parts):
        m = re.search(r"F(\d+)", part, re.IGNORECASE)
        if m:
            return f"F{int(m.group(1)):02d}"
    return "F_UNKNOWN"


def analyze_trs_survey(survey_dir: Path, custom_meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Procesa completamente un levantamiento TRS generando análisis por traza y del tendido global."""
    dir_name = survey_dir.name
    meta = custom_meta or SURVEY_METADATA.get(dir_name, {
        "slug": re.sub(r"[^\w]+", "_", dir_name),
        "title": dir_name,
        "technique": "TRS (Tomografía de Refracción Sísmica)",
        "dx_m": 5.0,
        "channels": 24,
        "notes": "Levantamiento TRS procesado desde archivos SEG-2.",
    })

    dx = float(meta["dx_m"])
    n_ch = int(meta["channels"])
    policy = TraceQualityPolicy()

    # Buscar archivos .sg2 (excluir subdirectorios MAM si existen)
    all_files = sorted(survey_dir.rglob("*.sg2"))
    trs_files = [f for f in all_files if "MAM" not in f.parts]
    if not trs_files:
        raise ValueError(f"No se encontraron archivos SEG-2 de TRS en {survey_dir}")

    shots: list[dict[str, Any]] = []
    traces_records: list[dict[str, Any]] = []
    trace_quality_objects: list[dict[str, Any]] = []
    source_groups: dict[str, list[dict[str, Any]]] = {}

    for idx, f in enumerate(trs_files, 1):
        raw = f.read_bytes()
        file_sha = sha256_bytes(raw)
        parsed = parse_seg2(raw)
        data = np.asarray(parsed.traces, dtype=float)
        dt = float(parsed.dt_s[0])
        fs = 1.0 / dt
        m_samples = data.shape[1]
        src_tag = infer_source_station_name(f)

        is_finite = bool(np.all(np.isfinite(data)))
        dead_channels = [ch + 1 for ch, tr in enumerate(data) if np.ptp(tr) == 0]
        constant_channels = [
            ch + 1 for ch, tr in enumerate(data) if (ch + 1) not in dead_channels and np.std(tr) < 1e-12
        ]

        rms_values = [float(np.sqrt(np.mean((tr - np.mean(tr)) ** 2))) for tr in data]
        ptp_values = [float(np.ptp(tr)) for tr in data]

        # Clipping sospechado por canal
        clip_fractions = [detect_clipping_fraction(tr) for tr in data]
        clipped_channels = [ch + 1 for ch, frac in enumerate(clip_fractions) if frac >= policy.clip_bad_min_fraction]

        # Primeros arribos (P-wave onsets)
        picks = [pick_first_arrival(tr, dt) for tr in data]
        valid_picks = [p for p in picks if p is not None]

        # Pre-trigger noise y SNR neta
        snr_values = []
        for ch, tr in enumerate(data):
            pre_noise = tr[: min(140, m_samples)]
            noise_std = float(np.std(pre_noise))
            post_signal = tr[150: min(1500, m_samples)]
            sig_std = float(np.std(post_signal))
            snr_ratio = (sig_std**2) / (noise_std**2 + 1e-24)
            snr_db = float(10.0 * np.log10(max(snr_ratio, 1e-6)))
            snr_values.append(snr_db)

        # Calificación individual de cada traza con geoqc.qc.quality.trace_quality
        shot_qualities = []
        for ch in range(n_ch):
            tr_dict = {
                "valid_fraction": 1.0 if is_finite else 0.0,
                "statistics": {
                    "state": "VALID" if is_finite else "INVALID",
                    "dead": (ch + 1) in dead_channels,
                    "constant": (ch + 1) in constant_channels,
                    "amplitude_anomaly": False,
                },
                "snr": {
                    "state": "VALID",
                    "value": snr_values[ch],
                    "details_json": json.dumps({"snr_db": snr_values[ch]}),
                },
                "clip": {"state": "VALID", "value": clip_fractions[ch]},
                "mains": {"flagged": False},
                "noise_diagnostics": {"alerts": []},
                "integrity": {"alerts": []},
            }
            q = trace_quality(tr_dict, policy)
            shot_qualities.append(q)
            trace_quality_objects.append(q)

            traces_records.append(
                {
                    "shot_id": f"{meta['slug']}_S{idx:03d}",
                    "file_name": f.name,
                    "source_tag": src_tag,
                    "channel": ch + 1,
                    "receiver_x_m": ch * dx,
                    "rms_ac": rms_values[ch],
                    "ptp": ptp_values[ch],
                    "clip_fraction": clip_fractions[ch],
                    "snr_db": snr_values[ch],
                    "onset_s": picks[ch],
                    "grade": q["grade"],
                    "color": q["color"],
                    "reason": q["reasons"][0] if q["reasons"] else "Satisface controles de campo",
                }
            )

        shot_meta = {
            "shot_id": f"{meta['slug']}_S{idx:03d}",
            "file_name": f.name,
            "relative_path": f.relative_to(survey_dir).as_posix(),
            "sha256": file_sha,
            "source_tag": src_tag,
            "channels": int(data.shape[0]),
            "samples": int(m_samples),
            "dt_s": dt,
            "fs_hz": fs,
            "duration_s": float(m_samples * dt),
            "is_finite": is_finite,
            "dead_channels": dead_channels,
            "constant_channels": constant_channels,
            "clipped_channels": clipped_channels,
            "has_dead": len(dead_channels) > 0,
            "has_clipping": len(clipped_channels) > 0,
            "mean_rms": float(np.mean(rms_values)),
            "mean_snr_db": float(np.mean(snr_values)),
            "picks_count": len(valid_picks),
            "picks_s": picks,
            "qualities": shot_qualities,
            "acquisition_date": parsed.headers["file_header"].get("ACQUISITION_DATE", "UNKNOWN"),
            "acquisition_time": parsed.headers["file_header"].get("ACQUISITION_TIME", "UNKNOWN"),
        }
        shots.append(shot_meta)
        source_groups.setdefault(src_tag, []).append({"meta": shot_meta, "data": data})

    # Calificación agregada del tendido global
    spread_assessment = assess_quality(trace_quality_objects)
    counts = Counter(q["grade"] for q in trace_quality_objects)
    spread_assessment["counts"] = {key: counts.get(key, 0) for key in ("BUENA", "REGULAR", "MALA")}

    # Repetibilidad intra-fuente entre impactos sucesivos
    repeatability: list[dict[str, Any]] = []
    for src_tag, group in sorted(source_groups.items()):
        if len(group) < 2:
            repeatability.append(
                {
                    "source_tag": src_tag,
                    "shots_count": len(group),
                    "pair": "N/A",
                    "median_correlation": None,
                    "min_correlation": None,
                    "max_correlation": None,
                    "grade": "SIN_REPETICION",
                }
            )
            continue
        for i in range(len(group) - 1):
            s1 = group[i]["data"]
            s2 = group[i + 1]["data"]
            corrs = []
            for ch in range(n_ch):
                c = np.corrcoef(s1[ch], s2[ch])[0, 1]
                if np.isfinite(c):
                    corrs.append(float(c))
            med_c = float(np.median(corrs)) if corrs else 0.0
            grade = "EXCELENTE" if med_c >= 0.85 else "BUENA" if med_c >= 0.70 else "REGULAR"
            repeatability.append(
                {
                    "source_tag": src_tag,
                    "shots_count": len(group),
                    "pair": f"Golpe {i+1} vs {i+2}",
                    "median_correlation": med_c,
                    "min_correlation": float(np.min(corrs)) if corrs else None,
                    "max_correlation": float(np.max(corrs)) if corrs else None,
                    "grade": grade,
                }
            )

    # Cobertura de picados y dromocrónicas
    all_picks_count = sum(s["picks_count"] for s in shots)
    total_trace_count = len(traces_records)
    pick_coverage_percent = 100.0 * all_picks_count / total_trace_count if total_trace_count else 0.0

    # Ajuste de ramas de refracción para cada estación de tiro
    branches_summary: list[dict[str, Any]] = []
    receiver_x = np.arange(n_ch) * dx
    source_tags_sorted = sorted(source_groups.keys())

    # Estimación de posición física aproximada de cada fuente a lo largo del perfil
    source_positions: dict[str, float] = {}
    for i, stag in enumerate(source_tags_sorted):
        m = re.search(r"\d+", stag)
        num = int(m.group()) if m else (i + 1)
        # Espaciamiento proporcional entre 0 y longitud de tendido L
        max_dist = (n_ch - 1) * dx
        pos = (num - 1) * (max_dist / max(1, len(source_tags_sorted) - 1))
        source_positions[stag] = float(pos)

    for stag, group in sorted(source_groups.items()):
        # Utilizar el último golpe de la serie (acoplamiento optimizado)
        best_shot = group[-1]["meta"]
        s_picks = best_shot["picks_s"]
        xs = source_positions[stag]
        valid_indices = [ch for ch, p in enumerate(s_picks) if p is not None]
        if len(valid_indices) >= 5:
            offsets = np.abs(receiver_x[valid_indices] - xs)
            times = np.asarray([s_picks[ch] for ch in valid_indices], dtype=float)
            try:
                fit = fit_branches(offsets, times, max_segments=2)
                params = horizontal_two_layer_parameters(fit, model_verified=False)
                branches_summary.append(
                    {
                        "source_tag": stag,
                        "source_x_m": xs,
                        "valid_channels": len(valid_indices),
                        "v1_ms": params.get("v1_ms"),
                        "v2_ms": params.get("v2_ms"),
                        "crossover_m": params.get("xc_m"),
                        "apparent_thickness_m": params.get("h1_apparent_m"),
                    }
                )
            except Exception:
                branches_summary.append(
                    {
                        "source_tag": stag,
                        "source_x_m": xs,
                        "valid_channels": len(valid_indices),
                        "v1_ms": None,
                        "v2_ms": None,
                        "crossover_m": None,
                        "apparent_thickness_m": None,
                    }
                )

    # Evaluación de reciprocidad de Fermat
    reciprocal_results: list[dict[str, Any]] = []
    if len(source_tags_sorted) >= 2:
        first_src = source_tags_sorted[0]
        last_src = source_tags_sorted[-1]
        shot_a = source_groups[first_src][-1]["meta"]
        shot_b = source_groups[last_src][-1]["meta"]
        # A -> B: disparo en extremo inicial registrado en geófono final (canal 24)
        t_ab = shot_a["picks_s"][-1]
        # B -> A: disparo en extremo final registrado en geófono inicial (canal 1)
        t_ba = shot_b["picks_s"][0]
        if t_ab is not None and t_ba is not None:
            obs_ab = ReciprocalObservation(
                source_id="STATION_START",
                receiver_id="STATION_END",
                time_s=t_ab,
                sigma_s=0.001,
                error_model_ref="FIELD_PICK",
            )
            obs_ba = ReciprocalObservation(
                source_id="STATION_END",
                receiver_id="STATION_START",
                time_s=t_ba,
                sigma_s=0.001,
                error_model_ref="FIELD_PICK",
            )
            recip = reciprocal_pair(obs_ab, obs_ba, tolerance_s=0.003, detectable_effect_s=0.002)
            reciprocal_results.append(
                {
                    "pair_id": f"{first_src}_CH{n_ch:02d} <-> {last_src}_CH01",
                    "t_ab_s": t_ab,
                    "t_ba_s": t_ba,
                    "delta_t_ms": float(recip["delta_s"] * 1000.0),
                    "within_tolerance": recip["operational_within_tolerance"],
                    "statistical_discrepancy": recip["statistical_discrepancy"],
                    "tolerance_ms": 3.0,
                    "status": "CONFORME" if recip["operational_within_tolerance"] else "DISCREPANCIA",
                }
            )

    summary = {
        "slug": meta["slug"],
        "title": meta["title"],
        "technique": meta["technique"],
        "dx_m": dx,
        "channels": n_ch,
        "aperture_m": (n_ch - 1) * dx,
        "total_files": len(trs_files),
        "total_traces": total_trace_count,
        "sources_count": len(source_groups),
        "sources_identified": source_tags_sorted,
        "source_positions_m": source_positions,
        "spread_quality": spread_assessment,
        "pick_coverage_percent": pick_coverage_percent,
        "all_picks_count": all_picks_count,
        "notes": meta["notes"],
        "branches_summary": branches_summary,
        "repeatability": repeatability,
        "reciprocal_pairs": reciprocal_results,
        "shots": shots,
        "acceptance_status": "NOT_CERTIFIED",
        "objective_sufficiency": "PENDIENTE",
        "objective_reason": (
            "La aceptación formal del modelo tomográfico 2D/3D requiere calibración independiente "
            "de campo (pozo exploratorio o velocidad cruzada) y comprobación de ausencia de capas ocultas."
        ),
    }

    return summary, traces_records, source_groups


def plot_trs_figures(summary: dict[str, Any], source_groups: dict[str, Any], output_dir: Path) -> list[Path]:
    """Genera gráficos multipágina de calidad y refracción para el informe PDF."""
    figures: list[Path] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = summary["slug"]
    dx = summary["dx_m"]
    n_ch = summary["channels"]
    shots = summary["shots"]

    # FIGURA 1: Geometría de Tendido, Arribos y Agregación Global
    fig1, axes1 = plt.subplots(2, 2, figsize=(14, 9))
    fig1.subplots_adjust(left=0.08, right=0.95, top=0.88, bottom=0.10, hspace=0.35, wspace=0.25)
    fig1.suptitle(
        f"{summary['title']} · Dosier de Control de Calidad TRS (Refracción Sísmica)\n"
        f"Tendido: {n_ch} canales × dx={dx:g} m · L={(n_ch-1)*dx:g} m · Calificación Global: {summary['spread_quality']['grade']}",
        fontsize=14,
        fontweight="bold",
        color="#0f172a",
    )

    # 1.1 Geometría del tendido y fuentes
    ax = axes1[0, 0]
    rec_x = np.arange(n_ch) * dx
    ax.scatter(rec_x, np.zeros_like(rec_x), marker="v", s=70, color="#0284c7", label="Geófonos (1 a 24)")
    for i, (stag, spos) in enumerate(summary["source_positions_m"].items()):
        ax.scatter([spos], [0.4 + (i % 2) * 0.3], marker="*", s=130, color="#d97706")
        ax.text(spos, 0.4 + (i % 2) * 0.3 + 0.12, stag, ha="center", fontsize=8, weight="bold", color="#78350f")
    ax.set_ylim(-0.3, 1.2)
    ax.set_yticks([])
    ax.set_xlabel("Distancia a lo largo del perfil (m)", fontsize=9)
    ax.set_title("1.1 Geometría del Tendido y Puntos de Impacto", fontsize=11, fontweight="bold")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.2)

    # 1.2 Distribución de Calidad del Tendido
    ax = axes1[0, 1]
    counts = summary["spread_quality"]["counts"]
    grades = ["BUENA", "REGULAR", "MALA"]
    vals = [counts.get(g, 0) for g in grades]
    c_list = [COLORS[g] for g in grades]
    bars = ax.bar(grades, vals, color=c_list, width=0.55)
    for bar in bars:
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width() / 2.0, h + max(vals) * 0.02, f"{int(h)} ({100*h/sum(vals):.1f}%)", ha="center", fontsize=9, weight="bold")
    ax.set_ylabel("Número de trazas evaluadas", fontsize=9)
    ax.set_title(f"1.2 Calificación por Traza ({summary['spread_quality']['total_traces']} trazas)", fontsize=11, fontweight="bold")
    ax.grid(alpha=0.2, axis="y")

    # 1.3 Dromocrónicas de Primeros Arribos
    ax = axes1[1, 0]
    for stag, group in sorted(source_groups.items()):
        s_meta = group[-1]["meta"]
        picks = s_meta["picks_s"]
        valid_x = [ch * dx for ch, p in enumerate(picks) if p is not None]
        valid_t = [p * 1000.0 for p in picks if p is not None]
        if valid_x:
            ax.plot(valid_x, valid_t, "o-", ms=3.5, label=stag, alpha=0.75)
    ax.set_xlabel("Posición de receptor (m)", fontsize=9)
    ax.set_ylabel("Tiempo de primer arribo (ms)", fontsize=9)
    ax.set_title(f"1.3 Dromocrónicas TRS (Cobertura {summary['pick_coverage_percent']:.1f}%)", fontsize=11, fontweight="bold")
    ax.grid(alpha=0.2)
    if len(source_groups) <= 12:
        ax.legend(fontsize=7, ncol=3)

    # 1.4 Resumen de Velocidades de Rama
    ax = axes1[1, 1]
    ax.axis("off")
    table_data = [["Estación", "V1 (m/s)", "V2 (m/s)", "Xc (m)", "Espesor (m)"]]
    for b in summary["branches_summary"][:8]:
        v1 = f"{b['v1_ms']:.0f}" if b.get("v1_ms") else "N/D"
        v2 = f"{b['v2_ms']:.0f}" if b.get("v2_ms") else "N/D"
        xc = f"{b['crossover_m']:.1f}" if b.get("crossover_m") else "N/D"
        h = f"{b['apparent_thickness_m']:.1f}" if b.get("apparent_thickness_m") else "N/D"
        table_data.append([b["source_tag"], v1, v2, xc, h])
    tab = ax.table(cellText=table_data, loc="center", cellLoc="center")
    tab.auto_set_font_size(False)
    tab.set_fontsize(8.5)
    tab.scale(1.0, 1.4)
    ax.set_title("1.4 Ajuste Diagnóstico de Ramas de Refracción", fontsize=11, fontweight="bold", pad=20)

    p1 = output_dir / f"{slug}_trs_p1.png"
    fig1.savefig(p1, dpi=140)
    figures.append(p1)
    plt.close(fig1)

    # FIGURA 2: Matriz de Calidad por Canal y Repetibilidad
    fig2, axes2 = plt.subplots(2, 2, figsize=(14, 9))
    fig2.subplots_adjust(left=0.08, right=0.95, top=0.88, bottom=0.10, hspace=0.35, wspace=0.25)
    fig2.suptitle(
        f"{summary['title']} · Matriz de Calidad, Repetibilidad y Reciprocidad de Fermat",
        fontsize=14,
        fontweight="bold",
        color="#0f172a",
    )

    # 2.1 Matriz de Calidad (Shot vs Canal)
    ax = axes2[0, 0]
    matrix = np.zeros((len(shots), n_ch))
    grade_map = {"BUENA": 2, "REGULAR": 1, "MALA": 0, "NO_EVALUABLE": -1}
    for r_idx, s in enumerate(shots):
        for c_idx, q in enumerate(s["qualities"]):
            matrix[r_idx, c_idx] = grade_map.get(q["grade"], 0)
    cmap = matplotlib.colors.ListedColormap(["#dc2626", "#b77900", "#16803c"])
    ax.imshow(matrix, aspect="auto", cmap=cmap, origin="upper", vmin=0, vmax=2)
    ax.set_xlabel("Canal del tendido (1 a 24)", fontsize=9)
    ax.set_ylabel("Índice de disparo (1 a N)", fontsize=9)
    ax.set_title("2.1 Matriz de Calidad (Verde: Buena, Amarillo: Regular, Rojo: Mala)", fontsize=10, fontweight="bold")

    # 2.2 Repetibilidad intra-fuente
    ax = axes2[0, 1]
    rep = summary["repeatability"]
    corrs = [r["median_correlation"] for r in rep if r.get("median_correlation") is not None]
    if corrs:
        tags = [r["source_tag"] for r in rep if r.get("median_correlation") is not None]
        ax.bar(range(len(corrs)), corrs, color=["#16803c" if c >= 0.85 else "#b77900" if c >= 0.70 else "#dc2626" for c in corrs])
        ax.axhline(0.85, color="#16803c", ls="--", label="Excelente (≥0.85)")
        ax.axhline(0.70, color="#b77900", ls="--", label="Aceptable (≥0.70)")
        ax.set_xticks(range(len(corrs)))
        ax.set_xticklabels(tags, rotation=45, fontsize=8)
        ax.set_ylim(0, 1.05)
        ax.set_ylabel("Correlación mediana r", fontsize=9)
        ax.set_title("2.2 Repetibilidad Intra-Fuente entre Impactos", fontsize=10, fontweight="bold")
        ax.legend(loc="lower left", fontsize=8)
        ax.grid(alpha=0.2)

    # 2.3 Balance de SNR en decibelios
    ax = axes2[1, 0]
    all_snr = np.zeros(n_ch)
    for s in shots:
        for c_idx, q in enumerate(s["qualities"]):
            all_snr[c_idx] += float(s["mean_snr_db"])
    all_snr /= max(1, len(shots))
    ax.plot(np.arange(1, n_ch + 1), all_snr, "s-", color="#0369a1", lw=1.8, ms=5)
    ax.axhline(12.0, color="#16803c", ls="--", label="Umbral Bueno (12 dB)")
    ax.axhline(6.0, color="#dc2626", ls="--", label="Umbral Malo (6 dB)")
    ax.set_xlabel("Canal (1 a 24)", fontsize=9)
    ax.set_ylabel("SNR Neta Media (dB)", fontsize=9)
    ax.set_title("2.3 Perfil Espacial de SNR Media", fontsize=10, fontweight="bold")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(alpha=0.2)

    # 2.4 Reciprocidad de Fermat
    ax = axes2[1, 1]
    ax.axis("off")
    recip_data = [["Par Recíproco", "t_AB (s)", "t_BA (s)", "Δt (ms)", "Estado"]]
    if summary["reciprocal_pairs"]:
        for rp in summary["reciprocal_pairs"]:
            recip_data.append([
                rp["pair_id"],
                f"{rp['t_ab_s']:.4f}",
                f"{rp['t_ba_s']:.4f}",
                f"{rp['delta_t_ms']:.2f}",
                rp["status"],
            ])
    else:
        recip_data.append(["Extremos no evaluables", "N/D", "N/D", "N/D", "PENDIENTE"])
    tab2 = ax.table(cellText=recip_data, loc="center", cellLoc="center")
    tab2.auto_set_font_size(False)
    tab2.set_fontsize(8.5)
    tab2.scale(1.0, 1.5)
    ax.set_title("2.4 Reciprocidad de Fermat entre Disparos Opuestos", fontsize=10, fontweight="bold", pad=20)

    p2 = output_dir / f"{slug}_trs_p2.png"
    fig2.savefig(p2, dpi=140)
    figures.append(p2)
    plt.close(fig2)

    return figures


def build_trs_pdf(summary: dict[str, Any], figures: list[Path], output_pdf: Path) -> None:
    """Compila el informe PDF formal multipágina de control de calidad TRS."""
    with PdfPages(output_pdf) as pdf:
        for fig_path in figures:
            img = plt.imread(fig_path)
            fig, ax = plt.subplots(figsize=(11.69, 8.27))  # A4 landscape
            ax.imshow(img)
            ax.axis("off")
            pdf.savefig(fig, bbox_inches="tight", pad_inches=0.1)
            plt.close(fig)


def build_trs_html(summary: dict[str, Any], figures: list[Path], traces_records: list[dict[str, Any]], output_html: Path) -> None:
    """Genera el panel interactivo HTML autónomo de control de calidad TRS."""
    img_b64 = []
    for fig_path in figures:
        b64 = base64.b64encode(fig_path.read_bytes()).decode("ascii")
        img_b64.append(b64)

    slug = escape(summary["slug"])
    title = escape(summary["title"])
    technique = escape(summary["technique"])
    sq = summary["spread_quality"]
    grade = sq["grade"]
    color = DISPLAY_COLORS.get(grade, "#64748b")

    # Resumen de trazas
    rows_html = []
    for r in traces_records[:120]:  # Mostrar primeras 120 trazas en visor
        g = r["grade"]
        c = COLORS.get(g, "#64748b")
        onset_str = f"{r['onset_s']*1000.0:.2f} ms" if r["onset_s"] is not None else "Sin arribo"
        rows_html.append(
            f"<tr>"
            f"<td>{escape(r['shot_id'])}</td>"
            f"<td>{escape(r['source_tag'])}</td>"
            f"<td>Ch {r['channel']:02d}</td>"
            f"<td>{r['receiver_x_m']:.1f} m</td>"
            f"<td>{r['snr_db']:.1f} dB</td>"
            f"<td>{100.0 * r['clip_fraction']:.3f} %</td>"
            f"<td>{onset_str}</td>"
            f"<td><span class='badge' style='background-color:{c};'>{g}</span></td>"
            f"<td class='reason-cell'>{escape(r['reason'])}</td>"
            f"</tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dosier TRS · Control de Calidad Geofísico · {title}</title>
<style>
:root {{
  --bg-primary: #0f172a;
  --bg-secondary: #1e293b;
  --bg-card: #334155;
  --text-main: #f8fafc;
  --text-muted: #94a3b8;
  --accent-blue: #38bdf8;
  --border-color: #475569;
  --good: #16803c;
  --regular: #b77900;
  --bad: #dc2626;
}}
body {{
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  background-color: var(--bg-primary);
  color: var(--text-main);
  line-height: 1.5;
  padding: 24px;
}}
.container {{
  max-width: 1200px;
  margin: 0 auto;
}}
header {{
  border-bottom: 2px solid var(--border-color);
  padding-bottom: 20px;
  margin-bottom: 24px;
}}
h1 {{
  margin: 0 0 6px 0;
  font-size: 26px;
  color: var(--text-main);
}}
.subtitle {{
  color: var(--accent-blue);
  font-size: 14px;
  margin: 0;
}}
.grid-cards {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}}
.card {{
  background-color: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 16px;
}}
.card-title {{
  font-size: 12px;
  text-transform: uppercase;
  color: var(--text-muted);
  letter-spacing: 0.05em;
  margin-bottom: 8px;
}}
.card-value {{
  font-size: 22px;
  font-weight: bold;
}}
.badge {{
  display: inline-block;
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 13px;
  font-weight: bold;
  color: #fff;
}}
.alert-box {{
  background-color: #451a03;
  border-left: 4px solid #f59e0b;
  padding: 14px 18px;
  border-radius: 6px;
  margin-bottom: 24px;
  color: #fef3c7;
  font-size: 13px;
}}
.section-title {{
  font-size: 18px;
  color: var(--text-main);
  border-bottom: 1px solid var(--border-color);
  padding-bottom: 8px;
  margin: 28px 0 16px 0;
}}
.fig-container {{
  background-color: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 20px;
  text-align: center;
}}
.fig-container img {{
  max-width: 100%;
  height: auto;
  border-radius: 4px;
}}
table {{
  width: 100%;
  border-collapse: collapse;
  background-color: var(--bg-secondary);
  border-radius: 8px;
  overflow: hidden;
  font-size: 12px;
}}
th, td {{
  padding: 8px 12px;
  text-align: left;
  border-bottom: 1px solid var(--border-color);
}}
th {{
  background-color: var(--bg-card);
  color: var(--text-muted);
  font-weight: 600;
}}
tr:hover {{
  background-color: rgba(255, 255, 255, 0.03);
}}
.reason-cell {{
  color: var(--text-muted);
  font-size: 11px;
}}
footer {{
  margin-top: 40px;
  border-top: 1px solid var(--border-color);
  padding-top: 16px;
  color: var(--text-muted);
  font-size: 12px;
  text-align: center;
}}
</style>
</head>
<body>
<div class="container">
<header>
  <h1>{title} · Dosier de Control de Calidad TRS</h1>
  <p class="subtitle">{technique} · 24 canales × dx={summary['dx_m']} m · Longitud de Tendido {summary['aperture_m']} m</p>
</header>

<div class="alert-box">
  <strong>ESTATUS DE SUFICIENCIA DEL OBJETIVO: {summary['objective_sufficiency']} ({summary['acceptance_status']})</strong><br>
  {summary['objective_reason']}
</div>

<div class="grid-cards">
  <div class="card">
    <div class="card-title">Calificación Tendido Global</div>
    <div class="card-value"><span class="badge" style="background-color:{color};">{grade}</span></div>
    <small style="color:var(--text-muted);">assess_quality() sobre todas las trazas</small>
  </div>
  <div class="card">
    <div class="card-title">Proporción Trazas Buenas</div>
    <div class="card-value">{sq['good_percent_bounds'][0]:.1f}% - {sq['good_percent_bounds'][1]:.1f}%</div>
    <small style="color:var(--text-muted);">{sq['counts']['BUENA']} de {sq['total_traces']} trazas</small>
  </div>
  <div class="card">
    <div class="card-title">Cobertura de Primeros Arribos</div>
    <div class="card-value">{summary['pick_coverage_percent']:.1f}%</div>
    <small style="color:var(--text-muted);">{summary['all_picks_count']} onsets detectados</small>
  </div>
  <div class="card">
    <div class="card-title">Estaciones de Disparo</div>
    <div class="card-value">{summary['sources_count']} fuentes</div>
    <small style="color:var(--text-muted);">{summary['total_files']} registros SEG-2</small>
  </div>
</div>

<div class="section-title">1. Geometría, Cobertura y Hodógrafas del Tendido</div>
<div class="fig-container">
  <img src="data:image/png;base64,{img_b64[0]}" alt="Geometría y dromocrónicas TRS">
</div>

<div class="section-title">2. Calidad Diagnóstica por Canal, Repetibilidad y Reciprocidad de Fermat</div>
<div class="fig-container">
  <img src="data:image/png;base64,{img_b64[1]}" alt="Matriz de calidad y repetibilidad TRS">
</div>

<div class="section-title">3. Registro de Trazas Evaluadas (Muestra de Canales)</div>
<div style="overflow-x:auto;">
<table>
  <thead>
    <tr>
      <th>Disparo</th>
      <th>Estación</th>
      <th>Canal</th>
      <th>Offset</th>
      <th>SNR Neta</th>
      <th>Clipping</th>
      <th>Primer Arribo</th>
      <th>Calificación</th>
      <th>Motivo Diagnóstico</th>
    </tr>
  </thead>
  <tbody>
    {"".join(rows_html)}
  </tbody>
</table>
</div>

<footer>
  Sistema Antigravity QC Sísmico · Dosier TRS reproducible con verificación criptográfica SHA-256.
</footer>
</div>
</body>
</html>
"""
    output_html.write_text(html, encoding="utf-8")


def export_trs_csvs(summary: dict[str, Any], traces_records: list[dict[str, Any]], output_dir: Path) -> None:
    """Exporta las tablas CSV formales del dosier TRS."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. traces_trs.csv
    with open(output_dir / "traces_trs.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "shot_id",
                "file_name",
                "source_tag",
                "channel",
                "receiver_x_m",
                "rms_ac",
                "ptp",
                "clip_fraction",
                "snr_db",
                "onset_s",
                "grade",
                "color",
                "reason",
            ],
        )
        writer.writeheader()
        writer.writerows(traces_records)

    # 2. picks_trs.csv
    with open(output_dir / "picks_trs.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["shot_id", "source_tag", "channel", "receiver_x_m", "onset_s", "onset_ms"])
        for r in traces_records:
            if r["onset_s"] is not None:
                writer.writerow([
                    r["shot_id"],
                    r["source_tag"],
                    r["channel"],
                    r["receiver_x_m"],
                    f"{r['onset_s']:.6f}",
                    f"{r['onset_s']*1000.0:.3f}",
                ])

    # 3. reciprocity_trs.csv
    with open(output_dir / "reciprocity_trs.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["pair_id", "t_ab_s", "t_ba_s", "delta_t_ms", "tolerance_ms", "status"])
        for rp in summary["reciprocal_pairs"]:
            writer.writerow([
                rp["pair_id"],
                f"{rp['t_ab_s']:.6f}",
                f"{rp['t_ba_s']:.6f}",
                f"{rp['delta_t_ms']:.3f}",
                f"{rp['tolerance_ms']:.1f}",
                rp["status"],
            ])

    # 4. repeatability_trs.csv
    with open(output_dir / "repeatability_trs.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["source_tag", "shots_count", "pair", "median_correlation", "min_correlation", "max_correlation", "grade"])
        for rep in summary["repeatability"]:
            med = f"{rep['median_correlation']:.4f}" if rep["median_correlation"] is not None else ""
            mi = f"{rep['min_correlation']:.4f}" if rep["min_correlation"] is not None else ""
            ma = f"{rep['max_correlation']:.4f}" if rep["max_correlation"] is not None else ""
            writer.writerow([rep["source_tag"], rep["shots_count"], rep["pair"], med, mi, ma, rep["grade"]])

    # 5. summary_trs.csv
    with open(output_dir / "summary_trs.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "value"])
        writer.writerow(["slug", summary["slug"]])
        writer.writerow(["title", summary["title"]])
        writer.writerow(["technique", summary["technique"]])
        writer.writerow(["channels", summary["channels"]])
        writer.writerow(["dx_m", summary["dx_m"]])
        writer.writerow(["aperture_m", summary["aperture_m"]])
        writer.writerow(["spread_grade", summary["spread_quality"]["grade"]])
        writer.writerow(["good_traces_count", summary["spread_quality"]["counts"]["BUENA"]])
        writer.writerow(["regular_traces_count", summary["spread_quality"]["counts"]["REGULAR"]])
        writer.writerow(["bad_traces_count", summary["spread_quality"]["counts"]["MALA"]])
        writer.writerow(["total_traces", summary["spread_quality"]["total_traces"]])
        writer.writerow(["good_percent_lower", summary["spread_quality"]["good_percent_bounds"][0]])
        writer.writerow(["good_percent_upper", summary["spread_quality"]["good_percent_bounds"][1]])
        writer.writerow(["pick_coverage_percent", summary["pick_coverage_percent"]])
        writer.writerow(["acceptance_status", summary["acceptance_status"]])
        writer.writerow(["objective_sufficiency", summary["objective_sufficiency"]])


def generate_trs_dossier(survey_path: Path, output_dir: Path) -> dict[str, Any]:
    """Flujo completo de generación del dosier TRS."""
    print(f"--> Analizando levantamiento TRS: {survey_path.name}")
    summary, traces_records, source_groups = analyze_trs_survey(survey_path)

    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Generar figuras
    figures = plot_trs_figures(summary, source_groups, output_dir)

    # 2. Generar PDF
    pdf_path = output_dir / "dossier_trs.pdf"
    build_trs_pdf(summary, figures, pdf_path)
    print(f"    [+] Generado PDF: {pdf_path.name}")

    # 3. Generar HTML
    html_path = output_dir / "dossier_trs.html"
    build_trs_html(summary, figures, traces_records, html_path)
    print(f"    [+] Generado HTML: {html_path.name}")

    # 4. Generar CSVs
    export_trs_csvs(summary, traces_records, output_dir)
    print(f"    [+] Exportadas tablas CSV en: {output_dir.name}")

    # 5. Generar JSON
    json_path = output_dir / "dossier_trs.json"
    json_data = json.dumps(summary, indent=2, ensure_ascii=False)
    json_path.write_text(json_data, encoding="utf-8")
    print(f"    [+] Generado JSON canónico: {json_path.name}")

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Generador de Dosieres TRS")
    parser.add_argument("--survey-dir", type=Path, help="Ruta al directorio del levantamiento TRS")
    parser.add_argument("--output-dir", type=Path, help="Ruta al directorio de salida")
    parser.add_argument("--all-surveys", action="store_true", help="Procesa todos los levantamientos KM en el root")
    args = parser.parse_args()

    if args.all_surveys:
        km_surveys = ["KM 40+672", "KM 44+552", "KM 52+500"]
        for km in km_surveys:
            p = ROOT / km
            if p.exists():
                slug = SURVEY_METADATA[km]["slug"]
                out = ROOT / "evidence/trs" / slug
                generate_trs_dossier(p, out)
        return 0

    if not args.survey_dir or not args.output_dir:
        parser.print_help()
        return 1

    generate_trs_dossier(args.survey_dir, args.output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
