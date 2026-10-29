import { fingerprint } from "./forms";
import React, { useState, useEffect, useRef } from "react";
import {
  Button,
  Group,
  Paper,
  Text,
  Title,
  TextInput,
  PasswordInput,
  Select,
  Textarea,
  Switch,
  Stack,
  Modal,
  FileButton,
  Anchor,
  Badge,
} from "@mantine/core";
import {
  ExternalLink,
  Folder,
  Upload,
  Trash2,
  Copy,
  RefreshCw,
  Link,
  Unlink,
  Plus,
  Settings as Gear,
} from "lucide-react";
import { api, appApi, copy, report, safe, watchJob, session } from "./api";
import { Icon, Nav, LogViewer, usePia } from "./shared";

export function DiscordPanel({ onChange = () => {} }) {
  const [state, setState] = useState(null),
    [channel, setChannel] = useState(""),
    [logs, setLogs] = useState(""),
    [result, setResult] = useState(""),
    [busy, setBusy] = useState(false),
    [channels, setChannels] = useState([]);
  const previous = useRef(null),
    call = (action, data = {}) => api("/integrations/discord/" + action, data);
  async function refresh() {
    const value = await call("status");
    setState(value);
    if (previous.current !== value.channel) {
      setChannel(value.channel);
      previous.current = value.channel;
      onChange(value);
    }
    setChannels((await call("channels")).channels);
  }
  async function loadLogs() {
    setLogs((await call("logs")).text);
  }
  useEffect(() => {
    refresh().catch(report);
    loadLogs().catch(report);
    const timer = setInterval(() => refresh().catch(report), 5000);
    return () => clearInterval(timer);
  }, []);
  async function action(name, data = {}) {
    setBusy(true);
    try {
      const value = await call(name, data);
      setResult(
        name === "test"
          ? "Mensagem de teste enviada: " + value.id
          : name === "diagnose"
            ? "Conexão válida: " + value.name
            : "Operação concluída.",
      );
      await refresh();
      await loadLogs();
    } catch (error) {
      setResult(error.message);
      await loadLogs();
      throw error;
    } finally {
      setBusy(false);
    }
  }
  return (
    <Stack mt="lg">
      <Paper withBorder p="lg">
        <Title order={4}>Conexão e publicação</Title>
        <Text size="sm" mt="sm">
          {state?.configured ? "Token configurado" : "Configure o token"} ·{" "}
          {state?.gateway?.state}
          {state?.gateway?.error ? " · " + state.gateway.error : ""}
        </Text>
        <Select
          mt="md"
          label="Canal da mensagem de teste"
          placeholder="Vincule um canal com /link"
          value={channel || null}
          data={[
            ...channels.map((item) => ({
              value: item.channel,
              label:
                (item.guild_name || item.guild) +
                " / #" +
                (item.name || item.channel),
            })),
            ...(channel && !channels.some((item) => item.channel === channel)
              ? [
                  {
                    value: channel,
                    label: "Canal padrão antigo · use /link para atualizar",
                  },
                ]
              : []),
          ]}
          onChange={(value) => setChannel(value || "")}
        />
        <Group mt="md">
          <Button
            disabled={busy}
            onClick={safe(() => action("diagnose", { channel }))}
          >
            Verificar conexão
          </Button>
          <Button
            disabled={busy}
            onClick={safe(() => action("test", { channel }))}
          >
            Enviar mensagem de teste
          </Button>
        </Group>
        <Text size="sm" mt="sm">
          {result}
        </Text>
      </Paper>
      <Paper withBorder p="lg">
        <Title order={4}>Canais para publicação</Title>
        <Text size="sm" my="md">
          Use /link no Discord com permissão Administrador. Cada canal vinculado
          aparece aqui e no seletor do Podcast Automation.
        </Text>
        {channels.map((item) => (
          <Group key={item.channel} justify="space-between">
            <Text>
              {item.guild_name || item.guild} / #{item.name || item.channel}
            </Text>
            <Icon
              feedback
              icon={Copy}
              label="Copiar ID do canal"
              onClick={() => copy(item.channel)}
            />
          </Group>
        ))}
        <Group mt="md">
          <Button disabled={busy} onClick={safe(() => action("register-link"))}>
            Registrar /link e conectar
          </Button>
          <Icon
            icon={RefreshCw}
            label="Reconectar"
            onClick={() => action("listener", { enabled: true })}
          />
          <Icon
            icon={Unlink}
            label="Desativar listener"
            onClick={() => action("listener", { enabled: false })}
          />
          <Icon
            icon={Trash2}
            label="Remover vínculo padrão"
            confirm
            onClick={() => action("unlink")}
          />
        </Group>
      </Paper>
      <LogViewer text={logs} title="Log do Discord" />
      <Icon icon={RefreshCw} label="Atualizar log" onClick={loadLogs} />
    </Stack>
  );
}

