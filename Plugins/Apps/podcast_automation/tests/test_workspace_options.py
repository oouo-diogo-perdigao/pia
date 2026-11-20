from src.settings_store import get_store, save_document, document

"""Persistence and published reader contracts, without accessing external accounts."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from Plugins.Apps.podcast_automation import web_api
from podcast_automation import notification
from podcast_automation.transcripts_page import render

EXAMPLE = json.loads(
    (
        Path(__file__).resolve().parents[1] / "docs/examples/config.example.json"
    ).read_text(encoding="utf-8")
)


class WorkspaceOptionsTests(unittest.TestCase):
    def test_selected_folder_and_bucket_survive_reload_and_campaign_save(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            save_document("Apps/podcast_automation/campaigns", copy.deepcopy(EXAMPLE))
            with patch.object(web_api, "ROOT", root):
                stale = web_api.handle("config", {}, None)
                options = {
                    "google_account": "work",
                    "google_folder": "nested-folder",
                    "google_folder_name": "Gravações RPG",
                    "storage_account": "r2-work",
                    "storage_bucket": "podcasts",
                }
                web_api.handle(
                    "save-options",
                    {"outputs": {"txt": True}, "integrations": options},
                    None,
                )
                reloaded = web_api.handle("config", {}, None)
                self.assertEqual(
                    reloaded["integrations"],
                    {**EXAMPLE.get("integrations", {}), **options},
                )
                # Even an editor opened before selecting the folder cannot revert it.
                stale["processing"]["fixture_change"] = True
                web_api.handle("save-config", {"value": stale}, None)
                saved = web_api.handle("config", {}, None)
                self.assertEqual(
                    saved["integrations"]["google_folder"], "nested-folder"
                )
                self.assertEqual(saved["integrations"]["google_account"], "work")
                self.assertEqual(saved["integrations"]["storage_bucket"], "podcasts")
                self.assertTrue(saved["processing"]["fixture_change"])

    def test_discord_announcement_contains_only_available_published_links(self):
        links = {
            "MP3": "https://example.invalid/audio.mp3",
            "Transcrição TXT": "https://example.invalid/audio.txt",
            "RSS": "https://example.invalid/rss.xml",
            "Transcrições gerais": "https://example.invalid/transcripts.html",
        }
        with (
            patch.object(
                notification,
                "get_config",
                return_value={
                    "integrations": {
                        "discord_notify": True,
                        "discord_channels": ["123", "456"],
                    }
                },
            ),
            patch("Plugins.Connectors.discord.service.Discord") as bot,
        ):
            self.assertTrue(
                notification.announce_publication("Sessão", "Campanha", links)
            )
            self.assertEqual(bot.return_value.send.call_count, 2)
            for call in bot.return_value.send.call_args_list:
                self.assertEqual(
                    call.args[0],
                    "Campanha - Sessão\nMP3: "
                    + links["MP3"]
                    + "\nRSS: "
                    + links["RSS"]
                    + "\nTRANSCRIÇÃO: "
                    + links["Transcrições gerais"],
                )

    def test_taverns_selection_persists_and_publishes_links(self):
        destination = (
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        )
        save_document("Apps/podcast_automation/campaigns", copy.deepcopy(EXAMPLE))
        with self.assertRaisesRegex(ValueError, "Selecione pelo menos um canal"):
            web_api.handle(
                "save-options", {"integrations": {"taverns_notify": True}}, None
            )
        web_api.handle(
            "save-options",
            {
                "integrations": {
                    "taverns_notify": True,
                    "taverns_channels": [destination],
                },
            },
            None,
        )
        with patch("Plugins.Connectors.taverns.service.Taverns") as bot:
            self.assertTrue(
                notification.announce_publication(
                    "Sessão",
                    "Campanha",
                    {"MP3": "https://example.invalid/episodio.mp3"},
                    season=1,
                    number=2,
                )
            )
            bot.return_value.send.assert_called_once_with(
                "Campanha - S01E02 - Sessão\nMP3: https://example.invalid/episodio.mp3",
                destination,
            )

    def test_reader_contains_every_transcript_with_escaped_content_and_tools(self):
        episodes = [
            dict(
                title="Sessão <1>",
                content="Fala única " + str(i) + '\n<script>alert("bad")</script>',
            )
            for i in range(3)
        ]
        page = render(
            episodes, "https://example.invalid/cover.png", {"title": "Mesa <RPG>"}
        )
        self.assertEqual(page.count('class="transcript"'), 3)
        for i in range(3):
            self.assertIn("Fala única " + str(i), page)
        self.assertNotIn('<script>alert("bad")</script>', page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn('id="search"', page)
        self.assertIn('id="copy-selected"', page)
        self.assertIn('aria-label="Sessões"', page)
        self.assertIn("session-3", page)
        self.assertNotIn("<script src=", page)

    def test_discord_splits_long_announcements_without_truncating_links(self):
        links = {
            name: "https://example.invalid/" + name.replace(" ", "-") + "x" * 900
            for name in ("MP3", "RSS", "Transcrições gerais")
        }
        with (
            patch.object(
                notification,
                "get_config",
                return_value={
                    "integrations": {
                        "discord_notify": True,
                        "discord_channels": ["123"],
                    }
                },
            ),
            patch("Plugins.Connectors.discord.service.Discord") as bot,
        ):
            self.assertTrue(
                notification.announce_publication("Sessão", "Campanha", links)
            )
            calls = bot.return_value.send.call_args_list
            self.assertGreater(len(calls), 1)
            combined = "\n".join(call.args[0] for call in calls)
            for url in links.values():
                self.assertIn(url, combined)
            self.assertTrue(all(len(call.args[0]) <= 2000 for call in calls))

    def test_episode_code_and_only_present_mapped_players_are_mentioned(self):
        config = {
            "integrations": {"discord_notify": True, "discord_channels": ["123"]},
            "discord_users": {
                "Caio": "111",
                "Dota": "222",
                "Ausente": "333",
                "Inválido": "@everyone",
            },
        }
        with (
            patch.object(notification, "get_config", return_value=config),
            patch("Plugins.Connectors.discord.service.Discord") as bot,
        ):
            self.assertTrue(
                notification.announce_publication(
                    "A chegada",
                    "Mesa",
                    {"MP3": "https://example.invalid/a.mp3"},
                    season=2,
                    number=35,
                    players=["Caio", "Dota", "Caio", "Inválido"],
                )
            )
            args = bot.return_value.send.call_args
            self.assertTrue(args.args[0].startswith("Mesa - S02E35 - A chegada\nMP3: "))
            self.assertEqual(args.kwargs["mentions"], ["111", "222"])
            self.assertNotIn("333", args.args[0])

    def test_reader_campaign_selector_escapes_labels_and_rejects_script_urls(self):
        page = render(
            [],
            None,
            {"title": "Mesa", "rss_key": "a/rss.xml"},
            [
                {
                    "title": "Mesa <A>",
                    "rss_key": "a/rss.xml",
                    "url": "https://example.invalid/a/transcripts.html",
                },
                {
                    "title": "Mesa B",
                    "rss_key": "b/rss.xml",
                    "url": "https://example.invalid/b/transcripts.html",
                },
                {"title": "Bad", "rss_key": "c/rss.xml", "url": "javascript:alert(1)"},
            ],
        )
        self.assertIn('id="campaign"', page)
        self.assertIn(
            'value="https://example.invalid/a/transcripts.html" selected', page
        )
        self.assertIn("Mesa &lt;A&gt;", page)
        self.assertNotIn("javascript:", page)

    def test_settings_schema_removes_tz_and_keeps_nine_operational_keys(self):
        schema_path = (
            Path(__file__).resolve().parents[1] / "settings.schema.json"
        )
        names = [item["name"] for item in json.loads(schema_path.read_text(encoding="utf-8"))]
        self.assertNotIn("TZ", names)
        self.assertEqual(
            names,
            [
                "POLL_INTERVAL_SECONDS",
                "DRIVE_PROCESS",
                "LOCAL_DRIVE_FOLDER",
                "PUBLICAR_DIRETO",
                "OWNER_EMAIL",
                "TRANSCRIPTS_FILE",
                "SKIP_CLOSED",
                "FEED_CACHE_DIR",
                "FEED_FORCE_REBUILD",
            ],
        )

    def test_config_exposes_app_settings_defaults_timezone_and_discord_users(self):
        save_document("Apps/podcast_automation/campaigns", copy.deepcopy(EXAMPLE))
        loaded = web_api.handle("config", {}, None)
        self.assertIn("discord_users", loaded)
        self.assertIsInstance(loaded["discord_users"], dict)
        self.assertIn("app_settings", loaded)
        self.assertEqual(len(loaded["app_settings"]), 9)
        self.assertIsInstance(loaded["app_settings"]["POLL_INTERVAL_SECONDS"], int)
        self.assertIsInstance(loaded["app_settings"]["DRIVE_PROCESS"], bool)
        self.assertIn("app_defaults", loaded)
        self.assertIn("audio", loaded["app_defaults"])
        self.assertIn("processing", loaded["app_defaults"])
        self.assertIn("publication", loaded["app_defaults"])
        self.assertIn("timezone", loaded)
        self.assertIn("iana", loaded["timezone"])
        self.assertIn("utc_offset", loaded["timezone"])

    def test_save_options_and_save_settings_preserve_unknown_and_llm_keys_without_polluting_doc(self):
        initial_doc = copy.deepcopy(EXAMPLE)
        initial_doc["discord_users"] = {"Dota": "123456"}
        initial_doc["custom_root"] = {"keep": True}
        initial_doc["integrations"] = {
            "llm_provider": "openai",
            "llm_model": "gpt-4o-mini",
            "future_0002_flag": True,
        }
        initial_doc["processing"]["extra_flag"] = "keep-me"
        save_document("Apps/podcast_automation/campaigns", initial_doc)

        web_api.handle(
            "save-options",
            {
                "outputs": {"txt": False},
                "integrations": {"google_account": "work", "extra_int": 42},
            },
            None,
        )
        web_api.handle(
            "save-settings",
            {
                "app_settings": {
                    "POLL_INTERVAL_SECONDS": 300,
                    "DRIVE_PROCESS": False,
                    "LOCAL_DRIVE_FOLDER": "data/custom-drive",
                    "OWNER_EMAIL": "owner@example.com",
                    "TRANSCRIPTS_FILE": "sessoes.html",
                },
                "audio": {"fade_seconds": "0,005", "compressor_ratio": 2.5},
                "publication": {"website": "https://rpg.example.com", "language": "pt-BR"},
                "processing": {"minimum_session_seconds": 900},
            },
            None,
        )

        raw_doc = document("Apps/podcast_automation/campaigns")
        self.assertNotIn("app_settings", raw_doc)
        self.assertNotIn("app_defaults", raw_doc)
        self.assertNotIn("timezone", raw_doc)
        self.assertEqual(raw_doc["discord_users"], {"Dota": "123456"})
        self.assertEqual(raw_doc["custom_root"], {"keep": True})
        self.assertEqual(raw_doc["integrations"]["llm_provider"], "openai")
        self.assertEqual(raw_doc["integrations"]["llm_model"], "gpt-4o-mini")
        self.assertTrue(raw_doc["integrations"]["future_0002_flag"])
        self.assertEqual(raw_doc["integrations"]["extra_int"], 42)
        self.assertEqual(raw_doc["processing"]["extra_flag"], "keep-me")
        self.assertEqual(raw_doc["processing"]["minimum_session_seconds"], 900)
        self.assertEqual(raw_doc["audio"]["fade_seconds"], 0.005)
        self.assertEqual(raw_doc["audio"]["compressor_ratio"], 2.5)

        reloaded = web_api.handle("config", {}, None)
        self.assertEqual(reloaded["app_settings"]["POLL_INTERVAL_SECONDS"], 300)
        self.assertFalse(reloaded["app_settings"]["DRIVE_PROCESS"])
        self.assertEqual(
            reloaded["app_settings"]["LOCAL_DRIVE_FOLDER"], "data/custom-drive"
        )
        self.assertEqual(reloaded["app_settings"]["OWNER_EMAIL"], "owner@example.com")
        self.assertEqual(reloaded["app_settings"]["TRANSCRIPTS_FILE"], "sessoes.html")

    def test_save_settings_validates_fields_with_pt_br_messages(self):
        save_document("Apps/podcast_automation/campaigns", copy.deepcopy(EXAMPLE))
        invalid_cases = [
            (
                {"app_settings": {"POLL_INTERVAL_SECONDS": 0}},
                "Informe um número inteiro de segundos, a partir de 1.",
            ),
            (
                {"app_settings": {"OWNER_EMAIL": "invalido"}},
                "Informe um e-mail válido, como nome@dominio.com, ou deixe em branco.",
            ),
            (
                {"app_settings": {"TRANSCRIPTS_FILE": "transcripts.txt"}},
                "Informe o nome de um arquivo .html, como transcripts.html.",
            ),
            (
                {"publication": {"website": "ftp://site.com"}},
                "Informe um endereço que comece com https:// ou http://.",
            ),
            (
                {"publication": {"language": "portugues"}},
                "Use um código de idioma, como pt-BR.",
            ),
            (
                {"processing": {"minimum_session_seconds": -1}},
                "Informe um número inteiro igual ou maior que zero.",
            ),
            (
                {"audio": {"compressor_ratio": 0.5}},
                "A razão do compressor deve ser 1 ou maior.",
            ),
            (
                {"audio": {"compressor_attack_ms": 0}},
                "Informe um tempo maior que zero.",
            ),
            (
                {"discord_users": {"Dota": "abc"}},
                "O ID do Discord tem só números. Deixe em branco se não quiser menções.",
            ),
        ]
        for payload, expected_msg in invalid_cases:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError) as ctx:
                    web_api.handle("save-settings", payload, None)
                self.assertEqual(str(ctx.exception), expected_msg)
