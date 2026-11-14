import { fieldGroup } from "./settings-groups.js";

export const TTS_SETTINGS_PREFIX = "TTS_";

export function isTtsField(field) {
  return fieldGroup(field) === "TTS";
}

export function splitTtsFields(fields = []) {
  const ttsFields = [];
  const otherFields = [];
  for (const field of fields) {
    if (isTtsField(field)) ttsFields.push(field);
    else otherFields.push(field);
  }
  return { ttsFields, otherFields };
}

export function encodeModelKey(provider, model) {
  if (!provider) return "";
  return model ? `${provider}::${model}` : provider;
}

export function decodeModelKey(key) {
  if (typeof key !== "string" || !key) return { provider: "", model: "" };
  const idx = key.indexOf("::");
  if (idx < 0) return { provider: key, model: "" };
  return { provider: key.slice(0, idx), model: key.slice(idx + 2) };
}

export function groupProviders(providers = []) {
  const local = [];
  const remote = [];
  for (const p of providers) {
    if (p?.kind === "local") local.push(p);
    else if (p) remote.push(p);
  }
  return { local, remote };
}

export function findProviderAndModel(providers = [], providerId, modelId) {
  const provider = providers.find((p) => p.id === providerId) || null;
  if (!provider) return { provider: null, model: null };
  const models = provider.models || [];
  const model =
    (modelId && models.find((m) => m.id === modelId)) || models[0] || null;
  return { provider, model };
}

export function speedBounds(model, provider) {
  const speed = model?.capabilities?.speed || provider?.capabilities?.speed;
  const min = Number.isFinite(Number(speed?.min)) ? Number(speed.min) : 0.5;
  const max = Number.isFinite(Number(speed?.max)) ? Number(speed.max) : 2.0;
  const step = Number.isFinite(Number(speed?.step)) ? Number(speed.step) : 0.05;
  const def = Number.isFinite(Number(speed?.default))
    ? Number(speed.default)
    : 1.0;
  return { min, max, step, defaultSpeed: def };
}

export function clampSpeed(value, bounds) {
  const num = Number(value);
  if (!Number.isFinite(num)) return bounds.defaultSpeed;
  return Math.min(bounds.max, Math.max(bounds.min, Number(num.toFixed(2))));
}

export function resolveDraftForModel(
  providers = [],
  nextProviderId,
  nextModelId,
  currentProfile = null,
) {
  const { provider, model } = findProviderAndModel(
    providers,
    nextProviderId,
    nextModelId,
  );
  if (!provider) {
    return {
      provider: nextProviderId || "",
      model: nextModelId || "",
      voice: "",
      speed: 1.0,
    };
  }
  const resolvedModelId = model?.id || nextModelId || "";
  const voices = model?.voices || provider.voices || [];
  const currentVoice = currentProfile?.voice || "";
  const voiceStillValid = voices.some((v) => v.id === currentVoice);
  const voice = voiceStillValid ? currentVoice : voices[0]?.id || "";
  const bounds = speedBounds(model, provider);
  const speed = clampSpeed(
    currentProfile?.speed !== undefined
      ? currentProfile.speed
      : bounds.defaultSpeed,
    bounds,
  );
  return {
    provider: provider.id,
    model: resolvedModelId,
    voice,
    speed,
  };
}

export function buildVoiceSelectGroups(providers = []) {
  const { local, remote } = groupProviders(providers);
  const toGroup = (label, list) => {
    const items = [];
    for (const p of list) {
      const models = p.models?.length
        ? p.models
        : [
            {
              id: p.id,
              name: p.name,
              available: p.available,
              voices: p.voices,
            },
          ];
      for (const m of models) {
        const reason = !m.available
          ? p.kind === "remote"
            ? "sem chave no cofre"
            : "não instalado"
          : "";
        items.push({
          value: encodeModelKey(p.id, m.id),
          label: `${p.name} · ${m.name}${reason ? ` (${reason})` : ""}`,
          disabled: !m.available,
        });
      }
    }
    return items.length ? { group: label, items } : null;
  };
  return [
    toGroup("Modelos Locais", local),
    toGroup("Modelos Remotos", remote),
  ].filter(Boolean);
}

export function formatBytes(bytes) {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n <= 0) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

export function formatReferenceLabel(ref) {
  if (ref === "pia:general") return "Voz Geral da PIA";
  if (ref === "native:secretaria") return "Bot Nativo: Secretária";
  if (typeof ref === "string" && ref.startsWith("dynamic:"))
    return `Bot Dinâmico (${ref.slice("dynamic:".length)})`;
  return String(ref || "");
}
