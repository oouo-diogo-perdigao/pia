import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  MUSIC_PROVIDER_LABELS,
  SUNO_SETTINGS_ROUTE,
  buildGeneratorOptions,
  buildMusicSelectPayload,
  buildSunoOAuthStartPayload,
  musicDraftSnapshot,
  providerLabel,
  resolveInitialProvider,
  resolveProviderAfterRefresh,
  resolveReuseProvider,
  resolveSunoConnectionStatus,
  selectionToMusicDraft,
  shouldShowSunoHint,
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
    const selectPayload = buildMusicSelectPayload({
      provider: "suno_mcp",
      suno_mcp_url: "  https://suno.example/mcp  ",
      suno_mcp_command: "",
      suno_mcp_token: "",
      suno_mcp_auth_type: "oauth",
      suno_mcp_client_id: " cid ",
      suno_mcp_client_secret: "",
    });
    assert.deepEqual(selectPayload, {
      provider: "suno_mcp",
      suno_mcp_url: "https://suno.example/mcp",
      suno_mcp_command: "",
      suno_mcp_auth_type: "oauth",
      suno_mcp_client_id: "cid",
    });

    const oauthPayload = buildSunoOAuthStartPayload({
      suno_mcp_client_id: " cid ",
      suno_mcp_client_secret: " sec ",
      suno_mcp_auth_url: "https://auth.example/authorize",
      suno_mcp_token_url: "",
      suno_mcp_scopes: "read write",
    });
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
        mode: "token",
        label: "Token configurado",
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
        mode: "oauth_pending",
        label: "OAuth pendente",
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
        mode: "none",
        label: "Não configurado",
        color: "gray",
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
});
