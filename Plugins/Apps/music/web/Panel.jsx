import { MediaTrack } from "../../../../src/pia/frontend/MediaPlayer";
import { Folder, RotateCcw, Trash2 } from "lucide-react";
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
  Badge,
  Collapse,
} from "@mantine/core";
import {
  api,
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
  buildGeneratorOptions,
  generatorHints,
  finalStateForError,
  interruptedProgressLabel,
  resolveInitialProvider,
  resolveProviderAfterRefresh,
  resolveReuseProvider,
} from "../../../../src/pia/frontend/music-helpers";
import {
  SUNO_ACCOUNT_FIELD_LABEL,
  SUNO_ACCOUNT_REQUIRED_HINT,
  activeJobBlockText,
  buildGeneratePayload,
  connectionNotice,
  describeSunoError,
  generateButtonState,
  progressDisplay,
  resolveResumeJob,
  resolveSunoAccountSelection,
  sunoUnavailableHint,
} from "../../../../src/pia/frontend/music-suno-helpers";
import {
  HISTORY_DELETE_CONFIRM,
  HISTORY_EMPTY_TEXT,
  HISTORY_LOAD_MORE_LABEL,
  HISTORY_REDOWNLOAD_LABEL,
  HISTORY_REUSE_LABEL,
  applyHistoryPage,
  historyDateLabel,
  historyFilePath,
  historyFromLibrary,
  historyGeneratorLabel,
  historyNotice,
  historyPath,
  historyStateColor,
  historyStateLabel,
  historyTrackAction,
  historyTrackLabel,
  historyTrackTitle,
  removeHistoryItem,
  replaceHistoryTrack,
  reuseFromHistory,
  trackFromRedownloadEvent,
  visibleHistoryItems,
} from "../../../../src/pia/frontend/music-history-helpers";
const call = (action, data = {}) => appApi("music", action, data);
const EMPTY_HISTORY = {
  items: [],
  nextCursor: null,
  serverUnavailable: false,
  serverReason: null,
  loaded: false,
  fallback: false,
};
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
    [scrollTarget, setScrollTarget] = useState(null),
    [catalog, setCatalog] = useState(null),
    [notice, setNoticeState] = useState({ text: "", source: "" }),
    // RN09: conta Suno escolhida NESTA sessão (2+ contas). Começa vazia e
    // volta a ficar vazia após cada geração; o selected_account_id do
    // backend não pré-seleciona.
    [sunoAccount, setSunoAccount] = useState(null),
    [connectionLost, setConnectionLost] = useState(""),
    [history, setHistory] = useState(EMPTY_HISTORY),
    [historyBusy, setHistoryBusy] = useState(false),
    [historyError, setHistoryError] = useState(null),
    [redownloading, setRedownloading] = useState({}),
    [openLyrics, setOpenLyrics] = useState({});
  const providerReady = useRef(false),
    providerRef = useRef(provider),
    busyRef = useRef(busy),
    jobRef = useRef(job),
    alive = useRef(true),
    catalogRequest = useRef(0),
    historyRequest = useRef(0),
    pendingReuse = useRef(null),
    jobAccountName = useRef(""),
    redownloadSources = useRef({});
  // source: "refresh" (catálogo mudou) ou "user" (reuse); o refresh só limpa
  // o próprio aviso.
  const setNotice = (text, source = "user") =>
    setNoticeState({ text: text || "", source: text ? source : "" });
  providerRef.current = provider;
  busyRef.current = busy;
  jobRef.current = job;
  const source = useRef(),
    form = useRef(),
    promptInput = useRef();
  const accountSelection = resolveSunoAccountSelection(catalog, sunoAccount);
  const jobBlock = activeJobBlockText(catalog, busy ? job : null);
  const generateState = generateButtonState({
    provider,
    prompt,
    busy,
    selection: accountSelection,
    blockText: jobBlock,
  });
  const unavailableHint = sunoUnavailableHint(catalog);
  // "Reutilizar prompt" (RN18/RN25): preenche o Gerador com o params do item.
  function reuse(item) {
    const reused = reuseFromHistory(item, catalog);
    setPrompt(reused.prompt);
    setLyrics(reused.lyrics);
    providerReady.current = true;
    pendingReuse.current = reused.pending
      ? { provider: item?.params?.provider || item?.provider }
      : null;
    setProvider(reused.provider);
    setNotice(reused.warning);
    setDuration(reused.duration);
    setCount(reused.count);
    // RN09: com 2+ contas não pré-seleciona; com 1, a seleção é automática.
    setSunoAccount(null);
    setScrollTarget(null);
    navigate({ ...route, sub: "principal" });
    requestAnimationFrame(() => {
      form.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      promptInput.current?.focus({ preventScroll: true });
    });
  }
  function follow(identity) {
    setBusy(true);
    busyRef.current = true;
    setJob(identity);
    jobRef.current = identity;
    setConnectionLost("");
    source.current?.close();
    source.current = watchJob(identity, (event) => {
      if (!alive.current) return;
      if (event.type === "progress") {
        setProgress(progressDisplay(event.value));
        // RN09/RN11: conexão perdida não encerra o job.
        setConnectionLost(connectionNotice(event.value));
      }
      if (event.type === "track")
        setItems((old) => [
          event.item,
          ...old.filter((item) => item.file !== event.item.file),
        ]);
      if (event.type === "log") setLogs((old) => old + event.text + "\n");
      if (["done", "error"].includes(event.type)) {
        setBusy(false);
        busyRef.current = false;
        setConnectionLost("");
        // RN09: o campo "Conta Suno" volta a ficar vazio após cada geração.
        setSunoAccount(null);
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
          report(
            describeSunoError(event, { accountName: jobAccountName.current })
              .text,
          );
          refresh().catch(() => {});
        } else {
          setScrollTarget({
            batch: event.result?.batch || null,
            job: identity,
          });
          if (event.result?.batch && currentSub.current === "principal")
            navigate({ ...route, sub: "history" });
          refresh().catch(report);
        }
        loadHistory();
      }
    });
  }
  const refresh = () =>
    call("library").then((value) => {
      if (!alive.current) return;
      setItems(value.items);
      setFolder(value.folder || "");
      if (value.job && !busyRef.current) follow(value.job);
    });
  // Histórico da conta (RN25): 1ª página substitui; "Carregar mais" acrescenta.
  // Sem a rota (antes da T6) ou com falha sem resposta, mostra a biblioteca
  // local com o aviso de indisponível.
  const loadHistory = (cursor = null) => {
    const requestId = ++historyRequest.current;
    if (cursor) setHistoryBusy(true);
    return api(historyPath(cursor))
      .then((value) => {
        if (!alive.current || requestId !== historyRequest.current) return;
        setHistory((old) => ({
          ...applyHistoryPage(old, value, { append: Boolean(cursor) }),
          loaded: true,
          fallback: false,
        }));
      })
      .catch((error) => {
        if (!alive.current || requestId !== historyRequest.current) return;
        if (cursor) {
          setHistoryError(describeSunoError(error));
          return;
        }
        setHistory({
          ...EMPTY_HISTORY,
          serverUnavailable: true,
          serverReason: error?.code || null,
          loaded: true,
          fallback: true,
        });
      })
      .finally(() => cursor && alive.current && setHistoryBusy(false));
  };
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
        // RN15/CA14: job do Suno deste PC ainda ativo → retoma pelo watchJob.
        const resume =
          valid && !busyRef.current
            ? resolveResumeJob(valid, jobRef.current)
            : null;
        if (resume) follow(resume);
        if (!providerReady.current) {
          providerReady.current = true;
          setProvider(
            resume && valid ? "suno_mcp" : resolveInitialProvider(valid),
          );
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
      Object.values(redownloadSources.current).forEach((item) => item?.close());
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
    if (sub === "history") {
      setHistoryError(null);
      loadHistory();
    }
  }, [sub]);
  const shownHistory = history.fallback
    ? historyFromLibrary(items)
    : visibleHistoryItems(history);
  useEffect(() => {
    if (!scrollTarget || sub !== "history") return;
    const target = shownHistory.find(
      (item) =>
        (scrollTarget.job && item.job_id === scrollTarget.job) ||
        (scrollTarget.batch && item.id === scrollTarget.batch),
    );
    if (target)
      requestAnimationFrame(() =>
        document
          .getElementById("music-history-" + target.id)
          ?.scrollIntoView({ behavior: "smooth", block: "start" }),
      );
  }, [scrollTarget, history, items, sub]);
  async function start(action) {
    setBusy(true);
    setLogs("");
    setProgress(null);
    if (action === "generate") setNotice("");
    jobAccountName.current =
      provider === "suno_mcp" ? accountSelection.account?.name || "" : "";
    try {
      const response = await call(
        action,
        action === "generate"
          ? buildGeneratePayload({
              prompt,
              lyrics,
              provider,
              duration,
              count,
              sunoAccountId: accountSelection.value,
            })
          : {},
      );
      follow(response.job);
    } catch (error) {
      setBusy(false);
      if (provider === "suno_mcp" && action === "generate") {
        report(
          describeSunoError(error, { accountName: jobAccountName.current })
            .text,
        );
        loadProviders();
        return;
      }
      throw error;
    }
  }
  // RN25/RN13: excluir pede confirmação; o arquivo local fica no PC.
  async function removeItem(item) {
    if (!window.confirm(HISTORY_DELETE_CONFIRM)) return;
    setHistoryError(null);
    try {
      await api("/music/history/" + encodeURIComponent(item.id), undefined, {
        method: "DELETE",
      });
      setHistory((old) => ({
        ...old,
        items: removeHistoryItem(old.items, item.id),
      }));
    } catch (error) {
      // Offline: pia_server_unreachable; não pareado: pia_server_unpaired
      // (com atalho). O item continua na lista.
      setHistoryError(describeSunoError(error));
    }
  }
  // RN16/CA15: "Baixar novamente" vira job; o evento track troca só a faixa.
  async function redownload(item, track) {
    const key = item.id + ":" + track.n;
    if (redownloading[key]) return;
    setHistoryError(null);
    setRedownloading((old) => ({ ...old, [key]: true }));
    const finish = () => {
      delete redownloadSources.current[key];
      if (alive.current)
        setRedownloading((old) => {
          const next = { ...old };
          delete next[key];
          return next;
        });
    };
    try {
      const response = await api(
        "/music/history/" +
          encodeURIComponent(item.id) +
          "/tracks/" +
          encodeURIComponent(track.n) +
          "/redownload",
        {},
      );
      if (!response?.job_id) return finish();
      redownloadSources.current[key]?.close();
      redownloadSources.current[key] = watchJob(response.job_id, (event) => {
        if (!alive.current) return;
        if (event.type === "track") {
          const updated = trackFromRedownloadEvent(event);
          setHistory((old) => ({
            ...old,
            items: replaceHistoryTrack(old.items, item.id, track.n, updated),
          }));
        }
        if (event.type === "error") {
          setHistoryError(describeSunoError(event));
          finish();
        }
        if (event.type === "done") {
          // A T6 repete a faixa em result.track: cobre um "track" perdido.
          const updated = trackFromRedownloadEvent(event);
          if (updated)
            setHistory((old) => ({
              ...old,
              items: replaceHistoryTrack(old.items, item.id, track.n, updated),
            }));
          finish();
          refresh().catch(() => {});
        }
      });
    } catch (error) {
      setHistoryError(describeSunoError(error));
      finish();
    }
  }
  const revealFile = (file) => {
    const path = historyFilePath(file, folder);
    if (path) api("/native", { action: "reveal-file", payload: { path } });
  };
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
          Suno aparece no seletor quando a PIA está conectada à PIA Server e há
          uma conta Suno conectada em Configurações → Música; a conexão com o
          Suno fica na PIA Server e cada faixa gerada pode consumir créditos da
          conta Suno escolhida. Flow Music abre na interface oficial da sua
          conta, sem geração automatizada pela PIA. Cancelar encerra a espera;
          uma tarefa já enviada ao motor/provedor pode continuar nele.
        </Text>
      </About>
    );
  const notice25 = history.loaded ? historyNotice(history) : null;
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
              {unavailableHint && (
                <Text size="xs" c="dimmed">
                  {unavailableHint.text}{" "}
                  {unavailableHint.route && (
                    <Anchor
                      component="button"
                      type="button"
                      size="xs"
                      onClick={() => navigate(unavailableHint.route)}
                    >
                      Abrir Configurações
                    </Anchor>
                  )}
                </Text>
              )}
              {provider === "suno_mcp" &&
                accountSelection.mode === "single" && (
                  <Text size="sm" c="dimmed">
                    {accountSelection.text}
                  </Text>
                )}
              {provider === "suno_mcp" &&
                accountSelection.mode === "multiple" && (
                  <Select
                    label={SUNO_ACCOUNT_FIELD_LABEL}
                    placeholder={SUNO_ACCOUNT_REQUIRED_HINT}
                    required
                    value={accountSelection.value}
                    data={accountSelection.options}
                    onChange={(value) => setSunoAccount(value || null)}
                    disabled={busy}
                    allowDeselect={false}
                  />
                )}
              {provider === "suno_mcp" &&
                accountSelection.mode === "single" &&
                accountSelection.expired.map((account) => (
                  <Text size="xs" c="dimmed" key={account.id}>
                    {
                      accountSelection.options.find(
                        (option) => option.value === account.id,
                      )?.label
                    }
                  </Text>
                ))}
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
                    disabled={!generateState.enabled}
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
              {provider !== "flow" && generateState.hint && (
                <Text size="xs" c="yellow">
                  {generateState.hint}
                </Text>
              )}
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
          {connectionLost && (
            <Text size="sm" c="yellow">
              {connectionLost}
            </Text>
          )}
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
          {notice25 && (
            <Text size="sm" c="yellow">
              {notice25.text}{" "}
              {notice25.route && (
                <Anchor
                  component="button"
                  type="button"
                  size="sm"
                  onClick={() => navigate(notice25.route)}
                >
                  Abrir Configurações → PIA Server
                </Anchor>
              )}
            </Text>
          )}
          {historyError?.text && (
            <Text size="sm" c="red">
              {historyError.text}{" "}
              {historyError.route && (
                <Anchor
                  component="button"
                  type="button"
                  size="sm"
                  onClick={() => navigate(historyError.route)}
                >
                  Abrir Configurações
                </Anchor>
              )}
            </Text>
          )}
          {history.loaded && !shownHistory.length && (
            <Text c="dimmed">{HISTORY_EMPTY_TEXT}</Text>
          )}
          {shownHistory.map((item) => (
            <Paper
              withBorder
              p="md"
              key={item.id}
              id={"music-history-" + item.id}
            >
              <Stack>
                <Group justify="space-between" wrap="nowrap" align="start">
                  <Text fw={600}>{item.prompt}</Text>
                  <Group gap={4} wrap="nowrap">
                    <Icon
                      icon={RotateCcw}
                      label={HISTORY_REUSE_LABEL}
                      disabled={busy}
                      onClick={() => reuse(item)}
                    />
                    {!history.fallback && (
                      <Icon
                        icon={Trash2}
                        label="Excluir do histórico"
                        onClick={safe(() => removeItem(item))}
                      />
                    )}
                  </Group>
                </Group>
                <Group gap="xs">
                  <Text size="xs" c="dimmed">
                    {[
                      historyDateLabel(item.created_at),
                      historyGeneratorLabel(item),
                      item.suno_account?.name
                        ? "Conta Suno: " + item.suno_account.name
                        : "",
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </Text>
                  <Badge
                    size="xs"
                    variant="light"
                    color={historyStateColor(item)}
                  >
                    {historyStateLabel(
                      item,
                      busy && item.job_id && item.job_id === job
                        ? progress
                        : null,
                    )}
                  </Badge>
                </Group>
                {item.lyrics && (
                  <div>
                    <Anchor
                      component="button"
                      type="button"
                      size="xs"
                      onClick={() =>
                        setOpenLyrics((old) => ({
                          ...old,
                          [item.id]: !old[item.id],
                        }))
                      }
                    >
                      {openLyrics[item.id] ? "Ocultar letra" : "Mostrar letra"}
                    </Anchor>
                    <Collapse in={Boolean(openLyrics[item.id])}>
                      <Text size="sm" style={{ whiteSpace: "pre-wrap" }} mt={4}>
                        {item.lyrics}
                      </Text>
                    </Collapse>
                  </div>
                )}
                {item.tracks.map((track) => {
                  const action = historyTrackAction(track, {
                    serverUnavailable: history.serverUnavailable,
                  });
                  const label = historyTrackLabel(track);
                  const title = historyTrackTitle(track);
                  const key = item.id + ":" + track.n;
                  return (
                    <div key={key}>
                      <Group gap="xs" wrap="wrap">
                        {action.kind === "local" ? (
                          <MediaTrack url={action.url} title={title} />
                        ) : (
                          <Text size="sm">{title}</Text>
                        )}
                        {label && (
                          <Badge size="xs" variant="outline">
                            {label}
                          </Badge>
                        )}
                        {action.kind === "local" &&
                          historyFilePath(action.file, folder) && (
                            <Icon
                              icon={Folder}
                              label="Abrir pasta"
                              onClick={safe(() => revealFile(action.file))}
                            />
                          )}
                        {action.kind === "local" && (
                          <Anchor
                            size="sm"
                            href={action.url}
                            download={action.file.file}
                          >
                            Salvar áudio
                          </Anchor>
                        )}
                        {action.kind === "redownload" && (
                          <Button
                            size="xs"
                            variant="light"
                            loading={Boolean(redownloading[key])}
                            onClick={safe(() => redownload(item, track))}
                          >
                            {HISTORY_REDOWNLOAD_LABEL}
                          </Button>
                        )}
                        {action.kind === "text" && (
                          <Text size="xs" c="dimmed">
                            {action.text}
                          </Text>
                        )}
                      </Group>
                    </div>
                  );
                })}
              </Stack>
            </Paper>
          ))}
          {!history.fallback && history.nextCursor && (
            <Group justify="center">
              <Button
                variant="light"
                loading={historyBusy}
                onClick={safe(() => loadHistory(history.nextCursor))}
              >
                {HISTORY_LOAD_MORE_LABEL}
              </Button>
            </Group>
          )}
        </>
      )}
    </Stack>
  );
}
