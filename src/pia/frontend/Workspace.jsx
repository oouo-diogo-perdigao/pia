import { notify } from "./toasts";
import Connectors, { connectors } from "./Connectors";
import ToastCenter from "./ToastCenter";
import { Plug } from "lucide-react";
import React, { useState, useEffect, useRef } from "react";
import {
  Button,
  Group,
  Text,
  TextInput,
  Paper,
  Menu,
  Select,
  Modal,
  Stack,
  Checkbox,
  Loader,
  Overlay,
} from "@mantine/core";
import {
  MessageCircle,
  Bot,
  Settings,
  AudioLines,
  Camera,
  HardDrive,
  Grid2X2,
  Plus,
  FolderPlus,
  MoreHorizontal,
  Search,
  PanelLeftClose,
  PanelLeftOpen,
  ArrowLeft,
  ArrowRight,
  Pin,
  Archive,
  Trash2,
  Pencil,
  FolderInput,
  ExternalLink,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { api, session, safe, report } from "./api";
import { Context, Icon, Nav, ErrorAlert } from "./shared";
import { ScreenHistory } from "./navigation";
import Chat from "./Chat";
import SettingsPanel from "./Settings";
import Podcast from "../../../Plugins/Apps/podcast_automation/web/Panel.jsx";
import Screenshots from "../../../Plugins/Apps/screenshots/web/Panel.jsx";
import Storage from "../../../Plugins/Apps/object_storage/web/Panel.jsx";
import Secretary from "../../../Plugins/Bot/secretaria/web/Panel.jsx";
const appIcons = {
  podcast_automation: AudioLines,
  screenshots: Camera,
  object_storage: HardDrive,
};
function parseRoute() {
  try {
    return (
      JSON.parse(decodeURIComponent(location.hash.slice(1))) || { view: "chat" }
    );
  } catch {
    return { view: "chat" };
  }
}
function Avatar() {
  const [svg, setSvg] = useState(""),
    [colors, setColors] = useState({});
  useEffect(() => {
    fetch("/bots/secretaria/avatar.svg")
      .then((response) => response.text())
      .then(setSvg)
      .catch(() => {});
    api("/bots/secretaria")
      .then((data) => setColors(data.config))
      .catch(() => {});
  }, []);
  return (
    <span
      className="bot-avatar"
      style={{
        "--bot-primary": colors.avatar_primary,
        "--bot-accent": colors.avatar_accent,
        "--bot-eyes": colors.avatar_eyes,
      }}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}

export default function Workspace({ standalone = null }) {
  const [state, setState] = useState({
      chats: [],
      folders: [],
      apps: [],
      jobs: [],
    }),
    [route, setRoute] = useState(() => standalone || parseRoute()),
    [ready, setReady] = useState(false),
    [language, setLanguage] = useState("pt-BR"),
    [catalog, setCatalog] = useState({}),
    [collapsed, setCollapsed] = useState(false),
    [search, setSearch] = useState(""),
    [popup, setPopup] = useState(null),
    [rename, setRename] = useState(null),
    [renameText, setRenameText] = useState(""),
    [bulk, setBulk] = useState(null),
    [move, setMove] = useState(null),
    [moveFolder, setMoveFolder] = useState(""),
    [drop, setDrop] = useState(null),
    [restarting, setRestarting] = useState(false),
    [folded, setFolded] = useState({});
  const historyRef = useRef(new ScreenHistory(50)),
    routeRef = useRef(route),
    [historyVersion, setHistoryVersion] = useState(0);
  const t = (text) => catalog[text] || text;
  async function refresh() {
    const value = await api("/state");
    setState(value);
    return value;
  }
  function navigate(next) {
    if (JSON.stringify(next) === JSON.stringify(routeRef.current)) return;
    const entry = historyRef.current.push(next);
    window.history.pushState(
      { pia: entry.key },
      "",
      location.pathname + "#" + encodeURIComponent(JSON.stringify(next)),
    );
    routeRef.current = next;
    setRoute(next);
    setHistoryVersion((old) => old + 1);
    setPopup(null);
  }
  useEffect(() => {
    let active = true;
    session()
      .then(async () => {
        const [data, prefs] = await Promise.all([
          api("/state"),
          api("/preferences"),
        ]);
        if (!active) return;
        setState(data);
        setLanguage(prefs.language);
        setReady(true);
        const entry = historyRef.current.push(routeRef.current);
        window.history.replaceState(
          { pia: entry.key },
          "",
          location.pathname +
            "#" +
            encodeURIComponent(JSON.stringify(routeRef.current)),
        );
      })
      .catch(report);
    const pop = (event) => {
      const entry = historyRef.current.select(event.state?.pia);
      const next = entry?.route || { view: "chat" };
      routeRef.current = next;
      setRoute(next);
      setPopup(null);
      setHistoryVersion((old) => old + 1);
    };
    const mouse = (event) => {
      if (event.button === 3 || event.button === 4) {
        event.preventDefault();
        event.stopPropagation();
        event.button === 3 ? back() : forward();
      }
    };
    window.addEventListener("popstate", pop);
    window.addEventListener("pointerup", mouse);
    return () => {
      active = false;
      window.removeEventListener("popstate", pop);
      window.removeEventListener("pointerup", mouse);
    };
  }, []);
  useEffect(() => {
    fetch("/pia/lang/" + language + ".json")
      .then((response) => response.json())
      .then(setCatalog)
      .catch(report);
    document.documentElement.lang = language;
  }, [language]);
  useEffect(() => {
    const close = (event) => {
      if (!event.target.closest(".conversation-menu")) setPopup(null);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, []);
  const currentApp = state.apps.find((app) => app.id === route.app),
    currentChat = state.chats.find((chat) => chat.id === route.chat),
    title =
      route.view === "chat"
        ? currentChat?.title || "PIA"
        : route.view === "settings"
          ? t("Configurações")
          : route.view === "connectors"
            ? "Conectores / " +
              (connectors.find((c) => c.id === route.connector)?.name ||
                "Google")
            : route.view === "bots"
              ? "Bots / " + t("Secretária")
              : currentApp?.name || "PIA";
  useEffect(() => {
    document.title = title + " · PIA";
  }, [title]);
  function back() {
    if (historyRef.current.index > 0) window.history.back();
  }
  function forward() {
    if (historyRef.current.index < historyRef.current.entries.length - 1)
      window.history.forward();
  }
  async function newChat(folder) {
    const result = await api("/chat/new", folder ? { folder } : {});
    await refresh();
    navigate({ view: "chat", chat: result.id });
  }
  function menu(chat, event) {
    event.preventDefault();
    event.stopPropagation();
    setPopup({
      chat,
      x: Math.min(event.clientX, innerWidth - 240),
      y: Math.min(event.clientY, innerHeight - 70),
    });
  }
  async function updateChat(chat, fields) {
    await api("/chat/update", { chat: chat.id, ...fields });
    await refresh();
  }
  async function dropChat(event, folder) {
    event.preventDefault();
    setDrop(null);
    const chat = event.dataTransfer.getData("application/x-pia-chat");
    if (chat) {
      await api("/chat/update", { chat, folder });
      await refresh();
    }
  }
  function dropProps(folder) {
    return {
      onDragOver: (event) => {
        if (event.dataTransfer.types.includes("application/x-pia-chat")) {
          event.preventDefault();
          setDrop(folder ?? "unfiled");
        }
      },
      onDragLeave: () => setDrop(null),
      onDrop: safe((event) => dropChat(event, folder)),
    };
  }
  function beginRename(type, item) {
    setRename({ type, id: item.id });
    setRenameText(item.title || item.name);
    setPopup(null);
  }
  function renameInput(type, item) {
    return (
      <TextInput
        autoFocus
        value={renameText}
        onChange={(event) => setRenameText(event.target.value)}
        onBlur={() => setRename(null)}
        onKeyDown={safe(async (event) => {
          if (event.key === "Escape") setRename(null);
          if (event.key === "Enter") {
            event.preventDefault();
            if (type === "chat") await updateChat(item, { title: renameText });
            else {
              await api("/folder/save", { id: item.id, name: renameText });
              await refresh();
            }
            setRename(null);
          }
        })}
      />
    );
  }
  function chatRow(chat) {
    return (
      <div
        className={"chat-row" + (route.chat === chat.id ? " active" : "")}
        key={chat.id}
        draggable={!bulk}
        onDragStart={(event) =>
          event.dataTransfer.setData("application/x-pia-chat", chat.id)
        }
        onContextMenu={(event) => menu(chat, event)}
      >
        {bulk && (
          <Checkbox
            aria-label={"Selecionar " + chat.title}
            checked={bulk.includes(chat.id)}
            onChange={() =>
              setBulk((old) =>
                old.includes(chat.id)
                  ? old.filter((id) => id !== chat.id)
                  : [...old, chat.id],
              )
            }
          />
        )}{" "}
        {rename?.type === "chat" && rename.id === chat.id ? (
          renameInput("chat", chat)
        ) : (
          <button
            className="chat-name"
            onClick={() =>
              bulk
                ? setBulk((old) =>
                    old.includes(chat.id)
                      ? old.filter((id) => id !== chat.id)
                      : [...old, chat.id],
                  )
                : navigate({
                    view: "chat",
                    chat: chat.id,
                    archived: !!route.archived,
                  })
            }
          >
            {chat.pinned && <Pin size={12} />} {chat.title}
          </button>
        )}
        <Icon
          icon={MoreHorizontal}
          label="Opções da conversa"
          onClick={(event) => menu(chat, event)}
        />
      </div>
    );
  }
  const matches = (chat) =>
    !!chat.archived === !!route.archived &&
    chat.title.toLocaleLowerCase().includes(search.toLocaleLowerCase());
  async function reorder(event, target) {
    event.preventDefault();
    setDrop(null);
    const dragged = event.dataTransfer.getData("application/x-pia-app");
    if (!dragged || dragged === target) return;
    const order = state.apps
      .map((app) => app.id)
      .filter((id) => id !== dragged);
    order.splice(order.indexOf(target), 0, dragged);
    await api("/apps/order", { order });
    await refresh();
  }
  let content =
    route.view === "chat" ? (
      <Chat key={route.chat || "blank"} chat={route.chat} />
    ) : route.view === "settings" ? (
      route.section === "accounts" ? (
        <Connectors />
      ) : route.section?.startsWith("Connectors/") ? (
        <Connectors connector={route.section.split("/")[1]} />
      ) : (
        <SettingsPanel key={route.section} section={route.section} />
      )
    ) : route.view === "connectors" ? (
      <Connectors connector={route.connector} />
    ) : route.view === "bots" ? (
      <Secretary />
    ) : route.app === "podcast_automation" ? (
      <Podcast sub={route.sub} />
    ) : route.app === "screenshots" ? (
      <Screenshots sub={route.sub} />
    ) : route.app === "object_storage" ? (
      <Storage sub={route.sub} />
    ) : (
      <iframe title={currentApp?.name || "Aplicativo"} src={currentApp?.url} />
    );
  if (!ready)
    return (
      <>
        <ErrorAlert />
        <div className="loading-screen">
          <Loader />
          <Text>Carregando PIA…</Text>
        </div>
      </>
    );
  return (
    <Context.Provider
      value={{
        state,
        route,
        navigate,
        refresh,
        language,
        setLanguage,
        t,
        boot: state.boot,
        setRestarting,
      }}
    >
      <ErrorAlert />
      <ToastCenter />
      {!standalone && (
        <nav className="page-menu">
          <Menu>
            <Menu.Target>
              <Button variant="subtle" size="compact-xs">
                {t("Arquivo")}
              </Button>
            </Menu.Target>
            <Menu.Dropdown>
              <Menu.Item onClick={safe(() => newChat())}>
                {t("Nova conversa")}
              </Menu.Item>
              <Menu.Item
                onClick={() =>
                  navigate({ view: "settings", section: "general" })
                }
              >
                {t("Configurações")}
              </Menu.Item>
            </Menu.Dropdown>
          </Menu>
          <Menu>
            <Menu.Target>
              <Button variant="subtle" size="compact-xs">
                {t("Exibir")}
              </Button>
            </Menu.Target>
            <Menu.Dropdown>
              <Menu.Item
                onClick={() =>
                  window.dispatchEvent(new Event("pia:toast-history"))
                }
              >
                Histórico de notificações
              </Menu.Item>
              <Menu.Item onClick={() => location.reload()}>
                {t("Recarregar")}
              </Menu.Item>
              <Menu.Item
                onClick={safe(async () => {
                  if (state.native) await api("/native", { action: "inspect" });
                  else alert("Pressione F12 ou Ctrl+Shift+I no navegador.");
                })}
              >
                Inspecionar HTML / CSS / JS · F12
              </Menu.Item>
            </Menu.Dropdown>
          </Menu>
          <Button
            variant="subtle"
            size="compact-xs"
            component="a"
            href="https://github.com/oouo-diogo-perdigao/pia"
            target="_blank"
          >
            {t("Ajuda")}
          </Button>
        </nav>
      )}
      <div className={"workspace" + (standalone ? " standalone" : "")}>
        {!standalone && (
          <>
            <nav className="activity-rail">
              <Icon
                icon={MessageCircle}
                label={t("Conversas")}
                variant={route.view === "chat" ? "light" : "subtle"}
                onClick={() => navigate({ view: "chat", chat: route.chat })}
              />
              <Icon
                icon={Bot}
                label="Bots"
                variant={route.view === "bots" ? "light" : "subtle"}
                onClick={() => navigate({ view: "bots" })}
              />
              <Icon
                icon={Plug}
                label="Conectores"
                variant={route.view === "connectors" ? "light" : "subtle"}
                onClick={() =>
                  navigate({ view: "connectors", connector: "google" })
                }
              />
              <div className="app-activities">
                {state.apps.map((app) => (
                  <div
                    key={app.id}
                    draggable
                    onDragStart={(event) =>
                      event.dataTransfer.setData(
                        "application/x-pia-app",
                        app.id,
                      )
                    }
                    onDragOver={(event) => {
                      if (
                        event.dataTransfer.types.includes(
                          "application/x-pia-app",
                        )
                      ) {
                        event.preventDefault();
                        setDrop(app.id);
                      }
                    }}
                    onDragLeave={() => setDrop(null)}
                    onDrop={safe((event) => reorder(event, app.id))}
                    className={drop === app.id ? "app-drop" : ""}
                  >
                    <Icon
                      icon={appIcons[app.id] || Grid2X2}
                      label={app.name}
                      variant={
                        route.app === app.id && route.view === "app"
                          ? "light"
                          : "subtle"
                      }
                      onClick={() =>
                        navigate({ view: "app", app: app.id, sub: "principal" })
                      }
                    />
                  </div>
                ))}
              </div>
              <div className="rail-bottom">
                <Icon
                  icon={Settings}
                  label={t("Configurações")}
                  onClick={() =>
                    navigate({ view: "settings", section: "general" })
                  }
                />
              </div>
            </nav>
            {!collapsed && (
              <aside className="sidebar">
                <Group justify="space-between" wrap="nowrap" mb="md">
                  <Text fw={600} size="sm">
                    {route.view === "chat"
                      ? t("Conversas")
                      : route.view === "bots"
                        ? "Bots"
                        : route.view === "connectors"
                          ? "Conectores"
                          : route.view === "settings"
                            ? t("Configurações")
                            : currentApp?.name}
                  </Text>
                  <Group gap={2}>
                    {route.view === "chat" && (
                      <Icon
                        icon={Plus}
                        label={t("Nova conversa")}
                        variant="filled"
                        radius="xl"
                        color="violet"
                        onClick={() => newChat()}
                      />
                    )}
                    <Icon
                      icon={PanelLeftClose}
                      label={t("Recolher lista")}
                      onClick={() => setCollapsed(true)}
                    />
                  </Group>
                </Group>
                {route.view === "chat" ? (
                  <>
                    <Group wrap="nowrap" gap={5}>
                      <TextInput
                        className="grow"
                        leftSection={<Search size={14} />}
                        placeholder={t("Buscar conversas")}
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                      />
                      <Icon
                        icon={FolderPlus}
                        label={t("Nova pasta")}
                        onClick={async () => {
                          const name = prompt(t("Nome da pasta"));
                          if (name) {
                            await api("/folder/save", { name });
                            await refresh();
                          }
                        }}
                      />
                    </Group>
                    <div className="chat-list">
                      {state.folders.map((folder) => (
                        <section key={folder.id}>
                          <Group
                            wrap="nowrap"
                            className={
                              "folder-heading" +
                              (drop === folder.id ? " drop-target" : "")
                            }
                            {...dropProps(folder.id)}
                          >
                            {rename?.type === "folder" &&
                            rename.id === folder.id ? (
                              renameInput("folder", folder)
                            ) : (
                              <button
                                onClick={() =>
                                  setFolded({
                                    ...folded,
                                    [folder.id]: !folded[folder.id],
                                  })
                                }
                              >
                                {folded[folder.id] ? (
                                  <ChevronRight size={14} />
                                ) : (
                                  <ChevronDown size={14} />
                                )}{" "}
                                {folder.name}
                              </button>
                            )}
                            <Icon
                              icon={Pencil}
                              label={t("Renomear pasta")}
                              onClick={() => beginRename("folder", folder)}
                            />
                            <Icon
                              icon={Trash2}
                              label={t("Remover pasta preservando conversas")}
                              confirm
                              onClick={async () => {
                                await api("/folder/delete", { id: folder.id });
                                await refresh();
                              }}
                            />
                          </Group>
                          {!folded[folder.id] &&
                            state.chats
                              .filter(
                                (chat) =>
                                  chat.folder === folder.id && matches(chat),
                              )
                              .map(chatRow)}
                        </section>
                      ))}
                      <Text
                        size="xs"
                        c="dimmed"
                        className={drop === "unfiled" ? "drop-target" : ""}
                        mt="md"
                        {...dropProps(null)}
                      >
                        {t("Conversas · sem pasta")}
                      </Text>
                      {state.chats
                        .filter((chat) => !chat.folder && matches(chat))
                        .map(chatRow)}
                    </div>
                    <div className="sidebar-footer">
                      {bulk ? (
                        <Group>
                          <Button
                            variant="subtle"
                            onClick={() => setBulk(null)}
                          >
                            {t("CANCELAR")}
                          </Button>
                          <Icon
                            icon={Trash2}
                            label={t("Excluir conversas selecionadas")}
                            danger
                            onClick={async () => {
                              await api("/chat/delete-many", { chats: bulk });
                              setBulk(null);
                              await refresh();
                              if (bulk.includes(route.chat))
                                navigate({ view: "chat" });
                            }}
                          />
                        </Group>
                      ) : (
                        <Nav
                          onClick={() =>
                            navigate({
                              view: "chat",
                              chat: route.chat,
                              archived: !route.archived,
                            })
                          }
                        >
                          {route.archived
                            ? t("← Conversas")
                            : t("Chats arquivados")}
                        </Nav>
                      )}
                    </div>
                  </>
                ) : route.view === "settings" ? (
                  <Stack gap={4}>
                    {[
                      ["general", "Geral"],
                      ["connectors", "Conectores"],
                      ["plugins", "Variáveis dos plugins"],
                      ["logs", "Inspeção e logs"],
                    ].map(([section, label]) => (
                      <Nav
                        key={section}
                        active={route.section === section}
                        onClick={() =>
                          navigate(
                            section === "connectors"
                              ? { view: "connectors", connector: "google" }
                              : { view: "settings", section },
                          )
                        }
                      >
                        {t(label)}
                      </Nav>
                    ))}
                  </Stack>
                ) : route.view === "connectors" ? (
                  <Stack gap={4}>
                    {connectors.map((item) => (
                      <Nav
                        key={item.id}
                        active={(route.connector || "google") === item.id}
                        onClick={() =>
                          navigate({ view: "connectors", connector: item.id })
                        }
                      >
                        <Plug size={17} />
                        {item.name}
                      </Nav>
                    ))}
                  </Stack>
                ) : route.view === "bots" ? (
                  <Nav active onClick={() => navigate({ view: "bots" })}>
                    <Avatar />
                    {t("Secretária")}
                  </Nav>
                ) : (
                  <Stack gap={4}>
                    {[
                      ["principal", "Principal"],
                      ...(route.app === "podcast_automation"
                        ? [["campaigns", "Campanhas"]]
                        : []),
                      ["about", "Sobre"],
                    ].map(([sub, label]) => (
                      <Nav
                        key={sub}
                        active={(route.sub || "principal") === sub}
                        onClick={() => navigate({ ...route, sub })}
                      >
                        {t(label)}
                      </Nav>
                    ))}
                  </Stack>
                )}
              </aside>
            )}
          </>
        )}
        <main className="main-area">
          {!standalone && (
            <header className="topbar">
              <Group wrap="nowrap" gap={5}>
                <Icon
                  icon={ArrowLeft}
                  label="Voltar"
                  disabled={historyRef.current.index <= 0}
                  onClick={back}
                />
                <Icon
                  icon={ArrowRight}
                  label="Avançar"
                  disabled={
                    historyRef.current.index >=
                    historyRef.current.entries.length - 1
                  }
                  onClick={forward}
                />
                {collapsed && (
                  <Icon
                    icon={PanelLeftOpen}
                    label={t("Exibir lista")}
                    onClick={() => setCollapsed(false)}
                  />
                )}
                <Text className="view-title" fw={600}>
                  {route.view === "bots" && <Avatar />}
                  {title}
                </Text>
              </Group>
              <Group wrap="nowrap">
                <Text size="xs" c="dimmed" ta="right">
                  {route.view === "app"
                    ? currentApp?.info
                    : route.view === "connectors"
                      ? connectors.find(
                          (item) => item.id === (route.connector || "google"),
                        )?.info
                      : route.view === "chat"
                        ? t("Converse com a PIA ou dê um comando.")
                        : route.view === "bots"
                          ? "Agenda, lembretes e e-mails importantes."
                          : t("Personalize a PIA e suas integrações.")}
                </Text>
                {route.view === "app" && (
                  <Icon
                    icon={Settings}
                    label={t("Configurações do aplicativo")}
                    onClick={() =>
                      route.app === "podcast_automation"
                        ? navigate({
                            view: "settings",
                            section: "Apps/podcast_automation",
                          })
                        : route.app === "object_storage"
                          ? navigate({
                              view: "connectors",
                              connector: "object_storage",
                            })
                          : navigate({ ...route, sub: "settings" })
                    }
                  />
                )}
              </Group>
            </header>
          )}
          <div className={route.view === "chat" ? "chat-container" : "content"}>
            {content}
          </div>
        </main>
      </div>
      {popup && (
        <Paper
          className="conversation-menu"
          shadow="xl"
          p="xs"
          style={{ left: popup.x, top: popup.y }}
        >
          <Group gap={2}>
            <Icon
              icon={Pencil}
              label={t("Renomear")}
              onClick={() => beginRename("chat", popup.chat)}
            />
            <Icon
              icon={FolderInput}
              label={t("Mover para pasta")}
              onClick={() => {
                setMove(popup.chat);
                setMoveFolder(popup.chat.folder || "");
                setPopup(null);
              }}
            />
            <Icon
              icon={Pin}
              label={t(popup.chat.pinned ? "Desafixar" : "Fixar")}
              onClick={async () => {
                await updateChat(popup.chat, { pinned: !popup.chat.pinned });
                setPopup(null);
              }}
            />
            <Icon
              icon={Archive}
              label={t(popup.chat.archived ? "Desarquivar" : "Arquivar")}
              onClick={async () => {
                await updateChat(popup.chat, {
                  archived: !popup.chat.archived,
                });
                setPopup(null);
              }}
            />
            <Icon
              icon={Trash2}
              label={t("Excluir conversas")}
              onClick={() => {
                setBulk([popup.chat.id]);
                setPopup(null);
              }}
            />
          </Group>
        </Paper>
      )}
      <Modal
        opened={!!move}
        onClose={() => setMove(null)}
        title={t("Mover conversa")}
      >
        <Stack>
          <Select
            label={t("Pasta")}
            value={moveFolder}
            data={[
              { value: "", label: t("Sem pasta") },
              ...state.folders.map((folder) => ({
                value: folder.id,
                label: folder.name,
              })),
            ]}
            onChange={(value) => setMoveFolder(value || "")}
          />
          <Button
            disabled={
              moveFolder ===
              (state.chats.find((chat) => chat.id === move)?.folder || "")
            }
            onClick={safe(async () => {
              await updateChat(move, { folder: moveFolder || null });
              setMove(null);
              notify("Salvo com sucesso.");
            })}
          >
            {t("Salvar")}
          </Button>
        </Stack>
      </Modal>
      {restarting && (
        <div className="restart-screen">
          <Loader />
          <Text>
            Configurações salvas. Reiniciando a PIA assim que as tarefas em
            execução terminarem…
          </Text>
        </div>
      )}
    </Context.Provider>
  );
}
