// Helpers puros da aba Histórico do app de Música (RN25/CA24, v3.2).
// API local da T6: GET /music/history, DELETE /music/history/<id>,
// POST /music/history/<id>/tracks/<n>/redownload (proposta-api-T7.md,
// "HISTÓRICO v3.1: fechamento" e "v3.2").

import { partialBatchLabel } from "./music-helpers.js";
import {
  PIA_SERVER_SETTINGS_ROUTE,
  resolveSunoAccountSelection,
} from "./music-suno-helpers.js";
import { resolveReuseProvider } from "./music-helpers.js";

export const HISTORY_PAGE_SIZE = 100;
// Textos do PO (RN25/RN16)
export const HISTORY_UNAVAILABLE_TEXT =
  "Histórico da conta indisponível agora; mostrando só as músicas deste computador.";
export const HISTORY_OTHER_DEVICE_LOCAL_TEXT = "Áudio no computador que gerou";
export const HISTORY_REDOWNLOAD_LABEL = "Baixar novamente";
export const HISTORY_REUSE_LABEL = "Reutilizar prompt";
export const HISTORY_LOAD_MORE_LABEL = "Carregar mais";
export const HISTORY_EXTRA_LABEL = "Suno · extra";
export const HISTORY_STATE_DONE = "Concluída";
export const HISTORY_STATE_INTERRUPTED = "Interrompida";
export const HISTORY_STATE_CANCELLED = "Cancelada";
// Anexo A do requisitos-PO.md (aprovados pelo PO)
export const HISTORY_STATE_RUNNING = "Em andamento";
export const HISTORY_EMPTY_TEXT = "Nenhuma música gerada ainda.";
export const HISTORY_DELETE_CONFIRM =
  "Excluir esta geração do histórico? O prompt, a letra e os links serão apagados da PIA Server e o item some em todos os computadores da conta. Os arquivos de música deste computador continuam na pasta Música/PIA. Não dá para desfazer.";

const ACTIVE_STATES = new Set(["queued", "pending", "running"]);
const DONE_STATES = new Set(["done", "completed", "complete", "succeeded"]);
const CANCELLED_STATES = new Set(["cancelled", "canceled"]);

/** URL da página: GET /music/history?cursor=&limit=100. */
export function historyPath(cursor = null, limit = HISTORY_PAGE_SIZE) {
  const params = new URLSearchParams();
  if (cursor) params.set("cursor", String(cursor));
  params.set("limit", String(limit));
  return "/music/history?" + params.toString();
}

function asTrack(track, index) {
  if (!track || typeof track !== "object") return null;
  const n = Number.isInteger(track.n) ? track.n : index + 1;
  return { ...track, n };
}

/** Item do histórico com campos garantidos (defensivo). */
export function normalizeHistoryItem(item) {
  if (!item || typeof item !== "object" || item.id == null) return null;
  const tracks = (Array.isArray(item.tracks) ? item.tracks : [])
    .map(asTrack)
    .filter(Boolean)
    .sort((a, b) => a.n - b.n);
  return {
    ...item,
    id: String(item.id),
    tracks,
    params: item.params && typeof item.params === "object" ? item.params : {},
  };
}

/** Resposta do GET -> {items, nextCursor, serverUnavailable, serverReason}. */
export function normalizeHistoryPage(response) {
  const items = (Array.isArray(response?.items) ? response.items : [])
    .map(normalizeHistoryItem)
    .filter(Boolean);
  return {
    items,
    nextCursor:
      typeof response?.next_cursor === "string" && response.next_cursor
        ? response.next_cursor
        : null,
    serverUnavailable: response?.server_unavailable === true,
    serverReason: response?.server_reason || null,
  };
}

export const isActiveHistoryItem = (item) =>
  ACTIVE_STATES.has(String(item?.state || "").toLowerCase());

/**
 * Junta páginas sem duplicar (o id é o item.id). A ordem é a do servidor
 * (ativos primeiro, depois do mais novo ao mais antigo); um item repetido
 * fica na posição antiga com os dados novos.
 */
export function mergeHistoryPages(current = [], incoming = []) {
  const byId = new Map();
  const order = [];
  for (const item of [...current, ...incoming]) {
    if (!item || item.id == null) continue;
    const id = String(item.id);
    if (!byId.has(id)) order.push(id);
    byId.set(id, item);
  }
  const merged = order.map((id) => byId.get(id));
  // Ativos sempre no topo (RN25), estável no resto.
  return [
    ...merged.filter(isActiveHistoryItem),
    ...merged.filter((item) => !isActiveHistoryItem(item)),
  ];
}

/** Página nova: a 1ª substitui; "Carregar mais" acrescenta. */
export function applyHistoryPage(state, response, { append = false } = {}) {
  const page = normalizeHistoryPage(response);
  return {
    ...page,
    items: append
      ? mergeHistoryPages(state?.items || [], page.items)
      : mergeHistoryPages([], page.items),
  };
}

