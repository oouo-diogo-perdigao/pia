# Perfil, cofre e migração entre computadores

As configurações de usuário são editadas exclusivamente pela interface da PIA.
Não há configuração por `.env` ou por variáveis de ambiente. As variáveis técnicas
de sessão do sistema e dos subprocessos (display, PATH, contexto autenticado de app,
eventos de job etc.) continuam necessárias à execução; não são uma fonte alternativa
de configuração da PIA.

## Armazenamento

`src/user_paths.py` usa a pasta **Documentos** configurada no Windows (inclusive
redirecionamentos para OneDrive ou outra unidade) e `XDG_DOCUMENTS_DIR` no arquivo
de pastas do Linux, com fallback para `~/Documents`. Dentro dela:

| Caminho | Conteúdo |
| --- | --- |
| `pia/workspace.sqlite3` | Chats, ramificações, pastas, preferências, configurações e metadados de contas |
| `pia/chat/` | Imagens geradas ou fotografadas no chat |
| `pia/screenshots/` | Capturas salvas |
| `pia/music/` | Músicas e metadados |
| `pia/images/` | Imagens salvas por ações nativas |
| `pia/apps/podcast_automation/` | Downloads, trabalho e artefatos locais do podcast |
| `pia/files/` | Arquivos de configuração gerenciados que não são credenciais |

O cofre do sistema mantém chaves, senhas, client secrets, tokens OAuth e credenciais
de storage sob o serviço `PIA`. SQLite contém referências, nunca esses valores.
Arquivos de credenciais enviados pelo editor são guardados no cofre do sistema,
sem cópia persistente em texto; plugins podem usar `credential_file(section,name)`
para obter bytes. Contas legadas de storage passam a ser contas comuns e editáveis.

Na instalação continuam código, assets versionados, schemas, `.venv`, `cache/` e
`logs/`. A materialização de palavras de ativação exigida pelo Sherpa vai para
`cache/main/wakeword`, derivada do SQLite; não é uma segunda fonte de configuração.

## Interface

- **Configurações / Geral e plugins:** formulários tipados, com segredos mascarados.
- **Configurações / Conectores:** pareamento e acesso ao cadastro de integrações na PIA Server.
- **Configurações / Ativação e atalhos:** palavras de ativação, atalhos e catálogo,
  armazenados no SQLite. Os nomes históricos `.txt`/`.yaml` identificam documentos
  lógicos, não arquivos que precisam ser editados na instalação.
- **Configurações / Cofre:** lista de entradas geridas pela PIA; revelar é explícito.

## Conectores centralizados

No desktop, abra **Configurações / Conectores / PIA Server** e pareie cada computador.
Cadastre as contas Google, Microsoft, Object Storage, Discord e Taverns no painel
da PIA Server. Na primeira consulta o servidor aproveita o cadastro do último
perfil recebido. As alterações ficam disponíveis aos computadores pareados.
A interface não exporta nem importa arquivos de credenciais.

O perfil compartilhado ainda permite copiar configurações e conversas. Esse fluxo
não altera o cadastro dos conectores. Instalações com credenciais legadas preservam
as entradas locais, usadas apenas em modo não pareado.

## Atualização da instalação existente

No próximo início pelo launcher, sem uma versão antiga ainda rodando, a PIA:

- importa `.env` antigos em SQLite/cofre, sem aceitar o ambiente como override;
- importa configurações JSON de conectores, apps e bots, além dos documentos nativos;
- copia/une o banco de conversas preservando árvores e a ramificação ativa;
- move os dados antigos da instalação para o perfil, verificando cópias e sem
  sobrescrever arquivos diferentes no destino;
- remove as fontes migradas somente após confirmar sua gravação. Se o cofre falhar,
  as credenciais de origem ainda não confirmadas permanecem no local original.

Isso não é executado pelos testes contra o perfil pessoal. A migração entre cofre e
filesystem não é uma transação distribuída; após uma falha, corrija o acesso ao cofre
e reinicie para retomar. Não apague fontes manualmente antes de confirmar os dados.

## Desenvolver configurações

Declare `settings.schema.json` com itens `{name,type,default,label,link}` no núcleo
ou na extensão. Tipos: `bool,int,float,path,file,secret,string`; todos aceitam vazio.
Use `settings_store.get(name,default,section=...)`, `values(section)`,
`get_store().save(section,values)` e `document/save_document` para estruturas.
Credenciais de contas usam `KeyringVault`, que registra entradas para exportação.
Não grave segredos em documentos JSON; use schemas secretos ou o cofre.

Novas rotas locais autenticadas: `POST /api/pia/settings/export`,
`POST /api/pia/settings/import-preview`, `POST /api/pia/settings/import`,
`GET|POST /api/pia/settings/documents`, `GET /api/pia/settings/credentials` e
`POST /api/pia/settings/credential`. Exportação/importação recebem senha no corpo;
nunca a coloque na URL ou em logs. Não são rotas OpenAI.

Entradas grandes do cofre são divididas internamente entre entradas do mesmo cofre e verificadas por hash, sem fragmentos em texto puro. GET /api/pia/settings/storage mostra a pasta do perfil e avisos da migração.
