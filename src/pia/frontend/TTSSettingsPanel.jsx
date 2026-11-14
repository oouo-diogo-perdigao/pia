import React, { useEffect, useState, useRef } from "react";
import {
  Accordion,
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Paper,
  Progress,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import {
  AlertTriangle,
  Check,
  Download,
  KeyRound,
  RefreshCw,
  Trash2,
  Volume2,
  X,
} from "lucide-react";
import { api, report, safe, watchJob } from "./api";
import { notify } from "./toasts";
import { usePia } from "./shared";
import VoiceSelector, {
  notifyTtsUpdated,
  useTtsCatalog,
  useTtsPreview,
} from "./VoiceSelector";
import {
  formatBytes,
  formatReferenceLabel,
  groupProviders,
  resolveDraftForModel,
} from "./tts-helpers";

function LocalModelCard({
  provider,
  model,
  isDraftSelected,
  isSavedActive,
  jobSnapshot,
  uninstallError,
  onSelect,
  onInstall,
  onCancelInstall,
  onUninstall,
}) {
  const [confirmingUninstall, setConfirmingUninstall] = useState(false);
  const instState =
    jobSnapshot?.state === "running" || jobSnapshot?.state === "queued"
      ? "installing"
      : model.installation?.state ||
        (model.installed ? "installed" : "not_installed");
  const isInstalling = instState === "installing" || model.installing;
  const isInstalled = Boolean(model.installed || model.available);
  const percent =
    jobSnapshot?.progress?.percent ?? (isInstalling ? null : undefined);

  useEffect(() => {
    setConfirmingUninstall(false);
  }, [model.id, isInstalled]);

  return (
    <Paper
      withBorder
      p="md"
      radius="md"
      style={{
        borderColor: isDraftSelected
          ? "var(--mantine-color-violet-6)"
          : undefined,
      }}
    >
      <Stack gap="xs">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <div style={{ minWidth: 0 }}>
            <Group gap="xs" wrap="wrap">
              <Text fw={600} size="sm">
                {model.name || provider.name}
              </Text>
              {model.size_mb ? (
                <Text size="xs" c="dimmed">
                  ~
                  {model.size_mb >= 1000
                    ? `${(model.size_mb / 1024).toFixed(1)} GB`
                    : `${model.size_mb} MB`}
                </Text>
              ) : null}
            </Group>
            <Text size="xs" c="dimmed">
              {model.description || provider.description}
            </Text>
          </div>
          <Group gap={6} wrap="nowrap">
            {isSavedActive && (
              <Badge color="violet" variant="filled" size="sm">
                Ativo na PIA
              </Badge>
            )}
            {isInstalling ? (
              <Badge
                color="violet"
                variant="light"
                size="sm"
                leftSection={<Loader size={10} />}
              >
                Instalando…
              </Badge>
            ) : isInstalled ? (
              <Badge color="green" variant="light" size="sm">
                Instalado
              </Badge>
            ) : instState === "error" ? (
              <Badge color="red" variant="light" size="sm">
                Erro
              </Badge>
            ) : (
              <Badge color="gray" variant="light" size="sm">
                Não instalado
              </Badge>
            )}
          </Group>
        </Group>

        {isInstalling && (
          <Stack gap={4}>
            <Progress
              value={percent != null ? percent : 100}
              animated
              color="violet"
              size="sm"
            />
            <Group justify="space-between">
              <Text size="xs" c="dimmed" role="status" aria-live="polite">
                {jobSnapshot?.phase === "downloading"
                  ? "Baixando arquivos do modelo…"
                  : "Preparando instalação…"}
                {jobSnapshot?.progress?.completed_bytes
                  ? ` (${formatBytes(jobSnapshot.progress.completed_bytes)}${
                      jobSnapshot.progress.total_bytes
                        ? ` / ${formatBytes(jobSnapshot.progress.total_bytes)}`
                        : ""
                    })`
                  : ""}
              </Text>
              {percent != null && (
                <Text size="xs" fw={600}>
                  {percent.toFixed(0)}%
                </Text>
              )}
            </Group>
          </Stack>
        )}

        {instState === "error" &&
          (jobSnapshot?.error?.message || model.installation?.error) && (
            <Text size="xs" c="red">
              {jobSnapshot?.error?.message || model.installation?.error}
            </Text>
          )}

        {uninstallError && (
          <Alert color="yellow" p="xs" icon={<AlertTriangle size={14} />}>
            <Text size="xs" fw={500}>
              {uninstallError.message}
            </Text>
            {uninstallError.references?.length > 0 && (
              <Text size="xs" c="dimmed" mt={2}>
                Troque antes em:{" "}
                {uninstallError.references.map(formatReferenceLabel).join(", ")}
              </Text>
            )}
          </Alert>
        )}

        <Group justify="space-between" wrap="wrap" gap="xs" mt={4}>
          {isInstalled ? (
            <Button
              size="xs"
              variant={isDraftSelected ? "filled" : "light"}
              color="violet"
              leftSection={isDraftSelected ? <Check size={14} /> : null}
              onClick={() => onSelect(provider.id, model.id)}
            >
              {isDraftSelected ? "Selecionado" : "Usar este modelo"}
            </Button>
          ) : isInstalling ? (
            <Button
              size="xs"
              variant="subtle"
              color="red"
              leftSection={<X size={14} />}
              onClick={() =>
                onCancelInstall(
                  jobSnapshot?.job_id || model.installation?.job_id,
                )
              }
            >
              Cancelar instalação
            </Button>
          ) : (
            <Button
              size="xs"
              variant="light"
              leftSection={<Download size={14} />}
              onClick={() => onInstall(provider.id, model.id)}
            >
              Instalar
            </Button>
          )}

          {isInstalled &&
            !isInstalling &&
            (confirmingUninstall ? (
              <Group gap={6}>
                <Text size="xs" c="red">
                  Remover {model.name || provider.name}?
                </Text>
                <Button
                  size="xs"
                  color="red"
                  onClick={() => {
                    setConfirmingUninstall(false);
                    onUninstall(provider.id, model.id);
                  }}
                >
                  Confirmar
                </Button>
                <Button
                  size="xs"
                  variant="subtle"
                  onClick={() => setConfirmingUninstall(false)}
                >
                  Cancelar
                </Button>
              </Group>
            ) : (
              <Button
                size="xs"
                variant="subtle"
                color="red"
                leftSection={<Trash2 size={14} />}
                onClick={() => setConfirmingUninstall(true)}
              >
                Desinstalar
              </Button>
            ))}
        </Group>
      </Stack>
    </Paper>
  );
}

function RemoteProviderCard({
  provider,
  draft,
  savedProfile,
  onSelect,
  onOpenVault,
  onRefreshVoices,
}) {
  const configured =
    provider.credential_state === "configured" || provider.available;
  const models = provider.models || [];
  const isDraftProvider = draft?.provider === provider.id;
  const isSavedProvider = savedProfile?.provider === provider.id;

  return (
    <Paper
      withBorder
      p="md"
      radius="md"
      style={{
        borderColor: isDraftProvider
          ? "var(--mantine-color-violet-6)"
          : undefined,
      }}
    >
      <Stack gap="xs">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <div>
            <Text fw={600} size="sm">
              {provider.name}
            </Text>
            <Text size="xs" c="dimmed">
              {provider.description}
            </Text>
          </div>
          <Group gap={6}>
            {isSavedProvider && (
              <Badge color="violet" variant="filled" size="sm">
                Ativo na PIA
              </Badge>
            )}
            <Badge
              color={configured ? "green" : "yellow"}
              variant="light"
              size="sm"
            >
              {configured ? "Chave no cofre" : "Requer chave no cofre"}
            </Badge>
          </Group>
        </Group>

        {provider.error && (
          <Text size="xs" c="red">
            {provider.error}
          </Text>
        )}

        <Group justify="space-between" wrap="wrap" gap="xs">
          {configured ? (
            <Group gap="xs">
              <Button
                size="xs"
                variant={isDraftProvider ? "filled" : "light"}
                color="violet"
                onClick={() =>
                  onSelect(
                    provider.id,
                    isDraftProvider
                      ? draft.model
                      : models[0]?.id || provider.id,
                  )
                }
              >
                {isDraftProvider ? "Selecionado" : "Usar este modelo"}
              </Button>
              {provider.id === "elevenlabs" && (
                <Button
                  size="xs"
                  variant="subtle"
                  leftSection={<RefreshCw size={13} />}
                  onClick={() =>
                    onRefreshVoices(
                      provider.id,
                      isDraftProvider ? draft.model : models[0]?.id,
                    )
                  }
                >
                  Atualizar vozes
                </Button>
              )}
            </Group>
          ) : (
            <Button
              size="xs"
              variant="light"
              color="yellow"
              leftSection={<KeyRound size={14} />}
              onClick={onOpenVault}
            >
              Gerenciar Cofre
            </Button>
          )}
        </Group>
      </Stack>
    </Paper>
  );
}

export default function TTSSettingsPanel({ ttsFields = [] }) {
  const { navigate } = usePia();
  const { providers, selection, revision, warnings, loading, error, refresh } =
    useTtsCatalog();
  const { preview, previewing } = useTtsPreview();

  const [draft, setDraft] = useState(null);
  const [savedProfile, setSavedProfile] = useState(null);
  const [savedRevision, setSavedRevision] = useState(1);
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [activeJobs, setActiveJobs] = useState({});
  const [uninstallErrors, setUninstallErrors] = useState({});
  const watchersRef = useRef({});

  // Advanced settings state (non-voice hardware/timeout fields)
  const initialAdv = () => {
    const map = Object.fromEntries(
      ttsFields.map((f) => [f.name, f.value ?? ""]),
    );
    return {
      TTS_DEVICE: map.TTS_DEVICE || "cuda",
      TTS_KOKORO_IDLE_TIMEOUT: map.TTS_KOKORO_IDLE_TIMEOUT || "600",
      TTS_QWEN_IDLE_TIMEOUT: map.TTS_QWEN_IDLE_TIMEOUT || "600",
      TTS_LLM_MODEL: map.TTS_LLM_MODEL || "free",
    };
  };
  const [adv, setAdv] = useState(initialAdv);
  const [savedAdv, setSavedAdv] = useState(initialAdv);
  const [savingAdv, setSavingAdv] = useState(false);

  useEffect(() => {
    const next = initialAdv();
    setAdv(next);
    setSavedAdv(next);
  }, [ttsFields]);

  useEffect(() => {
    if (!selection) return;
    setSavedProfile(selection);
    setSavedRevision(revision);
    setDraft((prev) => prev || selection);
  }, [selection, revision]);

  const attachJob = (providerId, modelId, jobId) => {
    if (!jobId) return;
    const key = `${providerId}::${modelId}`;
    if (watchersRef.current[key]) return;

    const cleanup = () => {
      if (watchersRef.current[key]) {
        watchersRef.current[key].source?.close();
        clearInterval(watchersRef.current[key].poll);
        delete watchersRef.current[key];
      }
    };

    const handleSnap = (snap) => {
      setActiveJobs((old) => ({ ...old, [key]: snap }));
      if (snap.state === "done" || snap.state === "error") {
        cleanup();
        refresh().catch(() => {});
        notifyTtsUpdated();
        if (snap.state === "done") {
          notify(`Modelo ${modelId} instalado com sucesso.`);
        }
      }
    };

    const source = watchJob(jobId, (ev) => {
      if (ev.type === "progress") {
        handleSnap({
          job_id: jobId,
          state: ev.state || "running",
          phase: ev.phase || "downloading",
          progress: ev.progress || {},
          error: ev.error || null,
        });
      } else if (ev.type === "done") {
        handleSnap({
          job_id: jobId,
          state: "done",
          phase: "installed",
          progress: { percent: 100 },
        });
      } else if (ev.type === "error") {
        handleSnap({
          job_id: jobId,
          state: "error",
          phase: ev.code === "cancelled" ? "cancelled" : "error",
          error: { code: ev.code, message: ev.error },
        });
      }
    });

    const poll = setInterval(async () => {
      try {
        const snap = await api(`/tts/jobs/${jobId}`);
        handleSnap(snap);
      } catch {}
    }, 1000);

    watchersRef.current[key] = { source, poll };
  };

  useEffect(() => {
    for (const p of providers) {
      if (p.kind !== "local") continue;
      for (const m of p.models || []) {
        if (m.installation?.state === "installing" && m.installation?.job_id) {
          attachJob(p.id, m.id, m.installation.job_id);
        }
      }
    }
  }, [providers]);

  useEffect(() => {
    return () => {
      for (const key of Object.keys(watchersRef.current)) {
        watchersRef.current[key].source?.close();
        clearInterval(watchersRef.current[key].poll);
      }
      watchersRef.current = {};
    };
  }, []);

  if (loading && !providers.length) {
    return (
      <Group gap="xs">
        <Loader size="sm" />
        <Text size="sm">Carregando modelos de voz…</Text>
      </Group>
    );
  }

  const { local, remote } = groupProviders(providers);
  const currentDraft = draft || savedProfile;
  const dirty =
    currentDraft &&
    savedProfile &&
    (currentDraft.provider !== savedProfile.provider ||
      currentDraft.model !== savedProfile.model ||
      currentDraft.voice !== savedProfile.voice ||
      Number(currentDraft.speed) !== Number(savedProfile.speed));

  const advDirty = JSON.stringify(adv) !== JSON.stringify(savedAdv);

  const timeoutOptions = [
    { value: "120", label: "2 minutos" },
    { value: "300", label: "5 minutos" },
    { value: "600", label: "10 minutos (Padrão)" },
    { value: "1800", label: "30 minutos" },
    { value: "0", label: "Manter sempre carregado" },
  ];
  const withCustomOption = (options, currentValue) => {
    const str = String(currentValue ?? "");
    if (!str || options.some((o) => o.value === str)) return options;
    return [...options, { value: str, label: `${str} (personalizado)` }];
  };

  const llmTierOptions = withCustomOption(
    [
      { value: "free", label: "Automático · Gratuito" },
      { value: "fast", label: "Rápido" },
      { value: "smart", label: "Avançado" },
    ],
    adv.TTS_LLM_MODEL,
  );

  return (
    <Stack gap="lg">
      {error && (
        <Alert color="red" title="Não foi possível carregar os modelos de voz">
          <Group justify="space-between">
            <Text size="sm">{error}</Text>
            <Button
              size="xs"
              variant="light"
              leftSection={<RefreshCw size={14} />}
              onClick={safe(() => refresh())}
            >
              Tentar novamente
            </Button>
          </Group>
        </Alert>
      )}

      {warnings.map((w, idx) => (
        <Alert key={idx} color="yellow" title="Aviso de migração TTS">
          <Text size="xs">{w}</Text>
        </Alert>
      ))}

      <Paper withBorder p="md" radius="md">
        <Group justify="space-between" wrap="wrap" gap="sm">
          <div>
            <Text size="xs" c="dimmed" fw={600} tt="uppercase">
              Voz Geral da PIA
            </Text>
            <Group gap="xs" mt={4}>
              <Text fw={600}>
                {savedProfile
                  ? `${savedProfile.provider} · ${savedProfile.model} · ${savedProfile.voice}`
                  : "Nenhuma voz selecionada"}
              </Text>
              {savedProfile?.speed != null && (
                <Badge variant="light" color="violet">
                  {Number(savedProfile.speed).toFixed(2)}×
                </Badge>
              )}
            </Group>
          </div>
          <Group gap="xs">
            <Button
              size="xs"
              variant="light"
              leftSection={
                previewing ? <Loader size={14} /> : <Volume2 size={15} />
              }
              disabled={previewing || !currentDraft?.voice}
              onClick={() => preview(currentDraft)}
            >
              Ouvir prévia
            </Button>
            <Button
              size="xs"
              variant="subtle"
              leftSection={<RefreshCw size={14} />}
              onClick={safe(() => refresh())}
            >
              Atualizar
            </Button>
          </Group>
        </Group>
      </Paper>

      <Stack gap="xs">
        <Title order={5}>Modelos Locais</Title>
        <Text size="xs" c="dimmed">
          Executam no seu computador, sem custo de API. Instale e gerencie cada
          modelo individualmente.
        </Text>
        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="sm">
          {local.flatMap((provider) =>
            (provider.models || []).map((model) => {
              const key = `${provider.id}::${model.id}`;
              return (
                <LocalModelCard
                  key={key}
                  provider={provider}
                  model={model}
                  isDraftSelected={
                    currentDraft?.provider === provider.id &&
                    currentDraft?.model === model.id
                  }
                  isSavedActive={
                    savedProfile?.provider === provider.id &&
                    savedProfile?.model === model.id
                  }
                  jobSnapshot={activeJobs[key]}
                  uninstallError={uninstallErrors[key]}
                  onSelect={(pid, mid) =>
                    setDraft((old) =>
                      resolveDraftForModel(providers, pid, mid, old),
                    )
                  }
                  onInstall={safe(async (pid, mid) => {
                    setUninstallErrors((old) => ({ ...old, [key]: null }));
                    const res = await api("/tts/install", {
                      provider: pid,
                      model: mid,
                      request_id: crypto.randomUUID(),
                    });
                    attachJob(pid, mid, res.job_id);
                    await refresh();
                  })}
                  onCancelInstall={safe(async (jobId) => {
                    if (!jobId) return;
                    await api(`/tts/jobs/${jobId}/cancel`, {});
                  })}
                  onUninstall={safe(async (pid, mid) => {
                    setUninstallErrors((old) => ({ ...old, [key]: null }));
                    try {
                      await api("/tts/uninstall", {
                        provider: pid,
                        model: mid,
                        request_id: crypto.randomUUID(),
                      });
                      notify(`Modelo ${model.name || mid} desinstalado.`);
                      await refresh();
                      notifyTtsUpdated();
                    } catch (err) {
                      if (err?.status === 409) {
                        setUninstallErrors((old) => ({
                          ...old,
                          [key]: {
                            message: err.message,
                            references: err.details?.references || [],
                          },
                        }));
                        return;
                      }
                      throw err;
                    }
                  })}
                />
              );
            }),
          )}
        </SimpleGrid>
      </Stack>

      <Stack gap="xs">
        <Title order={5}>Modelos Remotos</Title>
        <Text size="xs" c="dimmed">
          Serviços na nuvem que usam suas chaves configuradas no Cofre da PIA.
        </Text>
        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="sm">
          {remote.map((provider) => (
            <RemoteProviderCard
              key={provider.id}
              provider={provider}
              draft={currentDraft}
              savedProfile={savedProfile}
              onSelect={(pid, mid) =>
                setDraft((old) =>
                  resolveDraftForModel(providers, pid, mid, old),
                )
              }
              onOpenVault={() =>
                navigate({ view: "settings", section: "credentials" })
              }
              onRefreshVoices={safe(async (pid, mid) => {
                await api(
                  `/tts/voices?provider=${encodeURIComponent(pid)}&model=${encodeURIComponent(mid || "")}&refresh=true`,
                );
                await refresh();
                notify("Lista de vozes atualizada.");
              })}
            />
          ))}
        </SimpleGrid>
      </Stack>

      <Paper withBorder p="md" radius="md">
        <Stack gap="md">
          <Title order={5}>Voz e Velocidade Padrão da PIA</Title>
          <VoiceSelector
            catalog={providers}
            value={currentDraft}
            onChange={(next) => setDraft(next)}
            previewing={previewing}
            onPreview={(prof) => preview(prof)}
          />

          {conflict && (
            <Alert color="yellow" title="Conflito de revisão">
              <Group justify="space-between">
                <Text size="xs">
                  A configuração de voz foi atualizada fora desta tela.
                  Recarregue a seleção atual antes de salvar.
                </Text>
                <Button
                  size="xs"
                  variant="light"
                  leftSection={<RefreshCw size={12} />}
                  onClick={safe(async () => {
                    const res = await refresh();
                    const sel = res.selection?.profile || res.selected;
                    if (sel) setDraft(sel);
                    setConflict(false);
                  })}
                >
                  Recarregar
                </Button>
              </Group>
            </Alert>
          )}

          <Group>
            <Button
              loading={saving}
              disabled={
                !dirty || !currentDraft?.provider || !currentDraft?.voice
              }
              onClick={safe(async () => {
                setSaving(true);
                try {
                  const res = await api("/tts/select", {
                    revision: savedRevision,
                    provider: currentDraft.provider,
                    model: currentDraft.model,
                    voice: currentDraft.voice,
                    speed: currentDraft.speed,
                  });
                  setSavedProfile(res.profile);
                  setSavedRevision(res.revision);
                  setDraft(res.profile);
                  setConflict(false);
                  notify("Voz Geral da PIA salva com sucesso.");
                  notifyTtsUpdated();
                  await refresh();
                } catch (err) {
                  if (err?.status === 409) setConflict(true);
                  throw err;
                } finally {
                  setSaving(false);
                }
              })}
            >
              Salvar Voz Geral da PIA
            </Button>
          </Group>
        </Stack>
      </Paper>

      <Accordion variant="separated" radius="md">
        <Accordion.Item value="advanced-tts">
          <Accordion.Control>
            Opções avançadas de hardware e memória
          </Accordion.Control>
          <Accordion.Panel>
            <Stack gap="md">
              <div>
                <Text size="sm" fw={500} mb={6}>
                  Dispositivo de processamento local
                </Text>
                <SegmentedControl
                  value={adv.TTS_DEVICE}
                  data={[
                    { value: "auto", label: "Auto" },
                    { value: "cuda", label: "GPU (CUDA)" },
                    { value: "cpu", label: "CPU" },
                  ]}
                  onChange={(val) =>
                    setAdv((old) => ({ ...old, TTS_DEVICE: val }))
                  }
                />
              </div>

              <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
                <Select
                  label="Liberar Kokoro da memória após inatividade"
                  data={withCustomOption(
                    timeoutOptions,
                    adv.TTS_KOKORO_IDLE_TIMEOUT,
                  )}
                  value={adv.TTS_KOKORO_IDLE_TIMEOUT}
                  onChange={(val) =>
                    val &&
                    setAdv((old) => ({ ...old, TTS_KOKORO_IDLE_TIMEOUT: val }))
                  }
                />
                <Select
                  label="Liberar Qwen3 da memória após inatividade"
                  data={withCustomOption(
                    timeoutOptions,
                    adv.TTS_QWEN_IDLE_TIMEOUT,
                  )}
                  value={adv.TTS_QWEN_IDLE_TIMEOUT}
                  onChange={(val) =>
                    val &&
                    setAdv((old) => ({ ...old, TTS_QWEN_IDLE_TIMEOUT: val }))
                  }
                />
              </SimpleGrid>

              <Select
                label="Modelo de IA para vozes em storytelling"
                data={llmTierOptions}
                value={adv.TTS_LLM_MODEL}
                onChange={(val) =>
                  val && setAdv((old) => ({ ...old, TTS_LLM_MODEL: val }))
                }
              />

              <Group>
                <Button
                  size="xs"
                  loading={savingAdv}
                  disabled={!advDirty}
                  onClick={safe(async () => {
                    setSavingAdv(true);
                    try {
                      await api("/settings/save", {
                        section: "general",
                        values: adv,
                      });
                      setSavedAdv(adv);
                    } finally {
                      setSavingAdv(false);
                    }
                  })}
                >
                  Salvar opções avançadas
                </Button>
              </Group>
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Stack>
  );
}
