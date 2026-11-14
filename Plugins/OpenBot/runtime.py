"""Execução, cancelamento e delegação segura para Bots Dinâmicos (OpenBot)."""

from __future__ import annotations

import logging
import threading
import uuid
from typing import Any

from src.tts_service import get_tts_service
from .models import OpenBotError
from .service import OpenBotService, get_openbot_service

logger = logging.getLogger(__name__)

MAX_DELEGATION_DEPTH = 1
MAX_DELEGATION_CALLS_PER_RUN = 4
DELEGATION_TIMEOUT_SECONDS = 120


class OpenBotRuntime:
    def __init__(self, service: OpenBotService | None = None):
        self.service = service or get_openbot_service()
        self._lock = threading.RLock()
        self._active_runs: dict[str, dict[str, Any]] = {}
        self._request_runs: dict[str, dict[str, str]] = {}

    def has_active_run(self, bot_id: str) -> bool:
        with self._lock:
            return any(
                r["bot_id"] == bot_id and r["status"] == "running"
                for r in self._active_runs.values()
            )

    def _run_llm(
        self,
        bot_snapshot: dict[str, Any],
        input_text: str,
        cancel_ev: threading.Event,
        on_delta=None,
        agent_manager=None,
    ) -> str:
        if agent_manager is None:
            from src.agents.AgentManager import AgentManager

            mgr = AgentManager()
        else:
            mgr = agent_manager
        tier = str(bot_snapshot.get("llm_tier") or "free").strip()
        model = None if tier in ("", "free", "default") else tier
        system_prompt = (
            bot_snapshot.get("instructions")
            or f"Você é o bot {bot_snapshot.get('name', 'OpenBot')}."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": input_text},
        ]
        chunks: list[str] = []
        for delta in mgr.complete_stream(messages, model=model):
            if cancel_ev.is_set():
                raise InterruptedError("Execução cancelada.")
            if delta:
                chunks.append(delta)
                if on_delta is not None:
                    on_delta(delta)
        return "".join(chunks)

    def start_run(
        self,
        bot_id: str,
        *,
        chat_id: str | None = None,
        input_text: str,
        request_id: str | None = None,
        speak: bool = False,
        workspace_jobs: dict[str, Any] | None = None,
        agent_manager=None,
        depth: int = 0,
        visited: set[str] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(input_text, str) or not input_text.strip():
            raise OpenBotError("input é obrigatório.")
        if len(input_text) > 100_000:
            raise OpenBotError("input excede o limite permitido.")

        bot = self.service.get_bot(bot_id)
        if not bot.get("enabled", True):
            raise OpenBotError(
                "Bot dinâmico está desativado.", status=409, code="bot_disabled"
            )

        with self._lock:
            if request_id and request_id in self._request_runs:
                return dict(self._request_runs[request_id])

            run_id = uuid.uuid4().hex
            cancel_ev = threading.Event()
            from src.pia.service import Job

            job = Job(chat_id)
            job.plugin_identity = "OpenBot"
            job_id = job.id
            if workspace_jobs is not None:
                workspace_jobs[job_id] = job

            run_doc = {
                "run_id": run_id,
                "bot_id": bot_id,
                "chat_id": chat_id,
                "job_id": job_id,
                "status": "running",
                "result": None,
                "error": None,
                "depth": depth,
                "visited": sorted(set(visited or set()) | {bot_id}),
                "delegation_count": 0,
            }
            self._active_runs[run_id] = {
                **run_doc,
                "cancel_event": cancel_ev,
                "job": job,
                "bot_snapshot": bot,
            }
            self.service.repo.save_run(run_doc)
            if request_id:
                self._request_runs[request_id] = {"run_id": run_id, "job_id": job_id}

        def work():
            try:

                def on_delta(chunk: str):
                    if cancel_ev.is_set() or job.cancelled.is_set():
                        raise InterruptedError("Execução cancelada.")
                    job.emit("delta", text=chunk)

                result_text = self._run_llm(
                    bot,
                    input_text.strip(),
                    cancel_ev,
                    on_delta=on_delta,
                    agent_manager=agent_manager,
                )
                if cancel_ev.is_set() or job.cancelled.is_set():
                    raise InterruptedError("Execução cancelada.")
                with self._lock:
                    entry = self._active_runs.get(run_id)
                    if entry:
                        entry["status"] = "done"
                        entry["result"] = result_text
                run_doc["status"] = "done"
                run_doc["result"] = result_text
                self.service.repo.save_run(run_doc)
                job.emit("done", text=result_text)

                if speak and result_text.strip() and not cancel_ev.is_set():
                    try:
                        get_tts_service().speak(
                            result_text.strip(),
                            speaker_id=f"dynamic:{bot_id}",
                            bot_name=bot.get("name"),
                            avatar_url=bot.get("avatar_url"),
                            avatar_colors=bot.get("avatar_colors"),
                        )
                    except Exception:
                        logger.exception("Falha ao falar resposta do bot %s", bot_id)
            except InterruptedError:
                with self._lock:
                    entry = self._active_runs.get(run_id)
                    if entry:
                        entry["status"] = "cancelled"
                        entry["error"] = "Execução cancelada."
                run_doc["status"] = "cancelled"
                run_doc["error"] = "Execução cancelada."
                self.service.repo.save_run(run_doc)
                if job.status == "running":
                    job.emit("error", error="Execução cancelada.", code="cancelled")
            except Exception as exc:
                with self._lock:
                    entry = self._active_runs.get(run_id)
                    if entry:
                        entry["status"] = "error"
                        entry["error"] = str(exc)
                run_doc["status"] = "error"
                run_doc["error"] = str(exc)
                self.service.repo.save_run(run_doc)
                if job.status == "running":
                    job.emit("error", error=str(exc))

        threading.Thread(
            target=work, daemon=True, name=f"openbot-run-{bot_id[:8]}"
        ).start()
        return {"run_id": run_id, "job_id": job_id}

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            active = self._active_runs.get(run_id)
            if active:
                return {
                    "run_id": active["run_id"],
                    "bot_id": active["bot_id"],
                    "chat_id": active["chat_id"],
                    "job_id": active["job_id"],
                    "status": active["status"],
                    "result": active["result"],
                    "error": active["error"],
                }
        stored = self.service.repo.get_run(run_id)
        if not stored:
            raise OpenBotError("Execução não encontrada.", status=404, code="not_found")
        return {
            "run_id": stored["run_id"],
            "bot_id": stored["bot_id"],
            "chat_id": stored.get("chat_id"),
            "job_id": stored["job_id"],
            "status": stored["status"],
            "result": stored.get("result"),
            "error": stored.get("error"),
        }

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            active = self._active_runs.get(run_id)
            if active:
                active["cancel_event"].set()
                active["job"].cancelled.set()
                if active["status"] == "running":
                    active["status"] = "cancelled"
                    active["error"] = "Execução cancelada."
                    self.service.repo.save_run(
                        {
                            "run_id": active["run_id"],
                            "bot_id": active["bot_id"],
                            "chat_id": active["chat_id"],
                            "job_id": active["job_id"],
                            "status": "cancelled",
                            "result": active["result"],
                            "error": "Execução cancelada.",
                        }
                    )
        return self.get_run(run_id)

    def delegate_to_bot(
        self,
        *,
        parent_run_id: str | None = None,
        source_bot_id: str | None = None,
        target_bot_id: str,
        task: str,
        agent_manager=None,
    ) -> dict[str, Any]:
        depth = 0
        visited: set[str] = set()
        if parent_run_id:
            with self._lock:
                parent = self._active_runs.get(parent_run_id)
                if not parent:
                    raise OpenBotError(
                        "Run pai não encontrado.", status=404, code="not_found"
                    )
                depth = int(parent.get("depth", 0)) + 1
                if depth > MAX_DELEGATION_DEPTH:
                    raise OpenBotError(
                        "Profundidade máxima de delegação atingida.",
                        status=400,
                        code="delegation_limit",
                    )
                if parent.get("delegation_count", 0) >= MAX_DELEGATION_CALLS_PER_RUN:
                    raise OpenBotError(
                        "Limite de chamadas de delegação por execução atingido.",
                        status=400,
                        code="delegation_limit",
                    )
                visited = set(parent.get("visited") or [])
                if target_bot_id in visited:
                    raise OpenBotError(
                        "Ciclo de delegação detectado.",
                        status=400,
                        code="delegation_cycle",
                    )
                allowed_targets = parent["bot_snapshot"].get("delegation_targets") or []
                if target_bot_id not in allowed_targets:
                    raise OpenBotError(
                        "Bot alvo não autorizado para delegação.",
                        status=403,
                        code="forbidden",
                    )
                parent["delegation_count"] = parent.get("delegation_count", 0) + 1
        elif source_bot_id:
            src_bot = self.service.get_bot(source_bot_id)
            if target_bot_id not in (src_bot.get("delegation_targets") or []):
                raise OpenBotError(
                    "Bot alvo não autorizado para delegação.",
                    status=403,
                    code="forbidden",
                )
            visited = {source_bot_id}
            depth = 1

        started = self.start_run(
            target_bot_id,
            input_text=task,
            speak=False,
            agent_manager=agent_manager,
            depth=depth,
            visited=visited,
        )
        run_id = started["run_id"]
        # Aguarda conclusão respeitando timeout
        with self._lock:
            active = self._active_runs.get(run_id)
            job = active["job"] if active else None
        if job is not None:
            with job.changed:
                if job.status == "running":
                    job.changed.wait(timeout=DELEGATION_TIMEOUT_SECONDS)
            if job.status == "running":
                self.cancel_run(run_id)
                raise OpenBotError(
                    "Delegação expirou (timeout).", status=504, code="timeout"
                )
        return self.get_run(run_id)


_openbot_runtime: OpenBotRuntime | None = None
_runtime_lock = threading.Lock()


def get_openbot_runtime() -> OpenBotRuntime:
    global _openbot_runtime
    with _runtime_lock:
        if _openbot_runtime is None:
            _openbot_runtime = OpenBotRuntime()
        return _openbot_runtime
