import React, { useState, useEffect, useCallback, useRef } from "react";
import {
  Paper,
  Title,
  Text,
  Select,
  Group,
  Stack,
  SimpleGrid,
  Badge,
  Button,
  Alert,
  Skeleton,
} from "@mantine/core";
import {
  Settings,
  RefreshCw,
  CircleCheck,
  LogIn,
  KeyRound,
  Download,
  CircleAlert,
} from "lucide-react";
import { api, safe } from "../../../../src/pia/frontend/api";
import {
  normalizeProviderStatus,
  formatProviderQuota,
  formatSessionUsage,
  resolveSelectedModel,
  buildSelectorOptions,
} from "../../../../src/pia/frontend/models";
import ProviderDrawer from "../../../../src/pia/frontend/ProviderDrawer";

const FALLBACK_QUOTA_LABEL = "Saldo não informado pelo provedor";

function statusIcon(status, authType) {
  if (status === "connected") return CircleCheck;
  if (status === "login_required") return authType === "cli" ? LogIn : KeyRound;
  if (status === "not_installed") return Download;
  return CircleAlert;
}

function statusActionLabel(status, provider) {
  const authType = provider?.auth_type;
  if (status === "login_required") {
    return authType === "cli" ? "Fazer login" : "Adicionar chave";
  }
  if (status === "not_installed") {
    return authType === "local" ? "Verificar serviço" : "Como instalar";
  }
  return "Reconectar";
}

function statusBlockingPhrase(status, provider) {
  if (status === "login_required") {
    return provider?.auth_type === "cli" ? "sem login" : "sem chave configurada";
  }
  if (status === "not_installed") {
    return "não instalado";
  }
  return "com erro de autenticação";
}

function selectionValue(provider, model) {
  const p = (provider || "").trim();
  const m = (model || "").trim();
  if (!p && !m) return "";
  if ((p === "free" || p === "paid") && !m) return p;
  if (p && m) return `${p}::${m}`;
  return p || m;
}

function parseSelectionValue(value, valueMap) {
  if (!value) return { llm_provider: "", llm_model: "" };
  if (valueMap && valueMap.has(value)) return valueMap.get(value);
  if (value === "free" || value === "paid") {
    return { llm_provider: value, llm_model: "" };
  }
  if (value.includes("::")) {
    const [llm_provider, ...rest] = value.split("::");
    return { llm_provider, llm_model: rest.join("::") };
  }
  if (value.includes("/")) {
    const [llm_provider] = value.split("/");
    return { llm_provider, llm_model: value };
  }
  return { llm_provider: value, llm_model: "" };
}

function buildSelectData(catalog, currentProvider, currentModel, resolved) {
  const valueMap = new Map();
  valueMap.set("", { llm_provider: "", llm_model: "" });

  const defaultLabel = catalog?.effective_default_label || "";
  const defaultOptionLabel = defaultLabel
    ? `Usar padrão da PIA (Chat) — ${defaultLabel}`
    : "Usar padrão da PIA (Chat)";

  const groups = [
    {
      group: "Padrão",
      items: [{ value: "", label: defaultOptionLabel }],
    },
  ];

  const built = catalog ? buildSelectorOptions(catalog) : null;

  if (Array.isArray(built) && built.length > 0) {
    for (const entry of built) {
      if (entry && Array.isArray(entry.items)) {
        const items = [];
        for (const item of entry.items) {
          if (!item || item.value === "") continue;
          const itemProvider =
            item.provider !== undefined
              ? item.provider
              : item.value === "free" || item.value === "paid"
                ? item.value
                : "";
          const itemModel =
            item.model !== undefined
              ? item.model
              : itemProvider === "free" || itemProvider === "paid"
                ? ""
                : item.value;
          const key = selectionValue(itemProvider, itemModel) || item.value;
          valueMap.set(key, {
            llm_provider: itemProvider,
            llm_model: itemModel,
          });
          items.push({
            value: key,
            label: item.label || key,
            disabled: !!item.disabled,
          });
        }
        if (items.length > 0) {
          groups.push({ group: entry.group || "Modelos", items });
        }
      }
    }
  } else if (catalog) {
    const autoOptions = catalog.automatic_options || [
      { id: "free", label: "Gratuito (free)" },
      { id: "paid", label: "Pago (paid)" },
    ];
    if (autoOptions.length > 0) {
      const items = autoOptions.map((opt) => {
        valueMap.set(opt.id, { llm_provider: opt.id, llm_model: "" });
        return { value: opt.id, label: opt.label };
      });
      groups.push({
        group: "Automático (pode alternar entre modelos)",
        items,
      });
    }
    for (const provider of catalog.providers || []) {
      const statusMeta = normalizeProviderStatus(provider.status);
      const groupTitle = `${provider.name} · ${statusMeta.label}`;
      const models =
        Array.isArray(provider.models) && provider.models.length > 0
          ? provider.models
          : [{ id: provider.id, label: provider.name }];
      const items = models.map((model) => {
        const key = selectionValue(provider.id, model.id);
        valueMap.set(key, { llm_provider: provider.id, llm_model: model.id });
        return {
          value: key,
          label: model.label || model.id,
        };
      });
      groups.push({ group: groupTitle, items });
    }
  }

  const currentKey = selectionValue(currentProvider, currentModel);
  const hasCurrent = currentKey === "" || valueMap.has(currentKey);
  if (currentKey && !hasCurrent) {
    const rawId = currentModel || currentProvider;
    const label =
      resolved && resolved.available === false
        ? `Modelo indisponível · ${rawId}`
        : rawId;
    valueMap.set(currentKey, {
      llm_provider: currentProvider,
      llm_model: currentModel,
    });
    groups.push({
      group: "Seleção salva",
      items: [{ value: currentKey, label }],
    });
  }

  return { data: groups, valueMap, currentKey };
}

