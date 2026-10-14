"""Generador de Dosieres de Control de Calidad Geofísico para Levantamientos KM*.

Procesa los levantamientos de campo reales:
- KM 40+672 (TRS 24 ch x dx 5.0m, 9 fuentes)
- KM 44+552 (TRS 24 ch x dx 5.0m, 9 fuentes)
- KM 52+500 (TRS 24 ch x dx 2.5m, 11 fuentes + MAM pasivo)

Genera para cada uno:
- dossier.json (schema y digest criptográfico)
- dossier.pdf (reporte gráfico formal multipágina)
- dossier.html (panel interactivo autónomo en Base64)
- traces.csv, shots.csv, repeatability.csv, first_arrivals.csv
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import platform
import re
from datetime import UTC, datetime
from html import escape
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
from geoqc.core.evidence import canonical_hash  # noqa: E402
from geoqc.io.binary import parse_seg2  # noqa: E402
from geoqc.masw.curves import ridge_path  # noqa: E402
from geoqc.masw.diagnostic_quality import UsabilityPolicy, assess_ridges  # noqa: E402
from geoqc.masw.transform import phase_shift  # noqa: E402


SURVEY_CONFIGS = {
    "KM 40+672": {
        "slug": "KM_40_672",
        "title": "KM 40+672",
        "technique": "TRS (Refracción Sísmica) / MASW",
        "dx_m": 5.0,
        "channels": 24,
        "sources_expected": 9,
        "notes": "TRS tendido 24 geófonos espaciados a 5.0 m (L = 115 m). 9 fuentes cada 15 m con 3-4 golpes por fuente.",
    },
    "KM 44+552": {
        "slug": "KM_44_552",
        "title": "KM 44+552",
        "technique": "TRS (Refracción Sísmica) / MASW",
        "dx_m": 5.0,
        "channels": 24,
        "sources_expected": 9,
        "notes": "TRS tendido 24 geófonos espaciados a 5.0 m (L = 115 m). 9 fuentes cada 15 m con 3-5 golpes por fuente.",
    },
    "KM 52+500": {
        "slug": "KM_52_500",
        "title": "KM 52+500",
        "technique": "TRS (Refracción Sísmica) / MAM",
        "dx_m": 2.5,
        "channels": 24,
        "sources_expected": 11,
        "notes": "TRS tendido 24 geófonos espaciados a 2.5 m (L = 57.5 m). 11 fuentes con 3-5 golpes por fuente + MAM pasivo.",
    },
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def detect_clipping(trace: np.ndarray, threshold_consecutive: int = 4) -> bool:
    """Detecta mesetas en extremos de amplitud (sospecha de clipping morfológico)."""
    ptp = np.ptp(trace)
    if ptp == 0:
        return False
    max_val, min_val = np.max(trace), np.min(trace)
    tol = ptp * 1e-4
    diff = np.diff(trace)
    zero_diff = np.abs(diff) <= tol
    at_extreme = (np.abs(trace[:-1] - max_val) <= tol) | (np.abs(trace[:-1] - min_val) <= tol)
    plateaus = zero_diff & at_extreme
    count = 0
    for p in plateaus:
        count = count + 1 if p else 0
        if count >= threshold_consecutive:
            return True
    return False


def estimate_first_arrival(trace: np.ndarray, dt: float, pre_samples: int = 400) -> float | None:
    """Estimador robusto de primer arribo mediante STA/LTA simple."""
    tr = trace - np.mean(trace[:pre_samples])
    noise = np.std(tr[:pre_samples])
    if noise == 0 or not np.isfinite(noise):
        return None
    # STA/LTA
    sta_len = int(0.002 / dt)  # 2 ms
    lta_len = int(0.020 / dt)  # 20 ms
    if len(tr) < lta_len + sta_len:
        return None
    energy = tr**2
    sta = np.convolve(energy, np.ones(sta_len) / sta_len, mode="full")[: len(energy)]
    lta = np.convolve(energy, np.ones(lta_len) / lta_len, mode="full")[: len(energy)] + 1e-12
    ratio = sta / lta
    # Look for trigger above 3.5 after pre_samples
    above = np.where(ratio[pre_samples:] > 3.5)[0]
    if len(above):
        pick_idx = above[0] + pre_samples
        return float(pick_idx * dt)
    return None


def analyze_survey(km_dir: Path, cfg: dict) -> dict:
    dx = cfg["dx_m"]
    n_ch = cfg["channels"]
    files = sorted(km_dir.rglob("*.sg2"))
    if not files:
        raise ValueError(f"No se encontraron archivos .sg2 en {km_dir}")

    # Separar TRS vs MAM si aplica
    trs_files = [f for f in files if "MAM" not in f.parts]
    mam_files = [f for f in files if "MAM" in f.parts]

    shots = []
    traces_records = []
    source_groups: dict[str, list[dict]] = {}

    for idx, f in enumerate(trs_files, 1):
        # Inferir fuente de la carpeta (e.g. F1, F2...)
        match_f = re.search(r"F(\d+)", str(f), re.IGNORECASE)
        src_tag = f"F{int(match_f.group(1)):02d}" if match_f else "F_UNKNOWN"

        raw_bytes = f.read_bytes()
        file_sha = hashlib.sha256(raw_bytes).hexdigest()
        w = parse_seg2(raw_bytes)
        data = np.array(w.traces)
        dt = w.dt_s[0]
        fs = 1.0 / dt
        m_samples = data.shape[1]

        # Integridad digital
        is_finite = bool(np.all(np.isfinite(data)))
        dead_channels = [ch + 1 for ch, tr in enumerate(data) if np.ptp(tr) == 0]
        clipped_channels = [ch + 1 for ch, tr in enumerate(data) if detect_clipping(tr)]
        rms_values = [float(np.sqrt(np.mean((tr - np.mean(tr)) ** 2))) for tr in data]
        ptp_values = [float(np.ptp(tr)) for tr in data]

        # Primeros arribos estimados
        picks = [estimate_first_arrival(tr, dt) for tr in data]
        valid_picks = [p for p in picks if p is not None]

        shot_meta = {
            "shot_id": f"{cfg['slug']}_S{idx:03d}",
            "file_name": f.name,
            "relative_path": f.relative_to(km_dir).as_posix(),
            "sha256": file_sha,
            "source_tag": src_tag,
            "channels": int(data.shape[0]),
            "samples": int(m_samples),
            "dt_s": dt,
            "fs_hz": fs,
            "duration_s": float(m_samples * dt),
            "is_finite": is_finite,
            "dead_channels": dead_channels,
            "clipped_channels": clipped_channels,
            "has_dead": len(dead_channels) > 0,
            "has_clipping": len(clipped_channels) > 0,
            "mean_rms": float(np.mean(rms_values)),
            "picks_count": len(valid_picks),
            "picks_s": picks,
            "acquisition_date": w.headers["file_header"].get("ACQUISITION_DATE", "UNKNOWN"),
            "acquisition_time": w.headers["file_header"].get("ACQUISITION_TIME", "UNKNOWN"),
        }
        shots.append(shot_meta)
        source_groups.setdefault(src_tag, []).append({"meta": shot_meta, "data": data})

        for ch in range(data.shape[0]):
            traces_records.append(
                {
                    "shot_id": shot_meta["shot_id"],
                    "source_tag": src_tag,
                    "channel_1based": ch + 1,
                    "offset_declared_m": ch * dx,
                    "rms_ac_native": rms_values[ch],
                    "ptp_native": ptp_values[ch],
                    "is_dead": (ch + 1) in dead_channels,
                    "suspected_clipping": (ch + 1) in clipped_channels,
                    "first_arrival_s": picks[ch],
                }
            )

    # Evaluación de repetibilidad por fuente
    repeatability = []
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
        # Calcular correlación cruzada canal por canal entre disparos consecutivos
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
                    "pair": f"Shot {i+1} vs {i+2}",
                    "median_correlation": med_c,
                    "min_correlation": float(np.min(corrs)) if corrs else None,
                    "max_correlation": float(np.max(corrs)) if corrs else None,
                    "grade": grade,
                }
            )

    # Análisis MASW en disparos extremos F01 y F_end
    masw_results = []
    candidate_sources = ["F01", sorted(source_groups.keys())[-1]]
    policy = UsabilityPolicy()
    for src_tag in candidate_sources:
        if src_tag not in source_groups:
            continue
        # Usar el último golpe de la fuente (usualmente mejor acoplado)
        shot_item = source_groups[src_tag][-1]
        shot_data = shot_item["data"]
        dt = shot_item["meta"]["dt_s"]
        x_coords = np.arange(n_ch) * dx
        c_grid = np.arange(80.0, 800.0, 2.0)
        f_all = np.fft.rfftfreq(shot_data.shape[1], dt)
        sel = (f_all >= 3.0) & (f_all <= 60.0)
        f_grid = f_all[sel]
        centered = shot_data - shot_data.mean(axis=1, keepdims=True)
        window = np.hanning(shot_data.shape[1])
        spectrum = np.fft.rfft(centered * window, axis=1).T[sel]
        direction = 1 if src_tag == "F01" else -1
        res = phase_shift(spectrum, f_grid, x_coords, c_grid, direction=direction)
        path = list(ridge_path(res["coherence"], f_grid, c_grid, slope_scale_ms_per_hz=30.0, penalty=0.02))
        ridge = c_grid[path]

        # Variantes para sensibilidad
        rect = np.fft.rfft(centered, axis=1).T[sel]
        rect_res = phase_shift(rect, f_grid, x_coords, c_grid, direction=direction)
        rect_path = list(ridge_path(rect_res["coherence"], f_grid, c_grid, slope_scale_ms_per_hz=30.0, penalty=0.02))
        sub_spec = spectrum[:, 1:] if direction == 1 else spectrum[:, :-1]
        sub_x = x_coords[1:] if direction == 1 else x_coords[:-1]
        drop_res = phase_shift(sub_spec, f_grid, sub_x, c_grid, direction=direction)
        drop_path = list(ridge_path(drop_res["coherence"], f_grid, c_grid, slope_scale_ms_per_hz=30.0, penalty=0.02))
        unpen = c_grid[np.argmax(res["coherence"], axis=1)]

        variants = np.vstack([c_grid[rect_path], c_grid[drop_path], unpen])
        quality = assess_ridges(spectrum, f_grid, x_coords, ridge, variants, policy)
        usable_bins = sum(q.grade == "UTILIZABLE" for q in quality)
        review_bins = sum(q.grade == "REVISAR" for q in quality)

        masw_results.append(
            {
                "source_tag": src_tag,
                "shot_id": shot_item["meta"]["shot_id"],
                "direction": direction,
                "total_bins": len(quality),
                "usable_bins": usable_bins,
                "review_bins": review_bins,
                "quality_objects": quality,
                "frequencies_hz": f_grid.tolist(),
                "ridge_c_ms": ridge.tolist(),
                "coherence": [float(q.coherence) if q.coherence is not None else None for q in quality],
                "contrast": [float(q.contrast) if q.contrast is not None else None for q in quality],
                "competitor_ratio": [
                    float(q.competitor_ratio) if q.competitor_ratio is not None else None for q in quality
                ],
                "sensitivity_rel": [
                    float(q.sensitivity_rel) if q.sensitivity_rel is not None else None for q in quality
                ],
                "reasons": [list(q.reasons) for q in quality],
                "grades": [q.grade for q in quality],
            }
        )

    # Resumen global del levantamiento
    all_corrs = [
        r["median_correlation"]
        for r in repeatability
        if r["median_correlation"] is not None and np.isfinite(r["median_correlation"])
    ]
    mean_rep = float(np.mean(all_corrs)) if all_corrs else None
    dead_total = sum(len(s["dead_channels"]) for s in shots)
    clipped_total = sum(len(s["clipped_channels"]) for s in shots)

    summary = {
        "slug": cfg["slug"],
        "title": cfg["title"],
        "technique": cfg["technique"],
        "dx_m": dx,
        "channels": n_ch,
        "aperture_m": (n_ch - 1) * dx,
        "total_files": len(files),
        "trs_shots_count": len(shots),
        "mam_files_count": len(mam_files),
        "total_traces": len(traces_records),
        "sources_identified": sorted(list(source_groups.keys())),
        "sources_count": len(source_groups),
        "dead_traces_count": dead_total,
        "suspected_clipped_traces_count": clipped_total,
        "average_repeatability_corr": mean_rep,
        "integrity_status": "PASS" if dead_total == 0 else "ADVERTENCIA",
        "notes": cfg["notes"],
        "shots": shots,
        "repeatability": repeatability,
        "masw_results": masw_results,
    }
    return summary, traces_records, source_groups


def plot_survey_figures(summary: dict, source_groups: dict, masw_results: list[dict], output_dir: Path) -> list[Path]:
    figures = []
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = summary["slug"]
    dx = summary["dx_m"]
    n_ch = summary["channels"]

    # FIGURA 1: Síntesis del Levantamiento y Repetibilidad
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    fig.subplots_adjust(left=0.08, right=0.95, top=0.90, bottom=0.10, hspace=0.35, wspace=0.25)
    fig.suptitle(
        f"{summary['title']} · Dosier de Control de Calidad Geofísico de Campo\n"
        f"{summary['technique']} · 24 canales × dx={dx:g} m · L={(n_ch-1)*dx:g} m",
        fontsize=15,
        fontweight="bold",
        color="#0f172a",
    )

    # 1.1 Esquema de fuentes y receptores
    ax = axes[0, 0]
    rec_x = np.arange(n_ch) * dx
    ax.scatter(rec_x, np.zeros_like(rec_x), marker="v", s=60, color="#0369a1", label="Geófonos (1 a 24)")
    for i, src_tag in enumerate(summary["sources_identified"]):
        # aproximar posición de fuente según su número
        src_num = int(src_tag.replace("F", ""))
        src_pos = (src_num - 1) * (len(rec_x) * dx / (len(summary["sources_identified"]) - 1 or 1))
        ax.scatter([src_pos], [0.5 + (i % 2) * 0.4], marker="*", s=140, color="#b77900")
        ax.text(src_pos, 0.5 + (i % 2) * 0.4 + 0.15, src_tag, ha="center", fontsize=8, weight="bold")
    ax.set_ylim(-0.5, 1.5)
    ax.set_yticks([])
    ax.set_xlabel("Distancia a lo largo del perfil (m)")
    ax.set_title("Geometría de Fuentes y Receptores", fontsize=11, fontweight="bold")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.2)

    # 1.2 Histograma de Repetibilidad (Correlación entre golpes)
    ax = axes[0, 1]
    corrs = [
        r["median_correlation"]
        for r in summary["repeatability"]
        if r["median_correlation"] is not None and np.isfinite(r["median_correlation"])
    ]
    if corrs:
        ax.bar(
            range(len(corrs)),
            corrs,
            color=["#16803c" if c >= 0.85 else "#b77900" if c >= 0.70 else "#b91c1c" for c in corrs],
        )
        ax.axhline(0.85, color="#16803c", ls="--", label="Excelente (≥0.85)")
        ax.axhline(0.70, color="#b77900", ls="--", label="Aceptable (≥0.70)")
        ax.set_xticks(range(len(corrs)))
        ax.set_xticklabels([r["source_tag"] for r in summary["repeatability"] if r["median_correlation"] is not None], rotation=45, fontsize=8)
        ax.set_ylim(0, 1.05)
        ax.set_ylabel("Correlación mediana entre golpes")
        ax.set_title("Repetibilidad Intra-Fuente por Posición", fontsize=11, fontweight="bold")
        ax.legend(loc="lower left", fontsize=8)
    ax.grid(alpha=0.2)

    # 1.3 Amplitudes RMS promedio por canal
    ax = axes[1, 0]
    all_rms = np.zeros(n_ch)
    count_rms = 0
    for group in source_groups.values():
        for item in group:
            d = item["data"]
            all_rms += np.sqrt(np.mean((d - d.mean(axis=1, keepdims=True)) ** 2, axis=1))
            count_rms += 1
    if count_rms > 0:
        all_rms /= count_rms
        ax.bar(np.arange(1, n_ch + 1), all_rms, color="#0369a1")
        ax.set_xlabel("Canal (1 a 24)")
        ax.set_ylabel("Amplitud RMS nativa media")
        ax.set_title("Balance de Amplitudes por Canal", fontsize=11, fontweight="bold")
        ax.grid(alpha=0.2)

    # 1.4 Primeros arribos superpuestos (Hodógrafas TRS)
    ax = axes[1, 1]
    for src_tag, group in source_groups.items():
        first_shot = group[0]["meta"]
        picks = first_shot["picks_s"]
        valid_x = [ch * dx for ch, p in enumerate(picks) if p is not None]
        valid_t = [p * 1000 for p in picks if p is not None]
        if valid_x:
            ax.plot(valid_x, valid_t, "o-", ms=3, label=src_tag, alpha=0.7)
    ax.set_xlabel("Posición de receptor (m)")
    ax.set_ylabel("Tiempo de primer arribo (ms)")
    ax.set_title("Abanico de Primeros Arribos TRS (Hodógrafas)", fontsize=11, fontweight="bold")
    ax.grid(alpha=0.2)
    if len(source_groups) <= 12:
        ax.legend(fontsize=7, ncol=3)

    p1 = output_dir / f"{slug}_summary.png"
    fig.savefig(p1, dpi=130)
    figures.append(p1)
    plt.close(fig)

    # FIGURA 2: Espectros de Dispersión MASW y Calidad Diagnóstica
    if masw_results:
        fig, axes = plt.subplots(len(masw_results), 2, figsize=(14, 5 * len(masw_results)))
        if len(masw_results) == 1:
            axes = np.array([axes])
        fig.suptitle(
            f"{summary['title']} · Diagnóstico de Dispersión MASW en Disparos de Extremo",
            fontsize=15,
            fontweight="bold",
        )
        for row, masw in enumerate(masw_results):
            # Espectro coherencia
            f = np.array(masw["frequencies_hz"])
            c = np.array(masw["ridge_c_ms"])
            usable_mask = np.array([g == "UTILIZABLE" for g in masw["grades"]])
            ax = axes[row, 0]
            ax.plot(f, c, "--", color="#64748b", lw=1, label="Cresta aparente total")
            ax.plot(f[usable_mask], c[usable_mask], color="#16803c", lw=2.5, label="Utilizable* (controles DRAFT)")
            # Limite Nyquist
            c_nyq = 2 * dx * f
            ax.plot(f, c_nyq, ":", color="#b91c1c", label=f"Nyquist espacial c=2·dx·f (dx={dx:g}m)")
            ax.set_ylim(80, 700)
            ax.set_xlabel("Frecuencia (Hz)")
            ax.set_ylabel("Velocidad de fase aparente (m/s)")
            ax.set_title(
                f"Disparo {masw['source_tag']} ({masw['shot_id']}) · Dispersión", fontsize=11, fontweight="bold"
            )
            ax.legend(fontsize=8)
            ax.grid(alpha=0.2)

            # Controles de Usabilidad
            ax2 = axes[row, 1]
            coh = np.array(masw["coherence"])
            cont = np.array(masw["contrast"])
            comp = np.array(masw["competitor_ratio"])
            ax2.plot(f, coh, color="#0369a1", label="Coherencia cresta I")
            ax2.plot(f, cont, color="#16803c", label="Contraste cresta-fondo")
            ax2.plot(f, comp, color="#b77900", label="Razón competidor/cresta")
            ax2.axhline(0.60, color="#0369a1", ls="--", alpha=0.5)
            ax2.axhline(0.25, color="#16803c", ls="--", alpha=0.5)
            ax2.axhline(0.80, color="#b77900", ls="--", alpha=0.5)
            ax2.set_ylim(-0.1, 1.1)
            ax2.set_xlabel("Frecuencia (Hz)")
            ax2.set_ylabel("Magnitud adimensional")
            ax2.set_title(
                f"Controles Internos {masw['source_tag']} (Bins utilizables: {masw['usable_bins']}/{masw['total_bins']})",
                fontsize=11,
                fontweight="bold",
            )
            ax2.legend(fontsize=8)
            ax2.grid(alpha=0.2)

        fig.subplots_adjust(left=0.08, right=0.95, top=0.90, bottom=0.08, hspace=0.35, wspace=0.25)
        p2 = output_dir / f"{slug}_masw_qc.png"
        fig.savefig(p2, dpi=130)
        figures.append(p2)
        plt.close(fig)

    return figures


def render_html_dossier(summary: dict, traces: list[dict], figures: list[Path], output_dir: Path) -> str:
    slug = summary["slug"]

    def embed_img(path: Path, alt: str) -> str:
        if not path.exists():
            return ""
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        return f'<img src="data:image/png;base64,{b64}" alt="{escape(alt)}" style="max-width:100%; height:auto; border-radius:8px; margin:15px 0;">'

    def fmt_val(v: float | None) -> str:
        return f"{v:.3f}" if v is not None else "—"

    rep_rows = "".join(
        f"<tr><td>{r['source_tag']}</td><td>{r['shots_count']}</td><td>{r['pair']}</td>"
        f"<td>{fmt_val(r['median_correlation'])}</td>"
        f"<td><span class='badge badge-{r['grade'].lower()}'>{r['grade']}</span></td></tr>"
        for r in summary["repeatability"]
    )
    shots_rows = "".join(
        f"<tr><td>{s['shot_id']}</td><td>{s['source_tag']}</td><td>{s['file_name']}</td>"
        f"<td>{s['fs_hz']:.0f} Hz</td><td>{s['duration_s']:.2f} s</td>"
        f"<td>{'PASS' if s['is_finite'] else 'FAIL'}</td>"
        f"<td>{len(s['dead_channels'])}</td><td>{len(s['clipped_channels'])}</td>"
        f"<td>{s['picks_count']}/24</td></tr>"
        for s in summary["shots"][:30]
    )

    imgs = "".join(embed_img(p, p.name) for p in figures)

    avg_rep_str = f"{summary['average_repeatability_corr']:.2f}" if summary['average_repeatability_corr'] is not None else "N/A"
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dosier QC · {summary['title']}</title>
<style>
body {{ font-family: system-ui, -apple-system, sans-serif; background: #f8fafc; color: #0f172a; margin: 0; padding: 20px; line-height: 1.5; }}
main {{ max-width: 1200px; margin: auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); }}
header {{ border-bottom: 2px solid #e2e8f0; padding-bottom: 20px; margin-bottom: 25px; }}
h1 {{ font-size: 28px; margin: 0 0 8px 0; color: #0369a1; }}
h2 {{ font-size: 20px; color: #0f172a; border-left: 4px solid #0369a1; padding-left: 10px; margin-top: 30px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; margin: 15px 0; }}
th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #e2e8f0; }}
th {{ background: #f1f5f9; font-weight: 600; }}
.badge {{ display: inline-block; padding: 3px 8px; border-radius: 12px; font-size: 11px; font-weight: bold; }}
.badge-excelente {{ background: #dcfce7; color: #166534; }}
.badge-buena {{ background: #fef9c3; color: #854d0e; }}
.badge-regular {{ background: #ffedd5; color: #9a3412; }}
.badge-sin_repeticion {{ background: #f1f5f9; color: #475569; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; margin: 20px 0; }}
.card {{ background: #f8fafc; padding: 15px; border-radius: 8px; border: 1px solid #e2e8f0; }}
.card-val {{ font-size: 22px; font-weight: bold; color: #0369a1; }}
.card-lbl {{ font-size: 12px; color: #64748b; }}
</style>
</head>
<body>
<main>
<header>
  <h1>{summary['title']} · Dosier de Control de Calidad Geofísico</h1>
  <p><strong>Técnica:</strong> {summary['technique']} | <strong>Geometría:</strong> 24 geófonos × dx={summary['dx_m']} m (L={summary['aperture_m']} m)</p>
  <p><em>{summary['notes']}</em></p>
</header>

<div class="grid">
  <div class="card"><div class="card-val">{summary['trs_shots_count']}</div><div class="card-lbl">Disparos TRS Registrados</div></div>
  <div class="card"><div class="card-val">{summary['sources_count']}</div><div class="card-lbl">Fuentes de Impacto Distintas</div></div>
  <div class="card"><div class="card-val">{summary['total_traces']}</div><div class="card-lbl">Trazas Sismográficas Evaluadas</div></div>
  <div class="card"><div class="card-val">{avg_rep_str}</div><div class="card-lbl">Correlación Media de Repetibilidad</div></div>
  <div class="card"><div class="card-val">{summary['integrity_status']}</div><div class="card-lbl">Integridad Digital Global</div></div>
</div>

<h2>Evidencia Gráfica y Diagnóstica</h2>
{imgs}

<h2>Control de Repetibilidad Intra-Fuente (Múltiples Golpes)</h2>
<p>Evalúa la coherencia de la señal sísmica entre impactos sucesivos sobre la misma posición de fuente:</p>
<table>
<thead><tr><th>Fuente</th><th>Golpes</th><th>Comparación</th><th>Correlación Mediana</th><th>Calificación</th></tr></thead>
<tbody>{rep_rows}</tbody>
</table>

<h2>Inventario de Disparos Analizados (Muestra de los primeros 30)</h2>
<table>
<thead><tr><th>ID Disparo</th><th>Fuente</th><th>Archivo</th><th>Tasa Muestreo</th><th>Duración</th><th>Finitud</th><th>Canales Muertos</th><th>Sospecha Clipping</th><th>Picks Arribos</th></tr></thead>
<tbody>{shots_rows}</tbody>
</table>

<footer>
  <p style="font-size:12px; color:#64748b; margin-top:30px;">
    Generado por GeoQC-Field · Diagnóstico de campo reproducible · Archivos crudos conservados intactos.
  </p>
</footer>
</main>
</body>
</html>
"""


