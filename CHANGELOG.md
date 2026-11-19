# PIA Changelog

## [0002 - Integração com Modelos Externos Estilo OpenBot] - 2026-11-18

### Added
- Módulo `src/model_session.py` com catálogo unificado dos 7 provedores externos (`codex`, `agy`, `openrouter`, `gemini`, `groq`, `cloudflare`, `local`), status canônicos (`connected`, `login_required`, `not_installed`, `error`) e `ModelSessionTracker` em memória (zerado no boot do `WorkspaceService`).
- Separação estrita entre consumo acumulado da sessão (`session_usage`) e saldo oficial do provedor (`provider_quota`): consulta oficial na OpenRouter (`GET /api/v1/credits` com fallback em `/api/v1/key`), `quota_checked_at` em UTC ISO 8601 com sufixo `Z` (`T3`), e exibição literal de `"Saldo não informado pelo provedor"` nos provedores sem API oficial de saldo ou quando a consulta falhar.
- Evolução de `Plugins/Connectors/agents/service.py` com verificação não-paga de login (`login_status`), disparo do fluxo oficial (`start_login`), extração de `usage` quando disponível e cancelamento imediato via `cancel_event` com `subprocess.Popen` mantendo retrocompatibilidade com `subprocess.run`.
- Endpoints no `WorkspaceService` e `src/pia/http.py`: `GET/POST /api/pia/models/status`, `POST /api/pia/models/connect`, `POST /api/pia/models/disconnect`, `POST /api/pia/models/verify`, `POST /api/pia/models/quota`, `POST /api/pia/models/reset-session`, `POST /api/pia/integrations/agents/reset-session` (`T4`), `POST /api/pia/models/default`, `POST /api/pia/chat/model` e campo `model_selection` em `GET /api/pia/chat/messages`, preservando `/integrations/agents/status` e `/integrations/agents/ask`.
- Roteamento unificado em `src/desktop_backend.py` e `src/HTTPServer.py` (`/v1/chat/completions` e `/v1/models`) com suporte a `codex` e `agy`, registro compartilhado de `session_usage` entre Chat e Podcast Automation e contrato de cancelamento `T5` em `/chat/cancel` (preserva mensagem `user`, grava `assistant` parcial apenas se `job.text` não vazio e emite `done` com `cancelled: true`).
- Módulo JS puro testável `src/pia/frontend/models.js` (`T1`), `src/pia/frontend/ProviderDrawer.jsx`, evolução do painel `src/pia/frontend/AgentsPanel.jsx` (7 cartões, cabeçalho de sessão com `"Zerar contagem da sessão"`, fluxo de login CLI e chaves no Cofre) + `AgentSetup.jsx`, e seletor pesquisável com `HoverCard` de consumo/saldo em `src/pia/frontend/Chat.jsx`.
- Integração no Podcast Automation (`0002-C3`): componente modular `Plugins/Apps/podcast_automation/web/ModelSettingsSlot.jsx` renderizado exclusivamente dentro de `data-slot="podcast-model-settings"` em `Panel.jsx`, validação e merge não-destrutivo de `integrations.llm_provider` e `integrations.llm_model` em `web_api.py` (`T2`), resolução de modelo e sanitização de erros em `llm.py` e `geradorResumoSessao.py`.
- Atualização de `postman/PIA.postman_collection.json` e bundle compilado em `src/pia/assets/*`.

### Security
- Proibida qualquer leitura, cópia ou reaproveitamento de tokens internos do aplicativo OpenBot (`app.asar` ou cofres externos); uso exclusivo das sessões oficiais dos CLIs locais (`--sandbox read-only` no Codex e `--mode plan` no AGY com ambiente sanitizado) e do `SystemVault` da PIA.
- Chaves de API nunca retornam em endpoints HTTP, logs ou estado React e são limpas da interface imediatamente após o envio.
- Validação leve de chaves no Cofre sem execução de geração paga (`UX-04`), sanitização de mensagens de erro e ausência de fallback silencioso quando um provedor explícito selecionado estiver desconectado ou falhar (`RN-0002-08`).

### Tests
- Frontend (`node --test` via `npm --prefix src/pia/frontend test`): suíte pura `models.test.js` (`T1`) somada a `navigation.test.js`, `forms.test.js` e `resources.test.js`.
- Backend e Podcast (`pytest` com mocks/fakes, sem credenciais reais): `tests/test_model_session_and_routing.py` (`T3`–`T5`), `Plugins/Apps/podcast_automation/tests/test_podcast_model_integration.py` (`T2`, `CA-0002-06`, `CA-0002-07`) e `tests/react_desktop_smoke.py`.

