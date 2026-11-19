import { MediaTrack } from "./MediaPlayer";
import React, { useState, useEffect, useRef } from "react";
import {
  Alert,
  ActionIcon,
  Badge,
  Button,
  Group,
  HoverCard,
  Popover,
  ScrollArea,
  Stack,
  Text,
  TextInput,
  Textarea,
  Tooltip,
  Paper,
  Loader,
  Checkbox,
} from "@mantine/core";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Copy,
  Pencil,
  Trash2,
  GitFork,
  Volume2,
  RotateCcw,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  ArrowUp,
  Mic,
  Square,
  X,
  Check,
  Info,
  Search,
  Settings,
  AlertTriangle,
} from "lucide-react";
import { api, watchJob, safe, report, copy } from "./api";
import { Icon, usePia } from "./shared";
import ProviderDrawer from "./ProviderDrawer";
import {
  buildSelectorOptions,
  formatProviderQuota,
  formatSessionUsage,
  resolveSelectedModel,
} from "./models";
function Message({ record, onAction }) {
  const { t } = usePia(),
    [editing, setEditing] = useState(false),
    [text, setText] = useState(record.content);
  return (
    <article className={"message " + record.role} data-message={record.id}>
      <div className="message-body">
        {editing ? (
          <Paper withBorder p="md">
            <Textarea
              aria-label={t("Editar mensagem")}
              autosize
              minRows={4}
              value={text}
              onChange={(event) => setText(event.target.value)}
              onKeyDown={safe(async (event) => {
                if (event.key === "Escape") setEditing(false);
                if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                  event.preventDefault();
                  if (text.trim() && text !== record.content)
                    await onAction(record, "edit", text);
                  setEditing(false);
                }
              })}
            />
            <Group mt="xs">
              <Icon
                icon={X}
                label="Cancelar edição · Esc"
                onClick={() => setEditing(false)}
              />
              <Icon
                icon={Check}
                label="Salvar edição · Ctrl+Enter"
                disabled={!text.trim() || text === record.content}
                onClick={async () => {
                  await onAction(record, "edit", text);
                  setEditing(false);
                }}
              />
            </Group>
          </Paper>
        ) : (
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              a: ({ href, children, ...props }) =>
                href?.startsWith("/api/pia/music/files/") ? (
                  <span>
                    <MediaTrack url={href} title="Música gerada" />
                    <a href={href} download>
                      {children}
                    </a>
                  </span>
                ) : (
                  <a href={href} {...props}>
                    {children}
                  </a>
                ),
            }}
          >
            {record.content}
          </ReactMarkdown>
        )}
      </div>
      <Group className="message-actions" gap={3}>
        <Icon
          feedback
          icon={Copy}
          label={t("Copiar")}
          onClick={() => copy(record.content)}
        />
        <Icon
          icon={Pencil}
          label={t("Editar")}
          onClick={() => {
            setText(record.content);
            setEditing(true);
          }}
        />
        <Icon
          icon={Trash2}
          label={t("Excluir")}
          confirm
          onClick={() => onAction(record, "delete")}
        />
        <Icon
          icon={GitFork}
          label="Fork: criar outra conversa"
          onClick={() => onAction(record, "fork")}
        />
        <Icon
          feedback
          icon={Volume2}
          label={t("Tocar")}
          onClick={() => onAction(record, "speak")}
        />
        <Icon
          icon={RotateCcw}
          label={t("Tentar novamente")}
          onClick={() => onAction(record, "retry")}
        />
        {record.alternatives?.length > 1 && (
          <>
            <Icon
              icon={ChevronLeft}
              label="Ramificação anterior"
              onClick={() =>
                onAction(
                  {
                    ...record,
                    id: record.alternatives[
                      (record.alternative + record.alternatives.length - 1) %
                        record.alternatives.length
                    ],
                  },
                  "select",
                )
              }
            />
            <Text size="xs">
              {record.alternative + 1}/{record.alternatives.length}
            </Text>
            <Icon
              icon={ChevronRight}
              label="Próxima ramificação"
              onClick={() =>
                onAction(
                  {
                    ...record,
                    id: record.alternatives[
                      (record.alternative + 1) % record.alternatives.length
                    ],
                  },
                  "select",
                )
              }
            />
          </>
        )}
      </Group>
    </article>
  );
}
function truncateSelectorText(text, max = 28) {
  const s = String(text || "");
  return s.length > max ? s.slice(0, max - 1) + "…" : s;
}

