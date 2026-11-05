import { MediaTrack } from "./MediaPlayer";
import React, { useState, useEffect, useRef } from "react";
import {
  Button,
  Group,
  Text,
  Textarea,
  Paper,
  Loader,
  Select,
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
  ArrowUp,
  Mic,
  Square,
  X,
  Check,
} from "lucide-react";
import { api, watchJob, safe, report, copy } from "./api";
import { Icon, usePia } from "./shared";
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
export default function Chat({ chat }) {
  const { state, refresh, navigate, t } = usePia(),
    [messages, setMessages] = useState([]),
    [draft, setDraft] = useState(""),
    [streaming, setStreaming] = useState(""),
    [running, setRunning] = useState(null),
    [sending, setSending] = useState(false),
    [dictating, setDictating] = useState(false);
  const scroll = useRef(),
    follow = useRef(true),
    source = useRef(),
    draftTimer = useRef(),
    activeChat = useRef(chat),
    seenMessage = useRef(0),
    readTimer = useRef();
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
      if (loadDraft) setDraft("");
      return;
    }
    const result = await api("/chat/messages?chat=" + chat);
    if (activeChat.current !== chat) return;
    setMessages(result.messages);
    if (loadDraft) setDraft(result.draft || "");
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
      }
    });
  }
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
  async function send() {
    if (running) {
      await api("/chat/cancel", { job: running });
      return;
    }
    const text = draft.trim();
    if (!text || sending) return;
    setSending(true);
    clearTimeout(draftTimer.current);
    setDraft("");
    let target = chat;
    try {
      if (!target) {
        target = (await api("/chat/new", {})).id;
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
                <Group>
                  <Loader size="xs" />
                  <Text>{t("Pensando…")}</Text>
                </Group>
              )}
            </div>
          </article>
        )}
      </div>
      <div className="composer-wrap">
        <Paper withBorder className="composer" p="md">
          <Textarea
            id="prompt"
            variant="unstyled"
            aria-label={t("Mensagem")}
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
          <Group justify="space-between">
            <Group>
              <Icon
                icon={Mic}
                label={t("Ditar no campo de mensagem")}
                color={dictating ? "red" : "gray"}
                onClick={dictate}
              />
              <Text size="xs" c="dimmed">
                {t("Shift + Enter para uma nova linha")}
              </Text>
            </Group>
            <Icon
              icon={running ? Square : ArrowUp}
              label={running ? t("Interromper resposta") : t("Enviar mensagem")}
              variant="filled"
              color="violet"
              radius="xl"
              disabled={sending || (!running && !draft.trim())}
              onClick={send}
            />
          </Group>
        </Paper>
        <Text ta="center" size="xs" c="dimmed" mt="xs">
          {t("A PIA pode cometer erros. Confira informações importantes.")}
        </Text>
      </div>
    </section>
  );
}