## [Não publicado — Suno pela PIA Server] - 2026-11-17

### Changed
- O Suno passou a rodar pela PIA Server: o token e o OAuth do Suno ficam só na pia-server e a PIA local é cliente dela (`Plugins/Apps/music/remote_suno.py`). Saíram o modo local/manual (URL, comando, bearer, `MUSIC_SUNO_MCP_TOKEN`, OAuth/PKCE/DCR no PC) e o cliente MCP direto (RN18). Substitui a entrada "Suno como gerador no app de Música" abaixo.
- Várias contas Suno por conta PIA: conectar (`POST /api/pia/music/suno/connect` + `GET /api/pia/music/suno/connect/<id>`, que devolve `expired` com 200), renomear (`POST .../accounts/<id>/rename`, 1 a 80 caracteres), desconectar e status. Com 2 ou mais contas válidas, a geração exige `suno_account_id` (`suno_account_required`). A conta vai só no generate: `/music/select` não guarda mais conta e o setting `MUSIC_SUNO_ACCOUNT_ID` saiu.
- Jobs criados na PIA Server, um por conta PIA (RN10), com polling até o estado terminal, `connection: lost|ok` e espera de 5 s a 60 s sem rede (RN09), faixas extras ("Suno · extra"), retomada do job deste PC e download pelo proxy do servidor.
- Erros da API local sempre como 400 `{error, code}`: 401 do servidor vira `pia_server_unpaired`, 5xx/rede e respostas fora do contrato viram `pia_server_unreachable`. Tabela completa em `docs/PLATFORM_SERVICES.md`.

### Added
- Histórico de gerações (`GET /api/pia/music/history`, `DELETE /api/pia/music/history/<id>`, `POST .../tracks/<n>/redownload`), mesclando servidor e índice local, com `availability` por faixa e "Baixar novamente" como job (RN16/RN20).
- Registro das gerações Local/Gemini na PIA Server sem o áudio, com fila offline de até 500 itens/30 dias (RN14).
- Aviso e remoção, com confirmação, das credenciais antigas do Suno (`/api/pia/music/suno/legacy-credentials*`, RN17).
- Coleção Postman com as rotas novas e exemplos fictícios; doc da arquitetura em `docs/PLATFORM_SERVICES.md` e roteiros manuais sem gasto em `docs/suno-music-roteiros.md`.

### Removed
- Sobras do Suno local: lote por chamada MCP, download direto de links de áudio do Suno e o mock `tests/fixtures/fake_suno_mcp.py` (os testes usam `tests/fixtures/fake_pia_server_suno.py`).

### Notes
- Riscos conhecidos aceitos: o token legado `MUSIC_SUNO_MCP_*` continua no export e no sync até o usuário remover; a retomada de jobs é lazy (catálogo e status); quando o áudio local some, a `availability` é `redownload` para item do Suno e `null` para item local.
- Decisão de produto: `media.enqueue` continua subindo as músicas como backup; a RN14 vale só para o histórico de gerações.
- Gerar no Suno gasta créditos; testes reais só com o ok explícito do dono da conta.

## [Não publicado — Suno como gerador no app de Música (substituído pela entrada acima)] - 2026-11-17

### Added
- Provedor `suno_mcp` no app de Música: seletor dinâmico (Suno só aparece quando `available=true`), Configurações → Música com selo de conexão (URL, OAuth/bearer, expirado, pendente) e deep link `Apps/music`.
- Geração via servidor MCP (URL ou comando), com até 10 faixas; o backend faz `ceil(N/2)` chamadas (2 clips por chamada) e descarta o excedente.
- Notificação de lote parcial no formato "k de N músicas prontas (geração interrompida)"; o lote para no primeiro clip que falha. Aviso de que cancelar a espera não interrompe a geração já enviada ao Suno (pode consumir créditos).
- Recusa da geração antes de criar o job quando o Suno não está conectado ou a credencial expirou (`suno_not_connected`, `suno_credential_expired`); o HTTP 400 inclui o `code`. Códigos do job: `incomplete_batch`, `download_failed`, `suno_no_credits`, além de auth/unavailable/timeout. Download seguro (sem gravar URL remota). Campo `ready_text` no erro e no progresso; estado final `interrupted` no WorkProgress.
- Mock HTTP local do MCP do Suno (`tests/fixtures/fake_suno_mcp.py`) e testes e2e (`tests/test_music_suno_e2e.py`) para sucesso, 401, 503, timeout, falha parcial, lote incompleto, recusa antes do job, download e créditos, e ausência de vazamento de token (CA05, CA06, CA07, CA10). Sem chamada paga ao Suno.

