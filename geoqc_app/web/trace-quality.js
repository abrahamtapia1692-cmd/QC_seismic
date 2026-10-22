// Present native trace-QC values; display reductions never feed scientific calculations.
const NS = "http://www.w3.org/2000/svg";
const colors = {BUENA: "#16803c", REGULAR: "#b77900", MALA: "#dc2626", NO_EVALUABLE: "#64748b"};
const names = {BUENA: "Buena", REGULAR: "Revisión", MALA: "Mala", NO_EVALUABLE: "No evaluable"};
const finite = (x) => typeof x === "number" && Number.isFinite(x);
const fmt = (x) => finite(x) ? new Intl.NumberFormat("es", {maximumSignificantDigits: 5,
  notation: x !== 0 && Math.abs(x) < 0.001 ? "scientific" : "standard"}).format(x) : "—";
function el(tag, text, cls) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (cls) n.className = cls;
  return n;
}
function s(tag, attrs = {}, text) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text !== undefined) n.textContent = text;
  return n;
}
function graph(title, height) {
  const n = s("svg", {viewBox: `0 0 800 ${height}`, role: "img", "aria-label": title});
  n.append(s("title", {}, title)); return n;
}
function table(headers, rows, cls = "") {
  const wrapper = el("div", undefined, "trs-table-scroll " + cls), t = el("table", undefined, "trs-table");
  const head = el("thead"), tr = el("tr");
  for (const h of headers) tr.append(el("th", h));
  head.append(tr); t.append(head);
  const body = el("tbody");
  for (const row of rows) { const r = el("tr"); for (const v of row) r.append(el("td", String(v ?? "—"))); body.append(r); }
  t.append(body); wrapper.append(t); return wrapper;
}
function panel(title, cls = "") { const box = el("div", undefined, "trs-panel " + cls); box.append(el("h3", title)); return box; }
function countsOf(qc) {
  if (qc.operational_assessment) return qc.operational_assessment.counts;
  return {...Object.fromEntries(Object.keys(names).map((grade) =>
    [grade, (qc.traces || []).filter((t) => t.quality.assessment_grade === grade).length])), ...qc.assessment_counts};
}
export function renderQualityOverview(records) {
  const box = panel("Resumen de calidad por registro y tendido", "qc-overview");
  box.append(el("p", "Verde: buena · Amarillo: revisión · Rojo: mala · Gris: no evaluable. Calificación diagnóstica con política DRAFT.", "hint"));
  const rows = records.map((r) => {
    const q = r.trace_qc, a = q?.operational_assessment || q?.data_assessment;
    if (!a) return [r.shot_id, "Sin QC", "—", "—", "—", "—", "Requiere otra ejecución"];
    const c = countsOf(q);
    return [r.shot_id, c.BUENA, c.REGULAR, c.MALA, c.NO_EVALUABLE,
      a.good_percent_bounds.map(fmt).join("–") + " %", names[a.grade] || a.grade];
  });
  box.append(table(["Registro / tendido", "Buenas", "Revisión", "Malas", "No evaluables", "Intervalo de buenas", "Evaluación"], rows));
  if (records.some((r) => r.trace_qc?.operational_assessment)) box.append(el("p", "Calificación diagnóstica condicional por muestras. Las buenas cumplen el escenario declarado; no implican metadatos completos ni aceptación de campo. La evaluación estricta se conserva por separado.", "notice"));
  const svg = graph("Distribución de calidad por registro", 55 + records.length * 55);
  records.forEach((r, i) => {
    const qc = r.trace_qc, total = qc?.data_assessment?.total_traces;
    const label = r.shot_id.length > 23 ? r.shot_id.slice(0, 21) + "…" : r.shot_id;
    const text = s("text", {x: 5, y: 27 + i * 55}, label); text.append(s("title", {}, r.shot_id)); svg.append(text);
    if (!total) return;
    let left = 210;
    for (const [state, count] of Object.entries(countsOf(qc))) {
      if (!count) continue;
      const width = count / total * 560, rect = s("rect", {x: left, y: 10 + i * 55, width, height: 28, fill: colors[state]});
      rect.append(s("title", {}, `${names[state]}: ${count} de ${total}`)); svg.append(rect);
      if (width > 24) svg.append(s("text", {x: left + width / 2, y: 29 + i * 55, fill: "white", "text-anchor": "middle"}, count));
      left += width;
    }
  });
  box.append(svg, el("p", "Porcentaje bueno = 100 × trazas buenas / total de trazas. Buena: ≥90 %; regular: ≥75 % y <90 %; mala: <75 %. El conjunto suma trazas de todos sus registros. Las pendientes permanecen en el denominador; si los extremos del intervalo cambian de categoría, el resultado es no evaluable.", "hint"));
  return box;
}
function operationalPanel(summary, traces) {
  const a = summary.operational_assessment, p = summary.request.operational_policy;
  const box = panel("Calificación diagnóstica por traza y tendido", "qc-operational");
  box.append(el("p", `Tendido: ${names[a.grade] || a.grade} · buenas ${a.good_percent_bounds.map(fmt).join("–")} % · cobertura media de comprobaciones ${fmt(a.mean_coverage_fraction * 100)} %.`, "qc-assessment"),
    el("p", `Política ${p.id}. Cobertura mínima ${fmt(p.minimum_coverage * 100)} % de cuatro dominios; integridad, morfología y contraste son necesarios para declarar buena. La cobertura indica disponibilidad de comprobaciones, no probabilidad de acierto.`, "hint"),
    el("p", "El contraste se estima sobre todos los bloques de la referencia declarada. Su intervalo expresa sensibilidad al ruido, no confianza estadística. La similitud estimada no verifica instrumento ni ganancia. Las mesetas son sospechas morfológicas; no se deducen límites ADC.", "hint"));
  box.append(table(["Criterio operativo", "Regla del escenario"], [
    ["Contraste condicional", `Buena si todo el intervalo alcanza ${fmt(p.contrast_good_db)} dB y la referencia es estable; menor soporte produce revisión, no una falla física demostrada.`],
    ["Estabilidad de referencia", `Razón máxima/mínima de potencia de ${p.reference_blocks} bloques ≤${fmt(p.max_reference_power_ratio)}.`],
    ["Mesetas digitales", `≥${p.plateau_min_run} muestras idénticas consecutivas en extremos observados: revisar.`],
    ["Similitud de forma", "Escenario con consenso entre vecinos y desfase limitado. Sin consenso, la medida es informativa y este dominio queda sin cobertura; no penaliza por sí solo la traza."],
    ["Líneas candidatas", `Revisión si persisten con prominencia ≥${fmt(p.line_prominence_db)} dB en ≥${fmt(100 * p.line_persistence_min_fraction)} % de los bloques, con soporte en todos.`],
    ["Falla demostrada", "Canal muerto/constante, falta de soporte o falla del QC estricto prevalecen."],
    ["Solo metadatos instrumentales ausentes", "Se mantienen como pendientes; no bloquean por sí solos esta calificación condicional."],
  ]));
  const grid = el("div", undefined, "qc-chart-grid");
  grid.append(metricPlot("Contraste estimado: sensibilidad a bloques", traces, [
    {name: "Límite inferior (azul)", color: "#2563eb", value: (t) => t.operational_quality.estimated_contrast.db_bounds?.[0]},
    {name: "Límite superior (naranja)", color: "#d97706", value: (t) => t.operational_quality.estimated_contrast.db_bounds?.[1]}], "dB", [{value:p.contrast_good_db,color:colors.BUENA}]),
    metricPlot("Similitud estimada y consenso", traces, [
      {name: "|ρ| estimada", color: "#236763", value: (t) => t.operational_quality.estimated_similarity.median_abs_rho},
      {name: "Consenso de vecinos", color: "#b77900", value: (t) => t.operational_quality.estimated_similarity.neighbor_consensus_rho}], "|ρ|"),
    metricPlot("Cobertura de comprobaciones por traza", traces, [{name: "Cobertura; no es confianza", color: "#236763", value: (t) => 100 * t.operational_quality.coverage_fraction}], "%", [{value:100,color:"#64748b"}, {value:100*p.minimum_coverage,color:colors.REGULAR}]));
  const grades = table(["Canal", "Calificación diagnóstica", "Cobertura", "Contraste (dB)", "Meseta candidata", "Motivos"], traces.map((t) => {
    const o = t.operational_quality;
    return [t.receiver_id, names[o.grade], `${fmt(100 * o.coverage_fraction)} %`, o.estimated_contrast.db_bounds?.map(fmt).join("–") || o.estimated_contrast.state,
      o.morphology.state === "MISSING" ? "Sin soporte" : o.morphology.candidate ? "Sí; revisar" : "No detectada", o.reasons.join("; ")];
  }));
  [...grades.querySelectorAll("tbody tr")].forEach((row, i) => {
    row.cells[1].style.color = colors[traces[i].operational_quality.grade];
    row.cells[1].style.fontWeight = "600";
    row.cells[0].style.borderLeft = `4px solid ${colors[traces[i].operational_quality.grade]}`;
  });
  box.querySelector(".qc-assessment").style.borderLeft = `4px solid ${colors[a.grade]}`;
  box.append(grid, grades, el("p", `Evaluación estricta conservada: ${names[summary.data_assessment.grade]}. Los faltantes de escala, clipping físico, independencia y calibración siguen visibles. Suficiencia NOT_DEMONSTRATED; sin aceptación automática.`, "hint"));
  return box;
}
function criteria(summary) {
  const box = panel("Criterios de evaluación y umbrales aplicados", "qc-criteria");
  const p = summary.request.protocol, q = p.quality_policy, sim = p.similarity;
  box.append(el("p", `Política ${q.id}. Límites locales provisionales; se muestra el protocolo congelado de esta ejecución.`));
  box.append(table(["Evidencia", "Buena", "Revisión", "Mala / falla demostrada"], [
    ["Integridad", "Todas las muestras válidas", "Huecos parciales", "Sin soporte válido suficiente"],
    ["Señal", "Variable", "Anomalía con modelo de amplitud declarado", "Canal muerto o constante"],
    ["SNR neta válida", `≥${fmt(q.snr_good_min_db)} dB`, `≥${fmt(q.snr_bad_below_db)} y <${fmt(q.snr_good_min_db)} dB`, `<${fmt(q.snr_bad_below_db)} dB o potencia neta no resuelta con ruido verificado`],
    ["Clipping confirmado", `≤${fmt(q.clip_good_max_fraction * 100)} %`, `>${fmt(q.clip_good_max_fraction * 100)} y <${fmt(q.clip_bad_min_fraction * 100)} %`, `≥${fmt(q.clip_bad_min_fraction * 100)} %`],
    ["Evidencia", "Comprobaciones requeridas completas", "Alertas observadas con motivo", "Una falla demostrada prevalece sobre los faltantes"],
  ], "qc-criteria-table"));
  box.append(el("p", "La peor condición demostrada determina la calificación por traza. Cuando solo falta evidencia, se muestra no evaluable. SNR exige ruido independiente y estacionariedad verificada; clipping exige rails y escala conocidos. Una SNR condicional alta no demuestra una traza buena. Una abstención del picker no demuestra una traza mala.", "hint"));
  if (sim) box.append(el("p", `Similitud local: revisión por |ρ| < ${fmt(sim.warn_below_rho)}; anomalía fuerte por mediana < ${fmt(sim.bad_below_rho)} y al menos ${fmt(100 * sim.bad_neighbor_fraction_min)} % de pares bajo ese límite, con consenso entre vecinos ≥${fmt(sim.neighbor_consensus_min)} y mínimo ${sim.min_neighbors} vecinos. Radio ${fmt(sim.neighbor_radius_m)} m; tope de desfase ${fmt(sim.max_lag_s * 1000)} ms. Comparabilidad instrumental: ${sim.comparable_channels ? "declarada" : "sin verificar; evaluación ausente"}.`));
  const window = (v) => v ? `[${fmt(v.start_s)}, ${fmt(v.end_s)}) s` : "No declarada";
  box.append(table(["Ventana / condición", "Declaración de esta ejecución"], [
    ["Análisis", window(p.analysis)], ["Señal", window(p.signal)], ["Ruido de referencia", window(p.noise)],
    ["Tipo de referencia", summary.request.noise?.reference_kind || "Sin diagnóstico de ruido solicitado"],
    ["Ruido independiente", p.noise_independent ? "Declarado" : "Sin verificar"],
    ["Estacionariedad para SNR", p.noise_stationarity],
    ["Rails / escala", finite(p.rail_scale_to_data) ? fmt(p.rail_scale_to_data) : "Sin escala verificada"],
  ]));
  if (summary.request.noise) {
    const n = summary.request.noise;
    box.append(el("p", `Ruido LF solicitado: ${n.low_band_hz.map(fmt).join("–")} Hz, mínimo ${fmt(n.minimum_cycles)} ciclos. Estacionariedad interna: ${n.noise_blocks} bloques, alerta de razón de potencias >${fmt(n.block_power_ratio_warn)}. Líneas candidatas: prominencia ${fmt(n.line_prominence_db)} dB. La banda parcial y los candidatos conservan sus límites de soporte.`, "hint"));
  }
  return box;
}
function metricPlot(title, traces, series, unit, thresholds = []) {
  const box = el("div", undefined, "qc-chart"), svg = graph(title, 245);
  box.append(el("h4", title));
  const values = series.flatMap((line) => traces.flatMap((t) => { const v = line.value(t); return finite(v) ? [v] : []; }));
  if (!values.length) { box.append(el("p", "Sin valores evaluables con este protocolo; no se representan como cero.", "hint")); return box; }
  const low = Math.min(0, ...values), high = Math.max(low + 1e-12, ...values, ...thresholds.map((t) => t.value));
  const x = (i) => 82 + i / Math.max(1, traces.length - 1) * 670;
  const y = (v) => 188 - (v - low) / (high - low || 1) * 150;
  for (let i = 0; i <= 4; i++) {
    const v = low + (high - low) * i / 4;
    svg.append(s("line", {x1: 82, x2: 752, y1: y(v), y2: y(v), stroke: "#dfe8e5"}),
      s("text", {x: 74, y: y(v) + 4, "text-anchor": "end"}, fmt(v)));
  }
  for (const mark of thresholds) svg.append(s("line", {x1: 82, x2: 752, y1: y(mark.value), y2: y(mark.value), stroke: mark.color, "stroke-dasharray": "5 4"}));
  traces.forEach((trace, i) => {
    if (i === 0 || i === traces.length - 1 || (i + 1) % 4 === 0) svg.append(s("text", {x: x(i), y: 208, "text-anchor": "middle"}, trace.channel_1based ?? i + 1));
    for (const line of series) {
      const v = line.value(trace); if (!finite(v)) continue;
      const point = s("circle", {cx: x(i), cy: y(v), r: 4, fill: line.color || colors[trace.quality.assessment_grade]});
      point.append(s("title", {}, `${trace.receiver_id} · ${line.name}: ${fmt(v)} ${unit}`)); svg.append(point);
    }
  });
  svg.append(s("text", {x: 416, y: 235, "text-anchor": "middle"}, `Canal · ${unit}`));
  box.append(svg, el("p", series.map((l) => l.name).join(" · "), "hint")); return box;
}
function diagnostics(summary, traces) {
  const box = panel("Diagnóstico gráfico de calidad y ruido", "qc-diagnostics"), grid = el("div", undefined, "qc-chart-grid");
  const policy = summary.request.protocol.quality_policy;
  const thresholds = [{value: policy.snr_bad_below_db, color: colors.MALA}, {value: policy.snr_good_min_db, color: colors.BUENA}];
  grid.append(metricPlot("SNR neta válida por canal", traces, [{name: "SNR válida", value: (t) => t.snr.state === "VALID" ? t.snr.value : null}], "dB", thresholds),
    metricPlot("SNR condicional de ventana", traces, [{name: "Condicional; no valida el primer arribo", value: (t) => t.noise_diagnostics?.snr.value}], "dB"),
    metricPlot("Clipping confirmado", traces, [{name: "Clipping con rails y escala", value: (t) => t.clip.state === "VALID" && finite(t.clip.value) ? 100 * t.clip.value : null}], "%"),
    metricPlot("Similitud local y consenso", traces, [{name: "|ρ| mediana", color: "#236763", value: (t) => t.similarity?.median_abs_rho}, {name: "Consenso de vecinos", color: "#b77900", value: (t) => t.similarity?.neighbor_consensus_rho}], "|ρ|"),
    metricPlot("Escalas de ruido: RMS AC y MAD", traces, [{name: "RMS AC (azul)", color: "#2563eb", value: (t) => t.noise_diagnostics?.noise_rms_ac}, {name: "MAD gaussiana (naranja)", color: "#d97706", value: (t) => t.noise_diagnostics?.noise_sigma_mad}], traces[0]?.amplitude_unit || "unidad nativa"),
    metricPlot("Ruido LF / potencia total de señal", traces, [{name: "Razón de potencias; banda soportada parcial", value: (t) => t.noise_diagnostics?.low_frequency?.noise_power_to_signal_total_power}], "razón"),
    metricPlot("Potencias por bloques de referencia", traces, Array.from({length: summary.request.noise?.noise_blocks || 0}, (_, i) => ({name: `Bloque ${i + 1}`, color: ["#236763", "#2563eb", "#d97706", "#9333ea"][i % 4], value: (t) => t.noise_diagnostics?.stationarity?.block_powers?.[i]})), `${traces[0]?.amplitude_unit || "unidad"}²`));
  box.append(grid);
  const lines = traces.flatMap((t) => (t.noise_diagnostics?.lines || []).map((l) => [t.receiver_id, fmt(l.estimated_hz), fmt(l.nominal_hz), fmt(l.prominence_db), fmt(l.bin_width_hz), l.state]));
  box.append(el("h4", "Líneas espectrales candidatas"), lines.length ? table(["Canal", "Estimada (Hz)", "Nominal (Hz)", "Prominencia (dB)", "Bin (Hz)", "Estado"], lines) : el("p", "Sin líneas candidatas informadas; consultar el estado de búsqueda de cada canal.", "hint"));
  box.append(el("p", "Los candidatos no identifican la causa ni autorizan un notch automático. Las gráficas muestran resultados nativos; valores ausentes conservan su estado. RMS y MAD son escalas distintas.", "hint"));
  return box;
}
function coverage(summary, traces) {
  const box = panel("Evidencia pendiente y acciones de revisión", "qc-actions");
  const reasons = new Map();
  for (const t of traces) for (const reason of new Set(t.quality.missing_evidence)) reasons.set(reason, (reasons.get(reason) || 0) + 1);
  box.append(table(["Evidencia pendiente", "Canales afectados"], [...reasons].map(([r, n]) => [r, n])));
  const list = el("ul");
  const actions = new Set(traces.flatMap((t) => [...(t.noise_diagnostics?.actions || []), ...(t.similarity?.actions || [])]));
  if (traces.some((t) => t.snr.state !== "VALID")) actions.add("Documentar ventanas de señal y ruido independiente, y verificar la transferencia estacionaria antes de usar SNR para calificar.");
  if (traces.some((t) => t.clip.state !== "VALID")) actions.add("Documentar rails ADC, escala de amplitud y convención de apilamiento para evaluar clipping.");
  for (const action of actions) list.append(el("li", action));
  box.append(list, el("h4", "Cobertura del abordaje"));
  const labels = {integrity: "Integridad digital", snr_clipping: "SNR y clipping", noise: "Ruido y espectros", similarity: "Similitud local", filtering: "Filtrado candidato", repeatability: "Repetibilidad", reciprocity: "Reciprocidad"};
  const meanings = {EXECUTED: "Ejecutado", EXECUTED_WITH_APPLICABILITY_GUARDS: "Ejecutado; cada métrica conserva su aplicabilidad", EXECUTED_CONDITIONAL: "Ejecutado bajo referencia condicional", NOT_REQUESTED: "No solicitado", NOT_APPLIED_RAW_PRESERVED: "Sin aplicar; muestras RAW conservadas", NOT_REQUESTED_REQUIRES_SOURCE_GROUPS: "Pendiente: requiere grupos de impactos de la misma fuente", NOT_REQUESTED_REQUIRES_PHYSICAL_PAIRS: "Pendiente: requiere pares físicos de fuentes y receptores"};
  box.append(table(["Etapa", "Estado y alcance"], Object.entries(summary.methodology).map(([k, v]) => [labels[k] || k, meanings[v] || v])));
  box.append(el("p", "Las acciones orientan la revisión; no cambian la calificación ni representan verificaciones ya realizadas. Suficiencia: NOT_DEMONSTRATED. Aceptación de campo: no certificada.", "hint"));
  return box;
}
function waveform(traces, picks, selected, select, timeWindow) {
  const height = 70 + traces.length * 24;
  const svg = graph("Formas de onda por canal, amplitudes normalizadas solo para visualizar", height);
  const start = timeWindow ? timeWindow[0] : Math.min(...traces.map((t) => t.waveform_preview.t0_s));
  const end = timeWindow ? timeWindow[1] : Math.max(...traces.map((t) => t.waveform_preview.t0_s + t.waveform_preview.sample_count * t.waveform_preview.dt_s));
  const x = (v) => 65 + (v - start) / (end - start) * 715;
  for (let i = 0; i <= 4; i++) {
    const time = start + (end - start) * i / 4;
    svg.append(s("line", {x1: x(time), x2: x(time), y1: 15, y2: height - 42, stroke: "#dfe8e5"}),
      s("text", {x: x(time), y: height - 22, "text-anchor": "middle"}, fmt(time * 1000)));
  }
  svg.append(s("text", {x: 430, y: height - 3, "text-anchor": "middle"}, "Tiempo registrado (ms) · envolvente min/max"));
  for (const [i, trace] of traces.entries()) {
    const w = trace.waveform_preview, points = w.points;
    const values = points.map((p) => p[1]).filter(finite);
    const center = finite(trace.statistics.dc) ? trace.statistics.dc : 0;
    const amplitude = Math.max(0, ...values.map((v) => Math.abs(v - center))) || 1;
    const base = 25 + i * 24;
    let drawing = "", connected = false;
    for (const [index, value] of points) {
      const time = w.t0_s + index * w.dt_s;
      if (!finite(value) || time < start || time >= end) { connected = false; continue; }
      drawing += `${connected ? "L" : "M"}${x(w.t0_s + index * w.dt_s).toFixed(2)},${(base - (value - center) / amplitude * 10).toFixed(2)}`;
      connected = true;
    }
    const label = s("text", {x: 6, y: base + 4, tabindex: 0, role: "button", class: "qc-channel",
      "aria-label": `Examinar ${trace.receiver_id}`}, trace.receiver_id);
    label.onclick = () => select(trace.receiver_id);
    label.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(trace.receiver_id); } };
    const path = s("path", {d: drawing, fill: "none", stroke: trace.receiver_id === selected ? "#173e43" : colors[trace.quality.assessment_grade] || "#64748b", "stroke-width": trace.receiver_id === selected ? 1.8 : 1});
    svg.append(label, path);
    const pick = picks.find((p) => p.receiver_id === trace.receiver_id);
    if (finite(pick?.arrival.onset_s) && pick.arrival.onset_s >= start && pick.arrival.onset_s < end) {
      const onset = x(pick.arrival.onset_s);
      const marker = s("line", {x1: onset, x2: onset, y1: base - 10, y2: base + 10, stroke: "#bc623a", "stroke-width": 2});
      marker.append(s("title", {}, `Onset ${fmt(pick.arrival.onset_s * 1000)} ms · ${pick.arrival.confidence}`)); svg.append(marker);
    }
  }
  return svg;
}
function spectrum(trace) {
  const box = el("div", undefined, "qc-spectrum");
  box.append(el("h4", "Espectro de la referencia de ruido"));
  const preview = trace.noise_diagnostics?.spectrum_preview;
  if (!preview) { box.append(el("p", "Sin espectro de referencia solicitado o con soporte insuficiente.")); return box; }
  const positive = preview.noise_psd_native_units.filter((p) => finite(p) && p > 0);
  if (!positive.length) { box.append(el("p", "Potencia no resuelta; no se representa como un nivel dB finito.")); return box; }
  const low = Math.min(...positive.map((p) => 10 * Math.log10(p))), high = Math.max(low + 1, ...positive.map((p) => 10 * Math.log10(p)));
  const maxF = Math.max(...preview.frequency_hz);
  const svg = graph("PSD nativa de la referencia: escala logarítmica, sin calibración adicional", 240);
  let drawing = "", connected = false;
  for (const [i, f] of preview.frequency_hz.entries()) {
    const power = preview.noise_psd_native_units[i];
    if (!(power > 0)) { connected = false; continue; }
    const x = 70 + f / maxF * 700, y = 180 - (10 * Math.log10(power) - low) / (high - low) * 160;
    drawing += `${connected ? "L" : "M"}${x.toFixed(2)},${y.toFixed(2)}`; connected = true;
  }
  for (let i = 0; i <= 4; i++) {
    const y = 180 - i * 40;
    svg.append(s("line", {x1: 70, x2: 770, y1: y, y2: y, stroke: "#dfe8e5"}),
      s("text", {x: 60, y: y + 4, "text-anchor": "end"}, fmt(low + (high - low) * i / 4)),
      s("text", {x: 70 + i * 175, y: 203, "text-anchor": "middle"}, fmt(maxF * i / 4)));
  }
  svg.append(s("path", {d: drawing, fill: "none", stroke: "#236763", "stroke-width": 1.5}),
    s("text", {x: 420, y: 231, "text-anchor": "middle"}, "Frecuencia (Hz)"));
  box.append(svg, el("p", `10 log10(PSD / 1 ${trace.amplitude_unit}²/Hz), según unidad declarada. Máximo por grupo para visualizar; espectro completo en el JSON científico.`, "hint"));
  return box;
}
export function renderTraceQuality(summary, traces, picks) {
  const root = el("div", undefined, "trs-panel qc-dashboard");
  if (summary.operational_assessment) root.append(operationalPanel(summary, traces));
  const assessment = summary.data_assessment;
  root.append(el("h3", summary.operational_assessment ? "Evaluación estricta y diagnósticos nativos" : "Dosier de calidad por traza y tendido"));
  root.append(el("p", `${names[assessment.grade] || assessment.grade} · ${assessment.total_traces} trazas · ${assessment.demonstrated_bad_traces} fallas demostradas · ${assessment.pending_traces} con evidencia pendiente.`, "qc-assessment"));
  const bounds = assessment.good_percent_bounds;
  root.append(el("p", `Trazas buenas: intervalo posible ${fmt(bounds[0])}–${fmt(bounds[1])} %. Cortes del registro: 90 % y 75 %. Las abstenciones del picker no califican la adquisición.`, "hint"));
  root.append(el("p", summary.protocol_source === "DECLARED" ? "Protocolo QC declarado; consulta su procedencia y límites de aplicabilidad." : "Protocolo de integridad del registro completo. No se han supuesto ventanas independientes de ruido ni comparabilidad entre canales.", "hint"));
  const counts = el("div", undefined, "trs-counts qc-counts");
  for (const state of Object.keys(names)) {
    const count = traces.filter((trace) => trace.quality.assessment_grade === state).length;
    const chip = el("span", `${count} ${names[state]}`, "trs-chip"); chip.style.borderColor = colors[state]; counts.append(chip);
  }
  root.append(counts);
  root.append(criteria(summary), diagnostics(summary, traces));
  const traceTable = el("table", undefined, "trs-table qc-table");
  const head = el("thead"), header = el("tr");
  for (const text of ["Canal", "Integridad", "SNR válida (dB)", "SNR condicional (dB)", "Clipping (%)", "Similitud |ρ|", "Consenso vecinos", "Evaluación", "Motivos / acciones"]) header.append(el("th", text));
  head.append(header); traceTable.append(head); const tbody = el("tbody"); traceTable.append(tbody);
  const selectorLabel = el("label", "Examinar canal"), selector = el("select");
  selector.setAttribute("aria-label", "Canal QC");
  for (const trace of traces) { const option = el("option", trace.receiver_id); option.value = trace.receiver_id; selector.append(option); }
  selectorLabel.append(selector);
  const windowLabel = el("label", "Ventana de visualización"), windowSelector = el("select");
  windowSelector.setAttribute("aria-label", "Ventana de visualización QC");
  const whole = el("option", "Registro completo"); whole.value = "full"; windowSelector.append(whole);
  const search = picks[0]?.arrival.window_s;
  if (search?.length === 2 && search.every(finite) && search[1] > search[0]) {
    const option = el("option", `Ventana del picker (${fmt(search[0] * 1000)}–${fmt(search[1] * 1000)} ms)`);
    option.value = "search"; windowSelector.append(option);
  }
  windowLabel.append(windowSelector);
  const gather = el("div", undefined, "qc-gather"), inspected = el("div", undefined, "qc-inspected");
  const gradeLabel = el("label", "Mostrar canales por calidad"), gradeFilter = el("select");
  gradeFilter.setAttribute("aria-label", "Filtrar canales por calidad");
  const all = el("option", "Todos los canales"); all.value = ""; gradeFilter.append(all);
  for (const [grade, name] of Object.entries(names)) { const o = el("option", name); o.value = grade; gradeFilter.append(o); }
  gradeLabel.append(gradeFilter);
  gradeFilter.onchange = () => { for (const row of tbody.rows) row.hidden = !!gradeFilter.value && row.dataset.grade !== gradeFilter.value; };
  function select(id) { selector.value = id; update(); }
  function update() {
    const trace = traces.find((t) => t.receiver_id === selector.value);
    if (!trace) return;
    gather.replaceChildren(waveform(traces, picks, trace.receiver_id, select, windowSelector.value === "search" ? search : null));
    inspected.replaceChildren(el("h4", `${trace.receiver_id} · ${names[trace.quality.assessment_grade] || trace.quality.assessment_grade}`));
    const reasons = el("ul"); for (const reason of trace.quality.reasons) reasons.append(el("li", reason)); inspected.append(reasons);
    inspected.append(el("p", `SNR: ${trace.snr.state} · ${trace.snr.reason}. Clipping: ${trace.clip.state} · ${trace.clip.reason}.`));
    inspected.append(el("p", `Muestras válidas: ${trace.statistics.valid_samples ?? "—"}. DC: ${fmt(trace.statistics.dc)} ${trace.amplitude_unit}; RMS AC: ${fmt(trace.statistics.rms_ac)} ${trace.amplitude_unit}.`));
    if (trace.similarity) inspected.append(el("p", `Similitud: ${trace.similarity.state} · ${trace.similarity.reasons.join("; ")}`));
    const similar = trace.similarity;
    if (similar) inspected.append(table(["Métrica local", "Valor"], [["|ρ| mediana", fmt(similar.median_abs_rho)], ["Consenso entre vecinos", fmt(similar.neighbor_consensus_rho)], ["Frecuencia mediana (Hz)", fmt(similar.spectral_median_hz)], ["Línea base / llegada RMS", fmt(similar.baseline_to_arrival_rms)], ["Línea base relativa a vecinos", fmt(similar.baseline_relative_to_neighbors)]]));
    const noise = trace.noise_diagnostics;
    if (noise) {
      inspected.append(el("p", `Ruido: ${noise.state}. La SNR de ventana es condicional y no valida la llegada.`));
      inspected.append(el("p", `RMS AC del ruido: ${fmt(noise.noise_rms_ac)} ${trace.amplitude_unit}; escala MAD: ${fmt(noise.noise_sigma_mad)} ${trace.amplitude_unit}.`));
      if (noise.stationarity) inspected.append(el("p", `Potencias por bloques: ${noise.stationarity.block_powers.map(fmt).join(" · ")}. Razón máximo/mínimo: ${fmt(noise.stationarity.max_min_power_ratio)}. Transferencia a señal sin verificar.`));
      if (noise.low_frequency) inspected.append(el("p", `Baja frecuencia: ${noise.low_frequency.state} · banda soportada ${noise.low_frequency.supported_band_hz?.map(fmt).join("–") || "sin soporte"} Hz · potencia LF / potencia total de señal: ${fmt(noise.low_frequency.noise_power_to_signal_total_power)}.`));
      inspected.append(el("p", `Líneas espectrales candidatas: ${noise.lines?.map((l) => `${fmt(l.estimated_hz)} Hz`).join("; ") || "ninguna informada"}.`));
    }
    const coherence = summary.noise_coherence?.find((pair) => pair.receiver_ids.includes(trace.receiver_id));
    if (coherence) inspected.append(el("p", `Coherencia LF con ${coherence.receiver_ids.join(" / ")}: ${coherence.state} · ${coherence.reason || ""}${finite(coherence.required_duration_s) ? ` · duración requerida: ${fmt(coherence.required_duration_s)} s` : ""}.`));
    inspected.append(spectrum(trace));
    const nearby = traces.filter((t) => Math.abs(traces.indexOf(t) - traces.indexOf(trace)) <= 2);
    inspected.append(el("h4", "Comparación de formas de onda con canales contiguos"),
      el("p", "Comparación visual en tiempo registrado, sin alinear ni corregir polaridad. La proximidad de canal no verifica comparabilidad instrumental ni consenso.", "hint"),
      waveform(nearby, picks, trace.receiver_id, select, windowSelector.value === "search" ? search : null));
    for (const row of tbody.rows) row.classList.toggle("selected", row.dataset.receiver === trace.receiver_id);
  }
  for (const trace of traces) {
    const row = el("tr"); row.dataset.receiver = trace.receiver_id; row.dataset.grade = trace.quality.assessment_grade;
    const first = el("td"), button = el("button", trace.receiver_id, "trs-row-button"); button.type = "button"; button.onclick = () => select(trace.receiver_id); first.append(button); row.append(first);
    const snr = trace.snr.state === "VALID" ? trace.snr.value : null;
    const clip = trace.clip.state === "VALID" && finite(trace.clip.value) ? trace.clip.value * 100 : null;
    for (const value of [`${fmt(trace.valid_fraction * 100)} %`, fmt(snr), fmt(trace.noise_diagnostics?.snr.value), fmt(clip), fmt(trace.similarity?.median_abs_rho), fmt(trace.similarity?.neighbor_consensus_rho), names[trace.quality.assessment_grade] || trace.quality.assessment_grade,
      [...trace.quality.reasons, ...(trace.noise_diagnostics?.actions || []), ...(trace.similarity?.actions || [])].join("; ")]) row.append(el("td", value));
    row.cells[row.cells.length - 2].style.color = colors[trace.quality.assessment_grade];
    tbody.append(row);
  }
  const wrapper = el("div", undefined, "trs-table-scroll"); wrapper.append(traceTable);
  root.append(el("h3", "Formas de onda y diagnóstico por canal"), selectorLabel, windowLabel, gather, el("p", "Envolvente min/max de muestras originales; cada canal se centra y normaliza solo en pantalla. Naranja: onset del picker. Esta reducción visual no mide amplitudes, no modifica muestras ni recalcula picks.", "hint"), gradeLabel, wrapper, inspected, coverage(summary, traces));
  const methods = el("details"), title = el("summary", "Cobertura metodológica y protocolo QC"); methods.append(title);
  const pre = el("pre", JSON.stringify({methodology: summary.methodology, request: summary.request, noise_coherence: summary.noise_coherence}, null, 2)); methods.append(pre); root.append(methods);
  selector.onchange = windowSelector.onchange = update; update(); return root;
}
