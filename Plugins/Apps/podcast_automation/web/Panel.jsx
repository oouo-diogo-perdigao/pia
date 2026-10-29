import { fingerprint } from "../../../../src/pia/frontend/forms";
import ResourcePicker from "../../../../src/pia/frontend/ResourcePicker";
import React, { useState, useEffect, useRef } from "react";
import {
  Button,
  Group,
  Paper,
  Text,
  Title,
  Select,
  MultiSelect,
  TextInput,
  Switch,
  Checkbox,
  Textarea,
  Stack,
  SimpleGrid,
  Modal,
  FileInput,
  Anchor,
  Badge,
} from "@mantine/core";
import {
  Settings,
  Search,
  Plus,
  Undo2,
  Check,
  Circle,
  X,
  Loader,
  Play,
  Square,
  ExternalLink,
  Trash2,
  Download,
} from "lucide-react";
import {
  api,
  appApi,
  watchJob,
  safe,
  report,
} from "../../../../src/pia/frontend/api";
import {
  Icon,
  Nav,
  WorkProgress,
  LogViewer,
  About,
  usePia,
} from "../../../../src/pia/frontend/shared";
function campaignConfig(value) {
  const { integrations, outputs, ...campaigns } = value;
  return campaigns;
}
const id = "podcast_automation",
  call = (action, data = {}) => appApi(id, action, data);
export default function Podcast({ sub = "principal" }) {
  const { navigate, route } = usePia(),
    [config, setConfig] = useState(null),
    [original, setOriginal] = useState(""),
    [savedOptions, setSavedOptions] = useState(""),
    [picker, setPicker] = useState(null),
    [editor, setEditor] = useState(""),
    [logs, setLogs] = useState(""),
    [pipeline, setPipeline] = useState({ stages: [], artifacts: [] }),
    [running, setRunning] = useState(false),
    [job, setJob] = useState(null),
    [monitor, setMonitor] = useState(false),
    [shutdownAfter, setShutdownAfter] = useState(false),
    [shutdownPending, setShutdownPending] = useState(false),
    [google, setGoogle] = useState([]),
    [accounts, setAccounts] = useState([]),
    [channels, setChannels] = useState([]),
    [result, setResult] = useState(null),
    [merge, setMerge] = useState(null),
    [files, setFiles] = useState([null, null]);
  const source = useRef();
  const opts = config?.integrations || {},
    outputs = config?.outputs || {},
    patch = (key, value) =>
      setConfig((old) => ({
        ...old,
        integrations: { ...old.integrations, [key]: value },
      }));
  const settings = (plugin) =>
    navigate({ view: "connectors", connector: plugin });
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
  useEffect(() => {
    let active = true;
    Promise.all([
      call("config"),
      call("status"),
      call("pipeline"),
      api("/integrations/google/accounts", {}),
      appApi("object_storage", "accounts"),
      api("/integrations/discord/channels", {}),
    ])
      .then(([configuration, status, steps, g, storage, discord]) => {
        if (!active) return;
        const integrations = { ...configuration.integrations };
        if (!integrations.discord_channels)
          integrations.discord_channels =
            integrations.discord_channel &&
            discord.channels.some(
              (c) => c.channel === integrations.discord_channel,
            )
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
        setGoogle(g.accounts);
        setAccounts(storage.accounts);
        setChannels(discord.channels);
        setLogs(status.lines.join("\n"));
        setResult(status.result || null);
        setPipeline(steps);
        setShutdownPending(!!status.shutdown_pending);
        if (status.running) {
          setMonitor(!!status.monitor);
          setShutdownAfter(!!status.shutdown_after);
          watch(status.job, status.cursor || 0);
        }
      })
      .catch(report);
    return () => {
      active = false;
      source.current?.close();
    };
  }, []);
  async function start(task, data = {}) {
    const result = await call("start", {
      task,
      monitor: task === "process" && monitor,
      shutdown_after: task === "process" && shutdownAfter,
      ...data,
    });
    setLogs("");
    setResult(null);
    setPipeline({ stages: [], artifacts: [] });
    watch(result.job);
  }
  const changeSub = (sub) => navigate({ ...route, sub });
  if (sub === "about")
    return (
      <About>
        <Text>
          Escolha as contas Google e Object Storage, a pasta de gravações, os
          arquivos de saída e as campanhas. Processar sessões usa a PIA local
          com Whisper medium e publica os arquivos no armazenamento escolhido.
          Acompanhe as etapas, o progresso e os links abaixo do processamento. O
          log acompanha o final até você rolar para cima.
        </Text>
      </About>
    );
  if (!config) return <Text>Carregando Podcast Automation…</Text>;
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
      </Group>
      {sub === "campaigns" ? (
        <Paper withBorder p="lg">
          <Text mb="sm">Campanhas, participantes e regras de publicação</Text>
          <Textarea
            id="config"
            className="campaign-editor"
            autosize
            minRows={18}
            value={editor}
            onChange={(event) => setEditor(event.target.value)}
          />
          <Group mt="md">
            <Button
              id="save-config"
              disabled={editor === original}
              onClick={safe(async () => {
                const value = JSON.parse(editor);
                await call("save-config", { value });
                setOriginal(editor);
                setConfig((old) => ({ ...old, ...campaignConfig(value) }));
              })}
            >
              Salvar campanhas
            </Button>
            <Icon
              icon={Undo2}
              label="Desfazer mudanças"
              disabled={editor === original}
              onClick={() => setEditor(original)}
            />
          </Group>
        </Paper>
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
              <Button disabled={running || shutdownPending} onClick={safe(() => start("rebuild"))}>
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
            <Title order={4} mt="xl" mb="md">
              Integrações
            </Title>
            <div className="integration-grid">
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
                  {opts.google_folder_name ||
                    opts.google_folder ||
                    "Selecionar…"}
                </Button>
                <Icon
                  icon={Settings}
                  label="Configurar Google Drive"
                  onClick={() => settings("google")}
                />
              </Group>
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
            </div>
            <Button
              mt="lg"
              disabled={
                fingerprint({
                  outputs: config.outputs || {},
                  integrations: opts,
                }) === savedOptions
              }
              onClick={safe(async () => {
                await call("save-options", {
                  outputs: config.outputs || {},
                  integrations: opts,
                });
                const fresh = await call("config");
                setConfig(fresh);
                setSavedOptions(
                  fingerprint({
                    outputs: fresh.outputs || {},
                    integrations: fresh.integrations || {},
                  }),
                );
                const text = JSON.stringify(campaignConfig(fresh), null, 2);
                if (editor === original) {
                  setOriginal(text);
                  setEditor(text);
                }
              })}
            >
              Salvar opções
            </Button>
            {fingerprint({
              outputs: config.outputs || {},
              integrations: opts,
            }) !== savedOptions && (
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
    </Stack>
  );
}
