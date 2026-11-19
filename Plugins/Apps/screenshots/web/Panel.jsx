import { fingerprint } from "../../../../src/pia/frontend/forms";
import React, { useState, useRef, useEffect, useCallback } from "react";
import {
  Alert,
  Badge,
  Button,
  ColorInput,
  Group,
  Kbd,
  Modal,
  NumberInput,
  Paper,
  SegmentedControl,
  SimpleGrid,
  Skeleton,
  Slider,
  Stack,
  Switch,
  Text,
  Title,
} from "@mantine/core";
import {
  Camera,
  Monitor,
  Copy,
  Plus,
  Minus,
  Trash2,
  CheckSquare,
  ExternalLink,
  Folder,
  RotateCcw,
} from "lucide-react";
import { appApi, safe, report } from "../../../../src/pia/frontend/api";
import { notify } from "../../../../src/pia/frontend/toasts";
import { Icon, About, usePia } from "../../../../src/pia/frontend/shared";

const call = (action, data = {}) => appApi("screenshots", action, data);

const KEY_LABELS = {
  ctrl: "Ctrl",
  control: "Ctrl",
  alt: "Alt",
  shift: "Shift",
  super: "Win",
  win: "Win",
  meta: "Win",
  print_screen: "Print Screen",
  space: "Espaço",
  enter: "Enter",
  tab: "Tab",
  backspace: "Backspace",
  delete: "Delete",
  insert: "Insert",
  home: "Home",
  end: "End",
  page_up: "Page Up",
  page_down: "Page Down",
  up: "Seta cima",
  down: "Seta baixo",
  left: "Seta esquerda",
  right: "Seta direita",
};

function formatShortcut(value) {
  if (!value) return "Desativado";
  return String(value)
    .split("+")
    .map((part) => part.trim().toLowerCase())
    .filter(Boolean)
    .map((token) => {
      if (KEY_LABELS[token]) return KEY_LABELS[token];
      if (token.length === 1) return token.toUpperCase();
      if (/^f\d+$/.test(token)) return token.toUpperCase();
      return token.charAt(0).toUpperCase() + token.slice(1);
    })
    .join(" + ");
}

function normalizeShortcutKey(value) {
  if (!value) return "";
  const aliases = { control: "ctrl", win: "super", meta: "super" };
  const parts = String(value)
    .split("+")
    .map((p) => p.trim().toLowerCase())
    .filter(Boolean);
  if (!parts.length) return "";
  const mods = [...new Set(parts.slice(0, -1).map((m) => aliases[m] || m))].sort();
  const key = parts[parts.length - 1];
  return [...mods, key].join("+");
}

function eventToShortcut(event) {
  if (event.key === "Escape") return { cancelled: true };
  const modifierKeys = new Set([
    "Control",
    "Alt",
    "Shift",
    "Meta",
    "OS",
    "AltGraph",
  ]);
  if (modifierKeys.has(event.key)) return { modifierOnly: true };

  const mods = [];
  if (event.ctrlKey) mods.push("ctrl");
  if (event.altKey) mods.push("alt");
  if (event.shiftKey) mods.push("shift");
  if (event.metaKey) mods.push("super");

  let key = "";
  const code = event.code || "";
  if (code === "PrintScreen" || event.key === "PrintScreen") {
    key = "print_screen";
  } else if (code === "Space" || event.key === " ") {
    key = "space";
  } else if (/^Key([A-Z])$/.test(code)) {
    key = code.slice(3).toLowerCase();
  } else if (/^Digit([0-9])$/.test(code)) {
    key = code.slice(5);
  } else if (/^F(\d{1,2})$/.test(code)) {
    key = code.toLowerCase();
  } else if (code === "ArrowUp") {
    key = "up";
  } else if (code === "ArrowDown") {
    key = "down";
  } else if (code === "ArrowLeft") {
    key = "left";
  } else if (code === "ArrowRight") {
    key = "right";
  } else if (code === "PageUp") {
    key = "page_up";
  } else if (code === "PageDown") {
    key = "page_down";
  } else if (event.key && event.key.length === 1) {
    key = event.key.toLowerCase();
  } else if (event.key) {
    key = event.key.toLowerCase().replace(/\s+/g, "_");
  }

  if (!key) return { modifierOnly: true };
  return { shortcut: [...mods, key].join("+") };
}

