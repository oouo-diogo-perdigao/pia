export const MUSIC_PROVIDER_LABELS = {
  local: "Criador de músicas local (ACE-Step)",
  gemini: "Gemini (Lyria)",
  suno_mcp: "Suno (MCP)",
};

export function selectionToMusicDraft(selection = {}) {
  const sel = selection && typeof selection === "object" ? selection : {};
  return {
    provider: sel.provider || "local",
    suno_mcp_url: sel.suno_mcp_url || "",
    suno_mcp_command: sel.suno_mcp_command || "",
    suno_mcp_token: "",
    suno_mcp_auth_type: sel.suno_mcp_auth_type || "none",
    suno_mcp_client_id: sel.suno_mcp_oauth_client_id || "",
    suno_mcp_client_secret: "",
    suno_mcp_auth_url: sel.suno_mcp_oauth_auth_url || "",
    suno_mcp_token_url: sel.suno_mcp_oauth_token_url || "",
    suno_mcp_scopes: sel.suno_mcp_oauth_scopes || "",
  };
}

export function musicDraftSnapshot(draft = {}) {
  return JSON.stringify({
    provider: draft.provider || "local",
    suno_mcp_url: String(draft.suno_mcp_url || "").trim(),
    suno_mcp_command: String(draft.suno_mcp_command || "").trim(),
    suno_mcp_token: String(draft.suno_mcp_token || ""),
    suno_mcp_auth_type: draft.suno_mcp_auth_type || "none",
    suno_mcp_client_id: String(draft.suno_mcp_client_id || "").trim(),
    suno_mcp_client_secret: String(draft.suno_mcp_client_secret || ""),
    suno_mcp_auth_url: String(draft.suno_mcp_auth_url || "").trim(),
    suno_mcp_token_url: String(draft.suno_mcp_token_url || "").trim(),
    suno_mcp_scopes: String(draft.suno_mcp_scopes || "").trim(),
  });
}

export const MASKED_SECRET_MARKER = "••••";

/** Detecta valor mascarado (•••• do cofre ou *** ) para não reenviá-lo. */
export function isMaskedSecret(value) {
  const text = String(value || "");
  return text.includes(MASKED_SECRET_MARKER) || /\*{3,}/.test(text);
}

const SELECT_ENDPOINT_FIELDS = ["suno_mcp_url", "suno_mcp_command"];
const SELECT_OAUTH_FIELDS = [
  "suno_mcp_client_id",
  "suno_mcp_client_secret",
  "suno_mcp_auth_url",
  "suno_mcp_token_url",
  "suno_mcp_scopes",
];
const SELECT_SENSITIVE_FIELDS = [
  ...SELECT_ENDPOINT_FIELDS,
  "suno_mcp_token",
  ...SELECT_OAUTH_FIELDS,
];

export const MASKED_EDITED_FIELD_ERROR =
  "Remova o valor mascarado (••••) do campo editado antes de salvar. Substitua o trecho oculto pelo valor real.";

function wasEdited(edited, key) {
  return Boolean(edited && typeof edited === "object" && edited[key]);
}

function includeSensitiveField(
  draft,
  key,
  edited,
  { allowEmpty = false } = {},
) {
  // D5: omita qualquer URL, comando ou campo OAuth não editado — a T1 não
  // coloca •••• na URL (só remove userinfo/query/fragment), então a decisão
  // não pode depender de isMaskedSecret.
  if (!wasEdited(edited, key)) return false;
  return allowEmpty || Boolean(String(draft[key] || "").trim());
}

/** Mensagem se um campo editado ainda contém ••••; senão, string vazia. */
export function maskedEditedFieldError(draft = {}, edited = {}) {
  const hasMasked = SELECT_SENSITIVE_FIELDS.some(
    (key) => wasEdited(edited, key) && isMaskedSecret(draft[key]),
  );
  return hasMasked ? MASKED_EDITED_FIELD_ERROR : "";
}

function assertNoMaskedEditedFields(draft, edited) {
  const error = maskedEditedFieldError(draft, edited);
  if (error) throw new Error(error);
}

export function buildMusicSelectPayload(draft = {}, options = {}) {
  const edited =
    options && typeof options === "object" ? options.edited || {} : {};
  const payload = { provider: draft.provider || "local" };
  if (payload.provider !== "suno_mcp") {
    return payload;
  }
  assertNoMaskedEditedFields(draft, edited);
  for (const key of SELECT_ENDPOINT_FIELDS) {
    if (includeSensitiveField(draft, key, edited, { allowEmpty: true })) {
      payload[key] = String(draft[key] || "").trim();
    }
  }
  if (draft.suno_mcp_auth_type) {
    payload.suno_mcp_auth_type = draft.suno_mcp_auth_type;
  }
  const token = String(draft.suno_mcp_token || "").trim();
  if (token && wasEdited(edited, "suno_mcp_token")) {
    payload.suno_mcp_token = token;
  }
  for (const key of SELECT_OAUTH_FIELDS) {
    if (includeSensitiveField(draft, key, edited, { allowEmpty: false })) {
      payload[key] = String(draft[key] || "").trim();
    }
  }
  return payload;
}

