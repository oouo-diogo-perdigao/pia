/**
 * Copy text using navigator.clipboard with a fixed hidden-textarea
 * document.execCommand('copy') fallback for non-HTTPS origins and an optional
 * native bridge fallback (QtWebEngine desktop shell).
 */
export function copyWithExecCommand(text, doc = globalThis.document) {
  if (
    !doc ||
    typeof doc.createElement !== "function" ||
    !doc.body ||
    typeof doc.execCommand !== "function"
  ) {
    return false;
  }
  const previousActive = doc.activeElement;
  const element = doc.createElement("textarea");
  element.value = text;
  element.setAttribute?.("readonly", "");
  element.setAttribute?.("aria-hidden", "true");
  Object.assign(element.style || {}, {
    position: "fixed",
    opacity: "0",
    pointerEvents: "none",
    left: "-9999px",
    top: "0",
  });
  doc.body.appendChild(element);
  try {
    element.focus?.();
    element.select?.();
    element.setSelectionRange?.(0, text.length);
    return Boolean(doc.execCommand("copy"));
  } catch {
    return false;
  } finally {
    if (typeof element.remove === "function") {
      element.remove();
    } else if (typeof doc.body.removeChild === "function") {
      doc.body.removeChild(element);
    }
    previousActive?.focus?.();
  }
}

export async function copyTextWithFallback(
  text,
  { nav = globalThis.navigator, doc = globalThis.document, nativeCopy } = {},
) {
  const value = String(text ?? "");
  if (nav?.clipboard && typeof nav.clipboard.writeText === "function") {
    try {
      await nav.clipboard.writeText(value);
      return true;
    } catch {
      // Non-HTTPS origin or denied clipboard permission: fall back below.
    }
  }
  if (copyWithExecCommand(value, doc)) {
    return true;
  }
  if (typeof nativeCopy === "function") {
    try {
      await nativeCopy(value);
      return true;
    } catch {
      // Native bridge unavailable in standalone browser mode.
    }
  }
  throw new Error("Não foi possível copiar para a área de transferência.");
}
