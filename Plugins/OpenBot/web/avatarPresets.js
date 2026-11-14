export const DEFAULT_BOT_COLORS = {
  primary: "#ad83ff",
  accent: "#65d9ff",
  eyes: "#faf4ff",
};

export const AVATAR_PRESETS = [
  {
    id: "orb",
    name: "Órbita PIA",
    svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">
  <style>
    .enable-mouth { opacity: 0; transition: opacity 0.12s ease; }
    .animation-talking { transform-origin: center; animation: orbPulse 0.42s ease-in-out infinite paused; }
    @keyframes orbPulse { 0%, 100% { transform: scaleY(0.75); } 50% { transform: scaleY(1.25); } }
  </style>
  <circle cx="60" cy="60" r="52" fill="var(--bot-primary, #ad83ff)" fill-opacity="0.16" stroke="var(--bot-accent, #65d9ff)" stroke-width="3" />
  <circle cx="60" cy="60" r="40" fill="var(--bot-primary, #ad83ff)" />
  <circle cx="45" cy="52" r="6" fill="var(--bot-eyes, #faf4ff)" />
  <circle cx="75" cy="52" r="6" fill="var(--bot-eyes, #faf4ff)" />
  <path d="M 46 72 Q 60 80 74 72" fill="none" stroke="var(--bot-eyes, #faf4ff)" stroke-width="4" stroke-linecap="round" opacity="0.55" />
  <g class="enable-mouth">
    <rect class="animation-talking" x="45" y="68" width="30" height="10" rx="5" fill="var(--bot-eyes, #faf4ff)" />
  </g>
</svg>`,
  },
  {
    id: "visor",
    name: "Visor Cibernético",
    svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">
  <style>
    .enable-mouth { opacity: 0; transition: opacity 0.12s ease; }
    .animation-talking { transform-origin: center; animation: visorWave 0.36s ease-in-out infinite paused; }
    @keyframes visorWave { 0%, 100% { transform: scaleX(0.8); } 50% { transform: scaleX(1.15); } }
  </style>
  <line x1="60" y1="10" x2="60" y2="24" stroke="var(--bot-accent, #65d9ff)" stroke-width="4" stroke-linecap="round" />
  <circle cx="60" cy="10" r="5" fill="var(--bot-accent, #65d9ff)" />
  <rect x="20" y="24" width="80" height="74" rx="22" fill="var(--bot-primary, #ad83ff)" />
  <rect x="30" y="38" width="60" height="24" rx="10" fill="#18122b" stroke="var(--bot-accent, #65d9ff)" stroke-width="2" />
  <ellipse cx="46" cy="50" rx="6" ry="5" fill="var(--bot-eyes, #faf4ff)" />
  <ellipse cx="74" cy="50" rx="6" ry="5" fill="var(--bot-eyes, #faf4ff)" />
  <line x1="44" y1="78" x2="76" y2="78" stroke="var(--bot-eyes, #faf4ff)" stroke-width="4" stroke-linecap="round" opacity="0.5" />
  <g class="enable-mouth">
    <rect class="animation-talking" x="40" y="73" width="40" height="10" rx="5" fill="var(--bot-accent, #65d9ff)" />
  </g>
</svg>`,
  },
  {
    id: "owl",
    name: "Coruja Analítica",
    svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">
  <style>
    .enable-mouth { opacity: 0; transition: opacity 0.12s ease; }
    .animation-talking { transform-origin: center; animation: beakTalk 0.34s ease-in-out infinite paused; }
    @keyframes beakTalk { 0%, 100% { transform: scaleY(0.82); } 50% { transform: scaleY(1.25); } }
  </style>
  <polygon points="26,34 38,16 48,30" fill="var(--bot-accent, #65d9ff)" />
  <polygon points="94,34 82,16 72,30" fill="var(--bot-accent, #65d9ff)" />
  <circle cx="60" cy="64" r="40" fill="var(--bot-primary, #ad83ff)" />
  <circle cx="44" cy="54" r="14" fill="#1d1832" stroke="var(--bot-accent, #65d9ff)" stroke-width="2.5" />
  <circle cx="76" cy="54" r="14" fill="#1d1832" stroke="var(--bot-accent, #65d9ff)" stroke-width="2.5" />
  <circle cx="44" cy="54" r="6" fill="var(--bot-eyes, #faf4ff)" />
  <circle cx="76" cy="54" r="6" fill="var(--bot-eyes, #faf4ff)" />
  <polygon points="53,68 67,68 60,78" fill="var(--bot-accent, #65d9ff)" opacity="0.7" />
  <g class="enable-mouth">
    <polygon class="animation-talking" points="51,68 69,68 60,84" fill="var(--bot-eyes, #faf4ff)" />
  </g>
</svg>`,
  },
  {
    id: "spark",
    name: "Núcleo Prisma",
    svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">
  <style>
    .enable-mouth { opacity: 0; transition: opacity 0.12s ease; }
    .animation-talking { transform-origin: center; animation: prismPulse 0.4s ease-in-out infinite paused; }
    @keyframes prismPulse { 0%, 100% { transform: scale(0.88); } 50% { transform: scale(1.16); } }
  </style>
  <polygon points="60,12 104,40 104,84 60,108 16,84 16,40" fill="var(--bot-primary, #ad83ff)" stroke="var(--bot-accent, #65d9ff)" stroke-width="3" stroke-linejoin="round" />
  <polygon points="60,24 92,45 92,77 60,96 28,77 28,45" fill="#18122b" fill-opacity="0.45" />
  <circle cx="45" cy="54" r="5.5" fill="var(--bot-eyes, #faf4ff)" />
  <circle cx="75" cy="54" r="5.5" fill="var(--bot-eyes, #faf4ff)" />
  <rect x="44" y="72" width="32" height="5" rx="2.5" fill="var(--bot-accent, #65d9ff)" opacity="0.6" />
  <g class="enable-mouth">
    <rect class="animation-talking" x="42" y="68" width="36" height="12" rx="6" fill="var(--bot-eyes, #faf4ff)" />
  </g>
</svg>`,
  },
];

