import {APIError} from "./transport.js";
import {createRepository} from "./repository.js";
import {createCommands, supportedDossier, uploadAcquisition, validateUpload} from "./usecases.js";
import {renderTRSDashboard} from "./trs-visuals.js";

const $ = (id) => document.getElementById(id);
const json = (value) => JSON.stringify(value, null, 2);
const message = (value = "") => { $("message").textContent = value; };
const uid = () => crypto.randomUUID();
let token = "", epoch = 0, dossier = null, review = null, reviewETag = null;
let draftETag = null, pendingReview = null, reviewBusy = false, uploadBusy = false;
let runId = "", detailVersion = 0, nextURL = null, flow = null, polling = false;
let exportRequest = null, exportResult = null, exportBusy = false;
const repository = createRepository(() => ({token, epoch}));
const request = repository.request, command = createCommands(repository), cache = repository;
const requestedDossier = new URL(location.href).searchParams.get("dossier");
if (requestedDossier && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(requestedDossier)) {
  $("dossier-id").value = requestedDossier;
  message("Conecta tu sesión para abrir directamente el dosier seleccionado en este enlace.");
}

function clearDossier() {
  $("trs-visuals").replaceChildren(); $("trs-visuals").hidden = true;
  dossier = review = reviewETag = draftETag = pendingReview = null;
  detailVersion++;
  nextURL = null;
  exportRequest = exportResult = null;
  $("export-format").disabled = false;
  $("export-download").disabled = true;
  $("export-status").textContent = "La exportación tiene estado propio y requiere el worker de exportaciones.";
  $("review-form").reset();
  $("dossier-section").hidden = $("review-section").hidden = true;
  $("detail-results").replaceChildren();
  $("conflict").hidden = true;
}

function addRecord() {
  const index = $("file-pairs").children.length;
  if (index >= 4) return;
  const pair = document.createElement("div");
  for (const [kind, title, accept] of [["waveform", "SEG-Y", ".sgy,.segy"], ["sidecar", "Sidecar JSON", ".json"]]) {
    const label = document.createElement("label");
    label.textContent = `Registro ${index + 1} · ${title}`;
    const input = document.createElement("input");
    input.type = "file"; input.required = true; input.accept = accept;
    input.dataset.kind = kind; input.id = `${kind}-${index}`;
    label.append(input); pair.append(label);
  }
  $("file-pairs").append(pair);
  $("add-record").disabled = index === 3;
}
addRecord();
$("add-record").onclick = addRecord;

function updateReviewControls() {
  const conflict = draftETag !== null && draftETag !== reviewETag;
  $("conflict").hidden = !conflict;
  $("rebase").hidden = !conflict || review?.state !== "PENDING" || !!pendingReview;
  $("review-fields").disabled = reviewBusy || !!pendingReview;
  $("review-submit").disabled = reviewBusy || !review || !supportedDossier(dossier) || (!pendingReview && (conflict || review.state !== "PENDING"));
  $("review-submit").textContent = pendingReview ? "Reintentar la misma revisión" : "Confirmar revisión";
}

async function refreshReview() {
  if (!dossier) return;
  const result = await request(`/v1/review-cases/${dossier.review_id}`);
  review = result.body; reviewETag = result.etag;
  $("review-state").textContent = `${review.state} · versión ${review.version}`;
  $("review-history").textContent = json(review.history);
  $("review-section").hidden = false;
  updateReviewControls();
}

function renderScience() {
  const summary = dossier.summary;
  $("historical-result").hidden = !dossier.current_dossier_id || dossier.current_dossier_id === dossier.id;
  const qcAssessment = summary.trace_qc_assessment;
  $("open-quality-report").hidden = summary.method !== "TRS" || !qcAssessment;
  $("qc-global").hidden = !qcAssessment;
  const operational = summary.operational_assessment;
  $("qc-global").textContent = qcAssessment ? `${operational ? `Calificación diagnóstica condicional del conjunto: ${operational.grade} · cobertura media ${Math.round(100 * operational.mean_coverage_fraction)} %. ` : ""}QC estricto: ${qcAssessment.grade} · ${qcAssessment.total_traces} trazas · ${qcAssessment.demonstrated_bad_traces} fallas demostradas · ${qcAssessment.pending_traces} con evidencia pendiente. Se suman trazas; no se promedian porcentajes de registros.` : "";
  $("science-summary").replaceChildren();
  for (const [title, value] of [["Estado científico", summary.scientific_status], ["Suficiencia", summary.sufficiency.status], ["Elegibilidad", String(summary.eligible_for_acceptance)]]) {
    const block = document.createElement("div"); block.className = "metric";
    const label = document.createElement("small"); label.textContent = title;
    const text = document.createElement("strong"); text.textContent = value;
    block.append(label, text); $("science-summary").append(block);
  }
  $("digest").textContent = `Dosier abierto: ${dossier.id} · Digest científico: ${dossier.scientific_digest}`;
  $("science-provenance").textContent = json({summary, manifest: dossier.manifest});
  $("dossier-section").hidden = false;
  $("unsupported").hidden = supportedDossier(dossier);
  for (const option of $("collection").options) {
    option.disabled = !!option.dataset.method && option.dataset.method !== summary.method;
  }
  if ($("collection").selectedOptions[0].disabled) $("collection").value = "records";
  updateFilters();
}

