import React, { useState, useEffect, useRef } from "react";
import { Accordion, Stack, Group, Text, TextInput } from "@mantine/core";
import { Trash2 } from "lucide-react";
import { api, report } from "./api";
import { Icon, LogViewer } from "./shared";

export default function LogsPanel() {
  const [logs, setLogs] = useState([]),
    [search, setSearch] = useState(""),
    [opened, setOpened] = useState([]);
  const live = useRef([]),
    selection = useRef([]);
  selection.current = opened;
  useEffect(() => {
    let active = true,
      timer;
    async function load() {
      try {
        const values = await api("/logs");
        if (active) {
          live.current = values;
          setLogs(values);
          setOpened(values.map((item) => item.name));
        }
      } catch (error) {
        report(error);
      }
    }
    async function poll() {
      try {
        const updated = await Promise.all(
          selection.current.map((name) => {
            const item = live.current.find((row) => row.name === name);
            return item
              ? api("/logs/read", {
                  name,
                  cursor: item.cursor,
                  identity: item.identity,
                })
              : null;
          }),
        );
        if (active) {
          live.current = live.current.map((item) => {
            const delta = updated.find((row) => row?.name === item.name);
            return delta
              ? {
                  ...delta,
                  text: delta.reset ? delta.text : item.text + delta.text,
                }
              : item;
          });
          setLogs(live.current);
        }
      } catch (error) {
        if (active) report(error);
      } finally {
        if (active) timer = setTimeout(poll, 2000);
      }
    }
    load().then(() => {
      if (active) timer = setTimeout(poll, 2000);
    });
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, []);
  async function clear(name) {
    await api("/logs/clear", name ? { name } : { all: true });
    live.current = live.current.map((item) =>
      !name || item.name === name ? { ...item, text: "", cursor: 0 } : item,
    );
    setLogs(live.current);
  }
  async function open(name) {
    const result = await api("/logs/open", { name });
    if (result.url) window.open(result.url, "_blank", "noopener");
  }
  return (
    <Stack>
      <Group justify="space-between">
        <Text fw={600}>Inspeção e logs</Text>
        <Icon
          icon={Trash2}
          label="Apagar todos os logs"
          onClick={() => clear()}
        />
      </Group>
      <TextInput
        placeholder="Buscar categoria, arquivo ou conteúdo"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />
      <Accordion
        multiple
        defaultValue={[
          "Main",
          "Apps",
          "Bot",
          "Connectors",
          "Skills",
          "Browser",
        ]}
      >
        {["Main", "Apps", "Bot", "Connectors", "Skills", "Browser"].map(
          (category) => {
            const rows = logs.filter((item) => item.category === category);
            return (
              <Accordion.Item key={category} value={category}>
                <Accordion.Control>
                  {category} · {rows.length}
                </Accordion.Control>
                <Accordion.Panel>
                  <Accordion multiple value={opened} onChange={setOpened}>
                    {rows
                      .filter(
                        (item) =>
                          !search ||
                          (item.name + "\n" + item.text)
                            .toLowerCase()
                            .includes(search.toLowerCase()),
                      )
                      .map((item) => (
                        <Accordion.Item key={item.name} value={item.name}>
                          <Accordion.Control>
                            {item.name
                              .replace(/^plugins\//, "")
                              .replace(/\.log$/, "")}
                          </Accordion.Control>
                          <Accordion.Panel>
                            <LogViewer
                              title={item.name}
                              text={item.text}
                              onClear={() => clear(item.name)}
                              onOpen={() => open(item.name)}
                            />
                          </Accordion.Panel>
                        </Accordion.Item>
                      ))}
                  </Accordion>
                </Accordion.Panel>
              </Accordion.Item>
            );
          },
        )}
      </Accordion>
      <Text size="xs" c="dimmed">
        Últimas 100 linhas ao abrir. Novas linhas desta sessão são mantidas;
        logs expandidos acompanham atualizações.
      </Text>
    </Stack>
  );
}
