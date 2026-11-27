import { session, appApi } from "/pia/sdk.js";
import {
  bounds,
  hex,
  drawStroke,
  selectionPath,
  renderResult,
} from "./image-tools.js";

const $ = (s) => document.querySelector(s);
const api = (action, data = {}) => appApi("screenshots", action, data);
const canvas = $("#canvas");
const ctx = canvas.getContext("2d");
const base = document.createElement("canvas");
const bc = base.getContext("2d", { willReadFrequently: true });

let source = null;
let selection = null;
let strokes = [];
let drawing = null;
let tool = "free";
let scale = 1;
let ox = 0;
let oy = 0;
let width = 3;
let smooth = true;
let pointer = { x: 0, y: 0 };
let lastColor = [0, 0, 0];
let record = null;
let sessionReady = false;
let starsCreated = false;
let loadingTimer = null;
let activeOpenGeneration = 0;

const reducedMotion = () =>
  window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches === true;

function announceStatus(text) {
  const el = $("#capture-status");
  if (!el) return;
  el.textContent = "";
  if (text) el.textContent = text;
}

function announceAlert(text) {
  const el = $("#capture-alert");
  if (!el) return;
  el.textContent = "";
  if (text) el.textContent = text;
}

function notice(text) {
  const el = $("#notice");
  if (!el) return;
  el.hidden = !text;
  el.textContent = text || "";
}

function safe(fn) {
  return (...args) =>
    Promise.resolve()
      .then(() => fn(...args))
      .catch((e) => {
        const msg = e?.message || String(e);
        notice(msg);
        announceAlert(msg);
      });
}

function size() {
  return { x: $("#stage").clientWidth, y: $("#stage").clientHeight };
}

function fit() {
  const s = size();
  scale = Math.min(s.x / base.width, s.y / base.height);
  ox = (s.x - base.width * scale) / 2;
  oy = (s.y - base.height * scale) / 2;
  render();
}

function coords(e) {
  const r = canvas.getBoundingClientRect();
  return {
    x: Math.max(0, Math.min(base.width - 1, (e.clientX - r.left - ox) / scale)),
    y: Math.max(0, Math.min(base.height - 1, (e.clientY - r.top - oy) / scale)),
  };
}

function render() {
  if (!source) return;
  const s = size();
  const dpr = devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(s.x * dpr));
  canvas.height = Math.max(1, Math.round(s.y * dpr));
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = "#111118";
  ctx.fillRect(0, 0, s.x, s.y);
  ctx.translate(ox, oy);
  ctx.scale(scale, scale);
  ctx.imageSmoothingEnabled = smooth;
  ctx.drawImage(base, 0, 0);
  for (const stroke of strokes) drawStroke(ctx, stroke);
  if (selection) {
    const r = bounds(selection.points, base.width, base.height);
    ctx.strokeStyle = "#c397ff";
    ctx.lineWidth = 1.5 / scale;
    ctx.setLineDash([5 / scale, 4 / scale]);
    selectionPath(ctx, selection, r);
    ctx.stroke();
    ctx.fillStyle = "#a16cdf17";
    ctx.fill();
    ctx.setLineDash([]);
  }
  $("#free").classList.toggle("selected", tool === "free");
  $("#rectangle").classList.toggle("selected", tool === "rect");
}

function read(point) {
  if (!source) return;
  pointer = point;
  const p = bc.getImageData(Math.floor(point.x), Math.floor(point.y), 1, 1).data;
  lastColor = [p[0], p[1], p[2]];
  let measurement = "";
  if (selection) {
    const r = bounds(selection.points, base.width, base.height);
    measurement = ` · seleção ${r.width} × ${r.height} px`;
  }
  $("#readout").style.borderRight = "12px solid " + hex(lastColor);
  $("#readout").style.paddingRight = "8px";
  $("#readout").textContent =
    `X ${Math.floor(point.x)} · Y ${Math.floor(point.y)} · ${hex(lastColor)} · zoom ${(scale * 100).toFixed(0)}%${measurement}`;
}

function zoomBy(mult, anchor) {
  const s = size();
  const a = anchor || { x: s.x / 2, y: s.y / 2 };
  const ix = (a.x - ox) / scale;
  const iy = (a.y - oy) / scale;
  scale = Math.max(0.05, Math.min(64, scale * mult));
  ox = a.x - ix * scale;
  oy = a.y - iy * scale;
  render();
  read(pointer);
}

