import { fingerprint } from "../../../../src/pia/frontend/forms";
import ResourcePicker from "../../../../src/pia/frontend/ResourcePicker";
import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  Accordion,
  Alert,
  Anchor,
  Badge,
  Button,
  Checkbox,
  Collapse,
  FileInput,
  Group,
  Modal,
  MultiSelect,
  Paper,
  SegmentedControl,
  Select,
  SimpleGrid,
  Skeleton,
  Stack,
  Switch,
  Table,
  TagsInput,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  Circle,
  Download,
  ExternalLink,
  FolderOpen,
  Loader,
  Play,
  Plus,
  RotateCcw,
  Search,
  Settings,
  Square,
  Trash2,
  Undo2,
  X,
} from "lucide-react";
import {
  api,
  appApi,
  watchJob,
  safe,
  report,
} from "../../../../src/pia/frontend/api";
import { notify } from "../../../../src/pia/frontend/toasts";
import {
  Icon,
  Nav,
  WorkProgress,
  LogViewer,
  About,
  usePia,
} from "../../../../src/pia/frontend/shared";
import {
  APP_SETTINGS_DEFAULTS,
  AUDIO_DEFAULTS,
  AUDIO_NUMERIC_KEYS,
  buildCampaignsList,
  buildParticipantsList,
  buildSettingsDraft,
  campaignsListToObject,
  formatMegabytesHelp,
  formatMinutesHelp,
  nextUid,
  participantsToConfig,
  validateCampaigns,
  validateParticipants,
  validateSettingsDraft,
} from "../../../../src/pia/frontend/podcast-helpers";

function campaignConfig(value) {
  const {
    integrations,
    outputs,
    app_settings,
    app_defaults,
    timezone,
    ...campaigns
  } = value || {};
  return campaigns;
}

function extraCampaignRootKeys(value) {
  const {
    integrations,
    outputs,
    app_settings,
    app_defaults,
    timezone,
    nomes_reais,
    discord_users,
    campaign_details,
    publication,
    processing,
    audio,
    ...rest
  } = value || {};
  return rest;
}

function parseJsonWithLine(text) {
  try {
    return { ok: true, value: JSON.parse(text), error: "" };
  } catch (err) {
    const msg = err?.message || "Erro de sintaxe";
    const posMatch = /position\s+(\d+)/i.exec(msg);
    let line = 1;
    if (posMatch) {
      const pos = Number(posMatch[1]);
      line = text.slice(0, pos).split("\n").length;
    }
    return {
      ok: false,
      value: null,
      error: `JSON inválido na linha ${line}: ${msg}.`,
    };
  }
}

function focusField(fieldId) {
  const el = document.getElementById(fieldId);
  if (el && typeof el.focus === "function") {
    el.focus();
    el.scrollIntoView?.({ behavior: "smooth", block: "center" });
  }
}

const id = "podcast_automation",
  call = (action, data = {}) => appApi(id, action, data);