async function openDossier(id) {
  if (dossier?.id !== id) {
    if (draftETag || pendingReview || exportRequest) throw new Error("Desconecta para cambiar de dosier y descartar el borrador o comando pendiente.");
    clearDossier();
    epoch++;
  }
  const result = await request(`/v1/dossiers/${encodeURIComponent(id)}`);
  dossier = result.body;
  $("dossier-id").value = dossier.id;
  const link = new URL(location.href); link.searchParams.set("dossier", dossier.id);
  history.replaceState(null, "", link);
  renderScience();
  $("technical-details").open = dossier.summary.method !== "TRS";
  $("dossier-section").scrollIntoView({block: "start"});
  $("collection").value = "records";
  updateFilters();
  await loadDetail(`/v1/dossiers/${dossier.id}/records?limit=25`);
  await refreshReview();
}

async function refresh() {
  if (!token || polling || (!runId && !dossier && !exportResult)) return;
  polling = true;
  try {
    if (runId) {
      const {body} = await request(`/v1/processing-runs/${encodeURIComponent(runId)}`);
      $("run-status").textContent = `Estado: ${body.state} · intento ${body.attempt}${body.error_code ? ` · ${body.error_code}` : ""}${body.state === "QUEUED" ? " · En espera del worker local; todavía no hay un dosier nuevo." : ""}`;
      if (body.dossier_id && !dossier) await openDossier(body.dossier_id);
    }
    if (dossier) {
      const result = await request(`/v1/dossiers/${dossier.id}`);
      dossier = result.body; renderScience();
      await refreshReview();
    }
    if (exportResult) {
      const {body} = await request(`/v1/exports/${exportResult.id}`);
      exportResult = body;
      $("export-status").textContent = `${body.state} · exportación ${body.id}${body.error_code ? ` · ${body.error_code}` : ""}`;
      $("export-download").disabled = body.state !== "READY";
    }
    $("connection").textContent = "Lectura confirmada · " + new Date().toLocaleTimeString("es-MX");
  } catch (error) {
    $("connection").textContent = "Lectura pendiente; estado mostrado puede estar desactualizado";
    message(error.message);
  } finally { polling = false; }
}
setInterval(refresh, 3000);
window.addEventListener("focus", refresh);
window.addEventListener("online", refresh);

$("session-form").onsubmit = async (event) => {
  event.preventDefault();
  if (uploadBusy || reviewBusy || exportBusy) return message("Espera a que termine la operación actual.");
  // An identity change must not discard a command whose response was lost.
  if (pendingReview || flow || exportRequest) return message("Desconecta para cambiar de identidad. Conserva los IDs antes de salir.");
  token = $("token").value.trim(); $("token").value = "";
  epoch++; cache.clear(); clearDossier(); runId = "";
  $("connection").textContent = "Token cargado; consulta un recurso para validar sus permisos";
  message();
  const linkedDossier = new URL(location.href).searchParams.get("dossier");
  if (linkedDossier && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(linkedDossier)) {
    try { await openDossier(linkedDossier); }
    catch (error) { message(error.message); }
  }
};
$("disconnect").onclick = () => {
  if (uploadBusy || reviewBusy || exportBusy) return message("Espera a que termine la operación actual.");
  token = ""; epoch++; cache.clear(); clearDossier(); flow = null; runId = "";
  $("token").value = ""; $("upload-fields").disabled = false;
  $("upload-submit").textContent = "Cargar y procesar";
  $("connection").textContent = "Sin conexión";
  $("run-status").textContent = "Sin seguimiento activo.";
  $("upload-progress").textContent = "Requiere rol FIELD_OPERATOR.";
  message("Sesión cerrada; los recursos confirmados permanecen en el servidor.");
};