async function copyColor() {
  const value = hex(lastColor, $("#bgr").checked);
  await api("color", { value });
  const msg = "Cor copiada: " + value;
  notice(msg);
  announceStatus(msg);
}

function resultCanvas() {
  return renderResult(base, strokes, selection, {
    opaque: $("#format").value !== "png",
    comment: $("#comment").value,
    border: $("#border").checked,
  });
}

function successMessage() {
  const cfg = record?.config || {};
  const autoSave = cfg.auto_save !== undefined ? !!cfg.auto_save : true;
  const autoCopy = cfg.auto_copy !== undefined ? !!cfg.auto_copy : true;
  if (autoSave && autoCopy) return "Captura salva e copiada.";
  if (autoSave) return "Captura salva.";
  if (autoCopy) return "Captura copiada.";
  return "Captura concluída.";
}

async function finish() {
  drawing = null;
  notice("Salvando captura…");
  announceStatus("Salvando captura…");
  try {
    await api("finalize", {
      data: resultCanvas().toDataURL("image/png"),
      format: $("#format").value,
      title: $("#title").value,
    });
    announceStatus(successMessage());
    new BroadcastChannel("pia:apps").postMessage({
      type: "screenshots:changed",
    });
  } catch (e) {
    const reason = e?.message || "erro desconhecido";
    const msg = `Não foi possível salvar a captura: ${reason}. Tente de novo ou pressione Esc.`;
    notice(msg);
    announceAlert(msg);
  }
}

async function fullScreen() {
  selection = null;
  await finish();
}

let cancelledGesture = false;
canvas.addEventListener("contextmenu", (e) => e.preventDefault());

function cancelGesture() {
  if (drawing === "annotation") strokes.pop();
  else if (drawing === "selection") selection = null;
  drawing = null;
  cancelledGesture = true;
  render();
}

canvas.addEventListener("mousedown", (e) => {
  if ((e.buttons & 3) === 3) {
    e.preventDefault();
    cancelGesture();
  }
});

canvas.addEventListener("pointerdown", (e) => {
  e.preventDefault();
  if ((e.buttons & 3) === 3) {
    cancelGesture();
    return;
  }
  cancelledGesture = false;
  canvas.setPointerCapture(e.pointerId);
  const p = coords(e);
  read(p);
  if (e.button === 1) {
    safe(copyColor)();
    return;
  }
  if (e.button === 2) {
    drawing = "annotation";
    strokes.push({
      kind: e.ctrlKey ? "rect" : "pen",
      points: [p],
      width,
      color: $("#ink").value,
    });
  } else if (e.button === 0) {
    drawing = "selection";
    selection = {
      kind: e.ctrlKey || tool === "rect" ? "rect" : "free",
      points: [p],
    };
  }
  render();
});

canvas.addEventListener("pointermove", (e) => {
  const p = coords(e);
  read(p);
  if ((e.buttons & 3) === 3) {
    cancelGesture();
    return;
  }
  if (drawing === "annotation") {
    const stroke = strokes.at(-1);
    if (stroke.kind === "rect") stroke.points[1] = p;
    else stroke.points.push(p);
  } else if (drawing === "selection") {
    if (selection.kind === "rect") selection.points[1] = p;
    else selection.points.push(p);
  }
  render();
});

canvas.addEventListener(
  "pointerup",
  safe(async (e) => {
    const previous = drawing;
    drawing = null;
    if (canvas.hasPointerCapture(e.pointerId))
      canvas.releasePointerCapture(e.pointerId);
    if (!cancelledGesture && previous === "selection") {
      const r = bounds(selection.points, base.width, base.height);
      if (r.width < 5 && r.height < 5) {
        selection = null;
        render();
        return;
      }
      await finish();
    }
    render();
  }),
);

canvas.addEventListener("pointercancel", cancelGesture);

canvas.addEventListener(
  "wheel",
  (e) => {
    e.preventDefault();
    if (e.ctrlKey) {
      const r = canvas.getBoundingClientRect();
      zoomBy(e.deltaY < 0 ? 1.2 : 1 / 1.2, {
        x: e.clientX - r.left,
        y: e.clientY - r.top,
      });
    } else {
      width = Math.max(1, Math.min(80, width + (e.deltaY < 0 ? 1 : -1)));
      $("#ink-size").textContent = width + " px";
    }
  },
  { passive: false },
);

