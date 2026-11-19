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

Os testes do Suno usam o fake local da pia-server `tests/fixtures/fake_pia_server_suno.py` (helpers e fixture `remote` em `tests/_suno_remote_support.py`), só em loopback. Não faça geração real nem chamada ao Suno ou a uma pia-server real na suíte comum. Os e2e (`tests/test_music_suno_e2e.py`) percorrem `web_api` com um `context` fake e cobrem status e contas, connect, geração (sucesso, extra, parcial, cancelamento, offline e volta, 409, 410), retomada e varredura de segredos; o histórico, a fila RN14 e o redownload estão em `tests/test_music_history_t6.py`, a migração das credenciais antigas em `tests/test_music_suno_t8_legacy.py` e os ajustes de contrato da T9 em `tests/test_music_t9_contract.py`. Roteiros manuais: `docs/suno-music-roteiros.md`.

## Áreas críticas

- Transcrição: json/text/verbose_json/srt/vtt, duração e timestamps reais, silêncio, fallback, repetição, emendas/pausas e arquivos longos; sem downloads de modelos na suite comum.
- Jobs: sair/voltar à tela, erro de provedor, cancelamento, conclusão e progresso sem duplicação de ações.
- Configuração: tipos, vazio, chaves legadas, segredo, arquivo, dirty state e reinício seguro.
- Conectores/ferramentas: autenticação, schema, conta explícita, escopos e erros. Não publique em canais/buckets reais durante testes comuns.
- Voz: epoch/cancelamento de respostas e áudio antigo, distinção entre ditado/conversação; hardware e eco precisam de teste manual separado.

Ao concluir, informe comandos/resultados reais e limites. Não reutilize a contagem de testes de uma tarefa anterior como evidência nova. Não execute ações pagas, captura real, alteração de contas ou desligamento para testar documentação.
