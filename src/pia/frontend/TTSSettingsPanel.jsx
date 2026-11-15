import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Progress,
  Select,
  Slider,
  Stack,
  Switch,
  Text,
  TextInput,
} from "@mantine/core";
import {
  AlertTriangle,
  Check,
  Download,
  KeyRound,
  Play,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { api, safe } from "./api";
import { usePia } from "./shared";
import { notify } from "./toasts";
import {
  notifyTtsUpdated,
  useTtsCatalog,
  useTtsPreview,
} from "./VoiceSelector";
import {
  clampSpeed,
  decodeModelKey,
  encodeModelKey,
  formatBytes,
  formatReferenceLabel,
  mergeInstallJob,
  normalizeInstallJob,
  resolveDraftForModel,
  speedBounds,
} from "./tts-helpers";
import {
  DEFAULT_TTS_PREVIEW_TEXT,
  MAX_TTS_PREVIEW_CHARS,
  formatVoiceOptionLabel,
  normalizePreviewText,
} from "./settings-simplification";

function sameProfile(a, b) {
  if (!a || !b) return false;
  return (
    (a.provider || "") === (b.provider || "") &&
    (a.model || "") === (b.model || "") &&
    (a.voice || "") === (b.voice || "") &&
    Math.abs(Number(a.speed ?? 1) - Number(b.speed ?? 1)) < 0.001
  );
}

export default function TTSSettingsPanel() {
  const { navigate, refresh } = usePia();
  const { catalog, selection, revision, loading, error, reload } =
    useTtsCatalog();
  const { preview, previewing } = useTtsPreview();

  const [draft, setDraft] = useState({
    provider: "",
    model: "",
    voice: "",
    speed: 1.0,
  });
  const [previewText, setPreviewText] = useState(DEFAULT_TTS_PREVIEW_TEXT);
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [jobs, setJobs] = useState({});
  const [uninstallErrors, setUninstallErrors] = useState({});
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [refreshingVoices, setRefreshingVoices] = useState(false);
  const [notifSettings, setNotifSettings] = useState({
    read_aloud: false,
    muted: [],
  });
  const [notifLoaded, setNotifLoaded] = useState(false);
  const [savingReadAloud, setSavingReadAloud] = useState(false);
  const pollers = useRef({});

  useEffect(() => {
    api("/notifications/settings")
      .then((res) => {
        if (res && typeof res === "object") {
          setNotifSettings({
            read_aloud: Boolean(res.read_aloud),
            muted: Array.isArray(res.muted) ? res.muted : [],
          });
        }
        setNotifLoaded(true);
      })
      .catch(() => setNotifLoaded(true));
  }, []);

  useEffect(() => {
    if (selection) {
      setDraft({
        provider: selection.provider || "",
        model: selection.model || "",
        voice: selection.voice || "",
        speed: Number(selection.speed ?? 1.0),
      });
    }
  }, [selection]);

  useEffect(() => {
    setConfirmRemove(false);
  }, [draft.provider, draft.model]);

  const attachJob = useCallback(
    (providerId, modelId, jobId) => {
      if (!jobId) return;
      const key = encodeModelKey(providerId, modelId);
      if (pollers.current[key]) clearInterval(pollers.current[key]);
      const poll = async () => {
        try {
          const snap = await api(`/tts/jobs/${jobId}`);
          setJobs((old) => ({
            ...old,
            [key]: mergeInstallJob(old[key], snap),
          }));
          if (
            ["completed", "done", "failed", "error", "cancelled"].includes(
              snap.status,
            )
          ) {
            clearInterval(pollers.current[key]);
            delete pollers.current[key];
            await reload();
            notifyTtsUpdated();
            if (snap.status === "completed" || snap.status === "done") {
              notify(`Modelo ${modelId} instalado com sucesso.`);
            }
          }
        } catch {
          clearInterval(pollers.current[key]);
          delete pollers.current[key];
        }
      };
      pollers.current[key] = setInterval(poll, 1200);
      poll();
    },
    [reload],
  );

  useEffect(() => {
    for (const provider of catalog) {
      for (const model of provider.models || []) {
        if (
          model.installation?.state === "installing" &&
          model.installation?.job_id
        ) {
          attachJob(provider.id, model.id, model.installation.job_id);
        }
      }
    }
  }, [catalog, attachJob]);

  useEffect(() => {
    const active = pollers.current;
    return () => {
      Object.values(active).forEach(clearInterval);
    };
  }, []);

  if (loading && !catalog.length) {
    return (
      <Text size="sm" c="dimmed">
        Carregando vozes e modelos…
      </Text>
    );
  }
  if (error) {
    return (
      <Alert color="red" title="Erro ao carregar vozes">
        {String(error.message || error)}
      </Alert>
    );
  }

  const localProviders = catalog.filter((p) => p.kind !== "remote");
  const remoteProviders = catalog.filter((p) => p.kind === "remote");

  const modelGroups = [];
  if (localProviders.length) {
    modelGroups.push({
      group: "Modelos locais",
      items: localProviders.flatMap((p) =>
        (p.models || []).map((m) => ({
          value: encodeModelKey(p.id, m.id),
          label: m.name || `${p.name} · ${m.id}`,
        })),
      ),
    });
  }
  if (remoteProviders.length) {
    modelGroups.push({
      group: "Provedores na nuvem",
      items: remoteProviders.flatMap((p) =>
        (p.models || []).map((m) => ({
          value: encodeModelKey(p.id, m.id),
          label: `${p.name} · ${m.name || m.id}`,
        })),
      ),
    });
  }

  const activeProvider =
    catalog.find((p) => p.id === draft.provider) || catalog[0] || {};
  const activeModels = activeProvider.models || [];
  const activeModel =
    activeModels.find((m) => m.id === draft.model) || activeModels[0] || {};

  const currentModelKey =
    activeProvider.id && activeModel.id
      ? encodeModelKey(activeProvider.id, activeModel.id)
      : "";
  const activeJob =
    jobs[currentModelKey] ||
    (activeModel.installation?.state === "installing"
      ? normalizeInstallJob(activeModel.installation)
      : null);
  const isInstalling = ["pending", "running", "installing"].includes(
    activeJob?.status || "",
  );
  const isLocal = activeProvider.kind !== "remote";
  const isInstalled = Boolean(activeModel.installed || activeModel.available);
  const isRemovable = isLocal && isInstalled && activeModel.removable !== false;
  const remoteConfigured =
    activeProvider.kind !== "remote" ||
    Boolean(
      activeProvider.configured ??
      activeProvider.available ??
      activeProvider.credential_state === "configured",
    );

  const voices = activeModel.voices || [];
  const selectedVoice = voices.some((v) => v.id === draft.voice)
    ? draft.voice
    : voices[0]?.id || "";
  const bounds = speedBounds(activeModel, activeProvider);
  const speed = clampSpeed(draft.speed, bounds);
  const dirty = !sameProfile(
    {
      provider: activeProvider.id,
      model: activeModel.id,
      voice: selectedVoice,
      speed,
    },
    selection,
  );

  const uninstallError = uninstallErrors[currentModelKey];
  const pct = Number(activeJob?.progress ?? 0);
  const bytesText =
    activeJob?.total_bytes > 0
      ? `${formatBytes(activeJob.downloaded_bytes)} / ${formatBytes(activeJob.total_bytes)}`
      : "";

  async function toggleReadAloud(next) {
    setSavingReadAloud(true);
    try {
      const updated = { ...notifSettings, read_aloud: next };
      await api("/notifications/settings", updated);
      setNotifSettings(updated);
      await refresh().catch(() => {});
    } finally {
      setSavingReadAloud(false);
    }
  }

  async function installActiveModel() {
    if (!activeProvider.id || !activeModel.id) return;
    setUninstallErrors((old) => ({ ...old, [currentModelKey]: null }));
    const res = await api("/tts/install", {
      provider: activeProvider.id,
      model: activeModel.id,
    });
    setJobs((old) => ({
      ...old,
      [currentModelKey]: mergeInstallJob(old[currentModelKey], {
        ...res,
        job_id: res.job_id,
        status: res.status || "running",
      }),
    }));
    attachJob(activeProvider.id, activeModel.id, res.job_id);
  }

  async function cancelInstall() {
    const jobId = activeJob?.job_id || activeModel.installation?.job_id;
    if (!jobId) return;
    await api(`/tts/jobs/${jobId}/cancel`, {});
    await reload();
  }

  async function uninstallActiveModel() {
    if (!activeProvider.id || !activeModel.id) return;
    setUninstallErrors((old) => ({ ...old, [currentModelKey]: null }));
    try {
      await api("/tts/uninstall", {
        provider: activeProvider.id,
        model: activeModel.id,
      });
      setConfirmRemove(false);
      notify(`Modelo ${activeModel.name || activeModel.id} removido.`);
      await reload();
      notifyTtsUpdated();
    } catch (err) {
      if (err?.status === 409) {
        setConfirmRemove(false);
        setUninstallErrors((old) => ({
          ...old,
          [currentModelKey]: {
            message:
              err.message ||
              "Este modelo está em uso e não pode ser removido agora.",
            references: err.data?.references || [],
          },
        }));
        return;
      }
      throw err;
    }
  }

  async function refreshVoices() {
    if (!activeProvider.id) return;
    setRefreshingVoices(true);
    try {
      await api(
        `/tts/voices?provider=${encodeURIComponent(activeProvider.id)}&model=${encodeURIComponent(activeModel.id || "")}&refresh=true`,
      );
      await reload();
      notify("Lista de vozes atualizada.");
    } finally {
      setRefreshingVoices(false);
    }
  }

  async function save() {
    setSaving(true);
    setConflict(false);
    try {
      await api("/tts/select", {
        provider: activeProvider.id,
        model: activeModel.id,
        voice: selectedVoice,
        speed,
        revision,
      });
      await reload();
      notify("Voz Geral da PIA salva com sucesso.");
      notifyTtsUpdated();
    } catch (err) {
      if (err?.status === 409) {
        setConflict(true);
        return;
      }
      throw err;
    } finally {
      setSaving(false);
    }
  }

  return (
    <Stack gap="md">
      {conflict && (
        <Alert
          color="orange"
          icon={<AlertTriangle size={16} />}
          title="Alteração concorrente detectada"
        >
          <Group justify="space-between" align="center" wrap="wrap">
            <Text size="sm">
              Outra janela ou bot atualizou a voz da PIA. Recarregue antes de
              salvar.
            </Text>
            <Button
              size="xs"
              variant="light"
              onClick={safe(async () => {
                setConflict(false);
                await reload();
              })}
            >
              Recarregar agora
            </Button>
          </Group>
        </Alert>
      )}

      <div>
        <div className="settings-section-title">Respostas faladas</div>
        <div className="settings-card">
          <div className="settings-row">
            <div className="settings-row-info">
              <Text size="sm" fw={600}>
                Modelo
              </Text>
              <Text size="xs" c="dimmed">
                {activeModel.description ||
                  activeProvider.description ||
                  "Escolha o sintetizador de voz usado pela PIA."}
              </Text>
            </div>
            <div className="settings-row-control">
              {isLocal && !isInstalled && !isInstalling && (
                <Button
                  size="xs"
                  variant="subtle"
                  leftSection={<Download size={14} />}
                  onClick={safe(installActiveModel)}
                >
                  Instalar
                </Button>
              )}
              {isInstalling && (
                <Button
                  size="xs"
                  color="red"
                  variant="subtle"
                  onClick={safe(cancelInstall)}
                >
                  Cancelar
                </Button>
              )}
              {isRemovable &&
                !isInstalling &&
                (confirmRemove ? (
                  <Group gap={6}>
                    <Button
                      size="xs"
                      color="red"
                      variant="light"
                      onClick={safe(uninstallActiveModel)}
                    >
                      Confirmar remoção
                    </Button>
                    <Button
                      size="xs"
                      variant="subtle"
                      onClick={() => setConfirmRemove(false)}
                    >
                      Voltar
                    </Button>
                  </Group>
                ) : (
                  <Button
                    size="xs"
                    color="gray"
                    variant="subtle"
                    leftSection={<Trash2 size={14} />}
                    onClick={() => setConfirmRemove(true)}
                  >
                    Remover
                  </Button>
                ))}
              {!isLocal && !remoteConfigured && (
                <Button
                  size="xs"
                  color="yellow"
                  variant="light"
                  leftSection={<KeyRound size={14} />}
                  onClick={() =>
                    navigate({ view: "settings", section: "credentials" })
                  }
                >
                  Cofre
                </Button>
              )}
              <Select
                w={240}
                aria-label="Modelo de voz"
                data={modelGroups}
                value={currentModelKey}
                onChange={(val) => {
                  const decoded = decodeModelKey(val);
                  if (!decoded) return;
                  const p =
                    catalog.find((item) => item.id === decoded.provider) ||
                    activeProvider;
                  const m =
                    (p.models || []).find(
                      (item) => item.id === decoded.model,
                    ) || (p.models || [])[0];
                  setDraft((old) => resolveDraftForModel(p, m, old.speed));
                }}
              />
            </div>
          </div>

          {isInstalling && (
            <div className="settings-row">
              <Stack gap={6} style={{ width: "100%" }}>
                <Group justify="space-between">
                  <Text size="xs" c="dimmed" role="status" aria-live="polite">
                    {activeJob?.message ||
                      activeJob?.step ||
                      "Baixando arquivos do modelo…"}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {pct > 0 ? `${Math.round(pct)}%` : ""}
                    {bytesText ? ` · ${bytesText}` : ""}
                  </Text>
                </Group>
                <Progress
                  size="sm"
                  color="violet"
                  value={pct > 0 ? pct : 25}
                  animated
                />
              </Stack>
            </div>
          )}

          {uninstallError && (
            <div className="settings-row">
              <Alert
                color="orange"
                style={{ width: "100%" }}
                title="Não foi possível remover o modelo"
              >
                <Text size="xs">{uninstallError.message}</Text>
                {uninstallError.references?.length > 0 && (
                  <Text size="xs" mt={4} c="dimmed">
                    Em uso por:{" "}
                    {uninstallError.references
                      .map(formatReferenceLabel)
                      .join(", ")}
                  </Text>
                )}
              </Alert>
            </div>
          )}

          <div className="settings-row">
            <div className="settings-row-info">
              <Text size="sm" fw={600}>
                Ler respostas em voz alta
              </Text>
              <Text size="xs" c="dimmed">
                Quando você dita uma mensagem, a resposta é lida em voz alta.
                Dite de novo para parar.
              </Text>
            </div>
            <div className="settings-row-control">
              <Switch
                aria-label="Ler respostas em voz alta"
                checked={Boolean(notifSettings.read_aloud)}
                disabled={!notifLoaded || savingReadAloud}
                onChange={(e) => toggleReadAloud(e.currentTarget.checked)}
              />
            </div>
          </div>

          <div className="settings-row">
            <div className="settings-row-info">
              <Text size="sm" fw={600} mb={6}>
                Voz
              </Text>
              <TextInput
                size="xs"
                aria-label="Texto de teste da voz"
                placeholder={DEFAULT_TTS_PREVIEW_TEXT}
                maxLength={MAX_TTS_PREVIEW_CHARS}
                value={previewText}
                onChange={(e) =>
                  setPreviewText(normalizePreviewText(e.currentTarget.value))
                }
                rightSectionWidth={52}
                rightSection={
                  <Text size="xs" c="dimmed">
                    {previewText.length}/{MAX_TTS_PREVIEW_CHARS}
                  </Text>
                }
              />
            </div>
            <div className="settings-row-control">
              <Button
                size="xs"
                variant="subtle"
                leftSection={
                  previewing ? <Loader size={14} /> : <Play size={14} />
                }
                disabled={
                  previewing ||
                  !activeProvider.id ||
                  !selectedVoice ||
                  !activeModel.available ||
                  !previewText.trim()
                }
                onClick={() =>
                  preview(
                    {
                      provider: activeProvider.id,
                      model: activeModel.id,
                      voice: selectedVoice,
                      speed,
                    },
                    normalizePreviewText(previewText),
                  )
                }
              >
                Ouvir
              </Button>
              {!isLocal && (
                <Button
                  size="xs"
                  variant="subtle"
                  px={8}
                  aria-label="Atualizar lista de vozes"
                  loading={refreshingVoices}
                  onClick={safe(refreshVoices)}
                >
                  <RefreshCw size={14} />
                </Button>
              )}
              <Select
                w={240}
                aria-label="Voz"
                placeholder={
                  voices.length
                    ? "Escolha a voz"
                    : "Nenhuma voz disponível para este modelo"
                }
                data={voices.map((v) => ({
                  value: v.id,
                  label: formatVoiceOptionLabel(v),
                }))}
                value={selectedVoice}
                disabled={!voices.length}
                searchable
                nothingFoundMessage="Nenhuma voz encontrada"
                onChange={(nextVoice) => {
                  if (!nextVoice) return;
                  setDraft((old) => ({
                    ...old,
                    provider: activeProvider.id,
                    model: activeModel.id,
                    voice: nextVoice,
                  }));
                }}
              />
            </div>
          </div>

          <div className="settings-row">
            <div className="settings-row-info">
              <Group gap="xs">
                <Text size="sm" fw={600}>
                  Velocidade
                </Text>
                <Badge size="xs" variant="light" color="violet">
                  {speed.toFixed(2)}×
                </Badge>
              </Group>
            </div>
            <div className="settings-row-control" style={{ minWidth: 240 }}>
              <Slider
                style={{ width: 240 }}
                aria-label="Velocidade da fala"
                min={bounds.min}
                max={bounds.max}
                step={bounds.step}
                label={(v) => `${v.toFixed(2)}×`}
                value={speed}
                onChange={(nextSpeed) =>
                  setDraft((old) => ({
                    ...old,
                    speed: clampSpeed(nextSpeed, bounds),
                  }))
                }
              />
            </div>
          </div>
        </div>
      </div>

      <Group justify="flex-end">
        <Button
          disabled={!dirty || saving}
          loading={saving}
          leftSection={<Check size={16} />}
          onClick={safe(save)}
        >
          Salvar voz da PIA
        </Button>
      </Group>
    </Stack>
  );
}
