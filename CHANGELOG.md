# PIA Changelog

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
