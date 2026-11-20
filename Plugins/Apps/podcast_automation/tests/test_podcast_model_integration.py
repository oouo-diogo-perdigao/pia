"""Testes de integração de modelo externo no Podcast Automation (Card 0002-C3 / T2 / CA-0002-06 / CA-0002-07)."""

import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from Plugins.Apps.podcast_automation import web_api
from podcast_automation import geradorResumoSessao, llm
from src.settings_store import save_document

PODCAST_ROOT = Path(__file__).resolve().parents[1]


def canonical_t2_fixture() -> dict:
    """Fixture canônica T2 com todas as chaves exigidas em requisitos-PO.md."""
    return {
        "outputs": {
            "mp3": True,
            "resumo.json": True,
            "srt": True,
            "txt": False,
            "vtt": True,
        },
        "integrations": {
            "google_account": "google-acc-1",
            "google_folder": "folder-123",
            "google_folder_name": "Sessões RPG",
            "google_folder_path": "Meu Drive/Sessões RPG",
            "storage_account": "r2-acc-1",
            "storage_bucket": "podcast-bucket",
            "announce": True,
            "discord_notify": True,
            "discord_channels": ["111222333"],
            "taverns_notify": True,
            "taverns_channels": [
                "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
            ],
            "llm_provider": "openrouter",
            "llm_model": "openai/gpt-4o-mini",
        },
        "nomes_reais": {"mestre_a": "Ana", "jogador_b": "Bruno"},
        "discord_users": {"Ana": "1001", "Bruno": "1002"},
        "campaign_details": {
            "Ana": {
                "Campanha": "Crônicas de Teste",
                "rss_key": "cronicas/rss.xml",
                "players": {"Bruno": "Bardo"},
                "closed": False,
            }
        },
        "publication": {"base_url": "https://example.invalid/podcast"},
        "audio": {"bitrate": "128k"},
        "processing": {"whisper_model": "medium", "timezone": "America/Sao_Paulo"},
    }


class PodcastModelPersistenceTests(unittest.TestCase):
    def test_t2_save_options_non_destructive_merge_preserves_all_keys(self):
        fixture = canonical_t2_fixture()
        save_document("Apps/podcast_automation/campaigns", copy.deepcopy(fixture))

        result = web_api.handle(
            "save-options",
            {
                "integrations": {
                    "llm_provider": "codex",
                    "llm_model": "",
                }
            },
            None,
        )
        self.assertEqual(result, {"ok": True})

        saved = web_api.handle("config", {}, None)
        expected = copy.deepcopy(fixture)
        expected["integrations"]["llm_provider"] = "codex"
        expected["integrations"]["llm_model"] = ""

        self.assertEqual(saved, expected)

    def test_t2_save_config_non_destructive_merge_preserves_model_and_all_keys(self):
        fixture = canonical_t2_fixture()
        save_document("Apps/podcast_automation/campaigns", copy.deepcopy(fixture))

        stale_campaigns = {
            "nomes_reais": copy.deepcopy(fixture["nomes_reais"]),
            "campaign_details": copy.deepcopy(fixture["campaign_details"]),
            "publication": copy.deepcopy(fixture["publication"]),
            "audio": copy.deepcopy(fixture["audio"]),
            "processing": {**fixture["processing"], "custom_flag": True},
        }
        result = web_api.handle("save-config", {"value": stale_campaigns}, None)
        self.assertEqual(result, {"ok": True})

        saved = web_api.handle("config", {}, None)
        self.assertEqual(saved["outputs"], fixture["outputs"])
        self.assertEqual(saved["integrations"], fixture["integrations"])
        self.assertEqual(saved["discord_users"], fixture["discord_users"])
        self.assertEqual(saved["nomes_reais"], fixture["nomes_reais"])
        self.assertEqual(saved["campaign_details"], fixture["campaign_details"])
        self.assertEqual(saved["publication"], fixture["publication"])
        self.assertEqual(saved["audio"], fixture["audio"])
        self.assertTrue(saved["processing"]["custom_flag"])
        self.assertEqual(saved["processing"]["timezone"], "America/Sao_Paulo")

    def test_save_options_accepts_all_supported_providers_and_empty_default(self):
        fixture = canonical_t2_fixture()
        save_document("Apps/podcast_automation/campaigns", copy.deepcopy(fixture))

        for provider in (
            "",
            "codex",
            "agy",
            "openrouter",
            "gemini",
            "groq",
            "cloudflare",
            "local",
            "free",
            "paid",
        ):
            with self.subTest(provider=provider):
                res = web_api.handle(
                    "save-options",
                    {"integrations": {"llm_provider": provider, "llm_model": ""}},
                    None,
                )
                self.assertEqual(res, {"ok": True})
                saved = web_api.handle("config", {}, None)
                self.assertEqual(saved["integrations"]["llm_provider"], provider)
                self.assertEqual(saved["integrations"]["llm_model"], "")

    def test_save_options_rejects_invalid_llm_provider_or_model(self):
        fixture = canonical_t2_fixture()
        save_document("Apps/podcast_automation/campaigns", copy.deepcopy(fixture))

        with self.assertRaisesRegex(ValueError, "Provedor de modelo inválido"):
            web_api.handle(
                "save-options",
                {"integrations": {"llm_provider": "provedor-inexistente"}},
                None,
            )

        with self.assertRaisesRegex(ValueError, "Provedor de modelo inválido"):
            web_api.handle(
                "save-options",
                {"integrations": {"llm_provider": 123}},
                None,
            )

        with self.assertRaisesRegex(ValueError, "Modelo inválido"):
            web_api.handle(
                "save-options",
                {"integrations": {"llm_model": ["gpt-4o"]}},
                None,
            )