export function StorageAccounts() {
  const [accounts, setAccounts] = useState([]),
    [form, setForm] = useState({ provider: "s3", region: "auto" }),
    [savedForm, setSavedForm] = useState(
      fingerprint({ provider: "s3", region: "auto" }),
    );
  const call = (action, data = {}) => appApi("object_storage", action, data);
  async function refresh() {
    setAccounts((await call("accounts")).accounts);
  }
  useEffect(() => {
    refresh().catch(report);
  }, []);
  async function edit(account) {
    const secrets = await api("/integrations/object_storage/secrets", {
      account: account.id,
    });
    setForm({ ...account, ...secrets });
    setSavedForm(fingerprint({ ...account, ...secrets }));
  }
  return (
    <Paper withBorder p="lg" mt="lg">
      <Title order={4}>Contas Object Storage</Title>
      {accounts.map((account) => (
        <Group key={account.id} mt="sm" justify="space-between">
          <Text>{account.name}</Text>
          {account.id !== "legacy" && (
            <Group>
              <Button variant="subtle" onClick={safe(() => edit(account))}>
                Editar
              </Button>
              <Icon
                icon={Trash2}
                label="Remover conta"
                confirm
                onClick={async () => {
                  await call("remove-account", { id: account.id });
                  await refresh();
                }}
              />
            </Group>
          )}
        </Group>
      ))}
      <Stack mt="lg">
        {[
          "name",
          "provider",
          "endpoint",
          "region",
          "bucket",
          "public_url",
          "access_key",
          "secret_key",
          "session_token",
        ].map((key) =>
          key === "provider" ? (
            <Select
              key={key}
              label="Provedor"
              value={form[key] || "s3"}
              data={["s3", "r2", "compatible"]}
              onChange={(value) => setForm({ ...form, [key]: value })}
            />
          ) : key.includes("key") || key === "session_token" ? (
            <PasswordInput
              key={key}
              label={key}
              value={form[key] || ""}
              onChange={(event) =>
                setForm({ ...form, [key]: event.target.value })
              }
            />
          ) : (
            <TextInput
              key={key}
              label={key}
              value={form[key] || ""}
              onChange={(event) =>
                setForm({ ...form, [key]: event.target.value })
              }
            />
          ),
        )}
        <Switch
          label="Conta padrão"
          checked={!!form.default}
          onChange={(event) =>
            setForm({ ...form, default: event.currentTarget.checked })
          }
        />
        <Group>
          <Button
            disabled={fingerprint(form) === savedForm}
            onClick={safe(async () => {
              await call("save-account", form);
              setForm({ provider: "s3", region: "auto" });
              setSavedForm(fingerprint({ provider: "s3", region: "auto" }));
              await refresh();
            })}
          >
            Salvar conta
          </Button>
          <Icon
            icon={Plus}
            label="Nova conta"
            onClick={() => {
              setForm({ provider: "s3", region: "auto" });
              setSavedForm(fingerprint({ provider: "s3", region: "auto" }));
            }}
          />
        </Group>
      </Stack>
    </Paper>
  );
}

