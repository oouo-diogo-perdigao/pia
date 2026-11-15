import { splitTtsFields } from "./tts-helpers";
import { DocumentSettings, VaultSettings } from "./ProfileSettings";
import LogsPanel from "./LogsPanel";
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
  Stack,
  FileButton,
} from "@mantine/core";
import { ExternalLink, Folder, Upload } from "lucide-react";
import { api, report, safe, session } from "./api";
import { Icon, Nav, usePia } from "./shared";
import TTSSettingsPanel from "./TTSSettingsPanel";
import MusicSettingsPanel from "./MusicSettingsPanel";
import GeneralSettingsTabs from "./GeneralSettingsTabs";
import {
  GENERAL_TABS,
  buildManagedInitialValues,
  safeArray,
} from "./settings-simplification";

function ServerProfilePanel() {
  const [profile, setProfile] = useState({ state: "pending" });

  useEffect(() => {
    let active = true;
    async function refresh() {
      try {
        const result = await api("/integrations/pia_server/profile-status");
        if (active) setProfile(result);
      } catch {
        if (active) setProfile({ state: "retrying" });
      }
    }
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  const messages = {
    pending: "Sincronização pendente.",
    synced: "Perfil sincronizado.",
    retrying: "Não foi possível sincronizar. A PIA tentará novamente.",
    disconnected: "Entre na PIA Server para sincronizar.",
    "different-account":
      "Este perfil pertence a outra conta. Entre com a conta original para sincronizar.",
  };

  return (
    <Paper withBorder p="lg">
      <Stack>
        <Title order={4}>Sincronização automática</Title>
        <Text size="sm">
          A PIA sincroniza configurações e conversas em segundo plano. As contas
          dos conectores são gerenciadas no servidor. Caminhos e preferências
          deste computador são mantidos localmente.
        </Text>
        <Text size="sm" role="status">
          {messages[profile.state]}
        </Text>
        <Anchor
          href="https://pia.travelrpg.com"
          target="_blank"
          rel="noreferrer"
        >
          Abrir painel da PIA Server
        </Anchor>
      </Stack>
    </Paper>
  );
}

export default function SettingsPanel({ section = "general" }) {
  const { navigate, t, boot, setRestarting } = usePia(),
    [sections, setSections] = useState([]),
    [values, setValues] = useState({}),
    [initialValues, setInitialValues] = useState({}),
    [savedValues, setSavedValues] = useState(""),
    [logs, setLogs] = useState([]),
    [notice, setNotice] = useState(""),
    [group, setGroup] = useState("Geral");
  useEffect(() => {
    let active = true;
    if (!["logs", "documents", "credentials"].includes(section)) {
      api("/settings")
        .then((result) => {
          if (!active) return;
          const safeResult = safeArray(result);
          setSections(safeResult);
          const selected =
            safeResult.find((s) => s?.id === section) || safeResult[0];
          const initial = selected
            ? buildManagedInitialValues(selected.id, selected.fields)
            : {};
          setValues(initial);
          setInitialValues(initial);
          setSavedValues(fingerprint(initial));
        })
        .catch(report);
    }
    return () => {
      active = false;
    };
  }, [section]);
  if (section === "logs") return <LogsPanel />;
  if (section === "documents") return <DocumentSettings />;
  if (section === "credentials") return <VaultSettings />;
  const safeSections = safeArray(sections);
  const selected =
    safeSections.find((s) => s?.id === section) || safeSections[0];
  if (!selected) return <Text>{t("Carregando…")}</Text>;
  const selectedFields = safeArray(selected.fields);
  const { otherFields } =
    selected.id === "general"
      ? splitTtsFields(selectedFields)
      : { otherFields: selectedFields };
  const isCustomTtsTab = selected.id === "general" && group === "TTS";
  const isCustomMusicTab =
    (selected.id === "general" && group === "Música") ||
    selected.id === "Apps/music";
  const isSimplifiedGeneralTab =
    selected.id === "general" && !isCustomTtsTab && !isCustomMusicTab;
  async function save() {
    const result = await api("/settings/save", {
      section: selected.id,
      values,
    });
    setSavedValues(fingerprint(values));
    setInitialValues(values);
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
    setNotice(
      "Configurações salvas. O reinício exige a sessão gráfica da PIA.",
    );
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
            <Group gap="xs" wrap="wrap">
              {GENERAL_TABS.map((name) => (
                <Button
                  key={name}
                  variant={group === name ? "light" : "subtle"}
                  onClick={() => setGroup(name)}
                >
                  {t(name)}
                </Button>
              ))}
            </Group>
          )}
          {isCustomTtsTab ? (
            <TTSSettingsPanel />
          ) : isCustomMusicTab ? (
            <MusicSettingsPanel />
          ) : isSimplifiedGeneralTab ? (
            <>
              <GeneralSettingsTabs
                group={group}
                fields={selected.fields}
                values={values}
                initialValues={initialValues}
                setValues={setValues}
              />
              {(group !== "Geral" || fingerprint(values) !== savedValues) && (
                <Group justify="flex-end">
                  <Button
                    disabled={fingerprint(values) === savedValues}
                    onClick={safe(save)}
                  >
                    {t("Salvar configurações")}
                  </Button>
                </Group>
              )}
              {notice && <Text size="sm">{notice}</Text>}
            </>
          ) : (
            <>
              {otherFields.map((field) => (
                <Group
                  key={field.name}
                  className="env-row"
                  wrap="nowrap"
                  align="center"
                  gap="xs"
                >
                  <Text
                    component="label"
                    htmlFor={"env-" + field.name}
                    size="xs"
                    className="env-name"
                  >
                    {field.label || field.name}
                  </Text>
                  <div className="grow">
                    {field.type === "bool" ? (
                      <Select
                        id={"env-" + field.name}
                        aria-label={field.name}
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
                        id={"env-" + field.name}
                        aria-label={field.name}
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
                        id={"env-" + field.name}
                        aria-label={field.name}
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
                      <FileButton
                        onChange={safe((file) => upload(field, file))}
                      >
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
                {t("Salvar configurações")}
              </Button>
              {notice && <Text size="sm">{notice}</Text>}
            </>
          )}
        </Stack>
      </Paper>
      {selected.id === "Connectors/pia_server" && <ServerProfilePanel />}
    </Stack>
  );
}
