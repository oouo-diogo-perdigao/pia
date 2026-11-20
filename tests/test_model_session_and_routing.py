"""Unit and integration tests for Demand 0002-C1 (100% mocked, no real credentials or paid calls)."""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import unittest

import requests

from Plugins.Connectors.agents import service as agents_service
from src import model_session
from src.desktop_backend import DesktopBackend
from src.pia.service import WorkspaceService
from src.workspace_store import WorkspaceStore


class _FakeVaultStore:
    def __init__(self, initial=None):
        self.data = dict(initial or {})

    def values(self, section):
        return dict(self.data)

    def save(self, section, updates):
        for k, v in updates.items():
            if v == "":
                self.data.pop(k, None)
            else:
                self.data[k] = v


class ModelSessionAndRoutingTests(unittest.TestCase):
    def _make_service(self, tmpdir: Path):
        store = WorkspaceStore(tmpdir / "workspace.sqlite3")
        backend = DesktopBackend.__new__(DesktopBackend)
        backend.notify = lambda *a, **kw: None
        backend.store = store
        backend.resources = SimpleNamespace(
            manifests=lambda: [], accounts=lambda *a: []
        )
        backend.secretary = SimpleNamespace(config=lambda: {}, poll=lambda: None)
        backend.chat_lock = threading.Lock()
        backend.voice_stop = threading.Event()
        backend.agent = None
        svc = WorkspaceService(backend=backend, apps=SimpleNamespace(public=lambda: []))
        return svc, store, backend

    def test_status_lists_7_providers_in_order_and_never_leaks_secrets(self):
        fake_vault = _FakeVaultStore(
            {"OPENROUTER_API_KEY": "sk-or-v1-supersecret-key-9999"}
        )
        with (
            TemporaryDirectory() as td,
            patch.object(model_session, "get_store", return_value=fake_vault),
            patch.object(
                model_session,
                "setting",
                side_effect=lambda k, d="": fake_vault.data.get(k, d),
            ),
            patch.object(
                agents_service,
                "login_status",
                return_value={
                    "status": "login_required",
                    "executable": None,
                    "detail": "",
                },
            ),
            patch.object(
                model_session,
                "verify_ollama",
                return_value=(
                    "not_installed",
                    "O Ollama não respondeu em http://localhost:11434. Abra o Ollama ou instale pelo site oficial.",
                    [],
                ),
            ),
        ):
            svc, _, _ = self._make_service(Path(td))
            payload = svc._dispatch("GET", "/models/status", {}, {})
            ids = [p["id"] for p in payload["providers"]]
            self.assertEqual(
                ids,
                ["codex", "agy", "openrouter", "gemini", "groq", "cloudflare", "local"],
            )
            serialized = json.dumps(payload, ensure_ascii=False)
            self.assertNotIn("sk-or-v1-supersecret-key-9999", serialized)
            openrouter = next(
                p for p in payload["providers"] if p["id"] == "openrouter"
            )
            self.assertTrue(openrouter["configured"])
            self.assertEqual(openrouter["status"], "connected")
            local = next(p for p in payload["providers"] if p["id"] == "local")
            self.assertEqual(local["status"], "not_installed")
            self.assertIn("http://localhost:11434", local["status_detail"])

    def test_openrouter_official_quota_and_iso_utc_timestamp_t3(self):
        fake_vault = _FakeVaultStore({"OPENROUTER_API_KEY": "sk-or-test-123456"})

        def fake_get(url, headers=None, timeout=None):
            resp = MagicMock()
            resp.status_code = 200
            if url.endswith("/credits"):
                resp.json.return_value = {
                    "data": {"total_credits": 20.0, "total_usage": 7.651}
                }
            else:
                resp.json.return_value = {"data": {}}
            return resp

        with (
            TemporaryDirectory() as td,
            patch.object(model_session, "get_store", return_value=fake_vault),
            patch.object(
                model_session,
                "setting",
                side_effect=lambda k, d="": fake_vault.data.get(k, d),
            ),
            patch.object(model_session.requests, "get", side_effect=fake_get),
            patch.object(
                agents_service,
                "login_status",
                return_value={
                    "status": "not_installed",
                    "executable": None,
                    "detail": "",
                },
            ),
            patch.object(
                model_session,
                "verify_ollama",
                return_value=("not_installed", "offline", []),
            ),
        ):
            svc, _, _ = self._make_service(Path(td))
            res = svc._dispatch("POST", "/models/quota", {"provider": "openrouter"}, {})
            quota = res["provider_quota"]
            self.assertTrue(quota["quota_available"])
            self.assertEqual(quota["quota_status"], "available")
            self.assertAlmostEqual(quota["quota_remaining"], 12.349, places=3)
            # Truncated to 2 decimals without rounding up: 12.349 -> 12,34
            self.assertEqual(quota["quota_label"], "US$ 12,34 disponíveis")
            self.assertRegex(
                quota["quota_checked_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
            )

            # Other providers must never invent quota
            for pid in ("codex", "agy", "gemini", "groq", "cloudflare", "local"):
                q = model_session.fetch_provider_quota(pid)
                self.assertFalse(q["quota_available"])
                self.assertEqual(q["quota_status"], "unavailable")
                self.assertIsNone(q["quota_checked_at"])
                self.assertTrue(
                    q["quota_label"].startswith("Saldo não informado pelo provedor")
                )

    def test_openrouter_quota_error_returns_literal_unavailable_label(self):
        fake_vault = _FakeVaultStore({"OPENROUTER_API_KEY": "sk-or-test-123456"})
        with (
            patch.object(
                model_session,
                "setting",
                side_effect=lambda k, d="": fake_vault.data.get(k, d),
            ),
            patch.object(
                model_session.requests,
                "get",
                side_effect=requests.RequestException("network down"),
            ),
        ):
            q = model_session.fetch_provider_quota("openrouter")
            self.assertFalse(q["quota_available"])
            self.assertEqual(q["quota_status"], "error")
            self.assertEqual(q["quota_label"], "Saldo não informado pelo provedor")
            self.assertRegex(
                q["quota_checked_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
            )

    def test_connect_and_disconnect_api_key_lightweight_ux04(self):
        fake_vault = _FakeVaultStore()

        def fake_get(url, headers=None, timeout=None):
            resp = MagicMock()
            if headers and headers.get("Authorization") == "Bearer gsk_valid_key":
                resp.status_code = 200
            else:
                resp.status_code = 401
            return resp

        with (
            TemporaryDirectory() as td,
            patch.object(model_session, "get_store", return_value=fake_vault),
            patch.object(
                model_session,
                "setting",
                side_effect=lambda k, d="": fake_vault.data.get(k, d),
            ),
            patch.object(model_session.requests, "get", side_effect=fake_get),
            patch.object(
                agents_service,
                "login_status",
                return_value={
                    "status": "not_installed",
                    "executable": None,
                    "detail": "",
                },
            ),
            patch.object(
                model_session,
                "verify_ollama",
                return_value=("not_installed", "offline", []),
            ),
        ):
            svc, _, _ = self._make_service(Path(td))
            with self.assertRaises(ValueError) as bad:
                svc._dispatch(
                    "POST",
                    "/models/connect",
                    {"provider": "groq", "api_key": "gsk_wrong_secret"},
                    {},
                )
            self.assertNotIn("gsk_wrong_secret", str(bad.exception))
            self.assertNotIn("GROQ_API_KEY", fake_vault.data)

            ok = svc._dispatch(
                "POST",
                "/models/connect",
                {"provider": "groq", "api_key": "gsk_valid_key"},
                {},
            )
            self.assertTrue(ok["ok"])
            self.assertEqual(ok["provider"]["status"], "connected")
            self.assertEqual(fake_vault.data["GROQ_API_KEY"], "gsk_valid_key")

            disc = svc._dispatch("POST", "/models/disconnect", {"provider": "groq"}, {})
            self.assertEqual(disc["provider"]["status"], "login_required")
            self.assertNotIn("GROQ_API_KEY", fake_vault.data)

    def test_session_usage_reset_t4_preserves_sqlite_history(self):
        with (
            TemporaryDirectory() as td,
            patch.object(
                agents_service,
                "login_status",
                return_value={
                    "status": "not_installed",
                    "executable": None,
                    "detail": "",
                },
            ),
            patch.object(
                model_session,
                "verify_ollama",
                return_value=("not_installed", "offline", []),
            ),
        ):
            svc, store, _ = self._make_service(Path(td))
            chat_id = store.new_chat()
            store.append(chat_id, "user", "Oi")
            store.append(chat_id, "assistant", "Olá!")

            tracker = svc._model_session()
            tracker.record_usage("codex")  # CLI without tokens
            tracker.record_usage("openrouter", 10, 25, 35)
            self.assertEqual(tracker.snapshot_usage("codex")["requests"], 1)
            self.assertFalse(tracker.snapshot_usage("codex")["tokens_reported"])
            self.assertEqual(tracker.snapshot_usage("openrouter")["total_tokens"], 35)
            self.assertTrue(tracker.snapshot_usage("openrouter")["tokens_reported"])

            res1 = svc._dispatch("POST", "/models/reset-session", {}, {})
            self.assertEqual(res1, {"ok": True})
            self.assertEqual(tracker.total_requests(), 0)
            self.assertEqual(tracker.snapshot_usage("openrouter")["total_tokens"], 0)
            # History remains intact
            self.assertEqual(len(store.messages(chat_id)), 2)

            tracker.record_usage("groq", 5, 5, 10)
            res2 = svc._dispatch("POST", "/integrations/agents/reset-session", {}, {})
            self.assertEqual(res2, {"ok": True})
            self.assertEqual(tracker.total_requests(), 0)

    def test_cancel_contract_t5_with_and_without_partial_text(self):
        with TemporaryDirectory() as td:
            svc, store, backend = self._make_service(Path(td))
            chat_id = store.new_chat()

            # Case 1: cancel before any delta -> no empty assistant message
            started = threading.Event()

            def slow_empty_reply(chat, text, on_delta=None, cancel_event=None):
                started.set()
                while not (cancel_event and cancel_event.is_set()):
                    time.sleep(0.01)
                raise InterruptedError("Resposta interrompida.")

            backend.reply = slow_empty_reply
            job_id = svc.send(chat_id, "Primeira pergunta")
            self.assertTrue(started.wait(2))
            svc._dispatch("POST", "/chat/cancel", {"job": job_id}, {})
            job = svc.jobs[job_id]
            with job.changed:
                if job.status == "running":
                    job.changed.wait(2)
            self.assertEqual(job.status, "done")
            self.assertTrue(
                any(
                    e.get("type") == "done" and e.get("cancelled") is True
                    for e in job.events
                )
            )
            self.assertEqual(
                store.messages(chat_id),
                [{"role": "user", "content": "Primeira pergunta"}],
            )

            # Case 2: cancel after partial delta -> single assistant with partial text
            partial_sent = threading.Event()

            def slow_partial_reply(chat, text, on_delta=None, cancel_event=None):
                on_delta("Parcial ")
                partial_sent.set()
                while not (cancel_event and cancel_event.is_set()):
                    time.sleep(0.01)
                on_delta("ignorado")

            backend.reply = slow_partial_reply
            job_id2 = svc.send(chat_id, "Segunda pergunta")
            self.assertTrue(partial_sent.wait(2))
            svc._dispatch("POST", "/chat/cancel", {"job": job_id2}, {})
            job2 = svc.jobs[job_id2]
            with job2.changed:
                if job2.status == "running":
                    job2.changed.wait(2)
            self.assertEqual(job2.status, "done")
            self.assertTrue(
                any(
                    e.get("type") == "done" and e.get("cancelled") is True
                    for e in job2.events
                )
            )
            msgs = store.messages(chat_id)
            self.assertEqual(
                msgs,
                [
                    {"role": "user", "content": "Primeira pergunta"},
                    {"role": "user", "content": "Segunda pergunta"},
                    {"role": "assistant", "content": "Parcial "},
                ],
            )
            self.assertEqual(svc._model_session().total_requests(), 0)

    def test_explicit_provider_no_silent_fallback_rn0002_08(self):
        with (
            TemporaryDirectory() as td,
            patch.object(
                agents_service,
                "login_status",
                return_value={
                    "status": "login_required",
                    "executable": "codex.exe",
                    "detail": "",
                },
            ),
            patch.object(agents_service, "ask") as mock_ask,
        ):
            svc, store, backend = self._make_service(Path(td))
            chat_id = store.new_chat()
            svc._dispatch(
                "POST",
                "/chat/model",
                {"chat": chat_id, "provider": "codex", "model": "codex"},
                {},
            )
            msgs_res = svc._dispatch("GET", "/chat/messages", {}, {"chat": [chat_id]})
            self.assertEqual(
                msgs_res["model_selection"], {"provider": "codex", "model": "codex"}
            )

            with self.assertRaisesRegex(RuntimeError, "login"):
                backend.reply(chat_id, "Olá")
            mock_ask.assert_not_called()

    def test_cli_ask_with_cancel_event_terminates_popen(self):
        cancel_ev = threading.Event()
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        fake_proc.pid = 99999
        fake_proc.stdin = MagicMock()

        def set_cancel_soon():
            time.sleep(0.05)
            cancel_ev.set()

        with (
            TemporaryDirectory() as td,
            patch.object(agents_service, "BASE_DIR", Path(td)),
            patch.object(agents_service, "executable", return_value="codex.exe"),
            patch.object(agents_service.subprocess, "Popen", return_value=fake_proc),
            patch.object(agents_service, "_terminate_process") as term_mock,
        ):
            threading.Thread(target=set_cancel_soon, daemon=True).start()
            with self.assertRaises(InterruptedError):
                agents_service.ask(
                    "codex", "Teste cancelamento", cancel_event=cancel_ev
                )
            term_mock.assert_called_once_with(fake_proc)

    def test_retrocompatibility_integrations_agents_status(self):
        with (
            TemporaryDirectory() as td,
            patch.object(agents_service, "executable", return_value="fixture.exe"),
        ):
            svc, _, _ = self._make_service(Path(td))
            res = svc._dispatch("GET", "/integrations/agents/status", {}, {})
            self.assertEqual(set(res.keys()), {"codex", "agy"})
            self.assertTrue(res["codex"]["available"])

    def test_default_models_and_explicit_candidate_outside_llm_providers(self):
        fake_vault = _FakeVaultStore(
            {
                "OPENROUTER_API_KEY": "sk-or-test-explicit",
                "CLOUDFLARE_API_TOKEN": "cf-test-token",
            }
        )
        with (
            TemporaryDirectory() as td,
            patch.object(model_session, "get_store", return_value=fake_vault),
            patch.object(
                model_session,
                "setting",
                side_effect=lambda k, d="": fake_vault.data.get(k, d),
            ),
            patch(
                "src.llm_routing.setting",
                side_effect=lambda k, d="": fake_vault.data.get(k, d),
            ),
            patch.object(
                agents_service,
                "login_status",
                return_value={
                    "status": "not_installed",
                    "executable": None,
                    "detail": "",
                },
            ),
            patch.object(
                model_session,
                "verify_ollama",
                return_value=("not_installed", "offline", []),
            ),
        ):
            svc, _, _ = self._make_service(Path(td))
            payload = svc._dispatch("GET", "/models/status", {}, {})
            openrouter = next(
                p for p in payload["providers"] if p["id"] == "openrouter"
            )
            cloudflare = next(
                p for p in payload["providers"] if p["id"] == "cloudflare"
            )
            self.assertGreater(len(openrouter["models"]), 0)
            self.assertGreater(len(cloudflare["models"]), 0)

            candidate = model_session.explicit_model_candidate(
                "openrouter/openai/gpt-4o-mini"
            )
            self.assertIsNotNone(candidate)
            self.assertEqual(candidate.provider, "openrouter")
            self.assertEqual(candidate.model, "openrouter/openai/gpt-4o-mini")
            self.assertEqual(
                candidate.params(),
                {
                    "model": "openrouter/openai/gpt-4o-mini",
                    "api_key": "sk-or-test-explicit",
                },
            )

            cf_candidate = model_session.explicit_model_candidate("cloudflare")
            self.assertIsNotNone(cf_candidate)
            self.assertEqual(cf_candidate.provider, "cloudflare")
            self.assertEqual(cf_candidate.params()["api_key"], "cf-test-token")


if __name__ == "__main__":
    unittest.main()
