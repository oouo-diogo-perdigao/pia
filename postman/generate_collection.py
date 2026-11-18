"""Build the manual API catalogue from source, without importing PIA or using accounts."""

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).with_name("PIA.postman_collection.json")


def tree(file):
    return ast.parse((ROOT / file).read_text(encoding="utf-8-sig"))


def compared(node, name):
    """Only equality/membership dispatch guards; not arbitrary strings/comments."""
    found = set()
    for item in ast.walk(node):
        if (
            not isinstance(item, ast.Compare)
            or not isinstance(item.left, ast.Name)
            or item.left.id != name
        ):
            continue
        for op, value in zip(item.ops, item.comparators):
            if (
                isinstance(op, ast.Eq)
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
            ):
                found.add(value.value)
            if isinstance(op, ast.In) and isinstance(
                value, (ast.Tuple, ast.List, ast.Set)
            ):
                found.update(
                    v.value
                    for v in value.elts
                    if isinstance(v, ast.Constant) and isinstance(v.value, str)
                )
    return found


def functions(file, names):
    return [
        n
        for n in ast.walk(tree(file))
        if isinstance(n, ast.FunctionDef) and n.name in names
    ]


BODIES = {
    "/v1/chat/completions": {
        "model": "local",
        "messages": [{"role": "user", "content": "Olá!"}],
        "stream": False,
    },
    "/v1/audio/speech": {
        "model": "tts-1",
        "input": "Olá, esta é a PIA.",
        "voice": "pf_dora",
        "response_format": "mp3",
    },
    "/v1/images/generations": {
        "prompt": "Uma paisagem roxa e azul",
        "n": 1,
        "response_format": "b64_json",
    },
    "/v1/music/generations": {
        "prompt": "Piano instrumental tranquilo",
        "lyrics": "",
        "provider": "local",
        "duration": 30,
    },
    # Catálogo: o item suno_mcp traz o status vindo da PIA Server (T8/T6).
    # GET-like; o corpo fica vazio. A descrição do item documenta o shape.
    "/music/providers": {},
    "/music/select": {"provider": "suno_mcp", "gemini_model": "lyria-3.5"},
    "/music/suno/legacy-credentials/remove": {"confirm": True},
    "/music/suno/legacy-credentials/dismiss": {},
    "/action/camera": {"device": 0, "width": 1280, "height": 720},
    "/action/text-at-cursor": {"text": "Texto de exemplo"},
    "/action/local-record": {"insert_at_cursor": False},
    "/action/play-audio": {"path": "{{audio_path}}"},
    "/action/play-audio-queue": {"path": "{{audio_path}}"},
    "/action/image": {"image": "{{image_data_url}}"},
    "/tts/speak": {"text": "Olá!", "voice": "pf_dora", "speed": 1},
    "/tts/generate": {"text": "Olá!", "voice": "pf_dora", "speed": 1},
    "/tts/storytelling": {"text": "Uma história começa aqui.", "speed": 1},
    "/tts/stream_text": {"text": "Uma frase completa.", "flush": True},
    "/protocols/ag-ui": {
        "threadId": "{{thread_id}}",
        "runId": "{{$guid}}",
        "messages": [{"role": "user", "content": "Olá!"}],
    },
    "/chat/new": {},
    "/chat/send": {"chat": "{{chat_id}}", "text": "Olá!"},
    "/chat/cancel": {"job": "{{job_id}}"},
    "/chat/draft": {"chat": "{{chat_id}}", "text": "Rascunho"},
    "/chat/update": {"chat": "{{chat_id}}", "title": "Minha conversa"},
    "/chat/message": {"chat": "{{chat_id}}", "id": 1, "action": "fork"},
    "/chat/delete": {"chat": "{{chat_id}}"},
    "/chat/delete-many": {"chats": ["{{chat_id}}"]},
    "/chat/read": {"chat": "{{chat_id}}", "through": 1},
    "/folder/save": {"name": "Minha pasta"},
    "/folder/delete": {"id": "{{folder_id}}"},
    "/settings/import-preview": {
        "data": "{{backup_base64}}",
        "password": "{{backup_password}}",
    },
    "/settings/credential": {"name": "{{credential_name}}"},
    "/settings/documents": {"name": "keywords.txt", "value": "pia"},
    "/settings/save": {"section": "general", "values": {}},
    "/settings/upload": {
        "section": "{{section}}",
        "name": "{{file_variable}}",
        "filename": "example.json",
        "data": "{{file_base64}}",
    },
    "/preferences": {"language": "pt-BR"},
    "/apps/order": {
        "order": ["music", "object_storage", "podcast_automation", "screenshots"]
    },
    "/notifications/settings": {"read_aloud": False, "muted": []},
    "/notifications/read": {"source": "Apps/music"},
    "/notifications/publish": {
        "source": "Apps/music",
        "title": "Teste",
        "text": "Notificação de teste",
        "links": [],
    },
    "/media/state": {"client": "{{media_client}}", "playing": False},
    "/logs/read": {"name": "{{log_name}}"},
    "/logs/open": {"name": "{{log_name}}"},
    "/logs/clear": {"name": "{{log_name}}"},
    "/native": {"action": "inspect"},
}

