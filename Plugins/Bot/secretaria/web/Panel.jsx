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
} from "@mantine/core";
import { api, report, safe } from "../../../../src/pia/frontend/api";
import { usePia } from "../../../../src/pia/frontend/shared";
export default function Secretary() {
  const { navigate } = usePia(),
    [data, setData] = useState(null),
    [saved, setSaved] = useState("");
  useEffect(() => {
    api("/bots/secretaria")
      .then((value) => {
        setData(value);
        setSaved(fingerprint(value.config));
      })
      .catch(report);
  }, []);
  if (!data) return <Text>Carregando secretária…</Text>;
  const config = data.config,
    patch = (key, value) =>
      setData({ ...data, config: { ...config, [key]: value } });
  return (
    <Paper withBorder p="lg">
      <Stack>
        {Object.entries({
          enabled: "Ativar secretária",
          reminders: "Lembrar compromissos",
          remind_minutes: "Antecedência dos lembretes (min)",
          open_meetings: "Abrir Meet automaticamente",
          meet_minutes: "Minutos antes de abrir o Meet",
          important_email: "Avisar novos e-mails importantes",
          speak: "Ler avisos em voz alta",
          poll_seconds: "Intervalo de consulta (seg)",
          calendar: "ID da agenda",
        }).map(([key, label]) =>
          typeof config[key] === "boolean" ? (
            <Switch
              key={key}
              label={label}
              checked={config[key]}
              onChange={(event) => patch(key, event.currentTarget.checked)}
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
        {["primary", "accent", "eyes"].map((color) => (
          <ColorInput
            key={color}
            label={color}
            value={config["avatar_" + color]}
            onChange={(value) => patch("avatar_" + color, value)}
          />
        ))}
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
            disabled={fingerprint(config) === saved}
            onClick={safe(async () => {
              const result = await api("/bots/secretaria", config);
              setData(result);
              setSaved(fingerprint(result.config));
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
  );
}