### Notes
- Salvar `MUSIC_PROVIDER=suno_mcp` sem credencial é permitido (RN04); o app abre em Local até autorizar.
- A duração no Suno é indicativa. Não há fallback automático para Local/Gemini em caso de erro.
- A mensagem de `incomplete_batch` não inclui "k de N"; esse texto fica na notificação, em `completed`/`total` e em `ready_text`.
- Roteiro manual do seletor e das configurações: `docs/suno-music-roteiros.md`.


## [v0.2.1] - 2026-11-15

### Added
- Presets de 18 cores e 12 rostos para bots dinâmicos; autorização Suno MCP com registro automático de cliente e PKCE S256.

### Fixed
- Criação musical direta pelo chat sem depender de LLM, com áudio quando o provedor conclui a geração e erro legível quando falha.
- Cópia de mensagens e erros com fallback para HTTP local e confirmação visual; estado OAuth vinculado à conta/servidor, expiração e uso único.
- Indicadores de credenciais baseados no cofre e proteção contra repetição de geração em respostas ambíguas do Suno.

### Notes
- A autorização Suno requer login/consentimento. O callback público da release pia-server apresenta o código para conclusão manual na PIA; abrir a autorização não significa que a conta já esteja conectada.

## [Correção — Autorização Suno MCP] - 2026-11-15

### Fixed
- OAuth do Suno usa registro automático de cliente quando o Client ID está vazio, endpoints oficiais e PKCE S256. O código é trocado com o verifier e redirect associados ao state, válido por 15 minutos e consumido uma única vez.
- Callback rejeita state ausente, expirado, reutilizado ou pertencente a outra conta/servidor. Access token e refresh token permanecem no cofre.
- Status de conexão consulta credenciais efetivamente presentes: servidor registrado e referência vazia não significam conexão; token manual aparece como “Token configurado”, sem afirmar autenticação validada.
- Frontend mantém conclusão manual da autorização. O callback público configurado depende de uma rota no pia-server; esta alteração local não implementa nem publica essa rota.

### Tests
- Regressões de DCR/PKCE, state, persistência no cofre e status; bundle reconstruído.

## [Correção — Música pelo chat e cópia de erros] - 2026-11-15

### Fixed
- Pedidos diretos de criação musical no chat acionam o serviço de música sem depender de LLM; pedidos que mencionam Suno selecionam explicitamente `suno_mcp`. O retorno inclui o áudio e os metadados da ferramenta quando a geração tem sucesso, ou uma mensagem de falha quando o provedor não atende.
- Falhas de disponibilidade dos modelos no chat recebem uma resposta legível com orientação para conferir a configuração.
- Cópia de mensagens e do balão de erro usa fallback com textarea e `document.execCommand('copy')` quando a API de clipboard falha ou está ausente, com confirmação “Copiado!” após sucesso.
- Timeouts e respostas inválidas do Suno não repetem automaticamente a geração por REST, evitando pedidos duplicados. O fallback REST fica restrito à rejeição explícita do endpoint/protocolo.

### Tests
- Regressões para intenção musical, propagação de áudio, indisponibilidade de LLM, prevenção de repetição e fallbacks de clipboard; bundle do frontend reconstruído.

## [Etapa 2 — Presets de Cores, 12 Rostos Dinâmicos e OAuth Suno MCP] - 2026-11-15

### Added
- **Bots Dinâmicos (`Plugins/OpenBot`)**: grade visual com **18 presets de cores** harmônicos + botão `+` (**Personalizar**) mantendo os seletores manuais ocultos por padrão, além de **12 rostos originais animados** (`orb`, `visor`, `owl`, `spark`, `fox`, `astro`, `neko`, `knight`, `lotus`, `pixel`, `flame`, `sonar`) com validação de `FACE_TYPES` em `Plugins/OpenBot/models.py` e compatibilidade com `sanitize_svg`.
- **Suno MCP OAuth + Cofre Único (`Plugins/Apps/music`, `src/mcp_connectors.py`, `src/pia/service.py`)**: suporte a autenticação OAuth no provedor `suno_mcp` persistida no `UnifiedVault` via `MCPConnectorManager`, troca de `authorization_code` em `token_url` no `complete_oauth`, rotas `/api/pia/music/suno/oauth/{start,callback,disconnect}`, exposição de status OAuth em `/api/pia/music/providers` e resolução automática de token em `call_suno_mcp`.

