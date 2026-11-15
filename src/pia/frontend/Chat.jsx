import { MediaTrack } from "./MediaPlayer";
import React, { useState, useEffect, useRef, useMemo } from "react";
import {
  Button,
  Group,
  Text,
  Textarea,
  Paper,
  Loader,
  Select,
  Popover,
  Badge,
  Modal,
  ActionIcon,
  Stack,
  Divider,
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
  Info,
  Download,
  FileText,
  Database,
  Sparkles,
  ArrowUpRight,
} from "lucide-react";
import { api, watchJob, safe, report, copy } from "./api";
import { Icon, usePia } from "./shared";
import MessageInfoPopover, {
  McpUsageBadge,
} from "./features/chat/MessageInfoPopover";
import SuggestionChips from "./features/chat/SuggestionChips";
import {
  CHAT_AUTO_MODEL_SENTINEL,
  buildChatModelOptions,
  buildChatSendPayload,
  buildChatActionPayload,
  formatMessageInfo,
  extractMessageMedia,
  extractMessageSuggestions,
  isImageUrl,
  isAudioUrl,
  createChatSpeechController,
} from "./chat-helpers";

const CHAT_MODEL_STORAGE_KEY = "pia.chat.selectedModel";

function buildMarkdownComponents(onPreviewImage) {
  return {
    img: ({ src, alt, ...props }) =>
      src ? (
        <img
          src={src}
          alt={alt || "Imagem"}
          loading="lazy"
          className="chat-inline-image"
          onClick={() =>
            onPreviewImage?.({ url: src, title: alt || "Captura / Imagem" })
          }
          {...props}
        />
      ) : null,
    a: ({ href, children, ...props }) => {
      if (isAudioUrl(href)) {
        const label =
          typeof children === "string" ? children : "Música / Áudio gerado";
        return (
          <span className="chat-media-chip">
            <MediaTrack url={href} title={label} />
            <a href={href} download>
              Baixar áudio
            </a>
          </span>
        );
      }
      if (isImageUrl(href)) {
        const label = typeof children === "string" ? children : "Imagem";
        return (
          <span>
            <img
              src={href}
              alt={label}
              loading="lazy"
              className="chat-inline-image"
              onClick={() => onPreviewImage?.({ url: href, title: label })}
            />
            <a href={href} download>
              {children}
            </a>
          </span>
        );
      }
      return (
        <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
          {children}
        </a>
      );
    },
  };
}

