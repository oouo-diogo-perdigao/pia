import { MediaTrack } from "../../../../src/pia/frontend/MediaPlayer";
import { RotateCcw } from "lucide-react";
import React, { useEffect, useState, useRef } from "react";
import {
  Stack,
  Paper,
  Title,
  Text,
  Textarea,
  Select,
  NumberInput,
  Button,
  Group,
  Anchor,
} from "@mantine/core";
import {
  appApi,
  report,
  safe,
  watchJob,
  copy,
} from "../../../../src/pia/frontend/api";
import {
  About,
  LogViewer,
  WorkProgress,
  Icon,
  usePia,
} from "../../../../src/pia/frontend/shared";
import {
  MUSIC_PROVIDERS_UPDATED_EVENT,
  SUNO_CANCEL_WARNING,
  SUNO_HINT_TEXT,
  buildGeneratorOptions,
  generatorHints,
  finalStateForError,
  interruptedProgressLabel,
  providerLabel,
  resolveInitialProvider,
  resolveProviderAfterRefresh,
  resolveReuseProvider,
  shouldShowSunoHint,
  sunoSettingsRoute,
} from "../../../../src/pia/frontend/music-helpers";
const call = (action, data = {}) => appApi("music", action, data);
export default function Music({ sub = "principal" }) {
  const { navigate, route } = usePia();
  const currentSub = useRef(sub);
  currentSub.current = sub;
  const [prompt, setPrompt] = useState(""),
    [lyrics, setLyrics] = useState(""),
    [provider, setProvider] = useState("local"),
    [duration, setDuration] = useState(30),
    [items, setItems] = useState([]),
    [busy, setBusy] = useState(false),
    [logs, setLogs] = useState(""),
    [job, setJob] = useState(null),
    [count, setCount] = useState(1),
    [progress, setProgress] = useState(null),
    [folder, setFolder] = useState(""),
    [scrollBatch, setScrollBatch] = useState(null),
    [catalog, setCatalog] = useState(null),
    [notice, setNoticeState] = useState({ text: "", source: "" });
  const providerReady = useRef(false),
    providerRef = useRef(provider),
    busyRef = useRef(busy),
    alive = useRef(true),
    catalogRequest = useRef(0),
    pendingReuse = useRef(null);
  // source: "refresh" (catálogo mudou) ou "user" (reuse); o refresh só limpa
  // o próprio aviso.
  const setNotice = (text, source = "user") =>
    setNoticeState({ text: text || "", source: text ? source : "" });
  providerRef.current = provider;
  busyRef.current = busy;
  const source = useRef(),
    form = useRef(),
    promptInput = useRef();
  function reuse(tracks) {
    const item = tracks[0];
    setPrompt(item.prompt || "");
    setLyrics(item.lyrics || "");
    const reused = resolveReuseProvider(item, catalog);
    providerReady.current = true;
    pendingReuse.current = reused.pending ? item : null;
    setProvider(reused.provider);
    setNotice(reused.warning);
    setDuration(
      Number.isInteger(item.requested_duration)
        ? Math.max(10, Math.min(180, item.requested_duration))
        : 30,
    );
    setCount(Math.max(1, Math.min(10, tracks.length)));
    setScrollBatch(null);
    navigate({ ...route, sub: "principal" });
    requestAnimationFrame(() => {
      form.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      promptInput.current?.focus({ preventScroll: true });
    });
  }
  function follow(identity) {
    setBusy(true);
    setJob(identity);
    source.current?.close();
    source.current = watchJob(identity, (event) => {
      if (!alive.current) return;
      if (event.type === "progress") setProgress(event.value);
      if (event.type === "track")
        setItems((old) => [
          event.item,
          ...old.filter((item) => item.file !== event.item.file),
        ]);
      if (event.type === "log") setLogs((old) => old + event.text + "\n");
      if (["done", "error"].includes(event.type)) {
        setBusy(false);
        busyRef.current = false;
        // Ex.: 401 do Suno durante a geração muda a disponibilidade.
        loadProviders();
        if (event.type === "error") {
          setProgress((old) =>
            old
              ? {
                  ...old,
                  state: finalStateForError(old, event),
                  label: interruptedProgressLabel(event),
                }
              : null,
          );
          report(event.error);
        } else {
          setScrollBatch(event.result?.batch);
          if (event.result?.batch && currentSub.current === "principal")
            navigate({ ...route, sub: "history" });
          refresh().catch(report);
        }
      }
    });
  }
  const refresh = () =>
    call("library").then((value) => {
      if (!alive.current) return;
      setItems(value.items);
      setFolder(value.folder || "");
      if (value.job && !source.current) follow(value.job);
    });
  // Catálogo de provedores: fonte da verdade para o seletor (RN03/RN05).
  // Em erro mantém o último catálogo válido; sem nenhum, o seletor cai em
  // Local, Gemini e Flow sem quebrar a tela.
  // Só a resposta mais recente é aplicada (requisições fora de ordem).
  const loadProviders = () => {
    const requestId = ++catalogRequest.current;
    return call("providers")
      .catch(() => null)
      .then((value) => {
        if (!alive.current || requestId !== catalogRequest.current) return;
        const valid = value && Array.isArray(value.providers) ? value : null;
        if (valid) setCatalog(valid);
        if (!providerReady.current) {
          providerReady.current = true;
          setProvider(resolveInitialProvider(valid));
          return;
        }
        if (!valid) return;
        if (pendingReuse.current && !busyRef.current) {
          const reused = resolveReuseProvider(pendingReuse.current, valid);
          pendingReuse.current = null;
          setProvider(reused.provider);
          setNotice(reused.warning);
          return;
        }
        const next = resolveProviderAfterRefresh(
          providerRef.current,
          valid,
          busyRef.current,
        );
        if (next.provider !== providerRef.current) setProvider(next.provider);
        if (next.warning) setNotice(next.warning, "refresh");
        else
          setNoticeState((old) =>
            old.source === "refresh" ? { text: "", source: "" } : old,
          );
      });
  };
  useEffect(() => {
    alive.current = true;
    refresh().catch((error) => alive.current && report(error));
    return () => {
      alive.current = false;
      source.current?.close();
    };
  }, []);
  useEffect(() => {
    let timer;
    const schedule = () => {
      clearTimeout(timer);
      timer = setTimeout(loadProviders, 500);
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") schedule();
    };
    loadProviders();
    window.addEventListener("focus", schedule);
    window.addEventListener(MUSIC_PROVIDERS_UPDATED_EVENT, schedule);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("focus", schedule);
      window.removeEventListener(MUSIC_PROVIDERS_UPDATED_EVENT, schedule);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);
  useEffect(() => {
    if (scrollBatch && sub === "history")
      requestAnimationFrame(() =>
        document
          .getElementById("music-batch-" + scrollBatch)
          ?.scrollIntoView({ behavior: "smooth", block: "start" }),
      );
  }, [scrollBatch, items, sub]);
  async function start(action) {
    setBusy(true);
    setLogs("");
    setProgress(null);
    if (action === "generate") setNotice("");
    try {
      const response = await call(
        action,
        action === "generate"
          ? { prompt, lyrics, provider, duration, count }
          : {},
      );
      follow(response.job);
    } catch (error) {
      setBusy(false);
      throw error;
    }
  }
  if (sub === "about")
    return (
      <About>
        <Text>
          Descreva o estilo musical e informe uma letra para voz cantada, ou
          deixe-a vazia para instrumental. O motor ACE-Step roda localmente em
          ambiente separado; a preparação baixa dependências de vários GB e o
          primeiro início baixa modelos. A qualidade e o tempo dependem da GPU.
          Gemini/Lyria usa a chave da PIA e a disponibilidade da API; o login do
          Gmail/Drive ou uma assinatura Gemini não substituem essa credencial.
          Suno aparece no seletor quando o MCP do Suno está configurado e
          autenticado em Configurações → Música; cada faixa gerada nele pode
          consumir créditos da sua conta. Flow Music abre na interface oficial
          da sua conta, sem geração automatizada pela PIA. Cancelar encerra a
          espera; uma tarefa já enviada ao motor/provedor pode continuar nele.
        </Text>
      </About>
    );
  return (
    <Stack>
      {sub !== "history" && (
        <>
          <Paper withBorder p="lg" ref={form}>
            <Stack>
              <Select
                label="Gerador"
                value={provider}
                onChange={(value) => {
                  if (!value) return;
                  providerReady.current = true;
                  pendingReuse.current = null;
                  setProvider(value);
                  setNotice("");
                }}
                disabled={busy}
                allowDeselect={false}
                data={buildGeneratorOptions(
                  catalog,
                  busy || !catalog || pendingReuse.current ? provider : null,
                )}
              />
              {shouldShowSunoHint(catalog) && (
                <Text size="xs" c="dimmed">
                  {SUNO_HINT_TEXT}.{" "}
                  <Anchor
                    component="button"
                    type="button"
                    size="xs"
                    onClick={() => navigate(sunoSettingsRoute(catalog))}
                  >
                    Abrir Configurações
                  </Anchor>
                </Text>
              )}
              {notice.text && (
                <Text size="sm" c="yellow">
                  {notice.text}
                </Text>
              )}
              <Textarea
                label="Descrição musical"
                ref={promptInput}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                minRows={3}
                autosize
              />
              <Textarea
                label="Letra (vazio gera instrumental)"
                value={lyrics}
                onChange={(e) => setLyrics(e.target.value)}
                minRows={5}
                autosize
              />
              <NumberInput
                label="Duração desejada (segundos)"
                min={10}
                max={180}
                value={duration}
                onChange={setDuration}
              />
              <NumberInput
                label="Quantidade de músicas"
                min={1}
                max={10}
                allowDecimal={false}
                value={count}
                onChange={setCount}
                disabled={busy}
              />
              <Text size="xs" c="dimmed">
                Destino: {folder || "Pasta de músicas do sistema / PIA"}
              </Text>
              <Group>
                {provider === "flow" ? (
                  <>
                    <Button
                      onClick={safe(() => copy(prompt + "\n\n" + lyrics))}
                    >
                      Copiar descrição e letra
                    </Button>
                    <Anchor href="https://www.flowmusic.app/" target="_blank">
                      Abrir acesso oficial ao Flow Music ↗
                    </Anchor>
                  </>
                ) : (
                  <Button
                    disabled={busy || !prompt.trim()}
                    onClick={safe(() => start("generate"))}
                  >
                    Gerar música
                  </Button>
                )}
                {provider === "local" && (
                  <Button
                    variant="light"
                    disabled={busy}
                    onClick={safe(() => start("prepare-local"))}
                  >
                    Instalar motor local (vários GB)
                  </Button>
                )}
                {busy && (
                  <Button
                    color="red"
                    onClick={safe(() => call("cancel", { job }))}
                  >
                    Cancelar espera
                  </Button>
                )}
              </Group>
              {generatorHints(provider).map((hint, index) => (
                <Text
                  size="xs"
                  c={hint === SUNO_CANCEL_WARNING ? "yellow" : "dimmed"}
                  key={index}
                >
                  {hint}
                </Text>
              ))}
              <Text size="sm" c="dimmed">
                A PIA não usa cookies das contas para simular APIs. O motor
                local fica separado do Whisper/TTS.
              </Text>
            </Stack>
          </Paper>
          <LogViewer text={logs} onClear={() => setLogs("")} />
          <WorkProgress value={progress} />
          {busy && (
            <Text size="xs" c="dimmed">
              O percentual indica músicas concluídas do lote. O provedor não
              fornece percentual confiável da geração individual.
            </Text>
          )}
        </>
      )}
      {sub === "history" && (
        <>
          <Title order={4}>Suas músicas</Title>
          {!items.length && (
            <Text c="dimmed">Nenhuma música gerada ainda.</Text>
          )}
          {Object.entries(
            items.reduce((groups, item) => {
              (groups[item.batch || item.file] ||= []).push(item);
              return groups;
            }, {}),
          ).map(([batch, tracks]) => (
            <Paper withBorder p="md" key={batch} id={"music-batch-" + batch}>
              <Stack>
                <Group justify="space-between" wrap="nowrap" align="start">
                  <Text fw={600}>{tracks[0].prompt}</Text>
                  <Icon
                    icon={RotateCcw}
                    label="Reutilizar prompt"
                    disabled={busy}
                    onClick={() => reuse(tracks)}
                  />
                </Group>
                <Text size="xs" c="dimmed">
                  {tracks.length} música(s) ·{" "}
                  {providerLabel(tracks[0].provider)}
                </Text>
                {tracks
                  .sort((a, b) => (a.variant || 0) - (b.variant || 0))
                  .map((item, index) => (
                    <div key={item.file}>
                      <MediaTrack
                        url={item.audio_url}
                        title={"Versão " + (index + 1)}
                      />
                      <Anchor href={item.audio_url} download={item.file}>
                        Salvar áudio
                      </Anchor>
                    </div>
                  ))}
              </Stack>
            </Paper>
          ))}
        </>
      )}
    </Stack>
  );
}
