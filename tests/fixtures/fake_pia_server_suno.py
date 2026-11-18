"""Fake pia-server (device API) for the Suno/music T6 tests. Loopback only.

Follows the real routes of pia-server ``0a1fee6`` (T2: status, connect,
attempt, DELETE account, capability ``suno:3``, 401 ``{error}`` without code
for an unpaired device) plus the v3 final contract for jobs, history and the
audio proxy (T4/T5/T5b, still being implemented on the server):

* ``GET  /device/account`` -> ``{..., capabilities: ["suno:3"]}``
* ``GET  /device/suno/status`` -> ``{accounts, default_account_id, active_job, settings}``
* ``POST /device/suno/connect`` -> ``{url, attempt_id, expires_in}``
* ``GET  /device/suno/connect/:id`` -> ``{state, account_id?, code?}``
* ``DELETE /device/suno/accounts/:id`` / ``PATCH /device/suno/accounts/:id {label}``
* ``POST /device/suno/jobs`` -> 202 ``{job_id, state, total, generation_id}``
* ``GET  /device/suno/jobs/:id`` / ``POST /device/suno/jobs/:id/cancel``
* ``GET|POST /device/music/generations``, ``DELETE /device/music/generations/:id``
* ``GET  /device/music/generations/:id/tracks/:n/audio`` (proxy, 410 when dead)

No real Suno or pia-server is ever called. The fake Suno token below lives
only here: it is never sent to the device, and tests scan for it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import threading
from typing import Any
from urllib.parse import parse_qs, urlsplit
import uuid

DEVICE_TOKEN = "D" * 43
OTHER_DEVICE_TOKEN = "E" * 43
SUNO_SECRET = "fake-suno-access-token-NEVER-ON-DEVICE"
SUNO_AUDIO_LINK = (
    "https://cdn1.suno.ai/fake-signed-link?X-Amz-Signature=fake-suno-signature"
)
SETTINGS = {"max_count": 10, "duration": [10, 180], "instrumental": True}
UNPAIRED = {"error": "Pareamento inválido."}
TERMINAL = {"completed", "failed", "interrupted", "cancelled"}


def account(identity=None, label="conta@suno", *, available=True, state=None):
    state = state or ("configured" if available else "refresh_failed")
    return {
        "id": identity or str(uuid.uuid4()),
        "label": label,
        "email": label if "@" in label else None,
        "name": None,
        "credential_state": state,
        "available": state == "configured",
        "expires_at": "2026-11-18T12:00:00.000Z" if state == "configured" else None,
        "scopes": "music" if state == "configured" else None,
    }


def audio_bytes(generation_id: str, n: int) -> bytes:
    return b"ID3" + f"{generation_id}:{n}".encode() * 50


def plan_success(count: int, *, extra: int = 0, steps: int = 2) -> list[dict[str, Any]]:
    """Snapshots: queued -> running (first track) -> completed."""
    tracks = [
        {"n": n, "title": f"Faixa {n}", "duration": 30, "extra": False}
        for n in range(1, count + 1)
    ]
    tracks += [
        {"n": count + i, "title": f"Extra {i}", "duration": 30, "extra": True}
        for i in range(1, extra + 1)
    ]
    snapshots = [{"state": "queued", "tracks": []}]
    if steps > 1:
        snapshots.append({"state": "running", "tracks": tracks[:1]})
    snapshots.append({"state": "completed", "tracks": tracks})
    return snapshots


def plan_partial(
    ready: int, total: int, code: str = "suno_unavailable", *, extra: int = 0
):
    tracks = [
        {"n": n, "title": f"Faixa {n}", "duration": 30, "extra": False}
        for n in range(1, ready + 1)
    ]
    tracks += [
        {"n": ready + i, "title": f"Extra {i}", "duration": 30, "extra": True}
        for i in range(1, extra + 1)
    ]
    return [
        {"state": "running", "tracks": tracks[:1]},
        {"state": "failed", "code": code, "tracks": tracks},
    ]


class FakePiaServerSuno:
    def __init__(self):
        self.lock = threading.RLock()
        self.devices = {DEVICE_TOKEN: "device-a", OTHER_DEVICE_TOKEN: "device-b"}
        self.capabilities = ["suno:3"]
        self.accounts: list[dict[str, Any]] = [account(label="diogo@suno")]
        self.attempts: dict[str, dict[str, Any]] = {}
        self.attempt_outcome: dict[str, Any] = {"state": "pending"}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.generations: list[dict[str, Any]] = []
        self.next_plan: list[dict[str, Any]] | None = None
        self.hold: dict[int, threading.Event] = {}  # step index -> gate
        self.offline = threading.Event()  # 503 on every /device route
        self.job_conflict = False  # POST jobs -> 409 suno_job_active
        self.dead_tracks: set[tuple[str, int]] = set()
        self.bad_sha: set[tuple[str, int]] = set()
        self.requests: list[tuple[str, str, Any]] = []
        self.polled = threading.Condition(self.lock)
        self.poll_count = 0
        self.server = None
        self.thread = None

    # -- lifecycle ---------------------------------------------------------
    def __enter__(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def handle_one(self, method):
                fake.dispatch(self, method)

            def do_GET(self):
                self.handle_one("GET")

            def do_POST(self):
                self.handle_one("POST")

            def do_DELETE(self):
                self.handle_one("DELETE")

            def do_PATCH(self):
                self.handle_one("PATCH")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(
            target=self.server.serve_forever, name="fake-pia-server"
        )
        self.thread.daemon = True
        self.thread.start()
        return self

    def __exit__(self, *exc):
        for gate in self.hold.values():
            gate.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(10)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    # -- helpers for tests ---------------------------------------------------
    def calls(self, method=None, prefix=""):
        with self.lock:
            return [
                r
                for r in self.requests
                if (method is None or r[0] == method) and r[1].startswith(prefix)
            ]

    def wait_polls(self, count: int, timeout: float = 10) -> bool:
        with self.polled:
            return self.polled.wait_for(
                lambda: self.poll_count >= count, timeout=timeout
            )

    def add_generation(self, **fields) -> dict[str, Any]:
        item = {
            "id": str(uuid.uuid4()),
            "client_id": str(uuid.uuid4()),
            "source": "suno",
            "provider": "suno_mcp",
            "device_id": "device-a",
            "suno_account": {
                "id": self.accounts[0]["id"],
                "name": self.accounts[0]["label"],
            },
            "prompt": "prompt",
            "lyrics": "",
            "count": 1,
            "duration": 30,
            "state": "completed",
            "code": None,
            "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "tracks": [
                {
                    "n": 1,
                    "title": "Faixa 1",
                    "duration": 30,
                    "extra": False,
                    "audio_url": SUNO_AUDIO_LINK,
                }
            ],
        }
        item.update(fields)
        with self.lock:
            self.generations.append(item)
        return item

    # -- dispatch ------------------------------------------------------------
    def dispatch(self, handler, method):
        url = urlsplit(handler.path)
        path = url.path
        length = int(handler.headers.get("Content-Length") or 0)
        raw = handler.rfile.read(length) if length else b""
        try:
            body = json.loads(raw) if raw else {}
        except ValueError:
            body = None
        with self.lock:
            self.requests.append(
                (method, path + (("?" + url.query) if url.query else ""), body)
            )
        if not path.startswith("/device/"):
            return self.send(handler, 404, {"error": "Não encontrado."})
        if self.offline.is_set():
            return self.send(handler, 503, {"error": "Indisponível."})
        auth = handler.headers.get("Authorization") or ""
        device = self.devices.get(auth.removeprefix("Bearer "))
        if not device or handler.headers.get("X-PIA-Protocol") != "1":
            return self.send(handler, 401, UNPAIRED)
        if body is None:
            return self.send(
                handler, 400, {"error": "Requisição inválida.", "code": "bad_request"}
            )
        query = parse_qs(url.query)
        try:
            status, payload, extra = self.route(method, path, body, query, device)
        except KeyError:
            status, payload, extra = (
                404,
                {"error": "Não encontrado.", "code": "not_found"},
                None,
            )
        if isinstance(payload, bytes):
            return self.send_bytes(handler, status, payload, extra or {})
        return self.send(handler, status, payload)

    def route(self, method, path, body, query, device):
        if method == "GET" and path == "/device/account":
            return (
                200,
                {
                    "name": "Diogo",
                    "email": "diogo@example.com",
                    "capabilities": list(self.capabilities),
                },
                None,
            )
        if path.startswith("/device/suno/") and "suno:3" not in self.capabilities:
            return 404, {"error": "Não encontrado."}, None
        if method == "GET" and path == "/device/suno/status":
            return 200, self.status(device), None
        if method == "POST" and path == "/device/suno/connect":
            replace = body.get("replace_account_id")
            if replace is not None and not any(
                a["id"] == replace for a in self.accounts
            ):
                return (
                    404,
                    {
                        "error": "Conta Suno não encontrada.",
                        "code": "suno_account_not_found",
                    },
                    None,
                )
            attempt = str(uuid.uuid4())
            with self.lock:
                self.attempts[attempt] = {"replace": replace}
            return (
                200,
                {
                    "url": f"https://auth.suno.com/authorize?state={attempt}",
                    "attempt_id": attempt,
                    "expires_in": 600,
                },
                None,
            )
        match = re.fullmatch(r"/device/suno/connect/([^/]+)", path)
        if method == "GET" and match:
            if match[1] not in self.attempts:
                return (
                    404,
                    {
                        "error": "Tentativa de conexão não encontrada.",
                        "code": "not_found",
                    },
                    None,
                )
            outcome = dict(self.attempt_outcome)
            if outcome.get("state") == "connected" and outcome.get("new_account"):
                with self.lock:
                    new = outcome.pop("new_account")
                    if not any(a["id"] == new["id"] for a in self.accounts):
                        self.accounts.append(new)
                    outcome["account_id"] = new["id"]
            outcome.pop("new_account", None)
            return 200, outcome, None
        match = re.fullmatch(r"/device/suno/accounts/([^/]+)", path)
        if match and method in ("DELETE", "PATCH"):
            found = next((a for a in self.accounts if a["id"] == match[1]), None)
            if found is None:
                return (
                    404,
                    {
                        "error": "Conta Suno não encontrada.",
                        "code": "suno_account_not_found",
                    },
                    None,
                )
            with self.lock:
                if method == "DELETE":
                    self.accounts.remove(found)
                    return 200, {"ok": True}, None
                label = body.get("label")
                if not isinstance(label, str) or not label.strip() or len(label) > 80:
                    return (
                        400,
                        {"error": "Apelido inválido.", "code": "bad_request"},
                        None,
                    )
                found["label"] = label.strip()
                return 200, {"ok": True, "account": dict(found)}, None
        if method == "POST" and path == "/device/suno/jobs":
            return self.create_job(body, device)
        match = re.fullmatch(r"/device/suno/jobs/([^/]+)(/cancel)?", path)
        if match:
            job = self.jobs[match[1]]
            if match[2] and method == "POST":
                with self.lock:
                    job["cancel"] = True
                return 200, {"ok": True}, None
            if method == "GET":
                return 200, self.snapshot(job), None
        if path == "/device/music/generations":
            if method == "POST":
                return self.record_local(body, device)
            if method == "GET":
                return 200, self.history(query, device), None
        match = re.fullmatch(r"/device/music/generations/([^/]+)", path)
        if match and method == "DELETE":
            with self.lock:
                found = next((g for g in self.generations if g["id"] == match[1]), None)
                if found is None:
                    return 404, {"error": "Não encontrado.", "code": "not_found"}, None
                self.generations.remove(found)  # hard delete (v3.2)
            return 200, {"ok": True}, None
        match = re.fullmatch(
            r"/device/music/generations/([^/]+)/tracks/(\d+)/audio", path
        )
        if match and method == "GET":
            gid, n = match[1], int(match[2])
            found = next((g for g in self.generations if g["id"] == gid), None)
            if found is None or not any(t["n"] == n for t in found.get("tracks") or []):
                return 404, {"error": "Não encontrado.", "code": "not_found"}, None
            if (gid, n) in self.dead_tracks:
                return (
                    410,
                    {
                        "error": "Esta música não está mais disponível no Suno.",
                        "code": "suno_track_unavailable",
                    },
                    None,
                )
            data = audio_bytes(gid, n)
            digest = sha256(b"x" if (gid, n) in self.bad_sha else data).hexdigest()
            return 200, data, {"Content-Type": "audio/mpeg", "X-Content-SHA256": digest}
        return 404, {"error": "Não encontrado.", "code": "not_found"}, None

    # -- state ---------------------------------------------------------------
    def status(self, device):
        usable = [a for a in self.accounts if a["available"]]
        active = None
        for job in self.jobs.values():
            snap = self.peek(job)
            if snap["state"] not in TERMINAL:
                active = {
                    "job_id": job["id"],
                    "generation_id": job["generation_id"],
                    "client_id": job["client_job_id"],
                    "state": snap["state"],
                    "this_device": job["device"] == device,
                    "suno_account_id": job["suno_account_id"],
                    "completed": snap["completed"],
                    "total": snap["total"],
                    "extra_ready": snap["extra_ready"],
                }
        return {
            "accounts": [dict(a) for a in self.accounts],
            "default_account_id": usable[0]["id"] if len(usable) == 1 else None,
            "active_job": active,
            "settings": dict(SETTINGS),
        }

    def create_job(self, body, device):
        usable = [a for a in self.accounts if a["available"]]
        if self.job_conflict or any(
            self.peek(j)["state"] not in TERMINAL for j in self.jobs.values()
        ):
            return (
                409,
                {
                    "error": "Já há uma geração do Suno em andamento nesta conta. Aguarde terminar.",
                    "code": "suno_job_active",
                },
                None,
            )
        account_id = body.get("suno_account_id")
        if account_id is None:
            if len(usable) > 1:
                return (
                    400,
                    {"error": "Escolha a conta Suno.", "code": "suno_account_required"},
                    None,
                )
            if not usable:
                return (
                    400,
                    {
                        "error": "Conecte uma conta Suno na PIA Server.",
                        "code": "suno_not_connected",
                    },
                    None,
                )
            account_id = usable[0]["id"]
        chosen = next((a for a in self.accounts if a["id"] == account_id), None)
        if chosen is None:
            return (
                400,
                {
                    "error": "Conecte uma conta Suno na PIA Server.",
                    "code": "suno_not_connected",
                },
                None,
            )
        if not chosen["available"]:
            return (
                400,
                {
                    "error": "A conexão com o Suno expirou.",
                    "code": "suno_credential_expired",
                },
                None,
            )
        count = body.get("count")
        plan = self.next_plan or plan_success(count)
        self.next_plan = None
        job_id, generation_id = str(uuid.uuid4()), str(uuid.uuid4())
        job = {
            "id": job_id,
            "generation_id": generation_id,
            "device": device,
            "client_job_id": body.get("client_job_id"),
            "suno_account_id": account_id,
            "total": count,
            "plan": plan,
            "step": 0,
            "cancel": False,
            "body": body,
        }
        created = datetime.now(timezone.utc) + timedelta(seconds=len(self.generations))
        with self.lock:
            self.jobs[job_id] = job
            self.generations.append(
                {
                    "id": generation_id,
                    "client_id": body.get("client_job_id"),
                    "source": "suno",
                    "provider": "suno_mcp",
                    "device_id": device,
                    "suno_account": {"id": account_id, "name": chosen["label"]},
                    "prompt": body.get("prompt"),
                    "lyrics": body.get("lyrics"),
                    "count": count,
                    "duration": body.get("duration"),
                    "state": "queued",
                    "code": None,
                    "created": created.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                    "tracks": [],
                    "job": job_id,
                }
            )
        return (
            202,
            {
                "job_id": job_id,
                "state": "queued",
                "total": count,
                "generation_id": generation_id,
            },
            None,
        )

    def peek(self, job):
        step = job["plan"][min(job["step"], len(job["plan"]) - 1)]
        tracks = [dict(t) for t in step.get("tracks", [])]
        state = step["state"]
        if job["cancel"] and state not in TERMINAL:
            state = "cancelled"
        regular = sum(1 for t in tracks if not t["extra"])
        return {
            "job_id": job["id"],
            "generation_id": job["generation_id"],
            "state": state,
            "code": step.get("code"),
            "completed": regular,
            "total": job["total"],
            "extra_ready": len(tracks) - regular,
            "ready_text": "informativo",
            "tracks": tracks,
        }

    def snapshot(self, job):
        gate = self.hold.get(job["step"])
        snap = self.peek(job)
        with self.lock:
            if (
                (gate is None or gate.is_set())
                and job["step"] < len(job["plan"]) - 1
                and snap["state"] not in TERMINAL
            ):
                job["step"] += 1
            for item in self.generations:
                if item.get("job") == job["id"]:
                    item["state"] = snap["state"]
                    item["code"] = snap["code"]
                    item["tracks"] = [
                        {**t, "audio_url": SUNO_AUDIO_LINK} for t in snap["tracks"]
                    ]
        with self.polled:
            self.poll_count += 1
            self.polled.notify_all()
        return snap

    def record_local(self, body, device):
        if body.get("source") != "local" or any(
            key in body for key in ("audio", "audio_url", "file", "path", "data")
        ):
            return 400, {"error": "Registro inválido.", "code": "bad_request"}, None
        with self.lock:
            found = next(
                (
                    g
                    for g in self.generations
                    if g["client_id"] == body.get("client_id")
                ),
                None,
            )
            if found is None:
                found = {
                    "id": str(uuid.uuid4()),
                    "client_id": body.get("client_id"),
                    "source": "local",
                    "provider": body.get("provider"),
                    "device_id": device,
                    "suno_account": None,
                    "prompt": body.get("prompt"),
                    "lyrics": body.get("lyrics"),
                    "count": body.get("count"),
                    "duration": body.get("duration"),
                    "state": body.get("state"),
                    "code": body.get("code"),
                    "created": body.get("created"),
                    "tracks": [],
                }
                self.generations.append(found)
        return 200, {"id": found["id"]}, None

    def history(self, query, device):
        limit = int((query.get("limit") or ["100"])[0])
        offset = int((query.get("cursor") or ["0"])[0] or 0)
        with self.lock:
            items = sorted(
                self.generations, key=lambda g: g.get("created") or "", reverse=True
            )
            items.sort(key=lambda g: g.get("state") not in ("queued", "running"))
            page = items[offset : offset + limit]
            out = []
            for g in page:
                public = {k: v for k, v in g.items() if k not in ("job",)}
                public["tracks"] = [
                    {k: v for k, v in t.items() if k != "audio_url"}
                    for t in g.get("tracks") or []
                ]
                public["from_this_device"] = g["device_id"] == device
                out.append(public)
        return {
            "items": out,
            "next_cursor": str(offset + limit) if offset + limit < len(items) else None,
        }

    # -- io ----------------------------------------------------------------
    @staticmethod
    def send(handler, status, payload):
        data = json.dumps(payload).encode()
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)

    @staticmethod
    def send_bytes(handler, status, data, headers):
        handler.send_response(status)
        for key, value in headers.items():
            handler.send_header(key, value)
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)
