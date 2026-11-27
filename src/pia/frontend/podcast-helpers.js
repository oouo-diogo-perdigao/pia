export const APP_SETTINGS_DEFAULTS = {
  POLL_INTERVAL_SECONDS: 600,
  DRIVE_PROCESS: true,
  LOCAL_DRIVE_FOLDER: "data/local-drive",
  PUBLICAR_DIRETO: false,
  OWNER_EMAIL: "",
  TRANSCRIPTS_FILE: "transcripts.html",
  SKIP_CLOSED: true,
  FEED_CACHE_DIR: "data/cache/feeds",
  FEED_FORCE_REBUILD: false,
};

export const PROCESSING_DEFAULTS = {
  minimum_session_seconds: 1800,
  duplicate_max_bytes: 10485760,
  duplicate_max_seconds: 3600,
};

export const PUBLICATION_DEFAULTS = {
  brand: "",
  website: "",
  copyright: "",
  genre: "",
  comment: "",
  unpublished_prefix: "unpublish",
  language: "pt-BR",
};

export const AUDIO_DEFAULTS = {
  remove_silence: true,
  silence_threshold_db: -40,
  minimum_silence_seconds: 1.5,
  keep_silence_seconds: 0.6,
  fade_seconds: 0.005,
  compressor_threshold_db: -18,
  compressor_ratio: 4,
  compressor_attack_ms: 20,
  compressor_release_ms: 200,
  loudness_lufs: -16,
  loudness_range: 11,
  true_peak_db: -1.5,
};

export const AUDIO_NUMERIC_KEYS = [
  "silence_threshold_db",
  "minimum_silence_seconds",
  "keep_silence_seconds",
  "fade_seconds",
  "compressor_threshold_db",
  "compressor_ratio",
  "compressor_attack_ms",
  "compressor_release_ms",
  "loudness_lufs",
  "loudness_range",
  "true_peak_db",
];

let uidCounter = 0;
export function nextUid(prefix = "item") {
  uidCounter += 1;
  return `${prefix}-${uidCounter}`;
}

export function normalizeDecimalInput(raw) {
  const text = String(raw ?? "")
    .trim()
    .replace(",", ".");
  if (!/^-?\d+(?:\.\d+)?$/.test(text)) return { ok: false, value: NaN, text };
  const value = Number(text);
  if (!Number.isFinite(value)) return { ok: false, value: NaN, text };
  return { ok: true, value, text };
}

export function parseIntegerInput(raw) {
  const text = String(raw ?? "").trim();
  if (!/^-?\d+$/.test(text)) return { ok: false, value: NaN };
  const value = Number(text);
  if (!Number.isSafeInteger(value)) return { ok: false, value: NaN };
  return { ok: true, value };
}

export function formatMinutesHelp(seconds) {
  const parsed = Number(seconds);
  if (!Number.isFinite(parsed) || parsed < 0) return "";
  const mins = parsed / 60;
  const formatted = Number.isInteger(mins)
    ? String(mins)
    : mins.toFixed(1).replace(/\.0$/, "");
  return `= ${formatted} min`;
}

export function formatMegabytesHelp(bytes) {
  const parsed = Number(bytes);
  if (!Number.isFinite(parsed) || parsed < 0) return "";
  const mb = parsed / (1024 * 1024);
  const formatted = Number.isInteger(mb)
    ? String(mb)
    : mb.toFixed(1).replace(/\.0$/, "");
  return `≈ ${formatted} MB`;
}

