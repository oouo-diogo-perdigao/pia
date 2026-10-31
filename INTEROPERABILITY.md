# Câmera, voz, agentes e música

Implementado na branch `codex/camera-voice-agent-music`.

## Câmera

`POST /action/camera` usa o mesmo verificador de autenticação das rotas OpenAI (Bearer quando a chave está preenchida) e retorna `image/png`. Corpo JSON: `{"device":0,"width":1280,"height":720}`; esses campos são opcionais. Requer câmera disponível e OpenCV; a câmera é liberada após cada captura. O chat também aceita pedidos explícitos como “Tire uma foto pela câmera”.

```sh
curl -X POST http://localhost:8762/action/camera \
  -H 'Authorization: Bearer local' -H 'Content-Type: application/json' \
  -d '{"device":0}' --output foto.png
```

## Interrupção por voz

No modo conversação, início sustentado de fala cancela a resposta anterior e o áudio pendente. A gravação continua para receber a nova fala. Ditado conserva seu comportamento. Há VAD e rejeição por correlação com o áudio reproduzido; isso não substitui cancelamento acústico de eco de hardware. Fones são recomendados em ambientes com eco. As reações de hover da Mini são aleatórias, com intervalo mínimo de cinco segundos entre tentativas.

## Protocolos

A autenticação usa o mesmo verificador Bearer da API: quando OPENAI_COMPAT_API_KEY está preenchida, envie Authorization; quando está vazia, a autenticação fica desabilitada. Não há login OAuth MCP. O [guia PIA como MCP no Codex](docs/MCP_CODEX.md) detalha cadastro, tokens, configuração desktop e diagnóstico. Registro compartilhado de ferramentas: contas/recursos, câmera, imagem, música e delegação aos CLIs. Skills podem chamar `piaTools(nome, argumentos)`. O chat disponibiliza ferramentas conforme o pedido e limita a seis etapas de execução.

| Perfil | Endpoint | Escopo |
|---|---|---|
| MCP Streamable HTTP, stateless | `/protocols/mcp` | initialize, ping, tools/list, tools/call; JSON-RPC, sem SSE/resume |
| AG-UI | `/protocols/ag-ui` | entrada RunAgentInput, SSE com eventos de início/texto/fim/erro |

Esses são perfis limitados, não implementações completas ou certificadas. AG-UI preserva contexto por threadId. ACP legado, A2A síncrono e Agent Card foram removidos; suas rotas não são mais disponibilizadas. Não há transporte de arquivos arbitrários nem tarefas distribuídas.

```sh
curl http://localhost:8762/protocols/mcp \
  -H 'Authorization: Bearer local' -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

Configure o cliente MCP com esse endpoint HTTP e header Authorization, conforme o formato de configuração do próprio cliente. Clientes que exigem descoberta anônima podem precisar de configuração explícita. As ferramentas usam as permissões das contas locais; compartilhe o token somente com clientes autorizados.

## Codex e Google Antigravity (AGY)

Em Configurações → Conectores → Agentes externos, use os CLIs oficiais instalados e previamente autenticados. A PIA executa Codex em read-only e Antigravity (`agy`) em plan, com prompt por stdin, diretório separado e limite de 300 segundos. AGY recebe um evento user em NDJSON e retorna um evento result com status SUCCESS. A disponibilidade é detectada localmente; configure AGENTS_AGY_EXECUTABLE para um caminho específico. A antiga variável AGENTS_GEMINI_EXECUTABLE não é reutilizada. Não é integração com a janela de desktop nem compartilhamento automático do histórico do Codex. Veja o README do conector para instalação e login.

## Música

Veja `Plugins/Apps/music/README.md`. `POST /v1/music/generations` aceita JSON com prompt, lyrics opcional, provider (`local` ou `gemini`) e duration (inteiro de 10 a 180). É uma rota própria da PIA, síncrona, com autenticação Bearer; não é um endpoint padrão OpenAI. Retorna arquivo, provedor, duração solicitada e audio_url. A interface usa jobs para não bloquear a navegação. A instalação local é opcional e baixa vários GB.

## Validação

Os testes automatizados substituem câmera, CLIs e provedores por adaptadores simulados. Captura real, interrupção com alto-falantes, download de modelos e geração paga exigem validação no ambiente configurado.