class PodcastModelExecutionTests(unittest.TestCase):
    def setUp(self):
        self.context = {
            "url": "http://localhost:8762",
            "model": "pia-global-default",
            "token": "app-token-secreto-123",
        }
        p1 = patch.object(llm, "current", return_value=self.context)
        p2 = patch("src.app_access.current", return_value=self.context)
        p1.start()
        p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)

    def test_resolve_model_variants(self):
        self.assertEqual(llm.resolve_model("pia-default", "", ""), "pia-default")
        self.assertEqual(llm.resolve_model("pia-default", "codex", ""), "codex")
        self.assertEqual(llm.resolve_model("pia-default", "codex", "codex"), "codex")
        self.assertEqual(
            llm.resolve_model("pia-default", "codex", "gpt-5"), "codex/gpt-5"
        )
        self.assertEqual(
            llm.resolve_model("pia-default", "openrouter", "openai/gpt-4o-mini"),
            "openrouter/openai/gpt-4o-mini",
        )
        self.assertEqual(
            llm.resolve_model(
                "pia-default", "openrouter", "openrouter/openai/gpt-4o-mini"
            ),
            "openrouter/openai/gpt-4o-mini",
        )
        self.assertEqual(llm.resolve_model("pia-default", "free", ""), "free")
        self.assertEqual(llm.resolve_model("pia-default", "paid", ""), "paid")

    def test_pia_client_uses_configured_provider_and_sanitizes_errors(self):
        config = canonical_t2_fixture()
        config["integrations"]["llm_provider"] = "codex"
        config["integrations"]["llm_model"] = ""

        response = Mock(status_code=503)
        response.json.return_value = {
            "error": {
                "message": (
                    "Codex CLI precisa de login. Token app-token-secreto-123 "
                    "sk-secretkey123456 em https://internal.example.invalid/auth"
                )
            }
        }
        with (
            patch.object(llm, "get_config", return_value=config),
            patch.object(llm.requests, "post", return_value=response) as post,
        ):
            client = llm.PiaClient()
            self.assertEqual(client.model, "codex")
            with self.assertRaises(RuntimeError) as ctx:
                client.complete_json("Roteiro", ("nome_sessao",), attempts=3)

        # Erro 503 de login/autenticação não deve retentar nem vazar segredos/URLs.
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs["json"]["model"], "codex")
        msg = str(ctx.exception)
        self.assertIn("Codex CLI precisa de login", msg)
        self.assertNotIn("app-token-secreto-123", msg)
        self.assertNotIn("sk-secretkey123456", msg)
        self.assertNotIn("https://internal.example.invalid", msg)

    def test_gerador_resumo_sessao_uses_configured_model_and_produces_valid_json(self):
        config = canonical_t2_fixture()
        config["integrations"]["llm_provider"] = "openrouter"
        config["integrations"]["llm_model"] = "openai/gpt-4o-mini"

        resumo_payload = {
            "nome_sessao": "O Eco da Fortaleza",
            "resumo_rapido": "Os aventureiros atravessam a ponte antiga e descobrem um selo arcano.",
            "resumo_completo": (
                "Primeiro parágrafo detalhando a chegada do grupo ao vale coberto de névoa.\n\n"
                "Segundo parágrafo descrevendo a negociação tensa com o guardião da ponte.\n\n"
                "Terceiro parágrafo narrando a descoberta do selo arcano e o gancho final."
            ),
        }
        response = Mock(status_code=200)
        response.json.return_value = {
            "choices": [
                {"message": {"content": json.dumps(resumo_payload, ensure_ascii=False)}}
            ]
        }

        with TemporaryDirectory() as tmpdir:
            roteiro = Path(tmpdir) / "sessao01.txt"
            roteiro.write_text(
                "Transcrição completa da sessão de teste.", encoding="utf-8"
            )
            storage = Mock()
            storage.getObjectIfExists.return_value = None

            with (
                patch.object(geradorResumoSessao, "get_config", return_value=config),
                patch.object(llm, "get_config", return_value=config),
                patch.object(llm.requests, "post", return_value=response) as post,
            ):
                gerador = geradorResumoSessao.GeradorResumoSessao(
                    campanha="Crônicas de Teste",
                    narrador="Ana",
                    personagens=["Bardo"],
                    jogadores=["Bruno"],
                    ouvintes=[],
                    roteiro_path=str(roteiro),
                    obj_storage=storage,
                )
                nome, rapido, completo = gerador.gerar_resumo()

            self.assertEqual(post.call_count, 1)
            self.assertEqual(
                post.call_args.kwargs["json"]["model"],
                "openrouter/openai/gpt-4o-mini",
            )
            self.assertEqual(nome, "O Eco da Fortaleza")
            self.assertIn("selo arcano", rapido)
            self.assertEqual(len(completo.split("\n\n")), 3)

            resumo_file = Path(gerador.resumo_json_path)
            self.assertTrue(resumo_file.is_file())
            saved_json = json.loads(resumo_file.read_text(encoding="utf-8"))
            self.assertEqual(saved_json["nome_sessao"], "O Eco da Fortaleza")
            self.assertEqual(saved_json["resumo_rapido"], rapido)
            self.assertEqual(saved_json["resumo_completo"], completo)

    def test_gerador_resumo_sessao_falls_back_to_global_default_when_empty(self):
        config = canonical_t2_fixture()
        config["integrations"]["llm_provider"] = ""
        config["integrations"]["llm_model"] = ""

        resumo_payload = {
            "nome_sessao": "Luz na Taverna",
            "resumo_rapido": "O grupo reúne pistas sobre o desaparecimento do ferreiro.",
            "resumo_completo": "Parágrafo um.\n\nParágrafo dois.\n\nParágrafo três.",
        }
        response = Mock(status_code=200)
        response.json.return_value = {
            "choices": [
                {"message": {"content": json.dumps(resumo_payload, ensure_ascii=False)}}
            ]
        }

        with TemporaryDirectory() as tmpdir:
            roteiro = Path(tmpdir) / "sessao02.txt"
            roteiro.write_text("Transcrição da sessão dois.", encoding="utf-8")
            storage = Mock()
            storage.getObjectIfExists.return_value = None

            with (
                patch.object(geradorResumoSessao, "get_config", return_value=config),
                patch.object(llm, "get_config", return_value=config),
                patch.object(llm.requests, "post", return_value=response) as post,
            ):
                gerador = geradorResumoSessao.GeradorResumoSessao(
                    campanha="Crônicas de Teste",
                    narrador="Ana",
                    personagens=["Bardo"],
                    jogadores=["Bruno"],
                    ouvintes=[],
                    roteiro_path=str(roteiro),
                    obj_storage=storage,
                )
                gerador.gerar_resumo()

            self.assertEqual(
                post.call_args.kwargs["json"]["model"],
                "pia-global-default",
            )

    def test_gerador_resumo_sessao_surfaces_actionable_error_without_fallback(self):
        config = canonical_t2_fixture()
        config["integrations"]["llm_provider"] = "codex"
        config["integrations"]["llm_model"] = ""

        response = Mock(status_code=401)
        response.json.return_value = {
            "error": {"message": "O Codex CLI precisa de login para responder."}
        }

        with TemporaryDirectory() as tmpdir:
            roteiro = Path(tmpdir) / "sessao03.txt"
            roteiro.write_text("Transcrição da sessão três.", encoding="utf-8")
            storage = Mock()
            storage.getObjectIfExists.return_value = None

            with (
                patch.object(geradorResumoSessao, "get_config", return_value=config),
                patch.object(llm, "get_config", return_value=config),
                patch.object(llm.requests, "post", return_value=response) as post,
            ):
                gerador = geradorResumoSessao.GeradorResumoSessao(
                    campanha="Crônicas de Teste",
                    narrador="Ana",
                    personagens=["Bardo"],
                    jogadores=["Bruno"],
                    ouvintes=[],
                    roteiro_path=str(roteiro),
                    obj_storage=storage,
                )
                with self.assertRaisesRegex(
                    RuntimeError,
                    r"Resumo não gerado:.*Codex CLI precisa de login.*Configurações > Inteligência artificial",
                ):
                    gerador.gerar_resumo()

            self.assertEqual(post.call_count, 1)


class PodcastSlotContractTests(unittest.TestCase):
    def test_panel_renders_model_settings_slot_container(self):
        panel_text = (PODCAST_ROOT / "web" / "Panel.jsx").read_text(encoding="utf-8")
        self.assertIn(
            'import ModelSettingsSlot from "./ModelSettingsSlot";', panel_text
        )
        self.assertIn('data-slot="podcast-model-settings"', panel_text)
        self.assertIn("<ModelSettingsSlot", panel_text)

    def test_model_settings_slot_follows_ux_and_shared_contract(self):
        slot_text = (PODCAST_ROOT / "web" / "ModelSettingsSlot.jsx").read_text(
            encoding="utf-8"
        )
        self.assertIn('id="podcast-model-settings-title"', slot_text)
        self.assertIn("../../../../src/pia/frontend/models", slot_text)
        self.assertIn("../../../../src/pia/frontend/ProviderDrawer", slot_text)
        self.assertIn("Consumo na sessão da PIA", slot_text)
        self.assertIn("Saldo do provedor", slot_text)
        self.assertIn("Saldo não informado pelo provedor", slot_text)
        self.assertIn("Gerenciar provedores", slot_text)


if __name__ == "__main__":
    unittest.main()
