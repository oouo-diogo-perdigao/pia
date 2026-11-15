# PIA Changelog

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