export function buildSettingsDraft(configuration) {
  const defaults = configuration?.app_defaults || {};
  const appSettingsSrc = {
    ...APP_SETTINGS_DEFAULTS,
    ...(defaults.app_settings || {}),
    ...(configuration?.app_settings || {}),
  };
  const processingSrc = {
    ...PROCESSING_DEFAULTS,
    ...(defaults.processing || {}),
    ...(configuration?.processing || {}),
  };
  const publicationSrc = {
    ...PUBLICATION_DEFAULTS,
    ...(defaults.publication || {}),
    ...(configuration?.publication || {}),
  };
  const audioSrc = {
    ...AUDIO_DEFAULTS,
    ...(defaults.audio || {}),
    ...(configuration?.audio || {}),
  };

  const audio = { remove_silence: audioSrc.remove_silence !== false };
  for (const key of AUDIO_NUMERIC_KEYS) {
    audio[key] =
      audioSrc[key] === undefined || audioSrc[key] === null
        ? String(AUDIO_DEFAULTS[key])
        : String(audioSrc[key]);
  }

  return {
    app_settings: {
      POLL_INTERVAL_SECONDS: String(
        appSettingsSrc.POLL_INTERVAL_SECONDS ?? 600,
      ),
      DRIVE_PROCESS: appSettingsSrc.DRIVE_PROCESS !== false,
      LOCAL_DRIVE_FOLDER: String(appSettingsSrc.LOCAL_DRIVE_FOLDER ?? ""),
      PUBLICAR_DIRETO: !!appSettingsSrc.PUBLICAR_DIRETO,
      OWNER_EMAIL: String(appSettingsSrc.OWNER_EMAIL ?? ""),
      TRANSCRIPTS_FILE: String(
        appSettingsSrc.TRANSCRIPTS_FILE ?? "transcripts.html",
      ),
      SKIP_CLOSED: appSettingsSrc.SKIP_CLOSED !== false,
      FEED_CACHE_DIR: String(appSettingsSrc.FEED_CACHE_DIR ?? ""),
      FEED_FORCE_REBUILD: !!appSettingsSrc.FEED_FORCE_REBUILD,
    },
    processing: {
      minimum_session_seconds: String(
        processingSrc.minimum_session_seconds ?? 1800,
      ),
      duplicate_max_bytes: String(
        processingSrc.duplicate_max_bytes ?? 10485760,
      ),
      duplicate_max_seconds: String(
        processingSrc.duplicate_max_seconds ?? 3600,
      ),
    },
    publication: {
      brand: String(publicationSrc.brand ?? ""),
      website: String(publicationSrc.website ?? ""),
      copyright: String(publicationSrc.copyright ?? ""),
      genre: String(publicationSrc.genre ?? ""),
      comment: String(publicationSrc.comment ?? ""),
      unpublished_prefix: String(publicationSrc.unpublished_prefix ?? ""),
      language: String(publicationSrc.language ?? "pt-BR"),
    },
    audio,
  };
}

export function validateSettingsDraft(draft) {
  const errors = [];
  const fieldErrors = {};
  const addError = (fieldId, message) => {
    if (!fieldErrors[fieldId]) {
      fieldErrors[fieldId] = message;
      errors.push({ fieldId, message });
    }
  };

  const poll = parseIntegerInput(draft.app_settings.POLL_INTERVAL_SECONDS);
  if (!poll.ok || poll.value < 1) {
    addError(
      "setting-POLL_INTERVAL_SECONDS",
      "Informe um número inteiro de segundos, a partir de 1.",
    );
  }

  if (
    !draft.app_settings.DRIVE_PROCESS &&
    !String(draft.app_settings.LOCAL_DRIVE_FOLDER || "").trim()
  ) {
    addError("setting-LOCAL_DRIVE_FOLDER", "Informe uma pasta.");
  }

  if (!String(draft.app_settings.FEED_CACHE_DIR || "").trim()) {
    addError("setting-FEED_CACHE_DIR", "Informe uma pasta.");
  }

  const email = String(draft.app_settings.OWNER_EMAIL || "").trim();
  if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    addError(
      "setting-OWNER_EMAIL",
      "Informe um e-mail válido, como nome@dominio.com, ou deixe em branco.",
    );
  }

  const transcripts = String(draft.app_settings.TRANSCRIPTS_FILE || "").trim();
  if (!transcripts || !transcripts.toLowerCase().endsWith(".html")) {
    addError(
      "setting-TRANSCRIPTS_FILE",
      "Informe o nome de um arquivo .html, como transcripts.html.",
    );
  }

  const website = String(draft.publication.website || "").trim();
  if (website && !/^https?:\/\/\S+$/i.test(website)) {
    addError(
      "setting-publication-website",
      "Informe um endereço que comece com https:// ou http://.",
    );
  }

  const language = String(draft.publication.language || "").trim();
  if (!/^[a-z]{2}(-[A-Z]{2})?$/.test(language)) {
    addError(
      "setting-publication-language",
      "Use um código de idioma, como pt-BR.",
    );
  }

  for (const key of [
    "minimum_session_seconds",
    "duplicate_max_bytes",
    "duplicate_max_seconds",
  ]) {
    const parsed = parseIntegerInput(draft.processing[key]);
    if (!parsed.ok || parsed.value < 0) {
      addError(
        `setting-processing-${key}`,
        "Informe um número inteiro igual ou maior que zero.",
      );
    }
  }

  const audioValues = { remove_silence: !!draft.audio.remove_silence };
  for (const key of AUDIO_NUMERIC_KEYS) {
    const parsed = normalizeDecimalInput(draft.audio[key]);
    if (!parsed.ok) {
      addError(
        `setting-audio-${key}`,
        "Informe um número. Use vírgula ou ponto para decimais.",
      );
      continue;
    }
    if (key === "compressor_ratio" && parsed.value < 1) {
      addError(
        `setting-audio-${key}`,
        "A razão do compressor deve ser 1 ou maior.",
      );
      continue;
    }
    if (
      (key === "compressor_attack_ms" || key === "compressor_release_ms") &&
      parsed.value <= 0
    ) {
      addError(`setting-audio-${key}`, "Informe um tempo maior que zero.");
      continue;
    }
    audioValues[key] = parsed.value;
  }

  if (errors.length) {
    return { ok: false, errors, fieldErrors, payload: null };
  }

  return {
    ok: true,
    errors: [],
    fieldErrors: {},
    payload: {
      app_settings: {
        POLL_INTERVAL_SECONDS: poll.value,
        DRIVE_PROCESS: !!draft.app_settings.DRIVE_PROCESS,
        LOCAL_DRIVE_FOLDER: String(
          draft.app_settings.LOCAL_DRIVE_FOLDER || "",
        ).trim(),
        PUBLICAR_DIRETO: !!draft.app_settings.PUBLICAR_DIRETO,
        OWNER_EMAIL: email,
        TRANSCRIPTS_FILE: transcripts,
        SKIP_CLOSED: !!draft.app_settings.SKIP_CLOSED,
        FEED_CACHE_DIR: String(draft.app_settings.FEED_CACHE_DIR || "").trim(),
        FEED_FORCE_REBUILD: !!draft.app_settings.FEED_FORCE_REBUILD,
      },
      processing: {
        minimum_session_seconds: Number(
          draft.processing.minimum_session_seconds,
        ),
        duplicate_max_bytes: Number(draft.processing.duplicate_max_bytes),
        duplicate_max_seconds: Number(draft.processing.duplicate_max_seconds),
      },
      publication: {
        brand: String(draft.publication.brand || "").trim(),
        website,
        copyright: String(draft.publication.copyright || "").trim(),
        genre: String(draft.publication.genre || "").trim(),
        comment: String(draft.publication.comment || "").trim(),
        unpublished_prefix: String(
          draft.publication.unpublished_prefix || "",
        ).trim(),
        language,
      },
      audio: audioValues,
    },
  };
}

