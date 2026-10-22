import {send} from "./transport.js";

// Each tab owns its conditional-read cache. No tokens, drafts or data persist to disk.
export function createRepository(context) {
  const cache = new Map();
  const check = (generation) => {
    if (generation !== context().epoch) throw new Error("La sesión o el resultado seleccionado cambió.");
  };
  return {
    clear() { cache.clear(); },
    async request(url, options = {}) {
      const {token, epoch} = context();
      const cached = options.method ? null : cache.get(url);
      const headers = new Headers(options.headers);
      if (cached?.etag) headers.set("If-None-Match", cached.etag);
      const response = await send(url, token, {...options, headers});
      check(epoch);
      if (response.status === 304 && cached) return cached;
      const result = {body: await response.json(), etag: response.headers.get("ETag")};
      check(epoch);
      if (!options.method) {
        if (cache.size >= 64) cache.delete(cache.keys().next().value);
        cache.set(url, result);
      }
      return result;
    },
    async download(url) {
      const {token, epoch} = context();
      const response = await send(url, token);
      const blob = await response.blob();
      check(epoch);
      return blob;
    },
  };
}
