export const MUSIC_PROVIDER_LABELS = {
  local: "Criador de músicas local (ACE-Step)",
  gemini: "Gemini (Lyria)",
  // RN24: o id interno continua suno_mcp; o usuário só vê "Suno".
  suno_mcp: "Suno",
};

// RN06/RN22 (T7, arquitetura servidor): sem URL, comando, token nem OAuth
// manual no PC. O /music/select recebe só {provider, gemini_model}; o
// suno_account_id NUNCA vai no select, só no /music/generate (T8, dba90f4).
export function selectionToMusicDraft(selection = {}) {
  const sel = selection && typeof selection === "object" ? selection : {};
  return { provider: sel.provider || "local" };
}

export function musicDraftSnapshot(draft = {}) {
  return JSON.stringify({ provider: draft?.provider || "local" });
}

/** Corpo do POST /music/select: só provider e gemini_model. */
export function buildMusicSelectPayload(draft = {}) {
  const payload = { provider: draft?.provider || "local" };
  if (typeof draft?.gemini_model === "string" && draft.gemini_model.trim()) {
    payload.gemini_model = draft.gemini_model.trim();
  }
  return payload;
}

/** Item suno_mcp do catálogo (/music/providers) ou null. */
export function findSunoProvider(catalog) {
  const list = Array.isArray(catalog?.providers) ? catalog.providers : [];
  return list.find((item) => item?.id === "suno_mcp") || null;
}

/** RN04: aviso quando o provedor salvo é Suno, mas o catálogo diz indisponível. */
export function shouldWarnSunoOpensInLocal(
  selection = {},
  activeProvider = {},
  draftProvider = "",
) {
  const provider = draftProvider || selection?.provider;
  if (provider !== "suno_mcp") return false;
  // Não recalcular a regra: usar o available do catálogo.
  return activeProvider?.available !== true;
}

// ---------------------------------------------------------------------------
// Seletor dinâmico do app de Música (Panel.jsx)
// Contrato (seção 3 do plano): GET /api/pia/music/providers e appApi("music", "providers")
// -> { providers: [{ id, label, available, ... }], selection: { provider } }
// `available` e `settings_route` do suno_mcp vêm do backend (T1, suno_status()):
// available = endpoint && credencial. O frontend não recalcula essa regra.
// ---------------------------------------------------------------------------

export const MUSIC_PROVIDER_SHORT_LABELS = {
  local: "Local",
  gemini: "Gemini",
  suno_mcp: "Suno",
  flow: "Flow Music",
};

export const SUNO_SETTINGS_ROUTE = { view: "settings", section: "Apps/music" };

// Disparado por Configurações → Música (T7) depois de conectar/desconectar o Suno.
export const MUSIC_PROVIDERS_UPDATED_EVENT = "pia:music-providers-updated";

/** Avisa o app de Música (Panel) para recarregar o catálogo, sem reiniciar. */
export function notifyMusicProvidersUpdated() {
  if (
    typeof window === "undefined" ||
    typeof window.dispatchEvent !== "function"
  ) {
    return;
  }
  window.dispatchEvent(new CustomEvent(MUSIC_PROVIDERS_UPDATED_EVENT));
}

/**
 * Executa uma mutação do catálogo (salvar, conectar, desconectar) e dispara
 * o evento no `finally` se `markMutated()` tiver sido chamado — inclusive
 * quando um passo posterior falha (select ok + oauth/start falhou, ou
 * callback ok + loadCatalog falhou).
 */
export async function runWithMusicProvidersUpdate(action) {
  let mutated = false;
  try {
    return await action(() => {
      mutated = true;
    });
  } finally {
    if (mutated) notifyMusicProvidersUpdated();
  }
}

export const SUNO_HINT_TEXT = "Conecte o Suno em Configurações → Música";

export const SUNO_REUSE_WARNING =
  "O Suno não está conectado. O prompt foi carregado no gerador Local; conecte o Suno em Configurações → Música para usá-lo.";

export const SUNO_UNAVAILABLE_WARNING =
  "O Suno deixou de estar disponível. O gerador voltou para Local.";

export const SUNO_DURATION_HINT =
  "No Suno a duração é indicativa; a faixa pode sair com outro tamanho.";

export const SUNO_CANCEL_WARNING =
  "Cancelar para a espera, mas não interrompe a geração já enviada ao Suno; pode consumir créditos.";

const GENERATOR_OPTIONS = [
  { value: "local", label: "Local · ACE-Step" },
  { value: "gemini", label: "Gemini · Lyria API" },
  { value: "suno_mcp", label: "Suno" },
  { value: "flow", label: "Google Flow Music · abrir interface oficial" },
];

const REUSABLE_PROVIDERS = ["local", "gemini", "suno_mcp"];

function catalogProviders(catalog) {
  return Array.isArray(catalog?.providers) ? catalog.providers : [];
}

function findCatalogProvider(catalog, id) {
  return catalogProviders(catalog).find((item) => item?.id === id) || null;
}

/**
 * Local, Gemini e Flow seguem sempre disponíveis no seletor (comportamento
 * atual). O Suno só conta quando o catálogo diz `available === true` (RN01).
 */
export function isGeneratorAvailable(id, catalog) {
  if (id === "suno_mcp") {
    // T1 sempre manda id suno_mcp; o fallback do host api.suno.com fica
    // em findSunoProvider, alinhado ao seletor e ao painel de settings.
    return findSunoProvider(catalog)?.available === true;
  }
  return GENERATOR_OPTIONS.some((option) => option.value === id);
}

