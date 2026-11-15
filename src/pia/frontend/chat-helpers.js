export const CHAT_AUTO_MODEL_SENTINEL = "__auto__";

const TIER_NAMES = new Set(["local", "free", "paid", "all"]);

const PROVIDER_LABELS = {
  gemini: "Gemini",
  groq: "Groq",
  local: "Local",
  openai: "OpenAI",
  anthropic: "Anthropic",
  openrouter: "OpenRouter",
};

export function formatProviderName(provider) {
  const key = String(provider || "")
    .trim()
    .toLowerCase();
  if (!key) return "";
  return PROVIDER_LABELS[key] || key.charAt(0).toUpperCase() + key.slice(1);
}

export function splitModelProvider(modelId, explicitProvider = "") {
  const raw = String(modelId || "").trim();
  const prov = String(explicitProvider || "")
    .trim()
    .toLowerCase();
  if (!raw) {
    return { provider: prov, shortModel: "" };
  }
  const slash = raw.indexOf("/");
  if (slash > 0) {
    return {
      provider: prov || raw.slice(0, slash).toLowerCase(),
      shortModel: raw.slice(slash + 1),
    };
  }
  return { provider: prov, shortModel: raw };
}

function normalizeModelEntry(entry) {
  if (!entry) return null;
  if (typeof entry === "string") {
    const value = entry.trim();
    if (!value || value === CHAT_AUTO_MODEL_SENTINEL || value === "auto") {
      return null;
    }
    const { provider, shortModel } = splitModelProvider(value);
    const providerLabel = formatProviderName(provider);
    return {
      value,
      label: providerLabel ? `${shortModel} (${providerLabel})` : value,
      provider,
      tier: "",
      disabled: false,
    };
  }
  if (typeof entry !== "object") return null;
  const rawId = String(entry.id || entry.value || "").trim();
  const rawProvider = String(entry.provider || "")
    .trim()
    .toLowerCase();
  if (
    rawId === "auto" ||
    rawId === CHAT_AUTO_MODEL_SENTINEL ||
    rawProvider === "auto"
  ) {
    return null;
  }
  const value = String(rawId || entry.model || "").trim();
  if (!value) return null;
  const { provider, shortModel } = splitModelProvider(
    entry.model || value,
    entry.provider,
  );
  const providerLabel = formatProviderName(provider);
  const tier = String(entry.tier || "")
    .trim()
    .toLowerCase();
  const baseLabel = String(
    entry.label || entry.name || shortModel || value,
  ).trim();
  const suffixParts = [];
  if (
    providerLabel &&
    !baseLabel.toLowerCase().includes(provider.toLowerCase())
  ) {
    suffixParts.push(providerLabel);
  }
  if (tier && !baseLabel.toLowerCase().includes(tier)) {
    suffixParts.push(tier);
  }
  const label =
    suffixParts.length > 0
      ? `${baseLabel} (${suffixParts.join(" · ")})`
      : baseLabel;
  const disabled = entry.available === false || entry.disabled === true;
  return {
    value,
    label,
    provider,
    tier,
    disabled,
  };
}

