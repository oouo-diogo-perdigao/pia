import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  AVATAR_PRESETS,
  BOT_TEMPLATES,
  BOT_TOOL_OPTIONS,
  COLOR_PRESETS,
  DEFAULT_BOT_COLORS,
  buildBotPayload,
  findMatchingColorPreset,
  validateClientSvg,
} from "../../../Plugins/OpenBot/web/avatarPresets.js";

describe("openbot presets and payload helpers", () => {
  it("provides 12 valid SVG avatar presets with talking classes and CSS color vars", () => {
    assert.equal(AVATAR_PRESETS.length, 12);
    const expectedIds = [
      "orb",
      "visor",
      "owl",
      "spark",
      "fox",
      "astro",
      "neko",
      "knight",
      "lotus",
      "pixel",
      "flame",
      "sonar",
    ];
    assert.deepEqual(
      AVATAR_PRESETS.map((p) => p.id),
      expectedIds,
    );
    for (const preset of AVATAR_PRESETS) {
      assert.equal(validateClientSvg(preset.svg).ok, true);
      assert.match(preset.svg, /class="enable-mouth"/);
      assert.match(preset.svg, /class="animation-talking"/);
      assert.match(preset.svg, /--bot-primary/);
      assert.match(preset.svg, /--bot-accent/);
      assert.match(preset.svg, /--bot-eyes/);
    }
    assert.ok(BOT_TEMPLATES.length >= 3);
    assert.ok(BOT_TOOL_OPTIONS.some((t) => t.value === "delegate_to_bot"));
  });

  it("provides 18 harmonious color presets and matches DEFAULT_BOT_COLORS cleanly", () => {
    assert.equal(COLOR_PRESETS.length, 18);
    const ids = new Set(COLOR_PRESETS.map((c) => c.id));
    assert.equal(ids.size, 18);
    assert.equal(
      findMatchingColorPreset(DEFAULT_BOT_COLORS)?.id,
      "vibrant_purple",
    );
    assert.equal(
      findMatchingColorPreset({
        primary: "#e8483f",
        accent: "#ff9e80",
        eyes: "#fff8f6",
      })?.id,
      "coral_red",
    );
    assert.equal(
      findMatchingColorPreset({
        primary: "#123456",
        accent: "#654321",
        eyes: "#ffffff",
      }),
      null,
    );
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
