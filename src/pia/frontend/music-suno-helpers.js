// Helpers puros do Suno via PIA Server (T7, requisitos v3.2).
// Contrato da API local: /workspace/devbackend/proposta-api-T7.md (T6).
// Os textos do PO (requisitos-PO.md v3.2) ficam aqui; o `hint.text` e o
// `error` do backend são só fallback.

import { findSunoProvider, partialBatchLabel } from "./music-helpers.js";

export const PIA_SERVER_SETTINGS_ROUTE = {
  view: "settings",
  section: "Connectors/pia_server",
};
export const MUSIC_SETTINGS_ROUTE = { view: "settings", section: "Apps/music" };

// --- Textos do PO ----------------------------------------------------------
// RN02 (dicas do Gerador quando o Suno está indisponível)
export const SUNO_TEXT_UNPAIRED =
  "Para usar o Suno, entre na PIA Server em Configurações → PIA Server.";
export const SUNO_TEXT_NOT_CONNECTED =
  "Conecte o Suno em Configurações → Música.";
export const SUNO_TEXT_ALL_EXPIRED =
  "A conexão com o Suno expirou. Reconecte em Configurações → Música.";
export const SUNO_TEXT_SERVER_DOWN =
  "Não foi possível falar com a PIA Server agora. O Suno volta a aparecer quando a conexão voltar.";
// RN06 (Configurações → Música)
export const SUNO_CONNECT_LABEL = "Conectar conta Suno";
export const SUNO_CONNECT_ANOTHER_LABEL = "Conectar outra conta";
export const SUNO_WAITING_TEXT = "Aguardando autorização no navegador…";
export const SUNO_TIMEOUT_TEXT = "Tempo esgotado, tente de novo";
export const SUNO_STATE_CONNECTED = "Conectada";
export const SUNO_STATE_EXPIRED = "Expirada — reconectar";
// RN08
export const SUNO_TEXT_ACCOUNT_TAKEN =
  "Esta conta Suno já está conectada a outra conta PIA. Desconecte-a lá antes de conectá-la aqui.";
// RN09
export const SUNO_ACCOUNT_FIELD_LABEL = "Conta Suno";
export const SUNO_ACCOUNT_REQUIRED_HINT = "Escolha a conta Suno";
export const SUNO_ACCOUNT_EXPIRED_SUFFIX =
  "expirada — reconecte em Configurações → Música";
// RN10
export const SUNO_TEXT_JOB_ACTIVE =
  "Já há uma geração do Suno em andamento nesta conta. Aguarde terminar.";
// RN11
export const SUNO_TEXT_UNAVAILABLE =
  "Suno indisponível no momento, tente de novo ou use outro gerador";
export const SUNO_TEXT_TIMEOUT =
  "O Suno não respondeu a tempo; a geração pode ter sido concluída lá";
export const SUNO_TEXT_CONNECTION_LOST =
  "Sem conexão com a PIA Server. A geração continua lá e as músicas serão baixadas quando a conexão voltar.";
export const SUNO_TEXT_DOWNLOAD_FAILED =
  "Não foi possível baixar a música. Tente de novo pelo Histórico.";
export const sunoExpiredText = (name) =>
  name
    ? `A autorização da conta Suno ${name} expirou. Reconecte em Configurações → Música`
    : SUNO_TEXT_ALL_EXPIRED;
export const sunoNoCreditsText = (name) =>
  name
    ? `A conta Suno ${name} está sem créditos.`
    : "A conta Suno está sem créditos.";
// RN16
export const SUNO_TEXT_TRACK_UNAVAILABLE =
  "Esta música não está mais disponível no Suno.";
// RN21 (credenciais antigas)
export const SUNO_LEGACY_QUESTION =
  "O Suno agora é conectado pela PIA Server. Remover as credenciais antigas do Suno deste computador?";
export const SUNO_LEGACY_REMOVE_LABEL = "Remover";
export const SUNO_LEGACY_DISMISS_LABEL = "Agora não";

