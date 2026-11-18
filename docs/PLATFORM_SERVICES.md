# Serviços compartilhados: notificações, mídia e logs

## Bandeja e configurações

Fechar a janela oculta o workspace. **Encerrar PIA** sai do event loop e executa cleanup numa única ação, mesmo com janela aberta. **Reiniciar PIA** inicia o launcher aguardando a instância anterior encerrar; usa o mesmo caminho de reinício das configurações.

Conectores ficam em Configurações → Conectores, em uma árvore de pastas expansível. Links/histórico antigos com view=connectors são normalizados para essa navegação. Variáveis gerais são agrupadas por Geral, STT, TTS, Imagens/ICE, LLMs e Voz/áudio, mantendo o nome real e o valor na mesma linha. Trocar a aba de variáveis não descarta alterações do formulário.

## Notificações

`src/notifications.py` mantém histórico no WorkspaceStore (até 1000 entradas), leitura, contadores e preferências globais. Apps e bots usam origens `Apps/<id>` ou `Bot/<id>`. O botão direito no ícone de cada app ou no item/card de cada bot abre o menu de silenciamento. O botão direito no sino ativa/desativa a leitura automática. Essas preferências não ficam mais na tela da central. Silenciar bloqueia toast/voz, mas preserva histórico e indicadores de não lidas. Cada bot tem contador próprio; o ícone geral de Bots mostra a soma. Abrir o app/bot em uma página visível e em foco marca os avisos daquela origem como vistos.

Em Python, um app carregado recebe o contexto do workspace:

```python
context.publish_notification('Apps/music', 'Músicas prontas', 'O lote terminou.')
```

Em uma página de app que usa o SDK:

```javascript
import {session, publishNotification} from '/pia/sdk.js';
await session();
await publishNotification('meu_app', 'Concluído', 'O processamento terminou.', [
  {label: 'Abrir resultado', url: 'https://exemplo.com/resultado'}
]);
```

O app deve estar registrado. A rota local autenticada é `POST /api/pia/notifications/publish`, com source/title/text/links. Links aceitam HTTPS; não coloque segredos ou URLs assinadas sensíveis no histórico. Não notifique a cada polling: publique apenas mudanças ou conclusões úteis.

A secretária publica avisos pelo serviço central com links de e-mail, compromisso e Meet quando disponíveis. A antiga preferência speak é migrada uma vez para leitura global, sem sobrescrever preferências já salvas. Preferências de voz não ficam mais na tela da secretária.

Conversas também têm contadores de respostas não visualizadas, tanto na lista quanto no ícone geral. A marca de leitura é persistida por chat e só avança para mensagens de assistente que aparecem na área visível de uma conversa aberta e em foco. Abas ocultas, respostas em outros chats e ramificações inativas não são marcadas automaticamente como lidas. A primeira migração considera o histórico antigo já lido.

## Reprodução compartilhada

`/pia/media.js` fornece um player por janela, mantido durante navegação entre apps. O workspace apresenta controles globais, posição e duração. Chat e app Música usam o mesmo recurso, sem players independentes.

```javascript
import {playMedia, pauseMedia} from '/pia/sdk.js';
await playMedia('/api/pia/music/files/ARQUIVO.mp3', 'Minha música');
await pauseMedia();
```

O recurso precisa ser uma URL autenticada da PIA na mesma origem. A reprodução depende de uma ação do usuário conforme as regras do navegador. O SDK também permite importar `subscribeMedia`, `seekMedia` e `stopMedia` diretamente de `/pia/media.js`. Ao criar uma UI própria, libere subscriptions no unmount.

O frontend informa o estado ao núcleo com identificador de janela e heartbeat. Enquanto houver reprodução ativa, a Mini mostra três notas animadas. Pausa, término e erro encerram a animação; leases e watchdog evitam estado preso após fechar/crashar a página. A rota de áudio oferece byte ranges para buscar posições sem recarregar o arquivo inteiro.

## Logs

Inspeção e logs organiza Main, Apps, Bot, Connectors, Skills e Browser, com painéis recolhíveis e busca no conteúdo carregado; pastas e arquivos começam expandidos. Ao abrir a tela, cada arquivo carrega somente as últimas 100 linhas. Arquivos expandidos recebem incrementos por cursor; essas novas linhas não são limitadas a 100 durante a sessão do visualizador. Busca não varre conteúdo histórico que ainda não foi carregado.