APP_BODIES = {
    "music/generate": BODIES["/v1/music/generations"] | {"count": 1},
    "music/cancel": {"job": "{{job_id}}"},
    "music/select": BODIES["/music/select"],
    "podcast_automation/start": {
        "task": "process",
        "monitor": False,
        "shutdown_after": False,
    },
    "podcast_automation/save-options": {
        "outputs": {
            "mp3": True,
            "txt": True,
            "srt": True,
            "vtt": True,
            "resumo.json": True,
        },
        "integrations": {},
    },
    "podcast_automation/save-config": {
        "value": {
            "nomes_reais": {},
            "campaign_details": {},
            "publication": {},
            "audio": {},
            "processing": {},
        }
    },
    "screenshots/capture": {"mode": "selection"},
    "screenshots/image": {"id": "{{capture_id}}"},
    "screenshots/list-saved": {"offset": 0, "limit": 24},
    "screenshots/color": {"value": "#8257e5"},
    "screenshots/delete-saved": {"names": ["{{capture_name}}"]},
    "screenshots/save-config": {"value": {"format": "png", "quality": 92}},
    "object_storage/delete": {"keys": ["{{object_key}}"]},
    "object_storage/upload-begin": {"key": "{{object_key}}", "size": 0},
    "object_storage/upload-chunk": {
        "id": "{{upload_id}}",
        "offset": 0,
        "data": "{{file_base64}}",
    },
}


MUSIC_GENERATE_400_DESCRIPTION = (
    "Gera um lote de músicas. Sucesso devolve `{job}` e o progresso segue no SSE. "
    "A recusa antes do job responde HTTP 400 com `{error, code}`, onde `code` é "
    "o motivo da indisponibilidade do Suno: `suno_not_connected`, "
    "`suno_credential_expired`, `pia_server_unpaired`, `pia_server_unreachable` "
    "ou `pia_server_unsupported`."
)


def music_generate_400_example(request):
    """Exemplo salvo da recusa 400 com o `code` validado pelo http.py."""
    return {
        "name": "400 — Suno não conectado",
        "originalRequest": request,
        "status": "Bad Request",
        "code": 400,
        "_postman_previewlanguage": "json",
        "header": [{"key": "Content-Type", "value": "application/json"}],
        "body": json.dumps(
            {
                "error": "Conecte o Suno em Configurações → Música.",
                "code": "suno_not_connected",
            },
            ensure_ascii=False,
            indent=2,
        ),
    }