export function Accounts({ providerId }) {
  const [data, setData] = useState(null),
    [forms, setForms] = useState({});
  useEffect(() => {
    api("/accounts")
      .then((result) => {
        setData(result);
        setForms(
          Object.fromEntries(
            result.providers.map((provider) => [
              provider.id,
              {
                client: result.clients[provider.id],
                secret: result.client_secrets?.[provider.id] || "",
                label: "",
              },
            ]),
          ),
        );
      })
      .catch(report);
  }, []);
  if (!data) return <Text>Carregando contas…</Text>;
  return (
    <Stack>
      {data.providers
        .filter((provider) => !providerId || provider.id === providerId)
        .map((provider) => (
          <Paper withBorder p="lg" key={provider.id}>
            <Title order={4}>{provider.name}</Title>
            <Anchor href={provider.setup_url} target="_blank" rel="noreferrer">
              Obter credenciais ↗
            </Anchor>
            <Stack mt="md">
              {["client", "secret", "label"].map((key) => {
                const Field = key === "secret" ? PasswordInput : TextInput;
                return (
                  <Field
                    key={key}
                    label={
                      {
                        client: "Client ID",
                        secret: "Client Secret",
                        label: "Nome local da conta",
                      }[key]
                    }
                    value={forms[provider.id][key]}
                    onChange={(event) =>
                      setForms({
                        ...forms,
                        [provider.id]: {
                          ...forms[provider.id],
                          [key]: event.target.value,
                        },
                      })
                    }
                  />
                );
              })}
              <Button
                onClick={safe(async () => {
                  const form = forms[provider.id],
                    job = await api("/accounts/connect", {
                      plugin: provider.id,
                      client_id: form.client,
                      client_secret: form.secret,
                      label: form.label,
                    });
                  watchJob(job.job, (event) => {
                    if (event.type === "error") report(event.error);
                    if (event.type === "done")
                      api("/accounts").then(setData).catch(report);
                  });
                })}
              >
                Conectar conta
              </Button>
              {data.accounts
                .filter((account) => account.plugin === provider.id)
                .map((account) => (
                  <Group key={account.id}>
                    <Text>
                      {account.label} · {account.email}
                    </Text>
                    <Icon
                      icon={Unlink}
                      label="Desconectar conta"
                      onClick={async () => {
                        await api("/accounts/disconnect", {
                          plugin: provider.id,
                          account: account.id,
                        });
                        setData(await api("/accounts"));
                      }}
                    />
                  </Group>
                ))}
            </Stack>
          </Paper>
        ))}
    </Stack>
  );
}

