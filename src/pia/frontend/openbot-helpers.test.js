import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  AVATAR_PRESETS,
  BOT_TEMPLATES,
  BOT_TOOL_OPTIONS,
  buildBotPayload,
  validateClientSvg,
} from "../../../Plugins/OpenBot/web/avatarPresets.js";

describe("openbot presets and payload helpers", () => {
  it("provides 4 valid SVG avatar presets with talking classes and CSS color vars", () => {
    assert.equal(AVATAR_PRESETS.length, 4);
    for (const preset of AVATAR_PRESETS) {
      assert.equal(validateClientSvg(preset.svg).ok, true);
      assert.match(preset.svg, /class="enable-mouth"/);
      assert.match(preset.svg, /class="animation-talking"/);
      assert.match(preset.svg, /--bot-primary/);
    }
    assert.ok(BOT_TEMPLATES.length >= 3);
    assert.ok(BOT_TOOL_OPTIONS.some((t) => t.value === "delegate_to_bot"));
  });

  it("rejects empty, oversized, or scripted SVGs in validateClientSvg", () => {
    assert.equal(validateClientSvg("").ok, false);
    assert.equal(validateClientSvg("<div>not svg</div>").ok, false);
    assert.equal(
      validateClientSvg("<svg><script>alert(1)</script></svg>").ok,
      false,
    );
    assert.equal(validateClientSvg('<svg onload="boom()"></svg>').ok, false);
    assert.equal(validateClientSvg("x".repeat(260 * 1024)).ok, false);
  });

  it("builds create and PATCH payloads cleanly preserving revision on edit", () => {
    const createPayload = buildBotPayload({
      name: "  Bot Teste  ",
      description: "  Resumo  ",
      instructions: "# Papel",
      enabled: true,
      speak_replies: false,
      llm_tier: "pro",
      avatar_colors: { primary: "#111111", accent: "#222222", eyes: "#ffffff" },
      tool_ids: ["pia_resources"],
      delegation_targets: [],
      voice: { mode: "inherit", profile: { provider: "kokoro" }, revision: 3 },
      revision: 1,
    });
    assert.equal(createPayload.name, "Bot Teste");
    assert.equal(createPayload.description, "Resumo");
    assert.equal(createPayload.revision, undefined);
    assert.deepEqual(createPayload.voice, {
      mode: "inherit",
      profile: null,
      revision: 3,
    });

    const editPayload = buildBotPayload(
      {
        name: "Bot Editado",
        revision: 4,
        voice: {
          mode: "custom",
          profile: {
            provider: "kokoro",
            model: "kokoro-82m",
            voice: "pf_dora",
            speed: 1.1,
          },
          revision: 2,
        },
      },
      { avatarId: "abcdef1234567890", isEdit: true },
    );
    assert.equal(editPayload.revision, 4);
    assert.equal(editPayload.avatar_id, "abcdef1234567890");
    assert.equal(editPayload.voice.mode, "custom");
    assert.equal(editPayload.voice.profile.voice, "pf_dora");
  });
});
