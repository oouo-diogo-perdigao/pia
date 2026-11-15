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

export function normalizeInstallJob(raw, fallbackJobId = "") {
  if (!raw || typeof raw !== "object") return null;
  const progress =
    raw.progress && typeof raw.progress === "object" ? raw.progress : {};
  const completedBytes = Number.isFinite(Number(progress.completed_bytes))
    ? Number(progress.completed_bytes)
    : null;
  const totalBytes =
    Number.isFinite(Number(progress.total_bytes)) &&
    Number(progress.total_bytes) > 0
      ? Number(progress.total_bytes)
      : null;
  let percent = Number.isFinite(Number(progress.percent))
    ? Number(progress.percent)
    : null;
  if (percent === null && completedBytes !== null && totalBytes !== null) {
    percent = Math.min(
      100,
      Math.round((completedBytes / totalBytes) * 1000) / 10,
    );
  }
  if (raw.type === "done" || raw.state === "done") {
    return {
      job_id: raw.job_id || fallbackJobId,
      state: "done",
      phase: "done",
      progress: {
        completed_bytes: completedBytes ?? totalBytes,
        total_bytes: totalBytes,
        percent: 100,
      },
      error: null,
    };
  }
  if (raw.type === "error" || raw.state === "error") {
    return {
      job_id: raw.job_id || fallbackJobId,
      state: "error",
      phase:
        raw.code === "cancelled" || raw.phase === "cancelled"
          ? "cancelled"
          : "error",
      progress: {
        completed_bytes: completedBytes,
        total_bytes: totalBytes,
        percent,
      },
      error:
        typeof raw.error === "object" && raw.error
          ? raw.error
          : {
              code: raw.code || "error",
              message: raw.error || "Erro na instalação.",
            },
    };
  }
  return {
    job_id: raw.job_id || fallbackJobId,
    state: raw.state || "running",
    phase: raw.phase || "downloading",
    progress: {
      completed_bytes: completedBytes,
      total_bytes: totalBytes,
      percent,
    },
    error: raw.error || null,
  };
}

export function mergeInstallJob(prev, next) {
  if (!next) return prev || null;
  if (!prev || (prev.job_id && next.job_id && prev.job_id !== next.job_id)) {
    return next;
  }
  if (next.state === "done" || next.state === "error") return next;
  if (prev.state === "done" || prev.state === "error") return prev;
  const prevBytes = prev.progress?.completed_bytes ?? -1;
  const nextBytes = next.progress?.completed_bytes ?? -1;
  if (prevBytes >= 0 && nextBytes >= 0 && nextBytes < prevBytes) {
    return prev;
  }
  if (prev.state === "running" && next.state === "queued") {
    return prev;
  }
  return next;
}

export function resolveLocalModelBadges(
  model = {},
  { isSavedActive = false, jobSnapshot = null } = {},
) {
  const instState =
    jobSnapshot?.state === "running" || jobSnapshot?.state === "queued"
      ? "installing"
      : model.installation?.state ||
        (model.installed ? "installed" : "not_installed");
  const isInstalling = instState === "installing" || Boolean(model.installing);
  const isReady = Boolean(model.installed && model.available);

  const activeBadge =
    isSavedActive && isReady
      ? { label: "Ativo", color: "blue", variant: "filled" }
      : null;

  let statusBadge;
  if (isInstalling) {
    statusBadge = {
      label: "Instalando…",
      color: "violet",
      variant: "light",
      loading: true,
    };
  } else if (isReady) {
    statusBadge = { label: "Instalado", color: "green", variant: "light" };
  } else if (instState === "error") {
    statusBadge = { label: "Erro", color: "red", variant: "light" };
  } else if (isSavedActive) {
    statusBadge = {
      label: "Selecionado (requer instalação)",
      color: "yellow",
      variant: "light",
    };
  } else {
    statusBadge = { label: "Não instalado", color: "gray", variant: "light" };
  }

  return {
    instState,
    isInstalling,
    isReady,
    activeBadge,
    statusBadge,
    pendingSelectionBadge:
      isSavedActive && !isReady && isInstalling
        ? { label: "Selecionado", color: "yellow", variant: "light" }
        : null,
  };
}
