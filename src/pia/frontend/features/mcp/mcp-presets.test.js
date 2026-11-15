import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  createEmptyMcpDraft,
  validateMcpDraft,
} from "../../extensions-helpers.js";
import { MCP_ONE_CLICK_PRESETS, applyMcpPreset } from "./mcp-presets.js";

describe("mcp-presets 1-click templates", () => {
  it("provides Suno (distributed), Dropbox (incremental), GitHub (alternating), and custom presets", () => {
    assert.deepEqual(
      MCP_ONE_CLICK_PRESETS.map((p) => p.id),
      ["suno", "dropbox", "github", "custom"],
    );

    const suno = applyMcpPreset(createEmptyMcpDraft(), "suno");
    assert.equal(suno.name, "Suno MCP");
    assert.equal(suno.transport, "http");
    assert.equal(suno.account_mode, "distributed");
    assert.equal(suno.accounts.length, 2);
    assert.equal(validateMcpDraft(suno).valid, true);

    const dropbox = applyMcpPreset(createEmptyMcpDraft(), "dropbox");
    assert.equal(dropbox.account_mode, "incremental");
    assert.equal(dropbox.accounts[0].auth_type, "oauth");
    assert.equal(validateMcpDraft(dropbox).valid, true);

    const github = applyMcpPreset(createEmptyMcpDraft(), "github");
    assert.equal(github.transport, "stdio");
    assert.equal(github.account_mode, "alternating");
    assert.equal(github.active_context, "Trabalho");
    assert.equal(validateMcpDraft(github).valid, true);
  });

  it("preserves connector id when applying preset to an existing draft", () => {
    const existing = { ...createEmptyMcpDraft(), id: "existing_123" };
    const updated = applyMcpPreset(existing, "suno");
    assert.equal(updated.id, "existing_123");
  });
});
