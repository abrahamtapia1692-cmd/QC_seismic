// HTTP only: authorization and safe, same-origin requests.
export class APIError extends Error {
  constructor(status, body) {
    super(`${body.code || status}: ${body.message || "Solicitud no confirmada"}`);
    this.status = status;
    this.code = body.code;
  }
}

export async function send(url, token, options = {}) {
  if (!token) throw new Error("Conecta una sesión local vigente.");
  const target = new URL(url, location.origin);
  if (target.origin !== location.origin || !target.pathname.startsWith("/v1/")) throw new Error("Ruta no permitida.");
  const headers = new Headers(options.headers);
  headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(target, {...options, headers, cache: "no-store", redirect: "error"});
  if (!response.ok && response.status !== 304) {
    throw new APIError(response.status, await response.json().catch(() => ({})));
  }
  return response;
}
