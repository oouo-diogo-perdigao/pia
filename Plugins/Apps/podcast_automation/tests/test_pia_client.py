"""Contrato HTTP da integração de resumos, sem acessar um servidor real."""

import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from podcast_automation.geradorResumoSessao import GeradorResumoSessao

spec = importlib.util.spec_from_file_location(
    "pia_client", Path(__file__).resolve().parents[1] / "src/podcast_automation/llm.py"
)
llm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(llm)


class PiaClientTests(unittest.TestCase):
    def setUp(self):
        context = dict(
            url="http://localhost:8762",
            model="pia-default",
            max_upload_bytes=209715200,
            token="internal-fixture",
        )
        first = patch.object(llm, "current", return_value=context)
        first.start()
        self.addCleanup(first.stop)
        second = patch("src.app_access.current", return_value=context)
        second.start()
        self.addCleanup(second.stop)

    @patch.dict(os.environ, {}, clear=True)
    def test_default_endpoint_auth_and_json_response(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "choices": [{"message": {"content": '{"resumo": "Sessão"}'}}]
        }
        with patch.object(llm.requests, "post", return_value=response) as post:
            result = llm.PiaClient().complete_json("Roteiro", ("resumo",))
        self.assertEqual(result, {"resumo": "Sessão"})
        self.assertEqual(
            post.call_args.args, ("http://localhost:8762/v1/chat/completions",)
        )
        self.assertNotIn("Authorization", post.call_args.kwargs["headers"])
        self.assertEqual(
            post.call_args.kwargs["headers"]["X-PIA-App-Token"], "internal-fixture"
        )
        self.assertEqual(post.call_args.kwargs["json"]["model"], "pia-default")
        self.assertFalse(post.call_args.kwargs["json"]["stream"])

    def test_connection_error_identifies_pia(self):
        with patch.object(
            llm.requests, "post", side_effect=llm.requests.ConnectionError
        ):
            with self.assertRaisesRegex(RuntimeError, "comunicar com a PIA"):
                llm.PiaClient().complete_json("Roteiro", ("resumo",), attempts=1)

    def test_invalid_response_is_distinct_from_connection_error(self):
        response = Mock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": "{}"}}]}
        with patch.object(llm.requests, "post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "campos do resumo"):
                llm.PiaClient().complete_json("Roteiro", ("resumo",), attempts=1)

    def test_server_validation_message_is_shown(self):
        response = Mock(status_code=400)
        response.json.return_value = {
            "error": {
                "message": "O seletor LLM não selecionou nenhum modelo configurado."
            }
        }
        with patch.object(llm.requests, "post", return_value=response) as post:
            with self.assertRaisesRegex(RuntimeError, "HTTP 400.*seletor LLM"):
                llm.PiaClient().complete_json("Roteiro", ("resumo",))
        self.assertEqual(post.call_count, 1)

    def test_accepts_summary_with_one_paragraph(self):
        summary = object.__new__(GeradorResumoSessao)
        data = dict(
            nome_sessao="Sessão",
            resumo_rapido="Uma frase.",
            resumo_completo="Um único parágrafo.",
        )
        response = Mock(status_code=200)
        response.json.return_value = {
            "choices": [{"message": {"content": json.dumps(data)}}]
        }

        with patch.object(llm.requests, "post", return_value=response) as post:
            result = llm.PiaClient().complete_json(
                "Roteiro",
                summary.CAMPOS_OBRIGATORIOS,
                attempts=1,
                validate=summary.validar_dados,
            )
        post.assert_called_once()
        self.assertEqual(result, data)

    def test_unauthorized_is_not_retried(self):
        with patch.object(
            llm.requests, "post", return_value=Mock(status_code=401)
        ) as post:
            with self.assertRaisesRegex(RuntimeError, "PIA retornou HTTP 401"):
                llm.PiaClient().complete_json("Roteiro", ("resumo",))
        self.assertEqual(post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
