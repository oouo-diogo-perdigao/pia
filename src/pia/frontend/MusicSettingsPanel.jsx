import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Badge,
  Button,
  Group,
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
  Pencil,
  RefreshCw,
  Trash2,
  Unlink,
} from "lucide-react";
import { api, appApi, safe, watchJob } from "./api";
import {
  MUSIC_PROVIDER_LABELS,
  buildMusicSelectPayload,
  findSunoProvider,
  musicDraftSnapshot,
  runWithMusicProvidersUpdate,
  selectionToMusicDraft,
  shouldWarnSunoOpensInLocal,
} from "./music-helpers";
import {
  PIA_SERVER_SETTINGS_ROUTE,
  SUNO_CONNECT_ANOTHER_LABEL,
  SUNO_CONNECT_LABEL,
  SUNO_LEGACY_QUESTION,
  SUNO_TEXT_SERVER_DOWN,
  SUNO_TEXT_UNPAIRED,
  SUNO_WAITING_TEXT,
  buildConnectPayload,
  buildSunoRenameRequest,
  connectResultMessage,
  describeSunoError,
  disconnectConfirmText,
  legacyCredentialsState,
  pollSunoConnect,
  safeAuthUrl,
  sunoAccountStateLabel,
  sunoAccounts,
} from "./music-suno-helpers";
import { usePia } from "./shared";
import { notify } from "./toasts";

