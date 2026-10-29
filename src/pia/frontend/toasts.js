const key = "pia:toast-history:v1";
export function toastHistory() {
  try {
    return JSON.parse(localStorage.getItem(key) || "[]");
  } catch {
    return [];
  }
}
export function notify(message, type = "success") {
  const entry = {
    id: crypto.randomUUID(),
    time: new Date().toISOString(),
    message: String(message),
    type,
  };
  try {
    localStorage.setItem(
      key,
      JSON.stringify([...toastHistory(), entry].slice(-200)),
    );
  } catch {}
  window.dispatchEvent(new CustomEvent("pia:toast", { detail: entry }));
}
