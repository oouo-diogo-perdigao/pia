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
