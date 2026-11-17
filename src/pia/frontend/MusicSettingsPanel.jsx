import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Badge,
  Button,
  Collapse,
  Group,
  PasswordInput,
  Progress,
  Select,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import {
  Check,
  Download,
  ExternalLink,
  KeyRound,
  Link2,
  Plug,
  Settings2,
  Unlink,
} from "lucide-react";
import { api, appApi, safe, watchJob } from "./api";
import {
  MUSIC_PROVIDER_LABELS,
  buildMusicSelectPayload,
  buildSunoOAuthStartPayload,
  findSunoProvider,
  maskedEditedFieldError,
  musicDraftSnapshot,
  resolveSunoConnectionStatus,
  runWithMusicProvidersUpdate,
  selectionToMusicDraft,
  shouldWarnSunoOpensInLocal,
} from "./music-helpers";
import { usePia } from "./shared";
import { notify } from "./toasts";

export default function MusicSettingsPanel() {
  const { navigate } = usePia();
  const [catalog, setCatalog] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [oauthBusy, setOauthBusy] = useState(false);
  const [oauthAdvancedOpen, setOauthAdvancedOpen] = useState(false);
  const [pendingOAuth, setPendingOAuth] = useState(null);
  const [oauthCallbackInput, setOauthCallbackInput] = useState({
    code: "",
    access_token: "",
  });
  const [installing, setInstalling] = useState(false);
  const [installProgress, setInstallProgress] = useState(null);
  const [savedSnapshot, setSavedSnapshot] = useState("");
  const [draft, setDraft] = useState(() => selectionToMusicDraft());
  const [editedFields, setEditedFields] = useState({});
  const jobSourceRef = useRef(null);

  function markEdited(key) {
    setEditedFields((old) => ({ ...old, [key]: true }));
  }

  function patchDraft(key, value) {
    markEdited(key);
    setDraft((old) => ({ ...old, [key]: value }));
  }

  const loadCatalog = useCallback(async () => {
    const data = await api("/music/providers");
    const nextDraft = selectionToMusicDraft(data?.selection || {});
    setCatalog(data);
    setDraft(nextDraft);
    setSavedSnapshot(musicDraftSnapshot(nextDraft));
    setEditedFields({});
    setLoading(false);
    return data;
  }, []);

  useEffect(() => {
    loadCatalog().catch(() => setLoading(false));
    return () => jobSourceRef.current?.close();
  }, [loadCatalog]);

  const providers = Array.isArray(catalog?.providers) ? catalog.providers : [];
  const activeProvider =
    providers.find((item) => item?.id === draft.provider) || providers[0] || {};
  const sunoProvider = findSunoProvider(catalog) || {};
  const dirty = !loading && musicDraftSnapshot(draft) !== savedSnapshot;
  const sunoStatus = resolveSunoConnectionStatus(
    catalog?.selection,
    sunoProvider,
    pendingOAuth,
  );
  const warnOpensInLocal = shouldWarnSunoOpensInLocal(
    catalog?.selection,
    sunoProvider,
    draft.provider,
  );
  const sunoOauthConnected =
    catalog?.selection?.suno_mcp_oauth_connected === true ||
    sunoProvider.oauth_connected === true;

  async function installLocalEngine() {
    setInstalling(true);
    setInstallProgress({
      value: 0,
      label: "Preparando motor local de música…",
    });
    try {
      const response = await appApi("music", "prepare-local", {});
      jobSourceRef.current?.close();
      jobSourceRef.current = watchJob(response.job, (event) => {
        if (event.type === "progress") {
          setInstallProgress(event.value || null);
        }
        if (event.type === "error") {
          setInstalling(false);
          notify(
            event.error?.message ||
              String(event.error || "Falha ao instalar motor local."),
            "error",
          );
        }
        if (event.type === "done") {
          setInstalling(false);
          setInstallProgress(null);
          notify("Motor local de música pronto.");
          loadCatalog().catch(() => {});
        }
      });
    } catch (error) {
      setInstalling(false);
      setInstallProgress(null);
      throw error;
    }
  }

  async function save(overrideDraft = null) {
    setSaving(true);
    try {
      const sourceDraft = overrideDraft || draft;
      const maskedError = maskedEditedFieldError(sourceDraft, editedFields);
      if (maskedError) {
        notify(maskedError, "error");
        return;
      }
      return await runWithMusicProvidersUpdate(async (markMutated) => {
        const payload = buildMusicSelectPayload(sourceDraft, {
          edited: editedFields,
        });
        const updated = await api("/music/select", payload);
        markMutated();
        const nextDraft = selectionToMusicDraft(updated?.selection || {});
        setCatalog(updated);
        setDraft(nextDraft);
        setSavedSnapshot(musicDraftSnapshot(nextDraft));
        setEditedFields({});
        notify("Configurações de música salvas.");
        return updated;
      });
    } finally {
      setSaving(false);
    }
  }

  async function startSunoOAuth() {
    setOauthBusy(true);
    try {
      const nextDraft = {
        ...draft,
        provider: "suno_mcp",
        suno_mcp_auth_type: "oauth",
      };
      const maskedError = maskedEditedFieldError(nextDraft, editedFields);
      if (maskedError) {
        notify(maskedError, "error");
        return;
      }
      setDraft(nextDraft);
      await runWithMusicProvidersUpdate(async (markMutated) => {
        if (musicDraftSnapshot(nextDraft) !== savedSnapshot) {
          await api(
            "/music/select",
            buildMusicSelectPayload(nextDraft, { edited: editedFields }),
          );
          markMutated();
        }
        const res = await api(
          "/music/suno/oauth/start",
          buildSunoOAuthStartPayload(nextDraft, { edited: editedFields }),
        );
        markMutated();
        if (res?.auth_url && /^https?:\/\//i.test(res.auth_url)) {
          window.open(res.auth_url, "_blank", "noopener,noreferrer");
        }
        if (res?.account?.oauth?.connected === true) {
          setPendingOAuth(null);
          notify("Conta Suno MCP conectada via OAuth.");
        } else {
          setPendingOAuth({
            state: res?.state || "",
            authUrl: res?.auth_url || "",
            accountId: res?.account?.id || "",
          });
          notify("Autorização OAuth do Suno MCP iniciada.");
        }
        await loadCatalog();
      });
    } finally {
      setOauthBusy(false);
    }
  }

  async function finishSunoOAuth() {
    if (!pendingOAuth) return;
    setOauthBusy(true);
    try {
      await runWithMusicProvidersUpdate(async (markMutated) => {
        await api("/music/suno/oauth/callback", {
          state: pendingOAuth.state,
          account_id: pendingOAuth.accountId || undefined,
          code: oauthCallbackInput.code.trim() || undefined,
          access_token: oauthCallbackInput.access_token.trim() || undefined,
        });
        markMutated();
        setPendingOAuth(null);
        setOauthCallbackInput({ code: "", access_token: "" });
        await loadCatalog();
        notify("Conta OAuth do Suno MCP conectada e salva no Cofre.");
      });
    } finally {
      setOauthBusy(false);
    }
  }

  async function disconnectSunoOAuth() {
    setOauthBusy(true);
    try {
      await runWithMusicProvidersUpdate(async (markMutated) => {
        const updated = await api("/music/suno/oauth/disconnect", {});
        markMutated();
        setPendingOAuth(null);
        if (updated?.selection) {
          const nextDraft = selectionToMusicDraft(updated.selection);
          setCatalog(updated);
          setDraft(nextDraft);
          setSavedSnapshot(musicDraftSnapshot(nextDraft));
          setEditedFields({});
        } else {
          await loadCatalog();
        }
        notify("Conexão OAuth do Suno MCP removida.");
      });
    } finally {
      setOauthBusy(false);
    }
  }

  if (loading && !catalog) {
    return (
      <Text size="sm" c="dimmed">
        Carregando configurações de música…
      </Text>
    );
  }

  return (
    <Stack gap="md">
      <div>
        <div className="settings-section-title">Geração de música</div>
        <div className="settings-card">
          <div className="settings-row">
            <div className="settings-row-info">
              <Text size="sm" fw={600}>
                Provedor de música
              </Text>
              <Text size="xs" c="dimmed">
                {activeProvider.description ||
                  "Escolha como a PIA cria músicas."}
              </Text>
            </div>
            <div className="settings-row-control">
              {draft.provider === "local" && !activeProvider.installed && (
                <Button
                  size="xs"
                  variant="subtle"
                  leftSection={<Download size={14} />}
                  loading={installing}
                  onClick={safe(installLocalEngine)}
                >
                  Instalar
                </Button>
              )}
              {draft.provider === "local" && activeProvider.installed && (
                <Badge variant="light" color="teal">
                  Instalado
                </Badge>
              )}
              <Select
                w={260}
                aria-label="Provedor de música"
                data={providers.map((item) => ({
                  value: item.id,
                  label: MUSIC_PROVIDER_LABELS[item.id] || item.name || item.id,
                }))}
                value={draft.provider}
                onChange={(val) =>
                  val && setDraft((old) => ({ ...old, provider: val }))
                }
              />
              {warnOpensInLocal && (
                <Text size="xs" c="dimmed" maw={260} ta="right">
                  O Suno pode ser salvo como padrão, mas o app de Música abre em
                  Local até a conta estar autorizada.
                </Text>
              )}
            </div>
          </div>

          {installing && installProgress && (
            <div className="settings-row">
              <Stack gap={6} style={{ width: "100%" }}>
                <Group justify="space-between">
                  <Text size="xs" c="dimmed">
                    {installProgress.label || "Instalando motor local…"}
                  </Text>
                  {typeof installProgress.value === "number" && (
                    <Text size="xs" c="dimmed">
                      {Math.round(installProgress.value)}%
                    </Text>
                  )}
                </Group>
                <Progress
                  size="sm"
                  color="violet"
                  value={
                    typeof installProgress.value === "number"
                      ? installProgress.value
                      : 30
                  }
                  animated
                />
              </Stack>
            </div>
          )}

          {draft.provider === "local" && (
            <div className="settings-row">
              <div className="settings-row-info">
                <Text size="sm" fw={600}>
                  Criador de músicas local
                </Text>
                <Text size="xs" c="dimmed">
                  {activeProvider.installed
                    ? "Motor ACE-Step instalado neste computador."
                    : "Roda offline neste computador após a instalação inicial."}
                </Text>
              </div>
              <div className="settings-row-control">
                <Button
                  size="xs"
                  variant="light"
                  rightSection={<ExternalLink size={14} />}
                  onClick={() => navigate({ view: "app", app: "music" })}
                >
                  Abrir app Música
                </Button>
              </div>
            </div>
          )}

          {draft.provider === "gemini" && (
            <div className="settings-row">
              <div className="settings-row-info">
                <Group gap="xs">
                  <Text size="sm" fw={600}>
                    Chave da API do Gemini
                  </Text>
                  <Badge
                    size="xs"
                    variant="light"
                    color={activeProvider.available ? "teal" : "yellow"}
                  >
                    {activeProvider.available ? "Configurada" : "Pendente"}
                  </Badge>
                </Group>
                <Text size="xs" c="dimmed">
                  Usa a credencial GEMINI_API_KEY gerenciada no Cofre.
                </Text>
              </div>
              <div className="settings-row-control">
                <Button
                  size="xs"
                  variant="light"
                  leftSection={<KeyRound size={14} />}
                  onClick={() =>
                    navigate({ view: "settings", section: "credentials" })
                  }
                >
                  Abrir Cofre
                </Button>
              </div>
            </div>
          )}

          {draft.provider === "suno_mcp" && (
            <>
              <div className="settings-row">
                <div className="settings-row-info">
                  <Group gap="xs">
                    <Text size="sm" fw={600}>
                      Conta OAuth · Suno MCP
                    </Text>
                    <Badge
                      size="xs"
                      variant="light"
                      color={sunoStatus.color}
                      leftSection={<Plug size={11} />}
                    >
                      {sunoStatus.label}
                    </Badge>
                  </Group>
                  <Text size="xs" c="dimmed">
                    {sunoStatus.connected
                      ? "Conta OAuth conectada e salva no Cofre Único."
                      : sunoStatus.mode === "expired"
                        ? "A autorização do Suno expirou. Reconecte para voltar a gerar."
                        : sunoStatus.mode === "needs_auth"
                          ? "A URL (ou o comando) está configurada, mas falta autorizar o Suno."
                          : sunoStatus.mode === "oauth_pending"
                            ? "Autorização OAuth pendente. Conclua no navegador e cole o código abaixo se necessário."
                            : sunoStatus.mode === "credential"
                              ? "Credencial configurada no Cofre Único (autenticação validada somente na chamada ao servidor)."
                              : "Conecte via OAuth (DCR automático + PKCE) ou informe um token manual no Cofre Único."}
                  </Text>
                </div>
                <div className="settings-row-control">
                  <Group gap="xs" wrap="wrap">
                    <Button
                      size="xs"
                      loading={oauthBusy}
                      leftSection={<Link2 size={14} />}
                      onClick={safe(startSunoOAuth)}
                    >
                      {sunoStatus.connected || sunoStatus.mode === "expired"
                        ? "Reconectar OAuth"
                        : "Conectar via OAuth"}
                    </Button>
                    {sunoOauthConnected && (
                      <Button
                        size="xs"
                        variant="light"
                        color="red"
                        loading={oauthBusy}
                        leftSection={<Unlink size={14} />}
                        onClick={safe(disconnectSunoOAuth)}
                      >
                        Desconectar
                      </Button>
                    )}
                    <Button
                      size="xs"
                      variant="light"
                      leftSection={<KeyRound size={14} />}
                      onClick={() =>
                        navigate({ view: "settings", section: "credentials" })
                      }
                    >
                      Abrir Cofre Único
                    </Button>
                    <Button
                      size="xs"
                      variant="subtle"
                      onClick={() =>
                        navigate({ view: "settings", section: "mcp" })
                      }
                    >
                      Contas MCP
                    </Button>
                  </Group>
                </div>
              </div>

              {pendingOAuth && (
                <div className="settings-row">
                  <Stack gap="xs" style={{ width: "100%" }}>
                    <Group justify="space-between" wrap="wrap" gap="xs">
                      <Text size="xs" fw={600}>
                        Concluir autorização OAuth do Suno MCP
                      </Text>
                      {pendingOAuth.authUrl && (
                        <Button
                          size="xs"
                          variant="subtle"
                          rightSection={<ExternalLink size={12} />}
                          onClick={() =>
                            window.open(
                              pendingOAuth.authUrl,
                              "_blank",
                              "noopener,noreferrer",
                            )
                          }
                        >
                          Reabrir janela de autorização
                        </Button>
                      )}
                    </Group>
                    <Group gap="xs" align="flex-end" wrap="wrap">
                      <TextInput
                        size="xs"
                        label="Código OAuth (opcional)"
                        placeholder="Cole o code retornado"
                        value={oauthCallbackInput.code}
                        onChange={(e) => {
                          const code = e.currentTarget.value;
                          setOauthCallbackInput((old) => ({ ...old, code }));
                        }}
                        style={{ flex: 1, minWidth: 180 }}
                      />
                      <PasswordInput
                        size="xs"
                        label="Access token direto (opcional)"
                        placeholder="Ou cole o access_token"
                        value={oauthCallbackInput.access_token}
                        onChange={(e) => {
                          const access_token = e.currentTarget.value;
                          setOauthCallbackInput((old) => ({
                            ...old,
                            access_token,
                          }));
                        }}
                        style={{ flex: 1, minWidth: 180 }}
                      />
                      <Button
                        size="xs"
                        loading={oauthBusy}
                        onClick={safe(finishSunoOAuth)}
                      >
                        Concluir OAuth
                      </Button>
                      <Button
                        size="xs"
                        variant="subtle"
                        onClick={() => setPendingOAuth(null)}
                      >
                        Cancelar
                      </Button>
                    </Group>
                  </Stack>
                </div>
              )}

              <div className="settings-row">
                <div className="settings-row-info">
                  <Text size="sm" fw={600}>
                    Endereço do servidor MCP do Suno
                  </Text>
                  <Text size="xs" c="dimmed">
                    Informe o endereço http(s) do servidor MCP do Suno.
                  </Text>
                </div>
                <div className="settings-row-control">
                  <TextInput
                    w={280}
                    aria-label="URL do servidor MCP do Suno"
                    placeholder="https://seu-servidor-mcp/suno"
                    value={draft.suno_mcp_url}
                    onChange={(e) =>
                      patchDraft("suno_mcp_url", e.currentTarget.value)
                    }
                  />
                </div>
              </div>

              <div className="settings-row">
                <div className="settings-row-info">
                  <Text size="sm" fw={600}>
                    Comando MCP (opcional)
                  </Text>
                  <Text size="xs" c="dimmed">
                    Preencha apenas se o servidor MCP iniciar por comando local.
                  </Text>
                </div>
                <div className="settings-row-control">
                  <TextInput
                    w={280}
                    aria-label="Comando do servidor MCP do Suno"
                    placeholder="npx suno-mcp-server"
                    value={draft.suno_mcp_command}
                    onChange={(e) =>
                      patchDraft("suno_mcp_command", e.currentTarget.value)
                    }
                  />
                </div>
              </div>

              <div className="settings-row">
                <div className="settings-row-info">
                  <Text size="sm" fw={600}>
                    Token do Suno MCP (opcional)
                  </Text>
                  <Text size="xs" c="dimmed">
                    {sunoStatus.connected
                      ? "Sessão OAuth ativa no Cofre. Preencha apenas se quiser definir um token manual."
                      : catalog?.selection?.suno_mcp_token_configured === true
                        ? "Token manual configurado no Cofre (presença não valida autenticação). Preencha apenas para substituir."
                        : "Chave Bearer manual caso não utilize OAuth."}
                  </Text>
                </div>
                <div className="settings-row-control">
                  <PasswordInput
                    w={280}
                    aria-label="Token do servidor MCP do Suno"
                    placeholder={
                      catalog?.selection?.suno_mcp_token_configured === true
                        ? "Token configurado"
                        : "Cole o token (opcional)"
                    }
                    value={draft.suno_mcp_token}
                    onChange={(e) =>
                      patchDraft("suno_mcp_token", e.currentTarget.value)
                    }
                  />
                </div>
              </div>

              <div className="settings-row">
                <Stack gap="xs" style={{ width: "100%" }}>
                  <Group justify="space-between">
                    <Text size="xs" c="dimmed">
                      Parâmetros avançados de OAuth (opcionais — usa DCR
                      automático + PKCE por padrão)
                    </Text>
                    <Button
                      size="xs"
                      variant="subtle"
                      leftSection={<Settings2 size={13} />}
                      onClick={() => setOauthAdvancedOpen((v) => !v)}
                    >
                      {oauthAdvancedOpen ? "Ocultar OAuth" : "Configurar OAuth"}
                    </Button>
                  </Group>
                  <Collapse in={oauthAdvancedOpen}>
                    <Stack gap="xs" pt="xs">
                      <Group grow align="flex-start">
                        <TextInput
                          size="xs"
                          label="Client ID (opcional)"
                          placeholder="Automático via DCR se vazio"
                          value={draft.suno_mcp_client_id}
                          onChange={(e) =>
                            patchDraft(
                              "suno_mcp_client_id",
                              e.currentTarget.value,
                            )
                          }
                        />
                        <PasswordInput
                          size="xs"
                          label="Client Secret (opcional)"
                          placeholder="Opcional"
                          value={draft.suno_mcp_client_secret}
                          onChange={(e) =>
                            patchDraft(
                              "suno_mcp_client_secret",
                              e.currentTarget.value,
                            )
                          }
                        />
                      </Group>
                      <Group grow align="flex-start">
                        <TextInput
                          size="xs"
                          label="Authorization URL (opcional)"
                          placeholder="Usa padrão Suno se vazio"
                          value={draft.suno_mcp_auth_url}
                          onChange={(e) =>
                            patchDraft(
                              "suno_mcp_auth_url",
                              e.currentTarget.value,
                            )
                          }
                        />
                        <TextInput
                          size="xs"
                          label="Token URL (opcional)"
                          placeholder="Usa padrão Suno se vazio"
                          value={draft.suno_mcp_token_url}
                          onChange={(e) =>
                            patchDraft(
                              "suno_mcp_token_url",
                              e.currentTarget.value,
                            )
                          }
                        />
                      </Group>
                      <TextInput
                        size="xs"
                        label="Escopos OAuth (opcional)"
                        placeholder="music.generate profile"
                        value={draft.suno_mcp_scopes}
                        onChange={(e) =>
                          patchDraft("suno_mcp_scopes", e.currentTarget.value)
                        }
                      />
                    </Stack>
                  </Collapse>
                </Stack>
              </div>
            </>
          )}
        </div>
      </div>

      <Group justify="flex-end">
        <Button
          disabled={!dirty || saving}
          loading={saving}
          leftSection={<Check size={16} />}
          onClick={safe(() => save())}
        >
          Salvar configurações
        </Button>
      </Group>
    </Stack>
  );
}
