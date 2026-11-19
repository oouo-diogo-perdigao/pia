export const PROVIDERS_ORDER = [
  "codex",
  "agy",
  "openrouter",
  "gemini",
  "groq",
  "cloudflare",
  "local",
];

export const STATUS_META = {
  connected: { status: "connected", label: "Conectado", color: "green" },
  login_required: {
    status: "login_required",
    label: "Login necessário",
    color: "yellow",
  },
  not_installed: {
    status: "not_installed",
    label: "Não instalado",
    color: "gray",
  },
  error: { status: "error", label: "Erro de autenticação", color: "red" },
};

export function normalizeProviderStatus(status) {
  return STATUS_META[status] || STATUS_META.not_installed;
}

export function formatLocalTimeHHMM(isoString) {
  if (!isoString) return null;
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return null;
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

export function truncateToTwoDecimals(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return 0;
  return Math.trunc(num * 100) / 100;
}

export function formatPtBrNumber(value, decimals = 0) {
  return new Intl.NumberFormat("pt-BR", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

export function formatTokenCount(tokens) {
  const num = Math.max(0, Math.floor(Number(tokens) || 0));
  if (num >= 100000) {
    const thousands = Math.round((num / 1000) * 10) / 10;
    return `${formatPtBrNumber(thousands, 1)} mil`;
  }
  return formatPtBrNumber(num, 0);
}

export function formatProviderQuota(providerQuota, providerId = null) {
  const checkedAt = formatLocalTimeHHMM(providerQuota?.quota_checked_at);
  const checkedAtText = checkedAt ? `Verificado às ${checkedAt}` : null;

  if (!providerQuota || providerQuota.quota_status !== "available") {
    const isLocal =
      providerId === "local" ||
      String(providerQuota?.quota_label || "").includes("Execução local");
    const label = isLocal
      ? "Saldo não informado pelo provedor · Execução local (sem cota externa)"
      : "Saldo não informado pelo provedor";
    const detail =
      providerQuota?.quota_status === "error"
        ? providerQuota?.quota_detail ||
          "Não foi possível consultar o saldo agora."
        : providerQuota?.quota_detail || null;
    return { label, detail, checkedAtText };
  }

  const truncated = truncateToTwoDecimals(providerQuota.quota_remaining ?? 0);
  const currency =
    !providerQuota.quota_currency || providerQuota.quota_currency === "USD"
      ? "US$"
      : providerQuota.quota_currency;
  const label = `${currency} ${formatPtBrNumber(truncated, 2)} disponíveis`;

  return {
    label,
    detail: providerQuota.quota_detail || null,
    checkedAtText,
  };
}

export function formatSessionUsage(sessionUsage, { compact = false } = {}) {
  const requests = Math.max(0, Math.floor(Number(sessionUsage?.requests) || 0));
  if (requests === 0) {
    return {
      hasUsage: false,
      summary: compact
        ? "Sessão: nenhuma requisição"
        : "Nenhuma requisição nesta sessão",
      detail: null,
    };
  }

  const reqPart = `${requests} req`;
  if (sessionUsage?.tokens_reported === false) {
    return {
      hasUsage: true,
      summary: compact
        ? `Sessão: ${reqPart} (tokens não informados pelo provedor)`
        : `${reqPart} · tokens não informados pelo provedor`,
      detail: null,
    };
  }

  const total = sessionUsage?.total_tokens ?? 0;
  const totalText = `${formatTokenCount(total)} tokens`;
  const hasBreakdown =
    sessionUsage?.prompt_tokens != null &&
    sessionUsage?.completion_tokens != null;

  return {
    hasUsage: true,
    summary: compact
      ? `Sessão: ${reqPart} · ${totalText}`
      : `${reqPart} · ${totalText}`,
    detail: hasBreakdown
      ? `entrada ${formatPtBrNumber(Math.max(0, Number(sessionUsage.prompt_tokens) || 0))} · saída ${formatPtBrNumber(Math.max(0, Number(sessionUsage.completion_tokens) || 0))}`
      : null,
  };
}

function blockingMessageForProvider(provider) {
  const name = provider?.name || provider?.id || "Provedor";
  if (provider?.status === "not_installed") {
    return `O ${name} não está instalado neste computador.`;
  }
  if (provider?.status === "error") {
    return `O ${name} recusou o acesso. Reconecte para continuar.`;
  }
  if (provider?.auth_type === "api_key") {
    return `O ${name} precisa de uma chave para responder. Sua mensagem não foi enviada.`;
  }
  return `O ${name} precisa de login para responder. Sua mensagem não foi enviada.`;
}

export function resolveSelectedModel(selection, catalog) {
  const rawProvider = String(
    selection?.provider ?? selection?.llm_provider ?? "",
  ).trim();
  const rawModel = String(
    selection?.model ?? selection?.llm_model ?? "",
  ).trim();

  const providers = Array.isArray(catalog?.providers) ? catalog.providers : [];
  const hasCatalog = providers.length > 0;

  if (!rawProvider && !rawModel) {
    const defProviderId = String(catalog?.default_provider || "").trim();
    const defModelId = String(catalog?.default_model || "").trim();
    if (defProviderId && defProviderId !== "free" && defProviderId !== "paid") {
      const resolvedDef = resolveSelectedModel(
        { provider: defProviderId, model: defModelId },
        catalog,
      );
      return {
        ...resolvedDef,
        mode: "default",
        modelLabel: catalog?.effective_default_label
          ? `Padrão da PIA (${catalog.effective_default_label})`
          : resolvedDef.modelLabel,
      };
    }
    const defaultLabel = catalog?.effective_default_label
      ? `Padrão da PIA (${catalog.effective_default_label})`
      : "Padrão da PIA";
    return {
      mode: "default",
      providerId: "",
      provider: null,
      modelId: "",
      modelLabel: defaultLabel,
      available: true,
      status: "connected",
      statusMeta: STATUS_META.connected,
      blockingReason: null,
    };
  }

  const autoId =
    rawProvider === "free" || rawProvider === "paid"
      ? rawProvider
      : !rawProvider && (rawModel === "free" || rawModel === "paid")
        ? rawModel
        : "";
  if (autoId) {
    return {
      mode: "automatic",
      providerId: autoId,
      provider: null,
      modelId: autoId,
      modelLabel: autoId === "free" ? "Gratuito (free)" : "Pago (paid)",
      available: true,
      status: "connected",
      statusMeta: STATUS_META.connected,
      blockingReason: null,
    };
  }

  const provider = providers.find((p) => p.id === rawProvider) || null;
  if (!provider) {
    if (!hasCatalog) {
      return {
        mode: "provider",
        providerId: rawProvider,
        provider: null,
        modelId: rawModel,
        modelLabel: rawModel || rawProvider,
        available: true,
        status: "connected",
        statusMeta: STATUS_META.connected,
        blockingReason: null,
      };
    }
    return {
      mode: "provider",
      providerId: rawProvider,
      provider: null,
      modelId: rawModel,
      modelLabel: `Modelo indisponível · ${rawModel || rawProvider}`,
      available: false,
      status: "error",
      statusMeta: STATUS_META.error,
      blockingReason:
        "O modelo desta conversa não está mais disponível. Escolha outro.",
    };
  }

  const models = Array.isArray(provider.models) ? provider.models : [];
  const matchedModel = rawModel
    ? models.find((m) => m.id === rawModel)
    : models[0] || null;

  if (rawModel && models.length > 0 && !matchedModel && rawModel !== provider.id) {
    return {
      mode: "provider",
      providerId: provider.id,
      provider,
      modelId: rawModel,
      modelLabel: `Modelo indisponível · ${rawModel}`,
      available: false,
      status: provider.status,
      statusMeta: normalizeProviderStatus(provider.status),
      blockingReason:
        "O modelo desta conversa não está mais disponível. Escolha outro.",
    };
  }

  const statusMeta = normalizeProviderStatus(provider.status);
  const connected = provider.status === "connected";
  const modelDisplay = matchedModel?.label || rawModel || provider.name;

  return {
    mode: "provider",
    providerId: provider.id,
    provider,
    modelId: matchedModel?.id || rawModel || provider.id,
    modelLabel: `${provider.name} · ${modelDisplay}`,
    available: connected,
    status: provider.status,
    statusMeta,
    blockingReason: connected ? null : blockingMessageForProvider(provider),
  };
}

export function buildSelectorOptions(catalog) {
  const defaultOption = {
    value: "",
    provider: "",
    model: "",
    label: catalog?.effective_default_label
      ? `Padrão da PIA (${catalog.effective_default_label})`
      : "Padrão da PIA",
  };

  const automaticSource = Array.isArray(catalog?.automatic_options)
    ? catalog.automatic_options
    : [
        { id: "free", label: "Gratuito (free)" },
        { id: "paid", label: "Pago (paid)" },
      ];
  const automaticOptions = automaticSource.map((opt) => ({
    value: opt.id,
    provider: opt.id,
    model: opt.id,
    label: opt.label,
  }));

  const providers = Array.isArray(catalog?.providers) ? catalog.providers : [];
  const byId = new Map(providers.map((p) => [p.id, p]));
  const ordered = [
    ...PROVIDERS_ORDER.map((id) => byId.get(id)).filter(Boolean),
    ...providers.filter((p) => !PROVIDERS_ORDER.includes(p.id)),
  ];

  const groups = ordered.map((provider) => {
    const statusMeta = normalizeProviderStatus(provider.status);
    const models = Array.isArray(provider.models) ? provider.models : [];
    return {
      providerId: provider.id,
      name: provider.name,
      authType: provider.auth_type,
      status: provider.status,
      statusMeta,
      connected: provider.status === "connected",
      models: models.map((m) => ({
        value: `${provider.id}::${m.id}`,
        provider: provider.id,
        model: m.id,
        label: m.label || m.id,
      })),
    };
  });

  return { defaultOption, automaticOptions, groups };
}
