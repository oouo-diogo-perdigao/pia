import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  MASKED_EDITED_FIELD_ERROR,
  MUSIC_PROVIDERS_UPDATED_EVENT,
  MUSIC_PROVIDER_LABELS,
  SUNO_CANCEL_WARNING,
  SUNO_DURATION_HINT,
  SUNO_HINT_TEXT,
  SUNO_REUSE_WARNING,
  SUNO_SETTINGS_ROUTE,
  buildGeneratorOptions,
  findSunoProvider,
  generatorHints,
  isGeneratorAvailable,
  isMaskedSecret,
  isSunoApiHost,
  isSunoCatalogProvider,
  maskedEditedFieldError,
  notifyMusicProvidersUpdated,
  finalStateForError,
  interruptedProgressLabel,
  partialBatchLabel,
  buildMusicSelectPayload,
  buildSunoOAuthStartPayload,
  musicDraftSnapshot,
  providerLabel,
  resolveInitialProvider,
  resolveProviderAfterRefresh,
  resolveReuseProvider,
  resolveSunoConnectionStatus,
  runWithMusicProvidersUpdate,
  selectionToMusicDraft,
  shouldShowSunoHint,
  shouldWarnSunoOpensInLocal,
  sunoSettingsRoute,
} from "./music-helpers.js";

describe("music-helpers Suno MCP & OAuth", () => {
  it("hydrates draft from /music/providers selection including OAuth fields", () => {
    const draft = selectionToMusicDraft({
      provider: "suno_mcp",
      suno_mcp_url: "https://mcp.suno.example.com/mcp",
      suno_mcp_auth_type: "oauth",
      suno_mcp_oauth_connected: true,
      suno_mcp_oauth_client_id: "client-123",
      suno_mcp_oauth_auth_url: "https://auth.suno.example.com/authorize",
      suno_mcp_oauth_token_url: "https://auth.suno.example.com/token",
      suno_mcp_oauth_scopes: "music.generate",
    });

    assert.equal(draft.provider, "suno_mcp");
    assert.equal(draft.suno_mcp_auth_type, "oauth");
    assert.equal(draft.suno_mcp_client_id, "client-123");
    assert.equal(draft.suno_mcp_scopes, "music.generate");
    assert.equal(draft.suno_mcp_client_secret, "");
    assert.ok(musicDraftSnapshot(draft).includes("client-123"));
  });

  it("builds /music/select and /music/suno/oauth/start payloads omitting empty secrets", () => {
    const edited = {
      suno_mcp_url: true,
      suno_mcp_command: true,
      suno_mcp_client_id: true,
      suno_mcp_client_secret: true,
      suno_mcp_auth_url: true,
      suno_mcp_token_url: true,
      suno_mcp_scopes: true,
    };
    const selectPayload = buildMusicSelectPayload(
      {
        provider: "suno_mcp",
        suno_mcp_url: "  https://suno.example/mcp  ",
        suno_mcp_command: "",
        suno_mcp_token: "",
        suno_mcp_auth_type: "oauth",
        suno_mcp_client_id: " cid ",
        suno_mcp_client_secret: "",
      },
      { edited },
    );
    assert.deepEqual(selectPayload, {
      provider: "suno_mcp",
      suno_mcp_url: "https://suno.example/mcp",
      suno_mcp_command: "",
      suno_mcp_auth_type: "oauth",
      suno_mcp_client_id: "cid",
    });

    const oauthPayload = buildSunoOAuthStartPayload(
      {
        suno_mcp_client_id: " cid ",
        suno_mcp_client_secret: " sec ",
        suno_mcp_auth_url: "https://auth.example/authorize",
        suno_mcp_token_url: "",
        suno_mcp_scopes: "read write",
      },
      { edited },
    );
    assert.deepEqual(oauthPayload, {
      client_id: "cid",
      client_secret: "sec",
      auth_url: "https://auth.example/authorize",
      scopes: "read write",
    });
  });

  it("does not require manual client_id when starting Suno OAuth with DCR defaults", () => {
    assert.deepEqual(buildSunoOAuthStartPayload({}), {});
    assert.deepEqual(
      buildSunoOAuthStartPayload({
        suno_mcp_client_id: "",
        suno_mcp_auth_url: "",
        suno_mcp_token_url: "",
        suno_mcp_scopes: "",
      }),
      {},
    );
  });

  it("reports accurate connection status without treating registered server or token presence as connected", () => {
    assert.deepEqual(
      resolveSunoConnectionStatus({ suno_mcp_oauth_connected: true }, {}),
      {
        connected: true,
        mode: "oauth",
        label: "Conta OAuth conectada (Cofre)",
        color: "teal",
      },
    );

    assert.deepEqual(
      resolveSunoConnectionStatus(
        {
          suno_mcp_url: "https://suno.example/mcp",
          suno_mcp_token_configured: true,
          suno_mcp_auth_type: "bearer",
        },
        {},
      ),
      {
        connected: false,
        mode: "credential",
        label: "Credencial configurada",
        color: "blue",
      },
    );

    assert.deepEqual(
      resolveSunoConnectionStatus(
        {
          suno_mcp_url: "https://suno.example/mcp",
          suno_mcp_auth_type: "oauth",
          suno_mcp_oauth_connected: false,
        },
        {},
      ),
      {
        connected: false,
        mode: "needs_auth",
        label: "URL configurada, falta autorizar",
        color: "yellow",
      },
    );

    assert.deepEqual(
      resolveSunoConnectionStatus(
        {
          suno_mcp_url: "https://suno.example/mcp",
          suno_mcp_command: "npx suno-mcp",
          suno_mcp_auth_type: "none",
          suno_mcp_token_configured: false,
          suno_mcp_oauth_connected: false,
        },
        {},
      ),
      {
        connected: false,
        mode: "needs_auth",
        label: "URL configurada, falta autorizar",
        color: "yellow",
      },
    );

    // Non-boolean token reference strings must not be coerced to connected/configured.
    assert.deepEqual(
      resolveSunoConnectionStatus(
        {
          suno_mcp_token_configured: "vault:suno_token",
          suno_mcp_oauth_connected: "pending",
        },
        {},
      ),
      {
        connected: false,
        mode: "none",
        label: "Não configurado",
        color: "gray",
      },
    );

    assert.deepEqual(resolveSunoConnectionStatus({}, {}), {
      connected: false,
      mode: "none",
      label: "Não configurado",
      color: "gray",
    });
  });
});