# --- Música / Suno pela PIA Server (T6/T8) -----------------------------------
# Rotas locais de web_api.route (src/pia/service.py encaminha /music/* para o
# app). Exemplos fictícios: nenhum token, link de áudio ou e-mail real.
STATUS = {200: "OK", 400: "Bad Request", 500: "Internal Server Error"}
SUNO_ACCOUNT_EXAMPLE = {
    "id": "acc_exemplo_1",
    "label": "Conta principal",
    "email": "pessoa@example.com",
    "name": "Pessoa Exemplo",
    "credential_state": "configured",
    "available": True,
    "expires_at": "2026-12-01T12:00:00Z",
    "reason": None,
    "hint": None,
}
SUNO_ITEM_EXAMPLE = {
    "id": "suno_mcp",
    "label": "Suno",
    "name": "Suno",
    "kind": "remote",
    "description": "Suno pela PIA Server",
    "available": True,
    "reason": None,
    "hint": None,
    "connected": True,
    "credential_state": "configured",
    "expires_at": "2026-12-01T12:00:00Z",
    "settings": {"max_count": 10, "duration": [10, 180], "instrumental": True},
    "accounts": [SUNO_ACCOUNT_EXAMPLE],
    "selected_account_id": "acc_exemplo_1",
    "active_job": None,
    "settings_route": {"view": "settings", "section": "Apps/music"},
}
LOCAL_FILE_EXAMPLE = {
    "file": "0123456789abcdef0123456789abcdef.mp3",
    "provider": "suno_mcp",
    "prompt": "Piano instrumental tranquilo",
    "lyrics": "",
    "requested_duration": 30,
    "audio_url": "/api/pia/music/files/0123456789abcdef0123456789abcdef.mp3",
    "batch": "7d3f0c1e2b4a4c8e9f001122aabbccdd",
    "variant": 1,
    "client_id": "7d3f0c1e-2b4a-4c8e-9f00-1122aabbccdd",
    "generation_id": "gen_exemplo_1",
    "track_n": 1,
    "extra": False,
    "label": "Suno",
    "title": "Manhã calma",
    "modified": 1795000000.0,
}
HISTORY_ITEM_EXAMPLE = {
    "id": "7d3f0c1e-2b4a-4c8e-9f00-1122aabbccdd",
    "job_id": None,
    "provider": "suno_mcp",
    "source": "suno",
    "suno_account": {"id": "acc_exemplo_1", "name": "Pessoa Exemplo"},
    "prompt": "Piano instrumental tranquilo",
    "lyrics": "",
    "params": {
        "provider": "suno_mcp",
        "duration": 30,
        "count": 2,
        "suno_account_id": "acc_exemplo_1",
    },
    "created_at": "2026-11-17T22:00:00.000000Z",
    "state": "completed",
    "code": None,
    "count": 2,
    "this_device": True,
    "tracks": [
        {
            "n": 1,
            "title": "Manhã calma",
            "duration": 31.5,
            "extra": False,
            "label": "Suno",
            "file": LOCAL_FILE_EXAMPLE,
            "availability": "local_file",
        },
        {
            "n": 2,
            "title": "Manhã calma (2)",
            "duration": 29.8,
            "extra": False,
            "label": "Suno",
            "file": None,
            "availability": "redownload",
        },
    ],
}
SUNO_ERROR_CODES = (
    "Erros: HTTP 400 {error, code}. Códigos possíveis: pia_server_unpaired, "
    "pia_server_unreachable, pia_server_unsupported, "
    "suno_not_connected, suno_credential_expired, suno_account_not_found, "
    "suno_account_taken, suno_account_mismatch, suno_identity_unavailable, "
    "suno_oauth_denied, suno_oauth_invalid ou o code repassado pela PIA Server."
)
UNPAIRED_ERROR = {
    "error": "Para usar o Suno, entre na PIA Server em Configurações → PIA Server.",
    "code": "pia_server_unpaired",
}
# (method, path, suffix) -> description, body, query and saved examples.
MUSIC_ROUTES = [
    {
        "method": "GET",
        "path": "/api/pia/music/suno/status",
        "description": (
            "Status do Suno lido agora da PIA Server (sem o cache curto do "
            "catálogo): o mesmo item suno_mcp do /music/providers. accounts[] "
            "traz {id, label, email, name, credential_state "
            "(configured|unavailable|refresh_failed), available, expires_at, "
            "reason, hint}. selected_account_id só vem preenchido com "
            "exatamente uma conta válida. active_job fica no nível do item, "
            "com suno_account_id e job_id (id local aceito pelo watchJob, só "
            "neste PC). Também retoma, de forma lazy, o job deste PC. Nunca "
            "traz token."
        ),
        "examples": [
            ("200 — uma conta conectada", 200, SUNO_ITEM_EXAMPLE),
            (
                "200 — PIA não pareada",
                200,
                {
                    **SUNO_ITEM_EXAMPLE,
                    "available": False,
                    "reason": "pia_server_unpaired",
                    "hint": {
                        "text": UNPAIRED_ERROR["error"],
                        "route": {
                            "view": "settings",
                            "section": "Connectors/pia_server",
                        },
                    },
                    "connected": False,
                    "credential_state": "missing",
                    "expires_at": None,
                    "accounts": [],
                    "selected_account_id": None,
                },
            ),
        ],
    },
    {
        "method": "POST",
        "path": "/api/pia/music/suno/connect",
        "body": {"replace_account_id": "{{suno_account_id}}"},
        "description": (
            "Inicia a conexão de uma conta Suno na PIA Server (o OAuth acontece "
            "lá, nunca neste PC). Corpo vazio {} conecta uma conta nova; "
            "replace_account_id reconecta uma conta existente. Abra auth_url "
            "no navegador e consulte GET /music/suno/connect/<attempt_id> a "
            "cada 3 s. " + SUNO_ERROR_CODES
        ),
        "examples": [
            (
                "200 — tentativa criada",
                200,
                {
                    "auth_url": "https://pia.example.com/suno/authorize?attempt=att_exemplo_1",
                    "attempt_id": "att_exemplo_1",
                    "expires_in": 600,
                },
            ),
            ("400 — PIA não pareada", 400, UNPAIRED_ERROR),
        ],
    },
    {
        "method": "GET",
        "path": "/api/pia/music/suno/connect/{{suno_attempt_id}}",
        "description": (
            "Estado da tentativa: {state: pending|connected|failed|expired, "
            "account_id?, code?}. Tentativa expirada responde 200 "
            "{state: expired}; só a tentativa inexistente responde 400 "
            "code=suno_connect_not_found. Em failed, code traz o motivo "
            "(ex.: suno_oauth_denied, suno_account_taken, "
            "suno_account_mismatch). Depois de connected, recarregue o "
            "/music/providers."
        ),
        "examples": [
            ("200 — pendente", 200, {"state": "pending"}),
            (
                "200 — conectada",
                200,
                {"state": "connected", "account_id": "acc_exemplo_1"},
            ),
            (
                "200 — falhou",
                200,
                {"state": "failed", "code": "suno_account_taken"},
            ),
            ("200 — expirada", 200, {"state": "expired"}),
            (
                "400 — tentativa inexistente",
                400,
                {
                    "error": "Tentativa de conexão não encontrada. Tente conectar de novo.",
                    "code": "suno_connect_not_found",
                },
            ),
        ],
    },
    {
        "method": "POST",
        "path": "/api/pia/music/suno/accounts/{{suno_account_id}}/rename",
        "body": {"label": "Conta principal"},
        "description": (
            "Apelido da conta Suno (RN07). Chama PATCH "
            "/device/suno/accounts/<id> na PIA Server e devolve {ok, provider} "
            "com o item suno_mcp atualizado. label: 1 a 80 caracteres, sem "
            "caracteres de controle; fora disso responde 400 "
            "code=invalid_label. Chaves além de label são recusadas. "
            + SUNO_ERROR_CODES
        ),
        "examples": [
            ("200 — renomeada", 200, {"ok": True, "provider": SUNO_ITEM_EXAMPLE}),
            (
                "400 — apelido inválido",
                400,
                {
                    "error": "O apelido da conta Suno deve ter de 1 a 80 caracteres, sem caracteres de controle.",
                    "code": "invalid_label",
                },
            ),
        ],
    },
    {
        "method": "POST",
        "path": "/api/pia/music/suno/disconnect",
        "body": {"account_id": "{{suno_account_id}}"},
        "description": (
            "Desconecta a conta Suno na PIA Server (DELETE "
            "/device/suno/accounts/<id>) e devolve {ok, provider} com o item "
            "suno_mcp atualizado. Nada do Suno fica neste PC. " + SUNO_ERROR_CODES
        ),
        "examples": [
            (
                "200 — desconectada",
                200,
                {
                    "ok": True,
                    "provider": {
                        **SUNO_ITEM_EXAMPLE,
                        "available": False,
                        "reason": "suno_not_connected",
                        "hint": {
                            "text": "Conecte o Suno em Configurações → Música.",
                            "route": {"view": "settings", "section": "Apps/music"},
                        },
                        "connected": False,
                        "credential_state": "missing",
                        "expires_at": None,
                        "accounts": [],
                        "selected_account_id": None,
                    },
                },
            ),
        ],
    },
    {
        "method": "GET",
        "path": "/api/pia/music/history",
        "query": "?cursor=&limit=100",
        "description": (
            "Histórico de gerações (RN20): itens da PIA Server mesclados com o "
            "índice local, jobs ativos primeiro e depois do mais novo para o "
            "mais antigo. cursor é opaco (next_cursor da página anterior); "
            "limit vai de 1 a 100. tracks[].availability: local_file (file "
            "traz o item da biblioteca), redownload (faixa Suno sem arquivo "
            "neste PC), other_device_local (áudio local de outro PC) ou null "
            "(áudio local deste PC que sumiu). Offline ou não pareado: só os "
            "itens locais, com server_unavailable=true e server_reason "
            "pia_server_unpaired|pia_server_unreachable."
        ),
        "examples": [
            (
                "200 — página do histórico",
                200,
                {
                    "items": [HISTORY_ITEM_EXAMPLE],
                    "next_cursor": None,
                    "server_unavailable": False,
                    "server_reason": None,
                },
            ),
        ],
    },
    {
        "method": "DELETE",
        "path": "/api/pia/music/history/{{history_id}}",
        "body": {},
        "description": (
            "Exclusão definitiva do item na PIA Server. NUNCA apaga o arquivo "
            "local: grava uma marca local (tombstone) para o item não voltar "
            "pela varredura da pasta. Não pareado: 400 pia_server_unpaired. "
            "Item desconhecido: 400 history_item_not_found."
        ),
        "examples": [
            (
                "200 — excluído",
                200,
                {"ok": True, "id": "7d3f0c1e-2b4a-4c8e-9f00-1122aabbccdd"},
            ),
            ("400 — PIA não pareada", 400, UNPAIRED_ERROR),
        ],
    },
    {
        "method": "POST",
        "path": "/api/pia/music/history/{{history_id}}/tracks/{{track_n}}/redownload",
        "body": {},
        "description": (
            "Baixa de novo uma faixa Suno pelo proxy da PIA Server, em qualquer "
            "PC da conta, para a pasta de música deste PC. Vira job: devolve "
            "{job_id} para o watchJob; um 2º pedido da mesma faixa ainda "
            "baixando devolve o mesmo job_id. O evento track traz {item, "
            "track: {n, title, duration, extra, label, availability: "
            "local_file, file}, history_id}. Erros 400: pia_server_unpaired, "
            "history_item_not_found, track_not_found, suno_track_unavailable "
            "(link morto no Suno), not_origin_device (faixa local de outro PC) "
            "e local_audio_missing (faixa local deste PC que sumiu)."
        ),
        "examples": [
            ("200 — job criado", 200, {"job_id": "{{job_id}}"}),
            (
                "400 — música indisponível no Suno",
                400,
                {
                    "error": "Esta música não está mais disponível no Suno.",
                    "code": "suno_track_unavailable",
                },
            ),
        ],
    },
]
LEGACY_EXAMPLES = {
    ("GET", "/api/pia/music/suno/legacy-credentials"): [
        (
            "200 — credenciais antigas encontradas",
            200,
            {
                "present": True,
                "prompt": True,
                "items": [
                    {
                        "kind": "vault",
                        "label": "Token de acesso OAuth do Suno (servidor)",
                    },
                    {
                        "kind": "setting",
                        "label": "Token do Suno nas configurações de Música",
                    },
                    {
                        "kind": "mcp_server",
                        "label": "Servidor MCP local do Suno (suno_mcp)",
                    },
                ],
            },
        ),
        (
            "200 — nada encontrado",
            200,
            {"present": False, "prompt": False, "items": []},
        ),
    ],
    ("POST", "/api/pia/music/suno/legacy-credentials/remove"): [
        (
            "200 — removidas",
            200,
            {
                "ok": True,
                "removed": ["Token do Suno nas configurações de Música"],
                "present": False,
                "prompt": False,
            },
        ),
        (
            "400 — falta confirmar",
            400,
            {
                "error": "Confirme a remoção das credenciais antigas do Suno deste computador.",
                "code": "confirmation_required",
            },
        ),
    ],
    ("POST", "/api/pia/music/suno/legacy-credentials/dismiss"): [
        (
            "200 — pergunta desligada",
            200,
            {
                "ok": True,
                "present": True,
                "prompt": False,
                "items": [
                    {
                        "kind": "setting",
                        "label": "Token do Suno nas configurações de Música",
                    }
                ],
            },
        ),
    ],
}
SUNO_GENERATE_BODY = {
    "prompt": "Piano instrumental tranquilo",
    "lyrics": "",
    "provider": "suno_mcp",
    "duration": 30,
    "count": 2,
    "suno_account_id": "{{suno_account_id}}",
}
SUNO_GENERATE_DESCRIPTION = (
    "ATENÇÃO: gera de verdade no Suno e GASTA CRÉDITOS. Não execute sem o ok "
    "explícito do dono da conta. Cria o job na PIA Server e devolve {job}; o "
    "progresso segue no SSE. suno_account_id é obrigatório com 2 ou mais "
    "contas válidas (senão 400 suno_account_required) e opcional com uma "
    "só. Recusas antes do job (400 {error, code}): suno_not_connected, "
    "suno_credential_expired, suno_account_required, suno_account_not_found, "
    "suno_job_active, pia_server_unpaired, pia_server_unreachable, "
    "pia_server_unsupported."
)