export function buildParticipantsList(nomesReais = {}, discordUsers = {}) {
  const byName = new Map();
  const ensure = (name) => {
    const key = String(name || "");
    if (!byName.has(key)) {
      byName.set(key, {
        id: nextUid("part"),
        realName: key,
        handles: [],
        discordId: "",
      });
    }
    return byName.get(key);
  };

  for (const [handle, realName] of Object.entries(nomesReais || {})) {
    const entry = ensure(realName);
    if (handle && !entry.handles.includes(handle)) {
      entry.handles.push(handle);
    }
  }
  for (const [realName, discordId] of Object.entries(discordUsers || {})) {
    const entry = ensure(realName);
    entry.discordId = discordId == null ? "" : String(discordId);
  }
  return Array.from(byName.values());
}

export function participantsToConfig(participants = []) {
  const nomes_reais = {};
  const discord_users = {};
  for (const person of participants) {
    const name = String(person.realName || "").trim();
    if (!name) continue;
    for (const handle of person.handles || []) {
      const trimmed = String(handle || "").trim();
      if (trimmed) nomes_reais[trimmed] = name;
    }
    const discordId = String(person.discordId || "").trim();
    if (discordId) {
      discord_users[name] = discordId;
    }
  }
  return { nomes_reais, discord_users };
}

export function validateParticipants(participants = []) {
  const errors = [];
  const fieldErrors = {};
  const addError = (fieldId, message) => {
    if (!fieldErrors[fieldId]) {
      fieldErrors[fieldId] = message;
      errors.push({ fieldId, message });
    }
  };

  const handleOwners = new Map();
  participants.forEach((person, index) => {
    const name = String(person.realName || "").trim();
    if (!name) {
      addError(`participant-name-${index}`, "Informe o nome real.");
    }
    for (const handle of person.handles || []) {
      const trimmed = String(handle || "").trim();
      if (!trimmed) {
        addError(
          `participant-handles-${index}`,
          "Informe o usuário do Discord.",
        );
        continue;
      }
      if (handleOwners.has(trimmed)) {
        addError(
          `participant-handles-${index}`,
          `Este usuário já está ligado a ${handleOwners.get(trimmed)}.`,
        );
      } else {
        handleOwners.set(trimmed, name || `#${index + 1}`);
      }
    }
    const discordId = String(person.discordId || "").trim();
    if (discordId && !/^\d+$/.test(discordId)) {
      addError(
        `participant-id-${index}`,
        "O ID do Discord tem só números. Deixe em branco se não quiser menções.",
      );
    }
  });
  return { ok: errors.length === 0, errors, fieldErrors };
}