## [Hotfix de integração — Bots e painéis] - 2026-11-15

### Fixed
- Import de Anchor nas Configurações e recuperação do ErrorBoundary para voltar à navegação após uma falha.
- Registro explícito e normalização de IDs de plugins para abrir os painéis nativos sem iframes duplicados em Música, Podcast Automation, Captura de Tela e Object Storage.
- Rotas `/bots/<id>`, `/bots/<id>/` e `/bots/<id>/index.html` com fallback para o workspace; `/apps/<id>` resolve `index.html` por padrão.
- Despacho de consultas GET dos domínios plugins, skills, apps, bots e music, incluindo detalhes e status de plugins.

### Added
- Chat direto nas telas de Secretária e Bots, com `POST /api/pia/bots/chat` e suporte a `bot_id`/`agent_id` e `system_prompt` no envio de chat.
- Testes de integração de rotas de bots/plugins e helpers do chat direto; bundle do workspace reconstruído no hotfix.

## [Nova Arquitetura Modular — Fases 0 a 8] - 2026-11-15

### Added
- CI para lint, testes Python/frontend e build; lockfiles de dependências e inicialização com build do workspace quando necessário.
- Router declarativo por tabela com módulos de rotas por domínio e compatibilidade com o despacho legado.
- UnifiedVault como fachada de credenciais e PluginHost/PluginContext para descoberta e injeção de serviços nas extensões.
- Ferramentas de música, podcast/RPG, screenshots e object storage extraídas para seus plugins, declaradas nos manifestos.
- Pacotes por domínio em `app`, `core`, `api`, `ai`, `voice`, `integrations` e `desktop`, com adaptadores para preservar imports existentes durante a migração incremental.
- Frontend organizado em `features`, cliente de API compartilhado e registry dinâmico de painéis via `import.meta.glob`.
- Contrato `X-PIA-Protocol: 1` documentado para integração com pia-server e enviado pelo conector local.
- UX de Conectores MCP: presets de configuração, explicações dos modos multi-conta e inspeção de ferramentas com descrição/schema e re-inspeção.

### Changed
- Bundle do workspace reconstruído; source map `workspace.js.map` removido do versionamento e ignorado pelo Git.
- Testes de fronteiras arquiteturais, registry de plugins e presets MCP. A estrutura modular mantém partes legadas por compatibilidade; não representa remoção integral do legado.

## [TTS Unificado, Voz por Bot e Bots Dinâmicos (OpenBot)] - 2026-11-14

