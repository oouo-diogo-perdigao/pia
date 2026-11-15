# PIA Changelog

## [TTS Unificado, Voz por Bot e Bots Dinâmicos (OpenBot)] - 2026-11-14

### Added
- Supertonic 3 atualizado para o pipeline ONNX multilíngue (`Supertone/supertonic-2`, 31 idiomas incluindo português `<pt>...</pt>` com acentuação NFKD preservada) e catálogo completo com 10 vozes (`F1..F5` `Voz feminina 1..5` e `M1..M5` `Voz masculina 1..5`).
- Suporte a texto customizado no preview de TTS (`POST /api/pia/tts/preview`) com fallback automático para a frase padrão da PIA.
- Serviço central `TTSService` (`src/tts_service.py`) unificando catálogo, seleção, instalação/desinstalação por modelo local (`kokoro`, `qwen`, `supertonic3`, `piper`), preview com TTL e síntese em `/v1/tts/*`, `/api/pia/tts/*`, `/v1/audio/speech` e `/tts/speak`.
- Voz própria por speaker/bot (`GET/PUT /api/pia/speakers/{speaker_id}/voice`), propagação de `speaker_id` em `NotificationCenter.publish` e contexto de reprodução (`utterance_id`, `speaker_id`, `avatar_url`, `phase`) em `/tts/status` e `/tts/status/stream`.
- Avatar da Secretária (`Plugins/Bot/secretaria/avatar.svg`) atualizado com classes `.enable-mouth` e `.animation-talking`.
- Extensão `Plugins/OpenBot` para Bots Dinâmicos: CRUD (`/api/pia/openbot/bots`), upload e sanitização estrita de avatares SVG (`/api/pia/openbot/avatars`), execução e cancelamento (`/api/pia/openbot/bots/{id}/runs`, `/api/pia/openbot/runs/{id}/cancel`) e ferramenta `delegate_to_bot` com limites de profundidade, ciclos e timeout.
- Painel visual unificado de TTS (`TTSSettingsPanel.jsx` e `VoiceSelector.jsx`) substituindo os campos textuais brutos em `Configurações -> Geral -> TTS`, com instalação/remoção individual de modelos locais, progresso ao vivo, validação de conflitos (`409`) e controle reutilizável `SpeakerVoicePanel`.
- Seleção de voz própria ou herdada para a Secretária (`Plugins/Bot/secretaria/web/Panel.jsx`) e troca dinâmica de avatar SVG + animação de fala no `PIA Mini` (`src/piamini/mini.js`, `index.html`, `mini.css`).
- Interface completa de Bots Dinâmicos (`Plugins/OpenBot/web/*`, `Bots.jsx` e `Workspace.jsx`): catálogo separado (Nativos vs Dinâmicos), criação/edição com editor `AGENTS.md`, presets/upload de SVG com 3 cores personalizáveis, voz dedicada e execução em streaming via SSE.

### Changed
- Removidos inputs textuais brutos `TTS_*` da sub-aba `TTS` em `Settings.jsx`, preservando parâmetros avançados (`TTS_DEVICE`, timeouts, `TTS_LLM_MODEL`) em seção dobrável dedicada.

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
