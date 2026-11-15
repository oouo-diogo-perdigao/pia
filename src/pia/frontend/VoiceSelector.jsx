import React, { useEffect, useState, useCallback, useRef } from "react";
import {
  Select,
  Loader,
  Text,
  Badge,
  Group,
  Stack,
  Slider,
  NumberInput,
  Button,
  Radio,
  Alert,
  Paper,
} from "@mantine/core";
import { Volume2, RefreshCw } from "lucide-react";
import { api, watchJob, report, safe } from "./api";
import { notify } from "./toasts";
import {
  encodeModelKey,
  decodeModelKey,
  findProviderAndModel,
  speedBounds,
  clampSpeed,
  resolveDraftForModel,
  buildVoiceSelectGroups,
  ttsPreviewController,
} from "./tts-helpers";

export const TTS_UPDATED_EVENT = "pia:tts-updated";

export function notifyTtsUpdated() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(TTS_UPDATED_EVENT));
  }
}

export function useTtsCatalog() {
  const [providers, setProviders] = useState([]);
  const [selection, setSelection] = useState(null);
  const [revision, setRevision] = useState(1);
  const [warnings, setWarnings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    try {
      setError(null);
      const res = await api("/tts/providers");
      setProviders(res.providers || []);
      const sel = res.selection?.profile || res.selected || null;
      setSelection(sel);
      setRevision(res.revision || res.selection?.revision || 1);
      setWarnings(res.warnings || []);
      return res;
    } catch (err) {
      setError(err?.message || "Falha ao carregar catálogo de voz.");
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    api("/tts/providers")
      .then((res) => {
        if (!active) return;
        setProviders(res.providers || []);
        setSelection(res.selection?.profile || res.selected || null);
        setRevision(res.revision || res.selection?.revision || 1);
        setWarnings(res.warnings || []);
      })
      .catch((err) => {
        if (!active) return;
        setError(err?.message || "Falha ao carregar catálogo de voz.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    const onUpdated = () => {
      if (active) refresh().catch(() => {});
    };
    window.addEventListener(TTS_UPDATED_EVENT, onUpdated);
    return () => {
      active = false;
      window.removeEventListener(TTS_UPDATED_EVENT, onUpdated);
    };
  }, [refresh]);

  return {
    providers,
    selection,
    revision,
    warnings,
    loading,
    error,
    refresh,
  };
}

export function useTtsPreview() {
  const [previewing, setPreviewing] = useState(false);
  const inFlightRef = useRef(false);
  const mountedRef = useRef(true);
  const ownerRef = useRef(null);
  if (!ownerRef.current) {
    ownerRef.current = Symbol("tts-preview");
  }

  useEffect(() => {
    mountedRef.current = true;
    const owner = ownerRef.current;
    return () => {
      mountedRef.current = false;
      ttsPreviewController.stop(owner);
    };
  }, []);

  const stop = useCallback(() => {
    ttsPreviewController.stop(ownerRef.current);
  }, []);

  const preview = useCallback(async (profile, text) => {
    if (inFlightRef.current) return;
    if (!profile?.provider || !profile?.voice) {
      notify("Selecione um modelo e uma voz antes de testar.", "error");
      return;
    }
    inFlightRef.current = true;
    setPreviewing(true);
    try {
      await ttsPreviewController.play(profile, text, {
        owner: ownerRef.current,
        requestPreview: (prof, previewText) =>
          api("/tts/preview", {
            profile: prof,
            ...(previewText ? { text: previewText } : {}),
          }),
        watch: watchJob,
        pollJob: (jobId) => api(`/tts/jobs/${jobId}`),
        createAudio: (url) => new Audio(url),
        notifyError: (msg) => notify(msg, "error"),
      });
    } catch (err) {
      report(err);
    } finally {
      inFlightRef.current = false;
      if (mountedRef.current) {
        setPreviewing(false);
      }
    }
  }, []);

  return { preview, previewing, stop };
}

export default function VoiceSelector({
  value = null,
  onChange,
  onPreview,
  previewing = false,
  catalog = [],
  disabled = false,
  label = "Modelo e voz",
}) {
  const safeVal = value && typeof value === "object" ? value : null;
  const { provider, model } = findProviderAndModel(
    catalog,
    safeVal?.provider,
    safeVal?.model,
  );
  const voices = model?.voices || provider?.voices || [];
  const bounds = speedBounds(model, provider);
  const modelKey = provider
    ? encodeModelKey(provider.id, model?.id || safeVal?.model)
    : null;
  const selectedVoice = voices.some((v) => v.id === safeVal?.voice)
    ? safeVal?.voice
    : null;
  const speed = clampSpeed(safeVal?.speed, bounds);
  const groups = buildVoiceSelectGroups(catalog);

  const unavailableReason =
    provider && !model?.available
      ? provider.kind === "remote"
        ? "Chave de API não configurada no Cofre."
        : "Modelo local não instalado."
      : null;

  return (
    <Stack gap="sm">
      <Select
        label={label}
        placeholder="Selecione um modelo de voz"
        data={groups}
        value={modelKey}
        disabled={disabled || !catalog.length}
        searchable
        nothingFoundMessage="Nenhum modelo disponível"
        onChange={(nextKey) => {
          if (!nextKey) return;
          const { provider: pid, model: mid } = decodeModelKey(nextKey);
          onChange?.(resolveDraftForModel(catalog, pid, mid, safeVal));
        }}
      />
      {unavailableReason && (
        <Text size="xs" c="yellow">
          {unavailableReason}
        </Text>
      )}
      <Group align="flex-end" wrap="wrap" gap="sm">
        <Select
          style={{ flex: 1, minWidth: 200 }}
          label="Voz"
          placeholder={
            voices.length
              ? "Escolha a voz"
              : "Nenhuma voz disponível para este modelo"
          }
          data={voices.map((v) => ({
            value: v.id,
            label: `${v.name}${v.lang ? ` · ${v.lang}` : ""}`,
          }))}
          value={selectedVoice}
          disabled={disabled || !voices.length}
          searchable
          nothingFoundMessage="Nenhuma voz encontrada"
          onChange={(nextVoice) => {
            if (!nextVoice) return;
            onChange?.({
              provider: provider?.id || safeVal?.provider || "",
              model: model?.id || safeVal?.model || "",
              voice: nextVoice,
              speed,
            });
          }}
        />
        {onPreview && (
          <Button
            variant="light"
            leftSection={
              previewing ? <Loader size={14} /> : <Volume2 size={16} />
            }
            disabled={
              disabled ||
              previewing ||
              !provider?.id ||
              !selectedVoice ||
              !model?.available
            }
            onClick={() =>
              onPreview({
                provider: provider?.id || safeVal?.provider,
                model: model?.id || safeVal?.model,
                voice: selectedVoice,
                speed,
              })
            }
          >
            Testar voz
          </Button>
        )}
      </Group>
      <Stack gap={4}>
        <Group justify="space-between">
          <Text size="sm" fw={500}>
            Velocidade da fala
          </Text>
          <Badge variant="light" color="violet">
            {speed.toFixed(2)}×
          </Badge>
        </Group>
        <Group gap="md" align="center" wrap="nowrap">
          <Slider
            style={{ flex: 1 }}
            aria-label="Velocidade da fala"
            min={bounds.min}
            max={bounds.max}
            step={bounds.step}
            value={speed}
            disabled={disabled}
            marks={[
              { value: bounds.min, label: `${bounds.min}×` },
              { value: 1.0, label: "1.0×" },
              { value: bounds.max, label: `${bounds.max}×` },
            ]}
            onChange={(nextSpeed) =>
              onChange?.({
                provider: provider?.id || safeVal?.provider || "",
                model: model?.id || safeVal?.model || "",
                voice: selectedVoice || "",
                speed: clampSpeed(nextSpeed, bounds),
              })
            }
          />
          <NumberInput
            aria-label="Velocidade numérica"
            w={90}
            size="xs"
            min={bounds.min}
            max={bounds.max}
            step={bounds.step}
            decimalScale={2}
            value={speed}
            disabled={disabled}
            onChange={(val) => {
              if (val === "" || val === null || val === undefined) return;
              onChange?.({
                provider: provider?.id || safeVal?.provider || "",
                model: model?.id || safeVal?.model || "",
                voice: selectedVoice || "",
                speed: clampSpeed(val, bounds),
              });
            }}
          />
        </Group>
      </Stack>
    </Stack>
  );
}

export function SpeakerVoicePanel({
  speakerId,
  value,
  onChange,
  catalog: externalCatalog,
  title = "Voz do bot",
  previewText,
  standalone = false,
}) {
  const internalCatalog = useTtsCatalog();
  const catalog = externalCatalog || internalCatalog.providers;
  const generalSelection = internalCatalog.selection;
  const { preview, previewing } = useTtsPreview();

  const isControlled = value !== undefined && onChange !== undefined;
  const [doc, setDoc] = useState({
    mode: "inherit",
    profile: null,
    revision: 1,
  });
  const [savedDoc, setSavedDoc] = useState(null);
  const [loading, setLoading] = useState(!isControlled);
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState(false);

  const loadSpeaker = useCallback(async () => {
    if (!speakerId) return;
    setLoading(true);
    setConflict(false);
    try {
      const res = await api(`/speakers/${encodeURIComponent(speakerId)}/voice`);
      setDoc(res);
      setSavedDoc(res);
    } catch (err) {
      report(err);
    } finally {
      setLoading(false);
    }
  }, [speakerId]);

  useEffect(() => {
    if (!isControlled && speakerId) {
      loadSpeaker();
    }
  }, [isControlled, speakerId, loadSpeaker]);

  const current = isControlled
    ? value || { mode: "inherit", profile: null, revision: 1 }
    : doc;
  const mode = current.mode === "custom" ? "custom" : "inherit";

  const emit = (next) => {
    if (isControlled) onChange(next);
    else setDoc(next);
  };

  const defaultCustomProfile = () => {
    if (current.profile?.provider) return current.profile;
    if (generalSelection?.provider) return { ...generalSelection };
    const firstAvail =
      catalog.find((p) => (p.models || []).some((m) => m.available)) ||
      catalog[0];
    return resolveDraftForModel(
      catalog,
      firstAvail?.id || "kokoro",
      firstAvail?.models?.[0]?.id || "kokoro-v1.0",
      null,
    );
  };

  if (loading) return <Loader size="sm" />;

  const dirty =
    !isControlled &&
    savedDoc &&
    JSON.stringify({ mode: doc.mode, profile: doc.profile }) !==
      JSON.stringify({ mode: savedDoc.mode, profile: savedDoc.profile });

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between">
          <Text fw={600} size="sm">
            {title}
          </Text>
          <Badge
            variant="light"
            color={mode === "custom" ? "violet" : "gray"}
            size="sm"
          >
            {mode === "custom" ? "Voz própria" : "Herdando Voz Geral da PIA"}
          </Badge>
        </Group>

        <Radio.Group
          value={mode}
          onChange={(nextMode) => {
            if (nextMode === "inherit") {
              emit({ ...current, mode: "inherit" });
            } else {
              emit({
                ...current,
                mode: "custom",
                profile: defaultCustomProfile(),
              });
            }
          }}
        >
          <Stack gap="xs">
            <Radio
              value="inherit"
              label={
                generalSelection
                  ? `Usar Voz Geral da PIA (${generalSelection.provider} · ${generalSelection.voice})`
                  : "Usar Voz Geral da PIA"
              }
            />
            <Radio value="custom" label="Usar voz própria exclusiva" />
          </Stack>
        </Radio.Group>

        {mode === "custom" && (
          <VoiceSelector
            label="Modelo e voz exclusiva"
            catalog={catalog}
            value={current.profile || defaultCustomProfile()}
            onChange={(nextProfile) =>
              emit({ ...current, mode: "custom", profile: nextProfile })
            }
            previewing={previewing}
            onPreview={(prof) => preview(prof, previewText)}
          />
        )}

        {mode === "inherit" && generalSelection && (
          <Group>
            <Button
              size="xs"
              variant="subtle"
              leftSection={
                previewing ? <Loader size={12} /> : <Volume2 size={14} />
              }
              disabled={previewing}
              onClick={() => preview(generalSelection, previewText)}
            >
              Ouvir Voz Geral atual
            </Button>
          </Group>
        )}

        {conflict && (
          <Alert color="yellow" title="Conflito de revisão">
            <Group justify="space-between">
              <Text size="xs">
                A voz foi alterada em outro lugar. Recarregue antes de salvar.
              </Text>
              <Button
                size="xs"
                variant="light"
                leftSection={<RefreshCw size={12} />}
                onClick={safe(loadSpeaker)}
              >
                Recarregar
              </Button>
            </Group>
          </Alert>
        )}

        {standalone && !isControlled && (
          <Group>
            <Button
              size="xs"
              loading={saving}
              disabled={!dirty}
              onClick={safe(async () => {
                setSaving(true);
                try {
                  const res = await api(
                    `/speakers/${encodeURIComponent(speakerId)}/voice`,
                    {
                      mode: doc.mode,
                      profile: doc.mode === "custom" ? doc.profile : null,
                      revision: doc.revision,
                    },
                    { method: "PUT" },
                  );
                  setDoc(res);
                  setSavedDoc(res);
                  setConflict(false);
                  notify("Voz do bot salva com sucesso.");
                  notifyTtsUpdated();
                } catch (err) {
                  if (err?.status === 409) setConflict(true);
                  throw err;
                } finally {
                  setSaving(false);
                }
              })}
            >
              Salvar voz do bot
            </Button>
          </Group>
        )}
      </Stack>
    </Paper>
  );
}
