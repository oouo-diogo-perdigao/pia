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

export function buildMusicSelectPayload(draft = {}) {
  const payload = { provider: draft.provider || "local" };
  if (payload.provider !== "suno_mcp") {
    return payload;
  }
  payload.suno_mcp_url = String(draft.suno_mcp_url || "").trim();
  payload.suno_mcp_command = String(draft.suno_mcp_command || "").trim();
  if (draft.suno_mcp_auth_type) {
    payload.suno_mcp_auth_type = draft.suno_mcp_auth_type;
  }
  if (String(draft.suno_mcp_token || "").trim()) {
    payload.suno_mcp_token = String(draft.suno_mcp_token).trim();
  }
  const optionalOAuthFields = [
    ["suno_mcp_client_id", "suno_mcp_client_id"],
    ["suno_mcp_client_secret", "suno_mcp_client_secret"],
    ["suno_mcp_auth_url", "suno_mcp_auth_url"],
    ["suno_mcp_token_url", "suno_mcp_token_url"],
    ["suno_mcp_scopes", "suno_mcp_scopes"],
  ];
  for (const [draftKey, apiKey] of optionalOAuthFields) {
    const val = String(draft[draftKey] || "").trim();
    if (val) {
      payload[apiKey] = val;
    }
  }
  return payload;
}

export function buildSunoOAuthStartPayload(draft = {}) {
  const payload = {};
  const map = [
    ["suno_mcp_client_id", "client_id"],
    ["suno_mcp_client_secret", "client_secret"],
    ["suno_mcp_auth_url", "auth_url"],
    ["suno_mcp_token_url", "token_url"],
    ["suno_mcp_scopes", "scopes"],
  ];
  for (const [draftKey, apiKey] of map) {
    const val = String(draft[draftKey] || "").trim();
    if (val) payload[apiKey] = val;
  }
  return payload;
}

export function resolveSunoConnectionStatus(
  selection = {},
  activeProvider = {},
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

  const authType = String(
    selection?.suno_mcp_auth_type ?? activeProvider?.auth_type ?? "none",
  )
    .trim()
    .toLowerCase();

  if (oauthConnected) {
    return {
      connected: true,
      mode: "oauth",
      label: "Conta OAuth conectada (Cofre)",
      color: "teal",
    };
  }
  if (authType === "oauth") {
    return {
      connected: false,
      mode: "oauth_pending",
      label: "OAuth pendente",
      color: "yellow",
    };
  }
  if (tokenConfigured) {
    return {
      connected: false,
      mode: "token",
      label: "Token configurado",
      color: "blue",
    };
  }
  return {
    connected: false,
    mode: "none",
    label: "Não configurado",
    color: "gray",
  };
}