function ShortcutRecorder({
  label,
  value,
  defaultValue,
  savedValue,
  reloadStatus,
  conflictCheck,
  onChange,
  disabled,
}) {
  const [listening, setListening] = useState(false);
  const [error, setError] = useState("");
  const boxRef = useRef(null);

  useEffect(() => {
    if (listening && boxRef.current) boxRef.current.focus();
  }, [listening]);

  const handleKeyDown = (event) => {
    if (!listening) return;
    event.preventDefault();
    event.stopPropagation();
    const parsed = eventToShortcut(event);
    if (parsed.cancelled) {
      setListening(false);
      setError("");
      return;
    }
    if (parsed.modifierOnly) {
      setError("Inclua uma tecla além de Ctrl, Alt, Shift ou Win.");
      return;
    }
    const conflictLabel = conflictCheck(parsed.shortcut);
    if (conflictLabel) {
      setError(
        `Este atalho já é usado por "${conflictLabel}". Escolha outro.`,
      );
      return;
    }
    setError("");
    setListening(false);
    onChange(parsed.shortcut);
  };

  const dirty = value !== savedValue;
  const isDefault =
    normalizeShortcutKey(value) === normalizeShortcutKey(defaultValue);

  return (
    <Stack gap={4}>
      <Group justify="space-between" align="center" wrap="wrap" gap="sm">
        <Text size="sm" fw={500}>
          {label}
        </Text>
        <Group gap="xs" wrap="nowrap">
          <div
            ref={boxRef}
            tabIndex={listening ? 0 : -1}
            role="status"
            aria-live="polite"
            onKeyDown={handleKeyDown}
            onBlur={() => setListening(false)}
            style={{
              padding: "4px 10px",
              borderRadius: 6,
              border: listening
                ? "2px solid var(--mantine-color-violet-5)"
                : "1px solid var(--mantine-color-default-border)",
              minWidth: 180,
              outline: "none",
            }}
          >
            {listening ? (
              <Text size="xs" c="violet">
                Pressione a nova combinação… (Esc cancela)
              </Text>
            ) : (
              <Kbd size="sm">{formatShortcut(value)}</Kbd>
            )}
          </div>
          <Button
            size="xs"
            variant={listening ? "filled" : "default"}
            disabled={disabled}
            onClick={() => {
              setError("");
              setListening((old) => !old);
            }}
          >
            {listening ? "Cancelar" : "Alterar"}
          </Button>
          <Icon
            icon={RotateCcw}
            label="Restaurar padrão"
            disabled={disabled || isDefault}
            onClick={() => {
              const conflictLabel = conflictCheck(defaultValue);
              if (conflictLabel) {
                setError(
                  `Este atalho já é usado por "${conflictLabel}". Escolha outro.`,
                );
                return;
              }
              setError("");
              setListening(false);
              onChange(defaultValue);
            }}
          />
        </Group>
      </Group>
      {error && (
        <Text size="xs" c="red">
          {error}
        </Text>
      )}
      {!error && dirty && (
        <Text size="xs" c="dimmed">
          Será aplicado ao salvar.
        </Text>
      )}
      {!error && !dirty && reloadStatus && (
        <Group gap="xs">
          {reloadStatus.mode === "hot-reload" && reloadStatus.ok && (
            <Badge color="green" variant="light" size="sm">
              Atalho ativo agora.
            </Badge>
          )}
          {reloadStatus.mode === "gnome" && (
            <Badge color="yellow" variant="light" size="sm">
              Atalho salvo. No GNOME, reaplique os atalhos do sistema para ele
              funcionar.
            </Badge>
          )}
          {(reloadStatus.mode === "restart-required" || !reloadStatus.ok) &&
            reloadStatus.mode !== "gnome" && (
              <Badge color="yellow" variant="light" size="sm">
                Atalho salvo. Reinicie a PIA para ativá-lo.
              </Badge>
            )}
        </Group>
      )}
    </Stack>
  );
}

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
  const { navigate } = usePia();
  const [items, setItems] = useState([]),
    [folder, setFolder] = useState(""),
    [folderWarning, setFolderWarning] = useState(""),
    [total, setTotal] = useState(0),
    [galleryLoading, setGalleryLoading] = useState(true),
    [galleryError, setGalleryError] = useState(""),
    [selected, setSelected] = useState([]),
    [preview, setPreview] = useState(null),
    [image, setImage] = useState(""),
    [zoom, setZoom] = useState(1);

  const [config, setConfig] = useState(null),
    [savedConfig, setSavedConfig] = useState(null),
    [configLoading, setConfigLoading] = useState(false),
    [configError, setConfigError] = useState(""),
    [choosingFolder, setChoosingFolder] = useState(false),
    [saving, setSaving] = useState(false);

  const [shortcutsMeta, setShortcutsMeta] = useState(null),
    [shortcutsForm, setShortcutsForm] = useState({
      screenshot: "print_screen",
      screenshot_window: "alt+print_screen",
    }),
    [savedShortcuts, setSavedShortcuts] = useState({
      screenshot: "print_screen",
      screenshot_window: "alt+print_screen",
    }),
    [shortcutsLoading, setShortcutsLoading] = useState(false),
    [shortcutsError, setShortcutsError] = useState(""),
    [reloadStatus, setReloadStatus] = useState(null);

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
      setGalleryError("");
      setGalleryLoading(true);
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
      setFolder(page.folder || "");
      setFolderWarning(page.folder_warning || "");
      setGalleryError("");
    } catch (err) {
      if (generation === version.current) {
        setGalleryError(err?.message || "Erro ao listar capturas.");
      }
    } finally {
      if (generation === version.current) {
        loading.current = false;
        setGalleryLoading(false);
      }
    }
  }, []);

  const loadShortcuts = useCallback(async () => {
    setShortcutsLoading(true);
    setShortcutsError("");
    try {
      const data = await call("shortcuts");
      setShortcutsMeta(data);
      const next = {
        screenshot: data.screenshot || "",
        screenshot_window: data.screenshot_window || "",
      };
      setShortcutsForm(next);
      setSavedShortcuts(next);
    } catch (err) {
      setShortcutsError(err?.message || "Falha ao ler atalhos.");
    } finally {
      setShortcutsLoading(false);
    }
  }, []);

  const loadConfig = useCallback(async () => {
    setConfigLoading(true);
    setConfigError("");
    try {
      const value = await call("config");
      setConfig(value);
      setSavedConfig(value);
    } catch (err) {
      setConfig(null);
      setConfigError(err?.message || "Erro desconhecido.");
    } finally {
      setConfigLoading(false);
    }
  }, []);

  useEffect(() => {
    load(true);
    loadShortcuts();
    const channel = new BroadcastChannel("pia:apps");
    channel.onmessage = (event) => {
      if (event.data?.type === "screenshots:changed") load(true);
    };
    return () => channel.close();
  }, [load, loadShortcuts]);

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
    if (sub === "settings") {
      setReloadStatus(null);
      loadConfig();
      loadShortcuts();
    }
  }, [sub, loadConfig, loadShortcuts]);

  async function open(name) {
    setPreview(name);
    setImage("");
    setZoom(1);
    const result = await call("saved-image", { name });
    setImage(result.data);
  }

  const openSettings = () =>
    navigate?.({ view: "app", app: "screenshots", sub: "settings" });

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

  if (sub === "settings") {
    if (configLoading && !config) {
      return (
        <Stack>
          <Text size="sm" c="dimmed">
            Carregando preferências…
          </Text>
          <Skeleton height={150} radius="md" />
          <Skeleton height={180} radius="md" />
        </Stack>
      );
    }
    if (configError || !config) {
      return (
        <Paper withBorder p="lg">
          <Stack gap="sm">
            <Alert
              color="red"
              title="Não foi possível carregar as preferências da captura."
            >
              {configError}
            </Alert>
            <Group>
              <Button onClick={() => loadConfig()}>Tentar novamente</Button>
            </Group>
          </Stack>
        </Paper>
      );
    }

    const defaultFolder = config.default_output_folder || "";
    const isDefaultFolder =
      !config.output_folder ||
      (defaultFolder && config.output_folder === defaultFolder);
    const folderChanged =
      savedConfig && config.output_folder !== savedConfig.output_folder;

    const colorValid = /^#[0-9a-fA-F]{6}$/.test(config.default_color || "");
    const widthNum = Number(config.default_width);
    const widthValid =
      Number.isInteger(widthNum) && widthNum >= 1 && widthNum <= 80;

    const configDirty =
      savedConfig && fingerprint(config) !== fingerprint(savedConfig);
    const shortcutsDirty =
      !shortcutsError &&
      fingerprint(shortcutsForm) !== fingerprint(savedShortcuts);
    const hasChanges = !!(configDirty || shortcutsDirty);

    const checkConflict = (field, candidate) => {
      const norm = normalizeShortcutKey(candidate);
      if (!norm) return null;
      const otherField =
        field === "screenshot" ? "screenshot_window" : "screenshot";
      const otherFieldLabel =
        otherField === "screenshot"
          ? "Capturar região"
          : "Capturar janela ativa";
      if (normalizeShortcutKey(shortcutsForm[otherField]) === norm) {
        return otherFieldLabel;
      }
      const others = shortcutsMeta?.others || {};
      for (const info of Object.values(others)) {
        if (info?.shortcut && normalizeShortcutKey(info.shortcut) === norm) {
          return info.label || info.shortcut;
        }
      }
      return null;
    };

    const handleSave = async () => {
      if (!colorValid || !widthValid) return;
      setSaving(true);
      try {
        let updatedConfig = config;
        const outputChanged =
          savedConfig && config.output_folder !== savedConfig.output_folder;
        if (configDirty) {
          const res = await call("save-config", { value: config });
          updatedConfig = res.config || config;
          setConfig(updatedConfig);
          setSavedConfig(updatedConfig);
        }
        if (shortcutsDirty) {
          const res = await call("save-shortcuts", shortcutsForm);
          if (res.shortcuts) {
            const next = {
              screenshot: res.shortcuts.screenshot || "",
              screenshot_window: res.shortcuts.screenshot_window || "",
            };
            setShortcutsMeta(res.shortcuts);
            setShortcutsForm(next);
            setSavedShortcuts(next);
          } else {
            setSavedShortcuts(shortcutsForm);
          }
          setReloadStatus(res.reload || { ok: true, mode: "restart-required" });
        }
        if (outputChanged) {
          new BroadcastChannel("pia:apps").postMessage({
            type: "screenshots:changed",
          });
          notify(
            `Preferências salvas. Novas capturas vão para ${updatedConfig.output_folder}.`,
          );
        } else {
          notify("Preferências salvas.");
        }
      } catch (err) {
        notify(
          "Não foi possível salvar as preferências. Nada foi alterado." +
            (err?.message ? " " + err.message : ""),
          "error",
        );
      } finally {
        setSaving(false);
      }
    };

    const handleDiscard = () => {
      if (savedConfig) setConfig(savedConfig);
      setShortcutsForm(savedShortcuts);
    };

    return (
      <Stack pb={hasChanges ? 72 : 0}>
        <Paper withBorder p="lg" id="arquivo-e-pasta">
          <Stack gap="md">
            <Title order={4}>Arquivo e pasta</Title>
            <Stack gap={4}>
              <Text size="sm" fw={500}>
                Formato do arquivo
              </Text>
              <SegmentedControl
                value={config.format}
                onChange={(format) => setConfig({ ...config, format })}
                data={[
                  { label: "PNG", value: "png" },
                  { label: "JPG", value: "jpg" },
                  { label: "BMP", value: "bmp" },
                ]}
              />
            </Stack>

            <Stack gap={6}>
              <Text size="sm" fw={500}>
                Qualidade do JPG
              </Text>
              <Group align="center" gap="md" wrap="nowrap">
                <Slider
                  style={{ flex: 1 }}
                  min={1}
                  max={100}
                  disabled={config.format !== "jpg"}
                  value={Number(config.quality) || 92}
                  onChange={(quality) => setConfig({ ...config, quality })}
                  marks={[
                    { value: 50, label: "50" },
                    { value: 75, label: "75" },
                    { value: 92, label: "92" },
                    { value: 100, label: "100" },
                  ]}
                />
                <NumberInput
                  w={84}
                  min={1}
                  max={100}
                  disabled={config.format !== "jpg"}
                  value={Number(config.quality) || 92}
                  onChange={(val) => {
                    if (typeof val === "number" && !Number.isNaN(val)) {
                      setConfig({
                        ...config,
                        quality: Math.max(1, Math.min(100, Math.round(val))),
                      });
                    }
                  }}
                />
              </Group>
              <Text size="xs" c="dimmed" mt="xs">
                {config.format === "jpg"
                  ? "Valores maiores geram arquivos maiores e mais nítidos."
                  : "A qualidade só vale para JPG."}
              </Text>
            </Stack>

            <Stack gap={6}>
              <Group gap="xs" align="center">
                <Text size="sm" fw={500}>
                  Pasta de destino
                </Text>
                {isDefaultFolder && (
                  <Badge size="xs" variant="light">
                    Padrão
                  </Badge>
                )}
              </Group>
              <Text size="sm" style={{ overflowWrap: "anywhere" }}>
                {config.output_folder}
              </Text>
              {folderChanged && (
                <Text size="xs" c="violet">
                  Será usada depois de salvar.
                </Text>
              )}
              <Group gap="xs">
                <Button
                  size="xs"
                  variant="default"
                  loading={choosingFolder}
                  onClick={safe(async () => {
                    setChoosingFolder(true);
                    try {
                      const res = await call("choose-folder");
                      if (res?.folder) {
                        setConfig({ ...config, output_folder: res.folder });
                      }
                    } finally {
                      setChoosingFolder(false);
                    }
                  })}
                >
                  {choosingFolder
                    ? "Abrindo seletor de pasta…"
                    : "Escolher pasta…"}
                </Button>
                <Button
                  size="xs"
                  variant="subtle"
                  disabled={isDefaultFolder || !defaultFolder}
                  onClick={() =>
                    setConfig({ ...config, output_folder: defaultFolder })
                  }
                >
                  Restaurar pasta padrão
                </Button>
              </Group>
              <Text size="xs" c="dimmed">
                Ao trocar de pasta, as capturas antigas continuam na pasta
                anterior.
              </Text>
            </Stack>
          </Stack>
        </Paper>

        <Paper withBorder p="lg" id="comportamento">
          <Stack gap="md">
            <Title order={4}>Comportamento</Title>
            {[
              [
                "auto_save",
                "Salvar automaticamente",
                "Salva a captura na pasta de destino ao concluir.",
              ],
              [
                "auto_copy",
                "Copiar automaticamente",
                "Copia a captura para a área de transferência ao concluir.",
              ],
              [
                "prefill_title",
                "Usar o título da janela",
                "Preenche o título da captura com o nome da janela ativa.",
              ],
              [
                "prefill_url",
                "Obter o endereço do navegador",
                "Quando a janela é um navegador, guarda o endereço da página.",
              ],
              [
                "border",
                "Adicionar borda",
                "Desenha uma borda em volta da imagem salva.",
              ],
            ].map(([key, label, description]) => (
              <Switch
                key={key}
                label={label}
                description={description}
                checked={!!config[key]}
                onChange={(event) =>
                  setConfig({ ...config, [key]: event.currentTarget.checked })
                }
              />
            ))}
          </Stack>
        </Paper>

        <Paper withBorder p="lg" id="atalhos">
          <Stack gap="md">
            <Title order={4}>Atalhos de captura</Title>
            {shortcutsLoading && !shortcutsMeta ? (
              <Text size="sm" c="dimmed">
                Lendo atalhos…
              </Text>
            ) : shortcutsError ? (
              <Alert color="yellow">
                Não foi possível ler o arquivo de atalhos. Nada foi alterado.
                Revise em Configurações &gt; Ativação e atalhos.
              </Alert>
            ) : (
              <>
                <ShortcutRecorder
                  label="Capturar região"
                  value={shortcutsForm.screenshot}
                  defaultValue={
                    shortcutsMeta?.defaults?.screenshot || "print_screen"
                  }
                  savedValue={savedShortcuts.screenshot}
                  reloadStatus={reloadStatus}
                  disabled={saving}
                  conflictCheck={(cand) => checkConflict("screenshot", cand)}
                  onChange={(val) =>
                    setShortcutsForm((old) => ({ ...old, screenshot: val }))
                  }
                />
                <ShortcutRecorder
                  label="Capturar janela ativa"
                  value={shortcutsForm.screenshot_window}
                  defaultValue={
                    shortcutsMeta?.defaults?.screenshot_window ||
                    "alt+print_screen"
                  }
                  savedValue={savedShortcuts.screenshot_window}
                  reloadStatus={reloadStatus}
                  disabled={saving}
                  conflictCheck={(cand) =>
                    checkConflict("screenshot_window", cand)
                  }
                  onChange={(val) =>
                    setShortcutsForm((old) => ({
                      ...old,
                      screenshot_window: val,
                    }))
                  }
                />
              </>
            )}
            <Text size="xs" c="dimmed">
              Os outros atalhos da PIA ficam em Configurações &gt; Ativação e
              atalhos e não são alterados aqui.
            </Text>
          </Stack>
        </Paper>

        <Paper withBorder p="lg" id="editor">
          <Stack gap="md">
            <Title order={4}>Editor</Title>
            <Stack gap={4}>
              <Text size="sm" fw={500}>
                Ferramenta inicial
              </Text>
              <SegmentedControl
                value={config.default_tool || "free"}
                onChange={(default_tool) =>
                  setConfig({ ...config, default_tool })
                }
                data={[
                  { label: "Mão livre", value: "free" },
                  { label: "Retângulo", value: "rect" },
                ]}
              />
            </Stack>

            <ColorInput
              label="Cor inicial da anotação"
              format="hex"
              value={config.default_color || "#ff4278"}
              error={!colorValid ? "Use uma cor no formato #RRGGBB." : null}
              onChange={(default_color) =>
                setConfig({ ...config, default_color })
              }
            />

            <NumberInput
              label="Espessura inicial"
              min={1}
              max={80}
              suffix=" px"
              value={config.default_width ?? 3}
              error={!widthValid ? "Use um valor de 1 a 80 px." : null}
              onChange={(default_width) =>
                setConfig({ ...config, default_width })
              }
            />

            <Switch
              label="Suavização ao ampliar"
              checked={config.smooth !== false}
              onChange={(event) =>
                setConfig({ ...config, smooth: event.currentTarget.checked })
              }
            />

            <Switch
              label="Copiar cor em BBGGRR"
              description="Use quando o destino espera a ordem azul-verde-vermelho."
              checked={!!config.bgr}
              onChange={(event) =>
                setConfig({ ...config, bgr: event.currentTarget.checked })
              }
            />
          </Stack>
        </Paper>

        {hasChanges && (
          <Paper
            withBorder
            p="sm"
            shadow="md"
            style={{ position: "sticky", bottom: 12, zIndex: 10 }}
          >
            <Group justify="space-between" wrap="wrap" gap="sm">
              <Text size="sm" fw={500}>
                Você tem alterações não salvas.
              </Text>
              <Group gap="xs">
                <Button
                  variant="subtle"
                  disabled={saving}
                  onClick={handleDiscard}
                >
                  Descartar alterações
                </Button>
                <Button
                  loading={saving}
                  disabled={!colorValid || !widthValid}
                  onClick={handleSave}
                >
                  {saving ? "Salvando…" : "Salvar preferências"}
                </Button>
              </Group>
            </Group>
          </Paper>
        )}
      </Stack>
    );
  }

  const regionShortcut = formatShortcut(
    shortcutsForm.screenshot || "print_screen",
  );
  const windowShortcut = formatShortcut(
    shortcutsForm.screenshot_window || "alt+print_screen",
  );

  return (
    <Stack>
      <Paper withBorder p="lg">
        <Group>
          <Button
            leftSection={<Camera size={17} />}
            onClick={safe(() => call("capture", { mode: "selection" }))}
          >
            Capturar região · {regionShortcut}
          </Button>
          <Button
            leftSection={<Monitor size={17} />}
            onClick={safe(() => call("capture", { mode: "window" }))}
          >
            Janela ativa · {windowShortcut}
          </Button>
        </Group>
      </Paper>
      <Group justify="space-between" wrap="nowrap">
        <Title order={4}>Capturas salvas</Title>
        <Group gap={6} wrap="nowrap">
          <Text
            size="xs"
            c="dimmed"
            ta="right"
            style={{ overflowWrap: "anywhere" }}
          >
            {folder}
          </Text>
          <Icon icon={Folder} label="Alterar pasta" onClick={openSettings} />
        </Group>
      </Group>
      {folderWarning && <Alert color="yellow">{folderWarning}</Alert>}
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
      {galleryLoading && items.length === 0 ? (
        <SimpleGrid cols={{ base: 2, sm: 3, lg: 4 }}>
          {Array.from({ length: 8 }).map((_, idx) => (
            <Skeleton key={idx} height={160} radius="sm" />
          ))}
        </SimpleGrid>
      ) : galleryError ? (
        <Paper withBorder p="lg">
          <Stack gap="sm">
            <Alert color="red">
              Não foi possível listar as capturas desta pasta.
            </Alert>
            <Group gap="xs">
              <Button size="xs" onClick={() => load(true)}>
                Tentar novamente
              </Button>
              <Button size="xs" variant="subtle" onClick={openSettings}>
                Alterar pasta
              </Button>
            </Group>
          </Stack>
        </Paper>
      ) : items.length === 0 ? (
        <Paper withBorder p="lg">
          <Text size="sm" c="dimmed">
            Nenhuma captura nesta pasta ainda. Use {regionShortcut} ou os botões
            acima.
          </Text>
        </Paper>
      ) : (
        <>
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
                  setSelected((old) =>
                    old.filter((name) => name !== item.name),
                  );
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
        </>
      )}
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