### Added
- Telas dedicadas de **Conectores MCP Personalizados**, **Plugins** e **Skills** nas Configurações (`McpConnectorsPanel.jsx`, `PluginsPanel.jsx`, `SkillsPanel.jsx`, `extensions-helpers.js`, `Connectors.jsx`, `Settings.jsx`, `Workspace.jsx`, `workspace.css`): modal no formato *"Conectar a um MCP personalizado"* (`STDIO` / `HTTP com streaming`, URL, variável de token do portador, pares dinâmicos de cabeçalhos e cabeçalhos via ambiente), autenticação OAuth (`/oauth/start`), gerenciamento multi-contas (`Distribuído`, `Incremental`, `Alternado` por contexto), inspeção/visualização de ferramentas MCP (`/tools`, `/inspect`), catálogo de plugins com ativação/desativação (`/api/pia/plugins`) e catálogo/CRUD/execução de skills nativas e personalizadas (`/api/pia/skills`).
- Backend de Conectores MCP Personalizados (`src/mcp_connectors.py`, `/api/pia/mcp/servers`) com transporte `stdio` e `http_streaming`, headers/variáveis de ambiente, autenticação OAuth (`/oauth/start`, `/oauth/callback` com segredos no cofre), roteamento multi-contas nos modos `distributed` (round-robin com fallback), `incremental` (agregação de todas as contas) e `alternating` (por contexto ativo), descoberta de ferramentas (`GET /api/pia/mcp/servers/<id>/tools` e `/inspect`) e integração ao chat/tool_registry.
- APIs de catálogo e gerenciamento para Plugins (`/api/pia/plugins`, `POST /api/pia/plugins/<id>/toggle` em `src/plugins_catalog.py`) e Skills (`/api/pia/skills`, CRUD, `/toggle`, `/execute` e tool `pia_run_skill` em `src/skills_catalog.py`, incluindo `"Iniciar Bloco de Notas"`).
- Botões de sugestões rápidas nas respostas da assistente (`extractMessageSuggestions` em `chat-helpers.js` e `Chat.jsx`, com suporte híbrido a `meta.suggestions`, marcadores e listas finais em Markdown) enviando o texto selecionado imediatamente como mensagem do usuário sem apagar o rascunho em digitação.
- Área útil do Chat ampliada e fluida em `workspace.css` (`.chat-topbar`, `.messages`, `.composer-wrap`, `.message` e `.message-body`), removendo o teto estreito de `800px` para aproveitar melhor monitores maiores e ultrawide.
- Interface do Chat aprimorada (`src/pia/frontend/Chat.jsx`, `chat-helpers.js`, `workspace.css`) com seletor de modelo no topo da conversa (`GET /api/pia/chat/models` e envio do campo `model` em `POST /api/pia/chat/send`), popover `"i"` nas respostas da assistente exibindo modelo/provedor e ferramentas/MCPs usados, alternância Som ↔ Stop no botão de fala com pausa/reset imediato de `<audio>` e cancelamento remoto (`/api/pia/tts/jobs/<id>/cancel` e `POST /api/pia/tts/stop`), e pré-visualização inline/zoom de capturas de tela, players `<MediaTrack>` e cartões de download/transcrição para resultados de MCP (buckets/RPG e Suno).
- Seletor de modelo por mensagem no chat (`GET /api/pia/chat/models` e `model` opcional em `POST /api/pia/chat/send`), persistência de metadados (`model`, `provider`, `tools_used`, `attachments`) em `WorkspaceStore` (`messages.meta`) e emissão no evento SSE `done`.
- Novas ferramentas nativas no chat e MCP (`src/mcp_chat_tools.py`, `src/tool_registry.py`): `pia_screenshot` (captura de tela em `/api/pia/chat/assets/*`), `pia_storage_list`/`pia_storage_get` (buckets S3-compatíveis com bloqueio de credenciais sensíveis), `pia_rpg_sessions` (busca fuzzy de campanhas e sessões de RPG com resumo/transcrição) e `pia_music` multi-turno integrado ao Suno MCP (`call_suno_mcp` via HTTP JSON-RPC/REST e stdio).
- Rota `POST /api/pia/tts/stop` no WorkspaceService para interromper imediatamente a fala e áudios em reprodução via `TTSManager().stop()`.
- Supertonic 3 atualizado para o pipeline ONNX multilíngue (`Supertone/supertonic-2`, 31 idiomas incluindo português `<pt>...</pt>` com acentuação NFKD preservada) e catálogo completo com 10 vozes (`F1..F5` `Voz feminina 1..5` e `M1..M5` `Voz masculina 1..5`).
- Suporte a texto customizado no preview de TTS (`POST /api/pia/tts/preview`) com fallback automático para a frase padrão da PIA.
- Configuração estruturada de Música (`GET /api/pia/music/providers` e `POST /api/pia/music/select`) com 3 provedores (`local`, `gemini`, `suno_mcp`) e integração com `Apps/music`.
- UI das 7 abas de Configurações (`Geral`, `STT`, `TTS`, `Música`, `Imagens · ICE`, `LLMs`, `Voz e áudio`) reformulada em padrão limpo de cards: removidos parâmetros técnicos redundantes preservando defaults do backend, campo editável de texto de teste no preview TTS (até 300 caracteres), catálogo completo de 10 vozes no Supertonic 3, slider único de velocidade, toggle para sons de gravação (`START_SOUND`/`END_SOUND`), links para o Cofre e painel simplificado de Música com Local (ACE-Step), Gemini e Suno MCP.
- Serviço central `TTSService` (`src/tts_service.py`) unificando catálogo, seleção, instalação/desinstalação por modelo local (`kokoro`, `qwen`, `supertonic3`, `piper`), preview com TTL e síntese em `/v1/tts/*`, `/api/pia/tts/*`, `/v1/audio/speech` e `/tts/speak`.
- Voz própria por speaker/bot (`GET/PUT /api/pia/speakers/{speaker_id}/voice`), propagação de `speaker_id` em `NotificationCenter.publish` e contexto de reprodução (`utterance_id`, `speaker_id`, `avatar_url`, `phase`) em `/tts/status` e `/tts/status/stream`.
- Avatar da Secretária (`Plugins/Bot/secretaria/avatar.svg`) atualizado com classes `.enable-mouth` e `.animation-talking`.
- Extensão `Plugins/OpenBot` para Bots Dinâmicos: CRUD (`/api/pia/openbot/bots`), upload e sanitização estrita de avatares SVG (`/api/pia/openbot/avatars`), execução e cancelamento (`/api/pia/openbot/bots/{id}/runs`, `/api/pia/openbot/runs/{id}/cancel`) e ferramenta `delegate_to_bot` com limites de profundidade, ciclos e timeout.
- Painel visual unificado de TTS (`TTSSettingsPanel.jsx` e `VoiceSelector.jsx`) substituindo os campos textuais brutos em `Configurações -> Geral -> TTS`, com instalação/remoção individual de modelos locais, progresso ao vivo, validação de conflitos (`409`) e controle reutilizável `SpeakerVoicePanel`.
- Seleção de voz própria ou herdada para a Secretária (`Plugins/Bot/secretaria/web/Panel.jsx`) e troca dinâmica de avatar SVG + animação de fala no `PIA Mini` (`src/piamini/mini.js`, `index.html`, `mini.css`).
- Interface completa de Bots Dinâmicos (`Plugins/OpenBot/web/*`, `Bots.jsx` e `Workspace.jsx`): catálogo separado (Nativos vs Dinâmicos), criação/edição com editor `AGENTS.md`, presets/upload de SVG com 3 cores personalizáveis, voz dedicada e execução em streaming via SSE.

