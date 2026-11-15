import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  isTtsField,
  splitTtsFields,
  encodeModelKey,
  decodeModelKey,
  groupProviders,
  speedBounds,
  clampSpeed,
  resolveDraftForModel,
  buildVoiceSelectGroups,
  formatBytes,
  formatReferenceLabel,
  normalizeInstallJob,
  mergeInstallJob,
  resolveLocalModelBadges,
} from "./tts-helpers.js";

const SAMPLE_PROVIDERS = [
  {
    id: "kokoro",
    name: "Kokoro",
    kind: "local",
    available: true,
    models: [
      {
        id: "kokoro-82m",
        name: "Kokoro 82M",
        available: true,
        capabilities: {
          speed: { min: 0.5, max: 2.0, step: 0.05, default: 1.0 },
        },
        voices: [
          { id: "pf_dora", label: "Dora (pt-BR)" },
          { id: "pm_alex", label: "Alex (pt-BR)" },
        ],
      },
    ],
  },
  {
    id: "qwen",
    name: "Qwen3-TTS",
    kind: "local",
    available: false,
    models: [
      {
        id: "qwen3-tts-0.6b",
        name: "Qwen3 0.6B",
        available: false,
        capabilities: {
          speed: { min: 0.75, max: 1.5, step: 0.05, default: 1.0 },
        },
        voices: [{ id: "vivian", label: "Vivian" }],
      },
    ],
  },
  {
    id: "openai",
    name: "OpenAI TTS",
    kind: "remote",
    available: true,
    models: [
      {
        id: "gpt-4o-mini-tts",
        name: "gpt-4o-mini-tts",
        available: true,
        capabilities: {
          speed: { min: 0.25, max: 4.0, step: 0.05, default: 1.0 },
        },
        voices: [{ id: "alloy", label: "Alloy" }],
      },
    ],
  },
];

