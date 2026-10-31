# Collection PIA

Importe [PIA.postman_collection.json](PIA.postman_collection.json) no Postman.
O arquivo é um catálogo para chamadas manuais, extraído das rotas atuais de
`src/HTTPServer.py`, `src/interop.py`, `src/pia/http.py`, `src/pia/service.py`
e dos `web_api.py` dos apps. Inclui operações nativas, APIs OpenAI, MCP,
AG-UI, interface, conectores, apps, arquivos e eventos SSE. Rotas dinâmicas
de arquivos são representadas por templates; não é uma lista de cada asset.
As rotas de tradução e voice consents constam com sua resposta 501 documentada.
Não inclui APIs de outros servidores, ACP/A2A removidos nem o callback OAuth
efêmero que abre em outra porta durante a conexão de contas.

## Conexão e autenticação

1. Inicie a PIA. Use Postman Desktop ou Desktop Agent para acessar localhost.
2. `base_url` começa como `http://127.0.0.1:8762`, sem barra final.
3. Para `/v1`, `/protocols` e câmera, preencha `api_key` com o valor de
   `OPENAI_COMPAT_API_KEY__SECRET`. Quando a configuração está vazia, a PIA
   não exige Bearer; a collection também começa sem uma chave real.
   `local` é apenas um exemplo, válido somente se configurado na PIA.
4. Para `/api/pia/*`, execute primeiro **POST /api/pia/session**.
   Deixe o cookie jar habilitado: a resposta grava `pia_session`, válido por
   24 horas. As requisições usam `Origin: {{base_url}}`, que deve coincidir
   exatamente com o Host (não misture localhost com 127.0.0.1).
   Bearer não substitui a sessão da interface. Essas rotas exigem loopback.
5. Preencha IDs e placeholders conforme o resultado das consultas. Criar uma
   conversa atualiza `chat_id`; copie `job` da resposta para `job_id` para
   acompanhar eventos. Em multipart selecione o arquivo local no campo File.

Os exemplos não contêm credenciais reais. Use valores locais do Postman/Vault
para segredos, sem sincronizá-los ou versioná-los. `/accounts`, configurações e
`object_storage/secrets` podem retornar segredos locais: não publique suas respostas.
Login do Codex, Bearer da PIA e OAuth dos conectores são independentes;
veja [MCP e Codex](../docs/MCP_CODEX.md).

## Uso e limites

Não execute a collection inteira no Runner: há operações que excluem dados,
publicam mensagens, alteram configurações, reiniciam a PIA ou usam hardware e
modelos. Os exemplos precisam de IDs existentes; os campos opcionais completos
continuam definidos pelo serviço correspondente. Apps nativos, como captura e
`/native`, precisam da PIA desktop. Google/Discord/storage dependem das contas
configuradas na própria PIA. Jobs e SSE podem exigir timeout maior no Postman.

Em transcrição há exemplos de `json`, `text`, `verbose_json`, `srt` e `vtt`.
Selecione um arquivo e mantenha `transcription_id` igual ao consultar progresso;
use a mesma autenticação nos dois requests. O upload OpenAI tem limite padrão
de **200 MiB do corpo completo**, configurável por
`OPENAI_COMPAT_MAX_UPLOAD_BYTES__INT`; multipart e base64 contam no limite.
A interface JSON aceita até 40 MiB, upload de configuração até 5 MiB;
protocolos/câmera/música aceitam JSON de até 2 MiB.
Chunks de Object Storage aceitam até 4 MiB de conteúdo decodificado.

## Atualizar o catálogo

Na raiz, execute com o Python local:

```powershell
.venv/Scripts/python.exe postman/generate_collection.py
.venv/Scripts/python.exe -m pytest tests/test_postman_collection.py -q
```

No Linux use `.venv/bin/python`. O gerador usa apenas a biblioteca padrão,
não importa managers, não lê `.env` e não executa requests. Revise exemplos,
novos tipos de dispatch e templates ao mudar rotas; a extração estática não é
um substituto para revisar contratos. Reimporte ou recrie a collection no
workspace desejado. Não há publicação automática nem execução de chamadas.

## Simulação local: ferramenta de imagens do chat

O contrato vem de src/HTTPServer.py: POST /v1/images/generations aceita prompt, n e response_format e retorna created/data com b64_json. A simulação responde com um PNG sintético e também modela erro 503; rotas não modeladas retornam 501.

mocks/pia-images/default.js implementa somente essa dependência. O código testado é o cliente real src/chat_tools.py, fora da simulação. simulations/chat-images.sim.yaml reúne a dependência em /pia. Rode tests/simulate_chat_images.py com o Python da PIA para iniciar, verificar os requests no log NDJSON e encerrar a simulação automaticamente. Não requer publicação ou alteração em workspace compartilhado.