describe("music-helpers T7: status, payload mascarado e evento", () => {
  const t1SunoDefaults = {
    id: "suno_mcp",
    label: "Suno",
    name: "Suno (MCP)",
    kind: "mcp",
    description: "Conexão com servidor MCP do Suno",
    url: "",
    command: "",
    endpoint_configured: false,
    credential_state: "missing",
    token_configured: false,
    auth_type: "none",
    oauth_connected: false,
    oauth_client_id: "",
    oauth_auth_url: "",
    oauth_token_url: "",
    oauth_scopes: "",
    server_id: "suno_mcp",
    settings_route: { view: "settings", section: "Apps/music" },
    available: false,
  };

  function t1Catalog(sunoOverrides = {}, selectionOverrides = {}) {
    const suno = { ...t1SunoDefaults, ...sunoOverrides };
    return {
      providers: [
        {
          id: "local",
          name: "Criador de músicas local",
          kind: "local",
          description: "ACE-Step local offline",
          installed: false,
          available: true,
        },
        {
          id: "gemini",
          name: "Gemini",
          kind: "remote",
          description: "Geração de música via Gemini (Lyria)",
          model: "lyria-3.5",
          credential_state: "missing",
          available: false,
        },
        suno,
      ],
      selection: {
        provider: "local",
        gemini_model: "lyria-3.5",
        suno_mcp_url: suno.url,
        suno_mcp_command: suno.command,
        suno_mcp_token_configured: suno.token_configured,
        suno_mcp_auth_type: suno.auth_type,
        suno_mcp_oauth_connected: suno.oauth_connected,
        suno_mcp_oauth_client_id: suno.oauth_client_id,
        suno_mcp_oauth_auth_url: suno.oauth_auth_url,
        suno_mcp_oauth_token_url: suno.oauth_token_url,
        suno_mcp_oauth_scopes: suno.oauth_scopes,
        ...selectionOverrides,
      },
    };
  }

  function statusOf(catalog) {
    return resolveSunoConnectionStatus(
      catalog.selection,
      findSunoProvider(catalog),
    );
  }

  async function withWindowEvents(run) {
    const events = [];
    const previous = globalThis.window;
    globalThis.window = {
      dispatchEvent(ev) {
        events.push(ev);
        return true;
      },
    };
    if (typeof globalThis.CustomEvent !== "function") {
      globalThis.CustomEvent = class CustomEvent {
        constructor(type) {
          this.type = type;
        }
      };
    }
    try {
      return await run(events);
    } finally {
      globalThis.window = previous;
    }
  }

  it("instalação nova (sem endpoint) mostra Não configurado, não falta autorizar", () => {
    const catalog = t1Catalog();
    assert.deepEqual(statusOf(catalog), {
      connected: false,
      mode: "none",
      label: "Não configurado",
      color: "gray",
    });
  });

  it("usa credential_state expired e endpoint sem credencial", () => {
    assert.deepEqual(
      statusOf(
        t1Catalog({
          url: "https://api.suno.com/mcp",
          endpoint_configured: true,
          credential_state: "expired",
          available: false,
        }),
      ),
      {
        connected: false,
        mode: "expired",
        label: "Expirado — reautorizar",
        color: "orange",
      },
    );
    assert.deepEqual(
      statusOf(
        t1Catalog({
          url: "https://api.suno.com/mcp",
          endpoint_configured: true,
          credential_state: "missing",
          available: false,
        }),
      ),
      {
        connected: false,
        mode: "needs_auth",
        label: "URL configurada, falta autorizar",
        color: "yellow",
      },
    );
  });

  it("token sem endpoint mostra Credencial configurada", () => {
    assert.deepEqual(
      statusOf(
        t1Catalog({
          endpoint_configured: false,
          credential_state: "configured",
          token_configured: true,
          auth_type: "bearer",
          available: false,
        }),
      ),
      {
        connected: false,
        mode: "credential",
        label: "Credencial configurada",
        color: "blue",
      },
    );
  });

  it("servidor desabilitado (T1 zera endpoint_configured) fica Não configurado", () => {
    const catalog = t1Catalog({
      url: "https://api.suno.com/mcp",
      endpoint_configured: false,
      credential_state: "missing",
      token_configured: false,
      oauth_connected: false,
      available: false,
    });
    assert.deepEqual(statusOf(catalog), {
      connected: false,
      mode: "none",
      label: "Não configurado",
      color: "gray",
    });
  });

  it("OAuth pendente com URL padrão (oauth/start) não vira falta autorizar", () => {
    const catalog = t1Catalog({
      url: "https://api.suno.com/mcp",
      endpoint_configured: true,
      credential_state: "missing",
      auth_type: "oauth",
      oauth_connected: false,
      available: false,
    });
    // Sem pendingOAuth ativo, auth_type residual cai em needs_auth (D1).
    assert.deepEqual(statusOf(catalog), {
      connected: false,
      mode: "needs_auth",
      label: "URL configurada, falta autorizar",
      color: "yellow",
    });
    assert.deepEqual(
      resolveSunoConnectionStatus(
        catalog.selection,
        findSunoProvider(catalog),
        { state: "xyz", authUrl: "https://auth.suno.com/authorize" },
      ),
      {
        connected: false,
        mode: "oauth_pending",
        label: "OAuth pendente",
        color: "yellow",
      },
    );
    assert.deepEqual(
      buildSunoOAuthStartPayload(
        {
          suno_mcp_client_id: catalog.selection.suno_mcp_oauth_client_id,
          suno_mcp_auth_url: catalog.selection.suno_mcp_oauth_auth_url,
        },
        { edited: {} },
      ),
      {},
    );
    assert.deepEqual(
      buildSunoOAuthStartPayload(
        { suno_mcp_client_id: "novo-client" },
        { edited: { suno_mcp_client_id: true } },
      ),
      { client_id: "novo-client" },
    );
  });

  it("oauth salvo + bearer configurado mostra Credencial configurada", () => {
    const catalog = t1Catalog({
      url: "https://api.suno.com/mcp",
      endpoint_configured: true,
      credential_state: "configured",
      token_configured: true,
      auth_type: "oauth",
      oauth_connected: false,
      available: true,
    });
    assert.deepEqual(statusOf(catalog), {
      connected: false,
      mode: "credential",
      label: "Credencial configurada",
      color: "blue",
    });
  });

  it("oauth salvo sem pendingOAuth e sem credencial cai em needs_auth", () => {
    const catalog = t1Catalog({
      url: "https://api.suno.com/mcp",
      endpoint_configured: true,
      credential_state: "missing",
      auth_type: "oauth",
      oauth_connected: false,
      available: false,
    });
    assert.deepEqual(statusOf(catalog), {
      connected: false,
      mode: "needs_auth",
      label: "URL configurada, falta autorizar",
      color: "yellow",
    });
  });

  it("pendingOAuth ativo mostra OAuth pendente", () => {
    const catalog = t1Catalog({
      url: "https://api.suno.com/mcp",
      endpoint_configured: true,
      credential_state: "missing",
      auth_type: "oauth",
      oauth_connected: false,
      available: false,
    });
    assert.deepEqual(
      resolveSunoConnectionStatus(
        catalog.selection,
        findSunoProvider(catalog),
        { state: "pending-1", authUrl: "https://api.suno.com/login" },
      ),
      {
        connected: false,
        mode: "oauth_pending",
        label: "OAuth pendente",
        color: "yellow",
      },
    );
  });

  it("depois de desconectar não fica OAuth pendente", () => {
    const catalog = t1Catalog({
      url: "https://api.suno.com/mcp",
      endpoint_configured: true,
      credential_state: "missing",
      token_configured: false,
      auth_type: "oauth",
      oauth_connected: false,
      available: false,
    });
    assert.deepEqual(statusOf(catalog), {
      connected: false,
      mode: "needs_auth",
      label: "URL configurada, falta autorizar",
      color: "yellow",
    });
  });

  it("servidor desabilitado com auth_type oauth residual fica Não configurado", () => {
    const catalog = t1Catalog({
      url: "https://api.suno.com/mcp",
      endpoint_configured: false,
      credential_state: "missing",
      token_configured: false,
      auth_type: "oauth",
      oauth_connected: false,
      available: false,
    });
    assert.deepEqual(statusOf(catalog), {
      connected: false,
      mode: "none",
      label: "Não configurado",
      color: "gray",
    });
  });

  it("trata api.suno.com com qualquer id como Suno quando a credencial vale", () => {
    assert.equal(isSunoApiHost("https://api.suno.com/mcp"), true);
    assert.equal(isSunoApiHost("https://example.com/mcp"), false);
    assert.equal(
      isSunoCatalogProvider({
        id: "minha-conta",
        url: "https://api.suno.com/mcp",
      }),
      true,
    );
    const catalog = {
      providers: [
        {
          id: "outra-conta",
          url: "https://api.suno.com/mcp",
          available: true,
          credential_state: "configured",
          oauth_connected: true,
        },
      ],
    };
    const suno = findSunoProvider(catalog);
    assert.equal(suno.id, "outra-conta");
    assert.equal(resolveSunoConnectionStatus({}, suno).mode, "oauth");
    assert.equal(resolveSunoConnectionStatus({}, suno).connected, true);
    assert.equal(isGeneratorAvailable("suno_mcp", catalog), true);
  });

  it("avisa RN04 quando Suno está salvo mas available não é true", () => {
    assert.equal(
      shouldWarnSunoOpensInLocal(
        { provider: "suno_mcp" },
        t1Catalog({
          url: "https://api.suno.com/mcp",
          endpoint_configured: true,
          credential_state: "missing",
          available: false,
        }).providers[2],
      ),
      true,
    );
    assert.equal(
      shouldWarnSunoOpensInLocal(
        { provider: "suno_mcp" },
        t1Catalog({
          endpoint_configured: true,
          credential_state: "configured",
          oauth_connected: true,
          auth_type: "oauth",
          available: true,
        }).providers[2],
      ),
      false,
    );
    assert.equal(
      shouldWarnSunoOpensInLocal({ provider: "local" }, {}, "local"),
      false,
    );
  });

  it("omite qualquer URL/comando/OAuth não editado, inclusive URL sem query da T1", () => {
    const draft = {
      provider: "suno_mcp",
      suno_mcp_url: "https://api.suno.com/mcp",
      suno_mcp_command: "npx suno-mcp",
      suno_mcp_auth_type: "oauth",
      suno_mcp_client_id: "client-visivel",
      suno_mcp_auth_url: "https://auth.suno.com/authorize",
      suno_mcp_scopes: "music.generate",
    };
    assert.equal(isMaskedSecret(draft.suno_mcp_url), false);
    assert.deepEqual(buildMusicSelectPayload(draft), {
      provider: "suno_mcp",
      suno_mcp_auth_type: "oauth",
    });
    assert.deepEqual(buildSunoOAuthStartPayload(draft), {});
  });

  it("inclui URL, comando e OAuth depois que o usuário edita o campo", () => {
    const draft = {
      provider: "suno_mcp",
      suno_mcp_url: "https://mcp.example/suno",
      suno_mcp_command: "npx suno-mcp",
      suno_mcp_auth_type: "oauth",
      suno_mcp_client_id: "novo-client",
      suno_mcp_auth_url: "https://auth.example/authorize",
    };
    const edited = {
      suno_mcp_url: true,
      suno_mcp_command: true,
      suno_mcp_client_id: true,
      suno_mcp_auth_url: true,
    };
    assert.deepEqual(buildMusicSelectPayload(draft, { edited }), {
      provider: "suno_mcp",
      suno_mcp_url: "https://mcp.example/suno",
      suno_mcp_command: "npx suno-mcp",
      suno_mcp_auth_type: "oauth",
      suno_mcp_client_id: "novo-client",
      suno_mcp_auth_url: "https://auth.example/authorize",
    });
  });

  it("campo mascarado editado bloqueia o salvamento; os outros campos seguem normais", () => {
    const draft = {
      provider: "suno_mcp",
      suno_mcp_url: "https://api.suno.com/mcp",
      suno_mcp_command: "npx suno --token •••• --v2",
      suno_mcp_auth_type: "oauth",
      suno_mcp_token: "  novo-token  ",
      suno_mcp_client_id: "client-ok",
    };
    assert.equal(
      maskedEditedFieldError(draft, { suno_mcp_command: true }),
      MASKED_EDITED_FIELD_ERROR,
    );
    assert.throws(
      () =>
        buildMusicSelectPayload(draft, { edited: { suno_mcp_command: true } }),
      { message: MASKED_EDITED_FIELD_ERROR },
    );
    const payload = buildMusicSelectPayload(draft, {
      edited: { suno_mcp_token: true, suno_mcp_client_id: true },
    });
    assert.equal(payload.provider, "suno_mcp");
    assert.equal(payload.suno_mcp_auth_type, "oauth");
    assert.equal(payload.suno_mcp_token, "novo-token");
    assert.equal(payload.suno_mcp_client_id, "client-ok");
    assert.equal("suno_mcp_url" in payload, false);
    assert.equal("suno_mcp_command" in payload, false);
  });

  it("dispara pia:music-providers-updated no window", async () => {
    await withWindowEvents((events) => {
      notifyMusicProvidersUpdated();
      assert.equal(events.length, 1);
      assert.equal(events[0].type, MUSIC_PROVIDERS_UPDATED_EVENT);
    });
  });

  it("dispara o evento se o select ok e o oauth/start falha", async () => {
    await withWindowEvents(async (events) => {
      await assert.rejects(
        () =>
          runWithMusicProvidersUpdate(async (markMutated) => {
            markMutated();
            throw new Error("oauth/start falhou");
          }),
        { message: "oauth/start falhou" },
      );
      assert.equal(events.length, 1);
      assert.equal(events[0].type, MUSIC_PROVIDERS_UPDATED_EVENT);
    });
  });

  it("dispara o evento se o callback ok e o loadCatalog falha", async () => {
    await withWindowEvents(async (events) => {
      await assert.rejects(
        () =>
          runWithMusicProvidersUpdate(async (markMutated) => {
            markMutated();
            throw new Error("loadCatalog falhou");
          }),
        { message: "loadCatalog falhou" },
      );
      assert.equal(events.length, 1);
    });
  });

  it("não dispara o evento se a ação falhar antes de mutar", async () => {
    await withWindowEvents(async (events) => {
      await assert.rejects(
        () =>
          runWithMusicProvidersUpdate(async () => {
            throw new Error("select falhou");
          }),
        { message: "select falhou" },
      );
      assert.equal(events.length, 0);
    });
  });
});

