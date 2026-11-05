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
  Anchor,
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
  GripVertical,
} from "lucide-react";
import {
  appApi,
  watchJob,
  safe,
  report,
  copy,
} from "../../../../src/pia/frontend/api";
import {
  Icon,
  About,
  WorkProgress,
  usePia,
} from "../../../../src/pia/frontend/shared";
const call = (action, data = {}) => appApi("object_storage", action, data);
const MIME = "application/x-pia-storage";
export default function Storage({ sub = "principal" }) {
  const { navigate, route, state } = usePia(),
    [accounts, setAccounts] = useState([]),
    [account, setAccount] = useState(""),
    [buckets, setBuckets] = useState([]),
    [bucket, setBucket] = useState(""),
    [prefix, setPrefix] = useState(""),
    [page, setPage] = useState({ folders: [], objects: [] }),
    [selected, setSelected] = useState([]),
    [transfer, setTransfer] = useState(null),
    [target, setTarget] = useState({}),
    [progress, setProgress] = useState(null),
    [active, setActive] = useState(false),
    [opening, setOpening] = useState(null),
    [prepared, setPrepared] = useState({}),
    [drop, setDrop] = useState(null);
  const files = useRef(),
    directory = useRef(),
    streams = useRef([]),
    uploadCancelled = useRef(false),
    currentJob = useRef(null),
    generation = useRef(0),
    location = useRef();
  const where = { account, bucket, prefix };
  location.current = where;
  const color = accounts.find((a) => a.id === account)?.color || "#9b7aff";
  const parent = prefix.replace(/[^/]+\/$/, "");
  async function browse(append = false) {
    if (!account || !bucket) return;
    const version = ++generation.current,
      identity = JSON.stringify(where);
    const result = await call("list", {
      ...where,
      cursor: append ? page.cursor : null,
    });
    if (
      version !== generation.current ||
      JSON.stringify(location.current) !== identity
    )
      return;
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
    // Active transfers finish independently of navigation; watchJob closes on completion.
    return () => {
      if (!currentJob.current)
        streams.current.forEach((stream) => stream.close());
    };
  }, []);
  useEffect(() => {
    let live = true;
    if (account)
      call("buckets", { account })
        .then((result) => {
          if (!live) return;
          setBuckets(result.buckets);
          setBucket(result.buckets[0] || "");
          setPrefix("");
        })
        .catch((error) => {
          if (live) report(error);
        });
    return () => {
      live = false;
    };
  }, [account]);
  useEffect(() => {
    browse().catch(report);
  }, [account, bucket, prefix]);
  function watch(result, label, refresh = true) {
    currentJob.current = result.job;
    setActive(true);
    setProgress({ label, percent: 0, state: "transferring" });
    return new Promise((resolve, reject) => {
      streams.current.push(
        watchJob(result.job, (event) => {
          if (event.type === "progress") setProgress({ ...event, label });
          if (event.type === "done") {
            currentJob.current = null;
            setActive(false);
            setProgress({ label, percent: 100, state: "completed" });
            if (
              refresh &&
              JSON.stringify(location.current) === JSON.stringify(where)
            )
              browse().catch(report);
            resolve(event.result);
          }
          if (event.type === "error") {
            currentJob.current = null;
            setActive(false);
            setProgress({ label, percent: 0, state: "error" });
            reject(Error(event.error));
          }
        }),
      );
    });
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
    await watch(await call("delete", { ...where, keys }), "Excluir objetos");
  }
  async function upload(list) {
    if (!account || !bucket) throw Error("Escolha uma conta e bucket.");
    uploadCancelled.current = false;
    setActive(true);
    try {
      for (const file of Array.from(list)) {
        if (uploadCancelled.current) break;
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
          if (uploadCancelled.current) throw Error("Envio cancelado.");
          await watch(
            await call("upload-finish", { id: result.id }),
            file.name,
          );
        } catch (error) {
          await call("upload-cancel", { id: result.id }).catch(() => {});
          throw error;
        }
      }
    } finally {
      setActive(false);
      currentJob.current = null;
    }
  }
  function changeAccount(value) {
    generation.current++;
    setAccount(value || "");
    setBucket("");
    setBuckets([]);
    setPrefix("");
    setPage({ folders: [], objects: [] });
    setSelected([]);
    setOpening(null);
  }
  async function prepare(item, open = false) {
    const identity = localIdentity(item);
    let local = prepared[identity];
    if (!local) {
      local = await watch(
        await call("prepare-local", { ...where, key: item.key }),
        "Baixando " + item.key,
        false,
      );
      setPrepared((old) => ({ ...old, [identity]: local }));
    }
    if (open) await call("open-local", { token: local.token });
  }
  function localIdentity(item) {
    return JSON.stringify([
      account,
      bucket,
      item.key,
      item.modified,
      item.size,
    ]);
  }
  function dragStart(event, item) {
    event.dataTransfer.setData(
      MIME,
      JSON.stringify({
        account,
        bucket,
        keys: selected.includes(item.key) ? selected : [item.key],
      }),
    );
    event.dataTransfer.effectAllowed = "move";
  }
  function dropProps(destination) {
    return {
      onDragOver: (event) => {
        if (!active && event.dataTransfer.types.includes(MIME)) {
          event.preventDefault();
          event.stopPropagation();
          setDrop(destination);
          event.dataTransfer.dropEffect = "move";
        }
      },
      onDragLeave: () => setDrop(null),
      onDrop: safe(async (event) => {
        if (!event.dataTransfer.types.includes(MIME)) return;
        event.preventDefault();
        event.stopPropagation();
        setDrop(null);
        if (active) return;
        const source = JSON.parse(event.dataTransfer.getData(MIME));
        if (source.account !== account || source.bucket !== bucket)
          throw Error("Use Transferir para mover entre contas ou buckets.");
        await watch(
          await call("move-many", {
            ...where,
            keys: source.keys,
            target: destination,
          }),
          "Mover objetos",
        );
      }),
    };
  }
  if (sub === "about")
    return (
      <About>
        <Text>
          Configure as contas em Configurações → Object Storage. Escolha conta e
          bucket para navegar, enviar arquivos/pastas, baixar, copiar, mover ou
          excluir objetos. Arraste itens para pastas, Voltar ou o caminho para
          movê-los. No desktop prepare o arquivo pelo ícone de arraste; depois
          segure esse ícone para copiar ao Explorer/área de trabalho. No
          navegador use Baixar. Link usa a URL pública configurada, sem tornar
          objetos privados públicos. S3 informa modificação; não há data
          universal de criação. Credenciais ficam no conector e no cofre do
          sistema.
        </Text>
      </About>
    );
  return (
    <Stack>
      <Paper withBorder p="lg" style={{ borderColor: color }}>
        <Group align="end">
          <Select
            label="Conta"
            data={accounts.map((a) => ({ value: a.id, label: a.name }))}
            value={account || null}
            onChange={changeAccount}
            disabled={active}
          />
          <Select
            label="Bucket"
            data={buckets}
            value={bucket || null}
            disabled={active}
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
            disabled={active || !bucket}
            onClick={() => files.current.click()}
          />
          <Icon
            icon={Folder}
            label="Enviar pasta"
            disabled={active || !bucket}
            onClick={() => directory.current.click()}
          />
          <Icon
            icon={Trash2}
            label="Excluir selecionados"
            disabled={!selected.length || active}
            onClick={() => remove(selected)}
          />
        </Group>
        <Group gap="xs" mt="md" aria-label="Caminho do bucket">
          <Anchor
            component="button"
            onClick={() => setPrefix("")}
            {...dropProps("")}
          >
            {bucket || "Selecione um bucket"}
          </Anchor>
          {prefix
            .split("/")
            .filter(Boolean)
            .map((part, index, parts) => {
              const path = parts.slice(0, index + 1).join("/") + "/";
              return (
                <React.Fragment key={path}>
                  <Text span>/</Text>
                  {index === parts.length - 1 ? (
                    <Text span>{part}</Text>
                  ) : (
                    <Anchor
                      component="button"
                      onClick={() => setPrefix(path)}
                      {...dropProps(path)}
                    >
                      {part}
                    </Anchor>
                  )}
                </React.Fragment>
              );
            })}
        </Group>
      </Paper>
      <Paper
        withBorder
        p="md"
        style={{ borderColor: color }}
        onDragOver={(event) => {
          if (event.dataTransfer.types.includes("Files"))
            event.preventDefault();
        }}
        onDrop={safe((event) => {
          if (event.dataTransfer.types.includes(MIME)) return;
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
              <Table.Th>Modificado em</Table.Th>
              <Table.Th>Ações</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {prefix && (
              <Table.Tr
                {...dropProps(parent)}
                style={{
                  background: drop === parent ? color + "33" : undefined,
                }}
              >
                <Table.Td />
                <Table.Td colSpan={4}>
                  <Button
                    variant="subtle"
                    leftSection={<ArrowUp size={16} />}
                    onClick={() => setPrefix(parent)}
                  >
                    .. / Voltar
                  </Button>
                </Table.Td>
              </Table.Tr>
            )}
            {[
              ...page.folders.map((key) => ({ key, folder: true })),
              ...page.objects,
            ].map((item) => (
              <Table.Tr
                key={item.key}
                draggable={!active}
                onDragStart={(event) => dragStart(event, item)}
                onDragEnd={() => setDrop(null)}
                {...(item.folder ? dropProps(item.key) : {})}
                style={{
                  borderBottom: `1px solid ${color}55`,
                  background: drop === item.key ? color + "33" : undefined,
                }}
              >
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
                    leftSection={item.folder ? <Folder size={16} /> : null}
                    onClick={safe(async () => {
                      if (item.folder) setPrefix(item.key);
                      else {
                        setOpening(item);
                      }
                    })}
                  >
                    {item.key.slice(prefix.length)}
                  </Button>
                </Table.Td>
                <Table.Td>
                  {item.folder
                    ? "—"
                    : ((item.size || 0) / 1024).toFixed(1) + " KiB"}
                </Table.Td>
                <Table.Td>
                  {item.modified
                    ? new Date(item.modified).toLocaleString()
                    : "—"}
                </Table.Td>
                <Table.Td>
                  <Group gap={2}>
                    {!item.folder && state.native && (
                      <Icon
                        icon={GripVertical}
                        label={
                          prepared[localIdentity(item)]
                            ? "Segure e arraste para copiar ao computador"
                            : "Preparar arquivo para arrastar ao computador"
                        }
                        disabled={active}
                        onMouseDown={
                          prepared[localIdentity(item)]
                            ? safe((event) => {
                                event.preventDefault();
                                event.stopPropagation();
                                return call("drag-local", {
                                  token: prepared[localIdentity(item)].token,
                                });
                              })
                            : undefined
                        }
                        onClick={
                          prepared[localIdentity(item)]
                            ? () => {}
                            : () => prepare(item)
                        }
                      />
                    )}
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
      {active && (
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
        opened={!!opening}
        onClose={() => setOpening(null)}
        title={opening?.key}
      >
        <Text mb="md">Como deseja abrir este arquivo?</Text>
        <Group>
          <Button
            disabled={!state.native || active}
            onClick={safe(async () => {
              const item = opening;
              setOpening(null);
              await prepare(item, true);
            })}
          >
            Abrir
          </Button>
          <Button
            onClick={safe(async () => {
              const result = await call("public-link", {
                ...where,
                key: opening.key,
              });
              await copy(result.url);
              setOpening(null);
            })}
          >
            Link
          </Button>
          <Button
            onClick={safe(async () => {
              const result = await call("public-link", {
                ...where,
                key: opening.key,
              });
              window.open(result.url, "_blank", "noopener");
              setOpening(null);
            })}
          >
            Navegador
          </Button>
          <Button variant="subtle" onClick={() => setOpening(null)}>
            Cancelar
          </Button>
        </Group>
        {!state.native && (
          <Text size="xs">
            Abrir localmente requer a janela desktop da PIA.
          </Text>
        )}
      </Modal>
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
              const operation = transfer;
              setTransfer(null);
              await watch(
                await call(operation.action, {
                  ...where,
                  key: operation.key,
                  target: target.key,
                  target_account: target.account,
                  target_bucket: target.bucket,
                }),
                operation.key,
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