function rectangle() {
  if (!selection)
    selection = {
      kind: "rect",
      points: [
        { x: 0, y: 0 },
        { x: base.width, y: base.height },
      ],
    };
  if (selection.kind !== "rect") {
    const r = bounds(selection.points, base.width, base.height);
    selection = {
      kind: "rect",
      points: [
        { x: r.x, y: r.y },
        { x: r.x + r.width, y: r.y + r.height },
      ],
    };
  }
  return selection;
}

window.addEventListener(
  "keydown",
  safe(async (e) => {
    const active = document.activeElement;
    if (active && ["INPUT", "TEXTAREA", "SELECT"].includes(active.tagName))
      return;
    if (e.key === "Escape") {
      e.preventDefault();
      await api("cancel");
      return;
    }
    if (e.key === "Enter" || e.key === " ") {
      const onButton =
        active?.tagName === "BUTTON" ||
        !!e.target?.closest?.("#toolbar, footer, #capture-error");
      if (onButton) return;
      e.preventDefault();
      await fullScreen();
    } else if (["Delete", "Backspace"].includes(e.key)) {
      e.preventDefault();
      strokes.pop();
      render();
    } else if (
      e.code.startsWith("Numpad") &&
      ["Numpad7", "Numpad9", "Numpad3", "Numpad1"].includes(e.code)
    ) {
      e.preventDefault();
      const sel = rectangle();
      const r = bounds(sel.points, base.width, base.height);
      let left = r.x;
      let top = r.y;
      let right = r.x + r.width;
      let bottom = r.y + r.height;
      if (e.code === "Numpad7") {
        left = pointer.x;
        top = pointer.y;
      }
      if (e.code === "Numpad9") {
        right = pointer.x;
        top = pointer.y;
      }
      if (e.code === "Numpad3") {
        right = pointer.x;
        bottom = pointer.y;
      }
      if (e.code === "Numpad1") {
        left = pointer.x;
        bottom = pointer.y;
      }
      sel.points = [
        { x: left, y: top },
        { x: right, y: bottom },
      ];
      render();
    } else if (e.key.startsWith("Arrow")) {
      e.preventDefault();
      const sel = rectangle();
      const r = bounds(sel.points, base.width, base.height);
      const step = e.shiftKey ? 10 : 1;
      const w = Math.max(
        1,
        Math.min(
          base.width - r.x,
          r.width +
            (e.key === "ArrowRight" ? step : e.key === "ArrowLeft" ? -step : 0),
        ),
      );
      const h = Math.max(
        1,
        Math.min(
          base.height - r.y,
          r.height +
            (e.key === "ArrowDown" ? step : e.key === "ArrowUp" ? -step : 0),
        ),
      );
      sel.points = [
        { x: r.x, y: r.y },
        { x: r.x + w, y: r.y + h },
      ];
      render();
      read(pointer);
    }
  }),
);

$("#free").onclick = () => {
  tool = "free";
  render();
};
$("#rectangle").onclick = () => {
  tool = "rect";
  render();
};
$("#undo").onclick = () => {
  strokes.pop();
  render();
};
$("#all").onclick = safe(fullScreen);
$("#cancel").onclick = safe(() => api("cancel"));
$("#capture-error-close").onclick = safe(() => api("cancel"));
$("#copy-color").onclick = safe(copyColor);
$("#smooth").onchange = () => {
  smooth = $("#smooth").checked;
  render();
};
window.addEventListener("resize", () => {
  if (source) fit();
});

function triggerEntryPulse() {
  document.querySelectorAll(".capture-flash").forEach((node) => node.remove());
  if (reducedMotion()) return;
  const flash = document.createElement("div");
  flash.className = "capture-flash";
  flash.setAttribute("aria-hidden", "true");
  flash.addEventListener("animationend", () => flash.remove(), { once: true });
  document.body.append(flash);
}

