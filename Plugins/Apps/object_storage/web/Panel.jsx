import React, { useState, useEffect, useRef } from "react";
import {
  Button,
  Group,
  Paper,
  Select,
  TextInput,
  Table,
  Checkbox,
  Text,
  Stack,
  Modal,
  Progress,
} from "@mantine/core";
import {
  RefreshCw,
  ArrowUp,
  FolderPlus,
  Upload,
  Trash2,
  Download,
  Copy,
  Move,
  Folder,
  Settings,
  X,
} from "lucide-react";
import {
  appApi,
  watchJob,
  safe,
  report,
} from "../../../../src/pia/frontend/api";
import {
  Icon,
  About,
  WorkProgress,
  usePia,
} from "../../../../src/pia/frontend/shared";
const call = (action, data = {}) => appApi("object_storage", action, data);
export default function Storage({ sub = "principal" }) {
  const { navigate, route } = usePia(),
    [accounts, setAccounts] = useState([]),
    [account, setAccount] = useState(""),
    [buckets, setBuckets] = useState([]),
    [bucket, setBucket] = useState(""),
    [prefix, setPrefix] = useState(""),
    [page, setPage] = useState({ folders: [], objects: [] }),
    [selected, setSelected] = useState([]),
    [transfer, setTransfer] = useState(null),
    [target, setTarget] = useState({}),
    [progress, setProgress] = useState(null);
  const files = useRef(),
    directory = useRef(),
    streams = useRef([]),
    uploadCancelled = useRef(false),
    currentJob = useRef(null);
  const where = { account, bucket, prefix };
  async function browse(append = false) {
    if (!account || !bucket) return;
    const result = await call("list", {
      ...where,
      cursor: append ? page.cursor : null,
    });
    setPage((old) =>
      append
        ? {
            ...result,
            folders: [...old.folders, ...result.folders],
            objects: [...old.objects, ...result.objects],
          }
        : result,
    );
    if (!append) setSelected([]);
  }
  useEffect(() => {
    call("accounts")
      .then((result) => {
        setAccounts(result.accounts);
        setAccount(result.default || result.accounts[0]?.id || "");
      })
      .catch(report);
    return () => streams.current.forEach((stream) => stream.close());
  }, []);
  useEffect(() => {
    if (account)
      call("buckets", { account })
        .then((result) => {
          setBuckets(result.buckets);
          setBucket(result.buckets[0] || "");
          setPrefix("");
        })
        .catch(report);
  }, [account]);
  useEffect(() => {
    browse().catch(report);
  }, [account, bucket, prefix]);
  function watch(result, label) {
    currentJob.current = result.job;
    setProgress({ label, percent: 0, state: "transferring" });
    streams.current.push(
      watchJob(result.job, (event) => {
        if (event.type === "progress") setProgress({ ...event, label });
        if (event.type === "done") {
          setProgress({ label, percent: 100, state: "completed" });
          browse().catch(report);
        }
        if (event.type === "error") {
          setProgress({ label, percent: 0, state: "error" });
          report(event.error);
        }
      }),
    );
  }
  async function remove(keys) {
    if (
      !window.confirm(
        "Excluir " +
          keys.length +
          " objetos/pastas? A exclusão de pasta inclui o conteúdo.",
      )
    )
      return;
    watch(await call("delete", { ...where, keys }), "Excluir objetos");
  }
  async function upload(list) {
    if (!account || !bucket) throw Error("Escolha uma conta e bucket.");
    uploadCancelled.current = false;
    for (const file of list) {
      const result = await call("upload-begin", {
        ...where,
        key: prefix + (file.webkitRelativePath || file.name),
        size: file.size,
      });
      try {
        for (let offset = 0; offset < file.size; offset += 4 * 1024 ** 2) {
          if (uploadCancelled.current) throw Error("Envio cancelado.");
          const chunk = file.slice(offset, offset + 4 * 1024 ** 2),
            data = await new Promise((resolve, reject) => {
              const reader = new FileReader();
              reader.onload = () => resolve(reader.result.split(",")[1]);
              reader.onerror = reject;
              reader.readAsDataURL(chunk);
            });
          await call("upload-chunk", { id: result.id, offset, data });
          setProgress({
            label: file.name,
            percent: (100 * (offset + chunk.size)) / file.size,
            state: "uploading",
          });
        }
        watch(await call("upload-finish", { id: result.id }), file.name);
      } catch (error) {
        await call("upload-cancel", { id: result.id }).catch(() => {});
        throw error;
      }
    }
  }
  if (sub === "about")
    return (
      <About>
        <Text>
          Configure as contas em Configurações → Object Storage. Escolha conta e
          bucket para navegar, enviar arquivos/pastas, baixar, copiar, mover ou
          excluir objetos. Credenciais ficam no conector e no cofre do sistema.
        </Text>
      </About>
    );
  return (
    <Stack>
      <Paper withBorder p="lg">
        <Group align="end">
          <Select
            label="Conta"
            data={accounts.map((a) => ({ value: a.id, label: a.name }))}
            value={account || null}
            onChange={(value) => setAccount(value || "")}
          />
          <Select
            label="Bucket"
            data={buckets}
            value={bucket || null}
            onChange={(value) => {
              setBucket(value || "");
              setPrefix("");
            }}
          />
          <Icon
            icon={Settings}
            label="Configurar Object Storage"
            onClick={() =>
              navigate({
                view: "connectors",
                connector: "object_storage",
              })
            }
          />
          <Icon icon={RefreshCw} label="Atualizar" onClick={() => browse()} />
          <Icon
            icon={ArrowUp}
            label="Pasta anterior"
            onClick={() => setPrefix((old) => old.replace(/[^/]+\/?$/, ""))}
          />
          <Icon
            icon={FolderPlus}
            label="Criar pasta"
            onClick={async () => {
              const name = prompt("Nome da pasta");
              if (name) {
                await call("mkdir", { ...where, key: prefix + name + "/" });
                await browse();
              }
            }}
          />
          <Icon
            icon={Upload}
            label="Enviar arquivos"
            onClick={() => files.current.click()}
          />
          <Icon
            icon={Folder}
            label="Enviar pasta"
            onClick={() => directory.current.click()}
          />
          <Icon
            icon={Trash2}
            label="Excluir selecionados"
            disabled={!selected.length}
            onClick={() => remove(selected)}
          />
        </Group>
        <Text size="xs" mt="md">
          {bucket} / {prefix}
        </Text>
      </Paper>
      <Paper
        withBorder
        p="md"
        onDragOver={(event) => event.preventDefault()}
        onDrop={safe((event) => {
          event.preventDefault();
          return upload(event.dataTransfer.files);
        })}
      >
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th />
              <Table.Th>Nome</Table.Th>
              <Table.Th>Tamanho</Table.Th>
              <Table.Th>Ações</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {[
              ...page.folders.map((key) => ({ key, folder: true })),
              ...page.objects,
            ].map((item) => (
              <Table.Tr key={item.key}>
                <Table.Td>
                  <Checkbox
                    aria-label={"Selecionar " + item.key}
                    checked={selected.includes(item.key)}
                    onChange={() =>
                      setSelected((old) =>
                        old.includes(item.key)
                          ? old.filter((k) => k !== item.key)
                          : [...old, item.key],
                      )
                    }
                  />
                </Table.Td>
                <Table.Td>
                  <Button
                    variant="subtle"
                    onClick={safe(async () => {
                      if (item.folder) setPrefix(item.key);
                      else {
                        const info = await call("info", {
                          ...where,
                          key: item.key,
                        });
                        alert(JSON.stringify(info, null, 2));
                      }
                    })}
                  >
                    {item.folder ? "📁 " : ""}
                    {item.key.slice(prefix.length)}
                  </Button>
                </Table.Td>
                <Table.Td>
                  {item.folder
                    ? "—"
                    : ((item.size || 0) / 1024).toFixed(1) + " KiB"}
                </Table.Td>
                <Table.Td>
                  <Group gap={2}>
                    {!item.folder && (
                      <Icon
                        icon={Download}
                        label="Baixar objeto"
                        onClick={async () => {
                          const result = await call("download", {
                            ...where,
                            key: item.key,
                          });
                          window.open(result.url, "_blank", "noopener");
                        }}
                      />
                    )}
                    {[
                      [Copy, "copy", "Copiar"],
                      [Move, "move", "Mover / renomear"],
                    ].map(([glyph, action, label]) => (
                      <Icon
                        key={action}
                        icon={glyph}
                        label={label}
                        onClick={() => {
                          setTransfer({ action, key: item.key });
                          setTarget({ account, bucket, key: item.key });
                        }}
                      />
                    ))}
                    <Icon
                      icon={Trash2}
                      label="Excluir objeto"
                      onClick={() => remove([item.key])}
                    />
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        <Text c="dimmed" size="sm">
          Arraste arquivos aqui para enviar.
        </Text>
        {page.cursor && (
          <Button onClick={safe(() => browse(true))}>Carregar mais</Button>
        )}
      </Paper>
      <WorkProgress value={progress} />
      {progress && (
        <Icon
          icon={X}
          label="Cancelar envio local"
          onClick={async () => {
            uploadCancelled.current = true;
            if (currentJob.current)
              await call("cancel", { job: currentJob.current });
          }}
        />
      )}
      <input
        ref={files}
        type="file"
        hidden
        multiple
        onChange={safe((event) => upload(event.target.files))}
      />
      <input
        ref={directory}
        type="file"
        hidden
        multiple
        webkitdirectory=""
        onChange={safe((event) => upload(event.target.files))}
      />
      <Modal
        opened={!!transfer}
        onClose={() => setTransfer(null)}
        title="Transferir objeto"
      >
        <Stack>
          <Select
            label="Conta de destino"
            value={target.account || null}
            data={accounts.map((a) => ({ value: a.id, label: a.name }))}
            onChange={(account) => setTarget({ ...target, account })}
          />
          <TextInput
            label="Bucket de destino"
            value={target.bucket || ""}
            onChange={(event) =>
              setTarget({ ...target, bucket: event.target.value })
            }
          />
          <TextInput
            label="Chave / pasta"
            value={target.key || ""}
            onChange={(event) =>
              setTarget({ ...target, key: event.target.value })
            }
          />
          <Button
            onClick={safe(async () => {
              watch(
                await call(transfer.action, {
                  ...where,
                  key: transfer.key,
                  target: target.key,
                  target_account: target.account,
                  target_bucket: target.bucket,
                }),
                transfer.key,
              );
              setTransfer(null);
            })}
          >
            Transferir
          </Button>
        </Stack>
      </Modal>
    </Stack>
  );
}