export default function Chat({ chat }) {
  const { state, refresh, navigate, t } = usePia(),
    [messages, setMessages] = useState([]),
    [draft, setDraft] = useState(""),
    [streaming, setStreaming] = useState(""),
    [running, setRunning] = useState(null),
    [sending, setSending] = useState(false),
    [dictating, setDictating] = useState(false),
    [catalog, setCatalog] = useState(null),
    [catalogLoading, setCatalogLoading] = useState(true),
    [catalogError, setCatalogError] = useState(false),
    [modelSelection, setModelSelection] = useState({ provider: "", model: "" }),
    [setAsDefault, setSetAsDefault] = useState(false),
    [popoverOpen, setPopoverOpen] = useState(false),
    [searchQuery, setSearchQuery] = useState(""),
    [drawerOpen, setDrawerOpen] = useState(false),
    [drawerFocusProvider, setDrawerFocusProvider] = useState(null),
    [sessionAnnouncement, setSessionAnnouncement] = useState("");
  const scroll = useRef(),
    follow = useRef(true),
    source = useRef(),
    draftTimer = useRef(),
    activeChat = useRef(chat),
    seenMessage = useRef(0),
    readTimer = useRef(),
    selectorBtnRef = useRef(null);

  async function loadCatalog() {
    try {
      const data = await api("/models/status");
      setCatalog(data);
      setCatalogError(false);
    } catch {
      setCatalogError(true);
    } finally {
      setCatalogLoading(false);
    }
  }
  async function markVisible() {
    if (
      !chat ||
      activeChat.current !== chat ||
      document.visibilityState !== "visible" ||
      !document.hasFocus() ||
      !scroll.current
    )
      return;
    const viewport = scroll.current.getBoundingClientRect();
    const visible = [
      ...scroll.current.querySelectorAll(".message.assistant[data-message]"),
    ]
      .filter((node) => {
        const box = node.getBoundingClientRect();
        return box.bottom > viewport.top && box.top < viewport.bottom;
      })
      .map((node) => Number(node.dataset.message))
      .filter(Number.isInteger);
    const through = Math.max(0, ...visible);
    if (through <= seenMessage.current) return;
    seenMessage.current = through;
    try {
      await api("/chat/read", { chat, through });
      await refresh();
    } catch (error) {
      seenMessage.current = 0;
      report(error);
    }
  }
  async function load(loadDraft = false) {
    if (!chat) {
      setMessages([]);
      if (loadDraft) {
        setDraft("");
        setModelSelection({ provider: "", model: "" });
      }
      return;
    }
    const result = await api("/chat/messages?chat=" + chat);
    if (activeChat.current !== chat) return;
    setMessages(result.messages);
    if (loadDraft) setDraft(result.draft || "");
    if (result.model_selection) {
      setModelSelection({
        provider: result.model_selection.provider || "",
        model: result.model_selection.model || "",
      });
    } else if (loadDraft) {
      setModelSelection({ provider: "", model: "" });
    }
  }
  function watch(id) {
    source.current?.close();
    setRunning(id);
    setStreaming("");
    source.current = watchJob(id, (event) => {
      if (event.type === "delta") setStreaming((old) => old + event.text);
      if (["done", "error"].includes(event.type)) {
        setRunning(null);
        setStreaming("");
        if (event.type === "error") report(event.error);
        load().catch(report);
        refresh().catch(report);
        loadCatalog().then(() => {
          if (event.type === "done" && !event.cancelled) {
            setSessionAnnouncement("Consumo na sessão atualizado.");
          }
        });
      }
    });
  }
  useEffect(() => {
    loadCatalog();
  }, []);
  useEffect(() => {
    activeChat.current = chat;
    seenMessage.current = 0;
    setRunning(null);
    setStreaming("");
    load(true).catch(report);
    const running = state.jobs.find((job) => job.chat === chat);
    if (running) watch(running.id);
    return () => {
      activeChat.current = null;
      source.current?.close();
      clearTimeout(draftTimer.current);
      clearTimeout(readTimer.current);
    };
  }, [chat]);
  useEffect(() => {
    if (chat && !running && state.notifications?.profile_revision)
      load().catch(report);
  }, [state.notifications?.profile_revision]);
  useEffect(() => {
    if (follow.current && scroll.current)
      scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [messages, streaming]);
  useEffect(() => {
    const frame = requestAnimationFrame(() => markVisible());
    const visibility = () => markVisible();
    document.addEventListener("visibilitychange", visibility);
    window.addEventListener("focus", visibility);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("visibilitychange", visibility);
      window.removeEventListener("focus", visibility);
    };
  }, [messages, chat]);
  const resolved = resolveSelectedModel(modelSelection, catalog);
  const isBlocked =
    !catalogLoading &&
    !catalogError &&
    resolved.mode === "provider" &&
    !resolved.available;

  async function selectModel(provider, model) {
    const next = { provider: provider || "", model: model || "" };
    setModelSelection(next);
    setPopoverOpen(false);
    setSearchQuery("");
    selectorBtnRef.current?.focus();
    if (chat) {
      await api("/chat/model", {
        chat,
        provider: next.provider,
        model: next.model,
        set_default: setAsDefault,
      });
      if (setAsDefault) await loadCatalog();
    }
  }

  async function send() {
    if (running) {
      await api("/chat/cancel", { job: running });
      return;
    }
    if (isBlocked) return;
    const text = draft.trim();
    if (!text || sending) return;
    setSending(true);
    clearTimeout(draftTimer.current);
    setDraft("");
    let target = chat;
    try {
      if (!target) {
        target = (await api("/chat/new", {})).id;
        if (modelSelection.provider || modelSelection.model || setAsDefault) {
          await api("/chat/model", {
            chat: target,
            provider: modelSelection.provider,
            model: modelSelection.model,
            set_default: setAsDefault,
          });
        }
        await api("/chat/send", {
          chat: target,
          text,
          request: crypto.randomUUID(),
        });
        await refresh();
        navigate({ view: "chat", chat: target });
        return;
      }
      setMessages((old) => [
        ...old,
        { id: "pending", role: "user", content: text },
      ]);
      const result = await api("/chat/send", {
        chat: target,
        text,
        request: crypto.randomUUID(),
      });
      if (target === activeChat.current) watch(result.job);
      await refresh();
    } catch (error) {
      setDraft(text);
      throw error;
    } finally {
      setSending(false);
    }
  }
  async function action(record, action, text) {
    const result = await api("/chat/message", {
      chat,
      id: record.id,
      action,
      ...(text !== undefined ? { text } : {}),
    });
    if (result.chat) {
      await refresh();
      navigate({ view: "chat", chat: result.chat });
      return;
    }
    if (action === "speak") return;
    await load();
    if (result.job) watch(result.job);
    await refresh();
  }
  async function dictate() {
    const identity = chat,
      result = await api("/native", { action: "dictate" });
    setDictating(true);
    watchJob(result.job, (event) => {
      if (event.type === "delta") {
        if (identity === activeChat.current)
          setDraft((old) => {
            const text = old + event.text;
            if (identity)
              api("/chat/draft", { chat: identity, text }).catch(report);
            return text;
          });
        else
          api("/chat/messages?chat=" + identity)
            .then((value) =>
              api("/chat/draft", {
                chat: identity,
                text: value.draft + event.text,
              }),
            )
            .catch(report);
      } else setDictating(false);
    });
  }
  return (
    <section className="chat-page">
      <div
        id="messages"
        ref={scroll}
        className="messages"
        role="log"
        onScroll={() => {
          const node = scroll.current;
          follow.current =
            node.scrollHeight - node.scrollTop - node.clientHeight < 100;
          clearTimeout(readTimer.current);
          readTimer.current = setTimeout(markVisible, 150);
        }}
      >
        {!messages.length && !running && (
          <div className="welcome">
            <h1>{t("Como posso ajudar?")}</h1>
            <Text c="dimmed">
              {t("Uma conversa, uma ideia ou um comando.")}
            </Text>
          </div>
        )}
        {messages.map((record) =>
          record.id === "pending" ? (
            <article className="message user" key="pending">
              <div className="message-body">{record.content}</div>
            </article>
          ) : (
            <Message key={record.id} record={record} onAction={action} />
          ),
        )}
        {(running || sending) && (
          <article className="message assistant">
            <div className="message-body">
              {streaming ? (
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    a: ({ href, children, ...props }) =>
                      href?.startsWith("/api/pia/music/files/") ? (
                        <span>
                          <MediaTrack url={href} title="Música gerada" />
                          <a href={href} download>
                            {children}
                          </a>
                        </span>
                      ) : (
                        <a href={href} {...props}>
                          {children}
                        </a>
                      ),
                  }}
                >
                  {streaming}
                </ReactMarkdown>
              ) : (
                <Stack gap={2}>
                  <Group>
                    <Loader size="xs" />
                    <Text>{t("Pensando…")}</Text>
                  </Group>
                  {resolved.provider?.auth_type === "cli" && (
                    <Text size="xs" c="dimmed">
                      {resolved.provider.name} envia a resposta completa ao
                      terminar.
                    </Text>
                  )}
                </Stack>
              )}
            </div>
          </article>
        )}
      </div>
      <div
        aria-live="polite"
        style={{
          position: "absolute",
          width: 1,
          height: 1,
          overflow: "hidden",
          clip: "rect(0 0 0 0)",
        }}
      >
        {sessionAnnouncement}
      </div>
      <div className="composer-wrap">
        {(() => {
          const selectorData = buildSelectorOptions(catalog);
          const query = searchQuery.trim().toLowerCase();
          const filteredGroups = selectorData.groups
            .map((g) => ({
              ...g,
              models: query
                ? g.models.filter(
                    (m) =>
                      m.label.toLowerCase().includes(query) ||
                      m.model.toLowerCase().includes(query) ||
                      g.name.toLowerCase().includes(query),
                  )
                : g.models,
            }))
            .filter((g) => !query || g.models.length > 0 || g.name.toLowerCase().includes(query));

          const activeUsage = resolved.provider?.session_usage || {
            requests: catalog?.total_requests || 0,
            tokens_reported: false,
          };
          const usageCompact = formatSessionUsage(activeUsage, { compact: true });
          const usageFull = formatSessionUsage(activeUsage);
          const quotaFull = formatProviderQuota(
            resolved.provider?.provider_quota,
            resolved.providerId,
          );

          const statusDotColor =
            resolved.statusMeta?.color === "green"
              ? "var(--mantine-color-green-6)"
              : resolved.statusMeta?.color === "yellow"
                ? "var(--mantine-color-yellow-6)"
                : resolved.statusMeta?.color === "red"
                  ? "var(--mantine-color-red-6)"
                  : "var(--mantine-color-gray-6)";

          const blockActionLabel =
            resolved.provider?.status === "not_installed"
              ? "Como instalar"
              : resolved.provider?.status === "error"
                ? "Reconectar"
                : resolved.provider?.auth_type === "api_key"
                  ? "Adicionar chave"
                  : "Fazer login";

          return (
            <Paper withBorder className="composer" p="md">
              {isBlocked && (
                <Alert color="yellow" role="alert" mb="xs" p="xs">
                  <Group justify="space-between" wrap="wrap" gap="xs">
                    <Text size="xs">{resolved.blockingReason}</Text>
                    <Group gap="xs">
                      <Button
                        size="compact-xs"
                        variant="light"
                        onClick={() => {
                          setDrawerFocusProvider(resolved.providerId);
                          setDrawerOpen(true);
                        }}
                      >
                        {blockActionLabel}
                      </Button>
                      <Button
                        size="compact-xs"
                        variant="subtle"
                        onClick={() => setPopoverOpen(true)}
                      >
                        Escolher outro modelo
                      </Button>
                    </Group>
                  </Group>
                </Alert>
              )}
              <Textarea
                id="prompt"
                variant="unstyled"
                aria-label={t("Mensagem")}
                title={t("Shift + Enter para uma nova linha")}
                placeholder={t("Pergunte à PIA ou dê um comando…")}
                autosize
                minRows={1}
                maxRows={7}
                value={draft}
                onChange={(event) => {
                  const text = event.target.value;
                  setDraft(text);
                  clearTimeout(draftTimer.current);
                  if (chat)
                    draftTimer.current = setTimeout(
                      () => api("/chat/draft", { chat, text }).catch(report),
                      350,
                    );
                }}
                onKeyDown={(event) => {
                  if (
                    event.key === "Enter" &&
                    !event.shiftKey &&
                    !event.nativeEvent.isComposing
                  ) {
                    event.preventDefault();
                    safe(send)();
                  }
                }}
              />
              <Group justify="space-between" wrap="nowrap" gap="xs">
                <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
                  <Icon
                    icon={Mic}
                    label={t("Ditar no campo de mensagem")}
                    color={dictating ? "red" : "gray"}
                    onClick={dictate}
                  />
                  <Popover
                    opened={popoverOpen}
                    onChange={setPopoverOpen}
                    width={340}
                    position="top-start"
                    withinPortal
                  >
                    <Popover.Target>
                      <Tooltip
                        label={
                          running || sending
                            ? "Aguarde a resposta terminar para trocar o modelo."
                            : catalogError
                              ? "Não foi possível atualizar a lista de modelos."
                              : resolved.modelLabel
                        }
                      >
                        <Button
                          ref={selectorBtnRef}
                          variant="subtle"
                          size="xs"
                          color="gray"
                          disabled={Boolean(running || sending || catalogLoading)}
                          aria-label={`Modelo da conversa: ${resolved.modelLabel}, ${resolved.statusMeta?.label || "Conectado"}. Alterar modelo`}
                          onClick={() => setPopoverOpen((o) => !o)}
                          leftSection={
                            catalogLoading ? (
                              <Loader size={10} />
                            ) : catalogError ? (
                              <AlertTriangle size={12} />
                            ) : (
                              <span
                                style={{
                                  width: 8,
                                  height: 8,
                                  borderRadius: "50%",
                                  backgroundColor: statusDotColor,
                                  display: "inline-block",
                                }}
                              />
                            )
                          }
                          rightSection={<ChevronDown size={13} />}
                        >
                          {catalogLoading
                            ? "Carregando modelos…"
                            : catalogError
                              ? `Modelo: ${truncateSelectorText(resolved.modelLabel, 20)}`
                              : truncateSelectorText(resolved.modelLabel, 28)}
                        </Button>
                      </Tooltip>
                    </Popover.Target>
                    <Popover.Dropdown p="xs">
                      <Stack gap="xs">
                        <TextInput
                          size="xs"
                          placeholder="Buscar modelo"
                          leftSection={<Search size={13} />}
                          value={searchQuery}
                          onChange={(e) => setSearchQuery(e.target.value)}
                          autoFocus
                        />
                        <ScrollArea.Autosize mah={280}>
                          <Stack gap={4}>
                            <Text size="xs" fw={600} c="dimmed">
                              Padrão
                            </Text>
                            <Button
                              size="xs"
                              variant={
                                resolved.mode === "default" ? "light" : "subtle"
                              }
                              justify="flex-start"
                              fullWidth
                              onClick={safe(() => selectModel("", ""))}
                            >
                              {selectorData.defaultOption.label}
                            </Button>

                            <Text size="xs" fw={600} c="dimmed" mt={4}>
                              Automático (pode alternar entre modelos)
                            </Text>
                            {selectorData.automaticOptions.map((opt) => (
                              <Button
                                key={opt.value}
                                size="xs"
                                variant={
                                  resolved.mode === "automatic" &&
                                  resolved.modelId === opt.value
                                    ? "light"
                                    : "subtle"
                                }
                                justify="flex-start"
                                fullWidth
                                onClick={safe(() =>
                                  selectModel(opt.provider, opt.model),
                                )}
                              >
                                {opt.label}
                              </Button>
                            ))}

                            {filteredGroups.map((g) => (
                              <Stack key={g.providerId} gap={2} mt={4}>
                                <Group justify="space-between" wrap="nowrap">
                                  <Text size="xs" fw={600} c="dimmed">
                                    {g.name} · {g.statusMeta.label}
                                  </Text>
                                  {!g.connected && (
                                    <Button
                                      size="compact-xs"
                                      variant="subtle"
                                      onClick={() => {
                                        setPopoverOpen(false);
                                        setDrawerFocusProvider(g.providerId);
                                        setDrawerOpen(true);
                                      }}
                                    >
                                      Conectar
                                    </Button>
                                  )}
                                </Group>
                                {g.models.map((m) => (
                                  <Button
                                    key={m.value}
                                    size="xs"
                                    variant={
                                      resolved.providerId === m.provider &&
                                      resolved.modelId === m.model
                                        ? "light"
                                        : "subtle"
                                    }
                                    disabled={!g.connected}
                                    justify="flex-start"
                                    fullWidth
                                    onClick={safe(() =>
                                      selectModel(m.provider, m.model),
                                    )}
                                  >
                                    {m.label}
                                  </Button>
                                ))}
                              </Stack>
                            ))}
                          </Stack>
                        </ScrollArea.Autosize>
                        <Checkbox
                          size="xs"
                          label="Usar como padrão das novas conversas"
                          checked={setAsDefault}
                          onChange={(e) =>
                            setSetAsDefault(e.currentTarget.checked)
                          }
                        />
                        <Button
                          size="xs"
                          variant="subtle"
                          justify="flex-start"
                          leftSection={<Settings size={13} />}
                          onClick={() => {
                            setPopoverOpen(false);
                            setDrawerFocusProvider(null);
                            setDrawerOpen(true);
                          }}
                        >
                          Gerenciar provedores
                        </Button>
                      </Stack>
                    </Popover.Dropdown>
                  </Popover>

                  <Text size="xs" c="dimmed" visibleFrom="sm" truncate>
                    {usageCompact.summary}
                  </Text>

                  <HoverCard width={280} withArrow shadow="md" withinPortal>
                    <HoverCard.Target>
                      <ActionIcon
                        size="xs"
                        variant="subtle"
                        color="gray"
                        aria-label="Detalhes de consumo e saldo"
                      >
                        <Info size={14} />
                      </ActionIcon>
                    </HoverCard.Target>
                    <HoverCard.Dropdown>
                      <Stack gap="xs">
                        <Text size="xs" fw={600}>
                          {resolved.modelLabel}
                        </Text>
                        <Paper withBorder p="xs">
                          <Text size="xs" fw={600} c="dimmed">
                            Consumo na sessão
                          </Text>
                          <Text size="xs" mt={2}>
                            {usageFull.summary}
                          </Text>
                          {usageFull.detail && (
                            <Text size="xs" c="dimmed">
                              {usageFull.detail}
                            </Text>
                          )}
                        </Paper>
                        <Paper withBorder p="xs">
                          <Text size="xs" fw={600} c="dimmed">
                            Saldo do provedor
                          </Text>
                          <Text size="xs" mt={2}>
                            {quotaFull.label}
                          </Text>
                          {quotaFull.checkedAtText && (
                            <Text size="xs" c="dimmed">
                              {quotaFull.checkedAtText}
                            </Text>
                          )}
                        </Paper>
                      </Stack>
                    </HoverCard.Dropdown>
                  </HoverCard>
                </Group>

                <Tooltip
                  label={`Conecte ${resolved.provider?.name || "o provedor"} ou escolha outro modelo para enviar.`}
                  disabled={!isBlocked}
                >
                  <Icon
                    icon={running ? Square : ArrowUp}
                    label={
                      running ? t("Interromper resposta") : t("Enviar mensagem")
                    }
                    variant="filled"
                    color="violet"
                    radius="xl"
                    disabled={
                      sending || isBlocked || (!running && !draft.trim())
                    }
                    onClick={send}
                  />
                </Tooltip>
              </Group>
            </Paper>
          );
        })()}
        <Text ta="center" size="xs" c="dimmed" mt="xs">
          {t("A PIA pode cometer erros. Confira informações importantes.")}
        </Text>
      </div>
      <ProviderDrawer
        opened={drawerOpen}
        focusProvider={drawerFocusProvider}
        onClose={() => {
          setDrawerOpen(false);
          selectorBtnRef.current?.focus();
        }}
        onUpdated={() => loadCatalog()}
      />
    </section>
  );
}
