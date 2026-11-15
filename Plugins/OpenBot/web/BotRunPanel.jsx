import React, { useEffect, useRef, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Divider,
  Group,
  Loader,
  Paper,
  Stack,
  Switch,
  Tabs,
  Text,
  Textarea,
} from "@mantine/core";
import {
  Bot as BotIcon,
  MessageSquare,
  Send,
  Settings,
  Square,
  Trash2,
  Volume2,
} from "lucide-react";
import { api, report, safe, watchJob } from "../../../src/pia/frontend/api";
import { usePia } from "../../../src/pia/frontend/shared";
import { notify } from "../../../src/pia/frontend/toasts";
import SafeSvgAvatar from "./SafeSvgAvatar";
import BotEditor from "./BotEditor";

export default function BotRunPanel({ botId }) {
  const { state, route, refresh, navigate } = usePia();
  const [bot, setBot] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState(route?.tab === "config" ? "config" : "run");

  const [promptText, setPromptText] = useState("");
  const [speakReply, setSpeakReply] = useState(true);
  const [messages, setMessages] = useState([]);
  const [activeRun, setActiveRun] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [speakingNow, setSpeakingNow] = useState(false);

  const jobSourceRef = useRef(null);
  const transcriptEndRef = useRef(null);

  const loadBot = async (id) => {
    setLoading(true);
    try {
      const doc = await api(`/openbot/bots/${id}`);
      setBot(doc);
      setSpeakReply(doc.speak_replies !== false);
    } catch (err) {
      report(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (jobSourceRef.current) {
      jobSourceRef.current.close();
      jobSourceRef.current = null;
    }
    setActiveRun(null);
    setMessages([]);
    setConfirmDelete(false);
    setTab(route?.tab === "config" ? "config" : "run");
    if (botId) loadBot(botId);
    return () => {
      if (jobSourceRef.current) {
        jobSourceRef.current.close();
        jobSourceRef.current = null;
      }
    };
  }, [botId]);

  useEffect(() => {
    if (!botId) return;
    let source;
    try {
      source = new EventSource("/api/pia/tts/status/stream");
      source.onmessage = (event) => {
        try {
          const val = JSON.parse(event.data);
          const isThisBot =
            val.speaker_id === botId || val.speaker_id === `dynamic:${botId}`;
          setSpeakingNow(Boolean(isThisBot && val.status === "playing"));
        } catch {}
      };
    } catch {}
    return () => {
      source?.close();
    };
  }, [botId]);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendPrompt = async () => {
    const trimmed = promptText.trim();
    if (!trimmed || activeRun || !bot) return;
    setPromptText("");

    const userMsgId = crypto.randomUUID();
    const assistantMsgId = crypto.randomUUID();
    setMessages((prev) => [
      ...prev,
      { id: userMsgId, role: "user", text: trimmed },
      { id: assistantMsgId, role: "assistant", text: "", status: "running" },
    ]);

    try {
      const started = await api(`/openbot/bots/${bot.id}/runs`, {
        input: trimmed,
        request_id: crypto.randomUUID(),
        speak: speakReply,
      });
      setActiveRun({ runId: started.run_id, jobId: started.job_id });

      const src = watchJob(started.job_id, (evt) => {
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
                    status: "done",
                  }
                : m,
            ),
          );
          setActiveRun(null);
          jobSourceRef.current = null;
        } else if (evt.type === "error") {
          const isCancel = evt.code === "cancelled";
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId
                ? {
                    ...m,
                    status: isCancel ? "cancelled" : "error",
                    error: evt.error || "Falha ao executar bot.",
                  }
                : m,
            ),
          );
          setActiveRun(null);
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
                error: err?.message || "Erro ao iniciar execução.",
              }
            : m,
        ),
      );
      setActiveRun(null);
      report(err);
    }
  };

  const cancelActiveRun = async () => {
    if (!activeRun?.runId) return;
    await api(`/openbot/runs/${activeRun.runId}/cancel`, {});
  };

  const handleDeleteBot = async () => {
    if (!bot) return;
    setDeleting(true);
    try {
      await api(`/openbot/bots/${bot.id}`, undefined, {
        method: "DELETE",
        headers: { "If-Match": String(bot.revision ?? 1) },
      });
      notify(`Bot "${bot.name}" excluído.`);
      await refresh();
      navigate({ view: "bots" });
    } catch (err) {
      report(err);
    } finally {
      setDeleting(false);
    }
  };

  if (loading) {
    return (
      <Group gap="xs" p="md">
        <Loader size="sm" />
        <Text size="sm">Carregando bot dinâmico…</Text>
      </Group>
    );
  }

  if (!bot) {
    return (
      <Alert color="red" title="Bot não encontrado">
        <Button
          size="xs"
          variant="light"
          onClick={() => navigate({ view: "bots" })}
        >
          Voltar para Bots
        </Button>
      </Alert>
    );
  }

  const voiceBadge =
    bot.voice?.mode === "custom" && bot.voice?.profile
      ? `Voz própria · ${bot.voice.profile.voice || bot.voice.profile.provider}`
      : "Voz Geral da PIA";

  return (
    <Stack gap="md">
      <Paper withBorder p="md" radius="md">
        <Group justify="space-between" wrap="wrap" gap="sm">
          <Group gap="sm">
            <SafeSvgAvatar
              src={bot.avatar_url || bot.avatar}
              colors={bot.avatar_colors}
              size={52}
              speaking={speakingNow}
              alt={bot.name}
            />
            <Stack gap={2}>
              <Group gap="xs" wrap="wrap">
                <Text fw={700} size="lg">
                  {bot.name}
                </Text>
                <Badge
                  size="sm"
                  variant="light"
                  color={bot.enabled ? "green" : "gray"}
                >
                  {bot.enabled ? "Ativo" : "Desativado"}
                </Badge>
                <Badge size="sm" variant="light" color="violet">
                  {voiceBadge}
                </Badge>
              </Group>
              {bot.description && (
                <Text size="sm" c="dimmed">
                  {bot.description}
                </Text>
              )}
            </Stack>
          </Group>
        </Group>
      </Paper>

      <Tabs value={tab} onChange={(val) => setTab(val || "run")}>
        <Tabs.List>
          <Tabs.Tab value="run" leftSection={<MessageSquare size={14} />}>
            Executar e Conversar
          </Tabs.Tab>
          <Tabs.Tab value="config" leftSection={<Settings size={14} />}>
            Configurações e AGENTS.md
          </Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="run" pt="md">
          <Stack gap="md">
            {!bot.enabled && (
              <Alert color="yellow" title="Bot desativado">
                Ative este bot na aba de configurações para executar novas
                solicitações.
              </Alert>
            )}

            <Paper
              withBorder
              p="md"
              radius="md"
              style={{
                minHeight: 260,
                maxHeight: 460,
                overflowY: "auto",
              }}
            >
              {!messages.length ? (
                <Stack align="center" justify="center" h={220} gap="xs">
                  <BotIcon size={32} opacity={0.45} />
                  <Text size="sm" c="dimmed">
                    Envie uma mensagem ou tarefa para {bot.name}.
                  </Text>
                </Stack>
              ) : (
                <Stack gap="sm">
                  {messages.map((msg) => (
                    <Paper
                      key={msg.id}
                      withBorder
                      p="sm"
                      radius="md"
                      style={{
                        borderColor:
                          msg.role === "user"
                            ? "var(--mantine-color-violet-8)"
                            : undefined,
                      }}
                    >
                      <Group justify="space-between" mb={4}>
                        <Text size="xs" fw={600} c="dimmed">
                          {msg.role === "user" ? "Você" : bot.name}
                        </Text>
                        {msg.status === "running" && (
                          <Group gap={6}>
                            <Loader size={12} />
                            <Text size="xs" c="violet">
                              Gerando…
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
                      </Group>
                      {msg.text ? (
                        <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
                          {msg.text}
                        </Text>
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
                  ))}
                  <div ref={transcriptEndRef} />
                </Stack>
              )}
            </Paper>

            <Paper withBorder p="sm" radius="md">
              <Stack gap="xs">
                <Textarea
                  placeholder={`Escreva uma tarefa para ${bot.name}…`}
                  minRows={2}
                  maxRows={6}
                  autosize
                  disabled={!bot.enabled || Boolean(activeRun)}
                  value={promptText}
                  onChange={(e) => setPromptText(e.currentTarget.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      sendPrompt();
                    }
                  }}
                />
                <Group justify="space-between" wrap="wrap" gap="xs">
                  <Switch
                    size="xs"
                    label={
                      <Group gap={4}>
                        <Volume2 size={13} />
                        <span>Falar resposta</span>
                      </Group>
                    }
                    checked={speakReply}
                    onChange={(e) => setSpeakReply(e.currentTarget.checked)}
                  />
                  <Group gap="xs">
                    {activeRun ? (
                      <Button
                        size="xs"
                        color="red"
                        variant="light"
                        leftSection={<Square size={12} />}
                        onClick={safe(cancelActiveRun)}
                      >
                        Cancelar execução
                      </Button>
                    ) : (
                      <Button
                        size="xs"
                        disabled={!bot.enabled || !promptText.trim()}
                        leftSection={<Send size={13} />}
                        onClick={safe(sendPrompt)}
                      >
                        Executar
                      </Button>
                    )}
                  </Group>
                </Group>
              </Stack>
            </Paper>
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="config" pt="md">
          <Stack gap="lg">
            <BotEditor
              bot={bot}
              allBots={state.bots || []}
              onSaved={(savedBot) => {
                setBot(savedBot);
                setSpeakReply(savedBot.speak_replies !== false);
              }}
            />

            <Divider color="red" label="Zona de Perigo" labelPosition="left" />

            <Paper withBorder p="md" radius="md">
              <Group justify="space-between" wrap="wrap" gap="sm">
                <Stack gap={2}>
                  <Text fw={600} size="sm" c="red">
                    Excluir este bot dinâmico
                  </Text>
                  <Text size="xs" c="dimmed">
                    Remove permanentemente o bot, suas instruções e sua voz
                    exclusiva. Não pode haver execução ativa.
                  </Text>
                </Stack>
                <Group gap="xs">
                  {confirmDelete && (
                    <Button
                      size="xs"
                      variant="subtle"
                      onClick={() => setConfirmDelete(false)}
                    >
                      Cancelar
                    </Button>
                  )}
                  <Button
                    size="xs"
                    color="red"
                    variant={confirmDelete ? "filled" : "light"}
                    loading={deleting}
                    leftSection={<Trash2 size={14} />}
                    onClick={safe(() => {
                      if (!confirmDelete) {
                        setConfirmDelete(true);
                        return;
                      }
                      return handleDeleteBot();
                    })}
                  >
                    {confirmDelete
                      ? "Confirmar exclusão definitiva"
                      : "Excluir bot"}
                  </Button>
                </Group>
              </Group>
            </Paper>
          </Stack>
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
