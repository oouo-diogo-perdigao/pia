# Agentes externos

Conector para Codex CLI e Gemini CLI. Instale o CLI oficial e faça login no próprio CLI antes de usar a tela Conectores / Agentes externos. A PIA reutiliza a sessão local; não copia cookies ou arquivos de autenticação. Os executáveis podem ser configurados nas variáveis deste conector.

As chamadas recebem a mensagem por stdin, em diretório de trabalho separado, com `codex exec --sandbox read-only` ou Gemini `--approval-mode plan`. Não fornecem acesso de escrita ao projeto. Timeout: 300 segundos. Consulte os logs em Inspeção e logs. Não é controle remoto da janela do Codex.

Para novos conectores, forneça `pia.json`, `plugin.toml`, `.env.example` e `lang/pt-BR.json`. Implemente operações no serviço e registre explicitamente as ferramentas em `src/tool_registry.py`; valide argumentos e nunca aceite comandos arbitrários de shell. A PIA fornece configurações tipadas, jobs, logs e acesso às contas dos conectores por identificador explícito.