describe("tts-helpers", () => {
  it("separates TTS fields from other general settings fields", () => {
    const fields = [
      { base: "LLM_PROVIDER", key: "LLM_PROVIDER" },
      { base: "TTS_DEVICE", key: "TTS_DEVICE" },
      { base: "TTS_LLM_MODEL", key: "TTS_LLM_MODEL" },
      { base: "MAX_TOKENS", key: "MAX_TOKENS" },
    ];
    assert.equal(isTtsField(fields[1]), true);
    assert.equal(isTtsField(fields[0]), false);
    const { ttsFields, otherFields } = splitTtsFields(fields);
    assert.deepEqual(
      ttsFields.map((f) => f.base),
      ["TTS_DEVICE", "TTS_LLM_MODEL"],
    );
    assert.deepEqual(
      otherFields.map((f) => f.base),
      ["LLM_PROVIDER", "MAX_TOKENS"],
    );
  });

  it("encodes and decodes model keys cleanly", () => {
    const key = encodeModelKey("kokoro", "kokoro-82m");
    assert.equal(key, "kokoro::kokoro-82m");
    assert.deepEqual(decodeModelKey(key), {
      provider: "kokoro",
      model: "kokoro-82m",
    });
    assert.deepEqual(decodeModelKey(""), { provider: "", model: "" });
  });

  it("groups local vs remote providers and builds grouped select options", () => {
    const grouped = groupProviders(SAMPLE_PROVIDERS);
    assert.equal(grouped.local.length, 2);
    assert.equal(grouped.remote.length, 1);

    const groups = buildVoiceSelectGroups(SAMPLE_PROVIDERS);
    assert.equal(groups.length, 2);
    assert.equal(groups[0].group, "Modelos Locais");
    assert.equal(groups[0].items[1].disabled, true);
    assert.match(groups[0].items[1].label, /não instalado/);
    assert.equal(groups[1].group, "Modelos Remotos");
    assert.equal(groups[1].items[0].disabled, false);
  });

  it("resolves drafts without throwing when provider or profile is null and resets invalid voices", () => {
    const empty = resolveDraftForModel(SAMPLE_PROVIDERS, "", "", null);
    assert.deepEqual(empty, {
      provider: "",
      model: "",
      voice: "",
      speed: 1.0,
    });

    const switched = resolveDraftForModel(
      SAMPLE_PROVIDERS,
      "kokoro",
      "kokoro-82m",
      {
        provider: "openai",
        model: "gpt-4o-mini-tts",
        voice: "alloy",
        speed: 3.5,
      },
    );
    assert.deepEqual(switched, {
      provider: "kokoro",
      model: "kokoro-82m",
      voice: "pf_dora",
      speed: 2.0,
    });

    const keptVoice = resolveDraftForModel(
      SAMPLE_PROVIDERS,
      "kokoro",
      "kokoro-82m",
      {
        provider: "kokoro",
        model: "kokoro-82m",
        voice: "pm_alex",
        speed: 1.25,
      },
    );
    assert.deepEqual(keptVoice, {
      provider: "kokoro",
      model: "kokoro-82m",
      voice: "pm_alex",
      speed: 1.25,
    });
  });

  it("clamps speed and formats bytes and 409 reference labels", () => {
    const bounds = speedBounds(
      SAMPLE_PROVIDERS[0].models[0],
      SAMPLE_PROVIDERS[0],
    );
    assert.equal(clampSpeed(0.1, bounds), 0.5);
    assert.equal(clampSpeed("not-a-number", bounds), 1.0);
    assert.equal(formatBytes(0), "");
    assert.equal(formatBytes(1536), "1.5 KB");
    assert.equal(formatBytes(330 * 1024 * 1024), "330.0 MB");
    assert.equal(formatReferenceLabel("pia:general"), "Voz Geral da PIA");
    assert.equal(
      formatReferenceLabel("native:secretaria"),
      "Bot Nativo: Secretária",
    );
    assert.equal(
      formatReferenceLabel("dynamic:abc-123"),
      "Bot Dinâmico (abc-123)",
    );
  });

  it("normalizes SSE and polling progress snapshots and avoids stale regressions", () => {
    const sseProg = normalizeInstallJob(
      {
        type: "progress",
        state: "running",
        phase: "downloading",
        progress: {
          completed_bytes: 52428800,
          total_bytes: 104857600,
          percent: 50.0,
        },
      },
      "job-1",
    );
    assert.equal(sseProg.job_id, "job-1");
    assert.equal(sseProg.progress.percent, 50.0);
    assert.equal(sseProg.progress.completed_bytes, 52428800);

    const stalePoll = normalizeInstallJob({
      job_id: "job-1",
      state: "running",
      phase: "downloading",
      progress: {
        completed_bytes: 10485760,
        total_bytes: 104857600,
        percent: 10.0,
      },
    });
    const merged = mergeInstallJob(sseProg, stalePoll);
    assert.equal(merged.progress.percent, 50.0);

    const doneEvt = normalizeInstallJob(
      {
        type: "done",
        progress: {
          completed_bytes: 104857600,
          total_bytes: 104857600,
          percent: 100,
        },
      },
      "job-1",
    );
    assert.equal(mergeInstallJob(merged, doneEvt).state, "done");
    assert.equal(mergeInstallJob(merged, doneEvt).progress.percent, 100);
  });

  it("only shows Ativo when installed && available, otherwise Selecionado (requer instalação)", () => {
    const readySelected = resolveLocalModelBadges(
      {
        installed: true,
        available: true,
        installation: { state: "installed" },
      },
      { isSavedActive: true },
    );
    assert.equal(readySelected.activeBadge?.label, "Ativo");
    assert.equal(readySelected.statusBadge?.label, "Instalado");

    const missingSelected = resolveLocalModelBadges(
      {
        installed: false,
        available: false,
        installation: { state: "not_installed" },
      },
      { isSavedActive: true },
    );
    assert.equal(missingSelected.activeBadge, null);
    assert.equal(
      missingSelected.statusBadge?.label,
      "Selecionado (requer instalação)",
    );

    const halfMissing = resolveLocalModelBadges(
      {
        installed: true,
        available: false,
        installation: { state: "not_installed" },
      },
      { isSavedActive: true },
    );
    assert.equal(halfMissing.activeBadge, null);
    assert.equal(
      halfMissing.statusBadge?.label,
      "Selecionado (requer instalação)",
    );

    const missingUnselected = resolveLocalModelBadges(
      {
        installed: false,
        available: false,
        installation: { state: "not_installed" },
      },
      { isSavedActive: false },
    );
    assert.equal(missingUnselected.activeBadge, null);
    assert.equal(missingUnselected.statusBadge?.label, "Não instalado");
  });
});
