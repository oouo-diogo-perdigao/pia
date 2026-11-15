import React, { useEffect, useRef, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  ColorInput,
  Divider,
  Group,
  MultiSelect,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { RefreshCw, Save, Sparkles, Upload, Volume2, X } from "lucide-react";
import { api, report, safe } from "../../../src/pia/frontend/api";
import { usePia } from "../../../src/pia/frontend/shared";
import { notify } from "../../../src/pia/frontend/toasts";
import {
  SpeakerVoicePanel,
  notifyTtsUpdated,
} from "../../../src/pia/frontend/VoiceSelector";
import SafeSvgAvatar from "./SafeSvgAvatar";
import {
  AVATAR_PRESETS,
  BOT_TEMPLATES,
  BOT_TOOL_OPTIONS,
  DEFAULT_BOT_COLORS,
  LLM_TIER_OPTIONS,
  buildBotPayload,
  validateClientSvg,
} from "./avatarPresets";

function makeInitialState(bot) {
  if (!bot) {
    return {
      name: "",
      description: "",
      instructions: BOT_TEMPLATES[0].instructions,
      enabled: true,
      speak_replies: true,
      llm_tier: "free",
      avatar_id: null,
      avatar_colors: { ...DEFAULT_BOT_COLORS },
      tool_ids: [],
      delegation_targets: [],
      voice: { mode: "inherit", profile: null, revision: 1 },
      revision: 1,
    };
  }
  return {
    name: bot.name || "",
    description: bot.description || "",
    instructions: bot.instructions || "",
    enabled: bot.enabled !== false,
    speak_replies: bot.speak_replies !== false,
    llm_tier: bot.llm_tier || "free",
    avatar_id: bot.avatar_id || null,
    avatar_colors: {
      primary: bot.avatar_colors?.primary || DEFAULT_BOT_COLORS.primary,
      accent: bot.avatar_colors?.accent || DEFAULT_BOT_COLORS.accent,
      eyes: bot.avatar_colors?.eyes || DEFAULT_BOT_COLORS.eyes,
    },
    tool_ids: Array.isArray(bot.tool_ids) ? bot.tool_ids : [],
    delegation_targets: Array.isArray(bot.delegation_targets)
      ? bot.delegation_targets
      : [],
    voice: bot.voice || { mode: "inherit", profile: null, revision: 1 },
    revision: bot.revision ?? 1,
  };
}

export default function BotEditor({
  bot = null,
  allBots = [],
  onSaved,
  onCancel,
}) {
  const isEdit = Boolean(bot?.id);
  const { refresh } = usePia();
  const fileInputRef = useRef(null);

  const [form, setForm] = useState(() => makeInitialState(bot));
  const [selectedPresetId, setSelectedPresetId] = useState(() =>
    isEdit && bot?.avatar_id ? "" : AVATAR_PRESETS[0].id,
  );
  const [pendingSvg, setPendingSvg] = useState(() =>
    !isEdit ? AVATAR_PRESETS[0].svg : "",
  );
  const [svgError, setSvgError] = useState("");
  const [previewSpeak, setPreviewSpeak] = useState(false);
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState(false);

  useEffect(() => {
    setForm(makeInitialState(bot));
    setSelectedPresetId(bot?.avatar_id ? "" : AVATAR_PRESETS[0].id);
    setPendingSvg(!bot?.id ? AVATAR_PRESETS[0].svg : "");
    setSvgError("");
    setConflict(false);
  }, [bot]);

  const setField = (key, value) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const applyTemplate = (tpl) => {
    const preset =
      AVATAR_PRESETS.find((p) => p.id === tpl.presetId) || AVATAR_PRESETS[0];
    setForm((prev) => ({
      ...prev,
      name: prev.name.trim() ? prev.name : tpl.name,
      description: tpl.description,
      instructions: tpl.instructions,
      llm_tier: tpl.llm_tier,
      tool_ids: [...tpl.tool_ids],
      avatar_colors: { ...tpl.avatar_colors },
    }));
    setSelectedPresetId(preset.id);
    setPendingSvg(preset.svg);
    setSvgError("");
  };

  const handleSvgUpload = (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const content = String(reader.result || "");
      const check = validateClientSvg(content);
      if (!check.ok) {
        setSvgError(check.error);
        return;
      }
      setSvgError("");
      setSelectedPresetId("custom");
      setPendingSvg(content);
    };
    reader.readAsText(file, "utf-8");
  };

  const delegationOptions = allBots
    .filter((b) => b.kind === "dynamic" && b.id !== bot?.id)
    .map((b) => ({
      value: b.id,
      label: b.name,
    }));

  const tierData = LLM_TIER_OPTIONS.some((o) => o.value === form.llm_tier)
    ? LLM_TIER_OPTIONS
    : [...LLM_TIER_OPTIONS, { value: form.llm_tier, label: form.llm_tier }];

  const canSave =
    form.name.trim().length >= 1 &&
    form.name.trim().length <= 80 &&
    form.description.length <= 2000 &&
    form.instructions.length <= 32000 &&
    !saving;

  const reloadLatestBot = async () => {
    if (!bot?.id) return;
    const latest = await api(`/openbot/bots/${bot.id}`);
    setForm(makeInitialState(latest));
    setConflict(false);
    onSaved?.(latest);
  };

  const handleSave = async () => {
    if (!form.name.trim()) {
      report(new Error("Informe um nome para o bot."));
      return;
    }
    setSaving(true);
    setConflict(false);
    try {
      let avatarId = form.avatar_id;
      if (pendingSvg) {
        const uploaded = await api("/openbot/avatars", { svg: pendingSvg });
        avatarId = uploaded.avatar_id;
      }
      const payload = buildBotPayload(form, {
        avatarId,
        isEdit,
      });
      const savedBot = isEdit
        ? await api(`/openbot/bots/${bot.id}`, payload, { method: "PATCH" })
        : await api("/openbot/bots", payload, { method: "POST" });

      setPendingSvg("");
      notify(
        isEdit
          ? `Bot "${savedBot.name}" atualizado.`
          : `Bot "${savedBot.name}" criado!`,
      );
      notifyTtsUpdated();
      await refresh();
      onSaved?.(savedBot);
    } catch (err) {
      if (err?.status === 409) {
        setConflict(true);
      }
      report(err);
    } finally {
      setSaving(false);
    }
  };

  const avatarSrc =
    !pendingSvg && (bot?.avatar_url || bot?.avatar)
      ? bot.avatar_url || bot.avatar
      : "";

  return (
    <Stack gap="md">
      {conflict && (
        <Alert color="yellow" title="Conflito de revisão (409)">
          <Group justify="space-between" wrap="wrap" gap="xs">
            <Text size="xs">
              Este bot foi alterado recentemente. Recarregue os dados atuais
              antes de salvar novamente.
            </Text>
            <Button
              size="xs"
              variant="light"
              leftSection={<RefreshCw size={12} />}
              onClick={safe(reloadLatestBot)}
            >
              Recarregar
            </Button>
          </Group>
        </Alert>
      )}

      {!isEdit && (
        <Paper withBorder p="sm" radius="md">
          <Stack gap="xs">
            <Group gap={6}>
              <Sparkles size={14} />
              <Text size="xs" fw={600} c="dimmed">
                Modelos iniciais rápidos (opcional)
              </Text>
            </Group>
            <Group gap="xs" wrap="wrap">
              {BOT_TEMPLATES.map((tpl) => (
                <Button
                  key={tpl.id}
                  size="xs"
                  variant="light"
                  onClick={() => applyTemplate(tpl)}
                >
                  {tpl.name}
                </Button>
              ))}
            </Group>
          </Stack>
        </Paper>
      )}

      <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
        <TextInput
          label="Nome do bot"
          placeholder="Ex.: Assistente de Projetos"
          required
          maxLength={80}
          value={form.name}
          onChange={(e) => setField("name", e.currentTarget.value)}
        />
        <Select
          label="Nível do modelo (LLM)"
          data={tierData}
          value={form.llm_tier}
          onChange={(val) => setField("llm_tier", val || "free")}
        />
      </SimpleGrid>

      <TextInput
        label="Descrição curta"
        placeholder="O que este bot faz em uma frase"
        maxLength={2000}
        value={form.description}
        onChange={(e) => setField("description", e.currentTarget.value)}
      />

      <Group gap="lg" wrap="wrap">
        <Switch
          label="Bot ativo"
          checked={form.enabled}
          onChange={(e) => setField("enabled", e.currentTarget.checked)}
        />
        <Switch
          label="Falar respostas automaticamente"
          checked={form.speak_replies}
          onChange={(e) => setField("speak_replies", e.currentTarget.checked)}
        />
      </Group>

      <Stack gap={4}>
        <Group justify="space-between">
          <Text size="sm" fw={500}>
            Instruções do Bot (AGENTS.md)
          </Text>
          <Text size="xs" c="dimmed">
            {form.instructions.length} / 32000 caracteres
          </Text>
        </Group>
        <Textarea
          placeholder="Defina o papel, regras, tom e estilo das respostas do bot..."
          autosize
          minRows={5}
          maxRows={14}
          maxLength={32000}
          styles={{
            input: { fontFamily: "monospace", fontSize: "0.85rem" },
          }}
          value={form.instructions}
          onChange={(e) => setField("instructions", e.currentTarget.value)}
        />
      </Stack>

      <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
        <MultiSelect
          label="Ferramentas permitidas"
          placeholder="Nenhuma ferramenta extra selecionada"
          data={BOT_TOOL_OPTIONS}
          value={form.tool_ids}
          onChange={(val) => setField("tool_ids", val)}
          searchable
          clearable
        />
        <MultiSelect
          label="Pode delegar para outros bots"
          placeholder={
            delegationOptions.length
              ? "Selecione bots de destino"
              : "Crie outros bots dinâmicos para delegar"
          }
          data={delegationOptions}
          value={form.delegation_targets}
          onChange={(val) => setField("delegation_targets", val)}
          disabled={!delegationOptions.length}
          searchable
          clearable
        />
      </SimpleGrid>

      <Divider label="Aparência e Avatar SVG" labelPosition="left" />

      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Group align="center" justify="space-between" wrap="wrap" gap="md">
            <Group gap="md" align="center">
              <SafeSvgAvatar
                svg={pendingSvg}
                src={avatarSrc}
                colors={form.avatar_colors}
                size={76}
                speaking={previewSpeak}
                alt={form.name || "Pré-visualização do avatar"}
              />
              <Stack gap={6}>
                <Text size="sm" fw={600}>
                  Pré-visualização ao vivo
                </Text>
                <Group gap="xs">
                  <Button
                    size="xs"
                    variant={previewSpeak ? "filled" : "light"}
                    color={previewSpeak ? "violet" : "gray"}
                    leftSection={<Volume2 size={13} />}
                    onClick={() => setPreviewSpeak((v) => !v)}
                  >
                    {previewSpeak ? "Parar animação" : "Simular fala"}
                  </Button>
                  <Button
                    size="xs"
                    variant="light"
                    leftSection={<Upload size={13} />}
                    onClick={() => fileInputRef.current?.click()}
                  >
                    Enviar .svg personalizado
                  </Button>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".svg,image/svg+xml"
                    style={{ display: "none" }}
                    onChange={handleSvgUpload}
                  />
                </Group>
              </Stack>
            </Group>
          </Group>

          {svgError && (
            <Alert color="red" variant="light">
              <Text size="xs">{svgError}</Text>
            </Alert>
          )}

          <Group gap="xs" wrap="wrap">
            {AVATAR_PRESETS.map((preset) => {
              const active = selectedPresetId === preset.id;
              return (
                <Tooltip key={preset.id} label={preset.name}>
                  <Paper
                    withBorder
                    p={6}
                    radius="md"
                    onClick={() => {
                      setSelectedPresetId(preset.id);
                      setPendingSvg(preset.svg);
                      setSvgError("");
                    }}
                    style={{
                      cursor: "pointer",
                      borderColor: active
                        ? "var(--mantine-color-violet-5)"
                        : undefined,
                    }}
                  >
                    <Group gap={6} wrap="nowrap">
                      <SafeSvgAvatar
                        svg={preset.svg}
                        colors={form.avatar_colors}
                        size={32}
                        alt={preset.name}
                      />
                      <Text size="xs" fw={active ? 600 : 400}>
                        {preset.name}
                      </Text>
                    </Group>
                  </Paper>
                </Tooltip>
              );
            })}
            {selectedPresetId === "custom" && (
              <Badge color="teal" variant="light">
                SVG personalizado carregado
              </Badge>
            )}
          </Group>

          <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm">
            {[
              ["primary", "Cor principal"],
              ["accent", "Cor de destaque"],
              ["eyes", "Cor dos olhos/boca"],
            ].map(([key, label]) => (
              <ColorInput
                key={key}
                label={label}
                format="hex"
                value={form.avatar_colors[key]}
                onChange={(val) =>
                  setField("avatar_colors", {
                    ...form.avatar_colors,
                    [key]: val || DEFAULT_BOT_COLORS[key],
                  })
                }
              />
            ))}
          </SimpleGrid>
        </Stack>
      </Paper>

      <SpeakerVoicePanel
        speakerId={isEdit ? `dynamic:${bot.id}` : undefined}
        title="Voz do Bot"
        value={form.voice}
        onChange={(nextVoice) => setField("voice", nextVoice)}
        previewText={`Olá! Eu sou ${form.name.trim() || "o seu novo bot"} na PIA.`}
      />

      <Group justify="flex-end" gap="sm">
        {onCancel && (
          <Button
            variant="subtle"
            leftSection={<X size={14} />}
            onClick={onCancel}
          >
            Cancelar
          </Button>
        )}
        <Button
          loading={saving}
          disabled={!canSave}
          leftSection={<Save size={15} />}
          onClick={handleSave}
        >
          {isEdit ? "Salvar alterações do bot" : "Criar Bot"}
        </Button>
      </Group>
    </Stack>
  );
}
