import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  buildMusicSelectPayload,
  buildSunoOAuthStartPayload,
  musicDraftSnapshot,
  resolveSunoConnectionStatus,
  selectionToMusicDraft,
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
