"""Image tool contracts, local settings/log safety and secretary preferences."""

import base64
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from PIL import Image
from src.chat_tools import ChatTools, image_intent
from src.pia.service import WorkspaceService
from src.workspace_store import WorkspaceStore
from Plugins.Bot.secretaria import Secretary


class ChatToolTests(unittest.TestCase):
    def test_explicit_image_intent_and_non_actions(self):
        for text in (
            "Gere a imagem de uma garota de anime",
            "Crie uma imagem de uma casa",
            "Por favor, desenhe um gato",
            "Você pode gerar uma imagem de anime?",
            "Draw a cat",
        ):
            self.assertTrue(image_intent(text), text)
        for text in (
            "Como gerar uma imagem?",
            "Não gere uma imagem",
            "Crie um texto sobre imagem",
            "Gere um prompt para criar uma imagem",
            "Explique geração de imagens",
            "Olá",
        ):
            self.assertFalse(image_intent(text), text)

    def test_image_response_persisted_and_capability_revoked(self):
        stream = io.BytesIO()
        Image.new("RGB", (2, 2), "blue").save(stream, "PNG")
        session = Mock()
        session.post.return_value = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "data": [{"b64_json": base64.b64encode(stream.getvalue()).decode()}]
                }
            ),
        )
        with (
            TemporaryDirectory() as temporary,
            patch(
                "src.chat_tools.app_access.revoke",
                wraps=__import__("src.app_access", fromlist=["revoke"]).revoke,
            ) as revoke,
        ):
            tools = ChatTools(root=temporary, session=session)
            result = tools.execute("Gere uma imagem de teste")
            self.assertIn("](/api/pia/chat/assets/", result)
            self.assertEqual(len(list(Path(temporary).glob("*.png"))), 1)
            self.assertTrue(
                session.post.call_args.args[0].endswith("/v1/images/generations")
            )
            self.assertNotIn("Authorization", session.post.call_args.kwargs["headers"])
            revoke.assert_called_once()

    def test_failure_does_not_claim_an_image(self):
        session = Mock()
        session.post.return_value = Mock(
            status_code=503,
            json=Mock(return_value={"error": {"message": "Provider offline"}}),
        )
        with TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(RuntimeError, "503.*Provider offline"):
                ChatTools(root=temporary, session=session).generate_image("test")
            self.assertFalse(list(Path(temporary).iterdir()))

    def test_log_clear_truncates_only_selected_logs_and_blocks_escape(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs = root / "logs"
            logs.mkdir()
            (logs / "one.log").write_text("one")
            (logs / "two.log").write_text("two")
            outside = root / "other.log"
            outside.write_text("private")
            service = WorkspaceService(
                backend=SimpleNamespace(store=WorkspaceStore(root / "chat.sqlite"))
            )
            with patch("src.pia.service.BASE_DIR", root):
                with self.assertRaises(ValueError):
                    service.dispatch(
                        "POST", "/logs/clear", {"name": "../other.log"}, {}
                    )
                service.dispatch("POST", "/logs/clear", {"name": "one.log"}, {})
                self.assertEqual((logs / "one.log").read_text(), "")
                self.assertEqual((logs / "two.log").read_text(), "two")
                service.dispatch("POST", "/logs/clear", {"all": True}, {})
                self.assertEqual((logs / "two.log").read_text(), "")
                self.assertEqual(outside.read_text(), "private")

    def test_settings_omit_empty_plugins(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            empty = root / "empty"
            full = root / "full"
            empty.mkdir()
            full.mkdir()
            (full / ".env.example").write_text("EXAMPLE_KEY=")
            service = WorkspaceService(
                backend=SimpleNamespace(store=WorkspaceStore(root / "chat.sqlite"))
            )
            with (
                patch.object(
                    service,
                    "plugin_folders",
                    return_value=[("Apps/empty", empty), ("Plugins/full", full)],
                ),
                patch(
                    "src.settings_store.schema",
                    side_effect=lambda section: [
                        {"name": "KEY", "type": "secret", "default": ""}
                    ]
                    if section == "Plugins/full"
                    else [],
                ),
            ):
                self.assertEqual(
                    [s["id"] for s in service.settings()], ["Plugins/full"]
                )

    def test_secretary_readable_filters_custom_compatibility_and_colors(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = WorkspaceStore(root / "chat.sqlite")
            resources = Mock()
            resources.accounts.return_value = []
            bot = Secretary(resources, store, Mock(), config_path=root / "bot.json")
            bot.configure({"email_filter": "inbox_unread", "avatar_primary": "#123abc"})
            self.assertEqual(bot.config()["email_query"], "is:unread in:inbox")
            self.assertEqual(bot.config()["avatar_primary"], "#123abc")
            bot.configure({"email_query": "from:example@example.invalid"})
            self.assertEqual(bot.config()["email_filter"], "custom")
            with self.assertRaises(ValueError):
                bot.configure({"avatar_primary": "url(javascript:alert(1))"})

    def test_music_intent_parsing_and_fast_path_execution(self):
        from src.chat_tools import music_intent, parse_music_request

        self.assertTrue(music_intent("crie no suno uma musica sobre um dia alegre"))
        self.assertTrue(music_intent("criar musica no suno rock espacial"))
        self.assertTrue(music_intent("gerar musica instrumental calma"))
        self.assertFalse(music_intent("como gerar musica no suno?"))
        self.assertFalse(music_intent("explique o que e suno"))

        parsed = parse_music_request("crie no suno uma musica sobre um dia alegre")
        self.assertEqual(parsed["provider"], "suno_mcp")
        self.assertEqual(parsed["prompt"], "um dia alegre")
        self.assertIn("Alegre", parsed["style"])

        with TemporaryDirectory() as temporary:
            tools = ChatTools(root=temporary, session=Mock())
            with patch(
                "Plugins.Apps.music.service.generate",
                return_value={
                    "file": "alegre.mp3",
                    "url": "/api/pia/apps/music/files/alegre.mp3",
                    "provider": "suno_mcp",
                },
            ) as gen:
                out = tools.execute("crie no suno uma musica sobre um dia alegre")
            gen.assert_called_once_with(prompt="um dia alegre", provider="suno_mcp")
            self.assertIn("Música criada:", out)
            self.assertIn("/api/pia/apps/music/files/alegre.mp3", out)
            self.assertEqual(tools.last_meta["tools_used"], ["pia_music"])
            self.assertEqual(
                tools.last_meta["attachments"][0]["url"],
                "/api/pia/apps/music/files/alegre.mp3",
            )

            with patch(
                "Plugins.Apps.music.service.generate",
                side_effect=RuntimeError("Suno (MCP) não configurado."),
            ):
                err_out = tools.execute("crie no suno uma musica sobre um dia alegre")
            self.assertIn("Não foi possível concluir a geração musical", err_out)
            self.assertIn("Suno (MCP) não configurado", err_out)
            self.assertEqual(tools.last_meta, {"tools_used": ["pia_music"]})

    def test_desktop_backend_propagates_fast_path_meta_and_handles_llm_fallback_error(
        self,
    ):
        import threading
        from src.desktop_backend import DesktopBackend

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = WorkspaceStore(root / "chat.sqlite")
            chat_id = store.new_chat()
            backend = DesktopBackend.__new__(DesktopBackend)
            backend.store = store
            backend.chat_lock = threading.Lock()
            backend.agent = None
            backend.voice_stop = threading.Event()

            # Fast path propagates attachments/tools_used without touching LLM
            with patch(
                "Plugins.Apps.music.service.generate",
                return_value={
                    "file": "alegre.mp3",
                    "url": "/api/pia/apps/music/files/alegre.mp3",
                    "provider": "suno_mcp",
                },
            ):
                deltas = []
                res = backend.reply(
                    chat_id,
                    "crie no suno uma musica sobre um dia alegre",
                    on_delta=deltas.append,
                )
            self.assertIn("/api/pia/apps/music/files/alegre.mp3", res)
            self.assertEqual(backend._last_reply_meta["tools_used"], ["pia_music"])
            self.assertEqual(
                backend._last_reply_meta["attachments"][0]["type"], "audio"
            )
            self.assertTrue(deltas)

            # LLM failure in fallback returns friendly message instead of raising
            failing_agent = Mock()
            failing_agent.complete_stream.side_effect = RuntimeError(
                "Todos os modelos LLM selecionados falharam, estão em cooldown ou não possuem credenciais."
            )
            failing_agent.last_meta.return_value = {}
            backend.agent = failing_agent
            deltas2 = []
            res2 = backend.reply(
                chat_id,
                "ola tudo bem",
                on_delta=deltas2.append,
            )
            self.assertIn("Modelos de IA indisponíveis", res2)
            self.assertIn("Configurações", res2)
            self.assertEqual(deltas2, [res2])


if __name__ == "__main__":
    unittest.main()
