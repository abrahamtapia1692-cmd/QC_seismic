// Read-only presentation of frozen TRS results. No fitting or picking in the browser.
import {renderQualityOverview, renderTraceQuality} from "./trace-quality.js";
const NS = "http://www.w3.org/2000/svg";
const states = {
  UNCALIBRATED: ["Sin calibrar", "#8a6219"],
  AMBIGUOUS: ["Ambiguo", "#8f4a7a"],
  MISSING: ["Sin llegada", "#66777f"],
  HIGH: ["HIGH", "#236763"],
  MEDIUM: ["MEDIUM", "#386e9d"],
  LOW: ["LOW", "#9d571c"],
};
const finite = (x) => typeof x === "number" && Number.isFinite(x);
const fmt = (x) => finite(x) ? new Intl.NumberFormat("es", {maximumFractionDigits: 3}).format(x) : "—";
function node(tag, text, cls) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (cls) el.className = cls;
  return el;
}
function svgNode(tag, attrs = {}, text) {
  const el = document.createElementNS(NS, tag);
  for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value);
  if (text !== undefined) el.textContent = text;
  return el;
}
function graphic(title, height = 300) {
  const svg = svgNode("svg", {viewBox: `0 0 800 ${height}`, role: "img", "aria-label": title});
  svg.append(svgNode("title", {}, title));
  return svg;
}
function domain(values) {
  const valid = values.filter(finite);
  const low = Math.min(0, ...valid), high = Math.max(1, ...valid);
  return [low, high];
}
function scale(value, min, max, start, end) {
  return start + (value - min) / (max - min) * (end - start);
}
function geometry(record) {
  const box = node("div", undefined, "trs-panel");
  box.append(node("h3", "Disposición de fuente y receptores"));
  const g = record.geometry;
  const svg = graphic("Geometría declarada: proyección sobre el eje X, en metros", 150);
  const [min, max] = domain([g.xs, ...g.xr]);
  const x = (v) => scale(v, min, max, 45, 755);
  svg.append(svgNode("line", {x1: 45, y1: 75, x2: 755, y2: 75, stroke: "#bdcfca"}));
  if (finite(g.xs)) {
    const marker = svgNode("path", {d: `M ${x(g.xs)} 60 l 9 15 l -9 15 l -9 -15 Z`, fill: "#bc623a"});
    marker.append(svgNode("title", {}, `Fuente: X ${fmt(g.xs)} m; Y ${fmt(g.ys)} m; Z ${fmt(g.zs)} m`));
    svg.append(marker, svgNode("text", {x: x(g.xs), y: 40, "text-anchor": "middle"}, "Fuente"));
  }
  for (const [i, value] of g.xr.entries()) {
    if (!finite(value)) continue;
    const marker = svgNode("circle", {cx: x(value), cy: 75, r: 4, fill: "#236763"});
    marker.append(svgNode("title", {}, `${record.acquisition.receiver_ids[i]}: X ${fmt(value)} m; Y ${fmt(g.yr[i])} m; Z ${fmt(g.zr[i])} m`));
    svg.append(marker);
    if (i === 0 || i === g.xr.length - 1 || i % Math.max(1, Math.ceil(g.xr.length / 8)) === 0) {
      svg.append(svgNode("text", {x: x(value), y: 105, "text-anchor": "middle"}, `${i + 1}`));
    }
  }
  svg.append(svgNode("text", {x: 400, y: 137, "text-anchor": "middle"}, `X: ${fmt(min)} a ${fmt(max)} m · números de receptor`));
  box.append(svg, node("p", "Proyección X de la geometría declarada; consulta la procedencia para distinguir posiciones medidas y supuestas.", "hint"));
  return box;
}
function arrivalsPlot(picks, select) {
  const svg = graphic("Primeros arribos: tiempo registrado en milisegundos frente a offset en metros", 360);
  const usable = picks.filter((p) => finite(p.offset_m) && finite(p.arrival.onset_s));
  const [xmin, xmax] = domain(picks.map((p) => p.offset_m));
  const [ymin, ymax] = domain(usable.map((p) => p.arrival.onset_s * 1000));
  const x = (v) => scale(v, xmin, xmax, 68, 770);
  const y = (v) => scale(v, ymin, ymax * 1.1, 290, 25);
  for (let i = 0; i <= 5; i++) {
    const tx = xmin + (xmax - xmin) * i / 5, ty = ymin + (ymax * 1.1 - ymin) * i / 5;
    svg.append(svgNode("line", {x1: 68, x2: 770, y1: y(ty), y2: y(ty), stroke: "#e0e9e6"}),
      svgNode("text", {x: 58, y: y(ty) + 4, "text-anchor": "end"}, fmt(ty)),
      svgNode("text", {x: x(tx), y: 314, "text-anchor": "middle"}, fmt(tx)));
  }
  svg.append(svgNode("text", {x: 420, y: 346, "text-anchor": "middle"}, "Offset fuente–receptor (m)"),
    svgNode("text", {transform: "translate(18 155) rotate(-90)", "text-anchor": "middle"}, "Tiempo registrado (ms)"));
  for (const pick of usable) {
    const a = pick.arrival, label = `${pick.receiver_id} · ${fmt(pick.offset_m)} m · ${fmt(a.onset_s * 1000)} ms · ${a.confidence}`;
    const point = svgNode("circle", {cx: x(pick.offset_m), cy: y(a.onset_s * 1000), r: 6,
      fill: states[a.confidence]?.[1] || "#236763", tabindex: 0, role: "button", "aria-label": label,
      "data-receiver": pick.receiver_id, class: "trs-pick"});
    point.append(svgNode("title", {}, label));
    point.onclick = () => select(pick.receiver_id);
    point.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(pick.receiver_id); } };
    svg.append(point);
  }
  if (!usable.length) svg.append(svgNode("text", {x: 420, y: 150, "text-anchor": "middle"}, "No hay tiempos de llegada disponibles"));
  return svg;
}
async function pages(request, path, current) {
  const items = [];
  let url = `${path}?limit=100`, total = 0;
  // Bound automatic presentation; a larger collection remains available in technical detail.
  for (let i = 0; i < 20; i++) {
    const {body} = await request(url);
    if (!current()) return null;
    items.push(...body[body.collection.replaceAll("-", "_")]); total = body.total_items;
    if (!body.next_cursor) break;
    url = `${path}?limit=100&cursor=${encodeURIComponent(body.next_cursor)}`;
  }
  return {items, total};
}
export function renderTRSDashboard(container, records, request, dossierId, isCurrent) {
  container.replaceChildren(); container.hidden = false;
  const root = node("div", undefined, "trs-dashboard"); container.append(root);
  root.append(node("h3", "Dosier de calidad de adquisición · TRS"),
    node("p", "Calificación, criterios, gráficas y evidencia por traza y tendido. Los primeros arribos se presentan después del QC de adquisición.", "hint"), renderQualityOverview(records));
  const label = node("label", "Registro"); const selector = node("select");
  for (const record of records) {
    const option = node("option", record.shot_id); option.value = record.record_index; selector.append(option);
  }
  selector.setAttribute("aria-label", "Registro de la vista TRS"); label.append(selector); root.append(label);
  const content = node("div"); root.append(content);
  let version = 0;
  async function show() {
    const generation = ++version;
    const current = () => generation === version && root.isConnected && isCurrent();
    const record = records.find((r) => r.record_index === Number(selector.value));
    content.replaceChildren(node("p", "Cargando gráficos del registro…", "hint"));
    if (!record) return;
    try {
      const base = `/v1/dossiers/${dossierId}/records/${record.record_index}`;
      const [arrivals, branches, qc] = await Promise.all([pages(request, `${base}/arrivals`, current), pages(request, `${base}/branches`, current),
        record.trace_qc?.integration_version ? pages(request, `${base}/qc-traces`, current) : Promise.resolve(null)]);
      if (!current() || !arrivals || !branches) return;
      content.replaceChildren();
      const picks = arrivals.items;
      if (qc) content.append(renderTraceQuality(record.trace_qc, qc.items, picks));
      else content.append(node("p", "Este dosier histórico no incluye QC por traza y conserva su resultado original. Para ver el dosier completo, abre en Seguimiento el UUID del resultado de una nueva ejecución con protocolo QC.", "notice"));
      content.append(node("h3", "Primeros arribos y ramas TRS"), node("p", "Resultados exploratorios del picker. Sus abstenciones no califican la adquisición.", "hint"));
      const counts = node("div", undefined, "trs-counts trs-pick-counts");
      for (const [state, count] of Object.entries(record.arrival_status_counts)) {
        const chip = node("span", `${count} ${states[state]?.[0] || state}`, "trs-chip");
        chip.style.borderColor = states[state]?.[1] || "#236763"; counts.append(chip);
      }
      content.append(counts, geometry(record));
      const panel = node("div", undefined, "trs-panel");
      panel.append(node("h3", "Tiempo–distancia"));
      const selected = node("p", "Selecciona un punto o un receptor para consultar su estado y motivo.", "trs-selection");
      const table = node("table", undefined, "trs-table trs-arrivals-table");
      const header = node("tr");
      for (const title of ["Receptor", "Offset (m)", "Llegada (ms)", "σ (ms)", "Estado"]) header.append(node("th", title));
      const head = node("thead"); head.append(header); table.append(head);
      const body = node("tbody"); table.append(body);
      const select = (id) => {
        const pick = picks.find((p) => p.receiver_id === id);
        if (!pick) return;
        for (const row of body.rows) row.classList.toggle("selected", row.dataset.receiver === id);
        for (const point of panel.querySelectorAll(".trs-pick")) point.classList.toggle("selected", point.dataset.receiver === id);
        selected.textContent = `${id} · ${pick.arrival.confidence} · ${pick.arrival.reason || "Sin motivo informado"}`;
      };
      panel.append(arrivalsPlot(picks, select), node("p",
        `${picks.filter((p) => finite(p.arrival.onset_s)).length} tiempos disponibles de ${arrivals.total} receptores. Los valores null no se dibujan como cero. Sin ajuste de velocidad ni barras de incertidumbre inferidas.`, "hint"), selected);
      if (picks.length < arrivals.total) panel.append(node("p", `Vista parcial: ${picks.length} de ${arrivals.total} receptores. Consulta el detalle por colección para recorrer todos.`, "notice"));
      const strip = node("div", undefined, "trs-receivers");
      for (const pick of picks) {
        const a = pick.arrival;
        const button = node("button", pick.receiver_id, "secondary"); button.type = "button";
        button.title = `${a.confidence}: ${a.reason || ""}`;
        button.setAttribute("aria-label", `${pick.receiver_id}: ${states[a.confidence]?.[0] || a.confidence}`);
        button.style.borderBottom = `4px solid ${states[a.confidence]?.[1] || "#236763"}`;
        button.onclick = () => select(pick.receiver_id); strip.append(button);
        const row = node("tr"); row.dataset.receiver = pick.receiver_id;
        const cell = node("td"); const link = node("button", pick.receiver_id, "trs-row-button"); link.type = "button";
        link.onclick = () => select(pick.receiver_id); cell.append(link); row.append(cell);
        for (const value of [fmt(pick.offset_m), fmt(finite(a.onset_s) ? a.onset_s * 1000 : null),
          fmt(finite(a.sigma_s) ? a.sigma_s * 1000 : null), states[a.confidence]?.[0] || a.confidence]) row.append(node("td", value));
        body.append(row);
      }
      panel.append(strip); content.append(panel);
      const wrapper = node("div", undefined, "trs-table-scroll"); wrapper.append(table); content.append(wrapper);
      const branchPanel = node("div", undefined, "trs-panel"); branchPanel.append(node("h3", "Ramas y modelo"));
      for (const branch of branches.items) {
        const side = branch.side === "LEFT" ? "Lado izquierdo" : branch.side === "RIGHT" ? "Lado derecho" : branch.side;
        branchPanel.append(node("h4", side));
        for (const [name, value] of [["Rama", branch], ["Ajuste", branch.fit], ["Parámetros", branch.parameters], ["Inversión", branch.inversion]]) {
          if (value?.state) branchPanel.append(node("p", `${name}: ${value.state} · ${value.reason || ""}`));
        }
      }
      if (!branches.total) branchPanel.append(node("p", "No hay ramas informadas en este registro."));
      content.append(branchPanel);
    } catch (error) { if (current()) content.replaceChildren(node("p", `No se pudo cargar la vista gráfica: ${error.message}`, "notice")); }
  }
  selector.onchange = show;
  show();
}
