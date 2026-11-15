import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Code,
  Collapse,
  Group,
  Modal,
  Paper,
  PasswordInput,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import {
  CheckCircle2,
  ExternalLink,
  Eye,
  Globe,
  KeyRound,
  Layers,
  Pencil,
  Plug,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  Users,
  Wrench,
} from "lucide-react";
import React, { useEffect, useState } from "react";
import { api, safe } from "./api";
import { usePia } from "./shared";
import { notify } from "./toasts";
import {
  MCP_ACCOUNT_AUTH_TYPES,
  MCP_ACCOUNT_MODES,
  MCP_DOCS_URL,
  MCP_TRANSPORTS,
  createEmptyAccountDraft,
  createEmptyMcpDraft,
  draftToMcpPayload,
  mcpServerToDraft,
  normalizeMcpServers,
  normalizeMcpTools,
  validateMcpDraft,
} from "./extensions-helpers";

function PairListSection({
  title,
  pairs,
  onChange,
  addLabel,
  keyPlaceholder = "Chave",
  valuePlaceholder = "Valor",
}) {
  function updateRow(index, field, value) {
    const next = pairs.map((row, idx) =>
      idx === index ? { ...row, [field]: value } : row,
    );
    onChange(next);
  }

  function removeRow(index) {
    const filtered = pairs.filter((_, idx) => idx !== index);
    onChange(filtered.length ? filtered : [{ key: "", value: "" }]);
  }

  function addRow() {
    onChange([...pairs, { key: "", value: "" }]);
  }

  return (
    <Paper className="mcp-form-box" p="md" radius="md" withBorder>
      <Stack gap="xs">
        <Text size="sm" fw={600}>
          {title}
        </Text>
        {pairs.map((row, index) => (
          <Group key={index} gap="xs" wrap="nowrap" align="center">
            <TextInput
              placeholder={keyPlaceholder}
              value={row.key}
              onChange={(event) =>
                updateRow(index, "key", event.currentTarget.value)
              }
              style={{ flex: 1 }}
            />
            <TextInput
              placeholder={valuePlaceholder}
              value={row.value}
              onChange={(event) =>
                updateRow(index, "value", event.currentTarget.value)
              }
              style={{ flex: 1 }}
            />
            <Tooltip label="Remover linha">
              <ActionIcon
                variant="subtle"
                color="gray"
                aria-label="Remover linha"
                onClick={() => removeRow(index)}
              >
                <Trash2 size={16} />
              </ActionIcon>
            </Tooltip>
          </Group>
        ))}
        <Button
          variant="light"
          color="gray"
          size="xs"
          fullWidth
          leftSection={<Plus size={14} />}
          onClick={addRow}
        >
          {addLabel}
        </Button>
      </Stack>
    </Paper>
  );
}

