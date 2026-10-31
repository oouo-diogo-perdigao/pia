import React, { useState } from "react";
import {
  Modal,
  Stack,
  Text,
  Code,
  Select,
  Anchor,
  Group,
  Button,
} from "@mantine/core";
import { Copy, ExternalLink } from "lucide-react";
import { Icon } from "./shared";
import { copy } from "./api";

function Command({ children }) {
  return (
    <Group wrap="nowrap" align="start">
      <Code block className="grow">
        {children}
      </Code>
      <Icon
        feedback
        icon={Copy}
        label="Copiar comando"
        onClick={() => copy(children)}
      />
    </Group>
  );
}
export default function AgentSetup({ provider, opened, onClose, status }) {
  const [platform, setPlatform] = useState(
    /Win/i.test(navigator.platform) ? "windows" : "linux",
  );
  const codex = provider === "codex";
  const name = codex ? "Codex CLI" : "Google Antigravity CLI (AGY)";
  const docs = codex
    ? "https://developers.openai.com/codex/cli/"
    : "https://antigravity.google/docs/getting-started?tab=cli";
  const install = codex
    ? "npm install -g @openai/codex"
    : platform === "windows"
      ? "irm https://antigravity.google/cli/install.ps1 | iex"
      : "curl -fsSL https://antigravity.google/cli/install.sh | bash";
  const command = codex ? "codex" : "agy";
  const variable = codex ? "AGENTS_CODEX_EXECUTABLE" : "AGENTS_AGY_EXECUTABLE";
  const path =
    platform === "windows"
      ? codex
        ? "Get-Command codex.cmd,codex.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source"
        : "(Get-Command agy.exe -ErrorAction Stop).Source"
      : "command -v " + command;
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={"Configurar " + name}
      size="lg"
    >
      <Stack>
        <Anchor href={docs} target="_blank" rel="noreferrer">
          Documentação oficial · {name} ↗
        </Anchor>
        <Select
          label="Seu sistema / terminal"
          value={platform}
          onChange={setPlatform}
          data={[
            { value: "windows", label: "Windows · PowerShell" },
            { value: "linux", label: "Linux · Bash" },
          ]}
          allowDeselect={false}
        />
        <Text fw={600}>1. Instale o CLI no mesmo sistema da PIA</Text>
        {codex && (
          <Text size="sm">
            O comando abaixo usa npm. Se ainda não tem Node.js/npm, instale pelo{" "}
            <Anchor
              href="https://nodejs.org/en/download"
              target="_blank"
              rel="noreferrer"
            >
              site oficial do Node.js
            </Anchor>
            . Instalar a extensão de editor ou aplicativo desktop não substitui
            o CLI.
          </Text>
        )}
        <Command>{install}</Command>
        <Text fw={600}>2. Abra outro terminal, confira e faça login</Text>
        <Command>{command + " --version\n" + command}</Command>
        <Text size="sm">
          Siga o login no navegador solicitado pelo CLI e conclua a primeira
          configuração. Depois saia com /exit. A PIA usa essa sessão salva; não
          é preciso colar tokens na PIA.
        </Text>
        <Text fw={600}>3. Obtenha o caminho do executável</Text>
        <Command>{path}</Command>
        <Text size="sm">
          Copie uma linha com o caminho completo, sem aspas, para{" "}
          <Code>{variable}</Code> nas variáveis deste conector, logo abaixo do
          painel de consulta. No Windows use o agy.exe nativo; para Codex pode
          usar codex.cmd do npm ou codex.exe.
        </Text>
        {!codex && platform === "windows" && (
          <Text size="sm">
            Local padrão do instalador AGY:{" "}
            <Code>%LOCALAPPDATA%\agy\bin\agy.exe</Code>.
          </Text>
        )}
        {status?.executable && (
          <>
            <Text size="sm">Executável detectado pela PIA:</Text>
            <Command>{status.executable}</Command>
          </>
        )}
        <Text fw={600}>4. Salve, reinicie e teste</Text>
        <Text size="sm">
          Ao salvar variáveis, a PIA solicita o reinício. Se instalou o CLI
          depois de abrir a PIA, reinicie pelo menu da bandeja. Selecione o
          agente e envie uma pergunta curta, por exemplo “Responda apenas:
          conexão funcionando”. A consulta usa sua conta e está sujeita aos
          limites dela.
        </Text>
        <Text size="sm" c="dimmed">
          PIA Windows precisa do CLI Windows; instalação pelo WSL é Linux. O
          conector usa diretório separado, Codex read-only e AGY plan; não
          compartilha este projeto ou histórico automaticamente.
        </Text>
        <Button variant="light" onClick={onClose}>
          Entendi
        </Button>
      </Stack>
    </Modal>
  );
}
