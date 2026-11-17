"""Mock HTTP local do servidor MCP do Suno, para testes da PIA (T8).

Sobe um servidor JSON-RPC em thread, na porta efêmera 127.0.0.1:0, e
responde ``initialize``, ``notifications/initialized``, ``tools/list``,
``tools/call`` da tool de geração e um GET de áudio com bytes fake.

Não faz nenhuma chamada real ou paga ao Suno. ``ConnectionResetError`` e ``BrokenPipeError`` do cliente de teste são ignorados em ``handle_error`` do servidor HTTP (sem acesso externo a ``_httpd``).

Por que um servidor HTTP de verdade (e não só monkeypatch de
``requests``): o cliente atual (``Plugins/Apps/music/tools.py`` e
``src/mcp_connectors.py``) usa ``requests.post``/``get`` com JSON ou SSE.
Um HTTP local funciona com os dois clientes, com o download de
``audio_url`` e com os testes e2e futuros, sem acoplar o mock ao
transporte interno.

Contrato de ``tools/list``
    Se existir ``tests/fixtures/suno_mcp_tools_list.json`` (fixture da T2),
    ela é usada. Caso contrário, o mock segue o contrato heurístico do
    plano técnico (tool ``generate_music`` com ``prompt``/``lyrics``/
    ``duration``, mais ``get_credits``), o mesmo catálogo inferido em
    ``src/mcp_connectors.py``. **É preciso alinhar quando a T2 entrar.**

Clips por chamada
    A tool de geração devolve **2 clips por chamada** (decisão do CEO).
    O backend deve fazer ``ceil(N/2)`` chamadas e guardar clips até
    completar N faixas, descartando o excedente (ex.: N=3 → 2 chamadas,
    4 clips, o 4º descartado). Use :func:`take_n_clips` para isso.

Cenários (por chamada da tool de geração, em sequência configurável)
    ``success``
        HTTP 200, 2 clips com ``audio_url`` apontando para o GET local.
    ``401``
        HTTP 401 (token expirado / recusado).
    ``503`` / ``500``
        HTTP 5xx (Suno indisponível).
    ``timeout``
        Atrasa a resposta por ``timeout_delay`` segundos (padrão 1,5 s)
        para o cliente estourar o próprio timeout. A espera usa um
        ``threading.Event`` que o ``stop()`` sinaliza.
    ``partial``
        HTTP 200, 2 clips, mas o segundo vem sem áudio (falha parcial
        dentro da chamada). O lote da T3 (Q8) para no primeiro clip
        que falha, então a 2ª chamada da sequência não é feita.
    ``402``
        HTTP 402 (sem créditos).

    Exemplo CA07 + Q8 (N=3): ``scenarios=["partial", "503"]`` → 1
    ``tools/call`` (o 503 não é usado), 1 faixa salva e a notificação
    "1 de 3 músicas prontas (geração interrompida)". Para 2 faixas
    válidas e falha na 2ª chamada: ``scenarios=["success", "503"]``.
    Com ``clips_per_call=1`` e ``success``, N=3 dispara
    ``incomplete_batch`` (1 clip quando o lote pedia 2).

Download de áudio (``audio_behavior``, por clip)
    ``ok``
        HTTP 200, ``FAKE_AUDIO_BYTES``, ``audio/mpeg``.
    ``403`` / ``404`` / ``500``
        O status HTTP correspondente.
    ``html``
        HTTP 200 com ``Content-Type: text/html``.
    ``large``
        Corpo grande em streaming, ``size=N`` bytes, gerado em chunks
        sem carregar tudo na memória. Use ``size`` maior que o
        ``MAX_AUDIO_BYTES`` da T3 (os testes dela podem baixar o limite
        via monkeypatch).
    ``redirect``
        HTTP 302 com ``Location`` para um URL ``http://`` externo
        (padrão ``http://example.invalid/suno-audio.mp3``). O mock
        **não** segue o redirect e **não** acessa a rede.
    ``truncated``
        ``Content-Length`` maior do que o corpo efetivamente enviado.
    ``slow``
        Atraso configurável (``delay``) antes de enviar o corpo.

    Aceita string, dict ``{"mode": "...", ...}`` ou sequência (um
    comportamento por clip, na ordem de criação). Depois da geração:
    ``suno.set_audio_behavior(clip_id, {"mode": "large", "size": N})``.

Sessão MCP
    O header ``Mcp-Session-Id`` é enviado **somente** na resposta do
    ``initialize``, com um id novo a cada handshake. ``expire_sessions()``
    e ``DELETE`` no endpoint (com esse header) invalidam a sessão, para
    o caso "404 de sessão → refaz o handshake". ``require_session``
    permanece ``False`` por padrão (o cliente HTTP atual ainda não faz
    handshake) e deve virar ``True`` quando a T2 entrar. Os dois modos
    são suportados.

CA10 (``leaky=True``)
    A ``audio_url`` vem assinada
    (``?X-Amz-Signature=...&token=suno-test-token``) e o bearer aparece
    nas mensagens de erro de 401 e 5xx, para os testes e2e procurarem
    vazamento. O padrão é ``False``.

Outras opções
    ``auth_on_initialize=True`` (padrão) exige Authorization já no
    ``initialize``. Toda resposta 401 inclui ``WWW-Authenticate: Bearer``.

Uso (context manager)::

    from tests.fixtures.fake_suno_mcp import FakeSunoMcpServer

    with FakeSunoMcpServer(scenarios=["success", "503"]) as suno:
        # suno.url            -> http://127.0.0.1:<porta>/mcp
        # suno.token          -> bearer esperado (Authorization: Bearer …)
        # suno.requests       -> requisições recebidas, para asserts
        # suno.generation_calls()
        # suno.set_scenarios(["partial", "401"])
        # suno.set_audio_behavior(clip_id, "403")
        # suno.expire_sessions()
        ...

Uso (fixture pytest)
    A fixture ``fake_suno_mcp`` está registrada em ``tests/conftest.py``.

    def test_algo(fake_suno_mcp):
        fake_suno_mcp.set_scenarios(["success"])
        ...

O servidor encerra de forma limpa ao sair do ``with`` / da fixture
(``shutdown`` + ``join`` da thread). Se a thread não encerrar no
``__exit__``, emite ``RuntimeWarning`` em vez de exceção, para não
mascarar a falha do teste.
"""

