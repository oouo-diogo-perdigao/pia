import { fingerprint } from "../../../../src/pia/frontend/forms";
import React, { useState, useEffect } from "react";
import {
  Paper,
  Stack,
  Switch,
  TextInput,
  NumberInput,
  Select,
  ColorInput,
  Button,
  Text,
  Group,
  Checkbox,
  SimpleGrid,
  Tabs,
  Title,
} from "@mantine/core";
import { MessageSquare, Settings } from "lucide-react";
import {
  SpeakerVoicePanel,
  notifyTtsUpdated,
} from "../../../../src/pia/frontend/VoiceSelector";
import BotChatPanel from "../../../../src/pia/frontend/features/bots/BotChatPanel";
import { api, report, safe } from "../../../../src/pia/frontend/api";
import { usePia } from "../../../../src/pia/frontend/shared";
import { notify } from "../../../../src/pia/frontend/toasts";
export default function Secretary() {
  const { route, navigate } = usePia(),
    [data, setData] = useState(null),
    [saved, setSaved] = useState(""),
    [tab, setTab] = useState(route?.tab === "config" ? "config" : "chat");
  useEffect(() => {
    if (route?.tab === "config" || route?.tab === "chat") {
      setTab(route.tab);
    }
  }, [route?.tab]);
  const snapshot = (value) =>
    fingerprint({
      config: value?.config || {},
      voice: {
        mode: value?.voice?.mode || "inherit",
        profile: value?.voice?.mode === "custom" ? value?.voice?.profile : null,
      },
    });
  useEffect(() => {
    api("/bots/secretaria")
      .then((value) => {
        setData(value);
        setSaved(snapshot(value));
      })
      .catch(report);
  }, []);
  if (!data) return <Text>Carregando secretária…</Text>;
  const config = data.config,
    voice = data.voice || { mode: "inherit", profile: null, revision: 1 },
    patch = (key, value) =>
      setData({ ...data, config: { ...config, [key]: value } });
  return (
    <Stack gap="md">
      <Group justify="space-between" wrap="wrap" gap="sm">
        <Stack gap={2}>
          <Title order={4}>Secretária</Title>
          <Text size="sm" c="dimmed">
            Converse diretamente com a Secretária ou ajuste agenda, e-mails e
            voz.
          </Text>
        </Stack>
      </Group>

      <Tabs value={tab} onChange={(val) => setTab(val || "chat")}>
        <Tabs.List>
          <Tabs.Tab value="chat" leftSection={<MessageSquare size={14} />}>
            Conversar com o Bot
          </Tabs.Tab>
          <Tabs.Tab value="config" leftSection={<Settings size={14} />}>
            Configurações e Voz
          </Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="chat" pt="md">
          <BotChatPanel
            botId="secretaria"
            botName="Secretária"
            botSubtitle="Agenda, lembretes e e-mails importantes"
            minHeight={300}
            maxHeight={460}
          />
        </Tabs.Panel>

        <Tabs.Panel value="config" pt="md">
          <Paper withBorder p="lg">
            <Stack gap="sm">
              <SimpleGrid
                cols={{ base: 1, sm: 2 }}
                spacing="sm"
                verticalSpacing="sm"
              >
                {Object.entries({
                  enabled: "Ativar secretária",
                  reminders: "Lembrar compromissos",
                  remind_minutes: "Antecedência dos lembretes (min)",
                  open_meetings: "Abrir Meet automaticamente",
                  meet_minutes: "Minutos antes de abrir o Meet",
                  important_email: "Avisar novos e-mails importantes",
                  poll_seconds: "Intervalo de consulta (seg)",
                  calendar: "ID da agenda",
                }).map(([key, label]) =>
                  typeof config[key] === "boolean" ? (
                    <Switch
                      key={key}
                      label={label}
                      checked={config[key]}
                      onChange={(event) =>
                        patch(key, event.currentTarget.checked)
                      }
                    />
                  ) : typeof config[key] === "number" ? (
                    <NumberInput
                      key={key}
                      label={label}
                      value={config[key]}
                      onChange={(value) => patch(key, value)}
                    />
                  ) : (
                    <TextInput
                      key={key}
                      label={label}
                      value={config[key]}
                      onChange={(event) => patch(key, event.target.value)}
                    />
                  ),
                )}
              </SimpleGrid>
              <Select
                label="Quais e-mails acompanhar?"
                data={data.filters.map((item) => ({
                  value: item.id,
                  label: item.name,
                }))}
                value={config.email_filter}
                onChange={(value) => patch("email_filter", value)}
              />
              {config.email_filter === "custom" && (
                <TextInput
                  label="Busca personalizada do Gmail"
                  value={config.email_query}
                  onChange={(event) => patch("email_query", event.target.value)}
                />
              )}
              <Text fw={600}>Cores do avatar</Text>
              <SimpleGrid cols={3} spacing="sm">
                {["primary", "accent", "eyes"].map((color) => (
                  <ColorInput
                    key={color}
                    label={
                      {
                        primary: "Principal",
                        accent: "Destaque",
                        eyes: "Olhos",
                      }[color]
                    }
                    value={config["avatar_" + color]}
                    onChange={(value) => patch("avatar_" + color, value)}
                  />
                ))}
              </SimpleGrid>
              <SpeakerVoicePanel
                speakerId="native:secretaria"
                title="Voz da Secretária"
                value={voice}
                onChange={(nextVoice) => setData({ ...data, voice: nextVoice })}
                previewText="Olá! Sou a Secretária da PIA e este é um teste da minha voz."
              />
              <Text fw={600}>Contas Google autorizadas</Text>
              {data.accounts.map((account) => (
                <Checkbox
                  key={account.id}
                  label={account.label + " · " + account.email}
                  checked={config.accounts.includes(account.id)}
                  onChange={(event) =>
                    patch(
                      "accounts",
                      event.currentTarget.checked
                        ? [...config.accounts, account.id]
                        : config.accounts.filter((id) => id !== account.id),
                    )
                  }
                />
              ))}
              {!data.accounts.length && (
                <Button
                  variant="subtle"
                  onClick={() =>
                    navigate({ view: "connectors", connector: "google" })
                  }
                >
                  Conectar conta Google ↗
                </Button>
              )}
              <Group>
                <Button
                  disabled={snapshot(data) === saved}
                  onClick={safe(async () => {
                    const result = await api("/bots/secretaria", {
                      ...config,
                      voice: {
                        mode: voice.mode || "inherit",
                        profile: voice.mode === "custom" ? voice.profile : null,
                        revision: voice.revision,
                      },
                    });
                    setData(result);
                    setSaved(snapshot(result));
                    notifyTtsUpdated();
                    notify("Preferências da secretária salvas.");
                  })}
                >
                  Salvar preferências
                </Button>
                <Button onClick={safe(() => api("/bots/secretaria/poll", {}))}>
                  Consultar agora
                </Button>
              </Group>
            </Stack>
          </Paper>
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