/**
 * Faixa atualizada vinda do job de redownload. Aceita o evento `track`
 * ({track}, {item} no formato de faixa do histórico, ou {item} no formato da
 * biblioteca: `file` string e `audio_url`) e o `done` da T6
 * ({result: {track, history_id}}).
 */
export function trackFromRedownloadEvent(event) {
  const raw = event?.track || event?.item || event?.result?.track || null;
  if (!raw || typeof raw !== "object") return null;
  if (raw.availability || raw.file?.audio_url || raw.n != null) {
    const out = { ...raw };
    if (out.file && typeof out.file === "object" && !out.availability)
      out.availability = "local_file";
    return out;
  }
  if (typeof raw.file === "string" && raw.audio_url)
    return { availability: "local_file", file: raw };
  return null;
}

/** Troca só a faixa `n` do item `itemId` (resto intacto). */
export function replaceHistoryTrack(items = [], itemId, n, updated) {
  if (!updated) return items;
  return items.map((item) => {
    if (String(item.id) !== String(itemId)) return item;
    return {
      ...item,
      tracks: item.tracks.map((track) =>
        track.n === n ? { ...track, ...updated, n } : track,
      ),
    };
  });
}

export function removeHistoryItem(items = [], itemId) {
  return items.filter((item) => String(item.id) !== String(itemId));
}

/**
 * Ação da faixa conforme `availability` (RN25):
 * - local_file + file: {kind:"local", url, file} (tocar e abrir pasta);
 * - redownload: {kind:"redownload"} ("Baixar novamente", qualquer PC);
 * - other_device_local: {kind:"text", text:"Áudio no computador que gerou"};
 * - desconhecido (inclusive o other_device_suno removido) ou sem arquivo:
 *   {kind:"none"}, sem ação e sem quebrar a tela.
 * Offline (`serverUnavailable`), o redownload não é oferecido.
 */
export function historyTrackAction(track, { serverUnavailable = false } = {}) {
  const availability = track?.availability;
  if (availability === "local_file") {
    const file = track?.file;
    const url = file && typeof file === "object" ? file.audio_url : null;
    return url ? { kind: "local", url, file } : { kind: "none" };
  }
  if (availability === "redownload")
    return serverUnavailable ? { kind: "none" } : { kind: "redownload" };
  if (availability === "other_device_local")
    return { kind: "text", text: HISTORY_OTHER_DEVICE_LOCAL_TEXT };
  return { kind: "none" };
}

/** Caminho do arquivo para o reveal-file (abrir pasta). */
export function historyFilePath(file, folder = "") {
  if (!file || typeof file !== "object") return null;
  if (typeof file.path === "string" && file.path) return file.path;
  if (typeof file.file !== "string" || !file.file) return null;
  const base = String(folder || "").replace(/[\\/]+$/, "");
  return base ? `${base}/${file.file}` : null;
}

/** Rótulo da faixa: "Suno · extra" quando extra; senão o label do backend. */
export function historyTrackLabel(track) {
  if (track?.extra === true) return HISTORY_EXTRA_LABEL;
  return typeof track?.label === "string" ? track.label : "";
}

export function historyTrackTitle(track) {
  const title = typeof track?.title === "string" ? track.title.trim() : "";
  return title || "Versão " + (Number.isInteger(track?.n) ? track.n : 1);
}

const GENERATOR_LABELS = {
  suno_mcp: "Suno",
  suno: "Suno",
  local: "Local · ACE-Step",
  gemini: "Gemini",
};

/** Gerador do item (RN25): "Suno", "Local · ACE-Step", "Gemini"… */
export function historyGeneratorLabel(item) {
  const provider = item?.provider || item?.params?.provider;
  if (provider && GENERATOR_LABELS[provider]) return GENERATOR_LABELS[provider];
  if (item?.source === "suno") return "Suno";
  return provider ? String(provider) : "";
}

/** Faixas pedidas prontas (sem extras). */
function readyRequested(item) {
  return item.tracks.filter((track) => track.extra !== true).length;
}

/**
 * Estado do item (RN25): "Concluída", "k de N músicas prontas",
 * "Interrompida", "Cancelada"; em andamento usa o progresso atual.
 */
export function historyStateLabel(item, liveProgress = null) {
  const state = String(item?.state || "").toLowerCase();
  if (ACTIVE_STATES.has(state)) {
    const live =
      liveProgress &&
      (typeof liveProgress.label === "string" ? liveProgress.label : "");
    if (live) return live;
    const done = Number.isInteger(item?.completed)
      ? item.completed
      : readyRequested(item);
    const total = Number.isInteger(item?.count) ? item.count : item?.total;
    const partial = partialBatchLabel(done, total);
    return partial
      ? `${HISTORY_STATE_RUNNING} · ${partial}`
      : HISTORY_STATE_RUNNING;
  }
  if (DONE_STATES.has(state)) return HISTORY_STATE_DONE;
  if (CANCELLED_STATES.has(state)) return HISTORY_STATE_CANCELLED;
  if (["interrupted", "error", "failed"].includes(state)) {
    const done = readyRequested(item);
    const total = Number(item?.count);
    if (done > 0 && Number.isInteger(total) && total > done)
      return partialBatchLabel(done, total);
    return HISTORY_STATE_INTERRUPTED;
  }
  return state ? String(item.state) : "";
}

