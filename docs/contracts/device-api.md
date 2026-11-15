# Contrato Device API (`pia` ↔ `pia-server`)

Versão do protocolo: **`1`** (`X-PIA-Protocol: 1`).

## Versionamento
- O cliente desktop (`Plugins/Connectors/pia_server/`) envia o cabeçalho `X-PIA-Protocol: 1` em todas as chamadas `/device/*` e `/mcp`.
- O servidor (`pia-server`) responde com `X-PIA-Protocol: 1` nas rotas `/device/*` e `/mcp`, mantendo compatibilidade retroativa com clientes `N` e `N-1`.

## Endpoints `/device/*`

### Pareamento e Login
- `POST /device/login/start`
  - Request: `{ "challenge": "<sha256>", "name": "<hostname>" }`
  - Response: `{ "id": "<43-char>", "code": "<6-digit>" }`
- `POST /device/login/poll`
  - Request: `{ "id": "<43-char>", "verifier": "<secret>" }`
  - Response: `{ "status": "pending" | "approved" | "expired", "token"?: "<device-token>" }`

### Runtime e Estado
- Autenticação: `Authorization: Bearer <device-token>` + `X-PIA-Protocol: 1`
- `GET /device/profile`: perfil da conta pareada.
- `GET /device/connectors`: lista de conectores e segredos gerenciados pelo servidor.
- `GET /device/secretary/pending`: notificações pendentes da Secretária.
- `POST /device/secretary/ack`: confirma leitura de notificações.

## Endpoint `/mcp`
- Protocolo JSON-RPC 2.0 sobre HTTP (`initialize`, `tools/list`, `tools/call`).
- Autenticação: `Authorization: Bearer <mcp-token>` + `X-PIA-Protocol: 1`.
