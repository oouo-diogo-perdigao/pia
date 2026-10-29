import { fingerprint } from "../../../../src/pia/frontend/forms";
import React, { useState, useRef, useEffect, useCallback } from "react";
import {
  Button,
  Group,
  Paper,
  Text,
  Title,
  Modal,
  Select,
  TextInput,
  Switch,
  Stack,
  SimpleGrid,
  Image,
} from "@mantine/core";
import {
  Camera,
  Monitor,
  Copy,
  X,
  Plus,
  Minus,
  Trash2,
  CheckSquare,
  ExternalLink,
  Folder,
} from "lucide-react";
import { appApi, safe, report } from "../../../../src/pia/frontend/api";
import { Icon, About } from "../../../../src/pia/frontend/shared";
const call = (action, data = {}) => appApi("screenshots", action, data);
function Capture({ item, onDelete, onSelect, selected, onPreview }) {
  const [src, setSrc] = useState("");
  useEffect(() => {
    let active = true;
    call("saved-image", { name: item.name, thumbnail: true })
      .then((result) => {
        if (active) setSrc(result.data);
      })
      .catch(report);
    return () => {
      active = false;
    };
  }, [item.name]);
  return (
    <Paper
      withBorder
      className={"capture-card" + (selected ? " selected" : "")}
      p="xs"
    >
      <button className="capture-image" onClick={() => onPreview(item.name)}>
        <img src={src} alt={item.name} loading="lazy" />
      </button>
      <Text size="xs" truncate>
        {item.name}
      </Text>
      <Group gap={4}>
        <Icon
          icon={Trash2}
          label="Excluir captura"
          confirm
          onClick={onDelete}
        />
        <Icon
          icon={CheckSquare}
          label="Selecionar captura"
          onClick={onSelect}
        />
        <Icon
          icon={ExternalLink}
          label="Abrir no sistema"
          onClick={() => call("open-saved", { name: item.name })}
        />
      </Group>
    </Paper>
  );
}
export default function Screenshots({ sub = "principal" }) {
  const [items, setItems] = useState([]),
    [folder, setFolder] = useState(""),
    [total, setTotal] = useState(0),
    [selected, setSelected] = useState([]),
    [preview, setPreview] = useState(null),
    [image, setImage] = useState(""),
    [zoom, setZoom] = useState(1),
    [config, setConfig] = useState(null),
    [saved, setSaved] = useState("");
  const sentinel = useRef(),
    offset = useRef(0),
    loading = useRef(false),
    version = useRef(0);
  const load = useCallback(async (reset = false) => {
    if (loading.current && !reset) return;
    if (reset) {
      version.current++;
      offset.current = 0;
      setItems([]);
    }
    const generation = version.current;
    loading.current = true;
    try {
      const page = await call("list-saved", {
        offset: offset.current,
        limit: 24,
      });
      if (generation !== version.current) return;
      setItems((old) => (reset ? page.captures : [...old, ...page.captures]));
      offset.current += page.captures.length;
      setTotal(page.total);
      setFolder(page.folder);
    } finally {
      if (generation === version.current) loading.current = false;
    }
  }, []);
  useEffect(() => {
    load(true).catch(report);
    const channel = new BroadcastChannel("pia:apps");
    channel.onmessage = (event) => {
      if (event.data?.type === "screenshots:changed") load(true).catch(report);
    };
    return () => channel.close();
  }, [load]);
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && offset.current < total)
          load().catch(report);
      },
      { rootMargin: "200px" },
    );
    if (sentinel.current) observer.observe(sentinel.current);
    return () => observer.disconnect();
  }, [load, total, items.length]);
  useEffect(() => {
    if (sub === "settings")
      call("config")
        .then((value) => {
          setConfig(value);
          setSaved(fingerprint(value));
        })
        .catch(report);
  }, [sub]);
  async function open(name) {
    setPreview(name);
    setImage("");
    setZoom(1);
    const result = await call("saved-image", { name });
    setImage(result.data);
  }
  if (sub === "about")
    return (
      <About>
        <Text>
          Arraste com o botão esquerdo para recortar; Ctrl seleciona um
          retângulo. O botão direito desenha. Pressionar o outro botão cancela o
          gesto. Ctrl+roda amplia; o botão do meio copia a cor do pixel. Enter
          captura tudo, Esc cancela. A captura é salva na pasta configurada e
          copiada para a área de transferência. Sem uploads ou e-mail.
        </Text>
      </About>
    );
  if (sub === "settings")
    return config ? (
      <Paper withBorder p="lg">
        <Stack>
          <Select
            label="Formato"
            data={["png", "jpg", "bmp"]}
            value={config.format}
            onChange={(format) => setConfig({ ...config, format })}
          />
          <Group align="end" wrap="nowrap">
            <TextInput
              className="grow"
              label="Pasta de destino"
              value={config.output_folder}
              onChange={(event) =>
                setConfig({ ...config, output_folder: event.target.value })
              }
            />
            <Icon
              icon={Folder}
              label="Selecionar pasta"
              onClick={async () => {
                const result = await call("choose-folder");
                if (result.folder)
                  setConfig({ ...config, output_folder: result.folder });
              }}
            />
          </Group>
          {Object.entries({
            prefill_title: "Usar título da janela",
            prefill_url: "Obter URL do navegador",
            border: "Adicionar borda",
            auto_save: "Salvar automaticamente",
            auto_copy: "Copiar automaticamente",
          }).map(([key, label]) => (
            <Switch
              key={key}
              label={label}
              checked={!!config[key]}
              onChange={(event) =>
                setConfig({ ...config, [key]: event.currentTarget.checked })
              }
            />
          ))}
          <Button
            disabled={fingerprint(config) === saved}
            onClick={safe(async () => {
              await call("save-config", { value: config });
              setSaved(fingerprint(config));
            })}
          >
            Salvar preferências
          </Button>
        </Stack>
      </Paper>
    ) : (
      <Text>Carregando…</Text>
    );
  return (
    <Stack>
      <Paper withBorder p="lg">
        <Group>
          <Button
            leftSection={<Camera size={17} />}
            onClick={safe(() => call("capture", { mode: "selection" }))}
          >
            Capturar região · Print Screen
          </Button>
          <Button
            leftSection={<Monitor size={17} />}
            onClick={safe(() => call("capture", { mode: "window" }))}
          >
            Janela ativa
          </Button>
        </Group>
      </Paper>
      <Group justify="space-between" wrap="nowrap">
        <Title order={4}>Capturas salvas</Title>
        <Text
          size="xs"
          c="dimmed"
          ta="right"
          style={{ overflowWrap: "anywhere" }}
        >
          {folder}
        </Text>
      </Group>
      {selected.length > 0 && (
        <Group>
          <Text>{selected.length} selecionadas</Text>
          <Button variant="subtle" onClick={() => setSelected([])}>
            Cancelar
          </Button>
          <Icon
            icon={Trash2}
            label="Excluir selecionadas"
            danger
            onClick={async () => {
              await call("delete-saved", { names: selected });
              setSelected([]);
              await load(true);
            }}
          />
        </Group>
      )}
      <SimpleGrid cols={{ base: 2, sm: 3, lg: 4 }}>
        {items.map((item) => (
          <Capture
            key={item.name}
            item={item}
            selected={selected.includes(item.name)}
            onSelect={() =>
              setSelected((old) =>
                old.includes(item.name)
                  ? old.filter((name) => name !== item.name)
                  : [...old, item.name],
              )
            }
            onPreview={safe(open)}
            onDelete={async () => {
              await call("delete-saved", { names: [item.name] });
              setSelected((old) => old.filter((name) => name !== item.name));
              await load(true);
            }}
          />
        ))}
      </SimpleGrid>
      <div ref={sentinel}>
        <Text size="sm" c="dimmed">
          {items.length < total
            ? "Role para carregar mais"
            : "Todas as capturas carregadas"}
        </Text>
      </div>
      <Modal
        opened={!!preview}
        onClose={() => setPreview(null)}
        fullScreen
        title={preview}
        className="capture-preview"
      >
        <Group mb="sm">
          <Icon
            icon={Plus}
            label="Ampliar"
            onClick={() => setZoom((old) => Math.min(8, old * 1.25))}
          />
          <Icon
            icon={Minus}
            label="Reduzir"
            onClick={() => setZoom((old) => Math.max(0.1, old / 1.25))}
          />
          <Icon
            feedback
            icon={Copy}
            label="Copiar imagem"
            onClick={() => call("copy-saved", { name: preview })}
          />
        </Group>
        <div
          className="preview-viewport"
          onWheel={(event) => {
            if (event.ctrlKey) {
              event.preventDefault();
              setZoom((old) =>
                Math.max(
                  0.1,
                  Math.min(8, old * (event.deltaY < 0 ? 1.1 : 1 / 1.1)),
                ),
              );
            }
          }}
        >
          <img
            src={image}
            alt={preview || ""}
            style={{ width: zoom * 100 + "%" }}
          />
        </div>
      </Modal>
    </Stack>
  );
}