def process_all_km_surveys(base_dir: Path, output_base: Path):
    print("=" * 70)
    print("INICIANDO CONTROL DE CALIDAD PARA LEVANTAMIENTOS KM*")
    print("=" * 70)

    results_all = {}
    for folder_name, cfg in SURVEY_CONFIGS.items():
        km_dir = base_dir / folder_name
        if not km_dir.exists():
            print(f"[-] Omitiendo {folder_name} (directorio no encontrado)")
            continue

        print(f"\n[+] Procesando levantamiento: {folder_name}...")
        survey_out = output_base / cfg["slug"]
        survey_out.mkdir(parents=True, exist_ok=True)

        # Análisis completo
        summary, traces, source_groups = analyze_survey(km_dir, cfg)
        print(f"    - Disparos TRS procesados: {summary['trs_shots_count']}")
        print(f"    - Fuentes detectadas: {summary['sources_count']} ({summary['sources_identified']})")
        print(f"    - Trazas analizadas: {summary['total_traces']}")
        rep_str = f"{summary['average_repeatability_corr']:.3f}" if summary['average_repeatability_corr'] is not None else "N/A"
        print(f"    - Repetibilidad media: {rep_str}")

        # Generar figuras
        figures = plot_survey_figures(summary, source_groups, summary["masw_results"], survey_out)

        # Generar PDF multipágina
        pdf_path = survey_out / "dossier.pdf"
        with PdfPages(pdf_path) as pdf:
            for fig_path in figures:
                img = plt.imread(fig_path)
                f, ax = plt.subplots(figsize=(11.7, 8.3))
                ax.imshow(img)
                ax.axis("off")
                pdf.savefig(f, bbox_inches="tight")
                plt.close(f)
        print(f"    - PDF generado: {pdf_path.name}")

        # Generar HTML autónomo
        html_content = render_html_dossier(summary, traces, figures, survey_out)
        html_path = survey_out / "dossier.html"
        html_path.write_text(html_content, encoding="utf-8")
        print(f"    - HTML generado: {html_path.name}")

        # Exportar CSVs
        traces_csv = survey_out / "traces.csv"
        with traces_csv.open("w", newline="", encoding="utf-8-sig") as stream:
            w = csv.DictWriter(stream, fieldnames=list(traces[0].keys()))
            w.writeheader()
            w.writerows(traces)

        rep_csv = survey_out / "repeatability.csv"
        with rep_csv.open("w", newline="", encoding="utf-8-sig") as stream:
            w = csv.DictWriter(stream, fieldnames=list(summary["repeatability"][0].keys()))
            w.writeheader()
            w.writerows(summary["repeatability"])

        shots_csv = survey_out / "shots.csv"
        with shots_csv.open("w", newline="", encoding="utf-8-sig") as stream:
            # excluir picks_s array para que sea csv plano
            sample_keys = [k for k in summary["shots"][0].keys() if k != "picks_s"]
            w = csv.DictWriter(stream, fieldnames=sample_keys)
            w.writeheader()
            for s in summary["shots"]:
                row = {k: json.dumps(s[k]) if isinstance(s[k], list) else s[k] for k in sample_keys}
                w.writerow(row)

        # JSON maestro
        # Sanitizar summary para JSON
        summary_clean = {
            k: v
            for k, v in summary.items()
            if k not in ("masw_results", "shots")
            or k == "shots"
            and len(v) <= 100
        }
        # Agregar digest canónico
        summary_clean["scientific_digest"] = canonical_hash(summary_clean)
        summary_clean["generated_at_utc"] = datetime.now(UTC).isoformat()
        json_path = survey_out / "dossier.json"
        json_path.write_text(json.dumps(summary_clean, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"    - JSON generado: {json_path.name}")

        results_all[folder_name] = summary_clean

    print("\n" + "=" * 70)
    print("PROCESAMIENTO DE TODOS LOS LEVANTAMIENTOS KM* COMPLETADO CON ÉXITO")
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/surveys")
    args = parser.parse_args()
    process_all_km_surveys(args.base, args.output)