export function buildCampaignsList(campaignDetails = {}) {
  return Object.entries(campaignDetails || {}).map(([narrator, details]) => {
    const {
      Campanha = "",
      rss_key = "",
      title = "",
      description = "",
      link = "",
      author = "",
      explicit = false,
      closed = false,
      players = {},
      ...extra
    } = details || {};
    return {
      id: nextUid("camp"),
      narrator,
      Campanha: String(Campanha),
      rss_key: String(rss_key),
      title: String(title),
      description: String(description),
      link: String(link),
      author: String(author),
      explicit: !!explicit,
      closed: !!closed,
      playersList: Object.entries(players || {}).map(([player, character]) => ({
        id: nextUid("player"),
        player: String(player),
        character: String(character ?? ""),
      })),
      extra,
    };
  });
}

export function campaignsListToObject(campaignsList = []) {
  const result = {};
  for (const item of campaignsList) {
    const narrator = String(item.narrator || "").trim();
    if (!narrator) continue;
    const players = {};
    for (const row of item.playersList || []) {
      const playerName = String(row.player || "").trim();
      if (playerName) {
        players[playerName] = String(row.character || "").trim();
      }
    }
    result[narrator] = {
      ...(item.extra || {}),
      Campanha: String(item.Campanha || "").trim(),
      rss_key: String(item.rss_key || "").trim(),
      title: String(item.title || "").trim(),
      description: String(item.description || "").trim(),
      link: String(item.link || "").trim(),
      author: String(item.author || "").trim(),
      explicit: !!item.explicit,
      closed: !!item.closed,
      players,
    };
  }
  return result;
}

export function validateCampaigns(campaignsList = []) {
  const errors = [];
  const fieldErrors = {};
  const addError = (fieldId, message) => {
    if (!fieldErrors[fieldId]) {
      fieldErrors[fieldId] = message;
      errors.push({ fieldId, message });
    }
  };

  const narrators = new Set();
  const rssFolders = new Set();

  campaignsList.forEach((item, index) => {
    const narrator = String(item.narrator || "").trim();
    if (!narrator) {
      addError(`campaign-narrator-${index}`, "Escolha o narrador.");
    } else if (narrators.has(narrator)) {
      addError(
        `campaign-narrator-${index}`,
        "Já existe uma campanha para este narrador.",
      );
    } else {
      narrators.add(narrator);
    }

    const name = String(item.Campanha || "").trim();
    if (!name) {
      addError(`campaign-name-${index}`, "Informe o nome da campanha.");
    }

    const rssKey = String(item.rss_key || "").trim();
    if (!rssKey.endsWith("/rss.xml") || rssKey.length <= "/rss.xml".length) {
      addError(
        `campaign-rss-${index}`,
        "O caminho do feed precisa terminar em /rss.xml.",
      );
    } else {
      const folder = rssKey.slice(0, -"/rss.xml".length);
      if (rssFolders.has(folder)) {
        addError(
          `campaign-rss-${index}`,
          `Outra campanha já usa a pasta "${folder}".`,
        );
      } else {
        rssFolders.add(folder);
      }
    }

    const link = String(item.link || "").trim();
    if (link && !/^https?:\/\/\S+$/i.test(link)) {
      addError(
        `campaign-link-${index}`,
        "Informe um endereço que comece com https:// ou http://.",
      );
    }

    const playersList = item.playersList || [];
    if (playersList.length === 0) {
      addError(
        `campaign-players-${index}`,
        "Adicione pelo menos um jogador e o personagem dele.",
      );
    } else {
      playersList.forEach((row, pIndex) => {
        const player = String(row.player || "").trim();
        const character = String(row.character || "").trim();
        if (!player) {
          addError(`campaign-player-${index}-${pIndex}`, "Escolha o jogador.");
        }
        if (!character) {
          addError(
            `campaign-character-${index}-${pIndex}`,
            `Informe o personagem de ${player || "jogador"}.`,
          );
        }
      });
    }
  });

  return { ok: errors.length === 0, errors, fieldErrors };
}
