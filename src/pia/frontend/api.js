import { notify } from "./toasts";
export async function session() {
  const response = await fetch("/api/pia/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  if (!response.ok) throw Error("Não foi possível iniciar a sessão local.");
}
export async function api(path, data) {
  const response = await fetch("/api/pia" + path, {
    method: data === undefined ? "GET" : "POST",
    headers: data === undefined ? {} : { "Content-Type": "application/json" },
    body: data === undefined ? undefined : JSON.stringify(data),
  });
  const result = await response.json();
  if (!response.ok) throw Error(result.error || "Falha na solicitação.");
  if (
    data !== undefined &&
    (/\/save(?:-|$)/.test(path) ||
      (path === "/chat/message" && data.action === "edit") ||
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
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    await api("/native", { action: "clipboard-text", payload: { text } });
  }
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