export default function ModelSettingsSlot({
  config,
  patchIntegrations,
  disabled = false,
}) {
  const [catalog, setCatalog] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [refreshingQuota, setRefreshingQuota] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerFocus, setDrawerFocus] = useState(null);
  const [liveAnnouncement, setLiveAnnouncement] = useState("");
  const triggerRef = useRef(null);

  const integrations = config?.integrations || {};
  const llmProvider =
    typeof integrations.llm_provider === "string"
      ? integrations.llm_provider
      : "";
  const llmModel =
    typeof integrations.llm_model === "string" ? integrations.llm_model : "";

  const loadCatalog = useCallback(async (announce = false) => {
    setLoading(true);
    setLoadError("");
    try {
      const data = await api("/models/status");
      setCatalog(data);
      if (announce) {
        setLiveAnnouncement("Status dos provedores atualizado.");
      }
    } catch {
      setLoadError(
        "Não foi possível verificar os provedores agora. A escolha salva continua valendo.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadCatalog(false);
  }, [loadCatalog]);

  const resolved = catalog
    ? resolveSelectedModel(
        { provider: llmProvider, model: llmModel },
        catalog,
      )
    : null;

  const { data: selectData, valueMap, currentKey } = buildSelectData(
    catalog,
    llmProvider,
    llmModel,
    resolved,
  );

  const isDefaultSelection = !llmProvider && !llmModel;
  const effectiveProvider = resolved?.provider || null;
  const effectiveStatus = resolved?.status || effectiveProvider?.status || null;
  const statusMeta = effectiveStatus
    ? normalizeProviderStatus(effectiveStatus)
    : null;
  const StatusIcon = effectiveStatus
    ? statusIcon(effectiveStatus, effectiveProvider?.auth_type)
    : null;

  const usage = formatSessionUsage(effectiveProvider?.session_usage);
  const quota = formatProviderQuota(
    effectiveProvider?.provider_quota,
    effectiveProvider?.id,
  );
  const quotaLabel = quota?.label || FALLBACK_QUOTA_LABEL;

  const isUnavailableModel =
    !!catalog && !isDefaultSelection && resolved?.available === false;
  const isProviderNotReady =
    !!effectiveProvider &&
    effectiveStatus &&
    effectiveStatus !== "connected";

  function openDrawer(providerId = null, event = null) {
    if (event?.currentTarget) {
      triggerRef.current = event.currentTarget;
    }
    setDrawerFocus(providerId);
    setDrawerOpen(true);
  }

  function closeDrawer() {
    setDrawerOpen(false);
    setDrawerFocus(null);
    loadCatalog(true);
    setTimeout(() => {
      triggerRef.current?.focus?.();
    }, 0);
  }

  const handleRefreshQuota = safe(async () => {
    if (!effectiveProvider?.id) return;
    setRefreshingQuota(true);
    try {
      await api("/models/quota", { provider: effectiveProvider.id });
      await loadCatalog(true);
    } finally {
      setRefreshingQuota(false);
    }
  });

  const selectDescription = disabled
    ? "Disponível quando o processamento terminar."
    : isDefaultSelection
      ? "O resumo das sessões usa o mesmo modelo padrão do Chat da PIA."
      : "Só o resumo das sessões usa este modelo. O Chat não muda.";

  return (
    <Paper withBorder p="md">
      <Stack gap="sm">
        <Title order={4} id="podcast-model-settings-title">
          Inteligência artificial · Modelo do resumo
        </Title>

        {loading && !catalog ? (
          <Stack gap="xs">
            <Skeleton height={36} radius="sm" />
            <Text size="sm" c="dimmed">
              Verificando provedores…
            </Text>
          </Stack>
        ) : (
          <>
            <Select
              label="Provedor e modelo do resumo"
              description={selectDescription}
              data={selectData}
              value={currentKey}
              disabled={disabled}
              allowDeselect={false}
              searchable
              onChange={(value) => {
                if (typeof patchIntegrations !== "function") return;
                const next = parseSelectionValue(value || "", valueMap);
                patchIntegrations(next);
              }}
            />

            {loadError && (
              <Alert color="yellow" role="alert">
                <Group justify="space-between" align="center" wrap="wrap">
                  <Text size="sm">{loadError}</Text>
                  <Button
                    size="xs"
                    variant="light"
                    color="yellow"
                    onClick={() => loadCatalog(true)}
                  >
                    Tentar novamente
                  </Button>
                </Group>
              </Alert>
            )}

            {isUnavailableModel && (
              <Alert color="yellow" role="alert">
                <Text size="sm">
                  O modelo salvo não está mais disponível. Escolha outro modelo
                  ou volte ao padrão da PIA.
                </Text>
              </Alert>
            )}

            {effectiveProvider && statusMeta && (
              <Group gap="xs" align="center">
                <Badge
                  color={statusMeta.color}
                  variant="light"
                  leftSection={StatusIcon ? <StatusIcon size={13} /> : null}
                >
                  {statusMeta.label}
                </Badge>
                <Text size="sm" fw={500}>
                  {effectiveProvider.name}
                </Text>
              </Group>
            )}

            {isProviderNotReady && (
              <Alert
                color={effectiveStatus === "error" ? "red" : "yellow"}
                role="alert"
              >
                <Group justify="space-between" align="center" wrap="wrap">
                  <Text size="sm">
                    O resumo não será gerado enquanto {effectiveProvider.name}{" "}
                    estiver {statusBlockingPhrase(effectiveStatus, effectiveProvider)}.
                  </Text>
                  <Button
                    size="xs"
                    variant="light"
                    color={effectiveStatus === "error" ? "red" : "yellow"}
                    onClick={(event) => openDrawer(effectiveProvider.id, event)}
                  >
                    {statusActionLabel(effectiveStatus, effectiveProvider)}
                  </Button>
                </Group>
              </Alert>
            )}

            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
              <Paper withBorder p="sm">
                <Text size="xs" fw={600} c="dimmed" mb={4}>
                  Consumo na sessão da PIA
                </Text>
                <Text size="sm" fw={500}>
                  {usage?.summary || "Nenhuma requisição nesta sessão"}
                </Text>
                {usage?.detail && (
                  <Text size="xs" c="dimmed">
                    {usage.detail}
                  </Text>
                )}
                <Text size="xs" c="dimmed" mt={4}>
                  Soma Chat e Podcast nesta sessão.
                </Text>
              </Paper>

              <Paper withBorder p="sm">
                <Group justify="space-between" align="center" mb={4}>
                  <Text size="xs" fw={600} c="dimmed">
                    Saldo do provedor
                  </Text>
                  {effectiveProvider?.id === "openrouter" &&
                    effectiveStatus === "connected" && (
                      <Button
                        size="compact-xs"
                        variant="subtle"
                        leftSection={<RefreshCw size={12} />}
                        loading={refreshingQuota}
                        onClick={handleRefreshQuota}
                      >
                        Atualizar saldo
                      </Button>
                    )}
                </Group>
                <Text size="sm" fw={500}>
                  {quotaLabel}
                </Text>
                {quota?.checkedAtText && (
                  <Text size="xs" c="dimmed">
                    {quota.checkedAtText}
                  </Text>
                )}
                {quota?.detail && (
                  <Text size="xs" c="dimmed">
                    {quota.detail}
                  </Text>
                )}
              </Paper>
            </SimpleGrid>
          </>
        )}

        <Group>
          <Button
            size="xs"
            variant="subtle"
            leftSection={<Settings size={14} />}
            onClick={(event) => openDrawer(effectiveProvider?.id || null, event)}
          >
            Gerenciar provedores
          </Button>
        </Group>

        <Text
          aria-live="polite"
          style={{
            position: "absolute",
            width: 1,
            height: 1,
            overflow: "hidden",
            clip: "rect(0 0 0 0)",
            whiteSpace: "nowrap",
          }}
        >
          {liveAnnouncement}
        </Text>
      </Stack>

      <ProviderDrawer
        opened={drawerOpen}
        onClose={closeDrawer}
        focusProvider={drawerFocus}
        onUpdated={() => loadCatalog(true)}
      />
    </Paper>
  );
}