describe("music-helpers seletor dinâmico (Suno no app de Música)", () => {
  const catalog = (sunoAvailable, provider = "local") => ({
    providers: [
      { id: "local", label: "Local", available: true },
      { id: "gemini", label: "Gemini", available: false },
      {
        id: "suno_mcp",
        label: "Suno",
        kind: "mcp",
        available: sunoAvailable,
        endpoint_configured: true,
        credential_state: sunoAvailable ? "configured" : "missing",
        settings_route: { view: "settings", section: "Apps/music" },
      },
    ],
    selection: { provider },
  });
  const values = (options) => options.map((option) => option.value);

  it("mostra Suno quando o catálogo diz available=true (CA01)", () => {
    const options = buildGeneratorOptions(catalog(true));
    assert.deepEqual(values(options), ["local", "gemini", "suno_mcp", "flow"]);
    assert.equal(options.find((o) => o.value === "suno_mcp").label, "Suno");
    assert.equal(shouldShowSunoHint(catalog(true)), false);
  });

  it("esconde Suno e mostra a dica quando indisponível (CA02)", () => {
    assert.deepEqual(values(buildGeneratorOptions(catalog(false))), [
      "local",
      "gemini",
      "flow",
    ]);
    assert.equal(shouldShowSunoHint(catalog(false)), true);
    assert.equal(
      shouldShowSunoHint({ providers: [{ id: "local", available: true }] }),
      true,
    );
  });

  it("só aceita available === true (valores truthy não contam)", () => {
    const cat = catalog(true);
    cat.providers[2].available = "true";
    assert.ok(!values(buildGeneratorOptions(cat)).includes("suno_mcp"));
  });

  it("catálogo vazio ou com erro devolve local, gemini e flow sem dica", () => {
    for (const bad of [undefined, null, {}, { error: "boom" }, "x"]) {
      assert.deepEqual(values(buildGeneratorOptions(bad)), [
        "local",
        "gemini",
        "flow",
      ]);
      assert.equal(shouldShowSunoHint(bad), false);
      assert.equal(resolveInitialProvider(bad), "local");
    }
  });

  it("Suno salvo abre em suno_mcp se disponível, senão em local (CA03)", () => {
    assert.equal(resolveInitialProvider(catalog(true, "suno_mcp")), "suno_mcp");
    assert.equal(resolveInitialProvider(catalog(false, "suno_mcp")), "local");
    assert.equal(resolveInitialProvider(catalog(true, "gemini")), "gemini");
    assert.equal(
      resolveInitialProvider(catalog(true, "desconhecido")),
      "local",
    );
  });

  it("após recarregar o catálogo volta para local só se não estiver ocupado (CA04)", () => {
    assert.deepEqual(resolveProviderAfterRefresh("suno_mcp", catalog(true)), {
      provider: "suno_mcp",
      warning: null,
    });
    const fallback = resolveProviderAfterRefresh("suno_mcp", catalog(false));
    assert.equal(fallback.provider, "local");
    assert.match(fallback.warning, /Suno/);
    assert.deepEqual(
      resolveProviderAfterRefresh("suno_mcp", catalog(false), true),
      { provider: "suno_mcp", warning: null },
    );
    assert.deepEqual(resolveProviderAfterRefresh("flow", catalog(false)), {
      provider: "flow",
      warning: null,
    });
  });

  it("reutilizar faixa Suno: Suno se disponível, Local com aviso se não (CA08)", () => {
    const item = { provider: "suno_mcp", prompt: "lofi" };
    assert.deepEqual(resolveReuseProvider(item, catalog(true)), {
      provider: "suno_mcp",
      warning: null,
    });
    const reused = resolveReuseProvider(item, catalog(false));
    assert.equal(reused.provider, "local");
    assert.match(reused.warning, /Configurações → Música/);
  });

  it("reutilizar mantém local/gemini e manda desconhecido para local", () => {
    assert.deepEqual(resolveReuseProvider({ provider: "gemini" }, null), {
      provider: "gemini",
      warning: null,
    });
    assert.deepEqual(
      resolveReuseProvider({ provider: "flow" }, catalog(true)),
      {
        provider: "local",
        warning: null,
      },
    );
    assert.deepEqual(resolveReuseProvider({ provider: "xyz" }, catalog(true)), {
      provider: "local",
      warning: null,
    });
    assert.deepEqual(resolveReuseProvider(undefined, catalog(true)), {
      provider: "local",
      warning: null,
    });
  });

  it("rótulos curtos para o Histórico com fallback para o id", () => {
    assert.equal(providerLabel("suno_mcp"), "Suno");
    assert.equal(providerLabel("local"), "Local");
    assert.equal(providerLabel("gemini"), "Gemini");
    assert.equal(providerLabel("outro_provedor"), "outro_provedor");
    assert.equal(providerLabel(undefined), "");
    assert.equal(MUSIC_PROVIDER_LABELS.suno_mcp, "Suno (MCP)");
  });

  it("rota do atalho vem do catálogo ou do padrão Apps/music", () => {
    assert.deepEqual(sunoSettingsRoute(catalog(false)), SUNO_SETTINGS_ROUTE);
    assert.deepEqual(sunoSettingsRoute(null), {
      view: "settings",
      section: "Apps/music",
    });
  });

  it("falha passageira do catálogo mantém o provedor atual sem aviso", () => {
    for (const bad of [undefined, null, {}, { error: "timeout" }]) {
      assert.deepEqual(resolveProviderAfterRefresh("suno_mcp", bad), {
        provider: "suno_mcp",
        warning: null,
      });
    }
  });

  it("resolveInitialProvider ignora flow salvo (não é gerador do backend)", () => {
    assert.equal(resolveInitialProvider(catalog(true, "flow")), "local");
  });

  it("isGeneratorAvailable direto", () => {
    assert.equal(isGeneratorAvailable("local", null), true);
    assert.equal(isGeneratorAvailable("gemini", catalog(false)), true);
    assert.equal(isGeneratorAvailable("flow", undefined), true);
    assert.equal(isGeneratorAvailable("suno_mcp", catalog(true)), true);
    assert.equal(isGeneratorAvailable("suno_mcp", catalog(false)), false);
    assert.equal(isGeneratorAvailable("suno_mcp", null), false);
    assert.equal(isGeneratorAvailable("xyz", catalog(true)), false);
    assert.equal(
      isGeneratorAvailable("suno_mcp", {
        providers: [
          {
            id: "outra-conta",
            url: "https://api.suno.com/mcp",
            available: true,
          },
        ],
      }),
      true,
    );
  });

  it("buildGeneratorOptions e sunoSettingsRoute devolvem cópias", () => {
    const first = buildGeneratorOptions(catalog(true));
    first[0].label = "alterado";
    first.push({ value: "x" });
    assert.equal(
      buildGeneratorOptions(catalog(true))[0].label,
      "Local · ACE-Step",
    );
    const cat = catalog(false);
    const route = sunoSettingsRoute(cat);
    route.section = "outra";
    assert.equal(cat.providers[2].settings_route.section, "Apps/music");
    const fallback = sunoSettingsRoute(null);
    fallback.view = "x";
    assert.equal(SUNO_SETTINGS_ROUTE.view, "settings");
  });

  it("sunoSettingsRoute só aceita view settings", () => {
    const cat = catalog(false);
    cat.providers[2].settings_route = { view: "chat", section: "x" };
    assert.deepEqual(sunoSettingsRoute(cat), SUNO_SETTINGS_ROUTE);
    cat.providers[2].settings_route = {
      view: "settings",
      section: "Apps/music2",
    };
    assert.deepEqual(sunoSettingsRoute(cat), {
      view: "settings",
      section: "Apps/music2",
    });
  });

  it("textos de dica, aviso e cancelamento", () => {
    assert.match(SUNO_HINT_TEXT, /Configurações → Música/);
    assert.match(SUNO_REUSE_WARNING, /Configurações → Música/);
    assert.match(SUNO_CANCEL_WARNING, /créditos/);
    assert.match(SUNO_DURATION_HINT, /duração é indicativa/);
  });

  it("generatorHints mostra duração indicativa e créditos só com Suno", () => {
    assert.deepEqual(generatorHints("suno_mcp"), [
      SUNO_DURATION_HINT,
      SUNO_CANCEL_WARNING,
    ]);
    assert.deepEqual(generatorHints("local"), []);
    assert.deepEqual(generatorHints("gemini"), []);
    assert.deepEqual(generatorHints(undefined), []);
  });

  it("partialBatchLabel usa o texto da notificação", () => {
    assert.equal(partialBatchLabel(1, 3), "1 de 3 músicas prontas");
    assert.equal(partialBatchLabel(0, 2), "0 de 2 músicas prontas");
    assert.equal(partialBatchLabel(0, 1), "0 de 1 música pronta");
    assert.equal(partialBatchLabel(undefined, 3), "");
    assert.equal(partialBatchLabel(1, 0), "");
  });

  it("buildGeneratorOptions mantém o provedor atual com keep", () => {
    assert.deepEqual(
      values(buildGeneratorOptions(catalog(false), "suno_mcp")),
      ["local", "gemini", "suno_mcp", "flow"],
    );
    assert.deepEqual(values(buildGeneratorOptions(null, "suno_mcp")), [
      "local",
      "gemini",
      "suno_mcp",
      "flow",
    ]);
    assert.deepEqual(values(buildGeneratorOptions(catalog(false), "xyz")), [
      "local",
      "gemini",
      "flow",
    ]);
    assert.deepEqual(values(buildGeneratorOptions(catalog(false), "local")), [
      "local",
      "gemini",
      "flow",
    ]);
  });

  it("reuse de faixa Suno com catálogo carregando fica pendente, sem aviso", () => {
    for (const loading of [null, undefined, { error: "x" }]) {
      assert.deepEqual(
        resolveReuseProvider({ provider: "suno_mcp" }, loading),
        {
          provider: "suno_mcp",
          warning: null,
          pending: true,
        },
      );
    }
  });

  it("evento de atualização do catálogo", () => {
    assert.equal(MUSIC_PROVIDERS_UPDATED_EVENT, "pia:music-providers-updated");
  });

  it("interruptedProgressLabel prefere o ready_text do backend", () => {
    assert.equal(
      interruptedProgressLabel({
        completed: 2,
        total: 3,
        ready_text: "2 de 3 músicas prontas",
      }),
      "Geração interrompida · 2 de 3 músicas prontas",
    );
    assert.equal(
      interruptedProgressLabel({ ready_text: "  1 de 4 músicas prontas " }),
      "Geração interrompida · 1 de 4 músicas prontas",
    );
  });

  it("interruptedProgressLabel cai no partialBatchLabel sem ready_text", () => {
    assert.equal(
      interruptedProgressLabel({ completed: 1, total: 3 }),
      "Geração interrompida · 1 de 3 músicas prontas",
    );
    assert.equal(
      interruptedProgressLabel({ completed: 1, total: 1, ready_text: "" }),
      "Geração interrompida · 1 de 1 música pronta",
    );
  });

  it("interruptedProgressLabel sem faixa pronta ou sem dados mostra só o título", () => {
    assert.equal(
      interruptedProgressLabel({
        completed: 0,
        total: 3,
        ready_text: "0 de 3 músicas prontas",
      }),
      "Geração interrompida",
    );
    assert.equal(interruptedProgressLabel({}), "Geração interrompida");
    assert.equal(interruptedProgressLabel(null), "Geração interrompida");
    assert.equal(
      interruptedProgressLabel({ completed: "x", total: 3, ready_text: 5 }),
      "Geração interrompida",
    );
  });

  it("finalStateForError usa interrupted com faixa pronta", () => {
    assert.equal(
      finalStateForError({ state: "running" }, { completed: 1, total: 3 }),
      "interrupted",
    );
    assert.equal(finalStateForError(null, { completed: "2" }), "interrupted");
  });

  it("finalStateForError mantém interrupted vindo do progress", () => {
    assert.equal(
      finalStateForError({ state: "interrupted" }, { completed: 0 }),
      "interrupted",
    );
    assert.equal(
      finalStateForError({ state: "interrupted" }, {}),
      "interrupted",
    );
  });

  it("finalStateForError usa error sem faixa pronta", () => {
    assert.equal(
      finalStateForError({ state: "running" }, { completed: 0, total: 3 }),
      "error",
    );
    assert.equal(finalStateForError(null, {}), "error");
    assert.equal(finalStateForError(undefined, undefined), "error");
    assert.equal(
      finalStateForError({ state: "running" }, { completed: "x" }),
      "error",
    );
  });
});
