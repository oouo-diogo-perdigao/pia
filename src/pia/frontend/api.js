import { notify } from "./toasts";
import { copyTextWithFallback } from "./clipboard-helpers";
export async function session() {
  const response = await fetch("/api/pia/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  if (!response.ok) throw Error("Não foi possível iniciar a sessão local.");
}
export async function api(path, data, options = {}) {
  const method = options.method || (data === undefined ? "GET" : "POST");
  const hasBody =
    data !== undefined && !["GET", "HEAD"].includes(method.toUpperCase());
  const headers = {
    ...(hasBody ? { "Content-Type": "application/json" } : {}),
    ...(options.headers || {}),
  };
  const response = await fetch("/api/pia" + path, {
    method,
    headers,
    body: hasBody ? JSON.stringify(data) : undefined,
  });
  const text = await response.text();
  let result = {};
  if (text) {
    try {
      result = JSON.parse(text);
    } catch {
      result = { error: text };
    }
  }
  if (!response.ok) {
    const err = Error(result?.error || "Falha na solicitação.");
    err.status = response.status;
    err.code = result?.code || null;
    err.details = result || {};
    throw err;
  }
  if (
    data !== undefined &&
    (/\/save(?:-|$)/.test(path) ||
      (path === "/chat/message" && data?.action === "edit") ||
      path === "/bots/secretaria" ||
      path === "/preferences")
  )
    notify("Salvo com sucesso.");
  return result;
}
export const appApi = (id, action, data = {}) =>
  api("/apps/" + id + "/" + action, data);
export function watchJob(id, callback, after = 0) {
  const source = new EventSource("/api/pia/events/" + id + "?after=" + after);
  source.onmessage = (event) => {
    const value = JSON.parse(event.data);
    callback(value);
    if (["done", "error"].includes(value.type)) source.close();
  };
  return source;
}
export function report(error) {
  notify(error?.stack || error?.message || String(error), "error");
  window.dispatchEvent(
    new CustomEvent("pia:error", {
      detail: error?.stack || error?.message || String(error),
    }),
  );
}
export async function copy(text) {
  return copyTextWithFallback(text, {
    nativeCopy: (value) =>
      api("/native", { action: "clipboard-text", payload: { text: value } }),
  });
}
export const safe =
  (fn) =>
  (...args) => {
    try {
      Promise.resolve(fn(...args)).catch(report);
    } catch (error) {
      report(error);
    }
  };
