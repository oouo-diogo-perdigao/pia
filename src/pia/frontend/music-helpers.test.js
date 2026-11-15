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

  it("reports clear connection status badges for OAuth, bearer, and disconnected states", () => {
    assert.deepEqual(
      resolveSunoConnectionStatus({ suno_mcp_oauth_connected: true }, {}),
      {
        connected: true,
        mode: "oauth",
        label: "Conta OAuth conectada (Cofre)",
        color: "teal",
      },
    );
    assert.equal(
      resolveSunoConnectionStatus(
        {
          suno_mcp_url: "https://suno.example/mcp",
          suno_mcp_token_configured: true,
        },
        {},
      ).mode,
      "bearer",
    );
    assert.equal(
      resolveSunoConnectionStatus(
        { suno_mcp_url: "https://suno.example/mcp" },
        {},
      ).mode,
      "configured",
    );
    assert.equal(resolveSunoConnectionStatus({}, {}).mode, "none");
  });
});