def response_example(request, name, status, body):
    return {
        "name": name,
        "originalRequest": request,
        "status": STATUS[status],
        "code": status,
        "_postman_previewlanguage": "json",
        "header": [{"key": "Content-Type", "value": "application/json"}],
        "body": json.dumps(body, ensure_ascii=False, indent=2),
    }


def example_for_node(node, base):
    """Document mandatory data keys without reading any runtime configuration."""
    result = dict(base)
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Subscript)
            and isinstance(child.value, ast.Name)
            and child.value.id == "data"
            and isinstance(child.slice, ast.Constant)
            and isinstance(child.slice.value, str)
        ):
            key = child.slice.value
            result.setdefault(key, "{{" + key + "}}")
    return result


def build():
    folders = {}
    seen = set()

    def add(group, method, path, data=None, suffix="", description="", query=""):
        identity = (method, path, suffix)
        if identity in seen:
            return
        seen.add(identity)
        local = path.startswith("/api/pia/")
        request = {
            "method": method,
            "header": [],
            "url": "{{base_url}}" + path + query,
            "description": description
            or (
                "API da interface: sessão local obrigatória. Consulte postman/README.md."
                if local
                else "Rota extraída do código atual. Consulte os contratos e limites no repositório."
            ),
        }
        if local or not path.startswith(("/v1/", "/protocols/", "/action/camera")):
            request["auth"] = {"type": "noauth"}
        if local:
            request["header"].append({"key": "Origin", "value": "{{base_url}}"})
        if method in ("POST", "DELETE"):
            request["header"].append(
                {"key": "Content-Type", "value": "application/json"}
            )
            request["body"] = {
                "mode": "raw",
                "raw": json.dumps(
                    data if data is not None else BODIES.get(path, {}),
                    ensure_ascii=False,
                    indent=2,
                ),
                "options": {"raw": {"language": "json"}},
            }
        item = {
            "name": method + " " + path + (" · " + suffix if suffix else ""),
            "request": request,
            "response": [],
        }
        folders.setdefault(group, []).append(item)
        return item

    add(
        "00 · Sessão local",
        "POST",
        "/api/pia/session",
        {},
        description="Execute primeiro para as APIs /api/pia. Postman armazena pia_session no cookie jar. Origin deve coincidir exatamente com base_url; use Desktop Agent para localhost. Não usa Bearer.",
    )
    for fn in functions("src/HTTPServer.py", {"do_GET", "do_POST", "do_DELETE"}):
        method = fn.name.removeprefix("do_")
        for path in sorted(compared(fn, "path")):
            if not path.startswith("/"):
                continue
            group = (
                "01 · OpenAI"
                if path.startswith("/v1/")
                else "02 · Ações nativas"
                if path.startswith("/action/")
                else "03 · TTS"
                if path.startswith("/tts/")
                else "04 · Mini PIA e voz"
            )
            unsupported = path in ("/v1/audio/translations", "/v1/audio/voice_consents")
            item = add(
                group,
                method,
                path,
                description="Compatibilidade: esta rota retorna 501 not_implemented."
                if unsupported
                else "",
            )
            if method == "POST" and path in (
                "/v1/audio/transcriptions",
                "/v1/images/edits",
                "/v1/images/variations",
            ):
                fields = [
                    {
                        "key": "file" if "transcriptions" in path else "image",
                        "type": "file",
                        "src": [],
                    }
                ]
                fields += [
                    {"key": k, "value": v, "type": "text"}
                    for k, v in (
                        {
                            "model": "whisper-1",
                            "response_format": "verbose_json",
                            "language": "pt",
                        }
                        if "transcriptions" in path
                        else {
                            "prompt": "Edite esta imagem",
                            "response_format": "b64_json",
                        }
                    ).items()
                ]
                item["request"]["header"] = []
                item["request"]["body"] = {"mode": "formdata", "formdata": fields}
                if "transcriptions" in path:
                    item["request"]["header"] = [
                        {
                            "key": "X-PIA-Transcription-ID",
                            "value": "{{transcription_id}}",
                        }
                    ]
                    for fmt in ("json", "text", "srt", "vtt"):
                        variant = add(group, method, path, suffix=fmt)
                        variant["request"]["header"] = item["request"]["header"].copy()
                        variant["request"]["body"] = json.loads(
                            json.dumps(item["request"]["body"])
                        )
                        next(
                            f
                            for f in variant["request"]["body"]["formdata"]
                            if f["key"] == "response_format"
                        )["value"] = fmt
    mini = "04 · Mini PIA e voz"
    for label, action, payload, detail in (
        ("Mostrar Mini PIA", "mini", {"visible": True}, "Mostra a Mini PIA."),
        (
            "Ocultar Mini PIA",
            "mini",
            {"visible": False},
            "Oculta a Mini PIA e mantém o aplicativo ativo.",
        ),
        (
            "Alternar microfone",
            "voice",
            {},
            "Alterna o microfone da Mini PIA. Pode iniciar a gravação.",
        ),
        (
            "Expandir janela principal",
            "show",
            {"visible": True},
            "Abre a janela principal da PIA.",
        ),
        (
            "Fechar compositor",
            "mini-compose-close",
            {},
            "Fecha o compositor. Salve o rascunho antes se necessário.",
        ),
        (
            "Ler resposta do chat",
            "mini-job",
            {"job": "{{job_id}}"},
            "Lê em voz alta a resposta de um job de chat existente.",
        ),
    ):
        add(
            mini,
            "POST",
            "/api/pia/native",
            {"action": action, "payload": payload},
            suffix=label,
            description="Requer PIA desktop e sessão local. " + detail,
        )
    add(
        mini,
        "GET",
        "/api/pia/chat/messages",
        query="?chat=_mini",
        suffix="Consultar rascunho da Mini PIA",
        description="Consulta o rascunho da Mini PIA. Requer sessão local.",
    )
    add(
        mini,
        "POST",
        "/api/pia/chat/draft",
        {"chat": "_mini", "text": "Rascunho de exemplo"},
        suffix="Salvar rascunho da Mini PIA",
        description="Substitui o rascunho da Mini PIA. Requer sessão local.",
    )
    add(
        mini,
        "POST",
        "/api/pia/chat/send",
        BODIES["/chat/send"],
        suffix="Enviar mensagem pela Mini PIA",
        description="Use o ID de uma conversa existente. Copie o job retornado para acompanhar os eventos ou ler a resposta. Requer sessão local.",
    )
    for method, path in [
        ("GET", "/v1/images/files/{{image_token}}"),
        ("GET", "/v1/audio/transcriptions/progress/{{transcription_id}}"),
        ("GET", "/v1/music/files/{{music_file}}"),
        ("POST", "/action/camera"),
        ("POST", "/v1/music/generations"),
    ]:
        if path == "/v1/music/generations":
            item = add(
                "05 · Câmera e música",
                method,
                path,
                description=MUSIC_GENERATE_400_DESCRIPTION,
            )
            if item:
                item["response"] = [music_generate_400_example(item["request"])]
        else:
            add("05 · Câmera e música", method, path)
    for name, body in [
        (
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "postman", "version": "1.0"},
            },
        ),
        ("ping", {}),
        ("tools/list", {}),
        ("tools/call", {"name": "pia_accounts", "arguments": {}}),
        ("notifications/initialized", {}),
    ]:
        rpc = {"jsonrpc": "2.0", "method": name, "params": body}
        if not name.startswith("notifications/"):
            rpc["id"] = 1
        add("06 · MCP e AG-UI", "POST", "/protocols/mcp", rpc, suffix=name)
    add(
        "06 · MCP e AG-UI",
        "POST",
        "/protocols/ag-ui",
        description="SSE RunAgentInput. Perfil PIA; resposta text/event-stream. Não há ACP nem A2A.",
    )
    readable = {
        "/state",
        "/chat/messages",
        "/settings",
        "/accounts",
        "/bots",
        "/bots/secretaria",
        "/logs",
        "/preferences",
        "/notifications",
        "/notifications/counts",
        "/settings/documents",
        "/settings/credentials",
        "/settings/storage",
        "/music/suno/legacy-credentials",
    }
    for fn in functions("src/pia/service.py", {"_dispatch"}):
        for path in sorted(compared(fn, "path")):
            methods = (
                ["GET", "POST"]
                if path in ("/preferences", "/bots/secretaria", "/settings/documents")
                else ["GET" if path in readable else "POST"]
            )
            for method in methods:
                body = BODIES.get(path, {})
                if path == "/bots/secretaria":
                    body = {"enabled": False}
                description = ""
                if path == "/music/providers":
                    description = (
                        "Catálogo dos geradores. O item suno_mcp (RN20) traz "
                        "available, reason (pia_server_unpaired|"
                        "pia_server_unreachable|pia_server_unsupported|"
                        "suno_not_connected|suno_credential_expired|null), "
                        "hint {text, route}, connected, credential_state, "
                        "expires_at, settings, accounts, selected_account_id, "
                        "active_job e legacy_credentials "
                        "{present, prompt}. selection traz provider e "
                        "gemini_model. Nenhum token do Suno existe no PC (RN16)."
                    )
                elif path == "/music/select":
                    description = (
                        "Salva o provedor (local, gemini ou suno_mcp) e o modelo "
                        "Gemini e devolve o catálogo. A conta Suno não é salva "
                        "aqui: ela vai só no generate (suno_account_id). Um "
                        "body antigo com suno_account_id é aceito e o campo é "
                        "ignorado. O modo Suno local/manual saiu (RN18)."
                    )
                elif path == "/music/suno/legacy-credentials":
                    description = (
                        "Credenciais antigas do Suno neste PC (RN17/CA15): "
                        "{present, prompt, items:[{kind, label}]}. Só rótulos, "
                        "nunca valores."
                    )
                elif path == "/music/suno/legacy-credentials/remove":
                    description = (
                        "Remove as credenciais antigas do Suno deste PC. Exige "
                        "{confirm: true}; sem isso responde 400 "
                        "code=confirmation_required e não apaga nada."
                    )
                elif path == "/music/suno/legacy-credentials/dismiss":
                    description = (
                        '"Agora não": não apaga nada e desliga a pergunta do '
                        "primeiro início."
                    )
                item = add(
                    "07 · Workspace e serviços",
                    method,
                    "/api/pia" + path,
                    body,
                    query="?chat={{chat_id}}" if path == "/chat/messages" else "",
                    description=description,
                )
                if path == "/chat/new":
                    item["event"] = [
                        {
                            "listen": "test",
                            "script": {
                                "type": "text/javascript",
                                "exec": [
                                    'if (pm.response.code === 200) pm.collectionVariables.set("chat_id", pm.response.json().id);'
                                ],
                            },
                        }
                    ]
    for route in MUSIC_ROUTES:
        item = add(
            "07 · Workspace e serviços",
            route["method"],
            route["path"],
            route.get("body"),
            query=route.get("query", ""),
            description=route["description"],
        )
        item["response"] = [
            response_example(item["request"], *example) for example in route["examples"]
        ]
    for folder in folders.values():
        for item in folder:
            request = item["request"]
            key = (request["method"], request["url"].removeprefix("{{base_url}}"))
            if key in LEGACY_EXAMPLES:
                item["response"] = [
                    response_example(request, *example)
                    for example in LEGACY_EXAMPLES[key]
                ]
    integrations = {
        "agents": {
            "status": {},
            "ask": {"provider": "codex", "prompt": "Explique suas capacidades."},
        },
        "google": {
            "accounts": {},
            "folders": {"account": "{{account_id}}", "folder": "root"},
        },
        "discord": {
            n: {}
            for n in (
                "status",
                "logs",
                "channels",
                "diagnose",
                "test",
                "register-link",
                "unlink",
            )
        },
        "taverns": {"channels": {}, "test": {"destination": "{{taverns_destination}}"}},
        "pia_server": {
            "account": None,
            "login-start": {"server": "https://pia.travelrpg.com"},
            "login-poll": {"id": "{{device_login_id}}"},
            "logout": {},
            "profile-status": {},
            "profile-push": {"revision": "0"},
            "profile-pull": {"revision": "1"},
        },
    }
    integrations["discord"].update(
        send={"text": "Mensagem de exemplo", "channel": "{{discord_channel_id}}"},
        listener={"enabled": True},
    )
    for plugin, actions in integrations.items():
        for action, body in actions.items():
            add(
                "08 · Conectores",
                "GET" if body is None else "POST",
                "/api/pia/integrations/" + plugin + "/" + action,
                body,
            )
    for file in sorted((ROOT / "Plugins/Apps").glob("*/web_api.py")):
        app = file.parent.name
        for fn in functions(file.relative_to(ROOT), {"handle"}):
            actions = compared(fn, "action")
            for n in ast.walk(fn):
                if (
                    app == "screenshots"
                    and isinstance(n, ast.Assign)
                    and any(
                        isinstance(t, ast.Name) and t.id == "allowed" for t in n.targets
                    )
                ):
                    actions.update(ast.literal_eval(n.value))
            # generate/prepare-local are accepted by a negative guard.
            if app == "music":
                actions.update(("generate", "prepare-local"))
            if app == "podcast_automation":
                actions.add("start")
            for action in sorted(actions):
                body = APP_BODIES.get(app + "/" + action, {})
                for guard in ast.walk(fn):
                    if isinstance(guard, ast.If) and action in compared(
                        guard.test, "action"
                    ):
                        body = example_for_node(
                            ast.Module(body=guard.body, type_ignores=[]), body
                        )
                if app == "object_storage" and action not in (
                    "accounts",
                    "cancel",
                    "upload-chunk",
                    "upload-finish",
                    "upload-cancel",
                ):
                    body = {"account": "{{account_id}}", "bucket": "{{bucket}}", **body}
                if app == "screenshots":
                    if action in (
                        "copy",
                        "save",
                        "desktop",
                        "drag",
                        "print",
                        "edit",
                        "finalize",
                    ):
                        body = {
                            "data": "{{image_data_url}}",
                            "title": "Captura",
                            "format": "png",
                        }
                    if action in ("saved-image", "open-saved", "copy-saved"):
                        body = {"name": "{{capture_name}}"}
                item = add(
                    "09 · Apps / " + app,
                    "POST",
                    "/api/pia/apps/" + app + "/" + action,
                    body,
                    description=(
                        MUSIC_GENERATE_400_DESCRIPTION
                        if app == "music" and action == "generate"
                        else ""
                    ),
                )
                if item and app == "music" and action == "generate":
                    item["response"] = [music_generate_400_example(item["request"])]
                    suno = add(
                        "09 · Apps / " + app,
                        "POST",
                        "/api/pia/apps/music/generate",
                        SUNO_GENERATE_BODY,
                        suffix="Suno (gasta créditos)",
                        description=SUNO_GENERATE_DESCRIPTION,
                    )
                    suno["response"] = [
                        response_example(
                            suno["request"],
                            "200 — job criado",
                            200,
                            {"job": "{{job_id}}"},
                        ),
                        response_example(
                            suno["request"],
                            "400 — escolha a conta Suno",
                            400,
                            {
                                "error": "Escolha a conta Suno",
                                "code": "suno_account_required",
                            },
                        ),
                    ]
    add(
        "10 · Arquivos e eventos",
        "GET",
        "/api/pia/events/{{job_id}}",
        query="?after=0",
        description="SSE de job. Sessão local; Last-Event-ID ou after permite retomar. Requer um job existente.",
    )
    add(
        "10 · Arquivos e eventos",
        "GET",
        "/api/pia/logs/file",
        query="?name={{log_name}}",
    )
    for path in (
        "/api/pia/music/files/{{music_file}}",
        "/api/pia/chat/assets/{{chat_asset}}",
        "/",
        "/pia/{{pia_asset}}",
        "/mini/{{mini_asset}}",
        "/apps/{{app_id}}/{{app_asset}}",
        "/bots/{{bot_id}}/avatar.svg",
        "/bots/{{bot_id}}/web/{{bot_asset}}",
        "/connectors/{{connector_id}}/web/{{connector_asset}}",
    ):
        add("10 · Arquivos e eventos", "GET", path)
    add(
        "10 · Arquivos e eventos",
        "OPTIONS",
        "/",
        description="Preflight CORS comum do servidor; não é uma ação de aplicação.",
    )
    variables = {
        "base_url": "http://127.0.0.1:8762",
        "api_key": "",
        "chat_id": "",
        "folder_id": "",
        "job_id": "",
        "transcription_id": "postman-transcription",
        "thread_id": "postman-thread",
        "account_id": "",
        "suno_account_id": "",
        "suno_attempt_id": "",
        "history_id": "",
        "track_n": "1",
        "music_file": "",
        "image_token": "",
        "log_name": "plugins/Apps/music.log",
        "media_client": "postman",
        "app_id": "screenshots",
        "app_asset": "about.html",
        "bot_id": "secretaria",
        "bot_asset": "about.html",
        "connector_id": "agents",
        "connector_asset": "about.html",
        "pia_asset": "sdk.js",
        "mini_asset": "index.html",
    }
    collection = {
        "info": {
            "name": "PIA",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            "description": "Catálogo manual das rotas atuais da PIA, gerado do código por postman/generate_collection.py. Não execute a collection inteira: há ações nativas, exclusões, publicações e gerações. Preencha IDs e arquivos antes de enviar. Bearer api_key é opcional quando a chave da PIA está vazia. Para /api/pia execute primeiro POST /api/pia/session, com cookie jar habilitado e Origin igual à base_url. Leia postman/README.md. ACP/A2A e rotas de outros servidores não fazem parte desta API.",
        },
        "auth": {
            "type": "bearer",
            "bearer": [{"key": "token", "value": "{{api_key}}", "type": "string"}],
        },
        "variable": [
            {"key": k, "value": v, "type": "string"} for k, v in variables.items()
        ],
        "item": [{"name": name, "item": items} for name, items in folders.items()],
    }
    # Populate all placeholders with empty values, never with real credentials.
    import re

    keys = set(re.findall(r"\{\{([a-zA-Z_][a-zA-Z_0-9]*)\}\}", json.dumps(collection)))
    collection["variable"].extend(
        {"key": k, "value": "", "type": "string"}
        for k in sorted(keys - variables.keys())
    )
    return collection


if __name__ == "__main__":
    collection = build()
    OUT.write_text(
        json.dumps(collection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{sum(len(f['item']) for f in collection['item'])} requests -> {OUT}")