function scheduleEdgeStars() {
  if (starsCreated || reducedMotion()) return;
  starsCreated = true;
  const sparkles = $("#capture-sparkles");
  if (!sparkles) return;
  const create = () => {
    if (reducedMotion()) return;
    const frag = document.createDocumentFragment();
    for (let i = 0; i < 24; i++) {
      const star = document.createElement("span");
      star.className = "capture-star";
      const side = i % 4;
      const along = ((i * 19.7 + 5) % 92) + 4;
      const depth = ((i * 3.1 + 1.5) % 6.5) + 0.8; // strictly within 8% edge band
      if (side === 0) {
        star.style.left = along + "%";
        star.style.top = depth + "%";
      } else if (side === 1) {
        star.style.left = along + "%";
        star.style.top = 100 - depth + "%";
      } else if (side === 2) {
        star.style.left = depth + "%";
        star.style.top = along + "%";
      } else {
        star.style.left = 100 - depth + "%";
        star.style.top = along + "%";
      }
      star.style.setProperty("--delay", -i * 0.43 + "s");
      star.style.setProperty("--size", 6 + (i % 4) * 2.5 + "px");
      star.style.setProperty("--duration", 3 + (i % 4) * 0.6 + "s");
      frag.append(star);
    }
    sparkles.append(frag);
  };
  if (typeof window.requestIdleCallback === "function") {
    window.requestIdleCallback(create, { timeout: 250 });
  } else {
    window.requestAnimationFrame(create);
  }
}

function applyConfigDefaults(cfg) {
  const safeCfg = cfg || {};
  $("#format").value = safeCfg.format || "png";
  $("#border").checked = !!safeCfg.border;
  tool = safeCfg.default_tool === "rect" ? "rect" : "free";
  const color =
    typeof safeCfg.default_color === "string" &&
    /^#[0-9a-fA-F]{6}$/.test(safeCfg.default_color)
      ? safeCfg.default_color
      : "#ff4278";
  $("#ink").value = color;
  const parsedWidth = Number(safeCfg.default_width);
  width =
    Number.isInteger(parsedWidth) && parsedWidth >= 1 && parsedWidth <= 80
      ? parsedWidth
      : 3;
  $("#ink-size").textContent = width + " px";
  smooth = safeCfg.smooth !== undefined ? !!safeCfg.smooth : true;
  $("#smooth").checked = smooth;
  $("#bgr").checked = !!safeCfg.bgr;
}

function showLoadError() {
  document.body.classList.remove("capture-ready");
  const errBox = $("#capture-error");
  if (errBox) {
    errBox.hidden = false;
    $("#capture-error-close")?.focus();
  }
  notice("");
  announceAlert("Não foi possível abrir a captura. Feche e tente de novo.");
}

async function openCapture(identity) {
  const generation = ++activeOpenGeneration;
  const timings = { start: performance.now() };
  window.piaCapture.ready = false;
  window.piaCapture.currentId = identity || null;
  window.piaCapture.timings = timings;

  selection = null;
  strokes = [];
  drawing = null;
  cancelledGesture = false;
  document.body.classList.remove("capture-ready");
  const errBox = $("#capture-error");
  if (errBox) errBox.hidden = true;

  clearTimeout(loadingTimer);
  notice("");
  loadingTimer = setTimeout(() => {
    if (generation === activeOpenGeneration && !window.piaCapture.ready) {
      notice("Carregando captura…");
    }
  }, 200);

  try {
    if (!sessionReady) {
      await session();
      sessionReady = true;
    }
    record = await api("image", { id: identity });
    if (generation !== activeOpenGeneration) return;
    timings.imageFetched = performance.now();

    source = new Image();
    source.src = record.data;
    await source.decode();
    if (generation !== activeOpenGeneration) return;
    timings.decoded = performance.now();

    base.width = source.naturalWidth;
    base.height = source.naturalHeight;
    bc.drawImage(source, 0, 0);

    $("#title").value = record.title || "";
    $("#comment").value = record.comment || "";
    applyConfigDefaults(record.config);
    fit();

    clearTimeout(loadingTimer);
    window.piaCapture.ready = true;
    timings.ready = performance.now();

    document.body.classList.add("capture-ready");
    triggerEntryPulse();
    window.focus();
    canvas.focus({ preventScroll: true });
    notice("Selecione a região ou pressione Enter para capturar tudo.");
    announceStatus(
      "Captura congelada aberta. Arraste para recortar, Enter captura a tela inteira, Esc cancela.",
    );
    scheduleEdgeStars();

    if (record.mode === "window") {
      await fullScreen();
      timings.finalized = performance.now();
    }
  } catch {
    if (generation !== activeOpenGeneration) return;
    clearTimeout(loadingTimer);
    showLoadError();
  }
}

window.piaCapture = {
  fullScreen,
  open: openCapture,
  ready: false,
  currentId: null,
  timings: {},
};

const initialId = new URLSearchParams(location.search).get("id");
if (initialId) {
  openCapture(initialId);
}