export default function McpConnectorsPanel() {
  const { refresh: refreshWorkspace } = usePia();
  const [servers, setServers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingId, setEditingId] = useState("");
  const [draft, setDraft] = useState(() => createEmptyMcpDraft());
  const [saving, setSaving] = useState(false);
  const [showDirectToken, setShowDirectToken] = useState(false);
  const [showAccountsSection, setShowAccountsSection] = useState(true);
  const [inspectServer, setInspectServer] = useState(null);
  const [inspectTools, setInspectTools] = useState([]);
  const [inspectLoading, setInspectLoading] = useState(false);
  const [oauthBusyKey, setOauthBusyKey] = useState("");

  async function loadServers() {
    setLoading(true);
    try {
      const response = await api("/mcp/servers");
      setServers(normalizeMcpServers(response));
    } catch {
      setServers([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadServers();
  }, []);

  function openNewModal() {
    setEditingId("");
    setDraft(createEmptyMcpDraft());
    setShowDirectToken(false);
    setShowAccountsSection(true);
    setEditorOpen(true);
  }

  function openEditModal(server) {
    setEditingId(server.id);
    const nextDraft = mcpServerToDraft(server);
    setDraft(nextDraft);
    setShowDirectToken(Boolean(nextDraft.bearer_token));
    setShowAccountsSection(true);
    setEditorOpen(true);
  }

  async function handleSave() {
    const check = validateMcpDraft(draft);
    if (!check.valid) {
      notify(check.errors[0]);
      return;
    }
    setSaving(true);
    try {
      const payload = draftToMcpPayload(draft);
      if (editingId) {
        await api(`/mcp/servers/${encodeURIComponent(editingId)}`, payload, {
          method: "PUT",
        });
      } else {
        await api("/mcp/servers", payload, { method: "POST" });
      }
      setEditorOpen(false);
      await loadServers();
      refreshWorkspace?.();
      notify("Conector MCP salvo.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(server) {
    if (!confirm(`Excluir o conector MCP "${server.name}"?`)) return;
    await api(
      `/mcp/servers/${encodeURIComponent(server.id)}`,
      {},
      { method: "DELETE" },
    );
    if (inspectServer?.id === server.id) setInspectServer(null);
    await loadServers();
    refreshWorkspace?.();
    notify("Conector MCP excluído.");
  }

  async function handleToggle(server) {
    await api(
      `/mcp/servers/${encodeURIComponent(server.id)}`,
      { enabled: !server.enabled },
      { method: "PUT" },
    );
    await loadServers();
  }

  async function handleContextSwitch(server, nextContext) {
    await api(
      `/mcp/servers/${encodeURIComponent(server.id)}`,
      { active_context: nextContext },
      { method: "PUT" },
    );
    await loadServers();
    notify(`Contexto ativo alterado para "${nextContext}".`);
  }

  async function openInspect(server) {
    setInspectServer(server);
    setInspectTools(server.tools || []);
    setInspectLoading(true);
    try {
      const response = await api(
        `/mcp/servers/${encodeURIComponent(server.id)}/tools`,
      );
      setInspectTools(normalizeMcpTools(response));
    } catch {
      setInspectTools(server.tools || []);
    } finally {
      setInspectLoading(false);
    }
  }

  async function handleReinspect() {
    if (!inspectServer) return;
    setInspectLoading(true);
    try {
      const response = await api(
        `/mcp/servers/${encodeURIComponent(inspectServer.id)}/inspect`,
        {},
        { method: "POST" },
      );
      const tools = normalizeMcpTools(response);
      setInspectTools(tools);
      await loadServers();
      notify(`${tools.length} ferramenta(s) encontrada(s).`);
    } finally {
      setInspectLoading(false);
    }
  }

  async function handleOAuthStart(serverId, account = null, index = null) {
    const busyKey = `${serverId || "new"}:${index ?? "server"}`;
    setOauthBusyKey(busyKey);
    try {
      const targetId = serverId || editingId;
      if (!targetId) {
        notify("Salve o conector primeiro antes de iniciar o fluxo OAuth.");
        return;
      }
      const payload = account
        ? {
            account_id: account.id || undefined,
            name: account.name,
            context: account.context,
            client_id: account.oauth_client_id,
            client_secret: account.oauth_client_secret,
            auth_url: account.oauth_auth_url,
            token_url: account.oauth_token_url,
            scopes: account.oauth_scopes,
          }
        : {
            client_id: draft.oauth_client_id,
            client_secret: draft.oauth_client_secret,
            auth_url: draft.oauth_auth_url,
            token_url: draft.oauth_token_url,
            scopes: draft.oauth_scopes,
          };
      const result = await api(
        `/mcp/servers/${encodeURIComponent(targetId)}/oauth/start`,
        payload,
      );
      const authUrl =
        result?.authorization_url || result?.auth_url || result?.url;
      if (authUrl && /^https?:\/\//i.test(authUrl)) {
        window.open(authUrl, "_blank", "noopener,noreferrer");
        notify("Fluxo OAuth iniciado em uma nova aba.");
      } else {
        notify(result?.message || "Sessão OAuth preparada pelo servidor.");
      }
      await loadServers();
    } finally {
      setOauthBusyKey("");
    }
  }

  function addAccount() {
    setDraft((prev) => ({
      ...prev,
      accounts: [
        ...prev.accounts,
        createEmptyAccountDraft(prev.accounts.length + 1),
      ],
    }));
  }

  function updateAccount(index, field, value) {
    setDraft((prev) => ({
      ...prev,
      accounts: prev.accounts.map((acc, idx) =>
        idx === index ? { ...acc, [field]: value } : acc,
      ),
    }));
  }

  function removeAccount(index) {
    setDraft((prev) => ({
      ...prev,
      accounts: prev.accounts.filter((_, idx) => idx !== index),
    }));
  }

  return (
    <div className="panel">
      <Group justify="space-between" align="flex-start" wrap="wrap">
        <div>
          <Text size="xl" fw={700}>
            Conectores MCP Personalizados
          </Text>
          <Text size="sm" c="dimmed">
            Conecte servidores Model Context Protocol (STDIO ou HTTP com
            streaming), configure autenticação OAuth e gerencie múltiplas contas
            com rotação, acesso simultâneo ou separação por contexto.
          </Text>
        </div>
        <Group gap="xs">
          <Button
            variant="light"
            color="gray"
            leftSection={<RefreshCw size={15} />}
            onClick={safe(loadServers)}
            loading={loading}
          >
            Atualizar
          </Button>
          <Button leftSection={<Plus size={16} />} onClick={openNewModal}>
            Conectar MCP personalizado
          </Button>
        </Group>
      </Group>

      {loading && servers.length === 0 ? (
        <Text c="dimmed">Carregando conectores MCP…</Text>
      ) : servers.length === 0 ? (
        <Paper p="xl" radius="md" withBorder className="mcp-empty-card">
          <Stack align="center" gap="sm">
            <Plug size={28} />
            <Text fw={600}>Nenhum conector MCP personalizado cadastrado</Text>
            <Text size="sm" c="dimmed" ta="center" maw={480}>
              Adicione servidores MCP via STDIO ou HTTP com streaming para expor
              novas ferramentas ao chat da PIA.
            </Text>
            <Button leftSection={<Plus size={15} />} onClick={openNewModal}>
              Conectar a um MCP personalizado
            </Button>
          </Stack>
        </Paper>
      ) : (
        <Stack gap="sm">
          {servers.map((server) => {
            const modeMeta =
              MCP_ACCOUNT_MODES.find((m) => m.value === server.account_mode) ||
              MCP_ACCOUNT_MODES[2];
            const contexts = server.available_contexts || [];
            return (
              <Paper
                key={server.id}
                className="mcp-connector-card"
                p="md"
                radius="md"
                withBorder
              >
                <Group justify="space-between" align="flex-start" wrap="wrap">
                  <Stack gap={6} style={{ flex: 1, minWidth: 260 }}>
                    <Group gap="xs" wrap="wrap">
                      <Text fw={600} size="md">
                        {server.name}
                      </Text>
                      <Badge variant="light" color="blue" size="sm">
                        {server.transport === "http"
                          ? "HTTP com streaming"
                          : "STDIO"}
                      </Badge>
                      <Badge variant="light" color="teal" size="sm">
                        Modo: {modeMeta.label}
                      </Badge>
                      <Badge
                        variant="dot"
                        color={server.enabled ? "green" : "gray"}
                        size="sm"
                      >
                        {server.enabled ? "Ativo" : "Pausado"}
                      </Badge>
                      <Badge
                        variant="outline"
                        color="gray"
                        size="sm"
                        leftSection={<Wrench size={11} />}
                      >
                        {server.tool_count} ferramenta(s)
                      </Badge>
                    </Group>

                    {server.description && (
                      <Text size="sm" c="dimmed">
                        {server.description}
                      </Text>
                    )}

                    <Group gap="md" wrap="wrap">
                      <Text size="xs" c="dimmed">
                        {server.transport === "http"
                          ? server.url || "URL não informada"
                          : [server.command, ...(server.args || [])]
                              .filter(Boolean)
                              .join(" ") || "Comando STDIO"}
                      </Text>
                      {server.accounts.length > 0 && (
                        <Group gap={4}>
                          <Users size={13} />
                          <Text size="xs" c="dimmed">
                            {server.accounts.length} conta(s):{" "}
                            {server.accounts
                              .map((a) => `${a.name} (${a.context})`)
                              .join(", ")}
                          </Text>
                        </Group>
                      )}
                    </Group>

                    {server.account_mode === "alternating" &&
                      contexts.length > 0 && (
                        <Group gap="xs" align="center" mt={4}>
                          <Text size="xs" fw={500}>
                            Contexto ativo:
                          </Text>
                          <Select
                            size="xs"
                            w={170}
                            value={server.active_context || contexts[0]}
                            data={contexts.map((ctx) => ({
                              value: ctx,
                              label: ctx,
                            }))}
                            onChange={(val) =>
                              val &&
                              safe(() => handleContextSwitch(server, val))()
                            }
                          />
                        </Group>
                      )}
                  </Stack>

                  <Group gap="xs" align="center" wrap="wrap">
                    <Switch
                      checked={server.enabled}
                      onChange={safe(() => handleToggle(server))}
                      aria-label={`Alternar ${server.name}`}
                    />
                    <Button
                      size="xs"
                      variant="light"
                      leftSection={<Eye size={14} />}
                      onClick={safe(() => openInspect(server))}
                    >
                      Visualizar
                    </Button>
                    <Button
                      size="xs"
                      variant="default"
                      leftSection={<Pencil size={14} />}
                      onClick={() => openEditModal(server)}
                    >
                      Editar
                    </Button>
                    <ActionIcon
                      variant="subtle"
                      color="red"
                      aria-label={`Excluir ${server.name}`}
                      onClick={safe(() => handleDelete(server))}
                    >
                      <Trash2 size={16} />
                    </ActionIcon>
                  </Group>
                </Group>
              </Paper>
            );
          })}
        </Stack>
      )}

      {/* Modal Estilo ChatGPT: Conectar a um MCP personalizado */}
      <Modal
        opened={editorOpen}
        onClose={() => setEditorOpen(false)}
        size="lg"
        radius="md"
        title={
          <Stack gap={2}>
            <Text size="lg" fw={700}>
              Conectar a um MCP personalizado
            </Text>
            <a
              href={MCP_DOCS_URL}
              target="_blank"
              rel="noreferrer"
              className="mcp-docs-link"
            >
              <span>Documentos</span>
              <Globe size={13} />
            </a>
          </Stack>
        }
      >
        <Stack gap="sm" className="mcp-chatgpt-modal">
          <Paper className="mcp-form-box" p="md" radius="md" withBorder>
            <Stack gap="sm">
              <TextInput
                label="Nome"
                placeholder="MCP server name"
                value={draft.name}
                onChange={(event) =>
                  setDraft((prev) => ({
                    ...prev,
                    name: event.currentTarget.value,
                  }))
                }
              />

              <TextInput
                label="Descrição (opcional)"
                placeholder="Ex.: Integração de armazenamento em nuvem ou geração de mídia"
                value={draft.description}
                onChange={(event) =>
                  setDraft((prev) => ({
                    ...prev,
                    description: event.currentTarget.value,
                  }))
                }
              />

              <Group
                justify="space-between"
                align="center"
                className="mcp-type-row"
              >
                <Text size="sm" fw={600}>
                  Tipo
                </Text>
                <SegmentedControl
                  size="sm"
                  value={draft.transport}
                  onChange={(value) =>
                    setDraft((prev) => ({ ...prev, transport: value }))
                  }
                  data={MCP_TRANSPORTS}
                />
              </Group>
            </Stack>
          </Paper>

          {draft.transport === "http" ? (
            <>
              <Paper className="mcp-form-box" p="md" radius="md" withBorder>
                <TextInput
                  label="URL"
                  placeholder="https://mcp.example.com/mcp"
                  value={draft.url}
                  onChange={(event) =>
                    setDraft((prev) => ({
                      ...prev,
                      url: event.currentTarget.value,
                    }))
                  }
                />
              </Paper>

              <Paper className="mcp-form-box" p="md" radius="md" withBorder>
                <Stack gap="xs">
                  <TextInput
                    label="Variável de ambiente de token do portador"
                    placeholder="MCP_BEARER_TOKEN"
                    value={draft.bearer_token_env}
                    onChange={(event) =>
                      setDraft((prev) => ({
                        ...prev,
                        bearer_token_env: event.currentTarget.value,
                      }))
                    }
                  />
                  <Group justify="space-between">
                    <Button
                      variant="subtle"
                      size="compact-xs"
                      onClick={() => setShowDirectToken((v) => !v)}
                    >
                      {showDirectToken
                        ? "Ocultar token direto"
                        : "Informar bearer token diretamente"}
                    </Button>
                  </Group>
                  <Collapse in={showDirectToken}>
                    <PasswordInput
                      label="Token do portador (opcional)"
                      placeholder="sk-..."
                      value={draft.bearer_token}
                      onChange={(event) =>
                        setDraft((prev) => ({
                          ...prev,
                          bearer_token: event.currentTarget.value,
                        }))
                      }
                    />
                  </Collapse>
                </Stack>
              </Paper>

              <PairListSection
                title="Cabeçalhos"
                pairs={draft.headers}
                onChange={(headers) =>
                  setDraft((prev) => ({ ...prev, headers }))
                }
                addLabel="+ Adicionar cabeçalho"
              />

              <PairListSection
                title="Cabeçalhos a partir de variáveis do ambiente"
                pairs={draft.env_headers}
                onChange={(env_headers) =>
                  setDraft((prev) => ({ ...prev, env_headers }))
                }
                addLabel="+ Adicionar variável"
              />
            </>
          ) : (
            <>
              <Paper className="mcp-form-box" p="md" radius="md" withBorder>
                <Stack gap="sm">
                  <TextInput
                    label="Comando"
                    placeholder="npx, uvx ou python"
                    value={draft.command}
                    onChange={(event) =>
                      setDraft((prev) => ({
                        ...prev,
                        command: event.currentTarget.value,
                      }))
                    }
                  />
                  <TextInput
                    label="Argumentos"
                    placeholder="-y @modelcontextprotocol/server-everything"
                    value={draft.args}
                    onChange={(event) =>
                      setDraft((prev) => ({
                        ...prev,
                        args: event.currentTarget.value,
                      }))
                    }
                  />
                  <TextInput
                    label="Diretório de trabalho (opcional)"
                    placeholder="D:/projetos/meu-mcp"
                    value={draft.cwd}
                    onChange={(event) =>
                      setDraft((prev) => ({
                        ...prev,
                        cwd: event.currentTarget.value,
                      }))
                    }
                  />
                </Stack>
              </Paper>

              <PairListSection
                title="Variáveis de ambiente (STDIO)"
                pairs={draft.env}
                onChange={(env) => setDraft((prev) => ({ ...prev, env }))}
                addLabel="+ Adicionar variável"
              />
            </>
          )}

          <Paper className="mcp-form-box" p="md" radius="md" withBorder>
            <Stack gap="sm">
              <Group justify="space-between" align="center">
                <Group gap="xs">
                  <Layers size={16} />
                  <Text size="sm" fw={600}>
                    Autenticação OAuth e Multi-Contas
                  </Text>
                </Group>
                <Button
                  variant="subtle"
                  size="compact-xs"
                  onClick={() => setShowAccountsSection((v) => !v)}
                >
                  {showAccountsSection ? "Recolher" : "Expandir"}
                </Button>
              </Group>

              <Collapse in={showAccountsSection}>
                <Stack gap="sm">
                  <Text size="xs" fw={600} c="dimmed">
                    Modo de operação das contas
                  </Text>
                  <div className="mcp-account-modes">
                    {MCP_ACCOUNT_MODES.map((mode) => {
                      const active = draft.account_mode === mode.value;
                      return (
                        <button
                          key={mode.value}
                          type="button"
                          className={
                            "mcp-mode-option" + (active ? " active" : "")
                          }
                          onClick={() =>
                            setDraft((prev) => ({
                              ...prev,
                              account_mode: mode.value,
                            }))
                          }
                        >
                          <Group justify="space-between" mb={2}>
                            <Text size="sm" fw={600}>
                              {mode.label}
                            </Text>
                            {active && <CheckCircle2 size={15} />}
                          </Group>
                          <Text size="xs" c="dimmed" ta="left">
                            {mode.description}
                          </Text>
                        </button>
                      );
                    })}
                  </div>

                  {draft.account_mode === "alternating" && (
                    <TextInput
                      label="Contexto ativo padrão"
                      placeholder="Ex.: Pessoal, Trabalho, Empresa X"
                      value={draft.active_context}
                      onChange={(event) =>
                        setDraft((prev) => ({
                          ...prev,
                          active_context: event.currentTarget.value,
                        }))
                      }
                    />
                  )}

                  <Group justify="space-between" align="center" mt="xs">
                    <Text size="sm" fw={600}>
                      Contas vinculadas ({draft.accounts.length})
                    </Text>
                    <Button
                      size="xs"
                      variant="light"
                      leftSection={<Plus size={14} />}
                      onClick={addAccount}
                    >
                      Adicionar conta
                    </Button>
                  </Group>

                  {draft.accounts.length === 0 ? (
                    <Text size="xs" c="dimmed">
                      Opcional: adicione múltiplas contas para dividir créditos
                      (Distribuído), consultar em conjunto (Incremental) ou
                      alternar por contexto (Alternado).
                    </Text>
                  ) : (
                    <Stack gap="xs">
                      {draft.accounts.map((acc, index) => (
                        <Paper
                          key={acc.id || index}
                          p="sm"
                          radius="sm"
                          withBorder
                          className="mcp-account-item"
                        >
                          <Stack gap="xs">
                            <Group justify="space-between" wrap="nowrap">
                              <Group gap="xs" style={{ flex: 1 }}>
                                <TextInput
                                  size="xs"
                                  placeholder="Nome da conta (ex.: Suno 1)"
                                  value={acc.name}
                                  onChange={(event) =>
                                    updateAccount(
                                      index,
                                      "name",
                                      event.currentTarget.value,
                                    )
                                  }
                                  style={{ flex: 1 }}
                                />
                                <TextInput
                                  size="xs"
                                  placeholder="Contexto (ex.: Trabalho)"
                                  value={acc.context}
                                  onChange={(event) =>
                                    updateAccount(
                                      index,
                                      "context",
                                      event.currentTarget.value,
                                    )
                                  }
                                  style={{ flex: 1 }}
                                />
                                <Select
                                  size="xs"
                                  w={150}
                                  data={MCP_ACCOUNT_AUTH_TYPES}
                                  value={acc.auth_type}
                                  onChange={(value) =>
                                    updateAccount(
                                      index,
                                      "auth_type",
                                      value || "bearer",
                                    )
                                  }
                                />
                              </Group>
                              <ActionIcon
                                variant="subtle"
                                color="red"
                                aria-label="Remover conta"
                                onClick={() => removeAccount(index)}
                              >
                                <Trash2 size={15} />
                              </ActionIcon>
                            </Group>

                            {acc.auth_type === "bearer" && (
                              <PasswordInput
                                size="xs"
                                placeholder="Token / API Key desta conta"
                                value={acc.bearer_token}
                                onChange={(event) =>
                                  updateAccount(
                                    index,
                                    "bearer_token",
                                    event.currentTarget.value,
                                  )
                                }
                              />
                            )}

                            {acc.auth_type === "env" && (
                              <TextInput
                                size="xs"
                                placeholder="Nome da variável de ambiente (ex.: SUNO_TOKEN_2)"
                                value={acc.bearer_env}
                                onChange={(event) =>
                                  updateAccount(
                                    index,
                                    "bearer_env",
                                    event.currentTarget.value,
                                  )
                                }
                              />
                            )}

                            {acc.auth_type === "oauth" && (
                              <Stack gap="xs">
                                <Group grow>
                                  <TextInput
                                    size="xs"
                                    placeholder="OAuth Client ID"
                                    value={acc.oauth_client_id}
                                    onChange={(event) =>
                                      updateAccount(
                                        index,
                                        "oauth_client_id",
                                        event.currentTarget.value,
                                      )
                                    }
                                  />
                                  <PasswordInput
                                    size="xs"
                                    placeholder="OAuth Client Secret"
                                    value={acc.oauth_client_secret}
                                    onChange={(event) =>
                                      updateAccount(
                                        index,
                                        "oauth_client_secret",
                                        event.currentTarget.value,
                                      )
                                    }
                                  />
                                </Group>
                                <Group grow>
                                  <TextInput
                                    size="xs"
                                    placeholder="Authorization URL"
                                    value={acc.oauth_auth_url}
                                    onChange={(event) =>
                                      updateAccount(
                                        index,
                                        "oauth_auth_url",
                                        event.currentTarget.value,
                                      )
                                    }
                                  />
                                  <TextInput
                                    size="xs"
                                    placeholder="Token URL"
                                    value={acc.oauth_token_url}
                                    onChange={(event) =>
                                      updateAccount(
                                        index,
                                        "oauth_token_url",
                                        event.currentTarget.value,
                                      )
                                    }
                                  />
                                </Group>
                                <Group justify="space-between" wrap="nowrap">
                                  <TextInput
                                    size="xs"
                                    placeholder="Scopes (ex.: read write files.metadata.read)"
                                    value={acc.oauth_scopes}
                                    onChange={(event) =>
                                      updateAccount(
                                        index,
                                        "oauth_scopes",
                                        event.currentTarget.value,
                                      )
                                    }
                                    style={{ flex: 1 }}
                                  />
                                  <Button
                                    size="xs"
                                    variant="light"
                                    leftSection={<KeyRound size={13} />}
                                    loading={
                                      oauthBusyKey ===
                                      `${editingId || "new"}:${index}`
                                    }
                                    onClick={safe(() =>
                                      handleOAuthStart(editingId, acc, index),
                                    )}
                                  >
                                    {acc.oauth_connected
                                      ? "Reconectar OAuth"
                                      : "Conectar via OAuth"}
                                  </Button>
                                </Group>
                              </Stack>
                            )}
                          </Stack>
                        </Paper>
                      ))}
                    </Stack>
                  )}
                </Stack>
              </Collapse>
            </Stack>
          </Paper>

          <Group justify="flex-end" mt="xs">
            <Button
              variant="subtle"
              color="gray"
              onClick={() => setEditorOpen(false)}
            >
              Cancelar
            </Button>
            <Button onClick={safe(handleSave)} loading={saving}>
              Salvar
            </Button>
          </Group>
        </Stack>
      </Modal>

      {/* Modal Visualizar Ferramentas e Detalhes */}
      <Modal
        opened={!!inspectServer}
        onClose={() => setInspectServer(null)}
        size="lg"
        radius="md"
        title={
          <Group gap="xs">
            <Wrench size={18} />
            <Text fw={700}>
              {inspectServer ? `Ferramentas · ${inspectServer.name}` : "MCP"}
            </Text>
          </Group>
        }
      >
        {inspectServer && (
          <Stack gap="md">
            <Paper p="sm" radius="md" withBorder>
              <Group justify="space-between" wrap="wrap">
                <Stack gap={4}>
                  <Group gap="xs">
                    <Badge variant="light" color="blue">
                      {inspectServer.transport === "http"
                        ? "HTTP com streaming"
                        : "STDIO"}
                    </Badge>
                    <Badge variant="light" color="teal">
                      {
                        (
                          MCP_ACCOUNT_MODES.find(
                            (m) => m.value === inspectServer.account_mode,
                          ) || MCP_ACCOUNT_MODES[2]
                        ).label
                      }
                    </Badge>
                    {inspectServer.account_mode === "alternating" && (
                      <Badge variant="outline">
                        Contexto: {inspectServer.active_context}
                      </Badge>
                    )}
                  </Group>
                  <Text size="xs" c="dimmed">
                    {inspectServer.transport === "http"
                      ? inspectServer.url
                      : [inspectServer.command, ...(inspectServer.args || [])]
                          .filter(Boolean)
                          .join(" ")}
                  </Text>
                </Stack>
                <Button
                  size="xs"
                  variant="light"
                  leftSection={<RefreshCw size={14} />}
                  onClick={safe(handleReinspect)}
                  loading={inspectLoading}
                >
                  Re-inspecionar servidor
                </Button>
              </Group>
            </Paper>

            {inspectServer.accounts.length > 0 && (
              <Paper p="sm" radius="md" withBorder>
                <Text size="sm" fw={600} mb="xs">
                  Contas configuradas ({inspectServer.accounts.length})
                </Text>
                <Stack gap={6}>
                  {inspectServer.accounts.map((acc) => (
                    <Group
                      key={acc.id}
                      justify="space-between"
                      align="center"
                      wrap="wrap"
                    >
                      <Group gap="xs">
                        <ShieldCheck size={14} />
                        <Text size="sm" fw={500}>
                          {acc.name}
                        </Text>
                        <Badge size="xs" variant="light">
                          {acc.context}
                        </Badge>
                        <Badge size="xs" variant="outline" color="gray">
                          {acc.auth_type}
                        </Badge>
                      </Group>
                      <Group gap="xs">
                        <Text size="xs" c="dimmed">
                          Uso: {acc.usage_count || 0} req
                        </Text>
                        {acc.auth_type === "oauth" && (
                          <Button
                            size="compact-xs"
                            variant="subtle"
                            leftSection={<ExternalLink size={12} />}
                            onClick={safe(() =>
                              handleOAuthStart(inspectServer.id, acc, acc.id),
                            )}
                          >
                            OAuth
                          </Button>
                        )}
                      </Group>
                    </Group>
                  ))}
                </Stack>
              </Paper>
            )}

            <Stack gap="xs">
              <Group justify="space-between">
                <Text size="sm" fw={600}>
                  Ferramentas expostas ({inspectTools.length})
                </Text>
                {inspectLoading && (
                  <Text size="xs" c="dimmed">
                    Inspecionando…
                  </Text>
                )}
              </Group>

              {inspectTools.length === 0 && !inspectLoading ? (
                <Alert color="gray" variant="light">
                  Nenhuma ferramenta listada ainda. Clique em{" "}
                  <strong>Re-inspecionar servidor</strong> para consultar{" "}
                  <Code>tools/list</Code> no servidor MCP.
                </Alert>
              ) : (
                inspectTools.map((tool) => (
                  <Paper
                    key={tool.name}
                    p="sm"
                    radius="sm"
                    withBorder
                    className="mcp-tool-card"
                  >
                    <Group justify="space-between" align="center" mb={4}>
                      <Code fw={600}>{tool.name}</Code>
                    </Group>
                    <Text size="xs" c="dimmed" mb={tool.inputSchema ? 6 : 0}>
                      {tool.description}
                    </Text>
                    {tool.inputSchema && (
                      <Code block className="mcp-tool-schema">
                        {JSON.stringify(tool.inputSchema, null, 2)}
                      </Code>
                    )}
                  </Paper>
                ))
              )}
            </Stack>
          </Stack>
        )}
      </Modal>
    </div>
  );
}
