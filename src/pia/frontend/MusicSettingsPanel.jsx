import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Badge,
  Button,
  Group,
  PasswordInput,
  Progress,
  Select,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { Check, Download, ExternalLink, KeyRound, Plug } from "lucide-react";
import { api, appApi, safe, watchJob } from "./api";
import { usePia } from "./shared";
import { notify } from "./toasts";

const MUSIC_PROVIDER_LABELS = {
  local: "Criador de músicas local (ACE-Step)",
  gemini: "Gemini (Lyria)",
  suno_mcp: "Suno (MCP)",
};

function draftSnapshot(draft) {
  return JSON.stringify({
    provider: draft.provider || "local",
    suno_mcp_url: (draft.suno_mcp_url || "").trim(),
    suno_mcp_command: (draft.suno_mcp_command || "").trim(),
    suno_mcp_token: draft.suno_mcp_token || "",
  });
}

export default function MusicSettingsPanel() {
  const { navigate } = usePia();
  const [catalog, setCatalog] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [installProgress, setInstallProgress] = useState(null);
  const [savedSnapshot, setSavedSnapshot] = useState("");
  const [draft, setDraft] = useState({
    provider: "local",
    suno_mcp_url: "",
    suno_mcp_command: "",
    suno_mcp_token: "",
  });
  const jobSourceRef = useRef(null);

  const loadCatalog = useCallback(async () => {
    const data = await api("/music/providers");
    const sel = data?.selection || {};
    const nextDraft = {
      provider: sel.provider || "local",
      suno_mcp_url: sel.suno_mcp_url || "",
      suno_mcp_command: sel.suno_mcp_command || "",
      suno_mcp_token: "",
    };
    setCatalog(data);
    setDraft(nextDraft);
    setSavedSnapshot(draftSnapshot(nextDraft));
    setLoading(false);
    return data;
  }, []);

  useEffect(() => {
    loadCatalog().catch(() => setLoading(false));
    return () => jobSourceRef.current?.close();
  }, [loadCatalog]);

  const providers = catalog?.providers || [];
  const activeProvider =
    providers.find((item) => item.id === draft.provider) || providers[0] || {};
  const dirty = !loading && draftSnapshot(draft) !== savedSnapshot;
  const sunoConfigured = Boolean(
    draft.suno_mcp_url.trim() || draft.suno_mcp_command.trim(),
  );

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
      const payload = { provider: draft.provider };
      if (draft.provider === "suno_mcp") {
        payload.suno_mcp_url = draft.suno_mcp_url.trim();
        payload.suno_mcp_command = draft.suno_mcp_command.trim();
        if (draft.suno_mcp_token.trim()) {
          payload.suno_mcp_token = draft.suno_mcp_token.trim();
        }
      }
      const updated = await api("/music/select", payload);
      const sel = updated?.selection || {};
      const nextDraft = {
        provider: sel.provider || draft.provider,
        suno_mcp_url: sel.suno_mcp_url || "",
        suno_mcp_command: sel.suno_mcp_command || "",
        suno_mcp_token: "",
      };
      setCatalog(updated);
      setDraft(nextDraft);
      setSavedSnapshot(draftSnapshot(nextDraft));
      notify("Configurações de música salvas.");
    } finally {
      setSaving(false);
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
                      Conectar servidor MCP do Suno
                    </Text>
                    <Badge
                      size="xs"
                      variant="light"
                      color={sunoConfigured ? "teal" : "gray"}
                      leftSection={<Plug size={11} />}
                    >
                      {sunoConfigured ? "Configurado" : "Não conectado"}
                    </Badge>
                  </Group>
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
                    onChange={(e) => {
                      const next = e.currentTarget.value;
                      setDraft((old) => ({ ...old, suno_mcp_url: next }));
                    }}
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
                    onChange={(e) => {
                      const next = e.currentTarget.value;
                      setDraft((old) => ({ ...old, suno_mcp_command: next }));
                    }}
                  />
                </div>
              </div>

              <div className="settings-row">
                <div className="settings-row-info">
                  <Text size="sm" fw={600}>
                    Token do Suno MCP (opcional)
                  </Text>
                  <Text size="xs" c="dimmed">
                    {catalog?.selection?.suno_mcp_token_configured
                      ? "Token já salvo. Preencha apenas para substituir."
                      : "Chave de autenticação, se exigida pelo servidor MCP."}
                  </Text>
                </div>
                <div className="settings-row-control">
                  <PasswordInput
                    w={280}
                    aria-label="Token do servidor MCP do Suno"
                    placeholder={
                      catalog?.selection?.suno_mcp_token_configured
                        ? "Já configurado"
                        : "Cole o token (opcional)"
                    }
                    value={draft.suno_mcp_token}
                    onChange={(e) => {
                      const next = e.currentTarget.value;
                      setDraft((old) => ({ ...old, suno_mcp_token: next }));
                    }}
                  />
                </div>
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
          onClick={safe(save)}
        >
          Salvar configurações
        </Button>
      </Group>
    </Stack>
  );
}