async function performUpload() {
  const run = await uploadAcquisition(flow, repository, (text) => { $("upload-progress").textContent = text; });
  $("upload-progress").textContent = `Carga confirmada · run ${run.id}`;
  runId = run.id; $("run-id").value = runId;
  $("upload-submit").textContent = "Carga confirmada";
  await refresh();
}

$("upload-form").onsubmit = async (event) => {
  event.preventDefault();
  if (uploadBusy || exportBusy) return;
  if (!token) return message("Conecta una sesión de operador.");
  if (draftETag || pendingReview) return message("Conserva el borrador y termina la revisión antes de iniciar otra adquisición.");
  uploadBusy = true; $("upload-submit").disabled = true; $("new-upload").disabled = true;
  try {
    if (!flow) {
      const project = $("project").value.trim();
      if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(project)) throw new Error("Proyecto debe ser un UUID: copia project_id de .local/credentials.json. El token va en Sesión local.");
      const pairs = [...$("file-pairs").children].map((pair) => Object.fromEntries([...pair.querySelectorAll("input")].map((input) => [input.dataset.kind, input.files[0]])));
      if (pairs.some((pair) => !pair.waveform || !pair.sidecar || pair.waveform.size > 32 * 1024 ** 2 || pair.sidecar.size > 1024 ** 2)) throw new Error("Selecciona cada pareja dentro de los límites de tamaño.");
      const protocolFile = $("protocol").files[0];
      if (!protocolFile || protocolFile.size > 1024 ** 2) throw new Error("Selecciona un protocolo JSON de hasta 1 MiB.");
      const technique = $("technique").value;
      const exclusions = technique === "TRS" ? [] : $("exclusions").value.split(",").map((value) => value.trim());
      if (technique === "MASW" && (exclusions.length !== pairs.length || exclusions.some((value) => !value))) throw new Error("Declara un receptor excluido por registro, en el mismo orden.");
      const protocol = await validateUpload(pairs, protocolFile, technique, exclusions);
      let traceQC = null;
      const qcFile = $("trace-qc").files[0];
      if (technique === "TRS" && !qcFile) throw new Error("El dosier TRS completo requiere QC por traza JSON. Para KM con estimaciones selecciona examples/km_app/demo_trs_f1/trace_qc_operational.json.");
      if (technique === "TRS" && qcFile) {
        if (qcFile.size > 1024 ** 2) throw new Error("QC por traza debe ser JSON de hasta 1 MiB.");
        try { traceQC = JSON.parse(await qcFile.text()); }
        catch { throw new Error("QC por traza JSON ilegible."); }
        if (!traceQC?.protocol?.analysis || !traceQC.protocol.provenance) throw new Error("Selecciona un protocolo QC por traza con protocol.analysis y procedencia.");
      }
      flow = {key: uid(), results: {}, pairs, technique, protocol, traceQC, exclusions, project, name: $("name").value.trim()};
      clearDossier(); epoch++; cache.clear(); runId = "";
      $("upload-fields").disabled = true;
    }
    message(); await performUpload();
  } catch (error) {
    if (flow && !Object.keys(flow.results).length && error instanceof APIError && error.status === 422 && error.code === "INVALID_REQUEST") {
      flow = null;
      $("upload-fields").disabled = false;
      $("upload-progress").textContent = "Solicitud rechazada antes de crear la adquisición. Puedes corregir los datos conservando los archivos.";
    }
    message(error.message + (flow ? " Puedes reintentar la misma carga mientras esta pestaña siga abierta." : " Corrige los datos o archivos antes de cargar."));
    $("upload-submit").textContent = flow ? "Reintentar carga" : "Cargar y procesar";
  } finally {
    uploadBusy = false; $("new-upload").disabled = false;
    $("upload-submit").disabled = !!flow?.results.run;
  }
};
$("new-upload").onclick = () => {
  if (uploadBusy) return;
  flow = null; $("upload-fields").disabled = false;
  $("upload-form").reset(); $("file-pairs").replaceChildren(); addRecord();
  updateTechnique();
  $("upload-submit").disabled = false; $("upload-submit").textContent = "Cargar y procesar";
  $("upload-progress").textContent = "Nueva carga. Las sesiones previas permanecen en el servidor hasta su cierre o vencimiento.";
};
$("run-form").onsubmit = async (event) => {
  event.preventDefault();
  if (uploadBusy || reviewBusy || exportBusy || draftETag || pendingReview) return message("Termina la operación o conserva el borrador antes de cambiar de run.");
  epoch++; cache.clear(); clearDossier(); runId = $("run-id").value.trim();
  message(); await refresh();
};
$("dossier-form").onsubmit = async (event) => {
  event.preventDefault();
  if (uploadBusy || reviewBusy || exportBusy) return;
  try { message(); runId = ""; await openDossier($("dossier-id").value.trim()); }
  catch (error) { message(error.message); }
};