export function historyStateColor(item) {
  const state = String(item?.state || "").toLowerCase();
  if (ACTIVE_STATES.has(state)) return "blue";
  if (DONE_STATES.has(state)) return "teal";
  if (CANCELLED_STATES.has(state)) return "gray";
  return "yellow";
}

/** Data/hora local (pt-BR) do created_at (ISO ou epoch s/ms). */
export function historyDateLabel(value) {
  if (value == null || value === "") return "";
  let date;
  if (typeof value === "number")
    date = new Date(value < 1e12 ? value * 1000 : value);
  else date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
  });
}

/**
 * Offline/sem pareamento (RN25): aviso do PO e, se não pareado, o atalho
 * para Configurações → PIA Server. Sem indisponibilidade, null.
 */
export function historyNotice(page) {
  if (!page?.serverUnavailable) return null;
  return {
    text: HISTORY_UNAVAILABLE_TEXT,
    route:
      page.serverReason === "pia_server_unpaired"
        ? { ...PIA_SERVER_SETTINGS_ROUTE }
        : null,
  };
}

/**
 * Itens exibidos: offline, só o que é deste PC e só as faixas com arquivo
 * local (a API já manda só os locais; isto é defesa extra).
 */
export function visibleHistoryItems(page) {
  const items = Array.isArray(page?.items) ? page.items : [];
  if (!page?.serverUnavailable) return items;
  return items
    .filter((item) => item.this_device !== false)
    .map((item) => ({
      ...item,
      tracks: item.tracks.filter(
        (track) => track.availability === "local_file",
      ),
    }));
}

const clamp = (value, min, max, fallback) => {
  const number = Number(value);
  return Number.isFinite(number)
    ? Math.max(min, Math.min(max, Math.round(number)))
    : fallback;
};

/**
 * "Reutilizar prompt" (RN18/RN25/CA21): preenche o Gerador a partir do
 * `params` (mesmas chaves do body do /music/generate). Provedor pela regra
 * de sempre (Suno se disponível, senão Local com aviso). Conta Suno: só fica
 * escolhida quando a regra de 1 conta vale; com 2+ o campo fica vazio
 * (RN09); conta que não existe mais também cai na regra normal.
 */
export function reuseFromHistory(item, catalog) {
  const params =
    item?.params && typeof item.params === "object" ? item.params : {};
  const provider = params.provider || item?.provider || "local";
  const reused = resolveReuseProvider({ provider }, catalog);
  let sunoAccountId = null;
  if (reused.provider === "suno_mcp" && !reused.pending) {
    const selection = resolveSunoAccountSelection(catalog, null);
    sunoAccountId = selection.mode === "single" ? selection.value : null;
  }
  const lyrics =
    typeof params.lyrics === "string"
      ? params.lyrics
      : typeof item?.lyrics === "string"
        ? item.lyrics
        : "";
  return {
    prompt:
      typeof params.prompt === "string" && params.prompt
        ? params.prompt
        : item?.prompt || "",
    lyrics,
    provider: reused.provider,
    warning: reused.warning || null,
    pending: reused.pending === true,
    duration: clamp(params.duration ?? item?.duration, 10, 180, 30),
    count: clamp(params.count ?? item?.count, 1, 10, 1),
    sunoAccountId,
  };
}

/**
 * Histórico a partir da biblioteca local (/apps/music/library) quando a
 * rota /music/history ainda não existe (antes da T6) ou falha sem resposta:
 * agrupa por lote e marca as faixas como local_file.
 */
export function historyFromLibrary(items = []) {
  const groups = new Map();
  for (const file of Array.isArray(items) ? items : []) {
    if (!file || typeof file !== "object" || !file.file) continue;
    const key = file.batch || file.file;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(file);
  }
  return [...groups.entries()].map(([id, files]) => {
    files.sort((a, b) => (a.variant || 0) - (b.variant || 0));
    const first = files[0];
    return {
      id: String(id),
      job_id: null,
      provider: first.provider || "local",
      source: first.provider === "suno_mcp" ? "suno" : "local",
      suno_account: null,
      prompt: first.prompt || "",
      lyrics: first.lyrics || "",
      params: {
        provider: first.provider || "local",
        prompt: first.prompt || "",
        lyrics: first.lyrics || "",
        duration: first.requested_duration,
        count: files.length,
      },
      state: "done",
      code: null,
      count: files.length,
      created_at: first.modified ?? null,
      this_device: true,
      tracks: files.map((file, index) => ({
        n: index + 1,
        title: file.title,
        extra: file.extra === true,
        label: file.label,
        availability: "local_file",
        file,
      })),
    };
  });
}
