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
import { About, LogViewer } from "../../../../src/pia/frontend/shared";
const call = (action, data = {}) => appApi("music", action, data);
export default function Music({ sub = "principal" }) {
  const [prompt, setPrompt] = useState(""),
    [lyrics, setLyrics] = useState(""),
    [provider, setProvider] = useState("local"),
    [duration, setDuration] = useState(30),
    [items, setItems] = useState([]),
    [busy, setBusy] = useState(false),
    [logs, setLogs] = useState(""),
    [job, setJob] = useState(null);
  const source = useRef();
  function follow(identity) {
    setBusy(true);
    setJob(identity);
    source.current?.close();
    source.current = watchJob(identity, (event) => {
      if (event.type === "log") setLogs((old) => old + event.text + "\n");
      if (["done", "error"].includes(event.type)) {
        setBusy(false);
        if (event.type === "error") report(event.error);
        else refresh().catch(report);
      }
    });
  }
  const refresh = () =>
    call("library").then((value) => {
      setItems(value.items);
      if (value.job && !source.current) follow(value.job);
    });
  useEffect(() => {
    refresh().catch(report);
    return () => source.current?.close();
  }, []);
  async function start(action) {
    setBusy(true);
    setLogs("");
    try {
      const response = await call(
        action,
        action === "generate" ? { prompt, lyrics, provider, duration } : {},
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
          Flow Music abre na interface oficial da sua conta, sem geração
          automatizada pela PIA. Cancelar encerra a espera; uma tarefa já
          enviada ao motor/provedor pode continuar nele.
        </Text>
      </About>
    );
  return (
    <Stack>
      <Paper withBorder p="lg">
        <Stack>
          <Select
            label="Gerador"
            value={provider}
            onChange={setProvider}
            disabled={busy}
            data={[
              { value: "local", label: "Local · ACE-Step" },
              { value: "gemini", label: "Gemini · Lyria API" },
              {
                value: "flow",
                label: "Google Flow Music · abrir interface oficial",
              },
            ]}
          />
          <Textarea
            label="Descrição musical"
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
          <Group>
            {provider === "flow" ? (
              <>
                <Button onClick={safe(() => copy(prompt + "\n\n" + lyrics))}>
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
              <Button color="red" onClick={safe(() => call("cancel", { job }))}>
                Cancelar espera
              </Button>
            )}
          </Group>
          <Text size="sm" c="dimmed">
            A PIA não usa cookies das contas para simular APIs. O motor local
            fica separado do Whisper/TTS.
          </Text>
        </Stack>
      </Paper>
      <LogViewer text={logs} onClear={() => setLogs("")} />
      <Title order={4}>Suas músicas</Title>
      {items.map((item) => (
        <Paper withBorder p="md" key={item.file}>
          <Text>{item.prompt}</Text>
          <Text size="xs" c="dimmed">
            {item.provider} · duração solicitada: {item.requested_duration}s
          </Text>
          <audio
            controls
            preload="none"
            src={item.audio_url}
            style={{ width: "100%", marginTop: 10 }}
          />
          <Anchor href={item.audio_url} download={item.file}>
            Salvar áudio
          </Anchor>
        </Paper>
      ))}
    </Stack>
  );
}
