export const MCP_DOCS_URL =
  "https://modelcontextprotocol.io/docs/concepts/transports";

export const MCP_TRANSPORTS = [
  { value: "stdio", label: "STDIO" },
  { value: "http", label: "HTTP com streaming" },
];

export const MCP_ACCOUNT_MODES = [
  {
    value: "distributed",
    label: "Distribuído",
    short: "Distribuído",
    description:
      "Dividir requisições entre contas (ex.: diversas contas no Suno para usar créditos de todas elas).",
  },
  {
    value: "incremental",
    label: "Incremental",
    short: "Incremental",
    description:
      "Acessar todas as contas em conjunto (ex.: diversas contas no Dropbox onde todas têm arquivos relevantes).",
  },
  {
    value: "alternating",
    label: "Alternado",
    short: "Alternado",
    description:
      "Contas separadas por contexto (ex.: Trabalho, Pessoal, Empresa X ou Y).",
  },
];

export const MCP_ACCOUNT_AUTH_TYPES = [
  { value: "bearer", label: "Token / Bearer" },
  { value: "oauth", label: "OAuth 2.0" },
  { value: "env", label: "Variável de ambiente" },
];

export const SKILL_CATEGORIES = [
  { value: "all", label: "Todas" },
  { value: "sistema", label: "Sistema" },
  { value: "voz", label: "Voz" },
  { value: "utilidades", label: "Utilidades" },
  { value: "personalizada", label: "Personalizadas" },
];

function safeList(value) {
  return Array.isArray(value) ? value : [];
}

export function normalizeTransport(value) {
  const raw = String(value || "")
    .trim()
    .toLowerCase();
  if (
    raw === "http" ||
    raw === "streamable_http" ||
    raw === "streamable-http" ||
    raw === "http_streaming" ||
    raw === "sse"
  ) {
    return "http";
  }
  return "stdio";
}

export function normalizeAccountMode(value) {
  const raw = String(value || "")
    .trim()
    .toLowerCase();
  if (["distributed", "incremental", "alternating"].includes(raw)) return raw;
  return "alternating";
}

export function objectToPairs(source) {
  if (Array.isArray(source)) {
    const mapped = source
      .map((item) => ({
        key: String(item?.key ?? item?.name ?? ""),
        value: String(item?.value ?? ""),
      }))
      .filter((item) => item.key || item.value);
    return mapped.length ? mapped : [{ key: "", value: "" }];
  }
  if (source && typeof source === "object") {
    const entries = Object.entries(source).map(([key, value]) => ({
      key: String(key),
      value: value == null ? "" : String(value),
    }));
    return entries.length ? entries : [{ key: "", value: "" }];
  }
  return [{ key: "", value: "" }];
}

export function pairsToObject(pairs) {
  const result = {};
  for (const row of safeList(pairs)) {
    const key = String(row?.key || "").trim();
    if (!key) continue;
    result[key] = String(row?.value ?? "");
  }
  return result;
}

export function createEmptyAccountDraft(index = 1) {
  return {
    id: "",
    name: index === 1 ? "Conta Principal" : `Conta ${index}`,
    context: index === 1 ? "Pessoal" : "Trabalho",
    auth_type: "bearer",
    bearer_token: "",
    bearer_env: "",
    oauth_client_id: "",
    oauth_client_secret: "",
    oauth_auth_url: "",
    oauth_token_url: "",
    oauth_scopes: "",
    oauth_connected: false,
    status: "pending",
    usage_count: 0,
    enabled: true,
  };
}

function normalizeAccountRecord(account, index = 0) {
  const oauth =
    account?.oauth && typeof account.oauth === "object" ? account.oauth : {};
  const authType = String(
    account?.auth_type ||
      (oauth.client_id || oauth.auth_url
        ? "oauth"
        : account?.bearer_token_env || account?.bearer_env
          ? "env"
          : "bearer"),
  ).toLowerCase();
  return {
    id: String(account?.id || `acc_${index + 1}`),
    name: String(account?.name || account?.label || `Conta ${index + 1}`),
    context: String(account?.context || account?.profile || "Pessoal"),
    auth_type: ["bearer", "oauth", "env"].includes(authType)
      ? authType
      : "bearer",
    bearer_token: String(
      account?.bearer_token ||
        account?.bearer_token_masked ||
        account?.token ||
        "",
    ),
    bearer_env: String(account?.bearer_token_env || account?.bearer_env || ""),
    oauth_client_id: String(account?.oauth_client_id || oauth.client_id || ""),
    oauth_client_secret: String(
      account?.oauth_client_secret || oauth.client_secret || "",
    ),
    oauth_auth_url: String(account?.oauth_auth_url || oauth.auth_url || ""),
    oauth_token_url: String(account?.oauth_token_url || oauth.token_url || ""),
    oauth_scopes: Array.isArray(oauth.scopes)
      ? oauth.scopes.join(" ")
      : String(account?.oauth_scopes || oauth.scopes || ""),
    oauth_connected: Boolean(
      account?.oauth_connected || oauth.connected || account?.connected,
    ),
    status: String(account?.status || "ready"),
    usage_count: Number(account?.usage_count || 0),
    enabled: account?.enabled !== false,
  };
}

