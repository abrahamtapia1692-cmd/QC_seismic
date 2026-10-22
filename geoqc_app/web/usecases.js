// One logical command keeps its body, precondition and key through transport retries.
export function createCommands(repository) {
  return (url, body, key, method = "POST", etag = null) => {
    const headers = {"Content-Type": "application/json", "Idempotency-Key": key};
    if (etag) headers["If-Match"] = etag;
    return repository.request(url, {method, headers, body: JSON.stringify(body)});
  };
}

// Resume confirmed stages only; do not resend bytes after completing an upload.
export async function uploadAcquisition(flow, repository, progress) {
  const command = createCommands(repository);
  const step = async (name, url, body) => {
    if (!flow.results[name]) flow.results[name] = (await command(url, body, `${flow.key}-${name}`)).body;
    return flow.results[name];
  };
  progress("Creando adquisición…");
  const acquisition = await step("acquisition", "/v1/acquisitions", {project_id: flow.project, name: flow.name});
  const uploads = [];
  for (let i = 0; i < flow.pairs.length; i++) {
    const upload = await step(`upload-${i}`, "/v1/upload-sessions", {acquisition_id: acquisition.id});
    progress(`Adquisición ${acquisition.id} · sesión ${upload.id} · registro ${i + 1}`);
    if (!flow.results[`complete-${i}`]) {
      for (const kind of ["waveform", "sidecar"]) {
        if (!flow.results[`${kind}-${i}`]) {
          flow.results[`${kind}-${i}`] = (await repository.request(`/v1/upload-sessions/${upload.id}/${kind}`, {method: "PUT", body: flow.pairs[i][kind]})).body;
        }
      }
      await step(`complete-${i}`, `/v1/upload-sessions/${upload.id}/complete`, {});
    }
    uploads.push(upload.id);
  }
  const revision = await step("revision", `/v1/acquisitions/${acquisition.id}/revisions`, {uploads});
  return step("run", "/v1/processing-runs", {revision_id: revision.id, technique: flow.technique || "MASW", protocol: flow.protocol, excluded_receiver_ids: flow.exclusions, ...(flow.traceQC ? {trace_qc: flow.traceQC} : {})});
}

export function supportedDossier(dossier) {
  const summary = dossier?.summary;
  const supported = (summary?.schema_version === "app-masw-dossier-0.1" && summary.method === "MASW" && summary.scope === "LOCAL_MASW_DIAGNOSTIC_ONLY") ||
    (summary?.schema_version === "app-trs-dossier-0.1" && summary.method === "TRS" && summary.scope === "LOCAL_TRS_DIAGNOSTIC_ONLY");
  return supported &&
    summary.scientific_status === "DIAGNOSTIC_ONLY_INCOMPLETE_EVIDENCE" &&
    summary.sufficiency?.status === "NOT_DEMONSTRATED" && summary.eligible_for_acceptance === false;
}

export async function validateUpload(pairs, protocolFile, technique, exclusions) {
  for (const [index, pair] of pairs.entries()) {
    let sidecar;
    try { sidecar = JSON.parse(await pair.sidecar.text()); }
    catch { throw new Error(`Registro ${index+1}: sidecar JSON ilegible.`); }
    if (sidecar?.context || !sidecar?.acquisition || !sidecar.shot_id || !sidecar.geometry_policy) {
      throw new Error(`Registro ${index+1}: selecciona el sidecar de adquisición .sgy.json, no assumptions.json ni una plantilla de preparación.`);
    }
    if (sidecar.acquisition.technique !== technique || sidecar.acquisition.wave !== (technique === "TRS" ? "P" : "RAYLEIGH")) {
      throw new Error(`Registro ${index+1}: el sidecar declara ${sidecar.acquisition.technique}; la técnica seleccionada es ${technique}. Usa los archivos de la misma técnica.`);
    }
    if (technique === "MASW" && !sidecar.acquisition.receiver_ids?.includes(exclusions[index])) {
      throw new Error(`Registro ${index+1}: el receptor excluido no está declarado en el sidecar.`);
    }
  }
  let protocol;
  try { protocol = JSON.parse(await protocolFile.text()); }
  catch { throw new Error("Protocolo JSON ilegible."); }
  if (technique === "TRS" ? !protocol?.picking : (!protocol?.signal || !Array.isArray(protocol.frequencies_hz) || !Array.isArray(protocol.velocities_ms))) {
    throw new Error(`Selecciona un protocolo ${technique}; no se convierte un protocolo de otra técnica.`);
  }
  return protocol;
}
