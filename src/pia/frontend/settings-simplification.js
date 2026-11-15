export const GENERAL_TABS = [
  "Geral",
  "STT",
  "TTS",
  "Música",
  "Imagens · ICE",
  "LLMs",
  "Voz e áudio",
];

export const VISIBLE_GENERAL_FIELDS = new Set([
  "STT_MODEL",
  "STT_LANG",
  "ICE_COMFYUI_URL",
  "ICE_IMAGE_DEFAULT_SIZE",
  "AGE_USER_NAME",
  "LLM_MODEL",
  "LLM_LOCAL_MODEL",
  "START_SOUND",
  "END_SOUND",
]);

export const VISIBLE_MUSIC_FIELDS = new Set(["MUSIC_LOCAL_URL"]);

export const DEFAULT_TTS_PREVIEW_TEXT =
  "Olá, eu sou a PIA e esta é a minha voz.";
export const MAX_TTS_PREVIEW_CHARS = 300;

export const DEFAULT_START_SOUND = "src/sounds/start.mp3";
export const DEFAULT_END_SOUND = "src/sounds/end.mp3";
export const DISABLED_SOUND_VALUE = "disabled";

export const STT_AUTO_LANG_SENTINEL = "__auto__";

export const STT_MODEL_OPTIONS = [
  { value: "large-v3-turbo", label: "Whisper large-v3 turbo (Recomendado)" },
  { value: "medium", label: "Whisper medium (Equilibrado)" },
  { value: "small", label: "Whisper small (Mais rápido)" },
  { value: "base", label: "Whisper base (Leve)" },
  { value: "tiny", label: "Whisper tiny (Ultraleve)" },
];

export const STT_LANG_OPTIONS = [
  { value: STT_AUTO_LANG_SENTINEL, label: "Automático (detectar idioma)" },
  { value: "pt", label: "Português" },
  { value: "en", label: "English" },
  { value: "es", label: "Español" },
  { value: "fr", label: "Français" },
  { value: "de", label: "Deutsch" },
  { value: "it", label: "Italiano" },
];

export const ICE_SIZE_OPTIONS = [
  { value: "1024x1024", label: "Quadrado (1024×1024)" },
  { value: "1280x720", label: "Paisagem (1280×720)" },
  { value: "720x1280", label: "Retrato (720×1280)" },
  { value: "768x768", label: "Compacto (768×768)" },
];

export const LLM_MODEL_OPTIONS = [
  { value: "free", label: "Automático (Gratuito primeiro)" },
  { value: "fast", label: "Rápido" },
  { value: "smart", label: "Avançado" },
  { value: "local", label: "Somente local (Ollama)" },
  { value: "paid", label: "Preferir modelos pagos" },
];

export function isManagedSettingField(sectionId, field) {
  const name = field?.base || field?.name || "";
  if (sectionId === "general") {
    return VISIBLE_GENERAL_FIELDS.has(name);
  }
  if (sectionId === "Apps/music") {
    return VISIBLE_MUSIC_FIELDS.has(name);
  }
  return true;
}

export function safeArray(value) {
  return Array.isArray(value) ? value : [];
}

export function buildManagedInitialValues(sectionId, fields = []) {
  return Object.fromEntries(
    safeArray(fields)
      .filter((field) => isManagedSettingField(sectionId, field))
      .map((field) => [field.name, field.value]),
  );
}

export function mergeSelectOptions(options, currentValue) {
  const safeOptions = safeArray(options);
  const raw = currentValue ?? "";
  if (safeOptions.some((opt) => opt.value === raw)) {
    return safeOptions;
  }
  if (!String(raw).trim()) {
    return safeOptions;
  }
  return [...safeOptions, { value: raw, label: String(raw) }];
}

export function toSttLangSelectValue(value) {
  const clean = String(value ?? "").trim();
  return clean || STT_AUTO_LANG_SENTINEL;
}

export function fromSttLangSelectValue(value) {
  if (!value || value === STT_AUTO_LANG_SENTINEL) {
    return "";
  }
  return String(value).trim();
}

export function isDisabledSoundValue(value) {
  const normalized = String(value ?? "")
    .trim()
    .toLowerCase();
  return ["disabled", "off", "none", "false", "0"].includes(normalized);
}

export function isRecordingSoundsEnabled(values = {}) {
  return (
    !isDisabledSoundValue(values.START_SOUND) ||
    !isDisabledSoundValue(values.END_SOUND)
  );
}

export function toggleRecordingSounds(
  values = {},
  enabled,
  fallbackValues = {},
) {
  if (!enabled) {
    return {
      ...values,
      START_SOUND: DISABLED_SOUND_VALUE,
      END_SOUND: DISABLED_SOUND_VALUE,
    };
  }
  const restorePath = (candidate, defaultPath) => {
    const clean = String(candidate ?? "").trim();
    if (clean && !isDisabledSoundValue(clean)) {
      return clean;
    }
    return defaultPath;
  };
  return {
    ...values,
    START_SOUND: restorePath(
      fallbackValues.START_SOUND ?? values.START_SOUND,
      DEFAULT_START_SOUND,
    ),
    END_SOUND: restorePath(
      fallbackValues.END_SOUND ?? values.END_SOUND,
      DEFAULT_END_SOUND,
    ),
  };
}

export function normalizePreviewText(text) {
  return String(text ?? "").slice(0, MAX_TTS_PREVIEW_CHARS);
}

export function formatVoiceOptionLabel(voice) {
  const name = String(voice?.name || voice?.id || "").trim();
  const lang = String(voice?.lang || "").trim();
  if (!lang || lang.toLowerCase() === "multi") {
    return name;
  }
  return `${name} · ${lang}`;
}

export function resolveTtsPanelState(providers, draft = {}) {
  const safeProviders = safeArray(providers);
  const safeDraft = draft && typeof draft === "object" ? draft : {};
  const activeProvider =
    safeProviders.find((p) => p?.id === safeDraft.provider) ||
    safeProviders[0] ||
    {};
  const activeModels = safeArray(activeProvider.models);
  const activeModel =
    activeModels.find((m) => m?.id === safeDraft.model) ||
    activeModels[0] ||
    {};
  const voices = safeArray(activeModel.voices).length
    ? safeArray(activeModel.voices)
    : safeArray(activeProvider.voices);
  const selectedVoice = voices.some((v) => v?.id === safeDraft.voice)
    ? safeDraft.voice
    : voices[0]?.id || "";
  return {
    providers: safeProviders,
    activeProvider,
    activeModels,
    activeModel,
    voices,
    selectedVoice,
  };
}
