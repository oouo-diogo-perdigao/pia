import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  Textarea,
  Tooltip,
} from "@mantine/core";
import {
  Bot as BotIcon,
  MessageSquare,
  Send,
  Square,
  Volume2,
  VolumeX,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, report, safe, watchJob } from "../../api";
import { createChatSpeechController } from "../../chat-helpers";
import { usePia } from "../../shared";
import {
  buildBotChatPayload,
  findBotChatRecord,
  getBotSuggestions,
} from "./bot-chat-helpers";

const STORAGE_KEY_PREFIX = "pia.bot_chat.";

function readStoredChatId(botId) {
  try {
    return window.localStorage?.getItem(STORAGE_KEY_PREFIX + botId) || "";
  } catch {
    return "";
  }
}

function writeStoredChatId(botId, chatId) {
  try {
    if (botId && chatId) {
      window.localStorage?.setItem(STORAGE_KEY_PREFIX + botId, chatId);
    }
  } catch {
    // Ignore storage errors in constrained webviews.
  }
}

export default function BotChatPanel({
  botId,
  botName = "Bot",
  botSubtitle = "",
  suggestions = null,
  systemPrompt = "",
  minHeight = 260,
  maxHeight = 420,
}) {
  const { state, refresh } = usePia();
  const [messages, setMessages] = useState([]);
  const [inputText, setInputText] = useState("");
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [activeJobId, setActiveJobId] = useState(null);
  const [speakingState, setSpeakingState] = useState({
    id: null,
    status: "idle",
  });

  const jobSourceRef = useRef(null);
  const transcriptEndRef = useRef(null);
  const speechControllerRef = useRef(null);

  const resolvedChat = useMemo(
    () => findBotChatRecord(state.chats, botId, readStoredChatId(botId)),
    [state.chats, botId],
  );
  const [chatId, setChatId] = useState(resolvedChat?.id || "");

  useEffect(() => {
    if (resolvedChat?.id && resolvedChat.id !== chatId) {
      setChatId(resolvedChat.id);
      writeStoredChatId(botId, resolvedChat.id);
    }
  }, [resolvedChat?.id, botId, chatId]);

  useEffect(() => {
    const controller = createChatSpeechController({
      synthesize: async (_record, speechText) => {
        const speakerId =
          botId === "secretaria" ? "native:secretaria" : `dynamic:${botId}`;
        const selection = await api(
          `/tts/selection?speaker_id=${encodeURIComponent(speakerId)}`,
        ).catch(() => null);
        const profile = selection?.profile || selection?.active || null;
        if (profile?.provider && profile?.voice) {
          const started = await api("/tts/preview", {
            profile,
            text: speechText,
          });
          if (started?.job_id) return { jobId: started.job_id };
          if (started?.audio_url) return { audioUrl: started.audio_url };
        }
        const started = await api("/tts/speak", {
          text: speechText,
          speaker_id: speakerId,
        });
        if (started?.job_id) return { jobId: started.job_id };
        return started?.audio_url ? { audioUrl: started.audio_url } : null;
      },
      watchJob,
      pollJob: (id) => api(`/jobs/${id}`),
      onStateChange: ({ messageId, status }) =>
        setSpeakingState({ id: messageId || null, status: status || "idle" }),
      onError: report,
    });
    speechControllerRef.current = controller;
    return () => {
      controller.stop();
      speechControllerRef.current = null;
    };
  }, [botId]);

  useEffect(() => {
    if (jobSourceRef.current) {
      jobSourceRef.current.close();
      jobSourceRef.current = null;
    }
    setActiveJobId(null);
    const knownChatId = resolvedChat?.id || readStoredChatId(botId);
    setChatId(knownChatId || "");
    if (!knownChatId) {
      setMessages([]);
      return;
    }
    let cancelled = false;
    setLoadingHistory(true);
    api(`/chat/messages?chat=${encodeURIComponent(knownChatId)}`)
      .then((res) => {
        if (cancelled) return;
        const recs = Array.isArray(res?.messages) ? res.messages : [];
        setMessages(
          recs.map((m, idx) => ({
            id: m.id || `${knownChatId}-${idx}`,
            role: m.role,
            text: m.content || "",
            status: "done",
          })),
        );
      })
      .catch(() => {
        if (!cancelled) setMessages([]);
      })
      .finally(() => {
        if (!cancelled) setLoadingHistory(false);
      });
    return () => {
      cancelled = true;
    };
  }, [botId]);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = async (overrideText) => {
    const rawText = typeof overrideText === "string" ? overrideText : inputText;
    const trimmed = rawText.trim();
    if (!trimmed || activeJobId || !botId) return;
    if (typeof overrideText !== "string") {
      setInputText("");
    }

    const userMsgId = crypto.randomUUID();
    const assistantMsgId = crypto.randomUUID();
    setMessages((prev) => [
      ...prev,
      { id: userMsgId, role: "user", text: trimmed, status: "done" },
      { id: assistantMsgId, role: "assistant", text: "", status: "running" },
    ]);

    try {
      const payload = buildBotChatPayload({
        botId,
        text: trimmed,
        chatId,
        systemPrompt,
        request: crypto.randomUUID(),
      });
      const started = await api("/chat/send", payload);
      const jobId = started?.job;
      setActiveJobId(jobId);

      const src = watchJob(jobId, (evt) => {
        if (evt.type === "delta" && evt.text) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId ? { ...m, text: m.text + evt.text } : m,
            ),
          );
        } else if (evt.type === "done") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId
                ? {
                    ...m,
                    text: evt.text !== undefined ? evt.text : m.text,
                    status: evt.cancelled ? "cancelled" : "done",
                  }
                : m,
            ),
          );
          setActiveJobId(null);
          jobSourceRef.current = null;
          refresh?.().catch(() => {});
        } else if (evt.type === "error") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId
                ? {
                    ...m,
                    status: "error",
                    error: evt.error || "Falha ao obter resposta do bot.",
                  }
                : m,
            ),
          );
          setActiveJobId(null);
          jobSourceRef.current = null;
        }
      });
      jobSourceRef.current = src;
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantMsgId
            ? {
                ...m,
                status: "error",
                error: err?.message || "Erro ao enviar mensagem para o bot.",
              }
            : m,
        ),
      );
      setActiveJobId(null);
      report(err);
    }
  };

  const cancelJob = async () => {
    if (!activeJobId) return;
    await api("/chat/cancel", { job: activeJobId });
  };

  const quickSuggestions =
    Array.isArray(suggestions) && suggestions.length > 0
      ? suggestions
      : getBotSuggestions(botId);

  return (
    <Stack gap="sm">
      <Group justify="space-between" wrap="wrap" gap="xs">
        <Group gap="xs">
          <MessageSquare size={16} />
          <Text fw={600} size="sm">
            Conversar com {botName}
          </Text>
          {botSubtitle && (
            <Text size="xs" c="dimmed">
              · {botSubtitle}
            </Text>
          )}
        </Group>
        {chatId && (
          <Badge size="xs" variant="light" color="gray">
            Histórico ativo
          </Badge>
        )}
      </Group>

      <Paper
        withBorder
        p="md"
        radius="md"
        style={{ minHeight, maxHeight, overflowY: "auto" }}
      >
        {loadingHistory ? (
          <Group gap="xs" justify="center" h={Math.max(140, minHeight - 40)}>
            <Loader size="xs" />
            <Text size="xs" c="dimmed">
              Carregando conversa…
            </Text>
          </Group>
        ) : !messages.length ? (
          <Stack
            align="center"
            justify="center"
            gap="sm"
            mih={Math.max(160, minHeight - 40)}
          >
            <BotIcon size={28} opacity={0.45} />
            <Text size="sm" c="dimmed" ta="center">
              Envie uma mensagem para conversar diretamente com {botName}.
            </Text>
            <Group gap="xs" justify="center" wrap="wrap">
              {quickSuggestions.map((prompt) => (
                <Button
                  key={prompt}
                  size="xs"
                  variant="light"
                  onClick={safe(() => sendMessage(prompt))}
                >
                  {prompt}
                </Button>
              ))}
            </Group>
          </Stack>
        ) : (
          <Stack gap="sm">
            {messages.map((msg) => {
              const isSpeaking =
                speakingState.id === msg.id && speakingState.status !== "idle";
              return (
                <Paper
                  key={msg.id}
                  withBorder
                  p="sm"
                  radius="md"
                  style={{
                    borderColor:
                      msg.role === "user"
                        ? "var(--mantine-color-violet-7)"
                        : undefined,
                  }}
                >
                  <Group justify="space-between" mb={4}>
                    <Text size="xs" fw={600} c="dimmed">
                      {msg.role === "user" ? "Você" : botName}
                    </Text>
                    <Group gap="xs">
                      {msg.status === "running" && (
                        <Group gap={6}>
                          <Loader size={12} />
                          <Text size="xs" c="violet">
                            Respondendo…
                          </Text>
                        </Group>
                      )}
                      {msg.status === "cancelled" && (
                        <Badge size="xs" color="yellow" variant="light">
                          Cancelado
                        </Badge>
                      )}
                      {msg.status === "error" && (
                        <Badge size="xs" color="red" variant="light">
                          Erro
                        </Badge>
                      )}
                      {msg.role === "assistant" &&
                        msg.status !== "running" &&
                        msg.text?.trim() && (
                          <Tooltip
                            label={
                              isSpeaking ? "Parar leitura" : "Ouvir resposta"
                            }
                          >
                            <ActionIcon
                              size="xs"
                              variant="subtle"
                              color={isSpeaking ? "red" : "violet"}
                              onClick={() =>
                                speechControllerRef.current?.toggle({
                                  id: msg.id,
                                  content: msg.text,
                                })
                              }
                            >
                              {isSpeaking ? (
                                <VolumeX size={13} />
                              ) : (
                                <Volume2 size={13} />
                              )}
                            </ActionIcon>
                          </Tooltip>
                        )}
                    </Group>
                  </Group>
                  {msg.text ? (
                    msg.role === "assistant" ? (
                      <div className="markdown-body" style={{ fontSize: 14 }}>
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {msg.text}
                        </ReactMarkdown>
                      </div>
                    ) : (
                      <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
                        {msg.text}
                      </Text>
                    )
                  ) : msg.status === "running" ? (
                    <Text size="xs" c="dimmed">
                      Aguardando resposta…
                    </Text>
                  ) : null}
                  {msg.error && (
                    <Text size="xs" c="red" mt={4}>
                      {msg.error}
                    </Text>
                  )}
                </Paper>
              );
            })}
            <div ref={transcriptEndRef} />
          </Stack>
        )}
      </Paper>

      <Paper withBorder p="sm" radius="md">
        <Stack gap="xs">
          <Textarea
            placeholder={`Converse com ${botName}…`}
            minRows={2}
            maxRows={5}
            autosize
            disabled={Boolean(activeJobId)}
            value={inputText}
            onChange={(e) => setInputText(e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
              }
            }}
          />
          <Group justify="space-between" wrap="wrap" gap="xs">
            <Text size="xs" c="dimmed">
              Enter para enviar · Shift+Enter para quebrar linha
            </Text>
            {activeJobId ? (
              <Button
                size="xs"
                color="red"
                variant="light"
                leftSection={<Square size={12} />}
                onClick={safe(cancelJob)}
              >
                Parar resposta
              </Button>
            ) : (
              <Button
                size="xs"
                disabled={!inputText.trim()}
                leftSection={<Send size={13} />}
                onClick={safe(() => sendMessage())}
              >
                Enviar
              </Button>
            )}
          </Group>
        </Stack>
      </Paper>
    </Stack>
  );
}