export function buildSunoOAuthStartPayload(draft = {}, options = {}) {
  const edited =
    options && typeof options === "object" ? options.edited || {} : {};
  assertNoMaskedEditedFields(draft, edited);
  const payload = {};
  const map = [
    ["suno_mcp_client_id", "client_id"],
    ["suno_mcp_client_secret", "client_secret"],
    ["suno_mcp_auth_url", "auth_url"],
    ["suno_mcp_token_url", "token_url"],
    ["suno_mcp_scopes", "scopes"],
  ];
  for (const [draftKey, apiKey] of map) {
    if (!wasEdited(edited, draftKey)) continue;
    const val = String(draft[draftKey] || "").trim();
    if (val) payload[apiKey] = val;
  }
  return payload;
}

/** True se a URL for do MCP oficial (host api.suno.com), qualquer id. */
export function isSunoApiHost(url) {
  try {
    const host = new URL(String(url || "")).hostname.toLowerCase();
    return host === "api.suno.com";
  } catch {
    return false;
  }
}

/** Entrada do catálogo reconhecida como Suno (id suno_mcp ou host oficial). */
export function isSunoCatalogProvider(item) {
  if (!item || typeof item !== "object") return false;
  if (item.id === "suno_mcp") return true;
  return isSunoApiHost(item.url || item.suno_mcp_url || "");
}

export function findSunoProvider(catalog) {
  const list = Array.isArray(catalog?.providers) ? catalog.providers : [];
  return (
    list.find((item) => item?.id === "suno_mcp") ||
    list.find((item) => isSunoCatalogProvider(item)) ||
    null
  );
}

export function resolveSunoConnectionStatus(
  selection = {},
  activeProvider = {},
  pendingOAuth = null,
) {
  const oauthRaw =
    selection?.suno_mcp_oauth_connected !== undefined
      ? selection.suno_mcp_oauth_connected
      : activeProvider?.oauth_connected;
  const oauthConnected = oauthRaw === true;

  const tokenRaw =
    selection?.suno_mcp_token_configured !== undefined
      ? selection.suno_mcp_token_configured
      : activeProvider?.token_configured;
  const tokenConfigured = tokenRaw === true;

  const credentialState = String(
    activeProvider?.credential_state ?? selection?.credential_state ?? "",
  )
    .trim()
    .toLowerCase();

  // Preferir o flag do catálogo (T1) quando vier definido; só inferir da
  // URL/comando se endpoint_configured não estiver presente.
  const endpointConfigured =
    typeof activeProvider?.endpoint_configured === "boolean"
      ? activeProvider.endpoint_configured
      : Boolean(String(selection?.suno_mcp_url || "").trim()) ||
        Boolean(String(selection?.suno_mcp_command || "").trim()) ||
        isSunoApiHost(activeProvider?.url || selection?.suno_mcp_url || "");

  if (credentialState === "expired") {
    return {
      connected: false,
      mode: "expired",
      label: "Expirado — reautorizar",
      color: "orange",
    };
  }

  if (oauthConnected) {
    return {
      connected: true,
      mode: "oauth",
      label: "Conta OAuth conectada (Cofre)",
      color: "teal",
    };
  }
  // Credencial configurada (bearer ou equivalente) antes de authType oauth:
  // um auth_type:"oauth" residual de um oauth/start antigo não deve esconder
  // o bearer atrás de "OAuth pendente".
  if (tokenConfigured || credentialState === "configured") {
    return {
      connected: false,
      mode: "credential",
      label: "Credencial configurada",
      color: "blue",
    };
  }
  // oauth_pending só com o fluxo pendente ativo no painel. Sem pendingOAuth,
  // cai em needs_auth se houver endpoint (D1) — inclusive depois de
  // desconectar e com servidor desabilitado (sem endpoint → "Não configurado").
  if (pendingOAuth) {
    return {
      connected: false,
      mode: "oauth_pending",
      label: "OAuth pendente",
      color: "yellow",
    };
  }
  // needs_auth só com endpoint configurado (D1). credential_state "missing"
  // numa instalação nova (sem URL) não deve cair aqui.
  if (endpointConfigured) {
    return {
      connected: false,
      mode: "needs_auth",
      label: "URL configurada, falta autorizar",
      color: "yellow",
    };
  }
  return {
    connected: false,
    mode: "none",
    label: "Não configurado",
    color: "gray",
  };
}

/** RN04: aviso quando o provedor salvo é Suno, mas o catálogo diz indisponível. */
export function shouldWarnSunoOpensInLocal(
  selection = {},
  activeProvider = {},
  draftProvider = "",
) {
  const provider = draftProvider || selection?.provider;
  if (provider !== "suno_mcp") return false;
  // Não recalcular a regra: usar o available do catálogo (T1).
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
