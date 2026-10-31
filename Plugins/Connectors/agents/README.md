# Agentes externos

Conector para Codex CLI e Google Antigravity CLI (`agy`). Instale o CLI oficial e faça login no próprio CLI antes de usar Configurações → Conectores → Agentes externos. A PIA reutiliza a sessão local; não copia cookies ou arquivos de autenticação. Os executáveis podem ser configurados nas variáveis deste conector.

As chamadas recebem a mensagem por stdin, em diretório de trabalho separado, com `codex exec --sandbox read-only` ou `agy --mode plan --input-format stream-json --output-format stream-json`. A entrada AGY contém um único evento user; só um resultado terminal SUCCESS é aceito. Não fornece o diretório do projeto como workspace. Timeout: 300 segundos. Consulte os logs em Inspeção e logs. Não é controle remoto da janela do Codex ou Antigravity.

## Usar o Antigravity

1. Instale o [Antigravity CLI oficial](https://antigravity.google/docs/getting-started?tab=cli).
2. Execute `agy` no terminal e conclua o login Google. Saia da sessão interativa antes de testar na PIA.
3. Reinicie a PIA e selecione **Google Antigravity · AGY** em Configurações → Conectores → Agentes externos.
4. Se o executável não for encontrado, configure `AGENTS_AGY_EXECUTABLE` com o caminho do `agy.exe` no Windows ou do binário `agy` no Linux. O conector também procura em `~/.local/bin` e, no Windows, `%LOCALAPPDATA%/agy/bin/agy.exe`.
5. Envie uma mensagem pelo painel ou peça no chat: “Consulte o Antigravity e explique este problema”.

`AGENTS_GEMINI_EXECUTABLE` foi aposentada no conector e não é reutilizada: seu caminho apontava para outro programa. Credenciais e configurações pessoais dos CLIs não são migradas pela PIA. Gemini como provedor de LLM/STT ou música continua independente dessa substituição.

O modo plan respeita as permissões do próprio AGY; a PIA não acrescenta flags de aprovação irrestrita nem altera permissões globais. Consulte [headless/stdin](https://antigravity.google/docs/cli/headless/) e [modos](https://antigravity.google/docs/cli/modes).

Para novos conectores, forneça `pia.json`, `plugin.toml`, `.env.example` e `lang/pt-BR.json`. Implemente operações no serviço e registre explicitamente as ferramentas em `src/tool_registry.py`; valide argumentos e nunca aceite comandos arbitrários de shell. A PIA fornece configurações tipadas, jobs, logs e acesso às contas dos conectores por identificador explícito.

O ícone de ajuda do painel abre instruções específicas para cada CLI, com comandos de instalação, login, versão e obtenção do caminho do executável. Os protocolos disponíveis no painel são MCP e AG-UI; ACP legado e A2A síncrono não fazem mais parte da PIA.

Para o sentido inverso — Codex acessando ferramentas da PIA — consulte [o guia MCP, incluindo autenticação e login](../../../docs/MCP_CODEX.md). Cadastrar esse MCP não exige AGENTS_CODEX_EXECUTABLE.
