import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_END_SOUND,
  DEFAULT_START_SOUND,
  DEFAULT_TTS_PREVIEW_TEXT,
  DISABLED_SOUND_VALUE,
  GENERAL_TABS,
  MAX_TTS_PREVIEW_CHARS,
  STT_AUTO_LANG_SENTINEL,
  buildManagedInitialValues,
  formatVoiceOptionLabel,
  fromSttLangSelectValue,
  isRecordingSoundsEnabled,
  mergeSelectOptions,
  normalizePreviewText,
  toSttLangSelectValue,
  toggleRecordingSounds,
} from "./settings-simplification.js";

describe("settings-simplification", () => {
  it("exposes all 7 simplified general settings tabs including Música", () => {
    assert.deepEqual(GENERAL_TABS, [
      "Geral",
      "STT",
      "TTS",
      "Música",
      "Imagens · ICE",
      "LLMs",
      "Voz e áudio",
    ]);
  });

  it("filters out hidden technical and secret fields from general settings save payload", () => {
    const schemaFields = [
      { name: "HOST", value: "0.0.0.0" },
      { name: "PORT", value: "8762" },
      { name: "OPENAI_COMPAT_API_KEY", value: "", configured: true },
      { name: "OPENAI_COMPAT_TIMEOUT_SECONDS", value: "180" },
      { name: "STT_MODEL", value: "large-v3-turbo" },
      { name: "STT_LANG", value: "pt" },
      { name: "STT_DEVICE", value: "cpu" },
      { name: "STT_COMPUTE_TYPE", value: "int8" },
      { name: "STT_RECOVERY_ENABLED", value: "true" },
      { name: "TTS_DEVICE", value: "cuda" },
      { name: "TTS_LLM_MODEL", value: "free" },
      { name: "ICE_COMFYUI_URL", value: "http://127.0.0.1:8188" },
      { name: "ICE_IMAGE_DEFAULT_SIZE", value: "1024x1024" },
      { name: "ICE_IMAGE_STEPS", value: "4" },
      { name: "ICE_IMAGE_CFG", value: "1.0" },
      { name: "AGE_USER_NAME", value: "Diogo" },
      { name: "AGE_GEMINI_API_KEY", value: "", configured: true },
      { name: "LLM_MODEL", value: "free" },
      { name: "LLM_LOCAL_MODEL", value: "ollama/qwen3:8b" },
      { name: "LLM_PROVIDERS", value: "gemini,groq,local" },
      { name: "OVE_RATE", value: "16000" },
      { name: "OVE_THRESHOLD", value: "0.5" },
      { name: "START_SOUND", value: "src/sounds/start.mp3" },
      { name: "END_SOUND", value: "src/sounds/end.mp3" },
    ];

    const managed = buildManagedInitialValues("general", schemaFields);
    assert.deepEqual(Object.keys(managed).sort(), [
      "AGE_USER_NAME",
      "END_SOUND",
      "ICE_COMFYUI_URL",
      "ICE_IMAGE_DEFAULT_SIZE",
      "LLM_LOCAL_MODEL",
      "LLM_MODEL",
      "START_SOUND",
      "STT_LANG",
      "STT_MODEL",
    ]);
  });

  it("limits Apps/music managed schema fields and leaves other sections untouched", () => {
    const musicFields = [
      { name: "MUSIC_LOCAL_URL", value: "http://127.0.0.1:8015" },
      { name: "MUSIC_LOCAL_KEY", value: "" },
      { name: "MUSIC_GEMINI_MODEL", value: "lyria-3.5" },
    ];
    assert.deepEqual(buildManagedInitialValues("Apps/music", musicFields), {
      MUSIC_LOCAL_URL: "http://127.0.0.1:8015",
    });

    const otherFields = [{ name: "CUSTOM_KEY", value: "abc" }];
    assert.deepEqual(
      buildManagedInitialValues("Apps/screenshots", otherFields),
      { CUSTOM_KEY: "abc" },
    );
  });

  it("maps automatic STT language cleanly and preserves custom options", () => {
    assert.equal(toSttLangSelectValue(""), STT_AUTO_LANG_SENTINEL);
    assert.equal(fromSttLangSelectValue(STT_AUTO_LANG_SENTINEL), "");
    assert.equal(toSttLangSelectValue("pt"), "pt");
    assert.equal(fromSttLangSelectValue("pt"), "pt");

    const merged = mergeSelectOptions(
      [{ value: "free", label: "Auto" }],
      "paid-pro",
    );
    assert.deepEqual(merged, [
      { value: "free", label: "Auto" },
      { value: "paid-pro", label: "paid-pro" },
    ]);
  });

  it("toggles recording sounds with non-empty disabled marker and restores paths", () => {
    assert.equal(
      isRecordingSoundsEnabled({ START_SOUND: "", END_SOUND: "" }),
      true,
    );
    const disabled = toggleRecordingSounds(
      { START_SOUND: "custom/start.wav", END_SOUND: "custom/end.wav" },
      false,
    );
    assert.equal(disabled.START_SOUND, DISABLED_SOUND_VALUE);
    assert.equal(disabled.END_SOUND, DISABLED_SOUND_VALUE);
    assert.equal(isRecordingSoundsEnabled(disabled), false);

    const restored = toggleRecordingSounds(disabled, true, {
      START_SOUND: "custom/start.wav",
      END_SOUND: "",
    });
    assert.equal(restored.START_SOUND, "custom/start.wav");
    assert.equal(restored.END_SOUND, DEFAULT_END_SOUND);

    const defaulted = toggleRecordingSounds(disabled, true, disabled);
    assert.equal(defaulted.START_SOUND, DEFAULT_START_SOUND);
    assert.equal(defaulted.END_SOUND, DEFAULT_END_SOUND);
  });

  it("normalizes TTS preview text length and formats all 10 Supertonic 3 voices cleanly", () => {
    assert.equal(
      DEFAULT_TTS_PREVIEW_TEXT,
      "Olá, eu sou a PIA e esta é a minha voz.",
    );
    const tooLong = "a".repeat(MAX_TTS_PREVIEW_CHARS + 50);
    assert.equal(normalizePreviewText(tooLong).length, MAX_TTS_PREVIEW_CHARS);

    const supertonicVoices = [
      "Voz feminina 1",
      "Voz feminina 2",
      "Voz feminina 3",
      "Voz feminina 4",
      "Voz feminina 5",
      "Voz masculina 1",
      "Voz masculina 2",
      "Voz masculina 3",
      "Voz masculina 4",
      "Voz masculina 5",
    ];
    for (const name of supertonicVoices) {
      assert.equal(
        formatVoiceOptionLabel({ id: "X", name, lang: "multi" }),
        name,
      );
    }
    assert.equal(
      formatVoiceOptionLabel({ id: "pf_dora", name: "Dora", lang: "pt-BR" }),
      "Dora · pt-BR",
    );
  });
});