// Textos da T7 sem redação do PO (genéricos; trocar se o UX/PO mandar outros).
export const SUNO_TEXT_CONNECTED = "Conta Suno conectada.";
export const SUNO_TEXT_CONNECT_FAILED =
  "Não foi possível conectar a conta Suno. Tente de novo.";
export const SUNO_TEXT_UNAVAILABLE_ACCOUNT = "indisponível";

// Anexo A do requisitos-PO.md (textos aprovados pelo PO, 17/11 ~22:30 BRT).
export const sunoAccountMismatchText = (name) =>
  name
    ? `A conta autorizada no Suno é diferente da conta ${name} que você pediu para reconectar. Entre no Suno com a conta ${name} e tente de novo.`
    : "A conta autorizada no Suno é diferente da que você pediu para reconectar. Entre no Suno com a conta certa e tente de novo.";
export const SUNO_TEXT_ACCOUNT_MISMATCH = sunoAccountMismatchText("");
export const SUNO_TEXT_IDENTITY_UNAVAILABLE =
  "O Suno não informou qual conta foi autorizada, então nenhuma conta foi conectada. Tente de novo.";
// Prevalece sobre o texto do backend.
export const SUNO_TEXT_CONNECT_NOT_FOUND =
  "Esta tentativa de conexão expirou. Clique em Conectar conta Suno para começar de novo.";
export const SUNO_TEXT_OAUTH_DENIED =
  "A autorização foi cancelada no Suno. Nenhuma conta foi conectada.";
export const SUNO_TEXT_OAUTH_INVALID =
  "Não foi possível concluir a autorização com o Suno. Tente conectar de novo.";
export const SUNO_TEXT_ACCOUNT_NOT_FOUND =
  "Esta conta Suno não está mais conectada. Escolha outra conta ou reconecte em Configurações → Música.";
// Só para faixa gerada localmente em outro PC; nunca bloqueia nem esconde o
// "Baixar novamente" das faixas `redownload` (RN16).
export const SUNO_TEXT_NOT_ORIGIN =
  "O áudio desta música ficou no computador que a gerou e não pode ser baixado aqui.";
export const GENERIC_ERROR_TEXT = "Algo deu errado. Tente de novo.";

// --- Codes -> texto ----------------------------------------------------------
const NO_CREDITS_CODES = new Set([
  "insufficient_credits",
  "suno_no_credits",
  "suno_insufficient_credits",
]);
const EXPIRED_CODES = new Set([
  "suno_credential_expired",
  "suno_auth",
  "refresh_failed",
]);

/**
 * Texto amigável de um `code` da API local, do evento de erro do job ou do
 * polling do connect. `accountName` entra nas mensagens da conta (RN11).
 * Code desconhecido devolve o `fallback` (texto do backend) ou o genérico.
 */
export function sunoErrorText(code, { accountName = "", fallback = "" } = {}) {
  const name = String(accountName || "").trim();
  const backend = String(fallback || "").trim();
  if (EXPIRED_CODES.has(code)) return sunoExpiredText(name);
  if (NO_CREDITS_CODES.has(code)) return sunoNoCreditsText(name);
  switch (code) {
    case "pia_server_unpaired":
      return SUNO_TEXT_UNPAIRED;
    case "pia_server_unreachable":
    case "pia_server_unsupported":
      return SUNO_TEXT_SERVER_DOWN;
    case "suno_not_connected":
      return SUNO_TEXT_NOT_CONNECTED;
    case "suno_account_required":
      return SUNO_ACCOUNT_REQUIRED_HINT;
    case "suno_account_taken":
    case "suno_account_owned_elsewhere": // nome antigo (antes do v3 final)
      return SUNO_TEXT_ACCOUNT_TAKEN;
    case "suno_account_mismatch":
      return sunoAccountMismatchText(name);
    case "suno_identity_unavailable":
      return SUNO_TEXT_IDENTITY_UNAVAILABLE;
    case "suno_connect_not_found":
      return SUNO_TEXT_CONNECT_NOT_FOUND;
    case "suno_oauth_denied":
      return SUNO_TEXT_OAUTH_DENIED;
    case "suno_oauth_invalid":
      return SUNO_TEXT_OAUTH_INVALID;
    case "suno_account_not_found":
      return SUNO_TEXT_ACCOUNT_NOT_FOUND;
    case "suno_job_active":
      return SUNO_TEXT_JOB_ACTIVE;
    case "suno_unavailable":
      return SUNO_TEXT_UNAVAILABLE;
    case "suno_timeout":
      return SUNO_TEXT_TIMEOUT;
    case "download_failed":
      return SUNO_TEXT_DOWNLOAD_FAILED;
    case "suno_track_unavailable":
      return SUNO_TEXT_TRACK_UNAVAILABLE;
    case "not_origin_device":
      return SUNO_TEXT_NOT_ORIGIN;
    default:
      return backend || GENERIC_ERROR_TEXT;
  }
}