export default function Podcast({
  sub = "principal",
  ModelSettingsSlot = null,
}) {
  const { navigate, route, openServerConnector } = usePia(),
    [config, setConfig] = useState(null),
    [configLoading, setConfigLoading] = useState(true),
    [configError, setConfigError] = useState(""),
    [original, setOriginal] = useState(""),
    [savedOptions, setSavedOptions] = useState(""),
    [picker, setPicker] = useState(null),
    [editor, setEditor] = useState(""),
    [logs, setLogs] = useState(""),
    [pipeline, setPipeline] = useState({ stages: [], artifacts: [] }),
    [running, setRunning] = useState(false),
    [job, setJob] = useState(null),
    [preview, setPreview] = useState(null),
    [previewError, setPreviewError] = useState(""),
    [previewLoading, setPreviewLoading] = useState(false),
    [previewVersion, setPreviewVersion] = useState(0),
    [monitor, setMonitor] = useState(false),
    [shutdownAfter, setShutdownAfter] = useState(false),
    [shutdownPending, setShutdownPending] = useState(false),
    [google, setGoogle] = useState([]),
    [accounts, setAccounts] = useState([]),
    [channels, setChannels] = useState([]),
    [taverns, setTaverns] = useState({ channels: [], loading: true }),
    [result, setResult] = useState(null),
    [merge, setMerge] = useState(null),
    [files, setFiles] = useState([null, null]),
    // Campanhas (modo estruturado + JSON avançado)
    [campaignsJsonMode, setCampaignsJsonMode] = useState(false),
    [jsonSwitchError, setJsonSwitchError] = useState(""),
    [participants, setParticipants] = useState([]),
    [campaigns, setCampaigns] = useState([]),
    [expandedCampaigns, setExpandedCampaigns] = useState({}),
    [savedCampaignsFp, setSavedCampaignsFp] = useState(""),
    [campaignErrors, setCampaignErrors] = useState({
      errors: [],
      fieldErrors: {},
    }),
    [savingCampaigns, setSavingCampaigns] = useState(false),
    [removeCampaignModal, setRemoveCampaignModal] = useState(null),
    // Configurações (aba Settings)
    [settingsDraft, setSettingsDraft] = useState(null),
    [savedSettingsFp, setSavedSettingsFp] = useState(""),
    [settingsErrors, setSettingsErrors] = useState({
      errors: [],
      fieldErrors: {},
    }),
    [savingSettings, setSavingSettings] = useState(false),
    [pickingFolder, setPickingFolder] = useState(""),
    [folderFeedback, setFolderFeedback] = useState({ path: "", message: "" }),
    [audioResetModal, setAudioResetModal] = useState(false),
    [pendingAnchor, setPendingAnchor] = useState(""),
    // Guarda de alterações não salvas
    [leaveModal, setLeaveModal] = useState(null);

  const source = useRef();
  const opts = config?.integrations || {},
    outputs = config?.outputs || {},
    patch = (key, value) =>
      setConfig((old) => ({
        ...old,
        integrations: { ...old.integrations, [key]: value },
      }));
  const settings = openServerConnector;

  useEffect(() => {
    let active = true;
    api("/integrations/taverns/channels", {}).then(
      (res) => {
        if (active) setTaverns(res);
      },
      (error) => {
        if (active) setTaverns({ channels: [], error: error.message });
      },
    );
    return () => {
      active = false;
    };
  }, []);

  function watch(identity, after = 0) {
    source.current?.close();
    setJob(identity);
    setRunning(true);
    source.current = watchJob(
      identity,
      (event) => {
        if (event.type === "log")
          setLogs((old) => (old + event.text + "\n").slice(-300000));
        if (event.type === "log-clear") setLogs("");
        if (event.type === "pipeline") setPipeline(event.value);
        if (["done", "error"].includes(event.type)) {
          setRunning(false);
          if (event.type === "done") {
            setResult(event.result || null);
            setShutdownPending(!!event.shutdown_pending);
          }
          if (event.type === "error") report(event.error);
        }
      },
      after,
    );
  }

  const syncFromConfig = useCallback((configuration, discordChannels = []) => {
    const integrations = { ...configuration.integrations };
    if (!integrations.discord_channels)
      integrations.discord_channels =
        integrations.discord_channel &&
        discordChannels.some((c) => c.channel === integrations.discord_channel)
          ? [integrations.discord_channel]
          : [];
    delete integrations.discord_channel;
    const normalized = { ...configuration, integrations };
    setConfig(normalized);
    setSavedOptions(
      fingerprint({ outputs: normalized.outputs || {}, integrations }),
    );
    const text = JSON.stringify(campaignConfig(configuration), null, 2);
    setOriginal(text);
    setEditor(text);

    const nextParticipants = buildParticipantsList(
      configuration.nomes_reais || {},
      configuration.discord_users || {},
    );
    const nextCampaigns = buildCampaignsList(
      configuration.campaign_details || {},
    );
    setParticipants(nextParticipants);
    setCampaigns(nextCampaigns);
    setSavedCampaignsFp(
      fingerprint({
        participants: nextParticipants.map(
          ({ realName, handles, discordId }) => ({
            realName,
            handles,
            discordId,
          }),
        ),
        campaigns: nextCampaigns.map(({ id: _id, playersList, ...rest }) => ({
          ...rest,
          playersList: playersList.map(({ player, character }) => ({
            player,
            character,
          })),
        })),
      }),
    );

    const nextSettingsDraft = buildSettingsDraft(configuration);
    setSettingsDraft(nextSettingsDraft);
    setSavedSettingsFp(fingerprint(nextSettingsDraft));
    setSettingsErrors({ errors: [], fieldErrors: {} });
    setCampaignErrors({ errors: [], fieldErrors: {} });
    return normalized;
  }, []);

  const loadAll = useCallback(async () => {
    setConfigLoading(true);
    setConfigError("");
    try {
      const [configuration, status, steps, g, storage, discord] =
        await Promise.all([
          call("config"),
          call("status"),
          call("pipeline"),
          api("/integrations/google/accounts", {}),
          appApi("object_storage", "accounts"),
          api("/integrations/discord/channels", {}),
        ]);
      syncFromConfig(configuration, discord.channels || []);
      setGoogle(g.accounts || []);
      setAccounts(storage.accounts || []);
      setChannels(discord.channels || []);
      setLogs((status.lines || []).join("\n"));
      setResult(status.result || null);
      setPipeline(steps || { stages: [], artifacts: [] });
      setShutdownPending(!!status.shutdown_pending);
      if (status.running) {
        setMonitor(!!status.monitor);
        setShutdownAfter(!!status.shutdown_after);
        watch(status.job, status.cursor || 0);
      }
    } catch (err) {
      setConfigError(err?.message || "Falha ao comunicar com o servidor.");
    } finally {
      setConfigLoading(false);
    }
  }, [syncFromConfig]);

  useEffect(() => {
    loadAll();
    return () => {
      source.current?.close();
    };
  }, [loadAll]);

  useEffect(() => {
    if (!config) return;
    let active = true;
    setPreviewLoading(true);
    setPreviewError("");
    setPreview(null);
    call("pending-preview", {
      google_account: opts.google_account || "",
      google_folder: opts.google_folder || "",
    })
      .then((value) => {
        if (active) setPreview(value);
      })
      .catch((error) => {
        if (active) setPreviewError(error.message);
      })
      .finally(() => {
        if (active) setPreviewLoading(false);
      });
    return () => {
      active = false;
    };
  }, [
    !!config,
    opts.google_account,
    opts.google_folder,
    previewVersion,
    running,
  ]);

  useEffect(() => {
    if (sub === "settings" && pendingAnchor) {
      const timer = setTimeout(() => {
        const target = document.getElementById(pendingAnchor);
        target?.scrollIntoView?.({ behavior: "smooth", block: "start" });
        setPendingAnchor("");
      }, 60);
      return () => clearTimeout(timer);
    }
  }, [sub, pendingAnchor]);

  const currentCampaignsFp = fingerprint({
    participants: participants.map(({ realName, handles, discordId }) => ({
      realName,
      handles,
      discordId,
    })),
    campaigns: campaigns.map(({ id: _id, playersList, ...rest }) => ({
      ...rest,
      playersList: playersList.map(({ player, character }) => ({
        player,
        character,
      })),
    })),
  });

  const jsonParsed = campaignsJsonMode ? parseJsonWithLine(editor) : null;
  const campaignsDirty = campaignsJsonMode
    ? editor !== original
    : currentCampaignsFp !== savedCampaignsFp;

  const integrationsDirty = config
    ? fingerprint({ outputs: config.outputs || {}, integrations: opts }) !==
      savedOptions
    : false;
  const settingsDirty = settingsDraft
    ? fingerprint(settingsDraft) !== savedSettingsFp ||
      (!!ModelSettingsSlot && integrationsDirty)
    : false;

  const hasUnsavedInCurrentTab =
    (sub === "campaigns" && campaignsDirty) ||
    (sub === "settings" && settingsDirty);

  useEffect(() => {
    if (!hasUnsavedInCurrentTab) return;
    const handler = (event) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [hasUnsavedInCurrentTab]);

  async function start(task, data = {}) {
    const res = await call("start", {
      task,
      monitor: task === "process" && monitor,
      shutdown_after: task === "process" && shutdownAfter,
      ...data,
    });
    setLogs("");
    setResult(null);
    setPipeline({ stages: [], artifacts: [] });
    watch(res.job);
  }

  function discardCurrentTab() {
    if (sub === "campaigns" && config) {
      setEditor(original);
      setParticipants(
        buildParticipantsList(
          config.nomes_reais || {},
          config.discord_users || {},
        ),
      );
      setCampaigns(buildCampaignsList(config.campaign_details || {}));
      setCampaignErrors({ errors: [], fieldErrors: {} });
      setJsonSwitchError("");
    }
    if (sub === "settings" && config) {
      setSettingsDraft(buildSettingsDraft(config));
      setSettingsErrors({ errors: [], fieldErrors: {} });
    }
  }

  async function saveCampaignsTab() {
    if (campaignsJsonMode) {
      const parsed = parseJsonWithLine(editor);
      if (!parsed.ok) return false;
      setSavingCampaigns(true);
      try {
        await call("save-config", { value: parsed.value });
        const fresh = await call("config");
        syncFromConfig(fresh, channels);
        notify("Campanhas salvas.", "success");
        return true;
      } catch (err) {
        notify(
          `Não foi possível salvar. Nada foi alterado. ${err?.message || ""}`.trim(),
          "error",
        );
        return false;
      } finally {
        setSavingCampaigns(false);
      }
    }

    const pVal = validateParticipants(participants);
    const cVal = validateCampaigns(campaigns);
    const combinedErrors = [...pVal.errors, ...cVal.errors];
    const combinedFieldErrors = { ...pVal.fieldErrors, ...cVal.fieldErrors };
    setCampaignErrors({
      errors: combinedErrors,
      fieldErrors: combinedFieldErrors,
    });
    if (combinedErrors.length > 0) {
      const firstId = combinedErrors[0].fieldId;
      const campMatch = /^campaign-[^-]+-(\d+)/.exec(firstId);
      if (campMatch) {
        const idx = Number(campMatch[1]);
        const item = campaigns[idx];
        if (item) {
          setExpandedCampaigns((old) => ({ ...old, [item.id]: true }));
        }
      }
      setTimeout(() => focusField(firstId), 30);
      return false;
    }

    const { nomes_reais, discord_users } = participantsToConfig(participants);
    const campaign_details = campaignsListToObject(campaigns);
    const value = {
      ...extraCampaignRootKeys(config),
      nomes_reais,
      discord_users,
      campaign_details,
      ...(config.publication ? { publication: config.publication } : {}),
      ...(config.processing ? { processing: config.processing } : {}),
      ...(config.audio ? { audio: config.audio } : {}),
    };

    setSavingCampaigns(true);
    try {
      await call("save-config", { value });
      const fresh = await call("config");
      syncFromConfig(fresh, channels);
      notify("Campanhas salvas.", "success");
      return true;
    } catch (err) {
      notify(
        `Não foi possível salvar. Nada foi alterado. ${err?.message || ""}`.trim(),
        "error",
      );
      return false;
    } finally {
      setSavingCampaigns(false);
    }
  }

  async function saveSettingsTab() {
    const validated = validateSettingsDraft(settingsDraft);
    setSettingsErrors({
      errors: validated.errors,
      fieldErrors: validated.fieldErrors,
    });
    if (!validated.ok) {
      setTimeout(() => focusField(validated.errors[0].fieldId), 30);
      return false;
    }

    setSavingSettings(true);
    try {
      const payload = { ...validated.payload };
      if (ModelSettingsSlot && integrationsDirty) {
        payload.integrations = opts;
      }
      await call("save-settings", payload);
      const fresh = await call("config");
      syncFromConfig(fresh, channels);
      notify("Configurações salvas.", "success");
      return true;
    } catch (err) {
      notify(
        `Não foi possível salvar. Nada foi alterado. ${err?.message || ""}`.trim(),
        "error",
      );
      return false;
    } finally {
      setSavingSettings(false);
    }
  }

  const changeSub = (nextSub, anchor = "") => {
    if (nextSub === sub) {
      if (anchor) setPendingAnchor(anchor);
      return;
    }
    if (hasUnsavedInCurrentTab) {
      setLeaveModal({ nextSub, anchor });
      return;
    }
    if (anchor) setPendingAnchor(anchor);
    navigate({ ...route, sub: nextSub });
  };

  if (sub === "about") {
    return (
      <About>
        <Text>
          Escolha a origem das gravações, os arquivos de saída, as integrações e
          as campanhas. Em Configurações ficam publicação, processamento, áudio
          e opções avançadas. O app usa o fuso horário do computador. Processar
          sessões usa a PIA local com Whisper medium e publica os arquivos no
          armazenamento escolhido.
        </Text>
      </About>
    );
  }

  if (configLoading && !config) {
    return (
      <Stack gap="md">
        <Text>Carregando Podcast Automation…</Text>
        <Skeleton height={80} radius="md" />
        <Skeleton height={160} radius="md" />
      </Stack>
    );
  }

  if (configError || !config) {
    return (
      <Paper withBorder p="lg">
        <Stack gap="sm">
          <Group gap="xs">
            <AlertTriangle size={20} color="var(--mantine-color-red-5)" />
            <Title order={4}>
              Não foi possível carregar as configurações do Podcast Automation.
            </Title>
          </Group>
          {configError && (
            <Text size="sm" c="dimmed">
              {configError}
            </Text>
          )}
          <Group>
            <Button onClick={loadAll}>Tentar novamente</Button>
          </Group>
        </Stack>
      </Paper>
    );
  }

  const appSettings = config.app_settings || APP_SETTINGS_DEFAULTS;
  const appDefaults = config.app_defaults || {};
  const defaultAppSettings = {
    ...APP_SETTINGS_DEFAULTS,
    ...(appDefaults.app_settings || {}),
  };
  const defaultAudio = {
    ...AUDIO_DEFAULTS,
    ...(appDefaults.audio || {}),
  };
  const driveProcess = appSettings.DRIVE_PROCESS !== false;
  const realNamesOptions = Array.from(
    new Set([
      ...participants.map((p) => p.realName.trim()).filter(Boolean),
      ...campaigns.map((c) => c.narrator.trim()).filter(Boolean),
    ]),
  );

  const tzInfo = config.timezone || {};

  return (
    <Stack gap="lg">
      <Group>
        <Nav
          active={sub === "principal"}
          onClick={() => changeSub("principal")}
        >
          Principal
        </Nav>
        <Nav
          active={sub === "campaigns"}
          onClick={() => changeSub("campaigns")}
        >
          Campanhas
        </Nav>
        <Nav active={sub === "settings"} onClick={() => changeSub("settings")}>
          Configurações
        </Nav>
        <Nav active={sub === "about"} onClick={() => changeSub("about")}>
          Sobre
        </Nav>
      </Group>

      {sub === "campaigns" ? (
        <Stack gap="lg">
          <Group justify="space-between" align="center">
            <Text size="sm" c="dimmed">
              Campanhas, participantes e regras de publicação
            </Text>
            <Button
              variant="subtle"
              size="xs"
              onClick={() => {
                if (!campaignsJsonMode) {
                  const { nomes_reais, discord_users } =
                    participantsToConfig(participants);
                  const campaign_details = campaignsListToObject(campaigns);
                  const nextObj = {
                    ...extraCampaignRootKeys(config),
                    nomes_reais,
                    discord_users,
                    campaign_details,
                    ...(config.publication
                      ? { publication: config.publication }
                      : {}),
                    ...(config.processing
                      ? { processing: config.processing }
                      : {}),
                    ...(config.audio ? { audio: config.audio } : {}),
                  };
                  setEditor(JSON.stringify(nextObj, null, 2));
                  setJsonSwitchError("");
                  setCampaignsJsonMode(true);
                } else {
                  const parsed = parseJsonWithLine(editor);
                  if (!parsed.ok) {
                    setJsonSwitchError(
                      "Corrija o JSON para voltar ao formulário.",
                    );
                    return;
                  }
                  setJsonSwitchError("");
                  setParticipants(
                    buildParticipantsList(
                      parsed.value.nomes_reais || {},
                      parsed.value.discord_users || {},
                    ),
                  );
                  setCampaigns(
                    buildCampaignsList(parsed.value.campaign_details || {}),
                  );
                  setCampaignsJsonMode(false);
                }
              }}
            >
              {campaignsJsonMode
                ? "Voltar ao formulário"
                : "Editar como JSON (avançado)"}
            </Button>
          </Group>

          {campaignsJsonMode ? (
            <Paper withBorder p="lg">
              <Stack gap="sm">
                <Text size="sm" c="dimmed">
                  Modo avançado. Chaves que o formulário não conhece são
                  mantidas.
                </Text>
                {(jsonSwitchError || (jsonParsed && !jsonParsed.ok)) && (
                  <Alert color="red" title="Erro no JSON">
                    {jsonSwitchError || jsonParsed?.error}
                  </Alert>
                )}
                <Textarea
                  id="config"
                  className="campaign-editor"
                  autosize
                  minRows={18}
                  value={editor}
                  onChange={(event) => {
                    setEditor(event.target.value);
                    if (jsonSwitchError) setJsonSwitchError("");
                  }}
                />
                <Group mt="xs">
                  <Button
                    id="save-config"
                    loading={savingCampaigns}
                    disabled={
                      editor === original ||
                      savingCampaigns ||
                      (jsonParsed && !jsonParsed.ok)
                    }
                    onClick={saveCampaignsTab}
                  >
                    Salvar campanhas
                  </Button>
                  <Icon
                    icon={Undo2}
                    label="Desfazer mudanças"
                    disabled={editor === original || savingCampaigns}
                    onClick={() => {
                      setEditor(original);
                      setJsonSwitchError("");
                    }}
                  />
                </Group>
              </Stack>
            </Paper>
          ) : (
            <>
              {campaignErrors.errors.length > 0 && (
                <Alert color="red" title="Corrija os campos antes de salvar">
                  <Text size="sm" mb="xs">
                    Corrija {campaignErrors.errors.length} campo(s) destacado(s)
                    antes de salvar.
                  </Text>
                  <Stack gap={4}>
                    {campaignErrors.errors.map((err, idx) => (
                      <Anchor
                        key={err.fieldId + idx}
                        size="sm"
                        component="button"
                        type="button"
                        onClick={() => focusField(err.fieldId)}
                      >
                        {err.message}
                      </Anchor>
                    ))}
                  </Stack>
                </Alert>
              )}

              <Paper withBorder p="lg">
                <Group justify="space-between" mb="xs">
                  <div>
                    <Title order={4}>Participantes</Title>
                    <Text size="sm" c="dimmed">
                      Liga os usuários do Discord ao nome real usado nas
                      transcrições e nas menções.
                    </Text>
                  </div>
                  <Button
                    size="xs"
                    variant="light"
                    leftSection={<Plus size={14} />}
                    onClick={() =>
                      setParticipants((old) => [
                        ...old,
                        {
                          id: nextUid("part"),
                          realName: "",
                          handles: [],
                          discordId: "",
                        },
                      ])
                    }
                  >
                    Adicionar participante
                  </Button>
                </Group>

                {participants.length === 0 ? (
                  <Stack gap="xs" mt="sm">
                    <Text size="sm" c="dimmed">
                      Nenhum participante cadastrado. Adicione quem aparece nas
                      gravações para mostrar nomes reais nas transcrições.
                    </Text>
                    <Group>
                      <Button
                        size="xs"
                        leftSection={<Plus size={14} />}
                        onClick={() =>
                          setParticipants([
                            {
                              id: nextUid("part"),
                              realName: "",
                              handles: [],
                              discordId: "",
                            },
                          ])
                        }
                      >
                        Adicionar participante
                      </Button>
                    </Group>
                  </Stack>
                ) : (
                  <Table mt="sm" verticalSpacing="xs">
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>Nome real</Table.Th>
                        <Table.Th>Usuários do Discord</Table.Th>
                        <Table.Th>
                          ID do Discord para menções (opcional)
                        </Table.Th>
                        <Table.Th w={44} />
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {participants.map((person, index) => (
                        <Table.Tr key={person.id}>
                          <Table.Td>
                            <TextInput
                              id={`participant-name-${index}`}
                              aria-label="Nome real"
                              value={person.realName}
                              error={
                                campaignErrors.fieldErrors[
                                  `participant-name-${index}`
                                ]
                              }
                              onChange={(event) => {
                                const val = event.target.value;
                                setParticipants((old) =>
                                  old.map((p, i) =>
                                    i === index ? { ...p, realName: val } : p,
                                  ),
                                );
                              }}
                            />
                          </Table.Td>
                          <Table.Td>
                            <TagsInput
                              id={`participant-handles-${index}`}
                              aria-label="Usuários do Discord"
                              placeholder="Digite e pressione Enter"
                              value={person.handles}
                              error={
                                campaignErrors.fieldErrors[
                                  `participant-handles-${index}`
                                ]
                              }
                              onChange={(val) =>
                                setParticipants((old) =>
                                  old.map((p, i) =>
                                    i === index ? { ...p, handles: val } : p,
                                  ),
                                )
                              }
                            />
                          </Table.Td>
                          <Table.Td>
                            <TextInput
                              id={`participant-id-${index}`}
                              aria-label="ID do Discord para menções"
                              placeholder="Somente números"
                              value={person.discordId}
                              error={
                                campaignErrors.fieldErrors[
                                  `participant-id-${index}`
                                ]
                              }
                              onChange={(event) => {
                                const val = event.target.value;
                                setParticipants((old) =>
                                  old.map((p, i) =>
                                    i === index ? { ...p, discordId: val } : p,
                                  ),
                                );
                              }}
                            />
                          </Table.Td>
                          <Table.Td>
                            <Icon
                              icon={Trash2}
                              label="Remover participante"
                              confirm
                              danger
                              onClick={() =>
                                setParticipants((old) =>
                                  old.filter((_, i) => i !== index),
                                )
                              }
                            />
                          </Table.Td>
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                )}
              </Paper>

              <Paper withBorder p="lg">
                <Group justify="space-between" mb="md">
                  <Title order={4}>Campanhas</Title>
                  <Button
                    size="xs"
                    variant="light"
                    leftSection={<Plus size={14} />}
                    onClick={() => {
                      const newId = nextUid("camp");
                      setCampaigns((old) => [
                        ...old,
                        {
                          id: newId,
                          narrator: "",
                          Campanha: "",
                          rss_key: "",
                          title: "",
                          description: "",
                          link: "",
                          author: "",
                          explicit: false,
                          closed: false,
                          playersList: [],
                          extra: {},
                        },
                      ]);
                      setExpandedCampaigns((old) => ({
                        ...old,
                        [newId]: true,
                      }));
                    }}
                  >
                    Adicionar campanha
                  </Button>
                </Group>

                {campaigns.length === 0 ? (
                  <Stack gap="xs">
                    <Text size="sm" c="dimmed">
                      Nenhuma campanha cadastrada. Adicione a primeira para
                      publicar episódios no feed.
                    </Text>
                    <Group>
                      <Button
                        size="xs"
                        leftSection={<Plus size={14} />}
                        onClick={() => {
                          const newId = nextUid("camp");
                          setCampaigns([
                            {
                              id: newId,
                              narrator: "",
                              Campanha: "",
                              rss_key: "",
                              title: "",
                              description: "",
                              link: "",
                              author: "",
                              explicit: false,
                              closed: false,
                              playersList: [],
                              extra: {},
                            },
                          ]);
                          setExpandedCampaigns({ [newId]: true });
                        }}
                      >
                        Adicionar campanha
                      </Button>
                    </Group>
                  </Stack>
                ) : (
                  <Stack gap="sm">
                    {campaigns.map((item, index) => {
                      const isOpen = !!expandedCampaigns[item.id];
                      const hasCardError = Object.keys(
                        campaignErrors.fieldErrors,
                      ).some(
                        (k) =>
                          k.startsWith(`campaign-`) && k.includes(`-${index}`),
                      );
                      const selectData = Array.from(
                        new Set([
                          ...realNamesOptions,
                          ...(item.narrator ? [item.narrator] : []),
                        ]),
                      );
                      return (
                        <Paper
                          key={item.id}
                          withBorder
                          p="md"
                          style={
                            hasCardError
                              ? { borderColor: "var(--mantine-color-red-6)" }
                              : undefined
                          }
                        >
                          <Group justify="space-between">
                            <Group
                              gap="xs"
                              style={{ cursor: "pointer", flex: 1 }}
                              onClick={() =>
                                setExpandedCampaigns((old) => ({
                                  ...old,
                                  [item.id]: !isOpen,
                                }))
                              }
                            >
                              {isOpen ? (
                                <ChevronDown size={16} />
                              ) : (
                                <ChevronRight size={16} />
                              )}
                              <Text fw={600}>
                                {item.Campanha || "Nova campanha"} · Narrador:{" "}
                                {item.narrator || "—"}
                              </Text>
                              {item.closed && (
                                <Badge color="gray" size="sm">
                                  Encerrada
                                </Badge>
                              )}
                            </Group>
                            <Button
                              size="xs"
                              variant="subtle"
                              color="red"
                              onClick={() =>
                                setRemoveCampaignModal({
                                  index,
                                  name:
                                    item.Campanha ||
                                    item.narrator ||
                                    "sem nome",
                                })
                              }
                            >
                              Remover campanha
                            </Button>
                          </Group>

                          <Collapse in={isOpen}>
                            <Stack gap="sm" mt="md">
                              <SimpleGrid cols={{ base: 1, sm: 2 }}>
                                <Select
                                  id={`campaign-narrator-${index}`}
                                  label="Narrador"
                                  searchable
                                  data={selectData}
                                  value={item.narrator || null}
                                  error={
                                    campaignErrors.fieldErrors[
                                      `campaign-narrator-${index}`
                                    ]
                                  }
                                  onChange={(val) =>
                                    setCampaigns((old) =>
                                      old.map((c, i) =>
                                        i === index
                                          ? { ...c, narrator: val || "" }
                                          : c,
                                      ),
                                    )
                                  }
                                />
                                <TextInput
                                  id={`campaign-name-${index}`}
                                  label="Nome da campanha"
                                  description="Nome da pasta das sessões."
                                  value={item.Campanha}
                                  error={
                                    campaignErrors.fieldErrors[
                                      `campaign-name-${index}`
                                    ]
                                  }
                                  onChange={(event) => {
                                    const val = event.target.value;
                                    setCampaigns((old) =>
                                      old.map((c, i) => {
                                        if (i !== index) return c;
                                        const suggestRss =
                                          !c.rss_key ||
                                          c.rss_key ===
                                            `campaigns/${c.Campanha}/rss.xml`;
                                        return {
                                          ...c,
                                          Campanha: val,
                                          rss_key:
                                            suggestRss && val
                                              ? `campaigns/${val}/rss.xml`
                                              : c.rss_key,
                                        };
                                      }),
                                    );
                                  }}
                                />
                                <TextInput
                                  id={`campaign-rss-${index}`}
                                  label="Caminho do feed"
                                  description="Precisa terminar em /rss.xml."
                                  value={item.rss_key}
                                  error={
                                    campaignErrors.fieldErrors[
                                      `campaign-rss-${index}`
                                    ]
                                  }
                                  onChange={(event) => {
                                    const val = event.target.value;
                                    setCampaigns((old) =>
                                      old.map((c, i) =>
                                        i === index
                                          ? { ...c, rss_key: val }
                                          : c,
                                      ),
                                    );
                                  }}
                                />
                                <TextInput
                                  label="Título do podcast"
                                  value={item.title}
                                  onChange={(event) => {
                                    const val = event.target.value;
                                    setCampaigns((old) =>
                                      old.map((c, i) =>
                                        i === index ? { ...c, title: val } : c,
                                      ),
                                    );
                                  }}
                                />
                                <TextInput
                                  id={`campaign-link-${index}`}
                                  label="Link"
                                  value={item.link}
                                  error={
                                    campaignErrors.fieldErrors[
                                      `campaign-link-${index}`
                                    ]
                                  }
                                  onChange={(event) => {
                                    const val = event.target.value;
                                    setCampaigns((old) =>
                                      old.map((c, i) =>
                                        i === index ? { ...c, link: val } : c,
                                      ),
                                    );
                                  }}
                                />
                                <TextInput
                                  label="Autor"
                                  value={item.author}
                                  onChange={(event) => {
                                    const val = event.target.value;
                                    setCampaigns((old) =>
                                      old.map((c, i) =>
                                        i === index ? { ...c, author: val } : c,
                                      ),
                                    );
                                  }}
                                />
                              </SimpleGrid>

                              <Textarea
                                label="Descrição"
                                autosize
                                minRows={2}
                                value={item.description}
                                onChange={(event) => {
                                  const val = event.target.value;
                                  setCampaigns((old) =>
                                    old.map((c, i) =>
                                      i === index
                                        ? { ...c, description: val }
                                        : c,
                                    ),
                                  );
                                }}
                              />

                              <Group gap="xl">
                                <Switch
                                  label="Conteúdo explícito"
                                  checked={!!item.explicit}
                                  onChange={(event) => {
                                    const checked = event.currentTarget.checked;
                                    setCampaigns((old) =>
                                      old.map((c, i) =>
                                        i === index
                                          ? { ...c, explicit: checked }
                                          : c,
                                      ),
                                    );
                                  }}
                                />
                                <Switch
                                  label="Campanha encerrada"
                                  description="Campanhas encerradas param de receber episódios."
                                  checked={!!item.closed}
                                  onChange={(event) => {
                                    const checked = event.currentTarget.checked;
                                    setCampaigns((old) =>
                                      old.map((c, i) =>
                                        i === index
                                          ? { ...c, closed: checked }
                                          : c,
                                      ),
                                    );
                                  }}
                                />
                              </Group>

                              <Stack gap="xs" mt="xs">
                                <Group justify="space-between">
                                  <Text fw={600} size="sm">
                                    Jogadores e personagens
                                  </Text>
                                  <Button
                                    size="xs"
                                    variant="light"
                                    leftSection={<Plus size={14} />}
                                    onClick={() =>
                                      setCampaigns((old) =>
                                        old.map((c, i) =>
                                          i === index
                                            ? {
                                                ...c,
                                                playersList: [
                                                  ...c.playersList,
                                                  {
                                                    id: nextUid("player"),
                                                    player: "",
                                                    character: "",
                                                  },
                                                ],
                                              }
                                            : c,
                                        ),
                                      )
                                    }
                                  >
                                    Adicionar jogador
                                  </Button>
                                </Group>
                                {campaignErrors.fieldErrors[
                                  `campaign-players-${index}`
                                ] && (
                                  <Text
                                    id={`campaign-players-${index}`}
                                    size="xs"
                                    c="red"
                                  >
                                    {
                                      campaignErrors.fieldErrors[
                                        `campaign-players-${index}`
                                      ]
                                    }
                                  </Text>
                                )}
                                {item.playersList.length === 0 ? (
                                  <Text size="sm" c="dimmed">
                                    Nenhum jogador nesta campanha.
                                  </Text>
                                ) : (
                                  <Table verticalSpacing="xs">
                                    <Table.Thead>
                                      <Table.Tr>
                                        <Table.Th>Jogador</Table.Th>
                                        <Table.Th>Personagem</Table.Th>
                                        <Table.Th w={44} />
                                      </Table.Tr>
                                    </Table.Thead>
                                    <Table.Tbody>
                                      {item.playersList.map((row, pIndex) => {
                                        const playerData = Array.from(
                                          new Set([
                                            ...realNamesOptions,
                                            ...(row.player ? [row.player] : []),
                                          ]),
                                        );
                                        return (
                                          <Table.Tr key={row.id}>
                                            <Table.Td>
                                              <Select
                                                id={`campaign-player-${index}-${pIndex}`}
                                                aria-label="Jogador"
                                                searchable
                                                data={playerData}
                                                value={row.player || null}
                                                error={
                                                  campaignErrors.fieldErrors[
                                                    `campaign-player-${index}-${pIndex}`
                                                  ]
                                                }
                                                onChange={(val) =>
                                                  setCampaigns((old) =>
                                                    old.map((c, i) =>
                                                      i === index
                                                        ? {
                                                            ...c,
                                                            playersList:
                                                              c.playersList.map(
                                                                (pl, pi) =>
                                                                  pi === pIndex
                                                                    ? {
                                                                        ...pl,
                                                                        player:
                                                                          val ||
                                                                          "",
                                                                      }
                                                                    : pl,
                                                              ),
                                                          }
                                                        : c,
                                                    ),
                                                  )
                                                }
                                              />
                                            </Table.Td>
                                            <Table.Td>
                                              <TextInput
                                                id={`campaign-character-${index}-${pIndex}`}
                                                aria-label="Personagem"
                                                value={row.character}
                                                error={
                                                  campaignErrors.fieldErrors[
                                                    `campaign-character-${index}-${pIndex}`
                                                  ]
                                                }
                                                onChange={(event) => {
                                                  const val =
                                                    event.target.value;
                                                  setCampaigns((old) =>
                                                    old.map((c, i) =>
                                                      i === index
                                                        ? {
                                                            ...c,
                                                            playersList:
                                                              c.playersList.map(
                                                                (pl, pi) =>
                                                                  pi === pIndex
                                                                    ? {
                                                                        ...pl,
                                                                        character:
                                                                          val,
                                                                      }
                                                                    : pl,
                                                              ),
                                                          }
                                                        : c,
                                                    ),
                                                  );
                                                }}
                                              />
                                            </Table.Td>
                                            <Table.Td>
                                              <Icon
                                                icon={Trash2}
                                                label="Remover jogador"
                                                danger
                                                onClick={() =>
                                                  setCampaigns((old) =>
                                                    old.map((c, i) =>
                                                      i === index
                                                        ? {
                                                            ...c,
                                                            playersList:
                                                              c.playersList.filter(
                                                                (_, pi) =>
                                                                  pi !== pIndex,
                                                              ),
                                                          }
                                                        : c,
                                                    ),
                                                  )
                                                }
                                              />
                                            </Table.Td>
                                          </Table.Tr>
                                        );
                                      })}
                                    </Table.Tbody>
                                  </Table>
                                )}
                              </Stack>
                            </Stack>
                          </Collapse>
                        </Paper>
                      );
                    })}
                  </Stack>
                )}
              </Paper>

              <Paper withBorder p="md">
                <Group justify="space-between" align="center">
                  <Text size="sm" c={campaignsDirty ? "yellow" : "dimmed"}>
                    {campaignsDirty
                      ? "Você tem alterações não salvas."
                      : "Nenhuma alteração pendente."}
                  </Text>
                  <Group>
                    <Button
                      variant="subtle"
                      disabled={!campaignsDirty || savingCampaigns}
                      onClick={discardCurrentTab}
                    >
                      Descartar alterações
                    </Button>
                    <Button
                      id="save-config"
                      loading={savingCampaigns}
                      disabled={!campaignsDirty || savingCampaigns}
                      onClick={saveCampaignsTab}
                    >
                      Salvar campanhas
                    </Button>
                  </Group>
                </Group>
              </Paper>
            </>
          )}
        </Stack>
      ) : sub === "settings" && settingsDraft ? (
        <Stack gap="lg">
          {settingsErrors.errors.length > 0 && (
            <Alert color="red" title="Corrija os campos antes de salvar">
              <Text size="sm" mb="xs">
                Corrija {settingsErrors.errors.length} campo(s) destacado(s)
                antes de salvar.
              </Text>
              <Stack gap={4}>
                {settingsErrors.errors.map((err, idx) => (
                  <Anchor
                    key={err.fieldId + idx}
                    size="sm"
                    component="button"
                    type="button"
                    onClick={() => focusField(err.fieldId)}
                  >
                    {err.message}
                  </Anchor>
                ))}
              </Stack>
            </Alert>
          )}

          {/* 3.1.1 Fuso horário */}
          <Paper withBorder p="lg" id="fuso-horario">
            <Title order={4} mb="xs">
              Fuso horário
            </Title>
            {tzInfo.detected === false ? (
              <Alert color="yellow" mb="xs">
                Não foi possível identificar o fuso horário do sistema. Datas
                exibidas em UTC.
              </Alert>
            ) : (
              <Text size="sm">
                Fuso horário detectado:{" "}
                <strong>{tzInfo.label || "UTC (UTC+00:00)"}</strong>
              </Text>
            )}
            <Text size="xs" c="dimmed" mt="xs">
              Usado nas datas exibidas, nos logs e nos horários do
              processamento. Para mudar, ajuste o fuso horário do sistema
              operacional.
            </Text>
            <Text size="xs" c="dimmed" mt={4}>
              Episódios já publicados mantêm a data original no feed RSS.
            </Text>
            {tzInfo.legacy_tz && (
              <Text size="xs" c="dimmed" mt="xs">
                A configuração antiga de fuso ({tzInfo.legacy_tz}) não é mais
                usada. O app segue o fuso do computador.
              </Text>
            )}
          </Paper>

          {/* 3.1.2 Origem das gravações */}
          <Paper withBorder p="lg" id="origem">
            <Title order={4} mb="md">
              Origem das gravações
            </Title>
            <Stack gap="md">
              <div>
                <Text size="sm" fw={500} mb={4}>
                  Origem das gravações
                </Text>
                <SegmentedControl
                  disabled={savingSettings}
                  value={
                    settingsDraft.app_settings.DRIVE_PROCESS ? "true" : "false"
                  }
                  onChange={(val) =>
                    setSettingsDraft((old) => ({
                      ...old,
                      app_settings: {
                        ...old.app_settings,
                        DRIVE_PROCESS: val === "true",
                      },
                    }))
                  }
                  data={[
                    { label: "Google Drive", value: "true" },
                    { label: "Pasta local", value: "false" },
                  ]}
                />
                <Text size="xs" c="dimmed" mt={4}>
                  Google Drive usa a conta e a pasta escolhidas na aba
                  Principal.
                </Text>
              </div>

              <div>
                <Group gap="xs" mb={4}>
                  <Text
                    component="label"
                    htmlFor="setting-LOCAL_DRIVE_FOLDER"
                    size="sm"
                    fw={500}
                  >
                    Pasta local de gravações
                  </Text>
                  {settingsDraft.app_settings.LOCAL_DRIVE_FOLDER ===
                    defaultAppSettings.LOCAL_DRIVE_FOLDER && (
                    <Badge size="xs" variant="light" color="gray">
                      Padrão
                    </Badge>
                  )}
                </Group>
                <Text size="xs" c="dimmed" mb={6}>
                  Pasta onde ficam os arquivos .zip das sessões.
                  {settingsDraft.app_settings.DRIVE_PROCESS
                    ? " Ativo só com a origem Pasta local."
                    : ""}
                </Text>
                <Group wrap="nowrap" align="start">
                  <TextInput
                    id="setting-LOCAL_DRIVE_FOLDER"
                    className="grow"
                    disabled={
                      savingSettings || settingsDraft.app_settings.DRIVE_PROCESS
                    }
                    value={settingsDraft.app_settings.LOCAL_DRIVE_FOLDER}
                    error={
                      settingsErrors.fieldErrors["setting-LOCAL_DRIVE_FOLDER"]
                    }
                    onChange={(event) => {
                      const val = event.target.value;
                      setSettingsDraft((old) => ({
                        ...old,
                        app_settings: {
                          ...old.app_settings,
                          LOCAL_DRIVE_FOLDER: val,
                        },
                      }));
                    }}
                  />
                  <Button
                    variant="light"
                    leftSection={<FolderOpen size={16} />}
                    loading={pickingFolder === "LOCAL_DRIVE_FOLDER"}
                    disabled={
                      savingSettings || settingsDraft.app_settings.DRIVE_PROCESS
                    }
                    onClick={safe(async () => {
                      setPickingFolder("LOCAL_DRIVE_FOLDER");
                      try {
                        const res = await api("/native", {
                          action: "choose-path",
                          payload: { mode: "directory" },
                        });
                        if (res?.path) {
                          setSettingsDraft((old) => ({
                            ...old,
                            app_settings: {
                              ...old.app_settings,
                              LOCAL_DRIVE_FOLDER: res.path,
                            },
                          }));
                          setFolderFeedback({
                            path: "LOCAL_DRIVE_FOLDER",
                            message: "Pasta definida.",
                          });
                          setTimeout(
                            () => setFolderFeedback({ path: "", message: "" }),
                            3000,
                          );
                        }
                      } finally {
                        setPickingFolder("");
                      }
                    })}
                  >
                    Escolher pasta…
                  </Button>
                  <Icon
                    icon={RotateCcw}
                    label="Restaurar padrão"
                    disabled={
                      savingSettings || settingsDraft.app_settings.DRIVE_PROCESS
                    }
                    onClick={() =>
                      setSettingsDraft((old) => ({
                        ...old,
                        app_settings: {
                          ...old.app_settings,
                          LOCAL_DRIVE_FOLDER:
                            defaultAppSettings.LOCAL_DRIVE_FOLDER,
                        },
                      }))
                    }
                  />
                </Group>
                {!settingsDraft.app_settings.LOCAL_DRIVE_FOLDER && (
                  <Text size="xs" c="dimmed" mt={4}>
                    Nenhuma pasta escolhida. Será usada a pasta padrão{" "}
                    <code>data/local-drive</code>.
                  </Text>
                )}
                {folderFeedback.path === "LOCAL_DRIVE_FOLDER" &&
                  folderFeedback.message && (
                    <Text size="xs" c="green" mt={4}>
                      {folderFeedback.message}
                    </Text>
                  )}
              </div>
            </Stack>
          </Paper>

          {/* 3.1.3 Processamento e automação */}
          <Paper withBorder p="lg" id="processamento">
            <Title order={4} mb="md">
              Processamento e automação
            </Title>
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <TextInput
                id="setting-POLL_INTERVAL_SECONDS"
                label="Intervalo entre verificações"
                rightSection={
                  <Text size="xs" c="dimmed" pr="xs">
                    s
                  </Text>
                }
                description={`No modo contínuo, tempo de espera antes de procurar novas sessões. ${formatMinutesHelp(settingsDraft.app_settings.POLL_INTERVAL_SECONDS)}`}
                disabled={savingSettings}
                value={settingsDraft.app_settings.POLL_INTERVAL_SECONDS}
                error={
                  settingsErrors.fieldErrors["setting-POLL_INTERVAL_SECONDS"]
                }
                onChange={(event) => {
                  const val = event.target.value;
                  setSettingsDraft((old) => ({
                    ...old,
                    app_settings: {
                      ...old.app_settings,
                      POLL_INTERVAL_SECONDS: val,
                    },
                  }));
                }}
              />
              <TextInput
                id="setting-processing-minimum_session_seconds"
                label="Duração mínima da sessão"
                rightSection={
                  <Text size="xs" c="dimmed" pr="xs">
                    s
                  </Text>
                }
                description={formatMinutesHelp(
                  settingsDraft.processing.minimum_session_seconds,
                )}
                disabled={savingSettings}
                value={settingsDraft.processing.minimum_session_seconds}
                error={
                  settingsErrors.fieldErrors[
                    "setting-processing-minimum_session_seconds"
                  ]
                }
                onChange={(event) => {
                  const val = event.target.value;
                  setSettingsDraft((old) => ({
                    ...old,
                    processing: {
                      ...old.processing,
                      minimum_session_seconds: val,
                    },
                  }));
                }}
              />
              <TextInput
                id="setting-processing-duplicate_max_bytes"
                label="Detecção de duplicatas: tamanho máximo"
                rightSection={
                  <Text size="xs" c="dimmed" pr="xs">
                    bytes
                  </Text>
                }
                description={`Usado para identificar gravações duplicadas. ${formatMegabytesHelp(settingsDraft.processing.duplicate_max_bytes)}`}
                disabled={savingSettings}
                value={settingsDraft.processing.duplicate_max_bytes}
                error={
                  settingsErrors.fieldErrors[
                    "setting-processing-duplicate_max_bytes"
                  ]
                }
                onChange={(event) => {
                  const val = event.target.value;
                  setSettingsDraft((old) => ({
                    ...old,
                    processing: {
                      ...old.processing,
                      duplicate_max_bytes: val,
                    },
                  }));
                }}
              />
              <TextInput
                id="setting-processing-duplicate_max_seconds"
                label="Detecção de duplicatas: duração máxima"
                rightSection={
                  <Text size="xs" c="dimmed" pr="xs">
                    s
                  </Text>
                }
                description={`Usado para identificar gravações duplicadas. ${formatMinutesHelp(settingsDraft.processing.duplicate_max_seconds)}`}
                disabled={savingSettings}
                value={settingsDraft.processing.duplicate_max_seconds}
                error={
                  settingsErrors.fieldErrors[
                    "setting-processing-duplicate_max_seconds"
                  ]
                }
                onChange={(event) => {
                  const val = event.target.value;
                  setSettingsDraft((old) => ({
                    ...old,
                    processing: {
                      ...old.processing,
                      duplicate_max_seconds: val,
                    },
                  }));
                }}
              />
            </SimpleGrid>
          </Paper>

          {/* 3.1.4 Publicação */}
          <Paper withBorder p="lg" id="publicacao">
            <Title order={4} mb="md">
              Publicação
            </Title>
            <Stack gap="md">
              <Switch
                label="Publicar direto na pasta final do RSS"
                description="Quando desligado, os arquivos usam o prefixo de não publicados abaixo."
                disabled={savingSettings}
                checked={settingsDraft.app_settings.PUBLICAR_DIRETO}
                onChange={(event) => {
                  const checked = event.currentTarget.checked;
                  setSettingsDraft((old) => ({
                    ...old,
                    app_settings: {
                      ...old.app_settings,
                      PUBLICAR_DIRETO: checked,
                    },
                  }));
                }}
              />
              <Switch
                label="Ignorar campanhas encerradas ao atualizar feeds"
                description='Campanhas marcadas como "Encerrada" ficam fora da atualização.'
                disabled={savingSettings}
                checked={settingsDraft.app_settings.SKIP_CLOSED}
                onChange={(event) => {
                  const checked = event.currentTarget.checked;
                  setSettingsDraft((old) => ({
                    ...old,
                    app_settings: { ...old.app_settings, SKIP_CLOSED: checked },
                  }));
                }}
              />
              <SimpleGrid cols={{ base: 1, sm: 2 }}>
                <TextInput
                  label="Prefixo de não publicados"
                  disabled={savingSettings}
                  value={settingsDraft.publication.unpublished_prefix}
                  onChange={(event) => {
                    const val = event.target.value;
                    setSettingsDraft((old) => ({
                      ...old,
                      publication: {
                        ...old.publication,
                        unpublished_prefix: val,
                      },
                    }));
                  }}
                />
                <TextInput
                  id="setting-OWNER_EMAIL"
                  label="E-mail do responsável pelo feed"
                  description="Aparece no campo de contato do feed (itunes:email)."
                  disabled={savingSettings}
                  value={settingsDraft.app_settings.OWNER_EMAIL}
                  error={settingsErrors.fieldErrors["setting-OWNER_EMAIL"]}
                  onChange={(event) => {
                    const val = event.target.value;
                    setSettingsDraft((old) => ({
                      ...old,
                      app_settings: { ...old.app_settings, OWNER_EMAIL: val },
                    }));
                  }}
                />
                <TextInput
                  label="Marca"
                  disabled={savingSettings}
                  value={settingsDraft.publication.brand}
                  onChange={(event) => {
                    const val = event.target.value;
                    setSettingsDraft((old) => ({
                      ...old,
                      publication: { ...old.publication, brand: val },
                    }));
                  }}
                />
                <TextInput
                  id="setting-publication-website"
                  label="Site"
                  disabled={savingSettings}
                  value={settingsDraft.publication.website}
                  error={
                    settingsErrors.fieldErrors["setting-publication-website"]
                  }
                  onChange={(event) => {
                    const val = event.target.value;
                    setSettingsDraft((old) => ({
                      ...old,
                      publication: { ...old.publication, website: val },
                    }));
                  }}
                />
                <TextInput
                  label="Direitos autorais"
                  placeholder="Ex.: © seusite.com"
                  disabled={savingSettings}
                  value={settingsDraft.publication.copyright}
                  onChange={(event) => {
                    const val = event.target.value;
                    setSettingsDraft((old) => ({
                      ...old,
                      publication: { ...old.publication, copyright: val },
                    }));
                  }}
                />
                <TextInput
                  label="Gênero"
                  disabled={savingSettings}
                  value={settingsDraft.publication.genre}
                  onChange={(event) => {
                    const val = event.target.value;
                    setSettingsDraft((old) => ({
                      ...old,
                      publication: { ...old.publication, genre: val },
                    }));
                  }}
                />
                <TextInput
                  label="Comentário padrão dos arquivos"
                  disabled={savingSettings}
                  value={settingsDraft.publication.comment}
                  onChange={(event) => {
                    const val = event.target.value;
                    setSettingsDraft((old) => ({
                      ...old,
                      publication: { ...old.publication, comment: val },
                    }));
                  }}
                />
                <TextInput
                  id="setting-publication-language"
                  label="Idioma do feed"
                  description="Código de idioma, como pt-BR."
                  disabled={savingSettings}
                  value={settingsDraft.publication.language}
                  error={
                    settingsErrors.fieldErrors["setting-publication-language"]
                  }
                  onChange={(event) => {
                    const val = event.target.value;
                    setSettingsDraft((old) => ({
                      ...old,
                      publication: { ...old.publication, language: val },
                    }));
                  }}
                />
              </SimpleGrid>
            </Stack>
          </Paper>

          {/* 3.1.5 Áudio e mixagem */}
          <Paper withBorder p="lg" id="audio">
            <Group justify="space-between" mb="md">
              <Title order={4}>Áudio e mixagem</Title>
              <Button
                size="xs"
                variant="subtle"
                disabled={savingSettings}
                onClick={() => setAudioResetModal(true)}
              >
                Restaurar padrões de áudio
              </Button>
            </Group>
            <Stack gap="md">
              <Switch
                label="Remover silêncios"
                disabled={savingSettings}
                checked={settingsDraft.audio.remove_silence}
                onChange={(event) => {
                  const checked = event.currentTarget.checked;
                  setSettingsDraft((old) => ({
                    ...old,
                    audio: { ...old.audio, remove_silence: checked },
                  }));
                }}
              />

              <Text fw={600} size="sm">
                Silêncio
              </Text>
              <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
                {[
                  ["silence_threshold_db", "Limiar de silêncio", "dB"],
                  [
                    "minimum_silence_seconds",
                    "Silêncio mínimo para cortar",
                    "s",
                  ],
                  [
                    "keep_silence_seconds",
                    "Silêncio mantido em cada corte",
                    "s",
                  ],
                  ["fade_seconds", "Fade nos cortes", "s"],
                ].map(([key, label, unit]) => (
                  <TextInput
                    key={key}
                    id={`setting-audio-${key}`}
                    label={label}
                    rightSection={
                      <Text size="xs" c="dimmed" pr="xs">
                        {unit}
                      </Text>
                    }
                    disabled={
                      savingSettings || !settingsDraft.audio.remove_silence
                    }
                    value={settingsDraft.audio[key]}
                    error={settingsErrors.fieldErrors[`setting-audio-${key}`]}
                    onChange={(event) => {
                      const val = event.target.value;
                      setSettingsDraft((old) => ({
                        ...old,
                        audio: { ...old.audio, [key]: val },
                      }));
                    }}
                  />
                ))}
              </SimpleGrid>

              <Text fw={600} size="sm">
                Compressor
              </Text>
              <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
                {[
                  ["compressor_threshold_db", "Compressor · limiar", "dB"],
                  ["compressor_ratio", "Compressor · razão", ": 1"],
                  ["compressor_attack_ms", "Compressor · ataque", "ms"],
                  ["compressor_release_ms", "Compressor · liberação", "ms"],
                ].map(([key, label, unit]) => (
                  <TextInput
                    key={key}
                    id={`setting-audio-${key}`}
                    label={label}
                    rightSection={
                      <Text size="xs" c="dimmed" pr="xs">
                        {unit}
                      </Text>
                    }
                    disabled={savingSettings}
                    value={settingsDraft.audio[key]}
                    error={settingsErrors.fieldErrors[`setting-audio-${key}`]}
                    onChange={(event) => {
                      const val = event.target.value;
                      setSettingsDraft((old) => ({
                        ...old,
                        audio: { ...old.audio, [key]: val },
                      }));
                    }}
                  />
                ))}
              </SimpleGrid>

              <Text fw={600} size="sm">
                Loudness
              </Text>
              <SimpleGrid cols={{ base: 1, sm: 3 }}>
                {[
                  ["loudness_lufs", "Loudness alvo", "LUFS"],
                  ["loudness_range", "Faixa de loudness (LRA)", "LU"],
                  ["true_peak_db", "Pico verdadeiro máximo", "dBTP"],
                ].map(([key, label, unit]) => (
                  <TextInput
                    key={key}
                    id={`setting-audio-${key}`}
                    label={label}
                    rightSection={
                      <Text size="xs" c="dimmed" pr="xs">
                        {unit}
                      </Text>
                    }
                    disabled={savingSettings}
                    value={settingsDraft.audio[key]}
                    error={settingsErrors.fieldErrors[`setting-audio-${key}`]}
                    onChange={(event) => {
                      const val = event.target.value;
                      setSettingsDraft((old) => ({
                        ...old,
                        audio: { ...old.audio, [key]: val },
                      }));
                    }}
                  />
                ))}
              </SimpleGrid>
            </Stack>
          </Paper>

          {/* 3.1.6 Inteligência artificial (Slot da Demanda 0002) */}
          <section
            id="ia"
            data-slot="podcast-model-settings"
            aria-labelledby="podcast-model-settings-title"
            hidden={!ModelSettingsSlot}
          >
            {ModelSettingsSlot &&
              React.createElement(ModelSettingsSlot, {
                config,
                patchIntegrations: patch,
                disabled: savingSettings,
              })}
          </section>

          {/* 3.1.7 Avançado */}
          <Paper withBorder p="lg" id="avancado">
            <Accordion>
              <Accordion.Item value="advanced">
                <Accordion.Control>Avançado</Accordion.Control>
                <Accordion.Panel>
                  <Stack gap="md">
                    <TextInput
                      id="setting-TRANSCRIPTS_FILE"
                      label="Arquivo da página de transcrições"
                      description="Nome do arquivo HTML publicado com as transcrições."
                      disabled={savingSettings}
                      value={settingsDraft.app_settings.TRANSCRIPTS_FILE}
                      error={
                        settingsErrors.fieldErrors["setting-TRANSCRIPTS_FILE"]
                      }
                      onChange={(event) => {
                        const val = event.target.value;
                        setSettingsDraft((old) => ({
                          ...old,
                          app_settings: {
                            ...old.app_settings,
                            TRANSCRIPTS_FILE: val,
                          },
                        }));
                      }}
                    />

                    <div>
                      <Group gap="xs" mb={4}>
                        <Text
                          component="label"
                          htmlFor="setting-FEED_CACHE_DIR"
                          size="sm"
                          fw={500}
                        >
                          Pasta de cache dos feeds
                        </Text>
                        {settingsDraft.app_settings.FEED_CACHE_DIR ===
                          defaultAppSettings.FEED_CACHE_DIR && (
                          <Badge size="xs" variant="light" color="gray">
                            Padrão
                          </Badge>
                        )}
                      </Group>
                      <Group wrap="nowrap" align="start">
                        <TextInput
                          id="setting-FEED_CACHE_DIR"
                          className="grow"
                          disabled={savingSettings}
                          value={settingsDraft.app_settings.FEED_CACHE_DIR}
                          error={
                            settingsErrors.fieldErrors["setting-FEED_CACHE_DIR"]
                          }
                          onChange={(event) => {
                            const val = event.target.value;
                            setSettingsDraft((old) => ({
                              ...old,
                              app_settings: {
                                ...old.app_settings,
                                FEED_CACHE_DIR: val,
                              },
                            }));
                          }}
                        />
                        <Button
                          variant="light"
                          leftSection={<FolderOpen size={16} />}
                          loading={pickingFolder === "FEED_CACHE_DIR"}
                          disabled={savingSettings}
                          onClick={safe(async () => {
                            setPickingFolder("FEED_CACHE_DIR");
                            try {
                              const res = await api("/native", {
                                action: "choose-path",
                                payload: { mode: "directory" },
                              });
                              if (res?.path) {
                                setSettingsDraft((old) => ({
                                  ...old,
                                  app_settings: {
                                    ...old.app_settings,
                                    FEED_CACHE_DIR: res.path,
                                  },
                                }));
                              }
                            } finally {
                              setPickingFolder("");
                            }
                          })}
                        >
                          Escolher pasta…
                        </Button>
                        <Icon
                          icon={RotateCcw}
                          label="Restaurar padrão"
                          disabled={savingSettings}
                          onClick={() =>
                            setSettingsDraft((old) => ({
                              ...old,
                              app_settings: {
                                ...old.app_settings,
                                FEED_CACHE_DIR:
                                  defaultAppSettings.FEED_CACHE_DIR,
                              },
                            }))
                          }
                        />
                      </Group>
                    </div>

                    <Switch
                      label="Sempre reconstruir os feeds do zero"
                      description="Mais lento. Use só para corrigir feeds com problema."
                      disabled={savingSettings}
                      checked={settingsDraft.app_settings.FEED_FORCE_REBUILD}
                      onChange={(event) => {
                        const checked = event.currentTarget.checked;
                        setSettingsDraft((old) => ({
                          ...old,
                          app_settings: {
                            ...old.app_settings,
                            FEED_FORCE_REBUILD: checked,
                          },
                        }));
                      }}
                    />
                  </Stack>
                </Accordion.Panel>
              </Accordion.Item>
            </Accordion>
          </Paper>

          {running && (
            <Alert color="blue">
              Há um processamento em andamento. As novas configurações valem a
              partir da próxima execução.
            </Alert>
          )}

          {settingsDirty && (
            <Paper
              withBorder
              p="md"
              style={{
                position: "sticky",
                bottom: 12,
                zIndex: 10,
                background: "var(--mantine-color-body)",
              }}
            >
              <Group justify="space-between" align="center">
                <Text size="sm" c="yellow">
                  Você tem alterações não salvas.
                </Text>
                <Group>
                  <Button
                    variant="subtle"
                    disabled={savingSettings}
                    onClick={discardCurrentTab}
                  >
                    Descartar alterações
                  </Button>
                  <Button loading={savingSettings} onClick={saveSettingsTab}>
                    Salvar configurações
                  </Button>
                </Group>
              </Group>
            </Paper>
          )}
        </Stack>
      ) : (
        <>
          <Paper withBorder p="lg">
            <Group>
              <Button
                id="process"
                leftSection={<Play size={17} />}
                disabled={running || shutdownPending}
                onClick={safe(() => start("process"))}
              >
                Processar sessões
              </Button>
              <Button
                disabled={running || shutdownPending}
                onClick={() => {
                  setFiles([null, null]);
                  setMerge("srt");
                }}
              >
                Unir SRT
              </Button>
              <Button
                disabled={running || shutdownPending}
                onClick={() => {
                  setFiles([null, null]);
                  setMerge("vtt");
                }}
              >
                Unir VTT
              </Button>
              <Button
                disabled={running || shutdownPending}
                onClick={safe(() => start("rebuild"))}
              >
                Reconstruir feeds
              </Button>
              <Icon
                icon={Square}
                label="Parar tarefa"
                disabled={!running}
                onClick={() => call("stop")}
              />
            </Group>
            <Switch
              mt="md"
              id="monitor-sessions"
              label="Monitorar novas sessões continuamente"
              checked={monitor}
              disabled={running || shutdownPending}
              onChange={(event) => {
                const checked = event.currentTarget.checked;
                setMonitor(checked);
                if (checked) setShutdownAfter(false);
              }}
            />
            <Switch
              mt="md"
              id="shutdown-after-processing"
              label="Desligar o computador ao concluir todos os arquivos"
              description="Somente após concluir sem erros. O desligamento é agendado para 60 segundos depois e pode ser cancelado."
              checked={shutdownAfter}
              disabled={running || shutdownPending}
              onChange={(event) => {
                const checked = event.currentTarget.checked;
                setShutdownAfter(checked);
                if (checked) setMonitor(false);
              }}
            />
            {shutdownPending && (
              <Group mt="md">
                <Text c="yellow">Desligamento agendado.</Text>
                <Button
                  onClick={safe(async () => {
                    await call("cancel-shutdown");
                    setShutdownPending(false);
                  })}
                >
                  Cancelar desligamento
                </Button>
              </Group>
            )}
          </Paper>
          <Paper withBorder p="lg">
            <Group justify="space-between">
              <Title order={4}>
                Gravações pendentes
                {preview?.configured ? ` · ${preview.pending.length}` : ""}
              </Title>
              <Icon
                icon={Search}
                label="Atualizar gravações pendentes"
                disabled={previewLoading}
                onClick={() => setPreviewVersion((value) => value + 1)}
              />
            </Group>
            {previewLoading ? (
              <Text size="sm" c="dimmed" mt="sm">
                Consultando arquivos da pasta…
              </Text>
            ) : previewError ? (
              <Text size="sm" c="red" mt="sm">
                {previewError}
              </Text>
            ) : !preview?.configured ? (
              <Text size="sm" mt="sm">
                {preview?.message || "Selecione a pasta de gravações."}
              </Text>
            ) : (
              <>
                <Text size="sm" c="dimmed" mt="sm">
                  {preview.processed} já processadas · {preview.pending.length}{" "}
                  sessões ZIP a processar
                </Text>
                <div style={{ maxHeight: 180, overflow: "auto", marginTop: 8 }}>
                  {preview.pending.map((file) => (
                    <Text size="sm" key={file.id}>
                      {file.name}
                    </Text>
                  ))}
                </div>
                {!preview.pending.length && (
                  <Text size="sm">Nenhuma gravação pendente.</Text>
                )}
              </>
            )}
          </Paper>
          <Paper withBorder p="lg">
            <Title order={4}>Arquivos gerados</Title>
            <Group mt="sm">
              {["mp3", "resumo.json", "srt", "txt", "vtt"].map((format) => (
                <Checkbox
                  key={format}
                  data-format={format}
                  label={format}
                  checked={format === "mp3" || outputs[format] !== false}
                  disabled={format === "mp3"}
                  onChange={(event) => {
                    const checked = event.currentTarget.checked;
                    setConfig((old) => ({
                      ...old,
                      outputs: { ...old.outputs, [format]: checked },
                    }));
                  }}
                />
              ))}
            </Group>
            <Title order={4} mt="xl">
              Integrações
            </Title>
            <Anchor
              size="xs"
              component="button"
              type="button"
              mb="md"
              onClick={() => changeSub("settings")}
            >
              Mais opções em Configurações
            </Anchor>
            <div className="integration-grid">
              {driveProcess ? (
                <>
                  <Group wrap="nowrap" align="end">
                    <Select
                      className="grow"
                      id="google-account"
                      label="Conta Google"
                      value={opts.google_account || null}
                      data={google.map((a) => ({
                        value: a.id,
                        label: a.label + " · " + a.email,
                      }))}
                      onChange={(value) =>
                        setConfig((old) => ({
                          ...old,
                          integrations: {
                            ...old.integrations,
                            google_account: value || "",
                            google_folder: "",
                            google_folder_name: "",
                            google_folder_path: "",
                          },
                        }))
                      }
                    />
                    <Icon
                      icon={Settings}
                      label="Configurar Google"
                      onClick={() => settings("google")}
                    />
                  </Group>
                  <Group wrap="nowrap" align="end">
                    <Button
                      className="grow nav-button"
                      variant="light"
                      onClick={() => setPicker("google")}
                    >
                      Pasta de gravações:{" "}
                      {(preview?.folder === opts.google_folder &&
                        preview?.folder_path) ||
                        opts.google_folder_path ||
                        opts.google_folder_name ||
                        "Selecionar…"}
                    </Button>
                    <Icon
                      icon={Settings}
                      label="Configurar Google Drive"
                      onClick={() => settings("google")}
                    />
                  </Group>
                </>
              ) : (
                <Group className="full-row" justify="space-between" wrap="wrap">
                  <Text size="sm">
                    Pasta local de gravações:{" "}
                    <code>
                      {appSettings.LOCAL_DRIVE_FOLDER ||
                        defaultAppSettings.LOCAL_DRIVE_FOLDER}
                    </code>
                  </Text>
                  <Anchor
                    size="sm"
                    component="button"
                    type="button"
                    onClick={() => changeSub("settings", "origem")}
                  >
                    Alterar em Configurações
                  </Anchor>
                </Group>
              )}
              <Group wrap="nowrap" align="end">
                <Select
                  className="grow"
                  label="Conta Object Storage"
                  value={opts.storage_account || null}
                  data={accounts.map((a) => ({ value: a.id, label: a.name }))}
                  onChange={(value) =>
                    setConfig((old) => ({
                      ...old,
                      integrations: {
                        ...old.integrations,
                        storage_account: value || "",
                        storage_bucket: "",
                      },
                    }))
                  }
                />
                <Icon
                  icon={Settings}
                  label="Configurar contas Object Storage"
                  onClick={() => settings("object_storage")}
                />
              </Group>
              <Group wrap="nowrap" align="end">
                <Button
                  className="grow nav-button"
                  variant="light"
                  onClick={() => setPicker("storage")}
                >
                  Bucket de destino: {opts.storage_bucket || "Selecionar…"}
                </Button>
                <Icon
                  icon={Settings}
                  label="Configurar Object Storage"
                  onClick={() => settings("object_storage")}
                />
              </Group>
              <Switch
                className="full-row"
                size="md"
                label="Anunciar publicação pela voz da PIA"
                checked={!!opts.announce}
                onChange={(event) =>
                  patch("announce", event.currentTarget.checked)
                }
              />
              <Switch
                className="full-row"
                size="md"
                label="Anunciar publicação no Discord"
                checked={!!opts.discord_notify}
                onChange={(event) =>
                  patch("discord_notify", event.currentTarget.checked)
                }
              />
              <Group className="full-row" wrap="nowrap" align="end">
                <MultiSelect
                  className="grow"
                  label="Servidores / canais do Discord"
                  description="Selecione os canais vinculados por /link. Vazio usa o canal padrão."
                  data={channels.map((c) => ({
                    value: c.channel,
                    label:
                      (c.guild_name || c.guild) +
                      " / #" +
                      (c.name || c.channel),
                  }))}
                  value={opts.discord_channels || []}
                  onChange={(value) => patch("discord_channels", value)}
                />
                <Icon
                  icon={Settings}
                  label="Configurar Discord"
                  onClick={() => settings("discord")}
                />
              </Group>
              <Switch
                className="full-row"
                size="md"
                label="Anunciar publicação na Tav.gg"
                checked={!!opts.taverns_notify}
                onChange={(event) =>
                  patch("taverns_notify", event.currentTarget.checked)
                }
              />
              <Group className="full-row" wrap="nowrap" align="end">
                <MultiSelect
                  className="grow"
                  label="Tavernas / canais da Tav.gg"
                  description={
                    taverns.loading
                      ? "Carregando canais…"
                      : taverns.error ||
                        (taverns.configured
                          ? "Escolha onde publicar os links da sessão."
                          : "Configure o bot no conector Taverns.")
                  }
                  data={[
                    ...taverns.channels,
                    ...(opts.taverns_channels || [])
                      .filter(
                        (value) =>
                          !taverns.channels.some(
                            (channel) => channel.value === value,
                          ),
                      )
                      .map((value) => ({
                        value,
                        label: "Canal indisponível · " + value,
                      })),
                  ]}
                  value={opts.taverns_channels || []}
                  onChange={(value) => patch("taverns_channels", value)}
                  searchable
                />
                <Icon
                  icon={Settings}
                  label="Configurar Taverns"
                  onClick={() => settings("taverns")}
                />
              </Group>
            </div>
            <Button
              mt="lg"
              disabled={!integrationsDirty}
              onClick={safe(async () => {
                await call("save-options", {
                  outputs: config.outputs || {},
                  integrations: opts,
                });
                const fresh = await call("config");
                syncFromConfig(fresh, channels);
              })}
            >
              Salvar opções
            </Button>
            {integrationsDirty && (
              <Text size="sm" c="yellow" mt="xs">
                Alterações não salvas. Salve as opções antes de processar as
                sessões.
              </Text>
            )}
          </Paper>
          <Paper withBorder p="lg">
            <Group justify="space-between">
              <Title order={4}>{pipeline.session || "Processamento"}</Title>
              <Badge color={running ? "violet" : "gray"}>
                {running ? "Em execução" : "Pronto"}
              </Badge>
            </Group>
            <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} mt="md">
              {(pipeline.stages || []).map((stage, index) => (
                <Group key={stage.name} gap="xs">
                  <span className={"stage-icon " + stage.status}>
                    {stage.status === "done" ? (
                      <Check size={17} />
                    ) : stage.status === "error" ? (
                      <X size={17} />
                    ) : stage.status === "running" ? (
                      <Loader size={17} className="spin" />
                    ) : (
                      <Circle size={14} />
                    )}
                  </span>
                  <Text
                    size="sm"
                    c={stage.status === "skipped" ? "dimmed" : undefined}
                  >
                    {index + 1}. {stage.name}
                    {stage.name === "Transcrever" && pipeline.progress?.total
                      ? ` ${pipeline.progress.completed || 0}/${pipeline.progress.total}`
                      : ""}
                    {stage.status === "skipped" ? " · dispensada" : ""}
                  </Text>
                </Group>
              ))}
            </SimpleGrid>
            {pipeline.error && (
              <Text c="red" mt="sm">
                {pipeline.error}
              </Text>
            )}
            <Group mt="lg">
              {(pipeline.artifacts || []).map((item, index) => (
                <Button
                  key={item.url + index}
                  component="a"
                  href={item.url}
                  target="_blank"
                  rel="noreferrer"
                  variant="light"
                  rightSection={<ExternalLink size={14} />}
                >
                  {item.name}
                </Button>
              ))}
            </Group>
          </Paper>
          {(pipeline.history || [])
            .filter((item) => item.session !== pipeline.session)
            .map((item, index) => (
              <Paper withBorder p="md" key={item.session + index}>
                <Group justify="space-between">
                  <Text fw={600}>{item.session}</Text>
                  <Badge color={item.status === "failed" ? "red" : "green"}>
                    {item.status === "complete" ? "Concluída" : item.status}
                  </Badge>
                </Group>
                <Group mt="sm">
                  {item.artifacts.map((artifact, n) => (
                    <Button
                      key={n}
                      component="a"
                      href={artifact.url}
                      target="_blank"
                      rel="noreferrer"
                      variant="light"
                      rightSection={<ExternalLink size={14} />}
                    >
                      {artifact.name}
                    </Button>
                  ))}
                </Group>
              </Paper>
            ))}
          <WorkProgress value={pipeline.progress} />
          {result && (
            <Button
              leftSection={<Download size={16} />}
              onClick={() => {
                const url = URL.createObjectURL(
                  new Blob([result.text], { type: "text/plain;charset=utf-8" }),
                );
                const link = document.createElement("a");
                link.href = url;
                link.download = result.name;
                link.click();
                setTimeout(() => URL.revokeObjectURL(url), 2000);
              }}
            >
              Baixar legenda unida
            </Button>
          )}
          <LogViewer
            text={logs}
            onClear={async () => {
              await call("clear-log");
              setLogs("");
            }}
          />
        </>
      )}

      {picker && (
        <ResourcePicker
          kind={picker === "google" ? "google" : "storage"}
          accounts={picker === "google" ? google : accounts}
          initialAccount={
            picker === "google" ? opts.google_account : opts.storage_account
          }
          onClose={() => setPicker(null)}
          onChoose={(selection) => {
            setConfig((old) => ({
              ...old,
              integrations: {
                ...old.integrations,
                ...(picker === "google"
                  ? {
                      google_account: selection.account,
                      google_folder: selection.id,
                      google_folder_name: selection.name,
                      google_folder_path: selection.path || selection.name,
                    }
                  : {
                      storage_account: selection.account,
                      storage_bucket: selection.id,
                    }),
              },
            }));
            setPicker(null);
          }}
        />
      )}

      <Modal
        opened={!!merge}
        onClose={() => setMerge(null)}
        title={"Unir " + (merge || "").toUpperCase()}
      >
        <Stack>
          <FileInput
            label="Primeira legenda"
            accept={"." + merge}
            value={files[0]}
            onChange={(file) => setFiles([file, files[1]])}
          />
          <FileInput
            label="Segunda legenda"
            accept={"." + merge}
            value={files[1]}
            onChange={(file) => setFiles([files[0], file])}
          />
          <Button
            disabled={!files[0] || !files[1]}
            onClick={safe(async () => {
              await start("merge_" + merge, {
                first: await files[0].text(),
                second: await files[1].text(),
              });
              setMerge(null);
            })}
          >
            Unir legendas
          </Button>
        </Stack>
      </Modal>

      <Modal
        opened={!!removeCampaignModal}
        onClose={() => setRemoveCampaignModal(null)}
        title="Remover campanha"
      >
        <Stack gap="md">
          <Text size="sm">
            Remover a campanha &ldquo;{removeCampaignModal?.name}&rdquo;? Ela
            sai das configurações ao salvar. Arquivos já publicados não são
            apagados.
          </Text>
          <Anchor
            size="sm"
            component="button"
            type="button"
            onClick={() => {
              const idx = removeCampaignModal?.index;
              setCampaigns((old) =>
                old.map((c, i) => (i === idx ? { ...c, closed: true } : c)),
              );
              setRemoveCampaignModal(null);
            }}
          >
            Prefere só encerrar? Marque &ldquo;Campanha encerrada&rdquo;.
          </Anchor>
          <Group justify="flex-end">
            <Button
              variant="subtle"
              onClick={() => setRemoveCampaignModal(null)}
            >
              Cancelar
            </Button>
            <Button
              color="red"
              onClick={() => {
                const idx = removeCampaignModal?.index;
                setCampaigns((old) => old.filter((_, i) => i !== idx));
                setRemoveCampaignModal(null);
              }}
            >
              Remover
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={audioResetModal}
        onClose={() => setAudioResetModal(false)}
        title="Restaurar padrões de áudio"
      >
        <Stack gap="md">
          <Text size="sm">
            Restaurar os 12 parâmetros de áudio para os valores padrão? Você
            ainda pode descartar antes de salvar.
          </Text>
          <Group justify="flex-end">
            <Button variant="subtle" onClick={() => setAudioResetModal(false)}>
              Cancelar
            </Button>
            <Button
              onClick={() => {
                setSettingsDraft((old) => {
                  const nextAudio = {
                    remove_silence: defaultAudio.remove_silence !== false,
                  };
                  for (const key of AUDIO_NUMERIC_KEYS) {
                    nextAudio[key] = String(
                      defaultAudio[key] ?? AUDIO_DEFAULTS[key],
                    );
                  }
                  return { ...old, audio: nextAudio };
                });
                setAudioResetModal(false);
              }}
            >
              Restaurar
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={!!leaveModal}
        onClose={() => setLeaveModal(null)}
        title="Há alterações não salvas"
      >
        <Stack gap="md">
          <Text size="sm">
            Salve antes de sair ou as mudanças serão perdidas.
          </Text>
          <Group justify="flex-end">
            <Button variant="subtle" onClick={() => setLeaveModal(null)}>
              Continuar editando
            </Button>
            <Button
              variant="light"
              color="red"
              onClick={() => {
                const target = leaveModal;
                discardCurrentTab();
                setLeaveModal(null);
                if (target.anchor) setPendingAnchor(target.anchor);
                navigate({ ...route, sub: target.nextSub });
              }}
            >
              Descartar
            </Button>
            <Button
              onClick={async () => {
                const target = leaveModal;
                const ok =
                  sub === "campaigns"
                    ? await saveCampaignsTab()
                    : await saveSettingsTab();
                setLeaveModal(null);
                if (ok) {
                  if (target.anchor) setPendingAnchor(target.anchor);
                  navigate({ ...route, sub: target.nextSub });
                }
              }}
            >
              Salvar e sair
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
