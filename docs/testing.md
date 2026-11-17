# Testes e evidências

Execute testes proporcionais à mudança e complete verificações exigidas pelos contratos afetados. Não crie testes que apenas reproduzem a implementação; priorize comportamento, falhas e fronteiras entre componentes.

## Python

PowerShell, na raiz:

```powershell
$env:PYTHONPATH='.;Plugins/Apps/podcast_automation/src'
.venv/Scripts/python.exe -m pytest tests Plugins/Apps/podcast_automation/tests -q
```

Linux/Git Bash com Python Linux:

```sh
PYTHONPATH=.:Plugins/Apps/podcast_automation/src .venv/bin/python -m pytest tests Plugins/Apps/podcast_automation/tests -q
```

No Git Bash com Python Windows, use o executável Windows e separador `;` no PYTHONPATH. Não rode pytest indiscriminadamente pela raiz: `cache/` pode conter cópias importadas de suites e causar colisões de módulos. Instale dependências de teste pelo grupo dev quando necessário.

## Frontend

```sh
npm --prefix src/pia/frontend test
npm --prefix src/pia/frontend run build
```

Confira formulários sem alterações, navegação sem reexecutar ações, estados de loading/erro/sucesso e desmontagem de watchers/tooltips. Assets gerados fazem parte da alteração quando a origem muda.

## Smoke tests desktop

Com dependências Qt/Chromium instaladas, no Windows:

```powershell
.venv/Scripts/python.exe tests/react_desktop_smoke.py
.venv/Scripts/python.exe tests/desktop_smoke.py
```

No Linux, substitua o executável por `.venv/bin/python`; disponibilidade depende das bibliotecas gráficas. Esses scripts usam fixtures/simulações. Não confunda sucesso em offscreen com validação física de câmera, áudio, bandeja e múltiplos monitores.

## Música / Suno

Os testes do Suno usam o mock HTTP local `tests/fixtures/fake_suno_mcp.py` (fixture `fake_suno_mcp` no `conftest`). Não faça geração real nem chamada paga ao `api.suno.com` na suíte comum. O e2e `tests/test_music_suno_e2e.py` percorre `web_api.handle("generate", …)` com um `context` fake e cobre sucesso, 401, 503, timeout, falha parcial (parada no primeiro clip), lote incompleto, recusa antes do job (com `code` no JSON 400), `download_failed`, `suno_no_credits` e vazamento de token. O smoke manual do seletor (CA11) e das Configurações está em `docs/suno-music-roteiros.md`.

## Áreas críticas

- Transcrição: json/text/verbose_json/srt/vtt, duração e timestamps reais, silêncio, fallback, repetição, emendas/pausas e arquivos longos; sem downloads de modelos na suite comum.
- Jobs: sair/voltar à tela, erro de provedor, cancelamento, conclusão e progresso sem duplicação de ações.
- Configuração: tipos, vazio, chaves legadas, segredo, arquivo, dirty state e reinício seguro.
- Conectores/ferramentas: autenticação, schema, conta explícita, escopos e erros. Não publique em canais/buckets reais durante testes comuns.
- Voz: epoch/cancelamento de respostas e áudio antigo, distinção entre ditado/conversação; hardware e eco precisam de teste manual separado.

Ao concluir, informe comandos/resultados reais e limites. Não reutilize a contagem de testes de uma tarefa anterior como evidência nova. Não execute ações pagas, captura real, alteração de contas ou desligamento para testar documentação.