export function createEmptyMcpDraft() {
  return {
    id: "",
    name: "",
    description: "",
    transport: "http",
    url: "",
    bearer_token_env: "",
    bearer_token: "",
    headers: [{ key: "", value: "" }],
    env_headers: [{ key: "", value: "" }],
    command: "",
    args: "",
    cwd: "",
    env: [{ key: "", value: "" }],
    account_mode: "alternating",
    active_context: "Pessoal",
    enabled: true,
    oauth_client_id: "",
    oauth_client_secret: "",
    oauth_auth_url: "",
    oauth_token_url: "",
    oauth_scopes: "",
    accounts: [],
  };
}

export function mcpServerToDraft(server) {
  if (!server || typeof server !== "object") return createEmptyMcpDraft();
  const transport = normalizeTransport(server.transport || server.type);
  const oauth =
    server.oauth && typeof server.oauth === "object" ? server.oauth : {};
  const args = Array.isArray(server.args)
    ? server.args.join(" ")
    : String(server.args || "");
  return {
    id: String(server.id || ""),
    name: String(server.name || ""),
    description: String(server.description || ""),
    transport,
    url: String(server.url || ""),
    bearer_token_env: String(server.bearer_token_env || server.token_env || ""),
    bearer_token: String(
      server.bearer_token || server.bearer_token_masked || "",
    ),
    headers: objectToPairs(server.headers),
    env_headers: objectToPairs(server.env_headers || server.envHeaders),
    command: String(server.command || ""),
    args,
    cwd: String(server.cwd || ""),
    env: objectToPairs(server.env),
    account_mode: normalizeAccountMode(server.account_mode),
    active_context: String(server.active_context || "Pessoal"),
    enabled: server.enabled !== false,
    oauth_client_id: String(server.oauth_client_id || oauth.client_id || ""),
    oauth_client_secret: String(
      server.oauth_client_secret || oauth.client_secret || "",
    ),
    oauth_auth_url: String(server.oauth_auth_url || oauth.auth_url || ""),
    oauth_token_url: String(server.oauth_token_url || oauth.token_url || ""),
    oauth_scopes: Array.isArray(oauth.scopes)
      ? oauth.scopes.join(" ")
      : String(server.oauth_scopes || oauth.scopes || ""),
    accounts: safeList(server.accounts).map((item, idx) =>
      normalizeAccountRecord(item, idx),
    ),
  };
}