function Message({
  record,
  onAction,
  isSpeaking,
  onToggleSpeak,
  onPreviewImage,
  onSendSuggestion,
  busy,
}) {
  const { t } = usePia(),
    [editing, setEditing] = useState(false),
    [text, setText] = useState(record.content),
    [infoOpen, setInfoOpen] = useState(false);

  const info = useMemo(() => formatMessageInfo(record), [record]);
  const media = useMemo(() => extractMessageMedia(record), [record]);
  const suggestions = useMemo(
    () => extractMessageSuggestions(record),
    [record],
  );
  const markdownComponents = useMemo(
    () => buildMarkdownComponents(onPreviewImage),
    [onPreviewImage],
  );
  const hasAttachments =
    media.images.length > 0 ||
    media.audios.length > 0 ||
    media.files.length > 0;

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
          <>
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={markdownComponents}
            >
              {record.content}
            </ReactMarkdown>
            {hasAttachments && (
              <div className="chat-attachments">
                {media.images.map((img) => (
                  <div key={img.url}>
                    <img
                      src={img.url}
                      alt={img.title}
                      loading="lazy"
                      className="chat-inline-image"
                      onClick={() =>
                        onPreviewImage?.({ url: img.url, title: img.title })
                      }
                    />
                    <Group gap={6} mt={4}>
                      <Text size="xs" c="dimmed">
                        {img.title}
                      </Text>
                      {img.downloadUrl && (
                        <a href={img.downloadUrl} download>
                          <Group gap={4} wrap="nowrap">
                            <Download size={12} />
                            <Text size="xs">Baixar</Text>
                          </Group>
                        </a>
                      )}
                    </Group>
                  </div>
                ))}
                {media.audios.map((audio) => (
                  <Paper
                    key={audio.url}
                    withBorder
                    p="xs"
                    className="chat-attachment-card"
                  >
                    <Group justify="space-between" wrap="wrap" gap="xs">
                      <MediaTrack url={audio.url} title={audio.title} />
                      {audio.downloadUrl && (
                        <a href={audio.downloadUrl} download>
                          <Group gap={4} wrap="nowrap">
                            <Download size={13} />
                            <Text size="xs">Baixar</Text>
                          </Group>
                        </a>
                      )}
                    </Group>
                  </Paper>
                ))}
                {media.files.map((file, idx) => (
                  <Paper
                    key={file.url || `${file.name}-${idx}`}
                    withBorder
                    p="xs"
                    className="chat-attachment-card"
                  >
                    <Group justify="space-between" gap="xs">
                      <Group gap={6}>
                        {file.bucket || file.kind === "bucket" ? (
                          <Database size={14} />
                        ) : (
                          <FileText size={14} />
                        )}
                        <Text size="xs" fw={500}>
                          {file.name}
                        </Text>
                        {file.bucket && (
                          <Badge size="xs" variant="light" color="blue">
                            {file.bucket}
                          </Badge>
                        )}
                      </Group>
                      {file.url && (
                        <a href={file.url} download>
                          <Group gap={4} wrap="nowrap">
                            <Download size={13} />
                            <Text size="xs">Baixar</Text>
                          </Group>
                        </a>
                      )}
                    </Group>
                    {file.transcript && (
                      <div className="chat-transcript-preview">
                        {file.transcript}
                      </div>
                    )}
                  </Paper>
                ))}
              </div>
            )}
            {record.role === "assistant" &&
              (info.tools.length > 0 || info.mcpBadge) && (
                <Group className="message-tools" gap={6}>
                  <McpUsageBadge info={info} />
                  {info.tools.map((tool) => (
                    <Badge
                      key={tool.name}
                      size="xs"
                      variant="dot"
                      color="violet"
                    >
                      {tool.detail
                        ? `${tool.name} · ${tool.detail}`
                        : tool.name}
                    </Badge>
                  ))}
                </Group>
              )}
            {record.role === "assistant" && (
              <SuggestionChips
                suggestions={suggestions}
                busy={busy}
                label={t("Sugestões rápidas")}
                onSendSuggestion={onSendSuggestion}
              />
            )}
          </>
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
          icon={isSpeaking ? Square : Volume2}
          color={isSpeaking ? "red" : "gray"}
          label={isSpeaking ? t("Parar fala") : t("Tocar")}
          onClick={() => onToggleSpeak?.(record)}
        />
        {record.role === "assistant" && (
          <MessageInfoPopover
            info={info}
            opened={infoOpen}
            onChange={setInfoOpen}
            onToggle={() => setInfoOpen((open) => !open)}
            t={t}
          />
        )}
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
    [dictating, setDictating] = useState(false),
    [modelOptions, setModelOptions] = useState(
      () => buildChatModelOptions(null, null).options,
    ),
    [selectedModel, setSelectedModel] = useState(() => {
      try {
        return (
          localStorage.getItem(CHAT_MODEL_STORAGE_KEY) ||
          CHAT_AUTO_MODEL_SENTINEL
        );
      } catch {
        return CHAT_AUTO_MODEL_SENTINEL;
      }
    }),
    [speakingId, setSpeakingId] = useState(null),
    [previewImage, setPreviewImage] = useState(null);
  const scroll = useRef(),
    follow = useRef(true),
    source = useRef(),
    draftTimer = useRef(),
    activeChat = useRef(chat),
    seenMessage = useRef(0),
    readTimer = useRef(),
    speechController = useRef(null);
  const streamingMarkdownComponents = useMemo(
    () => buildMarkdownComponents(setPreviewImage),
    [],
  );

  useEffect(() => {
    let active = true;
    Promise.allSettled([api("/chat/models"), api("/settings")]).then(
      ([modelsResult, settingsResult]) => {
        if (!active) return;
        const modelsData =
          modelsResult.status === "fulfilled" ? modelsResult.value : null;
        const settingsData =
          settingsResult.status === "fulfilled"
            ? settingsResult.value?.values || settingsResult.value
            : null;
        const { options } = buildChatModelOptions(modelsData, settingsData);
        setModelOptions(options);
        setSelectedModel((prev) =>
          options.some((opt) => opt.value === prev && !opt.disabled)
            ? prev
            : CHAT_AUTO_MODEL_SENTINEL,
        );
      },
    );
    return () => {
      active = false;
    };
  }, [state.notifications?.profile_revision]);

  useEffect(() => {
    const controller = createChatSpeechController({
      synthesize: async (record, speechText, { signal }) => {
        const selection = await api("/tts/selection").catch(() => null);
        const profile = selection?.profile || selection?.active || null;
        if (profile?.provider && profile?.voice) {
          try {
            const started = await api("/tts/preview", {
              profile,
              text: speechText,
            });
            if (started?.job_id) {
              return { jobId: started.job_id };
            }
            if (started?.audio_url) {
              return { audioUrl: started.audio_url };
            }
          } catch {
            // Fall through to full-length /v1/audio/speech or chat speak action.
          }
        }
        try {
          const response = await fetch("/v1/audio/speech", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              input: speechText.slice(0, 4096),
              ...(profile?.voice ? { voice: profile.voice } : {}),
              ...(profile?.speed ? { speed: Number(profile.speed) } : {}),
              response_format: "mp3",
            }),
            signal,
          });
          if (response.ok) {
            const blob = await response.blob();
            return { objectUrl: URL.createObjectURL(blob) };
          }
        } catch (err) {
          if (err?.name === "AbortError") throw err;
        }
        const fallback = await api("/chat/message", {
          chat: activeChat.current,
          id: record.id,
          action: "speak",
        });
        if (fallback?.audio_url || fallback?.job_id) {
          return {
            audioUrl: fallback.audio_url,
            jobId: fallback.job_id,
          };
        }
        return { serverSide: true };
      },
      watch: watchJob,
      pollJob: (jobId) => api(`/tts/jobs/${jobId}`),
      cancelRemote: async (entry) => {
        if (entry?.remoteJobId && !entry.playbackStarted) {
          await api(`/tts/jobs/${entry.remoteJobId}/cancel`, {}).catch(
            () => {},
          );
        }
        await api("/tts/stop", {}).catch(() => {});
      },
      onStateChange: ({ activeId }) => setSpeakingId(activeId),
      onError: report,
    });
    speechController.current = controller;
    return () => {
      controller.stop();
      speechController.current = null;
    };
  }, []);
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
        const doneMeta =
          event.result && typeof event.result === "object"
            ? event.result
            : event;
        load()
          .then(() => {
            if (
              doneMeta?.model ||
              doneMeta?.provider ||
              doneMeta?.tools_used ||
              doneMeta?.mcp_account ||
              doneMeta?.account_mode ||
              doneMeta?.mcp_server ||
              doneMeta?.active_context
            ) {
              setMessages((prev) => {
                const copyList = [...prev];
                for (let idx = copyList.length - 1; idx >= 0; idx--) {
                  if (copyList[idx]?.role === "assistant") {
                    copyList[idx] = {
                      ...copyList[idx],
                      ...(doneMeta.model && !copyList[idx].model
                        ? { model: doneMeta.model }
                        : {}),
                      ...(doneMeta.provider && !copyList[idx].provider
                        ? { provider: doneMeta.provider }
                        : {}),
                      ...(doneMeta.tools_used && !copyList[idx].tools_used
                        ? { tools_used: doneMeta.tools_used }
                        : {}),
                      ...(doneMeta.mcp_account && !copyList[idx].mcp_account
                        ? { mcp_account: doneMeta.mcp_account }
                        : {}),
                      ...(doneMeta.account_mode && !copyList[idx].account_mode
                        ? { account_mode: doneMeta.account_mode }
                        : {}),
                      ...(doneMeta.mcp_server && !copyList[idx].mcp_server
                        ? { mcp_server: doneMeta.mcp_server }
                        : {}),
                      ...(doneMeta.active_context &&
                      !copyList[idx].active_context
                        ? { active_context: doneMeta.active_context }
                        : {}),
                    };
                    break;
                  }
                }
                return copyList;
              });
            }
          })
          .catch(report);
        refresh().catch(report);
      }
    });
  }
  useEffect(() => {
    activeChat.current = chat;
    seenMessage.current = 0;
    speechController.current?.stop();
    setRunning(null);
    setStreaming("");
    load(true).catch(report);
    const running = state.jobs.find((job) => job.chat === chat);
    if (running) watch(running.id);
    return () => {
      activeChat.current = null;
      source.current?.close();
      speechController.current?.stop();
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
  async function send(overrideText) {
    const isOverride = typeof overrideText === "string";
    if (running) {
      if (isOverride) return;
      await api("/chat/cancel", { job: running });
      return;
    }
    const text = (isOverride ? overrideText : draft).trim();
    if (!text || sending) return;
    setSending(true);
    if (!isOverride) {
      clearTimeout(draftTimer.current);
      setDraft("");
    }
    let target = chat;
    try {
      if (!target) {
        target = (await api("/chat/new", {})).id;
        await api(
          "/chat/send",
          buildChatSendPayload({
            chat: target,
            text,
            request: crypto.randomUUID(),
            model: selectedModel,
          }),
        );
        await refresh();
        navigate({ view: "chat", chat: target });
        return;
      }
      setMessages((old) => [
        ...old,
        { id: "pending", role: "user", content: text },
      ]);
      const result = await api(
        "/chat/send",
        buildChatSendPayload({
          chat: target,
          text,
          request: crypto.randomUUID(),
          model: selectedModel,
        }),
      );
      if (target === activeChat.current) watch(result.job);
      await refresh();
    } catch (error) {
      if (!isOverride) setDraft(text);
      throw error;
    } finally {
      setSending(false);
    }
  }
  async function action(record, action, text) {
    const result = await api(
      "/chat/message",
      buildChatActionPayload({
        chat,
        id: record.id,
        action,
        text,
        model: selectedModel,
      }),
    );
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
  function handleModelChange(value) {
    const next = value || CHAT_AUTO_MODEL_SENTINEL;
    setSelectedModel(next);
    try {
      localStorage.setItem(CHAT_MODEL_STORAGE_KEY, next);
    } catch {}
  }

  return (
    <section className="chat-page">
      <div className="chat-topbar">
        <Group gap="xs" wrap="nowrap">
          <Sparkles size={15} />
          <Text size="xs" c="dimmed">
            {t("Modelo:")}
          </Text>
          <Select
            className="chat-model-select"
            size="xs"
            searchable
            allowDeselect={false}
            aria-label={t("Modelo para a próxima resposta")}
            placeholder={t("Automático (Padrão)")}
            data={modelOptions}
            value={selectedModel}
            onChange={handleModelChange}
          />
        </Group>
      </div>
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
            <Message
              key={record.id}
              record={record}
              onAction={action}
              isSpeaking={speakingId === record.id}
              onToggleSpeak={(rec) => speechController.current?.toggle(rec)}
              onPreviewImage={setPreviewImage}
              onSendSuggestion={(prompt) => send(prompt)}
              busy={sending || Boolean(running)}
            />
          ),
        )}
        {(running || sending) && (
          <article className="message assistant">
            <div className="message-body">
              {streaming ? (
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={streamingMarkdownComponents}
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
      <Modal
        opened={Boolean(previewImage)}
        onClose={() => setPreviewImage(null)}
        title={previewImage?.title || t("Visualização")}
        size="xl"
        centered
      >
        {previewImage && (
          <Stack gap="sm" align="center">
            <img
              src={previewImage.url}
              alt={previewImage.title || "Imagem"}
              style={{ maxWidth: "100%", maxHeight: "75vh", borderRadius: 10 }}
            />
            <a href={previewImage.url} download>
              <Group gap={6}>
                <Download size={14} />
                <Text size="sm">{t("Baixar imagem")}</Text>
              </Group>
            </a>
          </Stack>
        )}
      </Modal>
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
