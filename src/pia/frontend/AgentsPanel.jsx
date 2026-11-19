import React, { useEffect, useRef, useState } from "react";
import {
  Accordion,
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Code,
  Group,
  Loader,
  Menu,
  Modal,
  Paper,
  PasswordInput,
  Select,
  SimpleGrid,
  Skeleton,
  Stack,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import {
  CircleAlert,
  CircleCheck,
  CircleHelp,
  Copy,
  Download,
  ExternalLink,
  KeyRound,
  LogIn,
  MoreHorizontal,
  RefreshCw,
} from "lucide-react";
import { api, copy, report, safe } from "./api";
import { notify } from "./toasts";
import SettingsPanel from "./Settings";
import AgentSetup from "./AgentSetup";
import { Icon } from "./shared";
import {
  PROVIDERS_ORDER,
  buildSelectorOptions,
  formatLocalTimeHHMM,
  formatProviderQuota,
  formatSessionUsage,
  normalizeProviderStatus,
} from "./models";

function statusIcon(status, authType) {
  if (status === "connected") return <CircleCheck size={14} />;
  if (status === "login_required") {
    return authType === "api_key" ? (
      <KeyRound size={14} />
    ) : (
      <LogIn size={14} />
    );
  }
  if (status === "error") return <CircleAlert size={14} />;
  return <Download size={14} />;
}

function connectionTypeLabel(authType) {
  if (authType === "cli") return "Login pelo CLI oficial";
  if (authType === "api_key") return "Chave no Cofre da PIA";
  return "Execução local";
}

function orderProviders(providers = []) {
  const byId = new Map(providers.map((p) => [p.id, p]));
  return [
    ...PROVIDERS_ORDER.map((id) => byId.get(id)).filter(Boolean),
    ...providers.filter((p) => !PROVIDERS_ORDER.includes(p.id)),
  ];
}

export default function AgentsPanel({
  compact = false,
  focusProvider = null,
  onStatusChange,
} = {}) {
  const [catalog, setCatalog] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [verifyingId, setVerifyingId] = useState(null);
  const [quotaLoadingId, setQuotaLoadingId] = useState(null);
  const [announcement, setAnnouncement] = useState("");

  // Compatibilidade com react_desktop_smoke.py + modal de instalação CLI
  const [helpOpen, setHelpOpen] = useState(false);
  const [helpProvider, setHelpProvider] = useState("codex");

  // Modais e formulários inline
  const [resetModalOpen, setResetModalOpen] = useState(false);
  const [keyEditorId, setKeyEditorId] = useState(null);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [keyError, setKeyError] = useState("");
  const [removeKeyTarget, setRemoveKeyTarget] = useState(null);
  const [cliLoginModal, setCliLoginModal] = useState(null);
  const [modelsModalProvider, setModelsModalProvider] = useState(null);

  const keyInputRef = useRef(null);
  const cardRefs = useRef({});

  async function loadCatalog({ silent = false } = {}) {
    if (!silent) setLoading(true);
    setLoadError(false);
    try {
      const data = await api("/models/status");
      setCatalog(data);
    } catch {
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadCatalog();
  }, []);

  useEffect(() => {
    if (focusProvider && cardRefs.current[focusProvider]) {
      cardRefs.current[focusProvider].scrollIntoView({
        behavior: "smooth",
        block: "nearest",
      });
    }
  }, [focusProvider, catalog]);

  useEffect(() => {
    if (keyEditorId && keyInputRef.current) {
      keyInputRef.current.focus();
    }
  }, [keyEditorId]);

  function applyUpdatedProvider(updatedProvider, prevStatus) {
    if (!updatedProvider) return;
    setCatalog((old) => {
      if (!old) return old;
      const providers = Array.isArray(old.providers)
        ? old.providers.map((p) =>
            p.id === updatedProvider.id ? updatedProvider : p,
          )
        : [updatedProvider];
      return { ...old, providers };
    });
    if (
      prevStatus &&
      prevStatus !== "connected" &&
      updatedProvider.status === "connected"
    ) {
      const msg = `${updatedProvider.name} conectado.`;
      notify(msg);
      setAnnouncement(msg);
    } else if (updatedProvider.status === "error") {
      setAnnouncement(`${updatedProvider.name}: erro de autenticação.`);
    }
    onStatusChange?.(updatedProvider);
  }

  async function handleVerify(providerId) {
    const prev = catalog?.providers?.find((p) => p.id === providerId)?.status;
    setVerifyingId(providerId);
    try {
      const res = await api("/models/verify", { provider: providerId });
      applyUpdatedProvider(res.provider, prev);
    } catch (error) {
      report(error);
    } finally {
      setVerifyingId(null);
    }
  }

  async function handleCliLogin(provider) {
    setVerifyingId(provider.id);
    try {
      const res = await api("/models/connect", {
        provider: provider.id,
        action: "login",
      });
      if (res.provider) {
        applyUpdatedProvider(res.provider, provider.status);
      }
      if (res.provider?.status !== "connected") {
        setCliLoginModal({
          providerId: provider.id,
          name: provider.name,
          started: Boolean(res.started),
          command:
            res.command ||
            provider.login_command ||
            (provider.id === "codex" ? "codex login" : "agy"),
          error: "",
        });
      }
    } catch (error) {
      report(error);
    } finally {
      setVerifyingId(null);
    }
  }

  async function handleCliVerifyAfterLogin() {
    if (!cliLoginModal) return;
    const providerId = cliLoginModal.providerId;
    const prev = catalog?.providers?.find((p) => p.id === providerId)?.status;
    setVerifyingId(providerId);
    try {
      const res = await api("/models/connect", {
        provider: providerId,
        action: "verify",
      });
      applyUpdatedProvider(res.provider, prev);
      if (res.provider?.status === "connected") {
        setCliLoginModal(null);
      } else {
        setCliLoginModal((old) =>
          old
            ? {
                ...old,
                error: `Ainda não encontramos um login ativo no ${old.name}. Conclua o login na janela do CLI e verifique de novo.`,
              }
            : null,
        );
      }
    } catch (error) {
      setCliLoginModal((old) =>
        old
          ? {
              ...old,
              error: error?.message || "Não foi possível verificar o login.",
            }
          : null,
      );
    } finally {
      setVerifyingId(null);
    }
  }

  async function handleSaveKey(provider) {
    const keyValue = apiKeyInput.trim();
    setApiKeyInput("");
    if (!keyValue) {
      setKeyError("Cole a chave antes de salvar.");
      return;
    }
    setKeyError("");
    setVerifyingId(provider.id);
    try {
      const res = await api("/models/connect", {
        provider: provider.id,
        api_key: keyValue,
      });
      if (res.provider?.status === "connected") {
        setKeyEditorId(null);
        notify(`Chave salva. ${provider.name} conectado.`);
        setAnnouncement(`${provider.name} conectado.`);
        applyUpdatedProvider(res.provider, "connected");
        await loadCatalog({ silent: true });
        onStatusChange?.(res.provider);
      } else {
        if (res.provider) applyUpdatedProvider(res.provider, provider.status);
        setKeyError(
          res.provider?.status_detail ||
            `A chave foi recusada pelo ${provider.name}. Confira se copiou a chave inteira e tente de novo.`,
        );
      }
    } catch (error) {
      setKeyError(
        error?.message ||
          `A chave foi recusada pelo ${provider.name}. Confira se copiou a chave inteira e tente de novo.`,
      );
    } finally {
      setApiKeyInput("");
      setVerifyingId(null);
    }
  }

  async function handleRemoveKey() {
    if (!removeKeyTarget) return;
    const target = removeKeyTarget;
    setVerifyingId(target.id);
    try {
      const res = await api("/models/disconnect", { provider: target.id });
      setRemoveKeyTarget(null);
      notify("Chave removida.");
      setAnnouncement(`${target.name} desconectado.`);
      if (res.provider) applyUpdatedProvider(res.provider, target.status);
      await loadCatalog({ silent: true });
      onStatusChange?.(res.provider);
    } catch (error) {
      report(error);
    } finally {
      setVerifyingId(null);
    }
  }

  async function handleRefreshQuota(providerId) {
    setQuotaLoadingId(providerId);
    try {
      const res = await api("/models/quota", { provider: providerId });
      if (res.provider) {
        applyUpdatedProvider(res.provider, res.provider.status);
      } else if (res.provider_quota) {
        setCatalog((old) =>
          old
            ? {
                ...old,
                providers: old.providers.map((p) =>
                  p.id === providerId
                    ? { ...p, provider_quota: res.provider_quota }
                    : p,
                ),
              }
            : old,
        );
      }
    } catch (error) {
      report(error);
    } finally {
      setQuotaLoadingId(null);
    }
  }

  async function handleResetSession() {
    try {
      await api("/models/reset-session", {});
      setResetModalOpen(false);
      notify("Contagem da sessão zerada.");
      setAnnouncement("Contagem da sessão zerada.");
      await loadCatalog({ silent: true });
      onStatusChange?.();
    } catch (error) {
      report(error);
    }
  }

  async function handleDefaultChange(value) {
    let provider = "";
    let model = "";
    if (value === "free" || value === "paid") {
      provider = value;
      model = value;
    } else if (value && value.includes("::")) {
      const idx = value.indexOf("::");
      provider = value.slice(0, idx);
      model = value.slice(idx + 2);
    }
    try {
      await api("/models/default", { provider, model });
      await loadCatalog({ silent: true });
      onStatusChange?.();
    } catch (error) {
      report(error);
    }
  }

  const providers = orderProviders(catalog?.providers || []);
  const anyConnected = providers.some((p) => p.status === "connected");
  const sessionStartHHMM =
    formatLocalTimeHHMM(catalog?.session_started_at) || "--:--";
  const totalRequests = Number(catalog?.total_requests || 0);

  const selectorData = buildSelectorOptions(catalog);
  const defaultSelectValue = !catalog?.default_provider
    ? ""
    : catalog.default_provider === "free" || catalog.default_provider === "paid"
      ? catalog.default_provider
      : `${catalog.default_provider}::${catalog.default_model || catalog.default_provider}`;

  const defaultSelectOptions = [
    {
      group: "Padrão e automático",
      items: [
        { value: "", label: selectorData.defaultOption.label },
        ...selectorData.automaticOptions.map((o) => ({
          value: o.value,
          label: o.label,
        })),
      ],
    },
    ...selectorData.groups
      .filter((g) => g.connected && g.models.length > 0)
      .map((g) => ({
        group: g.name,
        items: g.models.map((m) => ({
          value: m.value,
          label: `${g.name} · ${m.label}`,
        })),
      })),
  ];

  return (
    <Stack gap="md">
      <div
        aria-live="polite"
        style={{
          position: "absolute",
          width: 1,
          height: 1,
          overflow: "hidden",
          clip: "rect(0 0 0 0)",
        }}
      >
        {announcement}
      </div>

      {!compact && (
        <Group justify="space-between" align="flex-start" wrap="wrap">
          <Stack gap={2} style={{ flex: 1, minWidth: 240 }}>
            <Title order={3}>Provedores de modelos</Title>
            <Text size="sm" c="dimmed">
              Conecte suas contas para usar outros modelos no Chat e no Podcast
              Automation. A PIA não lê nem copia logins de outros aplicativos.
            </Text>
          </Stack>
          <Group align="flex-end" gap="xs">
            <Select
              size="xs"
              label="Agente"
              data={[
                { value: "codex", label: "Codex" },
                { value: "agy", label: "Google Antigravity · AGY" },
              ]}
              value={helpProvider}
              onChange={(val) => val && setHelpProvider(val)}
              allowDeselect={false}
              w={220}
            />
            <Icon
              icon={CircleHelp}
              label="Como instalar e configurar o agente"
              onClick={() => setHelpOpen(true)}
            />
          </Group>
        </Group>
      )}

      {loading && !catalog ? (
        <SimpleGrid cols={{ base: 1, md: compact ? 1 : 2 }} spacing="md">
          {PROVIDERS_ORDER.map((id) => (
            <Paper key={id} withBorder p="md">
              <Stack gap="xs">
                <Group justify="space-between">
                  <Skeleton height={18} width={140} />
                  <Skeleton height={20} width={96} radius="xl" />
                </Group>
                <Skeleton height={14} width={160} />
                <SimpleGrid cols={2} spacing="xs">
                  <Skeleton height={54} />
                  <Skeleton height={54} />
                </SimpleGrid>
                <Skeleton height={28} width={130} />
              </Stack>
            </Paper>
          ))}
        </SimpleGrid>
      ) : loadError ? (
        <Alert
          color="red"
          title="Não foi possível verificar os provedores agora."
        >
          <Button
            size="xs"
            variant="light"
            color="red"
            mt="xs"
            onClick={() => loadCatalog()}
          >
            Tentar novamente
          </Button>
        </Alert>
      ) : (
        <>
          <Paper withBorder p="sm">
            <Group justify="space-between" wrap="wrap" gap="xs">
              <Text size="sm">
                Sessão atual desde {sessionStartHHMM} · {totalRequests} req
                nesta sessão
              </Text>
              <Button
                size="xs"
                variant="subtle"
                color="gray"
                onClick={() => setResetModalOpen(true)}
              >
                Zerar contagem da sessão
              </Button>
            </Group>
          </Paper>

          {!compact && (
            <Select
              label="Modelo padrão das novas conversas"
              data={defaultSelectOptions}
              value={defaultSelectValue}
              onChange={handleDefaultChange}
              allowDeselect={false}
            />
          )}

          {!anyConnected && (
            <Alert color="blue" variant="light">
              Nenhum provedor conectado. O Chat continua usando o padrão da PIA.
              Conecte um provedor abaixo para escolher outros modelos.
            </Alert>
          )}

          <SimpleGrid cols={{ base: 1, md: compact ? 1 : 2 }} spacing="md">
            {providers.map((p) => {
              const isVerifying = verifyingId === p.id;
              const isQuotaLoading = quotaLoadingId === p.id;
              const statusMeta = normalizeProviderStatus(p.status);
              const usage = formatSessionUsage(p.session_usage);
              const quota = formatProviderQuota(p.provider_quota, p.id);
              const isEditingKey = keyEditorId === p.id;
              const docsUrl = p.docs_url;

              return (
                <Paper
                  key={p.id}
                  ref={(el) => {
                    cardRefs.current[p.id] = el;
                  }}
                  withBorder
                  p="md"
                  aria-busy={isVerifying ? "true" : undefined}
                  style={
                    focusProvider === p.id
                      ? { borderColor: "var(--mantine-color-violet-5)" }
                      : undefined
                  }
                >
                  <Stack gap="sm">
                    <Group justify="space-between" wrap="nowrap" gap="xs">
                      <Stack gap={2}>
                        <Text fw={600} size="sm">
                          {p.name}
                        </Text>
                        <Text size="xs" c="dimmed">
                          {connectionTypeLabel(p.auth_type)}
                        </Text>
                      </Stack>
                      {isVerifying ? (
                        <Badge
                          color="blue"
                          variant="light"
                          leftSection={<Loader size={12} />}
                        >
                          Verificando…
                        </Badge>
                      ) : (
                        <Badge
                          color={statusMeta.color}
                          variant="light"
                          leftSection={statusIcon(p.status, p.auth_type)}
                        >
                          {p.status_label || statusMeta.label}
                        </Badge>
                      )}
                    </Group>

                    <SimpleGrid cols={2} spacing="xs">
                      <Paper withBorder p="xs">
                        <Text size="xs" fw={600} c="dimmed">
                          Consumo na sessão
                        </Text>
                        <Text size="xs" mt={4}>
                          {usage.summary}
                        </Text>
                        {usage.detail && (
                          <Text size="xs" c="dimmed">
                            {usage.detail}
                          </Text>
                        )}
                      </Paper>
                      <Paper withBorder p="xs">
                        <Group justify="space-between" wrap="nowrap" gap={4}>
                          <Text size="xs" fw={600} c="dimmed">
                            Saldo do provedor
                          </Text>
                          {p.id === "openrouter" &&
                            p.status === "connected" && (
                              <Tooltip label="Atualizar saldo">
                                <ActionIcon
                                  size="xs"
                                  variant="subtle"
                                  aria-label="Atualizar saldo"
                                  loading={isQuotaLoading}
                                  onClick={() => handleRefreshQuota(p.id)}
                                >
                                  <RefreshCw size={12} />
                                </ActionIcon>
                              </Tooltip>
                            )}
                        </Group>
                        {isQuotaLoading ? (
                          <Text size="xs" mt={4} c="dimmed">
                            Consultando saldo…
                          </Text>
                        ) : (
                          <>
                            <Text size="xs" mt={4}>
                              {quota.label}
                            </Text>
                            {quota.checkedAtText && (
                              <Text size="xs" c="dimmed">
                                {quota.checkedAtText}
                              </Text>
                            )}
                            {quota.detail && (
                              <Text size="xs" c="dimmed">
                                {quota.detail}
                              </Text>
                            )}
                          </>
                        )}
                      </Paper>
                    </SimpleGrid>

                    {p.auth_type === "api_key" &&
                      p.configured &&
                      p.status === "connected" &&
                      !isEditingKey && (
                        <Text size="xs" c="dimmed">
                          Chave salva no Cofre da PIA
                        </Text>
                      )}

                    {p.status === "error" && p.status_detail && (
                      <Text size="xs" c="red">
                        {p.status_detail}
                      </Text>
                    )}

                    {p.id === "local" && p.status === "not_installed" && (
                      <Text size="xs" c="dimmed">
                        {p.status_detail ||
                          "O Ollama não respondeu em http://localhost:11434. Abra o Ollama ou instale pelo site oficial."}
                      </Text>
                    )}

                    {p.auth_type === "api_key" && isEditingKey && (
                      <Stack gap="xs">
                        <PasswordInput
                          ref={keyInputRef}
                          size="xs"
                          autoComplete="off"
                          label={`Chave da API do ${p.name}`}
                          placeholder="Cole a chave aqui"
                          description="A chave vai direto para o Cofre da PIA e não aparece mais na tela."
                          value={apiKeyInput}
                          onChange={(e) => setApiKeyInput(e.target.value)}
                          error={keyError || undefined}
                          disabled={isVerifying}
                        />
                        <Group gap="xs">
                          <Button
                            size="xs"
                            loading={isVerifying}
                            onClick={() => handleSaveKey(p)}
                          >
                            Salvar e verificar
                          </Button>
                          <Button
                            size="xs"
                            variant="subtle"
                            color="gray"
                            disabled={isVerifying}
                            onClick={() => {
                              setKeyEditorId(null);
                              setApiKeyInput("");
                              setKeyError("");
                            }}
                          >
                            Cancelar
                          </Button>
                        </Group>
                      </Stack>
                    )}

                    <Group justify="space-between" wrap="wrap" gap="xs">
                      <Group gap="xs">
                        {p.auth_type === "cli" && (
                          <>
                            {(p.status === "login_required" ||
                              p.status === "error") && (
                              <Button
                                size="xs"
                                disabled={isVerifying}
                                onClick={() => handleCliLogin(p)}
                              >
                                {p.status === "error"
                                  ? "Fazer login de novo"
                                  : "Fazer login"}
                              </Button>
                            )}
                            {p.status === "connected" && (
                              <Button
                                size="xs"
                                variant="light"
                                disabled={isVerifying}
                                onClick={() => handleVerify(p.id)}
                              >
                                Verificar conexão
                              </Button>
                            )}
                            <Button
                              size="xs"
                              variant={
                                p.status === "not_installed"
                                  ? "filled"
                                  : "subtle"
                              }
                              onClick={() => {
                                setHelpProvider(p.id);
                                setHelpOpen(true);
                              }}
                            >
                              Como instalar e fazer login
                            </Button>
                          </>
                        )}

                        {p.auth_type === "api_key" && !isEditingKey && (
                          <>
                            {(p.status === "login_required" ||
                              p.status === "error") && (
                              <Button
                                size="xs"
                                disabled={isVerifying}
                                onClick={() => {
                                  setKeyEditorId(p.id);
                                  setApiKeyInput("");
                                  setKeyError("");
                                }}
                              >
                                {p.status === "error"
                                  ? "Trocar chave"
                                  : "Adicionar chave"}
                              </Button>
                            )}
                            {p.status === "connected" && (
                              <Button
                                size="xs"
                                variant="light"
                                disabled={isVerifying}
                                onClick={() => handleVerify(p.id)}
                              >
                                Verificar conexão
                              </Button>
                            )}
                          </>
                        )}

                        {p.auth_type === "local" && (
                          <Button
                            size="xs"
                            variant={
                              p.status === "not_installed" ? "filled" : "light"
                            }
                            disabled={isVerifying}
                            onClick={() => handleVerify(p.id)}
                          >
                            Verificar serviço
                          </Button>
                        )}
                      </Group>

                      <Menu position="bottom-end" withinPortal>
                        <Menu.Target>
                          <ActionIcon
                            size="sm"
                            variant="subtle"
                            aria-label={`Mais ações de ${p.name}`}
                          >
                            <MoreHorizontal size={16} />
                          </ActionIcon>
                        </Menu.Target>
                        <Menu.Dropdown>
                          <Menu.Item onClick={() => setModelsModalProvider(p)}>
                            Ver modelos disponíveis
                          </Menu.Item>
                          {p.auth_type === "api_key" && (
                            <Menu.Item
                              onClick={() => {
                                setKeyEditorId(p.id);
                                setApiKeyInput("");
                                setKeyError("");
                              }}
                            >
                              Trocar chave
                            </Menu.Item>
                          )}
                          {p.auth_type === "api_key" && p.configured && (
                            <Menu.Item
                              color="red"
                              onClick={() => setRemoveKeyTarget(p)}
                            >
                              Remover chave
                            </Menu.Item>
                          )}
                          {docsUrl && (
                            <Menu.Item
                              component="a"
                              href={docsUrl}
                              target="_blank"
                              rel="noreferrer"
                              rightSection={<ExternalLink size={13} />}
                            >
                              Documentação oficial ↗
                            </Menu.Item>
                          )}
                        </Menu.Dropdown>
                      </Menu>
                    </Group>
                  </Stack>
                </Paper>
              );
            })}
          </SimpleGrid>
        </>
      )}

      {!compact && (
        <Accordion variant="separated">
          <Accordion.Item value="advanced">
            <Accordion.Control>Avançado</Accordion.Control>
            <Accordion.Panel>
              <Stack gap="md">
                <Paper withBorder p="md">
                  <Title order={5}>Protocolos da PIA</Title>
                  <Text size="sm" mt={4}>
                    MCP stateless HTTP e AG-UI com SSE. Todos exigem o Bearer
                    configurado na PIA.
                  </Text>
                  <Code block mt="xs">
                    {"/protocols/mcp\n/protocols/ag-ui"}
                  </Code>
                  <Text size="sm" mt="xs" c="dimmed">
                    Cadastre o endpoint MCP no Codex/Antigravity para
                    disponibilizar as ferramentas da PIA ao outro agente. Isso
                    não altera automaticamente a configuração dos CLIs.
                  </Text>
                </Paper>
                <SettingsPanel section="Connectors/agents" />
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        </Accordion>
      )}

      <AgentSetup
        opened={helpOpen}
        onClose={() => setHelpOpen(false)}
        provider={helpProvider}
        status={catalog?.providers?.find((p) => p.id === helpProvider)}
        onVerify={(id) => handleVerify(id)}
      />

      <Modal
        opened={resetModalOpen}
        onClose={() => setResetModalOpen(false)}
        title="Zerar a contagem desta sessão?"
      >
        <Stack gap="md">
          <Text size="sm">
            Os contadores de requisições e tokens de todos os provedores voltam
            a zero. Conversas e configurações não são apagadas.
          </Text>
          <Group justify="flex-end">
            <Button
              variant="subtle"
              color="gray"
              onClick={() => setResetModalOpen(false)}
            >
              Cancelar
            </Button>
            <Button color="red" onClick={safe(handleResetSession)}>
              Zerar contagem
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={Boolean(removeKeyTarget)}
        onClose={() => setRemoveKeyTarget(null)}
        title={
          removeKeyTarget
            ? `Remover a chave do ${removeKeyTarget.name}?`
            : "Remover chave"
        }
      >
        <Stack gap="md">
          <Text size="sm">
            O {removeKeyTarget?.name} fica desconectado e conversas que usam
            este provedor não poderão enviar mensagens até você conectar de
            novo.
          </Text>
          <Group justify="flex-end">
            <Button
              variant="subtle"
              color="gray"
              onClick={() => setRemoveKeyTarget(null)}
            >
              Cancelar
            </Button>
            <Button color="red" onClick={safe(handleRemoveKey)}>
              Remover chave
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={Boolean(cliLoginModal)}
        onClose={() => setCliLoginModal(null)}
        title={
          cliLoginModal ? `Fazer login no ${cliLoginModal.name}` : "Fazer login"
        }
      >
        {cliLoginModal && (
          <Stack gap="md">
            {cliLoginModal.started ? (
              <Text size="sm">
                Abrimos o login oficial do {cliLoginModal.name} em outra janela.
                Conclua lá e volte aqui.
              </Text>
            ) : (
              <>
                <Text size="sm">
                  Não foi possível abrir o login automaticamente. Abra um
                  terminal, rode o comando abaixo e siga as instruções no
                  navegador.
                </Text>
                <Group wrap="nowrap" align="start">
                  <Code block className="grow">
                    {cliLoginModal.command}
                  </Code>
                  <Button
                    size="xs"
                    variant="light"
                    leftSection={<Copy size={14} />}
                    onClick={() => {
                      copy(cliLoginModal.command);
                      notify("Comando copiado.");
                    }}
                  >
                    Copiar comando
                  </Button>
                </Group>
              </>
            )}
            {cliLoginModal.error && (
              <Alert color="yellow">{cliLoginModal.error}</Alert>
            )}
            <Text size="xs" c="dimmed">
              A PIA não pede nem guarda sua senha. O login fica com o{" "}
              {cliLoginModal.name}.
            </Text>
            <Group justify="flex-end">
              <Button
                variant="subtle"
                color="gray"
                onClick={() => setCliLoginModal(null)}
              >
                Cancelar
              </Button>
              <Button
                loading={verifyingId === cliLoginModal.providerId}
                onClick={safe(handleCliVerifyAfterLogin)}
              >
                Já fiz login · Verificar
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>

      <Modal
        opened={Boolean(modelsModalProvider)}
        onClose={() => setModelsModalProvider(null)}
        title={
          modelsModalProvider
            ? `Modelos disponíveis · ${modelsModalProvider.name}`
            : "Modelos disponíveis"
        }
      >
        {modelsModalProvider && (
          <Stack gap="xs">
            {modelsModalProvider.models?.length ? (
              modelsModalProvider.models.map((m) => (
                <Paper key={m.id} withBorder p="xs">
                  <Text size="sm" fw={500}>
                    {m.label || m.id}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {m.id}
                  </Text>
                </Paper>
              ))
            ) : (
              <Text size="sm" c="dimmed">
                Nenhum modelo listado no momento.
              </Text>
            )}
          </Stack>
        )}
      </Modal>
    </Stack>
  );
}