Abrir log usa o programa padrão na sessão nativa ou uma página de texto autenticada no navegador, permitindo consultar o arquivo completo. Limpar um arquivo altera apenas seu painel. O leitor detecta rotação/truncamento e não permite caminhos fora de logs/. Cada resposta incremental é limitada em bytes; o cursor permite continuar sem descartar linhas.

## Capturas

O fluxo anterior foi restaurado: cada captura abre uma janela nova com seu identificador, carregando PNG/base64 pelo adaptador nativo. Foram removidos pré-carregamento, reutilização do editor, metadados paralelos e a rota binária experimental. O app continua solicitando /action/screen-all e a Mini permanece visível; não há espera para ocultá-la. O tempo real depende da captura do sistema e dos monitores.

## Música

O app cria de 1 a 10 faixas por pedido, agrupadas em um card. Progresso percentual corresponde às faixas concluídas, não a uma estimativa inventada da inferência individual. Resultados parciais sobrevivem a falhas/cancelamento. Ao concluir na tela Principal, o app rola até o card.

Destino fixo: `Documentos/pia/music`, dentro do perfil do usuário. As configurações e credenciais são gerenciadas pela interface e armazenadas no SQLite/cofre; consulte [perfil e migração](PROFILE_MIGRATION.md).

O app oferece os geradores Local (ACE-Step), Gemini/Lyria e **Suno**. O Suno roda pela PIA Server (abaixo). Roteiro manual: [suno-music-roteiros.md](suno-music-roteiros.md); detalhes do app: [README do app de Música](../Plugins/Apps/music/README.md).

### Suno pela PIA Server

**Arquitetura.** O token e o OAuth do Suno existem **só na pia-server**. A PIA local é cliente dela: conversa com `/device/*` usando o token do dispositivo (pareamento em Configurações → PIA Server, cabeçalho `X-PIA-Protocol: 1`) e nunca fala com o Suno. Nenhum token, link de áudio ou prompt vai para log. O código está em `Plugins/Apps/music/remote_suno.py` (status, contas, connect, jobs e download), `history.py` (histórico e fila RN14), `suno_legacy.py` (credenciais antigas) e `web_api.py` (rotas e jobs). O cliente HTTP do dispositivo é `Plugins/Connectors/pia_server/remote.py`.

- O servidor precisa anunciar a capability `suno:3` em `GET /device/account`; sem ela o motivo é `pia_server_unsupported`.
- Status em `GET /device/suno/status`, com cache curto de 15 s no catálogo. Conectar: `POST /device/suno/connect` e `GET /device/suno/connect/:id`. Apelido: `PATCH /device/suno/accounts/:id`. Desconectar: `DELETE /device/suno/accounts/:id`.
- Geração: `POST /device/suno/jobs`, acompanhamento com `GET /device/suno/jobs/:id` e cancelamento com `POST /device/suno/jobs/:id/cancel`. Um job ativo por conta PIA (RN10).
- O áudio é baixado pelo proxy `GET /device/music/generations/:id/tracks/:n/audio` (limite de 100 MiB, `.part` + troca atômica, `X-Content-SHA256` conferido quando vier). O link do Suno nunca chega ao PC.
- Polling até o estado terminal (`completed`, `failed`, `interrupted`, `cancelled`). Sem conexão, `progress.connection` vira `lost` e a espera cresce de 5 s até 60 s, sem prazo (RN09). As faixas extras são salvas com o rótulo "Suno · extra" e o `ready_text` é calculado localmente (ex.: "3 de 3 músicas prontas (+1 extra)"). Cancelar entrega as faixas já prontas.
- Um único item `suno_mcp` no catálogo. Com exatamente uma conta válida, ela é usada sem escolha. Com duas ou mais, `selected_account_id` vem `null` e a geração exige `suno_account_id` (senão `suno_account_required`). A conta vai só no generate; `/music/select` não guarda conta.

**Rotas locais** (todas sob `/api/pia`, sessão local; exemplos na coleção Postman, pasta "07 · Workspace e serviços"):