export default function MusicSettingsPanel() {
  const { navigate } = usePia();
  const [catalog, setCatalog] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [installProgress, setInstallProgress] = useState(null);
  const [savedSnapshot, setSavedSnapshot] = useState("");
  const [draft, setDraft] = useState(() => selectionToMusicDraft());
  // Connect assíncrono (RN06): {attemptId, authUrl, replaceId} enquanto
  // espera a autorização no navegador.
  const [connecting, setConnecting] = useState(null);
  const [connectNotice, setConnectNotice] = useState(null);
  const [accountBusy, setAccountBusy] = useState("");
  const [renaming, setRenaming] = useState(null);
  const [legacyBusy, setLegacyBusy] = useState(false);
  const jobSourceRef = useRef(null);
  const connectToken = useRef(0);
  const alive = useRef(true);

  const loadCatalog = useCallback(async () => {
    const data = await api("/music/providers");
    if (!alive.current) return data;
    const nextDraft = selectionToMusicDraft(data?.selection || {});
    setCatalog(data);
    setDraft(nextDraft);
    setSavedSnapshot(musicDraftSnapshot(nextDraft));
    setLoading(false);
    return data;
  }, []);

  useEffect(() => {
    alive.current = true;
    loadCatalog().catch(() => alive.current && setLoading(false));
    // RN05: status ao voltar o foco.
    let timer;
    const schedule = () => {
      clearTimeout(timer);
      timer = setTimeout(() => loadCatalog().catch(() => {}), 500);
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") schedule();
    };
    window.addEventListener("focus", schedule);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      alive.current = false;
      connectToken.current += 1;
      clearTimeout(timer);
      window.removeEventListener("focus", schedule);
      document.removeEventListener("visibilitychange", onVisibility);
      jobSourceRef.current?.close();
    };
  }, [loadCatalog]);

  const providers = Array.isArray(catalog?.providers) ? catalog.providers : [];
  const activeProvider =
    providers.find((item) => item?.id === draft.provider) || providers[0] || {};
  const sunoProvider = findSunoProvider(catalog) || {};
  const accounts = sunoAccounts(sunoProvider);
  const sunoReason = sunoProvider.reason || null;
  const serverBlocked =
    sunoReason === "pia_server_unpaired" ||
    sunoReason === "pia_server_unreachable" ||
    sunoReason === "pia_server_unsupported";
  const legacy = legacyCredentialsState(catalog);
  const dirty = !loading && musicDraftSnapshot(draft) !== savedSnapshot;
  const warnOpensInLocal = shouldWarnSunoOpensInLocal(
    catalog?.selection,
    sunoProvider,
    draft.provider,
  );

  function showSunoError(error, accountName = "") {
    const info = describeSunoError(error, { accountName });
    notify(info.text, "error");
    return info;
  }

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

  async function save() {
    setSaving(true);
    try {
      return await runWithMusicProvidersUpdate(async (markMutated) => {
        const updated = await api(
          "/music/select",
          buildMusicSelectPayload(draft),
        );
        markMutated();
        const nextDraft = selectionToMusicDraft(updated?.selection || {});
        if (Array.isArray(updated?.providers)) setCatalog(updated);
        setDraft(nextDraft);
        setSavedSnapshot(musicDraftSnapshot(nextDraft));
        notify("Configurações de música salvas.");
        return updated;
      });
    } finally {
      setSaving(false);
    }
  }

  // RN06/CA04/CA07: POST /music/suno/connect abre a URL de autorização do
  // servidor e faz polling em /music/suno/connect/<attempt_id> a cada 3 s.
  async function connectSuno(replaceAccount = null) {
    const token = ++connectToken.current;
    setConnectNotice(null);
    let response;
    try {
      response = await api(
        "/music/suno/connect",
        buildConnectPayload(replaceAccount?.id),
      );
    } catch (error) {
      showSunoError(error, replaceAccount?.name);
      return;
    }
    const authUrl = safeAuthUrl(response?.auth_url);
    if (authUrl) window.open(authUrl, "_blank", "noopener,noreferrer");
    if (!response?.attempt_id) {
      setConnectNotice({
        text: connectResultMessage({ state: "failed" }).text,
        color: "red",
      });
      return;
    }
    setConnecting({
      attemptId: response.attempt_id,
      authUrl,
      replaceId: replaceAccount?.id || null,
    });
    const result = await pollSunoConnect({
      attemptId: response.attempt_id,
      expiresIn: response.expires_in,
      fetchState: (attemptId) =>
        api("/music/suno/connect/" + encodeURIComponent(attemptId)),
      isCancelled: () => !alive.current || token !== connectToken.current,
    });
    if (!alive.current || token !== connectToken.current) return;
    setConnecting(null);
    const message = connectResultMessage(result);
    setConnectNotice(
      message.text ? { text: message.text, color: message.color } : null,
    );
    if (message.ok) {
      notify(message.text);
      await runWithMusicProvidersUpdate(async (markMutated) => {
        markMutated();
        await loadCatalog();
      });
    }
  }

  function cancelConnect() {
    connectToken.current += 1;
    setConnecting(null);
  }

  // RN06/CA04: desconectar só a conta escolhida, com confirmação.
  async function disconnectAccount(account) {
    if (!window.confirm(disconnectConfirmText(account))) return;
    setAccountBusy(account.id);
    try {
      await runWithMusicProvidersUpdate(async (markMutated) => {
        let updated;
        try {
          updated = await api("/music/suno/disconnect", {
            account_id: account.id,
          });
        } catch (error) {
          showSunoError(error, account.name);
          return;
        }
        markMutated();
        if (Array.isArray(updated?.provider?.accounts)) {
          setCatalog((old) =>
            old && Array.isArray(old.providers)
              ? {
                  ...old,
                  providers: old.providers.map((item) =>
                    item?.id === "suno_mcp" ? updated.provider : item,
                  ),
                }
              : old,
          );
        }
        notify(`Conta Suno ${account.name} desconectada.`);
        await loadCatalog().catch(() => {});
      });
    } finally {
      setAccountBusy("");
    }
  }

  // RN07: apelido da conta (rota única em buildSunoRenameRequest).
  async function renameAccount(account, label) {
    const request = buildSunoRenameRequest(account, label);
    setRenaming(null);
    if (!request) return;
    setAccountBusy(account.id);
    try {
      await runWithMusicProvidersUpdate(async (markMutated) => {
        try {
          await api(request.path, request.data, { method: request.method });
        } catch (error) {
          showSunoError(error, account.name);
          return;
        }
        markMutated();
        await loadCatalog().catch(() => {});
      });
    } finally {
      setAccountBusy("");
    }
  }

  // RN21/CA20: botão em Configurações → Música, com confirmação.
  async function removeLegacyCredentials() {
    if (!window.confirm(SUNO_LEGACY_QUESTION)) return;
    setLegacyBusy(true);
    try {
      const result = await api("/music/suno/legacy-credentials/remove", {
        confirm: true,
      });
      const removed = Array.isArray(result?.removed) ? result.removed : [];
      notify(
        removed.length
          ? "Credenciais antigas do Suno removidas: " + removed.join(", ") + "."
          : "Credenciais antigas do Suno removidas.",
      );
      await loadCatalog().catch(() => {});
    } catch (error) {
      showSunoError(error);
    } finally {
      setLegacyBusy(false);
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
                  Local até haver uma conta Suno conectada e válida.
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
        </div>
      </div>

      <div>
        <div className="settings-section-title">Contas Suno</div>
        <div className="settings-card">
          <div className="settings-row">
            <div className="settings-row-info">
              <Text size="sm" fw={600}>
                Suno pela PIA Server
              </Text>
              <Text size="xs" c="dimmed">
                A conexão com o Suno fica na PIA Server; nenhum token do Suno é
                guardado neste computador. Todos os computadores da sua conta
                PIA veem as mesmas contas Suno.
              </Text>
              {sunoReason === "pia_server_unpaired" && (
                <Text size="xs" c="yellow" mt={4}>
                  {SUNO_TEXT_UNPAIRED}
                </Text>
              )}
              {(sunoReason === "pia_server_unreachable" ||
                sunoReason === "pia_server_unsupported") && (
                <Text size="xs" c="yellow" mt={4}>
                  {SUNO_TEXT_SERVER_DOWN}
                </Text>
              )}
            </div>
            <div className="settings-row-control">
              {sunoReason === "pia_server_unpaired" ? (
                <Button
                  size="xs"
                  variant="light"
                  rightSection={<ExternalLink size={14} />}
                  onClick={() => navigate({ ...PIA_SERVER_SETTINGS_ROUTE })}
                >
                  Abrir Configurações → PIA Server
                </Button>
              ) : (
                <Button
                  size="xs"
                  leftSection={<Link2 size={14} />}
                  disabled={serverBlocked || Boolean(connecting)}
                  onClick={safe(() => connectSuno())}
                >
                  {accounts.length
                    ? SUNO_CONNECT_ANOTHER_LABEL
                    : SUNO_CONNECT_LABEL}
                </Button>
              )}
            </div>
          </div>

          {connecting && (
            <div className="settings-row">
              <Group justify="space-between" style={{ width: "100%" }}>
                <Text size="xs">{SUNO_WAITING_TEXT}</Text>
                <Group gap="xs">
                  {connecting.authUrl && (
                    <Button
                      size="xs"
                      variant="subtle"
                      rightSection={<ExternalLink size={12} />}
                      onClick={() =>
                        window.open(
                          connecting.authUrl,
                          "_blank",
                          "noopener,noreferrer",
                        )
                      }
                    >
                      Reabrir janela de autorização
                    </Button>
                  )}
                  <Button size="xs" variant="subtle" onClick={cancelConnect}>
                    Cancelar
                  </Button>
                </Group>
              </Group>
            </div>
          )}

          {connectNotice?.text && (
            <div className="settings-row">
              <Text size="xs" c={connectNotice.color}>
                {connectNotice.text}
              </Text>
            </div>
          )}

          {accounts.map((account) => {
            const state = sunoAccountStateLabel(account);
            const busy = accountBusy === account.id;
            return (
              <div className="settings-row" key={account.id}>
                <div className="settings-row-info">
                  {renaming?.id === account.id ? (
                    <Group gap="xs">
                      <TextInput
                        size="xs"
                        aria-label="Apelido da conta Suno"
                        value={renaming.label}
                        maxLength={80}
                        autoFocus
                        onChange={(event) => {
                          const label = event.currentTarget.value;
                          setRenaming((old) => ({ ...old, label }));
                        }}
                        onKeyDown={(event) => {
                          if (event.key === "Enter")
                            safe(() =>
                              renameAccount(account, renaming.label),
                            )();
                          if (event.key === "Escape") setRenaming(null);
                        }}
                      />
                      <Button
                        size="xs"
                        onClick={safe(() =>
                          renameAccount(account, renaming.label),
                        )}
                      >
                        Salvar
                      </Button>
                      <Button
                        size="xs"
                        variant="subtle"
                        onClick={() => setRenaming(null)}
                      >
                        Cancelar
                      </Button>
                    </Group>
                  ) : (
                    <Group gap="xs">
                      <Text size="sm" fw={600}>
                        {account.name}
                      </Text>
                      <Badge size="xs" variant="light" color={state.color}>
                        {state.label}
                      </Badge>
                    </Group>
                  )}
                  {renaming?.id !== account.id &&
                    !account.usable &&
                    !account.expired &&
                    account.hintText && (
                      <Text size="xs" c="dimmed">
                        {account.hintText}
                      </Text>
                    )}
                </div>
                <div className="settings-row-control">
                  <Group gap="xs" wrap="wrap">
                    {account.expired && (
                      <Button
                        size="xs"
                        variant="light"
                        leftSection={<RefreshCw size={14} />}
                        disabled={serverBlocked || Boolean(connecting) || busy}
                        onClick={safe(() => connectSuno(account))}
                      >
                        Reconectar
                      </Button>
                    )}
                    <Button
                      size="xs"
                      variant="subtle"
                      leftSection={<Pencil size={13} />}
                      disabled={serverBlocked || busy}
                      onClick={() =>
                        setRenaming({ id: account.id, label: account.name })
                      }
                    >
                      Apelido
                    </Button>
                    <Button
                      size="xs"
                      variant="light"
                      color="red"
                      loading={busy}
                      leftSection={<Unlink size={14} />}
                      disabled={serverBlocked}
                      onClick={safe(() => disconnectAccount(account))}
                    >
                      Desconectar
                    </Button>
                  </Group>
                </div>
              </div>
            );
          })}

          {legacy.present && (
            <div className="settings-row">
              <div className="settings-row-info">
                <Text size="sm" fw={600}>
                  Credenciais antigas do Suno
                </Text>
                <Text size="xs" c="dimmed">
                  Este computador ainda guarda credenciais do Suno da versão
                  anterior. A PIA não as usa mais.
                </Text>
              </div>
              <div className="settings-row-control">
                <Button
                  size="xs"
                  variant="light"
                  color="red"
                  loading={legacyBusy}
                  leftSection={<Trash2 size={14} />}
                  onClick={safe(removeLegacyCredentials)}
                >
                  Remover credenciais antigas
                </Button>
              </div>
            </div>
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
