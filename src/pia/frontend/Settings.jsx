import { fieldGroup } from "./settings-groups";
import { DocumentSettings, VaultSettings } from "./ProfileSettings";
import LogsPanel from "./LogsPanel";
import { fingerprint } from "./forms";
import React, { useState, useEffect, useRef } from "react";
import { Button, Group, Paper, Text, Title, TextInput, PasswordInput, Select, Stack, Modal, FileButton, Anchor } from "@mantine/core";
import { ExternalLink, Folder, Upload } from "lucide-react";
import { api, report, safe, session } from "./api";
import { Icon, Nav, usePia } from "./shared";

function ServerProfilePanel() {
  const [revision, setRevision] = useState(null);
  const [pending, setPending] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function transfer(action) {
    setBusy(true);
    try {
      const result = await api("/integrations/pia_server/profile-" + action, {
        revision,
      });
      setRevision(result.revision);
      setPending(null);
      if (action === "push") setMessage("Perfil salvo no servidor.");
      if (action === "pull")
        setMessage(
          "Perfil carregado. Reinicie a PIA para aplicar as configurações.",
        );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Paper withBorder p="lg">
      <Stack>
        <Title order={4}>Perfil compartilhado</Title>
        <Text size="sm">
          Configurações e conversas podem ser copiadas entre computadores. As contas dos conectores são gerenciadas no servidor. As
          preferências de notificação ficam neste computador.
        </Text>
        <Anchor
          href="https://pia.travelrpg.com"
          target="_blank"
          rel="noreferrer"
        >
          Abrir painel da PIA Server
        </Anchor>
        <Text size="sm">
          {revision === null
            ? "Consulte o perfil antes de sincronizar."
            : revision === "0"
              ? "Ainda não existe um perfil no servidor."
              : "Revisão no servidor: " + revision}
        </Text>
        <Group>
          <Button
            variant="light"
            disabled={busy}
            onClick={safe(() => transfer("status"))}
          >
            Consultar perfil
          </Button>
          <Button
            disabled={busy || revision === null}
            onClick={() => setPending("push")}
          >
            Enviar perfil local
          </Button>
          <Button
            variant="light"
            disabled={busy || !revision || revision === "0"}
            onClick={() => setPending("pull")}
          >
            Carregar perfil do servidor
          </Button>
        </Group>
        {message && (
          <Text size="sm" role="status">
            {message}
          </Text>
        )}
        <Modal
          opened={!!pending}
          onClose={() => !busy && setPending(null)}
          title="Sincronizar perfil"
        >
          <Stack>
            <Text>
              {pending === "pull"
                ? "As conversas locais serão substituídas pelas do servidor. As configurações correspondentes também serão atualizadas."
                : "O servidor passará a guardar a cópia deste computador. A revisão atual será substituída."}
            </Text>
            <Button loading={busy} onClick={safe(() => transfer(pending))}>
              Confirmar sincronização
            </Button>
          </Stack>
        </Modal>
      </Stack>
    </Paper>
  );
}

export default function SettingsPanel({ section = "general" }) {
  const { navigate, language, setLanguage, t, boot, setRestarting } = usePia(),
    [sections, setSections] = useState([]),
    [values, setValues] = useState({}),
    [savedValues, setSavedValues] = useState(""),
    [logs, setLogs] = useState([]),
    [notice, setNotice] = useState(""),
    [group, setGroup] = useState("Geral");
  useEffect(() => {
    let active = true;
    if (
      !["logs", "documents", "credentials"].includes(
        section,
      )
    ) {
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
  if (section === "logs") return <LogsPanel />;
  if (section === "documents") return <DocumentSettings />;
  if (section === "credentials") return <VaultSettings />;
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
          {selected.id === "general" && (
            <Group gap="xs">
              {[
                "Geral",
                "STT",
                "TTS",
                "Imagens · ICE",
                "LLMs",
                "Voz e áudio",
              ].map((name) => (
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
          {selected.fields
            .filter(
              (field) =>
                selected.id !== "general" || fieldGroup(field) === group,
            )
            .map((field) => (
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
            {t("Salvar configurações")}
          </Button>
          {notice && <Text size="sm">{notice}</Text>}
        </Stack>
      </Paper>
      {selected.id === "Connectors/pia_server" && <ServerProfilePanel />}
    </Stack>
  );
}