from __future__ import annotations

import json
import sys
import threading
import uuid
import warnings
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import urlparse

CLIPS_PER_CALL = 2
DEFAULT_TOKEN = "suno-test-token"
DEFAULT_PROTOCOL_VERSION = "2025-11-25"
DEFAULT_TIMEOUT_DELAY = 1.5
DEFAULT_LARGE_AUDIO_SIZE = 256 * 1024
STREAM_CHUNK_SIZE = 64 * 1024
FAKE_AUDIO_BYTES = b"ID3\x04\x00\x00\x00\x00\x00\x00fake-suno-mcp-audio"
FAKE_AUDIO_CONTENT_TYPE = "audio/mpeg"
DEFAULT_REDIRECT_LOCATION = "http://example.invalid/suno-audio.mp3"
HTML_AUDIO_BODY = b"<html><body>not audio</body></html>"

TOOLS_LIST_FIXTURE_PATH = Path(__file__).with_name("suno_mcp_tools_list.json")

GENERATION_TOOL_CANDIDATES = (
    "generate_music",
    "create_song",
    "suno_generate_custom_music",
)

# Já estava no arquivo original; mantido para documentação do contrato.
ScenarioName = str  # success, 401, 402, 503, 500, timeout, partial

DEFAULT_TOOLS: list[dict[str, Any]] = [
    {
        "name": "generate_music",
        "description": (
            "Gera música a partir de prompt de estilo, letra opcional "
            "e duração. Cada chamada devolve 2 clips."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "style": {"type": "string"},
                "description": {"type": "string"},
                "lyrics": {"type": "string"},
                "lyric": {"type": "string"},
                "instrumental": {"type": "boolean"},
                "duration": {"type": "integer"},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "get_credits",
        "description": "Consulta créditos disponíveis na conta Suno.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def load_suno_tools_list(
    path: Path | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Carrega o ``tools/list`` da fixture T2, se existir.

    Devolve ``(tools, origem)``. ``origem`` é ``t2-fixture`` ou
    ``plano-heuristico``. Aceita um JSON ``{"tools": [...]}`` ou uma lista.
    """
    fixture = path if path is not None else TOOLS_LIST_FIXTURE_PATH
    if fixture.is_file():
        data = json.loads(fixture.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            tools = data.get("tools")
            if tools is None and isinstance(data.get("result"), dict):
                tools = data["result"].get("tools")
        elif isinstance(data, list):
            tools = data
        else:
            tools = None
        if isinstance(tools, list) and tools:
            return tools, "t2-fixture"
    return [dict(tool) for tool in DEFAULT_TOOLS], "plano-heuristico"


def pick_generation_tool(tools: Sequence[dict[str, Any]]) -> str:
    """Escolhe a tool de geração com a heurística da D2."""
    names = [str(t.get("name") or "") for t in tools]
    for candidate in GENERATION_TOOL_CANDIDATES:
        if candidate in names:
            return candidate
    for name in names:
        lowered = name.lower()
        if any(a in lowered for a in ("generate", "create")) and any(
            b in lowered for b in ("song", "music")
        ):
            return name
    return "generate_music"


def take_n_clips(
    batches: Iterable[Sequence[dict[str, Any]]], n: int
) -> list[dict[str, Any]]:
    """Empilha clips das chamadas até ``n``, descartando o excedente.

    Espelha a regra do backend: ``ceil(N/2)`` chamadas, cada clip vira
    uma faixa, e o clip extra de um N ímpar é descartado.
    """
    selected: list[dict[str, Any]] = []
    for batch in batches:
        for clip in batch:
            if len(selected) >= n:
                return selected
            selected.append(clip)
    return selected


def _normalize_scenarios(
    scenarios: str | Sequence[str] | None,
) -> list[str]:
    if scenarios is None:
        return ["success"]
    if isinstance(scenarios, str):
        return [scenarios]
    values = [str(item) for item in scenarios if str(item)]
    return values or ["success"]


def normalize_audio_behavior(behavior: Any) -> dict[str, Any]:
    """Normaliza um comportamento de download para ``{"mode": ...}``."""
    if behavior is None:
        return {"mode": "ok"}
    if isinstance(behavior, int):
        return {"mode": "status", "status": int(behavior)}
    if isinstance(behavior, str):
        text = behavior.strip()
        if text.isdigit():
            return {"mode": "status", "status": int(text)}
        aliases = {
            "ok": "ok",
            "html": "html",
            "text/html": "html",
            "large": "large",
            "oversized": "large",
            "redirect": "redirect",
            "truncated": "truncated",
            "slow": "slow",
        }
        if text in aliases:
            return {"mode": aliases[text]}
        return {"mode": text}
    if isinstance(behavior, dict):
        mode = behavior.get("mode")
        if not mode and "status" in behavior:
            mode = "status"
        result = dict(behavior)
        result["mode"] = str(mode or "ok")
        return result
    return {"mode": "ok"}


def public_clip(clip: dict[str, Any]) -> dict[str, Any]:
    """Remove chaves internas (ex.: ``_audio_behavior``) da resposta."""
    return {key: value for key, value in clip.items() if not str(key).startswith("_")}


@dataclass
class RecordedRequest:
    """Uma requisição recebida pelo mock (para asserts)."""

    method: str
    path: str
    headers: dict[str, str]
    body: bytes
    jsonrpc_method: str | None = None
    rpc_id: Any = None
    tool_name: str | None = None
    tool_arguments: dict[str, Any] | None = None
    status: int | None = None

    def json(self) -> Any:
        if not self.body:
            return None
        return json.loads(self.body.decode("utf-8"))


class _QuietThreadingHTTPServer(ThreadingHTTPServer):
    """Ignora reset/broken-pipe do cliente de teste no keep-alive."""

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


@dataclass
class FakeSunoMcpServer:
    """Servidor MCP HTTP fake do Suno (porta efêmera, uma thread).

    Parâmetros
    ----------
    scenarios
        Cenário único ou sequência aplicada a cada ``tools/call`` da
        tool de geração. Chamadas extras repetem o último cenário.
    required_token
        Bearer exigido. ``None`` desliga a checagem de Authorization.
    timeout_delay
        Segundos de espera no cenário ``timeout`` (e no download
        ``slow``, se ``delay`` não for informado).
    require_session
        Se verdadeiro, ``tools/list`` e ``tools/call`` exigem o header
        ``Mcp-Session-Id`` devolvido no ``initialize`` (404 se faltar
        ou tiver expirado). O padrão é falso, porque o cliente HTTP
        atual ainda não faz o handshake (a T2 vai passar para True).
    auth_on_initialize
        Se verdadeiro (padrão), o ``initialize`` também exige o bearer.
    include_base64
        Se verdadeiro, cada clip de sucesso também traz ``audio_base64``.
    leaky
        Se verdadeiro, a ``audio_url`` sai assinada e as mensagens de
        401/5xx incluem o bearer (CA10).
    audio_behavior
        Comportamento padrão de download (string, dict ou sequência
        aplicada na ordem de criação dos clips).
    tools
        Catálogo explícito; se omitido, usa :func:`load_suno_tools_list`.
    credits
        Valor devolvido por ``get_credits``.
    clips_per_call
        Quantos clips a tool de geração devolve (padrão 2). Use 1
        para exercitar ``incomplete_batch`` (Q1).
    """

    scenarios: str | Sequence[str] | None = "success"
    required_token: str | None = DEFAULT_TOKEN
    timeout_delay: float = DEFAULT_TIMEOUT_DELAY
    require_session: bool = False
    auth_on_initialize: bool = True
    include_base64: bool = False
    leaky: bool = False
    audio_behavior: Any = "ok"
    tools: list[dict[str, Any]] | None = None
    credits: int = 42
    clips_per_call: int = CLIPS_PER_CALL
    host: str = "127.0.0.1"

    requests: list[RecordedRequest] = field(default_factory=list, init=False)
    tools_list_source: str = field(default="", init=False)
    generation_tool: str = field(default="generate_music", init=False)
    session_id: str = field(default="", init=False)
    _scenario_list: list[str] = field(default_factory=list, init=False)
    _generation_index: int = field(default=0, init=False)
    _httpd: ThreadingHTTPServer | None = field(default=None, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _stop_event: threading.Event = field(default_factory=threading.Event, init=False)
    _clips: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)
    _sessions: set[str] = field(default_factory=set, init=False)
    _audio_behavior_default: dict[str, Any] = field(
        default_factory=lambda: {"mode": "ok"}, init=False
    )
    _audio_behavior_list: list[dict[str, Any]] = field(default_factory=list, init=False)
    _audio_behavior_index: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.tools is None:
            loaded, source = load_suno_tools_list()
            self.tools = loaded
            self.tools_list_source = source
        else:
            self.tools_list_source = "explicit"
        self.generation_tool = pick_generation_tool(self.tools)
        self.set_scenarios(self.scenarios)
        self.set_default_audio_behavior(self.audio_behavior)
        self.session_id = ""

    # -- ciclo de vida -------------------------------------------------

    @property
    def token(self) -> str | None:
        return self.required_token

    @property
    def port(self) -> int:
        if self._httpd is None:
            raise RuntimeError("O mock do Suno MCP ainda não foi iniciado.")
        return int(self._httpd.server_port)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def url(self) -> str:
        """Endpoint JSON-RPC (use nas settings ``MUSIC_SUNO_MCP_URL``)."""
        return f"{self.base_url}/mcp"

    def audio_url(self, clip_id: str, ext: str = "mp3") -> str:
        url = f"{self.base_url}/audio/{clip_id}.{ext}"
        if self.leaky:
            token = self.required_token or DEFAULT_TOKEN
            url += f"?X-Amz-Signature=fake-suno-signature&token={token}"
        return url

    def start(self) -> FakeSunoMcpServer:
        if self._httpd is not None:
            return self
        self._stop_event.clear()
        handler = self._make_handler()
        self._httpd = _QuietThreadingHTTPServer((self.host, 0), handler)
        httpd = self._httpd
        self._thread = threading.Thread(
            target=httpd.serve_forever,
            kwargs={"poll_interval": 0.05},
            name="fake-suno-mcp",
            daemon=True,
        )
        self._thread.start()
        return self

    def stop(self, *, warn_on_hang: bool = False) -> None:
        self._stop_event.set()
        httpd = self._httpd
        thread = self._thread
        self._httpd = None
        self._thread = None
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        if thread is not None:
            thread.join(timeout=2)
            if thread.is_alive():
                message = "A thread do mock do Suno MCP não encerrou."
                if warn_on_hang:
                    warnings.warn(message, RuntimeWarning, stacklevel=2)
                else:
                    raise RuntimeError(message)

    def __enter__(self) -> FakeSunoMcpServer:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop(warn_on_hang=True)

    def _interruptible_wait(self, seconds: float) -> bool:
        """Espera até ``seconds`` ou até o ``stop()``. True se interrompido."""
        return self._stop_event.wait(seconds)

    # -- configuração em runtime --------------------------------------

    def set_scenarios(self, scenarios: str | Sequence[str] | None) -> None:
        """Redefine a sequência de cenários e zera o contador de geração."""
        with self._lock:
            self._scenario_list = _normalize_scenarios(scenarios)
            self.scenarios = self._scenario_list
            self._generation_index = 0

    def set_default_audio_behavior(self, behavior: Any) -> None:
        """Define o comportamento de download dos próximos clips."""
        with self._lock:
            if isinstance(behavior, (list, tuple)):
                self._audio_behavior_list = [
                    normalize_audio_behavior(item) for item in behavior
                ]
                self._audio_behavior_default = {"mode": "ok"}
            else:
                self._audio_behavior_list = []
                self._audio_behavior_default = normalize_audio_behavior(behavior)
            self._audio_behavior_index = 0
            self.audio_behavior = behavior

    def set_audio_behavior(self, clip_id: str, behavior: Any) -> None:
        """Altera o download de um clip já gerado."""
        with self._lock:
            clip = self._clips.get(clip_id)
            if clip is None:
                raise KeyError(f"clip desconhecido: {clip_id}")
            clip["_audio_behavior"] = normalize_audio_behavior(behavior)

    def _behavior_for_new_clip(self) -> dict[str, Any]:
        with self._lock:
            if self._audio_behavior_list:
                index = min(
                    self._audio_behavior_index, len(self._audio_behavior_list) - 1
                )
                self._audio_behavior_index += 1
                return dict(self._audio_behavior_list[index])
            return dict(self._audio_behavior_default)

    def expire_sessions(self, session_id: str | None = None) -> None:
        """Invalida uma sessão (ou todas).

        Com ``require_session=True``, o próximo ``tools/list``/``tools/call``
        deve receber 404 para o cliente refazer o ``initialize``.
        """
        with self._lock:
            if session_id is None:
                self._sessions.clear()
            else:
                self._sessions.discard(session_id)

    def reset_recordings(self) -> None:
        """Limpa o log de requisições e o contador de gerações."""
        with self._lock:
            self.requests.clear()
            self._generation_index = 0
            self._clips.clear()
            self._audio_behavior_index = 0

    def next_scenario(self) -> str:
        with self._lock:
            if not self._scenario_list:
                return "success"
            index = min(self._generation_index, len(self._scenario_list) - 1)
            self._generation_index += 1
            return self._scenario_list[index]

    def generation_calls(self) -> list[RecordedRequest]:
        """Só as chamadas ``tools/call`` da tool de geração."""
        with self._lock:
            return [
                req
                for req in self.requests
                if req.jsonrpc_method == "tools/call"
                and req.tool_name == self.generation_tool
            ]

    def rpc_methods(self) -> list[str]:
        with self._lock:
            return [req.jsonrpc_method for req in self.requests if req.jsonrpc_method]

    def _error_message(self, kind: str) -> str:
        if kind == "unauthorized":
            message = "Unauthorized"
        elif kind == "credits":
            message = "Insufficient credits"
        else:
            message = "Suno unavailable"
        if self.leaky and self.required_token:
            return f"{message}: Bearer {self.required_token}"
        return message

    # -- handler HTTP --------------------------------------------------

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt: str, *args: object) -> None:
                return

            def do_GET(self) -> None:  # noqa: N802
                server._handle_get(self)

            def do_POST(self) -> None:  # noqa: N802
                server._handle_post(self)

            def do_DELETE(self) -> None:  # noqa: N802
                server._handle_delete(self)

        return Handler

    def _read_body(self, handler: BaseHTTPRequestHandler) -> bytes:
        length = int(handler.headers.get("Content-Length") or 0)
        return handler.rfile.read(length) if length else b""

    def _header_map(self, handler: BaseHTTPRequestHandler) -> dict[str, str]:
        return {str(k): str(v) for k, v in handler.headers.items()}

    def _send(
        self,
        handler: BaseHTTPRequestHandler,
        status: int,
        body: bytes = b"",
        content_type: str = "application/json",
        extra_headers: dict[str, str] | None = None,
        content_length: int | None = None,
    ) -> None:
        declared = len(body) if content_length is None else content_length
        headers = {
            "Content-Type": content_type,
            "Content-Length": str(declared),
        }
        if extra_headers:
            headers.update(extra_headers)
        try:
            handler.send_response(status)
            for key, value in headers.items():
                handler.send_header(key, value)
            handler.end_headers()
            if body:
                handler.wfile.write(body)
            handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # Cliente desistiu (ex.: timeout). Não falha o servidor.
            return

    def _send_json(
        self,
        handler: BaseHTTPRequestHandler,
        status: int,
        payload: dict[str, Any],
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(handler, status, body, extra_headers=extra_headers)

    def _send_401(
        self,
        handler: BaseHTTPRequestHandler,
        rpc_id: Any,
    ) -> None:
        self._send_json(
            handler,
            401,
            {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {
                    "code": -32001,
                    "message": self._error_message("unauthorized"),
                },
            },
            extra_headers={"WWW-Authenticate": "Bearer"},
        )

    def _send_stream(
        self,
        handler: BaseHTTPRequestHandler,
        status: int,
        size: int,
        content_type: str,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        """Envia ``size`` bytes em chunks, sem montar o corpo inteiro."""
        headers = {
            "Content-Type": content_type,
            "Content-Length": str(size),
        }
        if extra_headers:
            headers.update(extra_headers)
        try:
            handler.send_response(status)
            for key, value in headers.items():
                handler.send_header(key, value)
            handler.end_headers()
            remaining = max(0, int(size))
            chunk = b"S" * STREAM_CHUNK_SIZE
            while remaining and not self._stop_event.is_set():
                n = min(STREAM_CHUNK_SIZE, remaining)
                handler.wfile.write(chunk[:n])
                remaining -= n
            handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

    def _record(
        self,
        handler: BaseHTTPRequestHandler,
        body: bytes,
        payload: dict[str, Any] | None,
        status: int,
    ) -> RecordedRequest:
        params = payload.get("params") if isinstance(payload, dict) else None
        tool_name = None
        tool_arguments = None
        if isinstance(params, dict):
            tool_name = params.get("name")
            arguments = params.get("arguments")
            if isinstance(arguments, dict):
                tool_arguments = arguments
        recorded = RecordedRequest(
            method=handler.command,
            path=urlparse(handler.path).path,
            headers=self._header_map(handler),
            body=body,
            jsonrpc_method=(payload or {}).get("method") if payload else None,
            rpc_id=(payload or {}).get("id") if payload else None,
            tool_name=tool_name if isinstance(tool_name, str) else None,
            tool_arguments=tool_arguments,
            status=status,
        )
        with self._lock:
            self.requests.append(recorded)
        return recorded

    def _authorized(self, handler: BaseHTTPRequestHandler) -> bool:
        if not self.required_token:
            return True
        auth = handler.headers.get("Authorization") or ""
        expected = f"Bearer {self.required_token}"
        return auth == expected

    def _valid_session(self, handler: BaseHTTPRequestHandler) -> bool:
        if not self.require_session:
            return True
        incoming = handler.headers.get("Mcp-Session-Id") or ""
        with self._lock:
            return incoming in self._sessions

    def _handle_delete(self, handler: BaseHTTPRequestHandler) -> None:
        incoming = handler.headers.get("Mcp-Session-Id") or ""
        raw = self._read_body(handler)
        if not incoming:
            self._record(handler, raw, None, 400)
            self._send_json(handler, 400, {"error": "missing Mcp-Session-Id"})
            return
        with self._lock:
            self._sessions.discard(incoming)
        self._record(handler, raw, None, 204)
        self._send(handler, 204, b"")

    def _handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        path = urlparse(handler.path).path
        body = b""
        if path.startswith("/audio/"):
            self._handle_audio_get(handler, path)
            return
        self._record(handler, body, None, 404)
        self._send_json(handler, 404, {"error": "not found"})

    def _handle_audio_get(self, handler: BaseHTTPRequestHandler, path: str) -> None:
        name = path.rsplit("/", 1)[-1]
        clip_id = name.rsplit(".", 1)[0]
        with self._lock:
            clip = self._clips.get(clip_id)
            behavior = dict((clip or {}).get("_audio_behavior") or {"mode": "ok"})
            has_audio = bool(clip and clip.get("audio_url"))
        if clip is None or not has_audio:
            self._record(handler, b"", None, 404)
            self._send_json(handler, 404, {"error": "audio not found"})
            return

        mode = str(behavior.get("mode") or "ok")
        if mode == "status":
            status = int(behavior.get("status") or 404)
            self._record(handler, b"", None, status)
            self._send_json(handler, status, {"error": f"audio http {status}"})
            return
        if mode == "html":
            html = behavior.get("body", HTML_AUDIO_BODY)
            if isinstance(html, str):
                html = html.encode("utf-8")
            self._record(handler, b"", None, 200)
            self._send(handler, 200, html, content_type="text/html")
            return
        if mode == "redirect":
            location = str(behavior.get("location") or DEFAULT_REDIRECT_LOCATION)
            self._record(handler, b"", None, 302)
            self._send(
                handler,
                302,
                b"",
                content_type="text/plain",
                extra_headers={"Location": location},
            )
            return
        if mode == "truncated":
            raw_body = behavior.get("body", FAKE_AUDIO_BYTES[:10])
            if isinstance(raw_body, str):
                raw_body = raw_body.encode("utf-8")
            declared = int(behavior.get("content_length") or (len(raw_body) + 1024))
            self._record(handler, b"", None, 200)
            self._send(
                handler,
                200,
                raw_body,
                content_type=FAKE_AUDIO_CONTENT_TYPE,
                content_length=declared,
            )
            return
        if mode == "large":
            size = int(behavior.get("size") or DEFAULT_LARGE_AUDIO_SIZE)
            self._record(handler, b"", None, 200)
            self._send_stream(handler, 200, size, content_type=FAKE_AUDIO_CONTENT_TYPE)
            return
        if mode == "slow":
            delay = float(behavior.get("delay") or self.timeout_delay)
            self._record(handler, b"", None, 200)
            self._interruptible_wait(delay)
            if self._stop_event.is_set():
                return
            self._send(
                handler,
                200,
                FAKE_AUDIO_BYTES,
                content_type=FAKE_AUDIO_CONTENT_TYPE,
            )
            return
        self._record(handler, b"", None, 200)
        self._send(
            handler,
            200,
            FAKE_AUDIO_BYTES,
            content_type=FAKE_AUDIO_CONTENT_TYPE,
        )

    def _handle_post(self, handler: BaseHTTPRequestHandler) -> None:
        raw = self._read_body(handler)
        try:
            payload = json.loads(raw.decode("utf-8") or "null")
        except json.JSONDecodeError:
            self._record(handler, raw, None, 400)
            self._send_json(
                handler,
                400,
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error"},
                },
            )
            return
        if not isinstance(payload, dict):
            self._record(handler, raw, None, 400)
            self._send_json(
                handler,
                400,
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "Invalid Request"},
                },
            )
            return

        method = str(payload.get("method") or "")
        rpc_id = payload.get("id")

        if method == "initialize":
            if self.auth_on_initialize and not self._authorized(handler):
                self._record(handler, raw, payload, 401)
                self._send_401(handler, rpc_id)
                return
            session_id = uuid.uuid4().hex
            with self._lock:
                self._sessions.add(session_id)
                self.session_id = session_id
            result = {
                "protocolVersion": DEFAULT_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "fake-suno-mcp", "version": "0.1.0"},
            }
            self._record(handler, raw, payload, 200)
            self._send_json(
                handler,
                200,
                {"jsonrpc": "2.0", "id": rpc_id, "result": result},
                extra_headers={"Mcp-Session-Id": session_id},
            )
            return

        if method == "notifications/initialized":
            self._record(handler, raw, payload, 202)
            self._send(handler, 202, b"")
            return

        if not self._authorized(handler):
            self._record(handler, raw, payload, 401)
            self._send_401(handler, rpc_id)
            return

        if method in {"tools/list", "tools/call"} and not self._valid_session(handler):
            self._record(handler, raw, payload, 404)
            self._send_json(
                handler,
                404,
                {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {
                        "code": -32000,
                        "message": "Session not found",
                    },
                },
            )
            return

        if method == "tools/list":
            self._record(handler, raw, payload, 200)
            self._send_json(
                handler,
                200,
                {"jsonrpc": "2.0", "id": rpc_id, "result": {"tools": self.tools}},
            )
            return

        if method == "tools/call":
            self._handle_tools_call(handler, raw, payload, rpc_id)
            return

        self._record(handler, raw, payload, 200)
        self._send_json(
            handler,
            200,
            {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            },
        )

    def _handle_tools_call(
        self,
        handler: BaseHTTPRequestHandler,
        raw: bytes,
        payload: dict[str, Any],
        rpc_id: Any,
    ) -> None:
        raw_params = payload.get("params")
        params = raw_params if isinstance(raw_params, dict) else {}
        tool_name = str(params.get("name") or "")
        raw_args = params.get("arguments")
        arguments = raw_args if isinstance(raw_args, dict) else {}

        if tool_name == "get_credits":
            self._record(handler, raw, payload, 200)
            text = json.dumps({"credits": self.credits})
            self._send_json(
                handler,
                200,
                {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "result": {
                        "content": [{"type": "text", "text": text}],
                    },
                },
            )
            return

        known = tool_name == self.generation_tool or (
            tool_name in GENERATION_TOOL_CANDIDATES
        )
        if not known:
            self._record(handler, raw, payload, 200)
            self._send_json(
                handler,
                200,
                {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {
                        "code": -32602,
                        "message": f"Unknown tool: {tool_name}",
                    },
                },
            )
            return

        scenario = self.next_scenario()
        if scenario == "401":
            self._record(handler, raw, payload, 401)
            self._send_401(handler, rpc_id)
            return
        if scenario == "402":
            self._record(handler, raw, payload, 402)
            self._send_json(
                handler,
                402,
                {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {
                        "code": 402,
                        "message": self._error_message("credits"),
                    },
                },
            )
            return
        if scenario in {"503", "500"}:
            status = int(scenario)
            self._record(handler, raw, payload, status)
            self._send_json(
                handler,
                status,
                {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {
                        "code": -32000,
                        "message": self._error_message("unavailable"),
                    },
                },
            )
            return
        if scenario == "timeout":
            # Registra antes da espera para o cliente que já desistiu
            # ainda conseguir inspecionar generation_calls().
            self._record(handler, raw, payload, 200)
            self._interruptible_wait(self.timeout_delay)
            if self._stop_event.is_set():
                return
            result = self._success_result(arguments, partial=False)
            self._send_json(
                handler,
                200,
                {"jsonrpc": "2.0", "id": rpc_id, "result": result},
            )
            return

        partial = scenario == "partial"
        result = self._success_result(arguments, partial=partial)
        self._record(handler, raw, payload, 200)
        self._send_json(
            handler,
            200,
            {"jsonrpc": "2.0", "id": rpc_id, "result": result},
        )

    def _success_result(
        self, arguments: dict[str, Any], *, partial: bool
    ) -> dict[str, Any]:
        import base64

        prompt = str(
            arguments.get("prompt")
            or arguments.get("style")
            or arguments.get("description")
            or ""
        )
        clips: list[dict[str, Any]] = []
        n_clips = max(0, int(self.clips_per_call))
        for index in range(n_clips):
            clip_id = f"clip-{uuid.uuid4().hex[:10]}"
            failed = partial and index == n_clips - 1
            clip: dict[str, Any] = {
                "id": clip_id,
                "title": prompt or f"fake-suno-{index + 1}",
                "status": "error" if failed else "complete",
                "prompt": prompt,
            }
            if failed:
                clip["audio_url"] = None
                clip["error"] = "sem áudio"
            else:
                clip["audio_url"] = self.audio_url(clip_id)
                if self.include_base64:
                    clip["audio_base64"] = base64.b64encode(FAKE_AUDIO_BYTES).decode(
                        "ascii"
                    )
                    clip["format"] = "mp3"
            clip["_audio_behavior"] = self._behavior_for_new_clip()
            clips.append(public_clip(clip))
            with self._lock:
                self._clips[clip_id] = clip

        payload = {"clips": clips}
        return {
            "content": [
                {"type": "text", "text": json.dumps(payload, ensure_ascii=False)}
            ]
        }


def parse_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    """Extrai o JSON de ``content[].text`` (formato MCP) ou devolve o dict."""
    if isinstance(result.get("content"), list):
        for part in result["content"]:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                try:
                    parsed = json.loads(part["text"])
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    return parsed
    return result


def clips_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = parse_tool_result(result)
    clips = data.get("clips")
    return list(clips) if isinstance(clips, list) else []
