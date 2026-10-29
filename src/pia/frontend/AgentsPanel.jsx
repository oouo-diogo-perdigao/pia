import React, { useEffect, useState } from "react";
import {
  Paper,
  Stack,
  Text,
  Title,
  Button,
  Select,
  Textarea,
  Code,
  Anchor,
} from "@mantine/core";
import { api, report, safe, watchJob } from "./api";
import SettingsPanel from "./Settings";
export default function AgentsPanel() {
  const [status, setStatus] = useState({}),
    [provider, setProvider] = useState("codex"),
    [prompt, setPrompt] = useState(""),
    [result, setResult] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    api("/integrations/agents/status", {}).then(setStatus).catch(report);
  }, []);
  return (
    <Stack>
      <Paper withBorder p="lg">
        <Stack>
          <Title order={4}>Codex e Gemini</Title>
          <Text>
            Os CLIs usam os próprios logins existentes. A PIA não lê nem copia
            tokens de autenticação. As consultas usam os modos read-only/plan
            dos CLIs e um diretório de trabalho separado.
          </Text>
          <Select
            label="Agente"
            data={["codex", "gemini"]}
            value={provider}
            onChange={setProvider}
          />
          <Text size="sm">
            {status[provider]?.available
              ? "CLI encontrado. O acesso da conta será verificado na chamada."
              : "CLI não encontrado. Instale e autentique-o primeiro."}
          </Text>
          <Anchor
            target="_blank"
            href={
              provider === "codex"
                ? "https://developers.openai.com/codex/cli"
                : "https://geminicli.com/docs/get-started/authentication/"
            }
          >
            Instalação e login ↗
          </Anchor>
          <Textarea
            label="Mensagem ao agente"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            minRows={4}
          />
          <Button
            disabled={busy || !prompt.trim() || !status[provider]?.available}
            onClick={safe(async () => {
              setBusy(true);
              try {
                const job = await api("/integrations/agents/ask", {
                  provider,
                  prompt,
                });
                watchJob(job.job, (event) => {
                  if (event.type === "done") {
                    setResult(event.result.text);
                    setBusy(false);
                  }
                  if (event.type === "error") {
                    report(event.error);
                    setBusy(false);
                  }
                });
              } catch (error) {
                setBusy(false);
                throw error;
              }
            })}
          >
            Enviar ao agente
          </Button>
          <Text style={{ whiteSpace: "pre-wrap" }}>{result}</Text>
        </Stack>
      </Paper>
      <Paper withBorder p="lg">
        <Title order={4}>Protocolos da PIA</Title>
        <Text>
          MCP stateless HTTP, A2A síncrono 0.3, ACP legado síncrono e AG-UI com
          SSE. Todos exigem o Bearer configurado na PIA.
        </Text>
        <Code block>
          {
            "/protocols/mcp\n/.well-known/agent-card.json\n/protocols/a2a\n/protocols/acp/agents\n/protocols/acp/runs\n/protocols/ag-ui"
          }
        </Code>
        <Text size="sm">
          Cadastre o endpoint MCP no Codex/Gemini para disponibilizar as
          ferramentas da PIA ao outro agente. Isso não altera automaticamente a
          configuração dos CLIs.
        </Text>
      </Paper>
      <SettingsPanel section="Connectors/agents" />
    </Stack>
  );
}