/** Atalho de Configurações para um code (ou null). */
export function sunoErrorRoute(code) {
  if (code === "pia_server_unpaired") return { ...PIA_SERVER_SETTINGS_ROUTE };
  if (
    code === "suno_not_connected" ||
    code === "suno_account_required" ||
    code === "suno_account_not_found" ||
    EXPIRED_CODES.has(code)
  )
    return { ...MUSIC_SETTINGS_ROUTE };
  return null;
}

/** Code de um erro lançado pelo `api()` (400 {error, code}). */
export function errorCode(error) {
  return error?.code || error?.details?.code || null;
}

/**
 * {code, text, route} de um erro do `api()` ou de um evento de erro do job
 * ({error, code}). O `hint.text` do backend só entra como fallback.
 */
export function describeSunoError(error, { accountName = "" } = {}) {
  const code = errorCode(error);
  const backend =
    error?.details?.hint?.text ||
    (typeof error?.error === "string" ? error.error : "") ||
    (typeof error?.message === "string" ? error.message : "") ||
    (typeof error === "string" ? error : "");
  return {
    code,
    text: sunoErrorText(code, { accountName, fallback: backend }),
    route: sunoErrorRoute(code),
  };
}

// --- Rotas vindas do backend -------------------------------------------------
/** hint.route do backend ({view:"settings", section}) validado, ou null. */
export function normalizeSettingsRoute(route) {
  if (route && typeof route === "object") {
    return route.view === "settings" &&
      typeof route.section === "string" &&
      route.section
      ? { view: "settings", section: route.section }
      : null;
  }
  // Proposta v2 mandava string "settings/pia_server" | "settings/music".
  if (route === "settings/pia_server") return { ...PIA_SERVER_SETTINGS_ROUTE };
  if (route === "settings/music") return { ...MUSIC_SETTINGS_ROUTE };
  return null;
}

/**
 * hint do backend: objeto {text, route:{view, section}|null} (T6) ou, por
 * defesa, string (só texto). `explicitRoute` diz se o backend decidiu o
 * atalho (route presente, inclusive null = sem atalho).
 */
export function parseHint(hint) {
  if (typeof hint === "string")
    return { text: hint.trim(), route: null, explicitRoute: false };
  if (!hint || typeof hint !== "object")
    return { text: "", route: null, explicitRoute: false };
  return {
    text: typeof hint.text === "string" ? hint.text.trim() : "",
    route: normalizeSettingsRoute(hint.route),
    explicitRoute: "route" in hint,
  };
}

// --- Contas Suno (RN06/RN07/RN09) -------------------------------------------
const EXPIRED_STATES = new Set(["expired", "refresh_failed"]);
const ACTIVE_JOB_STATES = new Set(["queued", "pending", "running"]);

