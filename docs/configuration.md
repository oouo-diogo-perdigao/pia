# Configuração, contas e segredos

## Localização e contratos

Use `src/config_paths.py` para caminhos nativos: `config/.env`, keywords, models e shortcuts. Não reintroduza configurações na raiz. Migrações preservam configurações existentes sem sobrescrever destinos silenciosamente.

Cada extensão mantém `.env`, exemplos e arquivos próprios na pasta do plugin. Metadados públicos ficam em `pia.json`, entradas técnicas em `plugin.toml`. Não trate banco de histórico, modelos baixados ou logs como configuração.

Use `src.env_types` em vez de ler dotenv diretamente quando a seção oferece tipos. O sufixo é removido para consumidores Python:

```dotenv
ENABLED__BOOL=
PORT__INT=8762
TEMPERATURE__FLOAT=0.4
OUTPUT__PATH=
INPUT__FILE=
API_KEY__SECRET=
MODEL=exemplo
```

Todos os tipos aceitam vazio. Sem sufixo, o valor é string. Bool oferece `true`, `false`, vazio; números devem ser válidos e finitos. PATH/FILE usam seletores e validação conforme o editor existente. Preserve leitura de chaves legadas e migração para nomes tipados ao salvar.

FILE pode apontar para arquivo externo ou cópia gerenciada. Upload gerenciado fica em `files/` junto da seção, com nome baseado no plugin e variável; limite atual 5 MiB. Não copie arquivos externos automaticamente nem inclua uploads privados no Git.

## UI e aplicação

Use o editor compartilhado: diferenças do formulário habilitam Salvar, sucesso gera toast, segredo tem password/olho e campos oferecem link de obtenção/configuração por ícone. Omita seções de variáveis vazias. Salvar variáveis solicita reinício pelo fluxo existente, respeitando jobs em andamento e a limitação de instâncias sem launcher gráfico.

## Conectores

Contas e credenciais Google/Microsoft, Object Storage e Discord pertencem a Conectores. Apps selecionam recursos dessas contas, sem duplicar configuração. Podcast não deve pedir GOOGLE_APPLICATION_CREDENTIALS, chave LLM própria ou WHISPER; usa integração Google e serviços da PIA. `PODCAST_CONFIG` é editado pela tela de campanhas, não pelo editor genérico de variáveis.

Múltiplas contas exigem seleção explícita. Preserve o cofre do sistema e os serviços existentes para tokens/segredos. Não deduza que uma assinatura ou autorização Gmail/Drive permite chamar APIs Gemini/Lyria. CLIs de agentes usam seus próprios logins, sem copiar tokens.

Nunca registre valores secretos, cookies, tokens ou arquivos de credenciais. Exemplos usam placeholders. Não exponha configurações privadas no bundle nem em rotas públicas. Autorização interna de apps usa o mecanismo existente de tokens/escopo; não remova autenticação global por ser uma chamada local.

Detalhes de formato: [EXTENSIONS.md](EXTENSIONS.md). Fluxo de reinício: [REACT_WORKSPACE.md](REACT_WORKSPACE.md).
