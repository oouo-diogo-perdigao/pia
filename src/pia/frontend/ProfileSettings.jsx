import React, { useEffect, useState } from "react";
import { Stack, Paper, Text, Button, Group, Modal, Textarea, Select } from "@mantine/core";
import { api, safe, report } from "./api";

export function DocumentSettings() {
  const [documents, setDocuments] = useState({}),
    [name, setName] = useState("keywords.txt"),
    [text, setText] = useState("");
  useEffect(() => {
    api("/settings/documents")
      .then((value) => {
        setDocuments(value);
        setText(value["keywords.txt"] || "");
      })
      .catch(report);
  }, []);
  return (
    <Paper withBorder p="lg">
      <Stack>
        <Text fw={600}>Ativação, atalhos e catálogo</Text>
        <Select
          label="Documento de configuração"
          value={name}
          data={["keywords.txt", "shortcuts.yaml", "models.yaml"]}
          onChange={(value) => {
            setName(value);
            setText(documents[value] || "");
          }}
        />
        <Textarea
          aria-label="Conteúdo do documento de configuração"
          autosize
          minRows={12}
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
        <Button
          disabled={text === (documents[name] || "")}
          onClick={safe(async () => {
            await api("/settings/documents", { name, value: text });
            setDocuments((old) => ({ ...old, [name]: text }));
          })}
        >
          Salvar configuração
        </Button>
        <Text size="xs" c="dimmed">
          Conteúdo armazenado no SQLite. Reinicie a PIA para aplicar palavras de
          ativação e atalhos.
        </Text>
      </Stack>
    </Paper>
  );
}

export function VaultSettings() {
  const [items, setItems] = useState([]),
    [opened, setOpened] = useState(null);
  useEffect(() => {
    api("/settings/credentials")
      .then((value) => setItems(value.items))
      .catch(report);
  }, []);
  return (
    <Paper withBorder p="lg">
      <Stack>
        <Text fw={600}>Cofre da PIA</Text>
        <Text size="sm">
          Entradas geridas pela PIA no cofre deste sistema. Edite chaves nas
          configurações do recurso e contas nos conectores. Os valores só são
          consultados ao clicar em Revelar.
        </Text>
        {!items.length && (
          <Text c="dimmed">Nenhuma credencial cadastrada.</Text>
        )}
        {items.map((name) => (
          <Group key={name} justify="space-between">
            <Text size="sm">{name}</Text>
            <Button
              variant="subtle"
              onClick={safe(async () =>
                setOpened({
                  name,
                  ...(await api("/settings/credential", { name })),
                }),
              )}
            >
              Revelar
            </Button>
          </Group>
        ))}
        <Modal
          opened={!!opened}
          onClose={() => setOpened(null)}
          title={opened?.name}
        >
          <Textarea
            readOnly
            autosize
            minRows={3}
            maxRows={15}
            aria-label="Conteúdo da credencial"
            value={
              opened
                ? typeof opened.value === "string"
                  ? opened.value
                  : JSON.stringify(opened.value, null, 2)
                : ""
            }
          />
        </Modal>
      </Stack>
    </Paper>
  );
}
