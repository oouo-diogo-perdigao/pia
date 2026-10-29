# Câmera, voz, agentes e música

Implementado na branch `codex/camera-voice-agent-music`.

## Câmera

`POST /action/camera` exige a mesma autenticação Bearer das rotas OpenAI e retorna `image/png`. Corpo JSON opcional: `{"device":0,"width":1280,"height":720}`. Requer câmera disponível e OpenCV; a câmera é liberada após cada captura. O chat também aceita pedidos explícitos como “Tire uma foto pela câmera”.

```sh
curl -X POST http://localhost:8762/action/camera \
  -H 'Authorization: Bearer local' -H 'Content-Type: application/json' \
  -d '{"device":0}' --output foto.png
```

## Interrupção por voz

No modo conversação, início sustentado de fala cancela a resposta anterior e o áudio pendente. A gravação continua para receber a nova fala. Ditado conserva seu comportamento. Há VAD e rejeição por correlação com o áudio reproduzido; isso não substitui cancelamento acústico de eco de hardware. Fones são recomendados em ambientes com eco. As reações de hover da Mini são aleatórias, com intervalo mínimo de cinco segundos entre tentativas.

## Protocolos

Todos exigem Bearer, inclusive descoberta. Registro compartilhado de ferramentas: contas/recursos, câmera, imagem, música e delegação aos CLIs. Skills podem chamar `piaTools(nome, argumentos)`. O chat disponibiliza ferramentas conforme o pedido e limita a seis etapas de execução.

| Perfil | Endpoint | Escopo |
|---|---|---|
| MCP Streamable HTTP, stateless | `/protocols/mcp` | initialize, ping, tools/list, tools/call; JSON-RPC, sem SSE/resume |
| A2A 0.3.0 síncrono | `/protocols/a2a` | message/send, tasks/get; tarefas concluídas em memória (até 200) |
| Agent Card | `/.well-known/agent-card.json` | descoberta do perfil A2A |
| ACP legado | `/protocols/acp/agents`, `/protocols/acp/runs` | subconjunto síncrono; Agent Communication Protocol, hoje incorporado ao A2A |
| AG-UI | `/protocols/ag-ui` | entrada RunAgentInput, SSE com eventos de início/texto/fim/erro |

Esses são perfis limitados, não implementações completas ou certificadas. ACP aqui não é o Agent Client Protocol de editores. A2A/AG-UI preservam o contexto entre chamadas pelo contextId/threadId. Não há transporte de arquivos arbitrários, tarefas distribuídas nem streaming A2A.

```sh
curl http://localhost:8762/protocols/mcp \
  -H 'Authorization: Bearer local' -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

No Gemini CLI, configure um servidor MCP com `httpUrl` apontando para esse endpoint e header Authorization. Clientes que exigem descoberta anônima podem precisar de configuração explícita. As ferramentas usam as permissões das contas locais; compartilhe o token somente com clientes autorizados.

## Codex e Gemini

Em Conectores / Agentes externos, use os CLIs oficiais instalados e previamente autenticados. A PIA executa Codex em read-only e Gemini em plan, com prompt por stdin, diretório isolado e limite de 300 segundos. A disponibilidade é detectada localmente. Não é integração com a janela de desktop nem compartilhamento automático do histórico do Codex.

## Música

Veja `Plugins/Apps/music/README.md`. `POST /v1/music/generations` aceita JSON com prompt, lyrics opcional, provider (`local` ou `gemini`) e duration (inteiro de 10 a 180). É uma rota própria da PIA, síncrona, com autenticação Bearer; não é um endpoint padrão OpenAI. Retorna arquivo, provedor, duração solicitada e audio_url. A interface usa jobs para não bloquear a navegação. A instalação local é opcional e baixa vários GB.

## Validação

Os testes automatizados substituem câmera, CLIs e provedores por adaptadores simulados. Captura real, interrupção com alto-falantes, download de modelos e geração paga exigem validação no ambiente configurado.
