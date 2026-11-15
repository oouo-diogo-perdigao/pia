import React, { useEffect, useState } from "react";
import { Stack, Paper, Group, Text, Button, Anchor } from "@mantine/core";
import { Check } from "lucide-react";
import { api, report, safe } from "./api";
import { Icon, usePia } from "./shared";

export default function Notifications() {
  const [state, setState] = useState(null);
  const { refresh, navigate, t } = usePia();
  const load = () => api("/notifications").then(setState);
  useEffect(() => {
    let active = true;
    const fetch = () =>
      api("/notifications")
        .then((data) => {
          if (active) setState(data);
        })
        .catch(report);
    fetch();
    const timer = setInterval(fetch, 3000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);
  async function read(id) {
    await api("/notifications/read", id ? { id } : {});
    await load();
    await refresh();
  }
  if (!state) return <Text>Carregando notificações…</Text>;
  return (
    <Stack>
      <Group justify="space-between">
        <Text>
          {state.unread} {t("não lidas")}
        </Text>
        <Button
          variant="subtle"
          disabled={!state.unread}
          onClick={safe(() => read())}
        >
          {t("Marcar todas como lidas")}
        </Button>
      </Group>
      {state.items.map((item) => (
        <Paper
          key={item.id}
          withBorder
          p="md"
          style={{
            borderColor: item.read
              ? undefined
              : "var(--mantine-color-violet-5)",
          }}
        >
          <Group justify="space-between">
            <Text fw={600}>{item.title}</Text>
            {!item.read && (
              <Icon
                icon={Check}
                label="Marcar como lida"
                onClick={() => read(item.id)}
              />
            )}
          </Group>
          <Text size="xs" c="dimmed">
            {item.source} · {new Date(item.created_at).toLocaleString()}
          </Text>
          <Text style={{ whiteSpace: "pre-wrap" }}>{item.text}</Text>
          <Group mt="xs">
            {item.links.map((link) => (
              <Anchor
                key={link.url}
                href={link.url}
                target="_blank"
                rel="noreferrer"
                onClick={safe(() => read(item.id))}
              >
                {link.label} ↗
              </Anchor>
            ))}
          </Group>
        </Paper>
      ))}
      {!state.items.length && (
        <Text c="dimmed">{t("Nenhuma notificação ainda.")}</Text>
      )}
    </Stack>
  );
}
