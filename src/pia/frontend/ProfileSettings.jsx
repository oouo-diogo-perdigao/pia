import React, { useEffect, useState } from "react";
import {
  Stack,
  Paper,
  Text,
  PasswordInput,
  Button,
  Group,
  FileButton,
  Modal,
  Textarea,
  Select,
} from "@mantine/core";
import { api, safe, report } from "./api";
import { usePia } from "./shared";

export function TransferSettings() {
  const { state, navigate } = usePia();
  const [password, setPassword] = useState(""),
    [confirmation, setConfirmation] = useState(""),
    [data, setData] = useState(""),
    [preview, setPreview] = useState(null),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  const [storage, setStorage] = useState(null);
  const [googleAccounts, setGoogleAccounts] = useState([]);
  const [googleAccount, setGoogleAccount] = useState(null);
  useEffect(() => {
    safe(async () => setStorage(await api("/settings/storage")))();
    safe(async () => {
      const { accounts } = await api("/settings/google-backup");
      setGoogleAccounts(accounts);
      if (accounts.length === 1) setGoogleAccount(accounts[0].id);
    })();
  }, []);
  async function work(fn) {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  }
  return (
    <Paper withBorder p="lg">
      <Stack>
        <Text fw={600}>Migrar configurações entre computadores</Text>
        <Text size="sm">
          Exporta as configurações e as credenciais do cofre em um arquivo
          criptografado por senha. O arquivo funciona no Windows e Linux. Chats,
          músicas, capturas e modelos não fazem parte deste backup.
        </Text>
        {storage && (
          <Text size="sm" c="dimmed">
            Perfil: {storage.folder}
          </Text>
        )}
        {storage?.notes?.map((note, index) => (
          <Text key={index} c="orange" size="sm">
            {note}
          </Text>
        ))}
        <PasswordInput
          label="Senha do arquivo de migração"
          description="Mínimo de 12 caracteres. Você precisará desta senha no outro computador."
          value={password}
          onChange={(event) => {
            setPassword(event.target.value);
            setPreview(null);
          }}
          autoComplete="new-password"
        />
        <PasswordInput
          label="Confirmar senha para exportar"
          value={confirmation}
          onChange={(event) => setConfirmation(event.target.value)}
          autoComplete="new-password"
        />
        <Group>
          <Button
            disabled={busy || password.length < 12 || password !== confirmation}
            onClick={safe(() =>
              work(async () => {
                const result = await api("/settings/export", { password });
                if (state.native)
                  await api("/native", {
                    action: "save-config-backup",
                    payload: { data: result.data },
                  });
                else {
                  const bytes = Uint8Array.from(atob(result.data), (char) =>
                    char.charCodeAt(0),
                  );
                  const url = URL.createObjectURL(
                    new Blob([bytes], { type: "application/octet-stream" }),
                  );
                  const link = document.createElement("a");
                  link.href = url;
                  link.download = result.filename;
                  link.click();
                  setTimeout(() => URL.revokeObjectURL(url), 1000);
                }
                setPassword("");
                setConfirmation("");
                setMessage(
                  "Arquivo de migração preparado. Guarde a senha separadamente.",
                );
              }),
            )}
          >
            Exportar configurações e credenciais
          </Button>
          <FileButton
            accept=".pia-backup"
            onChange={safe((file) =>
              work(async () => {
                if (!file) return;
                if (file.size > 24 * 1024 ** 2)
                  throw Error("Arquivo excede 24 MiB.");
                const encoded = await new Promise((resolve, reject) => {
                  const reader = new FileReader();
                  reader.onload = () => resolve(reader.result.split(",")[1]);
                  reader.onerror = reject;
                  reader.readAsDataURL(file);
                });
                setData(encoded);
                setPreview(null);
                setMessage(
                  "Arquivo carregado. Informe sua senha e clique em Verificar.",
                );
              }),
            )}
          >
            {(props) => (
              <Button {...props} disabled={busy} variant="light">
                Selecionar arquivo para importar
              </Button>
            )}
          </FileButton>
          <Button
            disabled={busy || !data || password.length < 12}
            onClick={safe(() =>
              work(async () =>
                setPreview(
                  await api("/settings/import-preview", { data, password }),
                ),
              ),
            )}
          >
            Verificar importação
          </Button>
        </Group>
        <Select
          label="Conta Google para backup"
          placeholder="Selecione uma conta"
          value={googleAccount}
          onChange={setGoogleAccount}
          disabled={busy}
          data={googleAccounts.map(({ id, label, email }) => ({
            value: id,
            label: email ? `${label} · ${email}` : label,
          }))}
        />
        <Group>
          <Button
            variant="light"
            disabled={
              busy ||
              !googleAccount ||
              password.length < 12 ||
              password !== confirmation
            }
            onClick={safe(() =>
              work(async () => {
                await api("/settings/google-backup", {
                  action: "export",
                  account: googleAccount,
                  password,
                });
                setPassword("");
                setConfirmation("");
                setMessage("Backup criptografado salvo no Google Drive.");
              }),
            )}
          >
            Exportar para Google Drive
          </Button>
          <Button
            variant="light"
            disabled={busy || !googleAccount}
            onClick={safe(() =>
              work(async () => {
                const result = await api("/settings/google-backup", {
                  action: "download",
                  account: googleAccount,
                });
                setData(result.data);
                setPreview(null);
                const date = result.created
                  ? ` (${new Date(result.created).toLocaleString()})`
                  : "";
                setMessage(
                  `Backup do Google Drive carregado${date}. Informe a senha e clique em Verificar importação.`,
                );
              }),
            )}
          >
            Importar do Google Drive
          </Button>
          <Button
            variant="subtle"
            disabled={busy}
            onClick={() =>
              navigate({ view: "connectors", connector: "google" })
            }
          >
            Conectar ou autorizar conta Google
          </Button>
        </Group>
        <Text size="xs" c="dimmed">
          Use a mesma conta e o mesmo cliente OAuth nos dois computadores. A
          importação carrega o backup mais recente salvo pela PIA nessa conta.
        </Text>
        {message && <Text size="sm">{message}</Text>}
        <Text size="xs" c="dimmed">
          A importação substitui as configurações correspondentes. Caminhos
          padrão são recalculados neste computador. Executáveis externos podem
          precisar ser selecionados novamente; provedores OAuth podem exigir
          reconexão. Aguarde jobs em andamento.
        </Text>
        <Modal
          opened={!!preview}
          onClose={() => setPreview(null)}
          title="Importar configurações"
        >
          <Stack>
            <Text>
              {preview?.settings} configurações, {preview?.documents} documentos
              e {preview?.credentials} credenciais. As configurações
              correspondentes deste computador serão substituídas.
            </Text>
            <Button
              color="violet"
              disabled={busy}
              onClick={safe(() =>
                work(async () => {
                  const result = await api("/settings/import", {
                    data,
                    password,
                  });
                  setPreview(null);
                  setData("");
                  setPassword("");
                  setConfirmation("");
                  setMessage(
                    result.restarting
                      ? "Importado com sucesso. A PIA está reiniciando. Reabra esta interface em alguns segundos."
                      : "Importado com sucesso. Reinicie a PIA para aplicar todas as configurações.",
                  );
                }),
              )}
            >
              Importar e substituir configurações
            </Button>
            <Button variant="subtle" onClick={() => setPreview(null)}>
              Cancelar
            </Button>
          </Stack>
        </Modal>
      </Stack>
    </Paper>
  );
}

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