### Changed
- Removidos inputs textuais brutos `TTS_*` da sub-aba `TTS` em `Settings.jsx`, preservando parâmetros avançados (`TTS_DEVICE`, timeouts, `TTS_LLM_MODEL`) em seção dobrável dedicada.

### Fixed
- Corrigido `TypeError: Cannot read properties of undefined (reading 'length')` ao abrir a aba `TTS` (`TTSSettingsPanel.jsx` agora desestrutura `{ providers, refresh }` corretamente de `useTtsCatalog()`, corrige a ordem de argumentos de `resolveDraftForModel` e aplica guardas defensivas `safeArray` em `TTSSettingsPanel.jsx`, `VoiceSelector.jsx`, `Settings.jsx`, `GeneralSettingsTabs.jsx`, `MusicSettingsPanel.jsx`, `tts-helpers.js` e `settings-simplification.js`).

### Security
- Sanitização XML estrita de SVG rejeitando `<script>`, `foreignObject`, DTD/entidades, atributos `on*` e referências externas.
- Bloqueio de desinstalação de modelos TTS em uso (`409 model_in_use`) e conflitos de revisão (`409 revision_conflict`).

## [Lint e formatação] - 2026-11-14

### Added
- Ruff básico e formatação Python em todos os arquivos próprios versionados; ESLint recomendado e Prettier no frontend.
- Hook pre-commit versionado, instalado por install.sh, verifica todo o código e bloqueia código fora do padrão ou alterações de código não adicionadas ao índice.
- scripts/lint.py --fix aplica a formatação. Corrigidos import ausente de binascii e referência à máquina de estados no endpoint blink encontrados pelo lint.

## [Windows/WSL] - 2026-11-14

### Fixed
- Instalador e inicializador encaminham execuções WSL em drives Windows para o Git Bash nativo, preservando argumentos e evitando dependências e ambientes virtuais Linux nesse fluxo.
- Sem Git Bash disponível, interrompem com orientação antes de instalar dependências. WSL em diretórios Linux mantém o comportamento Linux.
- `bash start.sh --dry-run` mostra a plataforma e o comando Python selecionados sem abrir a aplicação.

## [Voice Selector] - 2026-11-14

### Added
- Seletor de voz na PIA
- Abstracao TTSProvider com suporte a multiplos providers
- TTSProviderRegistry que descobre providers disponiveis com base em chaves de API no cofre
- Supertonic3Provider (TTS local)
- OpenAITTSProvider (TTS remoto via OpenAI)
- ElevenLabsProvider (TTS remoto via ElevenLabs)
- Endpoint GET /v1/tts/providers
- Endpoint POST /v1/tts/select
- Componente VoiceSelector (Mantine Select) agrupado por local/remoto
- Integracao do VoiceSelector em Settings.jsx
- Persistencia de selecao via settings_store/SQLite

### Security
- Chaves de API armazenadas apenas no cofre (keyring)
- Auth Bearer nos endpoints
- Validacao de voice ID contra list_voices
- Validacao de provider e speed

### Tests
- 4 testes de contrato e smoke (pytest) - todos passando
- 6 testes frontend - todos passando