/**
 * Opções do Select "Gerador". Suno escondido (não desabilitado) se
 * indisponível (RN02/RN03). `keep` mantém um provedor conhecido na lista mesmo
 * indisponível (geração em andamento ou catálogo ainda carregando), para o
 * Select não ficar em branco.
 */
export function buildGeneratorOptions(catalog, keep = null) {
  return GENERATOR_OPTIONS.filter(
    (option) =>
      option.value === keep || isGeneratorAvailable(option.value, catalog),
  ).map((option) => ({ ...option }));
}

/** Provedor salvo (MUSIC_PROVIDER) se disponível, senão "local" (RN04). */
export function resolveInitialProvider(catalog) {
  const saved = catalog?.selection?.provider;
  // MUSIC_PROVIDER só admite geradores reais; "flow" não é salvo no backend.
  return REUSABLE_PROVIDERS.includes(saved) &&
    isGeneratorAvailable(saved, catalog)
    ? saved
    : "local";
}

/**
 * Depois de recarregar o catálogo (foco/visibilidade): se o provedor atual
 * deixou de estar disponível e não há geração em andamento, volta para Local.
 */
export function resolveProviderAfterRefresh(current, catalog, busy = false) {
  // Falha passageira do catálogo (sem providers) não tira o usuário do Suno.
  if (!Array.isArray(catalog?.providers)) {
    return { provider: current, warning: null };
  }
  if (busy || isGeneratorAvailable(current, catalog)) {
    return { provider: current, warning: null };
  }
  return {
    provider: "local",
    warning: current === "suno_mcp" ? SUNO_UNAVAILABLE_WARNING : null,
  };
}

/**
 * "Reutilizar prompt" de uma faixa do Histórico (RN10). Sem catálogo ainda
 * (carregando ou erro), uma faixa Suno fica pendente em vez de ser tratada
 * como "Suno não conectado": `pending: true` pede reavaliar quando o catálogo
 * chegar.
 */
export function resolveReuseProvider(item, catalog) {
  const provider = item?.provider;
  if (!REUSABLE_PROVIDERS.includes(provider)) {
    return { provider: "local", warning: null };
  }
  if (provider === "suno_mcp" && !Array.isArray(catalog?.providers)) {
    return { provider, warning: null, pending: true };
  }
  if (isGeneratorAvailable(provider, catalog)) {
    return { provider, warning: null };
  }
  return {
    provider: "local",
    warning: provider === "suno_mcp" ? SUNO_REUSE_WARNING : null,
  };
}

/**
 * Dica "Conecte o Suno…" quando o catálogo carregou e o Suno não está
 * disponível. Sem catálogo (erro de rede), não afirma nada sobre o Suno.
 */
export function shouldShowSunoHint(catalog) {
  if (!Array.isArray(catalog?.providers)) return false;
  return !isGeneratorAvailable("suno_mcp", catalog);
}

/** Rota do atalho para Configurações → Música. */
export function sunoSettingsRoute(catalog) {
  const route = findCatalogProvider(catalog, "suno_mcp")?.settings_route;
  return route?.view === "settings" && route.section
    ? { view: route.view, section: route.section }
    : { ...SUNO_SETTINGS_ROUTE };
}

/** Rótulo curto para o Histórico: "Local", "Gemini", "Suno"; fallback para o id. */
export function providerLabel(id) {
  if (!id) return "";
  return MUSIC_PROVIDER_SHORT_LABELS[id] || String(id);
}

/** Dicas extras abaixo do formulário conforme o gerador selecionado. */
export function generatorHints(provider) {
  return provider === "suno_mcp"
    ? [SUNO_DURATION_HINT, SUNO_CANCEL_WARNING]
    : [];
}

/** Texto do lote parcial, igual ao da notificação: "1 de 3 músicas prontas". */
export function partialBatchLabel(completed, total) {
  const done = Number(completed);
  const all = Number(total);
  if (!Number.isInteger(done) || !Number.isInteger(all) || all < 1) return "";
  return `${done} de ${all} ${all === 1 ? "música pronta" : "músicas prontas"}`;
}

// Label da barra quando o job termina com erro no meio do lote.
// Prefere o `ready_text` do backend (T4) e cai no partialBatchLabel sem ele.
// Sem nenhuma faixa pronta, mostra só "Geração interrompida".
export const INTERRUPTED_LABEL = "Geração interrompida";
export function interruptedProgressLabel(event) {
  const completed = Number(event?.completed);
  if (event?.completed != null && completed === 0) return INTERRUPTED_LABEL;
  const ready =
    typeof event?.ready_text === "string" ? event.ready_text.trim() : "";
  const detail =
    ready || (completed > 0 ? partialBatchLabel(completed, event?.total) : "");
  return detail ? `${INTERRUPTED_LABEL} · ${detail}` : INTERRUPTED_LABEL;
}

// Estado final da barra quando o job termina com evento `error`.
// Com pelo menos uma faixa pronta, ou se o backend já marcou `interrupted`,
// a geração é tratada como interrompida (amarelo); sem nada pronto, é erro (vermelho).
export function finalStateForError(prev, event) {
  const completed = Number(event?.completed);
  if (completed >= 1 || prev?.state === "interrupted") return "interrupted";
  return "error";
}