export function splitCommandArgs(argsText) {
  const raw = String(argsText || "").trim();
  if (!raw) return [];
  const matches = raw.match(/(?:[^\s"']+|"[^"]*"|'[^']*')+/g) || [];
  return matches.map((token) => {
    if (
      (token.startsWith('"') && token.endsWith('"')) ||
      (token.startsWith("'") && token.endsWith("'"))
    ) {
      return token.slice(1, -1);
    }
    return token;
  });
}

export function draftToMcpPayload(draft) {
  const transport = normalizeTransport(draft?.transport);
  const accountMode = normalizeAccountMode(draft?.account_mode);
  const accounts = safeList(draft?.accounts)
    .filter((acc) => String(acc?.name || "").trim())
    .map((acc, idx) => {
      const oauth =
        acc.auth_type === "oauth"
          ? {
              client_id: String(acc.oauth_client_id || "").trim(),
              client_secret: String(acc.oauth_client_secret || "").trim(),
              auth_url: String(acc.oauth_auth_url || "").trim(),
              token_url: String(acc.oauth_token_url || "").trim(),
              scopes: String(acc.oauth_scopes || "").trim(),
            }
          : undefined;
      return {
        ...(acc.id ? { id: acc.id } : { id: `acc_${idx + 1}` }),
        name: String(acc.name || "").trim(),
        context: String(acc.context || "Pessoal").trim() || "Pessoal",
        auth_type: acc.auth_type || "bearer",
        bearer_token: String(acc.bearer_token || "").trim(),
        bearer_token_env: String(acc.bearer_env || "").trim(),
        enabled: acc.enabled !== false,
        ...(oauth ? { oauth } : {}),
      };
    });

  const base = {
    name: String(draft?.name || "").trim(),
    description: String(draft?.description || "").trim(),
    transport: transport === "http" ? "http_streaming" : "stdio",
    enabled: draft?.enabled !== false,
    account_mode: accountMode,
    active_context: String(draft?.active_context || "Pessoal").trim(),
    accounts,
  };

  if (draft?.oauth_client_id || draft?.oauth_auth_url) {
    base.oauth = {
      client_id: String(draft.oauth_client_id || "").trim(),
      client_secret: String(draft.oauth_client_secret || "").trim(),
      auth_url: String(draft.oauth_auth_url || "").trim(),
      token_url: String(draft.oauth_token_url || "").trim(),
      scopes: splitCommandArgs(draft.oauth_scopes),
    };
  }

  if (transport === "http") {
    return {
      ...base,
      url: String(draft?.url || "").trim(),
      bearer_token_env: String(draft?.bearer_token_env || "").trim(),
      bearer_token: String(draft?.bearer_token || "").trim(),
      headers: pairsToObject(draft?.headers),
      env_headers: pairsToObject(draft?.env_headers),
    };
  }

  return {
    ...base,
    command: String(draft?.command || "").trim(),
    args: splitCommandArgs(draft?.args),
    cwd: String(draft?.cwd || "").trim(),
    env: pairsToObject(draft?.env),
  };
}

export function validateMcpDraft(draft) {
  const errors = [];
  if (!String(draft?.name || "").trim()) {
    errors.push("Informe o nome do servidor MCP.");
  }
  const transport = normalizeTransport(draft?.transport);
  if (transport === "http") {
    const url = String(draft?.url || "").trim();
    if (!url) {
      errors.push("Informe a URL do endpoint HTTP com streaming.");
    } else if (!/^https?:\/\//i.test(url)) {
      errors.push(
        "A URL do servidor MCP deve começar com http:// ou https://.",
      );
    }
  } else if (!String(draft?.command || "").trim()) {
    errors.push("Informe o comando executável para transporte STDIO.");
  }
  return { valid: errors.length === 0, errors };
}

export function normalizeMcpServers(response) {
  const list = Array.isArray(response)
    ? response
    : safeList(response?.servers || response?.items || response?.connectors);
  return list.map((server, idx) => ({
    ...server,
    id: String(server?.id || server?.name || `mcp_${idx + 1}`),
    name: String(server?.name || `MCP ${idx + 1}`),
    description: String(server?.description || ""),
    transport: normalizeTransport(server?.transport || server?.type),
    account_mode: normalizeAccountMode(server?.account_mode),
    active_context: String(server?.active_context || "Pessoal"),
    enabled: server?.enabled !== false,
    status: String(
      server?.last_status ||
        server?.status ||
        (server?.enabled === false ? "disabled" : "ready"),
    ),
    tools: safeList(server?.tools || server?.cached_tools).map(
      normalizeMcpTool,
    ),
    tool_count: Number(
      server?.tool_count ??
        safeList(server?.tools || server?.cached_tools).length ??
        0,
    ),
    accounts: safeList(server?.accounts).map((acc, accIdx) =>
      normalizeAccountRecord(acc, accIdx),
    ),
    available_contexts: Array.from(
      new Set(
        safeList(server?.accounts)
          .map((acc) => String(acc?.context || "").trim())
          .filter(Boolean),
      ),
    ),
  }));
}

export function normalizeMcpTool(tool, index = 0) {
  return {
    name: String(tool?.name || `tool_${index + 1}`),
    description: String(tool?.description || "Sem descrição informada."),
    inputSchema:
      tool?.inputSchema && typeof tool.inputSchema === "object"
        ? tool.inputSchema
        : tool?.parameters && typeof tool.parameters === "object"
          ? tool.parameters
          : null,
  };
}

export function normalizeMcpTools(response) {
  const list = Array.isArray(response) ? response : safeList(response?.tools);
  return list.map((tool, index) => normalizeMcpTool(tool, index));
}

export function normalizePlugins(response) {
  const list = Array.isArray(response)
    ? response
    : safeList(response?.plugins || response?.items);
  return list.map((plugin, idx) => ({
    id: String(plugin?.id || plugin?.slug || `plugin_${idx + 1}`),
    name: String(plugin?.name || plugin?.id || `Plugin ${idx + 1}`),
    description: String(plugin?.description || ""),
    version: String(plugin?.version || "1.0.0"),
    category: String(plugin?.category || "extensão"),
    enabled: plugin?.enabled !== false,
    capabilities: safeList(plugin?.capabilities).map(String),
    settings_section: plugin?.settings_section
      ? String(plugin.settings_section)
      : "",
    status: String(
      plugin?.status || (plugin?.enabled === false ? "disabled" : "active"),
    ),
  }));
}

export function filterPlugins(plugins, query = "") {
  const needle = String(query || "")
    .trim()
    .toLowerCase();
  if (!needle) return safeList(plugins);
  return safeList(plugins).filter((plugin) =>
    [
      plugin.name,
      plugin.description,
      plugin.category,
      ...safeList(plugin.capabilities),
    ]
      .join(" ")
      .toLowerCase()
      .includes(needle),
  );
}

export function normalizeSkills(response) {
  const list = Array.isArray(response)
    ? response
    : safeList(response?.skills || response?.items);
  return list.map((skill, idx) => {
    const triggers = Array.isArray(skill?.triggers)
      ? skill.triggers.map(String)
      : skill?.trigger
        ? [String(skill.trigger)]
        : [];
    return {
      id: String(skill?.id || skill?.slug || `skill_${idx + 1}`),
      name: String(skill?.name || `Skill ${idx + 1}`),
      description: String(skill?.description || ""),
      category: String(skill?.category || "personalizada").toLowerCase(),
      trigger: triggers.join(", "),
      triggers,
      action_type: String(skill?.action_type || skill?.kind || "command"),
      command: String(skill?.command || skill?.executable || ""),
      instructions: String(skill?.prompt || skill?.instructions || ""),
      enabled: skill?.enabled !== false,
      native: Boolean(skill?.builtin || skill?.native),
    };
  });
}

export function createEmptySkillDraft() {
  return {
    id: "",
    name: "",
    description: "",
    category: "personalizada",
    trigger: "",
    action_type: "command",
    command: "",
    instructions: "",
    enabled: true,
  };
}

export function skillToDraft(skill) {
  if (!skill || typeof skill !== "object") return createEmptySkillDraft();
  const triggers = Array.isArray(skill.triggers)
    ? skill.triggers.join(", ")
    : String(skill.trigger || "");
  return {
    id: String(skill.id || ""),
    name: String(skill.name || ""),
    description: String(skill.description || ""),
    category: String(skill.category || "personalizada").toLowerCase(),
    trigger: triggers,
    action_type: String(skill.action_type || "command"),
    command: String(skill.command || ""),
    instructions: String(skill.prompt || skill.instructions || ""),
    enabled: skill.enabled !== false,
  };
}

export function draftToSkillPayload(draft) {
  const triggers = String(draft?.trigger || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  return {
    name: String(draft?.name || "").trim(),
    description: String(draft?.description || "").trim(),
    category:
      String(draft?.category || "personalizada").trim() || "personalizada",
    triggers,
    action_type: String(draft?.action_type || "command").trim() || "command",
    command: String(draft?.command || "").trim(),
    prompt: String(draft?.instructions || "").trim(),
    enabled: draft?.enabled !== false,
  };
}

export function validateSkillDraft(draft) {
  const errors = [];
  if (!String(draft?.name || "").trim()) {
    errors.push("Informe o nome da skill.");
  }
  if (!String(draft?.description || "").trim()) {
    errors.push("Informe uma descrição clara do que a skill faz.");
  }
  if (
    draft?.action_type === "command" &&
    !String(draft?.command || "").trim() &&
    !String(draft?.instructions || "").trim()
  ) {
    errors.push("Informe o comando executável ou instruções da skill.");
  }
  return { valid: errors.length === 0, errors };
}

export function filterSkills(skills, { category = "all", query = "" } = {}) {
  const cat = String(category || "all").toLowerCase();
  const needle = String(query || "")
    .trim()
    .toLowerCase();
  return safeList(skills).filter((skill) => {
    if (cat !== "all" && String(skill.category || "").toLowerCase() !== cat) {
      return false;
    }
    if (!needle) return true;
    return [
      skill.name,
      skill.description,
      skill.trigger,
      skill.command,
      skill.category,
    ]
      .join(" ")
      .toLowerCase()
      .includes(needle);
  });
}