| Rota | Corpo | Resposta |
| --- | --- | --- |
| `GET /music/providers` | — | catálogo; o item `suno_mcp` traz `available`, `reason`, `hint {text, route}`, `connected`, `credential_state` (`configured`/`expired`/`missing`), `expires_at`, `settings`, `accounts[]`, `selected_account_id`, `active_job`, `legacy_credentials {present, prompt}` |
| `POST /music/select` | `{provider?, gemini_model?}` | catálogo. Um `suno_account_id` vindo de um body antigo é ignorado (nada é salvo), como as outras chaves desconhecidas |
| `GET /music/suno/status` | — | o item `suno_mcp`, lido agora da PIA Server |
| `POST /music/suno/connect` | `{replace_account_id?}` | `{auth_url, attempt_id, expires_in}` |
| `GET /music/suno/connect/<id>` | — | `{state: pending\|connected\|failed\|expired, account_id?, code?}`; tentativa inexistente: 400 `suno_connect_not_found` |
| `POST /music/suno/accounts/<id>/rename` | `{label}` (1 a 80 caracteres, sem controle) | `{ok, provider}`; fora do limite: 400 `invalid_label` |
| `POST /music/suno/disconnect` | `{account_id}` | `{ok, provider}` |
| `POST /apps/music/generate` | `{prompt, lyrics?, provider, duration, count, suno_account_id?, instrumental?}` | `{job}`; o progresso segue no SSE `/api/pia/events/<job>` |
| `GET /music/history?cursor=&limit=100` | — | `{items, next_cursor, server_unavailable, server_reason}` |
| `DELETE /music/history/<id>` | — | `{ok, id}` |
| `POST /music/history/<id>/tracks/<n>/redownload` | — | `{job_id}` |
| `GET /music/suno/legacy-credentials` | — | `{present, prompt, items:[{kind, label}]}` (só rótulos) |
| `POST /music/suno/legacy-credentials/remove` | `{confirm: true}` | `{ok, removed, present, prompt}`; sem `confirm`: 400 `confirmation_required` |
| `POST /music/suno/legacy-credentials/dismiss` | `{}` | `{ok, present, prompt: false, items}` |

`accounts[]` traz `{id, label, email, name, credential_state, available, expires_at, reason, hint}`. O `credential_state` da conta é o do servidor (`configured`, `unavailable` ou `refresh_failed`); fora de `configured`, a conta tem `reason = suno_credential_expired`. O `label` local nunca vem vazio: usa o apelido, depois o nome, o e-mail e por fim o id (até 80 caracteres). `email` e `name` podem ser `null`. `active_job` fica no nível do item: `{job_id, state, this_device, suno_account_id, completed, total, extra_ready}`, e `job_id` é o id local aceito pelo `watchJob`, só no PC de origem.

**Erros e mapeamento.** A API local responde todo erro como **HTTP 400 `{error, code}`** (o `http.py` aceita `code` em `[a-z0-9_]{1,64}`); o status do servidor não é repassado.

| Resposta da PIA Server | `code` local |
| --- | --- |
| 401 (com ou sem `code`), token do dispositivo ausente ou URL inválida | `pia_server_unpaired` |
| 5xx, falha de rede, timeout ou 2xx que não é JSON | `pia_server_unreachable` |
| Sem a capability `suno:3` | `pia_server_unsupported` |
| 4xx com `code` válido | o mesmo `code` (ex.: `suno_job_active` do 409, `suno_track_unavailable` do 410, `suno_account_taken`, `suno_account_mismatch`) |
| 4xx sem `code` válido ou resposta fora do formato | `pia_server_unreachable` (o fallback interno `pia_server_error` do cliente nunca sai da API local) |
| 404 ou `code` `not_found` em `GET /device/suno/connect/:id` | `suno_connect_not_found` |

Codes do contrato: `pia_server_unpaired`, `pia_server_unreachable`, `pia_server_unsupported`, `suno_not_connected`, `suno_credential_expired`, `suno_account_required`, `suno_account_taken`, `suno_account_not_found`, `suno_account_mismatch`, `suno_identity_unavailable`, `suno_oauth_denied`, `suno_oauth_invalid`, `suno_connect_not_found`, `suno_job_active`, `suno_track_unavailable`, `confirmation_required`, `not_origin_device` e `invalid_label`. Id de conta inválido enviado pelo cliente (`account_id` do disconnect, `replace_account_id` do connect) responde `suno_account_not_found`. Durante o job, o evento `error` usa também `cancelled`, `incomplete_batch`, `download_failed`, `suno_no_credits`, `suno_unavailable`, `suno_timeout` e `interrupted`.

Codes locais sem equivalente no contrato do servidor (todos HTTP 400):

| `code` | Mensagem | Quando |
| --- | --- | --- |
| `history_item_not_found` | "Item do histórico não encontrado." | `DELETE` ou redownload de um id que não está no índice local nem na PIA Server |
| `track_not_found` | "Faixa não encontrada." | redownload de um `n` que o item não tem |
| `local_audio_missing` | "O áudio desta geração local não está mais neste computador." | redownload de uma faixa **local** (Local/Gemini) deste PC cujo arquivo sumiu: o áudio local nunca sobe, então não há de onde baixar |