function updateFilters() {
  const collection = $("collection").value;
  $("record-index").disabled = collection === "records";
  for (const id of ["direction", "frequency-min", "frequency-max"]) $(id).disabled = ["records", "traces", "arrivals", "branches", "qc-traces"].includes(collection);
}
function updateTechnique() {
  const technique = $("technique").value;
  $("trace-qc-label").hidden = $("trace-qc-help").hidden = technique !== "TRS";
  $("trace-qc").disabled = technique !== "TRS";
  $("trace-qc").required = technique === "TRS";
  $("protocol-label").textContent = `Protocolo ${technique} JSON`;
  $("exclusions-label").hidden = technique === "TRS";
  $("exclusions").disabled = technique === "TRS";
  $("exclusions").required = technique === "MASW";
  $("technique-help").textContent = technique === "TRS" ? "TRS calcula primeros arribos y ramas tiempo-distancia. Requiere sidecar TRS/P y protocolo TRS." : "MASW calcula dispersión aparente. Requiere sidecar MASW/Rayleigh y protocolo MASW.";
}
$("technique").onchange = updateTechnique;
updateTechnique();
$("collection").onchange = updateFilters;
updateFilters();
async function loadDetail(url) {
  const version = ++detailVersion;
  const generation = epoch;
  $("next-page").disabled = true;
  try {
    const {body} = await request(url);
    if (version !== detailVersion || generation !== epoch) return;
    $("detail-results").replaceChildren();
    $("detail-context").textContent = `${body.total_items} elementos · ${body.context?.shot_id || "Registros del dosier"}`;
    const context = document.createElement("details");
    const contextLabel = document.createElement("summary"); contextLabel.textContent = "Contexto, protocolo y unidades";
    const contextJSON = document.createElement("pre"); contextJSON.textContent = json({context: body.context, units: body.units});
    context.append(contextLabel, contextJSON); $("detail-context").append(context);
    if (body.collection === "records" && dossier?.summary.method === "TRS") {
      const id = dossier.id;
      renderTRSDashboard($("trs-visuals"), body.records, request, id, () => generation === epoch && dossier?.id === id);
    }
    for (const [index, value] of body[body.collection.replaceAll("-", "_")].entries()) {
      const article = document.createElement("article");
      const label = document.createElement("strong"); label.textContent = `${body.collection} · elemento ${index + 1} de esta página`;
      const pre = document.createElement("pre"); pre.textContent = json(value);
      article.append(label, pre); $("detail-results").append(article);
    }
    if (!body.total_items) $("detail-results").textContent = "Sin elementos para este filtro.";
    const next = new URL(url, location.origin);
    if (body.next_cursor) next.searchParams.set("cursor", body.next_cursor);
    nextURL = body.next_cursor ? next.pathname + next.search : null;
    $("next-page").hidden = !nextURL;
  } catch (error) { if (version === detailVersion) message(error.message); }
  finally { if (version === detailVersion) $("next-page").disabled = false; }
}
$("detail-form").onsubmit = async (event) => {
  event.preventDefault();
  if (!dossier) return;
  const collection = $("collection").value, params = new URLSearchParams({limit: "25"});
  let url = `/v1/dossiers/${dossier.id}/records`;
  if (collection !== "records") url += `/${encodeURIComponent($("record-index").value)}/${collection}`;
  if (!["records", "traces", "arrivals", "branches", "qc-traces"].includes(collection)) {
    for (const [id, key] of [["direction", "direction"], ["frequency-min", "frequency_min_hz"], ["frequency-max", "frequency_max_hz"]]) {
      if ($(id).value !== "") params.set(key, $(id).value);
    }
  }
  message(); await loadDetail(`${url}?${params}`);
};
$("next-page").onclick = () => { if (nextURL) loadDetail(nextURL); };