export default function SettingsPanel({ section = "general" }) {
  const { navigate, language, setLanguage, t, boot, setRestarting } = usePia(),
    [sections, setSections] = useState([]),
    [values, setValues] = useState({}),
    [savedValues, setSavedValues] = useState(""),
    [logs, setLogs] = useState([]),
    [notice, setNotice] = useState("");
  useEffect(() => {
    let active = true;
    if (section === "logs") {
      api("/logs")
        .then((result) => {
          if (active) setLogs(result);
        })
        .catch(report);
    } else if (section !== "accounts") {
      api("/settings")
        .then((result) => {
          if (!active) return;
          setSections(result);
          const selected = result.find((s) => s.id === section) || result[0];
          const initial = Object.fromEntries(
            selected.fields.map((field) => [field.name, field.value]),
          );
          setValues(initial);
          setSavedValues(fingerprint(initial));
        })
        .catch(report);
    }
    return () => {
      active = false;
    };
  }, [section]);
  if (section === "accounts") return <Accounts />;
  if (section === "logs")
    return (
      <Stack>
        <Group justify="space-between">
          <Title order={4}>{t("Inspeção e logs")}</Title>
          <Icon
            icon={Trash2}
            label={t("Apagar todos os logs")}
            onClick={async () => {
              await api("/logs/clear", { all: true });
              setLogs((old) => old.map((log) => ({ ...log, text: "" })));
            }}
          />
        </Group>
        {logs.map((log) => (
          <LogViewer
            key={log.name}
            title={log.name}
            text={log.text}
            onClear={async () => {
              await api("/logs/clear", { name: log.name });
              setLogs((old) =>
                old.map((item) =>
                  item.name === log.name ? { ...item, text: "" } : item,
                ),
              );
            }}
          />
        ))}
      </Stack>
    );
  const selected = sections.find((s) => s.id === section) || sections[0];
  if (!selected) return <Text>{t("Carregando…")}</Text>;
  async function save() {
    const result = await api("/settings/save", {
      section: selected.id,
      values,
    });
    setSavedValues(fingerprint(values));
    if (result.restarting) {
      setRestarting(true);
      await new Promise((resolve) => setTimeout(resolve, 1300));
      for (let n = 0; n < 17280; n++) {
        try {
          await session();
          const state = await api("/state");
          if (state.boot !== boot) {
            location.reload();
            return;
          }
        } catch {}
        await new Promise((resolve) => setTimeout(resolve, 5000));
      }
      throw Error("A PIA ainda não voltou. Consulte logs/launcher.log.");
    }
    setNotice("Variáveis salvas. O reinício exige a sessão gráfica da PIA.");
  }
  async function upload(field, file) {
    if (!file) return;
    if (file.size > 5 * 1024 ** 2) throw Error("Arquivo excede 5 MiB.");
    const encoded = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result.split(",")[1]);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
    const result = await api("/settings/upload", {
      section: selected.id,
      name: field.name,
      filename: file.name,
      data: encoded,
    });
    setValues((old) => ({ ...old, [field.name]: result.path }));
  }
  return (
    <Stack>
      <Group className="settings-tabs">
        {sections
          .filter((item) =>
            section.startsWith("Connectors/")
              ? item.id === section
              : !item.id.startsWith("Connectors/"),
          )
          .map((item) => (
            <Nav
              key={item.id}
              active={item.id === selected.id}
              onClick={() => navigate({ view: "settings", section: item.id })}
            >
              {item.id === "general" ? t("Geral") : item.name}
            </Nav>
          ))}
      </Group>
      <Paper withBorder p="lg">
        <Title order={4} mb="lg">
          {t(selected.name)}
        </Title>
        <Stack>
          {selected.id === "general" && (
            <Select
              label={t("Idioma")}
              data={[
                { value: "pt-BR", label: "Português" },
                { value: "en", label: "English" },
              ]}
              value={language}
              onChange={safe(async (value) => {
                await api("/preferences", { language: value });
                setLanguage(value);
              })}
            />
          )}{" "}
          {selected.fields
            .filter(
              (field) =>
                selected.id !== "Connectors/discord" ||
                field.base !== "DISCORD_CHANNEL_ID",
            )
            .map((field) => (
              <Group key={field.name} wrap="nowrap" align="end">
                <div className="grow">
                  {field.type === "bool" ? (
                    <Select
                      label={field.name}
                      data={[
                        { value: "", label: '""' },
                        { value: "true", label: "true" },
                        { value: "false", label: "false" },
                      ]}
                      value={values[field.name] || ""}
                      onChange={(value) =>
                        setValues({ ...values, [field.name]: value || "" })
                      }
                    />
                  ) : field.sensitive ? (
                    <PasswordInput
                      label={field.name}
                      value={values[field.name] || ""}
                      onChange={(event) =>
                        setValues({
                          ...values,
                          [field.name]: event.target.value,
                        })
                      }
                    />
                  ) : (
                    <TextInput
                      label={field.name}
                      type={
                        ["int", "float"].includes(field.type)
                          ? "number"
                          : "text"
                      }
                      step={field.type === "int" ? "1" : "any"}
                      value={values[field.name] || ""}
                      onChange={(event) =>
                        setValues({
                          ...values,
                          [field.name]: event.target.value,
                        })
                      }
                    />
                  )}
                </div>
                {["path", "file"].includes(field.type) && (
                  <Icon
                    icon={Folder}
                    label={t("Selecionar pasta")}
                    onClick={async () => {
                      const result = await api("/native", {
                        action: "choose-path",
                        payload: {
                          mode: field.type === "file" ? "file" : "directory",
                        },
                      });
                      if (result.path)
                        setValues({ ...values, [field.name]: result.path });
                    }}
                  />
                )}
                {field.type === "file" && (
                  <>
                    <FileButton onChange={safe((file) => upload(field, file))}>
                      {(props) => (
                        <span {...props}>
                          <Icon icon={Upload} label="Carregar arquivo" />
                        </span>
                      )}
                    </FileButton>
                    <Icon
                      icon={Folder}
                      label="Abrir pasta do arquivo"
                      onClick={() =>
                        api("/native", {
                          action: "reveal-file",
                          payload: { path: values[field.name] },
                        })
                      }
                    />
                  </>
                )}
                <Icon
                  icon={ExternalLink}
                  label={t("Configurar ↗")}
                  component="a"
                  href={field.link}
                  target="_blank"
                  rel="noreferrer"
                />
              </Group>
            ))}
          <Button
            disabled={fingerprint(values) === savedValues}
            onClick={safe(save)}
          >
            {t("Salvar variáveis")}
          </Button>
          {notice && <Text size="sm">{notice}</Text>}
        </Stack>
      </Paper>
      {selected.id === "Connectors/discord" && <DiscordPanel />}{" "}
      {selected.id === "Connectors/object_storage" && <StorageAccounts />}
    </Stack>
  );
}