function splitSettingCsv(raw) {
  return String(raw || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function collectSettingsFallbackModels(settings) {
  if (!settings || typeof settings !== "object") return [];
  const entries = [];
  const addProviderList = (raw, provider, tier) => {
    for (const name of splitSettingCsv(raw)) {
      const value =
        provider && provider !== "local" && !name.includes("/")
          ? `${provider}/${name}`
          : name;
      entries.push({ value, provider, tier });
    }
  };
  addProviderList(settings.LLM_GEMINI_FREE_MODELS, "gemini", "free");
  addProviderList(settings.LLM_GEMINI_PAID_MODELS, "gemini", "paid");
  addProviderList(settings.LLM_GROQ_FREE_MODELS, "groq", "free");
  addProviderList(settings.LLM_GROQ_PAID_MODELS, "groq", "paid");
  addProviderList(settings.LLM_OPENROUTER_FREE_MODELS, "openrouter", "free");
  addProviderList(settings.LLM_OPENROUTER_PAID_MODELS, "openrouter", "paid");
  addProviderList(settings.LLM_OPENAI_PAID_MODELS, "openai", "paid");
  addProviderList(settings.LLM_ANTHROPIC_PAID_MODELS, "anthropic", "paid");
  addProviderList(
    settings.LLM_LOCAL_MODELS || settings.LLM_LOCAL_MODEL,
    "local",
    "local",
  );

  const active = String(settings.LLM_MODEL || "").trim();
  if (active && !TIER_NAMES.has(active.toLowerCase())) {
    entries.unshift(active);
  }
  return entries;
}

/**
 * Builds deduplicated Mantine <Select> options for the chat model selector.
 * Keeps `Automático (Padrão)` at the top using CHAT_AUTO_MODEL_SENTINEL.
 */
export function buildChatModelOptions(modelsResponse, settingsResponse) {
  const autoOption = {
    value: CHAT_AUTO_MODEL_SENTINEL,
    label: "Automático (Padrão)",
    provider: "",
    tier: "auto",
    disabled: false,
  };

  let rawList = [];
  if (Array.isArray(modelsResponse)) {
    rawList = modelsResponse;
  } else if (Array.isArray(modelsResponse?.models)) {
    rawList = modelsResponse.models;
  } else if (Array.isArray(modelsResponse?.data)) {
    rawList = modelsResponse.data;
  }

  const seen = new Set();
  const catalogOptions = [];
  for (const item of rawList) {
    const normalized = normalizeModelEntry(item);
    if (!normalized || seen.has(normalized.value)) continue;
    seen.add(normalized.value);
    catalogOptions.push(normalized);
  }

  const hasCatalog = catalogOptions.length > 0;
  if (!hasCatalog && settingsResponse) {
    for (const item of collectSettingsFallbackModels(settingsResponse)) {
      const normalized = normalizeModelEntry(item);
      if (!normalized || seen.has(normalized.value)) continue;
      seen.add(normalized.value);
      catalogOptions.push(normalized);
    }
  }

  const defaultModel = String(
    modelsResponse?.current || modelsResponse?.default || "",
  ).trim();

  return {
    options: [autoOption, ...catalogOptions],
    defaultModel,
    hasCatalog,
  };
}

export function normalizeSelectedModel(value) {
  const raw = String(value || "").trim();
  if (!raw || raw === CHAT_AUTO_MODEL_SENTINEL || raw === "auto") {
    return "";
  }
  return raw;
}

export function buildChatSendPayload({ chat, text, request, model }) {
  const payload = { chat, text, request };
  const resolvedModel = normalizeSelectedModel(model);
  if (resolvedModel) {
    payload.model = resolvedModel;
  }
  return payload;
}

export function buildChatActionPayload({ chat, id, action, text, model }) {
  const payload = { chat, id, action };
  if (text !== undefined) {
    payload.text = text;
  }
  const resolvedModel = normalizeSelectedModel(model);
  if (action === "retry" && resolvedModel) {
    payload.model = resolvedModel;
  }
  return payload;
}

function normalizeToolsList(rawTools) {
  if (!rawTools) return [];
  const items = Array.isArray(rawTools)
    ? rawTools
    : typeof rawTools === "string"
      ? splitSettingCsv(rawTools)
      : [];
  const seen = new Set();
  const result = [];
  for (const item of items) {
    if (!item) continue;
    let name = "";
    let detail = "";
    if (typeof item === "string") {
      name = item.trim();
    } else if (typeof item === "object") {
      name = String(item.name || item.tool || item.id || "").trim();
      detail = String(item.server || item.summary || item.status || "").trim();
    }
    if (!name || seen.has(name)) continue;
    seen.add(name);
    result.push({ name, detail });
  }
  return result;
}

/**
 * Formats model, provider, and tool usage metadata for the assistant "i" popover.
 */
export function formatMessageInfo(record) {
  const meta =
    record?.meta && typeof record.meta === "object"
      ? record.meta
      : record?.metadata && typeof record.metadata === "object"
        ? record.metadata
        : {};
  const rawModel = String(record?.model || meta.model || "").trim();
  const rawProvider = String(record?.provider || meta.provider || "").trim();
  const { provider, shortModel } = splitModelProvider(rawModel, rawProvider);
  const providerLabel = formatProviderName(provider);
  const tools = normalizeToolsList(
    record?.tools_used ??
      record?.tools ??
      record?.mcp_tools ??
      meta.tools_used ??
      meta.tools,
  );
  const modelDisplay = rawModel
    ? providerLabel
      ? `${shortModel || rawModel} (${providerLabel})`
      : shortModel || rawModel
    : providerLabel
      ? `Automático (${providerLabel})`
      : "";

  return {
    model: rawModel,
    shortModel,
    provider,
    providerLabel,
    modelDisplay,
    tools,
    hasMetadata: Boolean(rawModel || provider || tools.length > 0),
  };
}

const IMAGE_EXT_RE = /\.(png|jpe?g|webp|gif|svg)(\?.*)?$/i;
const AUDIO_EXT_RE = /\.(mp3|wav|ogg|opus|m4a|flac|aac)(\?.*)?$/i;

export function isImageUrl(url) {
  const value = String(url || "").trim();
  if (!value) return false;
  return (
    value.startsWith("data:image/") ||
    value.startsWith("/api/pia/chat/assets/") ||
    value.startsWith("/api/pia/apps/screenshots/") ||
    IMAGE_EXT_RE.test(value)
  );
}

export function isAudioUrl(url) {
  const value = String(url || "").trim();
  if (!value) return false;
  return (
    value.startsWith("data:audio/") ||
    value.startsWith("/api/pia/music/files/") ||
    value.startsWith("/api/pia/tts/previews/") ||
    AUDIO_EXT_RE.test(value)
  );
}

/**
 * Extracts structured MCP attachments (screenshots, Suno audio, bucket/transcript files)
 * from a message record while skipping assets already embedded verbatim in Markdown content.
 */
export function extractMessageMedia(record) {
  const content = String(record?.content || "");
  const images = [];
  const audios = [];
  const files = [];
  const seenUrls = new Set();

  const pushUnique = (target, item) => {
    const key = String(item.url || item.name || "").trim();
    if (!key || seenUrls.has(key)) return;
    seenUrls.add(key);
    target.push(item);
  };

  const handleCandidate = (entry) => {
    if (!entry) return;
    if (typeof entry === "string") {
      const url = entry.trim();
      if (!url) return;
      if (isImageUrl(url)) {
        if (!content.includes(url)) {
          pushUnique(images, {
            url,
            title: "Captura / Imagem",
            downloadUrl: url,
          });
        }
      } else if (isAudioUrl(url)) {
        if (!content.includes(url)) {
          pushUnique(audios, { url, title: "Áudio gerado", downloadUrl: url });
        }
      } else if (!content.includes(url)) {
        pushUnique(files, {
          url,
          name: url.split("/").pop()?.split("?")[0] || "Arquivo",
          kind: "file",
        });
      }
      return;
    }
    if (typeof entry !== "object") return;
    const url = String(
      entry.url ||
        entry.src ||
        entry.href ||
        entry.download_url ||
        entry.image_url ||
        entry.screenshot_url ||
        entry.audio_url ||
        entry.file_url ||
        "",
    ).trim();
    const kind = String(
      entry.kind || entry.type || entry.mime || "",
    ).toLowerCase();
    const title = String(
      entry.title ||
        entry.name ||
        entry.filename ||
        entry.key ||
        (url ? url.split("/").pop()?.split("?")[0] : "") ||
        "Anexo",
    ).trim();

    if (
      kind.includes("image") ||
      kind.includes("screenshot") ||
      isImageUrl(url)
    ) {
      if (url && !content.includes(url)) {
        pushUnique(images, {
          url,
          title: entry.title || entry.alt || "Captura / Imagem",
          downloadUrl: entry.download_url || url,
        });
      }
      return;
    }

    if (kind.includes("audio") || kind.includes("music") || isAudioUrl(url)) {
      if (url && !content.includes(url)) {
        pushUnique(audios, {
          url,
          title: entry.title || "Música / Áudio gerado",
          downloadUrl: entry.download_url || url,
        });
      }
      return;
    }

    if (url || entry.transcript || entry.bucket || entry.key) {
      pushUnique(files, {
        url,
        name: title,
        kind: kind || (entry.bucket ? "bucket" : "file"),
        bucket: String(entry.bucket || "").trim(),
        transcript: String(entry.transcript || entry.preview || "").trim(),
      });
    }
  };

  const lists = [
    record?.attachments,
    record?.media,
    record?.artifacts,
    record?.mcp_results,
    record?.files,
    record?.bucket_files,
  ];
  for (const list of lists) {
    if (Array.isArray(list)) {
      list.forEach(handleCandidate);
    }
  }

  const singleFields = [
    record?.screenshot
      ? { type: "screenshot", url: record.screenshot, title: "Screenshot" }
      : null,
    record?.screenshot_url
      ? { type: "screenshot", url: record.screenshot_url, title: "Screenshot" }
      : null,
    record?.image_url
      ? { type: "image", url: record.image_url, title: "Imagem" }
      : null,
    record?.audio_url
      ? { type: "audio", url: record.audio_url, title: "Música / Áudio gerado" }
      : null,
    record?.music,
  ];
  singleFields.forEach(handleCandidate);

  return { images, audios, files };
}

/**
 * Strips basic Markdown syntax before sending assistant/user replies to TTS.
 */
export function prepareSpeechText(content) {
  return String(content || "")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/!\[[^\]]*\]\([^)]+\)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[#*_`~>-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Manages Sound <-> Stop state transitions and singleton audio playback for chat messages.
 * Immediately switches to Stop on speak(), supports clicking Stop or switching messages,
 * and restores the Sound icon automatically on stop, end, or error.
 */
export function createChatSpeechController({
  synthesize,
  cancelRemote,
  watch,
  pollJob,
  createAudio = (url) => new Audio(url),
  revokeObjectUrl = (url) => {
    try {
      URL.revokeObjectURL(url);
    } catch {}
  },
  onStateChange,
  onError,
  pollIntervalMs = 600,
} = {}) {
  let active = null;
  let nextToken = 0;

  function emit(activeId = null, status = "idle") {
    onStateChange?.({ activeId, status });
  }

  function stopAudio(audio) {
    if (!audio) return;
    try {
      audio.onended = null;
      audio.onerror = null;
      audio.pause?.();
      if ("currentTime" in audio) {
        audio.currentTime = 0;
      }
    } catch {}
  }

  function cleanupEntry(entry) {
    if (!entry) return;
    if (entry.pollTimer != null) {
      clearInterval(entry.pollTimer);
      entry.pollTimer = null;
    }
    try {
      entry.source?.close?.();
    } catch {}
    entry.source = null;
    try {
      entry.abortController?.abort?.();
    } catch {}
    stopAudio(entry.audio);
    entry.audio = null;
    if (entry.objectUrl) {
      revokeObjectUrl(entry.objectUrl);
      entry.objectUrl = null;
    }
  }

  function stop() {
    const current = active;
    if (!current) {
      return false;
    }
    active = null;
    current.cancelled = true;
    cleanupEntry(current);
    if (current.remoteJobId || current.usedRemoteSpeak) {
      Promise.resolve(cancelRemote?.(current)).catch(() => {});
    }
    current.resolvePromise?.(false);
    emit(null, "idle");
    return true;
  }

  async function speak(record) {
    const messageId = record?.id;
    if (messageId == null) return false;

    const text = prepareSpeechText(record?.content);
    if (!text) return false;

    stop();

    const token = ++nextToken;
    const abortController =
      typeof AbortController !== "undefined" ? new AbortController() : null;

    const entry = {
      token,
      messageId,
      audio: null,
      objectUrl: null,
      source: null,
      pollTimer: null,
      abortController,
      cancelled: false,
      settled: false,
      playbackStarted: false,
      remoteJobId: null,
      usedRemoteSpeak: false,
      resolvePromise: null,
    };
    active = entry;
    emit(messageId, "loading");

    const finish = (err, played = false) => {
      if (entry.settled) return;
      entry.settled = true;
      cleanupEntry(entry);
      if (active === entry) {
        active = null;
        emit(null, "idle");
      }
      if (err && !entry.cancelled) {
        onError?.(err);
      }
      entry.resolvePromise?.(played);
    };

    try {
      const spec = await synthesize(record, text, {
        signal: abortController?.signal,
      });

      if (entry.cancelled || active !== entry) {
        return false;
      }

      if (!spec) {
        finish(Error("Não foi possível gerar áudio para esta mensagem."));
        return false;
      }

      if (spec.objectUrl) {
        entry.objectUrl = spec.objectUrl;
      }
      if (spec.jobId || spec.job) {
        entry.remoteJobId = spec.jobId || spec.job;
      }

      const startAudioUrl = (audioUrl, isObjectUrl = false) => {
        if (
          entry.settled ||
          entry.cancelled ||
          entry.playbackStarted ||
          active !== entry
        ) {
          if (isObjectUrl && audioUrl) revokeObjectUrl(audioUrl);
          return;
        }
        entry.playbackStarted = true;
        if (isObjectUrl) entry.objectUrl = audioUrl;
        if (entry.pollTimer != null) {
          clearInterval(entry.pollTimer);
          entry.pollTimer = null;
        }
        try {
          entry.source?.close?.();
        } catch {}
        entry.source = null;

        try {
          const audio = createAudio(audioUrl);
          entry.audio = audio;
          emit(messageId, "playing");
          audio.onended = () => finish(null, true);
          audio.onerror = () =>
            finish(Error("Falha ao reproduzir áudio da mensagem."));
          Promise.resolve(audio.play()).catch((err) => finish(err));
        } catch (err) {
          finish(err);
        }
      };

      return await new Promise((resolve) => {
        entry.resolvePromise = resolve;

        const directUrl = spec.audioUrl || spec.audio_url || spec.objectUrl;
        if (directUrl) {
          startAudioUrl(directUrl, Boolean(spec.objectUrl));
          return;
        }

        if (spec.serverSide) {
          entry.usedRemoteSpeak = true;
          emit(messageId, "playing");
          if (spec.job && watch) {
            entry.source = watch(spec.job, (ev) => {
              if (entry.cancelled || active !== entry) return;
              if (ev?.type === "done") {
                const doneUrl = ev?.result?.audio_url || ev?.audio_url;
                if (doneUrl) startAudioUrl(doneUrl);
                else finish(null, true);
              } else if (ev?.type === "error") {
                finish(Error(ev?.error || "Erro ao sintetizar áudio."));
              }
            });
            return;
          }
          finish(null, true);
          return;
        }

        const jobId = entry.remoteJobId;
        if (!jobId) {
          finish(Error("Resposta de áudio inválida."));
          return;
        }

        if (watch) {
          entry.source = watch(jobId, (ev) => {
            if (entry.cancelled || active !== entry) return;
            if (
              ev?.type === "done" &&
              (ev?.result?.audio_url || ev?.audio_url)
            ) {
              startAudioUrl(ev.result?.audio_url || ev.audio_url);
            } else if (ev?.type === "error") {
              finish(Error(ev.error || "Erro ao sintetizar áudio."));
            }
          });
        }

        if (pollJob) {
          let pollInFlight = false;
          entry.pollTimer = setInterval(async () => {
            if (
              entry.settled ||
              entry.cancelled ||
              entry.playbackStarted ||
              active !== entry ||
              pollInFlight
            ) {
              return;
            }
            pollInFlight = true;
            try {
              const snap = await pollJob(jobId);
              if (
                entry.settled ||
                entry.cancelled ||
                entry.playbackStarted ||
                active !== entry
              ) {
                return;
              }
              const snapUrl = snap?.result?.audio_url || snap?.audio_url;
              if (snap?.state === "done" && snapUrl) {
                startAudioUrl(snapUrl);
              } else if (snap?.state === "error") {
                finish(
                  Error(snap?.error?.message || "Erro ao sintetizar áudio."),
                );
              }
            } catch {
              // Retry until stopped or SSE completes.
            } finally {
              pollInFlight = false;
            }
          }, pollIntervalMs);
        }
      });
    } catch (err) {
      finish(err);
      return false;
    }
  }

  function toggle(record) {
    if (active && active.messageId === record?.id) {
      stop();
      return Promise.resolve(false);
    }
    return speak(record);
  }

  function getActiveId() {
    return active ? active.messageId : null;
  }

  return {
    speak,
    stop,
    toggle,
    getActiveId,
  };
}