$("review-form").oninput = () => { if (!draftETag && review) draftETag = reviewETag; updateReviewControls(); };
$("rebase").onclick = () => { if (review?.state === "PENDING" && !pendingReview) { draftETag = reviewETag; updateReviewControls(); } };
$("review-form").onsubmit = async (event) => {
  event.preventDefault();
  if (!review || reviewBusy) return;
  if (!supportedDossier(dossier)) return message("Versión o estado científico no soportado por este cliente. Dictamen bloqueado.");
  if (!pendingReview && (review.state !== "PENDING" || (draftETag && draftETag !== reviewETag))) return message("La revisión cambió. Consulta el historial; tu borrador se conserva.");
  if (!pendingReview) {
    const body = {verdict: $("verdict").value, scope: $("scope").value.trim(), justification: $("justification").value.trim(), caveats: $("caveats").value.split("\n").map((value) => value.trim()).filter(Boolean), scientific_digest: dossier.scientific_digest};
    if (!body.scope || !body.justification || (body.verdict === "ACCEPTED" && !body.caveats.length)) return message("Completa alcance, justificación y salvedades de ACCEPTED.");
    if (body.caveats.length > 32 || body.caveats.some((value) => value.length > 4000)) return message("Máximo 32 salvedades de 4000 caracteres.");
    draftETag ||= reviewETag;
    pendingReview = {body, key: uid(), etag: draftETag || reviewETag, id: review.id};
  }
  reviewBusy = true; updateReviewControls();
  try {
    const pending = pendingReview;
    await command(`/v1/review-cases/${pending.id}`, pending.body, pending.key, "PUT", pending.etag);
    pendingReview = null; draftETag = null;
    $("review-form").reset();
    message("Revisión confirmada. La calidad científica, suficiencia y elegibilidad se conservan.");
    await refreshReview();
  } catch (error) {
    // A transport/5xx failure may follow a committed write: preserve exact command and key.
    if (error instanceof APIError && error.status < 500) pendingReview = null;
    message(error.message + (pendingReview ? " Reintenta la misma revisión para recuperar su confirmación." : " Tu borrador se conserva."));
    try { await refreshReview(); } catch { /* The draft remains available during an outage. */ }
  } finally { reviewBusy = false; updateReviewControls(); }
};

async function download(url, filename) {
  const blob = await repository.download(url);
  const objectURL = URL.createObjectURL(blob);
  const link = document.createElement("a"); link.href = objectURL; link.download = filename; link.click();
  setTimeout(() => URL.revokeObjectURL(objectURL), 1000);
}

$("export-form").onsubmit = async (event) => {
  event.preventDefault();
  if (!dossier || exportBusy) return;
  exportBusy = true; $("export-submit").disabled = true;
  try {
    exportRequest ||= {id: dossier.id, format: $("export-format").value, key: uid()};
    $("export-format").disabled = true;
    $("export-download").disabled = true;
    exportResult = (await command(`/v1/dossiers/${exportRequest.id}/exports`, {format: exportRequest.format}, exportRequest.key)).body;
    exportRequest = null;
    $("export-status").textContent = `${exportResult.state} · exportación ${exportResult.id}`;
    $("export-format").disabled = false;
    message("Exportación solicitada. Puedes consultar su estado sin recalcular ciencia.");
  } catch (error) {
    if (error instanceof APIError && error.status < 500) { exportRequest = null; $("export-format").disabled = false; }
    message(error.message + (exportRequest ? " Reintenta para recuperar la misma exportación." : ""));
  } finally { exportBusy = false; $("export-submit").disabled = false; }
};
$("export-download").onclick = async () => {
  if (exportResult?.state !== "READY") return;
  try { await download(`/v1/exports/${exportResult.id}/content`, `geoqc-${exportResult.id}.${exportResult.format.toLowerCase()}`); }
  catch (error) { message(error.message); }
};

$("download-science").onclick = async () => {
  if (!dossier) return;
  try {
    // The manifest contains the scientific JSON artifact; use the dossier's published reference.
    const manifest = dossier.manifest;
    const artifact = manifest.artifacts.find((item) => item.kind === "scientific_json");
    if (!artifact?.id) throw new Error("No se encontró la referencia de descarga científica.");
    await download(`/v1/artifacts/${artifact.id}/content`, `geoqc-${dossier.id}.json`);
  } catch (error) { message(error.message); }
};

$("open-quality-report").onclick = async () => {
  if (!dossier) return;
  const tab = window.open("about:blank", "_blank");
  if (!tab) return message("Permite abrir una pestaña para consultar el informe completo.");
  tab.opener = null;
  try {
    const blob = await repository.download(`/v1/dossiers/${dossier.id}/quality-report`);
    const url = URL.createObjectURL(blob);
    tab.location.replace(url);
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch (error) { tab.close(); message(error.message); }
};

$("open-current-dossier").onclick = async () => {
  if (!dossier?.current_dossier_id) return;
  try { await openDossier(dossier.current_dossier_id); }
  catch (error) { message(error.message); }
};