export const BOT_TOOL_OPTIONS = [
  {
    value: "pia_accounts",
    label: "Contas e agendas conectadas (pia_accounts)",
  },
  {
    value: "pia_resources",
    label: "Arquivos e recursos locais (pia_resources)",
  },
  { value: "pia_camera", label: "Câmera e visão (pia_camera)" },
  { value: "pia_image", label: "Geração de imagens (pia_image)" },
  { value: "pia_music", label: "Controle de música (pia_music)" },
  {
    value: "delegate_to_bot",
    label: "Delegar para outros bots (delegate_to_bot)",
  },
];

export const LLM_TIER_OPTIONS = [
  { value: "free", label: "Padrão (Seleção automática)" },
  { value: "fast", label: "Rápido (Baixa latência)" },
  { value: "pro", label: "Avançado (Maior raciocínio)" },
];

export const BOT_TEMPLATES = [
  {
    id: "assistant",
    name: "Assistente Focado",
    description:
      "Responde perguntas e organiza tarefas de forma direta e objetiva.",
    instructions:
      "# Papel\nVocê é um assistente especialista objetivo e confiável.\n\n# Regras\n- Responda em português claro.\n- Vá direto ao ponto antes de detalhar.\n- Se faltar contexto essencial, peça apenas o mínimo necessário.",
    llm_tier: "free",
    tool_ids: ["pia_resources"],
    presetId: "orb",
    avatar_colors: { primary: "#ad83ff", accent: "#65d9ff", eyes: "#faf4ff" },
  },
  {
    id: "reviewer",
    name: "Revisor de Código",
    description:
      "Analisa arquitetura, bugs, segurança e legibilidade em trechos de código.",
    instructions:
      "# Papel\nVocê é um revisor técnico sênior.\n\n# Diretrizes\n- Aponte riscos reais de bug, regressão ou segurança antes de estilo.\n- Sugira correções enxutas e testáveis.\n- Nunca invente resultados de execução que não observou.",
    llm_tier: "pro",
    tool_ids: ["pia_resources"],
    presetId: "visor",
    avatar_colors: { primary: "#5c7cfa", accent: "#38d9a9", eyes: "#f8f9fa" },
  },
  {
    id: "researcher",
    name: "Pesquisador & Resumo",
    description:
      "Sintetiza documentos, notas e compromissos com clareza executiva.",
    instructions:
      "# Papel\nVocê sintetiza informações complexas em resumos acionáveis.\n\n# Estrutura\n- Comece com a conclusão principal.\n- Liste pontos-chave em tópicos curtos.\n- Separe fatos confirmados de inferências.",
    llm_tier: "fast",
    tool_ids: ["pia_accounts", "pia_resources"],
    presetId: "owl",
    avatar_colors: { primary: "#845ef7", accent: "#ffd43b", eyes: "#fff9db" },
  },
];

export function validateClientSvg(rawText) {
  if (typeof rawText !== "string" || !rawText.trim()) {
    return { ok: false, error: "Arquivo SVG vazio." };
  }
  if (rawText.length > 256 * 1024) {
    return { ok: false, error: "O SVG excede o limite de 256 KiB." };
  }
  const lower = rawText.toLowerCase();
  if (!lower.includes("<svg")) {
    return { ok: false, error: "O arquivo precisa conter um elemento <svg>." };
  }
  if (
    /<script\b|<foreignobject\b|<!doctype|<!entity|\son[a-z]+\s*=/i.test(
      rawText,
    )
  ) {
    return {
      ok: false,
      error: "O SVG contém tags ou atributos de script não permitidos.",
    };
  }
  return { ok: true, error: null };
}

export function buildBotPayload(form, options = {}) {
  const payload = {
    name: String(form.name || "").trim(),
    description: String(form.description || "").trim(),
    instructions: String(form.instructions || ""),
    enabled: Boolean(form.enabled ?? true),
    speak_replies: Boolean(form.speak_replies ?? true),
    llm_tier: String(form.llm_tier || "free").trim() || "free",
    avatar_colors: {
      primary: form.avatar_colors?.primary || DEFAULT_BOT_COLORS.primary,
      accent: form.avatar_colors?.accent || DEFAULT_BOT_COLORS.accent,
      eyes: form.avatar_colors?.eyes || DEFAULT_BOT_COLORS.eyes,
    },
    tool_ids: Array.isArray(form.tool_ids) ? form.tool_ids : [],
    delegation_targets: Array.isArray(form.delegation_targets)
      ? form.delegation_targets
      : [],
    voice: form.voice
      ? {
          mode: form.voice.mode === "custom" ? "custom" : "inherit",
          profile:
            form.voice.mode === "custom" ? form.voice.profile || null : null,
          ...(form.voice.revision !== undefined
            ? { revision: form.voice.revision }
            : {}),
        }
      : { mode: "inherit", profile: null },
  };
  if (options.avatarId !== undefined) {
    payload.avatar_id = options.avatarId;
  } else if (form.avatar_id !== undefined) {
    payload.avatar_id = form.avatar_id;
  }
  if (options.isEdit && form.revision !== undefined) {
    payload.revision = form.revision;
  }
  return payload;
}