/** Nome de exibição da conta (RN07): name/label/email, senão o id. */
export function sunoAccountName(account) {
  if (!account || typeof account !== "object") return "";
  // Contrato real da pia-server (0a1fee6): label → name → email.
  for (const key of ["label", "name", "email", "display_name"]) {
    const value = account[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return account.id != null ? String(account.id) : "";
}

/** Contas do item suno_mcp normalizadas. */
export function sunoAccounts(catalogOrItem) {
  const item = Array.isArray(catalogOrItem?.providers)
    ? findSunoProvider(catalogOrItem)
    : catalogOrItem;
  const list = Array.isArray(item?.accounts) ? item.accounts : [];
  return list
    .filter((acc) => acc && typeof acc === "object" && acc.id != null)
    .map((acc) => {
      const state = String(acc.credential_state || "").toLowerCase();
      const expired =
        EXPIRED_STATES.has(state) ||
        EXPIRED_CODES.has(acc.reason) ||
        acc.reason === "suno_credential_expired";
      const usable =
        !expired &&
        (acc.available === true ||
          (acc.available === undefined && state === "configured"));
      return {
        id: String(acc.id),
        name: sunoAccountName(acc),
        credentialState: state,
        expired,
        usable,
        reason: acc.reason || null,
        hint: acc.hint || null,
        hintText: parseHint(acc.hint).text,
        expiresAt: acc.expires_at || null,
        activeJob:
          acc.active_job && typeof acc.active_job === "object"
            ? acc.active_job
            : null,
      };
    });
}

/** Rótulo de estado de uma conta na lista de Configurações (RN06). */
export function sunoAccountStateLabel(account) {
  return account?.expired
    ? { label: SUNO_STATE_EXPIRED, color: "orange" }
    : account?.usable
      ? { label: SUNO_STATE_CONNECTED, color: "teal" }
      : { label: "Indisponível", color: "gray" }; // credential_state unavailable
}

/**
 * Seleção da conta no Gerador (RN09).
 * - 0 válidas: mode "none".
 * - 1 válida: mode "single", automática ("Conta Suno: <nome>").
 * - 2+ válidas: mode "multiple", obrigatória, começa vazia. Só vale um
 *   `chosenId` que seja de uma conta válida; o `selected_account_id` do
 *   backend NÃO pré-seleciona (RN09: sem valor pré-selecionado).
 * Contas expiradas aparecem desabilitadas (`options` / `expired`).
 */
export function resolveSunoAccountSelection(catalogOrItem, chosenId = null) {
  const accounts = sunoAccounts(catalogOrItem);
  const valid = accounts.filter((acc) => acc.usable);
  const expired = accounts.filter((acc) => !acc.usable);
  const options = [
    ...valid.map((acc) => ({ value: acc.id, label: acc.name })),
    ...expired.map((acc) => ({
      value: acc.id,
      label: `${acc.name} · ${acc.expired ? SUNO_ACCOUNT_EXPIRED_SUFFIX : SUNO_TEXT_UNAVAILABLE_ACCOUNT}`,
      disabled: true,
    })),
  ];
  if (valid.length === 0) {
    return {
      mode: "none",
      value: null,
      account: null,
      options,
      expired,
      ready: false,
      text: "",
      hint: "",
    };
  }
  if (valid.length === 1) {
    return {
      mode: "single",
      value: valid[0].id,
      account: valid[0],
      options,
      expired,
      ready: true,
      text: `${SUNO_ACCOUNT_FIELD_LABEL}: ${valid[0].name}`,
      hint: "",
    };
  }
  const chosen =
    chosenId != null
      ? valid.find((acc) => acc.id === String(chosenId)) || null
      : null;
  return {
    mode: "multiple",
    value: chosen ? chosen.id : null,
    account: chosen,
    options,
    expired,
    ready: Boolean(chosen),
    text: "",
    hint: chosen ? "" : SUNO_ACCOUNT_REQUIRED_HINT,
  };
}

/**
 * Job ativo do Suno na conta PIA (RN10: 1 por conta PIA). Aceita as duas
 * posições do contrato: no item (`active_job`, com `suno_account_id`) ou em
 * `accounts[].active_job`. Devolve {jobId, state, thisDevice, accountId,
 * completed, total, extraReady} ou null.
 */
export function findActiveSunoJob(catalogOrItem) {
  const item = Array.isArray(catalogOrItem?.providers)
    ? findSunoProvider(catalogOrItem)
    : catalogOrItem;
  if (!item || typeof item !== "object") return null;
  const candidates = [];
  if (item.active_job && typeof item.active_job === "object")
    candidates.push({
      job: item.active_job,
      accountId: item.active_job.suno_account_id ?? null,
    });
  for (const acc of Array.isArray(item.accounts) ? item.accounts : []) {
    if (acc?.active_job && typeof acc.active_job === "object")
      candidates.push({
        job: acc.active_job,
        accountId: acc.active_job.suno_account_id ?? acc.id ?? null,
      });
  }
  for (const { job, accountId } of candidates) {
    const state = String(job.state || "running").toLowerCase();
    // job_id pode vir null (T6): o job existe e bloqueia o Gerar, mas não
    // há o que acompanhar pelo watchJob.
    if (!ACTIVE_JOB_STATES.has(state)) continue;
    return {
      jobId: job.job_id ? String(job.job_id) : null,
      state,
      thisDevice: job.this_device === true,
      accountId: accountId != null ? String(accountId) : null,
      completed: Number.isFinite(job.completed) ? job.completed : null,
      total: Number.isFinite(job.total) ? job.total : null,
      extraReady: Number.isFinite(job.extra_ready) ? job.extra_ready : 0,
    };
  }
  return null;
}

/**
 * Retomada ao abrir (RN15/CA14): com job ativo DESTE PC que ainda não está
 * sendo acompanhado, devolve o job_id para o `watchJob`; senão null.
 */
export function resolveResumeJob(catalog, followingJobId = null) {
  const job = findActiveSunoJob(catalog);
  if (!job || !job.thisDevice || !job.jobId) return null;
  return job.jobId === followingJobId ? null : job.jobId;
}

/**
 * RN10: com um job do Suno ativo na conta PIA (qualquer conta Suno), o Gerar
 * do Suno fica bloqueado, a menos que seja o job que este Panel já
 * acompanha (aí o Panel está ocupado de qualquer jeito). Texto ou "".
 */
export function activeJobBlockText(catalog, followingJobId = null) {
  const job = findActiveSunoJob(catalog);
  if (!job) return "";
  return followingJobId && job.jobId && job.jobId === String(followingJobId)
    ? ""
    : SUNO_TEXT_JOB_ACTIVE;
}

/**
 * Estado do botão Gerar: {enabled, hint}. Para o Suno exige conta válida
 * escolhida (RN09) e nenhum job ativo de outro PC (RN10).
 */
export function generateButtonState({
  provider,
  prompt = "",
  busy = false,
  selection = null,
  blockText = "",
}) {
  if (busy) return { enabled: false, hint: "" };
  const hasPrompt = Boolean(String(prompt || "").trim());
  if (provider !== "suno_mcp") return { enabled: hasPrompt, hint: "" };
  // As dicas do Suno aparecem mesmo antes de digitar o prompt (RN09/RN10).
  if (blockText) return { enabled: false, hint: blockText };
  if (!selection || selection.mode === "none")
    return { enabled: false, hint: "" };
  if (!selection.ready)
    return {
      enabled: false,
      hint: selection.hint || SUNO_ACCOUNT_REQUIRED_HINT,
    };
  return { enabled: hasPrompt, hint: "" };
}

/**
 * Corpo do appApi("music", "generate"). Com Suno, o suno_account_id vai
 * SEMPRE (inclusive com 1 conta, vindo da seleção automática): sem ele o
 * backend responde 400 suno_account_required com 2+ contas.
 */
export function buildGeneratePayload({
  prompt,
  lyrics,
  provider,
  duration,
  count,
  sunoAccountId = null,
}) {
  const body = { prompt, lyrics, provider, duration, count };
  if (provider === "suno_mcp" && sunoAccountId)
    body.suno_account_id = String(sunoAccountId);
  return body;
}

// --- RN02: dica quando o Suno não aparece no Gerador -------------------------
/**
 * {text, route} da dica do RN02 conforme o `reason` do item suno_mcp, ou null
 * se o Suno está disponível ou o catálogo não carregou.
 */
export function sunoUnavailableHint(catalog) {
  if (!Array.isArray(catalog?.providers)) return null;
  const item = findSunoProvider(catalog);
  if (item?.available === true) return null;
  const reason = item?.reason || null;
  const backendHint = parseHint(item?.hint);
  const accounts = sunoAccounts(item);
  let text;
  let route;
  if (reason === "pia_server_unpaired") {
    text = SUNO_TEXT_UNPAIRED;
    route = PIA_SERVER_SETTINGS_ROUTE;
  } else if (
    reason === "pia_server_unreachable" ||
    reason === "pia_server_unsupported"
  ) {
    text = SUNO_TEXT_SERVER_DOWN;
    route = null;
  } else if (
    EXPIRED_CODES.has(reason) ||
    (accounts.length > 0 && accounts.every((acc) => acc.expired))
  ) {
    text = SUNO_TEXT_ALL_EXPIRED;
    route = MUSIC_SETTINGS_ROUTE;
  } else if (reason === "suno_not_connected" || !item || !reason) {
    text = SUNO_TEXT_NOT_CONNECTED;
    route = MUSIC_SETTINGS_ROUTE;
  } else {
    text = backendHint.text || SUNO_TEXT_NOT_CONNECTED;
    route = MUSIC_SETTINGS_ROUTE;
  }
  // Com hint objeto do backend, vale o route dele (null = sem atalho);
  // sem hint (ou hint string), o atalho padrão do motivo.
  if (backendHint.explicitRoute)
    return {
      text,
      route: backendHint.route ? { ...backendHint.route } : null,
    };
  return { text, route: route ? { ...route } : null };
}

// --- Connect assíncrono (RN06/CA04/CA07) -------------------------------------
export const SUNO_CONNECT_POLL_MS = 3000;
export const SUNO_CONNECT_DEFAULT_EXPIRES_S = 600;
const CONNECT_TERMINAL = new Set(["connected", "failed", "expired"]);

/** auth_url só se for http(s); senão null (não abre nada). */
export function safeAuthUrl(url) {
  return typeof url === "string" && /^https?:\/\//i.test(url.trim())
    ? url.trim()
    : null;
}

/**
 * Polling do GET /music/suno/connect/<attempt_id> a cada 3 s até sair de
 * pending ou estourar o `expires_in` (s). `fetchState(attemptId)` faz a
 * chamada; `sleep(ms)`, `now()` e `isCancelled()` são injetáveis (testes).
 * Erros transitórios do polling não encerram a espera. Devolve
 * {state, account_id?, code?} ou {state:"cancelled"}.
 */
export async function pollSunoConnect({
  attemptId,
  expiresIn = SUNO_CONNECT_DEFAULT_EXPIRES_S,
  fetchState,
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  now = () => Date.now(),
  isCancelled = () => false,
  interval = SUNO_CONNECT_POLL_MS,
}) {
  const seconds =
    Number.isFinite(Number(expiresIn)) && Number(expiresIn) > 0
      ? Number(expiresIn)
      : SUNO_CONNECT_DEFAULT_EXPIRES_S;
  const deadline = now() + seconds * 1000;
  while (true) {
    if (isCancelled()) return { state: "cancelled" };
    if (now() >= deadline) return { state: "expired" };
    await sleep(interval);
    if (isCancelled()) return { state: "cancelled" };
    let result = null;
    try {
      result = await fetchState(attemptId);
    } catch (error) {
      // Attempt desconhecido/expirado no servidor encerra; rede oscilando não.
      const code = errorCode(error);
      if (code === "pia_server_unpaired" || code === "suno_connect_not_found")
        return { state: "failed", code };
      continue;
    }
    const state = String(result?.state || "pending").toLowerCase();
    if (CONNECT_TERMINAL.has(state)) {
      const out = { state };
      if (result.account_id != null) out.account_id = String(result.account_id);
      if (result.code) out.code = result.code;
      return out;
    }
  }
}

/**
 * Resultado final do connect -> {ok, text, color}. `accountName` é a conta
 * pedida no Reconectar (replace_account_id), usada no suno_account_mismatch.
 */
export function connectResultMessage(result, { accountName = "" } = {}) {
  const state = result?.state;
  if (state === "connected")
    return { ok: true, text: SUNO_TEXT_CONNECTED, color: "teal" };
  if (state === "cancelled") return { ok: false, text: "", color: "gray" };
  if (state === "expired")
    return { ok: false, text: SUNO_TIMEOUT_TEXT, color: "orange" };
  return {
    ok: false,
    text: result?.code
      ? sunoErrorText(result.code, {
          accountName,
          fallback: SUNO_TEXT_CONNECT_FAILED,
        })
      : SUNO_TEXT_CONNECT_FAILED,
    color: "red",
  };
}

/** Corpo do POST /music/suno/connect (renovar usa replace_account_id). */
export function buildConnectPayload(replaceAccountId = null) {
  return replaceAccountId
    ? { replace_account_id: String(replaceAccountId) }
    : {};
}

/** Texto da confirmação do Desconectar por conta (RN06/CA04; Anexo A). */
export function disconnectConfirmText(account) {
  const name = sunoAccountName(account);
  return `Desconectar a conta Suno${name ? " " + name : ""}? Ela não poderá mais ser usada para gerar músicas em nenhum computador desta conta PIA. As músicas já baixadas e o histórico continuam como estão.`;
}

// --- Apelido da conta (RN07) ---------------------------------------------
// Rota num lugar só. A T6 (435c4cd) usa POST .../rename {label}, porque o
// servidor local não tem do_PATCH; label inválido -> 400 invalid_label.
export const SUNO_RENAME_METHOD = "POST";
export const sunoRenamePath = (accountId) =>
  "/music/suno/accounts/" + encodeURIComponent(String(accountId)) + "/rename";

/** {path, method, data} do apelido; label vazio/igual devolve null. */
export function buildSunoRenameRequest(account, label) {
  const next = String(label || "").trim();
  if (!account?.id || !next || next === sunoAccountName(account)) return null;
  return {
    path: sunoRenamePath(account.id),
    method: SUNO_RENAME_METHOD,
    data: { label: next.slice(0, 80) },
  };
}

// --- Credenciais antigas (RN21/CA20) -----------------------------------------
/**
 * Estado das credenciais antigas: o item suno_mcp do /music/providers traz
 * legacy_credentials {present, prompt} (T8). Aceita também a resposta do
 * GET /music/suno/legacy-credentials. Sempre {present, prompt} booleanos.
 */
export function legacyCredentialsState(catalogOrResponse) {
  const source = Array.isArray(catalogOrResponse?.providers)
    ? findSunoProvider(catalogOrResponse)?.legacy_credentials
    : catalogOrResponse?.legacy_credentials || catalogOrResponse;
  return {
    present: source?.present === true,
    prompt: source?.present === true && source?.prompt === true,
  };
}

/** Pergunta no primeiro início só com present && prompt. */
export function shouldPromptLegacyCredentials(response) {
  return response?.present === true && response?.prompt === true;
}

/** Botão em Configurações → Música só se ainda houver credenciais antigas. */
export function hasLegacyCredentials(response) {
  return response?.present === true;
}

// --- Progresso (RN09/RN11/RN12) -----------------------------------------------
/** "3 de 3 músicas prontas (+1 extra)": ready_text ou calculado localmente. */
export function progressReadyText(value) {
  const ready =
    typeof value?.ready_text === "string" ? value.ready_text.trim() : "";
  if (ready) return ready;
  const base = partialBatchLabel(value?.completed, value?.total);
  if (!base) return "";
  const extra = Number(value?.extra_ready);
  return Number.isInteger(extra) && extra > 0
    ? `${base} (+${extra} extra)`
    : base;
}

/**
 * Valor exibido no WorkProgress: usa o ready_text (ou o calculado) quando o
 * backend mandar ready_text ou extras; senão mantém o label do backend.
 */
export function progressDisplay(value) {
  if (!value || typeof value !== "object") return value;
  const hasReady =
    (typeof value.ready_text === "string" && value.ready_text.trim()) ||
    Number(value.extra_ready) > 0;
  if (!hasReady) return value;
  return { ...value, label: progressReadyText(value) || value.label };
}

/** RN09/RN11: aviso de conexão perdida durante o job (sem encerrar). */
export function connectionNotice(value) {
  return value?.connection === "lost" ? SUNO_TEXT_CONNECTION_LOST : "";
}