**Histórico (RN20).** `GET /music/history` mescla as gerações da PIA Server com o índice local `pia-generations-index.json` (na pasta de música), com os jobs ativos primeiro e depois do mais novo para o mais antigo. Cada item traz `id` (o `client_id`), `job_id`, `provider`, `source` (`suno`/`local`), `suno_account {id, name}`, `prompt`, `lyrics`, `params`, `created_at`, `state`, `code`, `count`, `this_device` e `tracks[]`. Cada faixa traz `{n, title, duration, extra, label, file, availability}`:

- `local_file`: o arquivo está neste PC e `file` traz o item da biblioteca (mesmo formato de `/apps/music/library`);
- `redownload`: faixa Suno sem arquivo neste PC, em qualquer PC da conta;
- `other_device_local`: áudio local gerado em outro PC;
- `null`: áudio local deste PC que sumiu (sem ação).

Offline ou sem pareamento, a rota devolve só os itens locais, com `server_unavailable: true` e `server_reason` (`pia_server_unpaired` ou `pia_server_unreachable`). O `DELETE` é definitivo na PIA Server, mas **nunca apaga o arquivo local**: grava uma marca (tombstone) para o item não voltar pela varredura da pasta. O redownload vira job (`{job_id}`); um segundo pedido da mesma faixa ainda baixando devolve o mesmo `job_id`, e o evento `track` traz `{item, track, history_id}`.

**Fila de registros locais (RN14).** Cada geração Local/Gemini é registrada em `POST /device/music/generations` com `source: "local"` e um `client_id` uuid (prompt, letra, quantidade, duração, estado). Sem pareamento, nada é enviado nem guardado. Pareado e offline, o registro entra na fila `pia_music_generation_queue` do SQLite, com no máximo 500 itens e 30 dias, e é reenviado do mais antigo para o mais novo na próxima geração ou listagem do histórico. Uma recusa que não é falta de conexão descarta o registro. O registro não leva o áudio.

**Credenciais antigas (RN17).** As entradas `mcp:connector:suno_mcp:*` do cofre, as settings `MUSIC_SUNO_MCP_*`/`MUSIC_SUNO_TIMEOUT` e o servidor MCP local `suno_mcp` não são mais lidos. A PIA só lê os nomes para mostrar o aviso e apaga somente com `{confirm: true}`; "Agora não" (`dismiss`) não apaga nada.

**Riscos conhecidos aceitos pelo TechLead:**

- O token legado `MUSIC_SUNO_MCP_*` continua no export e no sync de perfil até o usuário remover pela tela de credenciais antigas.
- A retomada dos jobs é lazy: acontece nas chamadas de catálogo (`/music/providers`) e status (`/music/suno/status`), que a interface faz ao abrir. Sem essas chamadas, um job deste PC não é retomado em segundo plano.
- **Fila de mídia e RN14 (decidido pelo Diogo):** o `media.enqueue` do conector PIA Server continua subindo o áudio gerado (Local/Gemini e as faixas Suno salvas) como backup. A RN14 ("o áudio local nunca sai do computador") vale só para o histórico de gerações, que envia apenas metadados.
- Quando o áudio local deste PC some, a `availability` é `redownload` para item do Suno e `null` para item local.

A PIA solicita o encerramento do processo ACE-Step iniciado por ela após cada geração, inclusive em erro/cancelamento. No Windows, o interpretador pode criar processos filhos que sobrevivem ao processo principal; o encerramento de toda a árvore e a liberação completa de VRAM ainda precisam de correção e validação com hardware. A próxima geração pode recarregar o motor. A PIA não encerra um servidor ACE-Step externo que já estava rodando; para ele, liberação de recursos depende de sua configuração. Não foi executado download de modelos ou geração paga para validar essas mudanças.

## Agentes externos

O ícone de ajuda do painel abre um popup específico para Codex ou AGY, com seleção Windows/PowerShell ou Linux/Bash. Ele contém documentação oficial, comando de instalação, login, verificação de versão e comandos para obter o caminho que deve ser preenchido em AGENTS_CODEX_EXECUTABLE ou AGENTS_AGY_EXECUTABLE. Os comandos são exemplos para copiar, não são executados pela interface. MCP e AG-UI permanecem; ACP legado e o perfil A2A síncrono foram removidos.

Configuração e dados usam o [perfil SQLite/cofre](PROFILE_MIGRATION.md).
