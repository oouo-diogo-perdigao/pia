"""Offline tests: real implementation, mocked desktop/model/provider boundaries.

Run without the desktop dependencies: python -m unittest discover -s tests -p test_transcription.py
"""

import ast
import base64
from http.client import HTTPConnection
import importlib.util
import json
from pathlib import Path
import queue
import sys
import threading
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load_stack():
    package = types.ModuleType("_pia_stt_tests")
    package.__path__ = [str(ROOT / "src")]
    stubs = {package.__name__: package}
    # Stub only dependencies outside the STT/HTTP code under test.
    for filename in ("STTManager", "HybridSTTManager", "VoiceAgent", "HTTPServer"):
        tree = ast.parse(
            (ROOT / "src" / (filename + ".py")).read_text(encoding="utf-8")
        )
        for node in tree.body:
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module in {"STTManager", "transcription", "__future__"}:
                continue
            if not node.level and node.module != "faster_whisper":
                continue
            name = "_pia_stt_tests." + node.module if node.level else node.module
            module = stubs.setdefault(name, types.ModuleType(name))
            for alias in node.names:
                setattr(module, alias.name, Mock())
    config = stubs["_pia_stt_tests.config"]
    config.STT_PROVIDERS = ("gemini", "groq", "local")
    config.STT_REMOTE_COOLDOWN_SECONDS = 900
    config.OPENAI_COMPAT_TIMEOUT_SECONDS = 5
    config.OPENAI_COMPAT_API_KEY = "local"
    config.OPENAI_COMPAT_MAX_UPLOAD_BYTES = 209715200
    config.STT_TEMPERATURE = 0.0
    loaded = []
    with patch.dict(sys.modules, stubs):
        for name in (
            "transcription",
            "STTManager",
            "HybridSTTManager",
            "VoiceAgent",
            "HTTPServer",
        ):
            full_name = "_pia_stt_tests." + name
            spec = importlib.util.spec_from_file_location(
                full_name, ROOT / "src" / (name + ".py")
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[full_name] = module
            spec.loader.exec_module(module)
            loaded.append(module)
    return loaded


timing, local, hybrid, voice, http = load_stack()


def transcript():
    return {
        "ok": True,
        "text": "Primeira. Segunda.",
        "duration": 105.0,
        "language": "pt",
        "segments": [
            {"id": 0, "start": 2.25, "end": 3.5, "text": "Primeira."},
            {"id": 1, "start": 93.1, "end": 94.2, "text": "Segunda."},
        ],
    }


class TimingTests(unittest.TestCase):
    def test_validation_and_silence(self):
        self.assertEqual(timing.timed_result(transcript()), transcript())
        self.assertEqual(
            timing.timed_result({"duration": 5, "text": "", "segments": []})[
                "segments"
            ],
            [],
        )
        for invalid in (
            {"text": "fala", "duration": 5, "segments": []},
            {"text": "", "duration": None, "segments": []},
            {"duration": 5, "segments": [{"start": 4, "end": 2}]},
            {"duration": float("nan"), "segments": []},
        ):
            with self.assertRaises(ValueError):
                timing.timed_result(invalid)

    def test_subtitles(self):
        segments = transcript()["segments"]
        srt = timing.render_subtitles(segments, "srt")
        self.assertIn("00:01:33,100 --> 00:01:34,200", srt)
        self.assertTrue(srt.startswith("1\n00:00:02,250"))
        self.assertTrue(
            timing.render_subtitles(segments, "vtt").startswith("WEBVTT\n\n")
        )
        self.assertEqual(timing.render_subtitles([], "srt"), "")
        self.assertEqual(timing.render_subtitles([], "vtt"), "WEBVTT\n\n")
        self.assertEqual(timing.subtitle_timestamp(3599.9996, "."), "01:00:00.000")

    def test_native_long_audio_timeline_and_silence(self):
        agent = voice.VoiceAgent.__new__(voice.VoiceAgent)
        agent.model = Mock()
        segments = [types.SimpleNamespace(**s) for s in transcript()["segments"]]
        agent.model.transcribe.return_value = (
            iter(segments),
            types.SimpleNamespace(duration=105, language="pt"),
        )
        result = agent.transcribe_chunk(b"audio", return_metadata=True)
        self.assertEqual(result["segments"], transcript()["segments"])
        self.assertEqual(result["duration"], 105)
        self.assertEqual(result["text"], "Primeira. Segunda.")
        # Native decoder windows are already on the original timeline: never rebase or concatenate them.
        self.assertEqual(result["segments"][1]["start"], 93.1)
        agent.model.transcribe.return_value = (
            iter([]),
            types.SimpleNamespace(duration=105, language="pt"),
        )
        result = agent.transcribe_chunk(b"silence", return_metadata=True)
        self.assertEqual(result["text"], "")
        self.assertEqual(result["segments"], [])
        self.assertTrue(agent.model.transcribe.call_args.kwargs["vad_filter"])

    def manager(self, providers=("gemini", "groq", "local")):
        manager = hybrid.STTManager.__new__(hybrid.STTManager)
        manager.providers = providers
        manager._provider_available = Mock(return_value=True)
        manager._disable_provider_temporarily = Mock()
        manager._transcribe_remote = Mock(return_value="plain")
        manager._transcribe_groq_litellm = Mock(return_value=transcript())
        return manager

    def test_provider_timestamps_and_fallback(self):
        manager = self.manager()
        result = manager.transcribe_request(b"long audio", require_timestamps=True)
        self.assertEqual(result["provider"], "groq")
        self.assertEqual(result["segments"], transcript()["segments"])
        manager._transcribe_remote.assert_not_called()
        for failure in (RuntimeError("upload too large"), None):
            manager._transcribe_groq_litellm.side_effect = failure
            manager._transcribe_groq_litellm.return_value = {"text": "missing timing"}
            with patch.object(
                local.STTManager, "transcribe_request", return_value=transcript()
            ) as fallback:
                result = manager.transcribe_request(
                    b"whole original file", require_timestamps=True
                )
                self.assertEqual(result["provider"], "local")
                self.assertEqual(fallback.call_args.args[0], b"whole original file")
                self.assertEqual(result["segments"][1]["start"], 93.1)
        manager = self.manager(("gemini",))
        self.assertIn(
            "timestamps reais",
            manager.transcribe_request(b"audio", require_timestamps=True)["error"],
        )
        self.assertEqual(manager.transcribe_request(b"audio")["text"], "plain")

    def test_groq_adapter_preserves_segments_and_measures_full_audio(self):
        manager = self.manager()
        response = Mock()
        response.model_dump.return_value = {**transcript(), "duration": 94.2}
        provider = types.ModuleType("litellm")
        provider.transcription = Mock(return_value=response)
        decoder = types.ModuleType("faster_whisper.audio")
        decoder.decode_audio = Mock(return_value=range(16000 * 105))
        with patch.dict(
            sys.modules, {"litellm": provider, "faster_whisper.audio": decoder}
        ):
            result = hybrid.STTManager._transcribe_groq_litellm(
                manager, b"audio", return_metadata=True
            )
        self.assertEqual(result["duration"], 105)
        self.assertEqual(result["segments"], transcript()["segments"])
        self.assertEqual(
            provider.transcription.call_args.kwargs["response_format"], "verbose_json"
        )

    def test_worker_preserves_metadata_and_separates_recorder(self):
        tasks, recorder_results, api_results = (
            queue.Queue(),
            queue.Queue(),
            queue.Queue(),
        )
        tasks.put({"kind": "api", "request_id": "request", "audio": b"audio"})
        tasks.put({"kind": "stream", "audio": b"audio"})
        tasks.put("SHUTDOWN")
        module = types.ModuleType("src.VoiceAgent")
        agent = Mock()
        agent.transcribe_chunk.side_effect = [transcript(), "recorder text"]
        module.VoiceAgent = Mock(return_value=agent)
        with patch.dict(sys.modules, {"src.VoiceAgent": module}):
            local.stt_worker_process(tasks, recorder_results, api_results, ROOT)
        self.assertEqual(api_results.get()["segments"], transcript()["segments"])
        self.assertEqual(recorder_results.get()["text"], "recorder text")
        self.assertTrue(
            agent.transcribe_chunk.call_args_list[0].kwargs["return_metadata"]
        )
        self.assertFalse(
            agent.transcribe_chunk.call_args_list[1].kwargs["return_metadata"]
        )

    def test_local_manager_queue_preserves_metadata(self):
        manager = local.STTManager.__new__(local.STTManager)
        manager.api_lock = threading.Lock()
        manager.timeout = 2
        manager.ensure_worker_running = Mock()
        manager.api_result_queue = queue.Queue()
        manager.audio_chunk_queue = Mock()
        manager.audio_chunk_queue.put.side_effect = (
            lambda task: manager.api_result_queue.put(
                {**transcript(), "request_id": task["request_id"]}
            )
        )
        self.assertEqual(
            manager.transcribe_request(b"audio")["segments"], transcript()["segments"]
        )

    def test_large_groq_upload_skips_without_cooldown(self):
        manager = self.manager(('groq', 'local'))
        with patch.dict(hybrid.os.environ, {'STT_GROQ_MAX_UPLOAD_BYTES': '25000000'}):
            with patch.object(local.STTManager, 'transcribe_request', return_value=transcript()):
                result = manager.transcribe_request(b'x' * 25000001, require_timestamps=True)
        self.assertEqual(result['provider'], 'local')
        manager._transcribe_groq_litellm.assert_not_called()
        manager._disable_provider_temporarily.assert_not_called()
        manager._transcribe_groq_litellm.reset_mock()
        manager.transcribe_request(b'small', require_timestamps=True)
        manager._transcribe_groq_litellm.assert_called_once()

    def test_groq_adapter_checks_size_before_import_or_upload(self):
        with patch.dict(hybrid.os.environ, {'STT_GROQ_MAX_UPLOAD_BYTES': '10'}):
            with self.assertRaisesRegex(hybrid.RemoteSTTUnavailable, 'limite'):
                hybrid.STTManager._transcribe_groq_litellm(self.manager(), b'x' * 11)

    def test_local_progress_finishes_and_reports_original_time(self):
        agent = voice.VoiceAgent.__new__(voice.VoiceAgent)
        agent.model = Mock()
        agent.model.transcribe.return_value = (
            iter(types.SimpleNamespace(**segment) for segment in transcript()['segments']),
            types.SimpleNamespace(duration=105, language='pt'),
        )
        logger = Mock()
        with patch.object(voice, 'logger_stt', logger), patch.object(voice.time, 'monotonic', side_effect=[0, 1, 2, 3, 4]):
            agent.transcribe_chunk(b'audio', return_metadata=True)
        events = [json.loads(call.args[1]) for call in logger.info.call_args_list if call.args[0] == '[STT_PROGRESS] %s']
        self.assertEqual(events[0]['state'], 'preparing')
        self.assertEqual(events[-1]['state'], 'completed')
        self.assertEqual(events[-1]['processed'], 105)
        self.assertTrue(any(event['processed'] == 94.2 for event in events))

    def test_launcher_progress_partial_lines_and_failure(self):
        tree = ast.parse((ROOT / 'pia_launcher.py').read_text(encoding='utf-8'))
        viewer_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'LogViewer')
        namespace = {'Path': Path, 'json': json}
        exec(compile(ast.Module(body=[viewer_class], type_ignores=[]), 'pia_launcher.py', 'exec'), namespace)
        viewer = namespace['LogViewer'].__new__(namespace['LogViewer'])
        info = {'progress_bar': Mock(), 'progress_label': Mock()}
        viewer.update_stt_progress(info, '[STT_PROGRESS] {"state":"transcribing","processed":60,')
        info['progress_label'].configure.assert_not_called()
        viewer.update_stt_progress(info, '"duration":120,"percent":50}\n')
        self.assertIn('50.0%', info['progress_label'].configure.call_args.kwargs['text'])
        viewer.update_stt_progress(info, '[STT_PROGRESS] {"state":"completed"}\n')
        self.assertIn('100%', info['progress_label'].configure.call_args.kwargs['text'])
        viewer.update_stt_progress(info, '[STT_PROGRESS] {"state":"error"}\n')
        self.assertIn('falha', info['progress_label'].configure.call_args.kwargs['text'])


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.STTThreadingHTTPServer(("127.0.0.1", 0), http.HTTPServer)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, fmt, token="local", result=None, multipart=False, chunked=False):
        conn = HTTPConnection(*self.server.server_address, timeout=5)
        body = {
            "input_audio": {
                "data": base64.b64encode(b"audio").decode(),
                "format": "wav",
            },
            "response_format": fmt,
        }
        content_type = "application/json"
        encoded = json.dumps(body)
        if multipart:
            content_type = "multipart/form-data; boundary=pia-test"
            encoded = (
                '--pia-test\r\nContent-Disposition: form-data; name="file"; filename="podcast.mp3"\r\n'
                "Content-Type: audio/mpeg\r\n\r\naudio\r\n"
                '--pia-test\r\nContent-Disposition: form-data; name="response_format"\r\n\r\n'
                + fmt
                + "\r\n--pia-test--\r\n"
            )
        with patch.object(
            http.STT_MANAGER, "transcribe_request", return_value=result or transcript()
        ):
            headers = {"Content-Type": content_type, "Authorization": "Bearer " + token}
            if chunked:
                headers["Transfer-Encoding"] = "chunked"
                encoded = [encoded.encode("utf-8")]
            conn.request(
                "POST",
                "/v1/audio/transcriptions",
                encoded,
                headers,
                encode_chunked=chunked,
            )
            response = conn.getresponse()
            data = response.read().decode()
            conn.close()
            return response.status, data, response.getheader("Content-Type")

    def test_response_formats_and_auth(self):
        status, body, _ = self.request("verbose_json")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["segments"], transcript()["segments"])
        self.assertEqual(json.loads(body)["duration"], 105)
        self.assertEqual(
            json.loads(self.request("json")[1]), {"text": "Primeira. Segunda."}
        )
        self.assertEqual(self.request("text")[1], "Primeira. Segunda.")
        for fmt in ("srt", "vtt"):
            status, body, content_type = self.request(fmt)
            self.assertEqual(status, 200)
            self.assertIn("00:01:33", body)
            self.assertIn(
                "text/vtt" if fmt == "vtt" else "application/x-subrip", content_type
            )
        self.assertEqual(self.request("json", token="wrong")[0], 401)
        self.assertEqual(self.request("unknown")[0], 400)

    def test_multipart_and_upload_limit(self):
        status, body, _ = self.request("verbose_json", multipart=True)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["segments"], transcript()["segments"])
        with patch.object(http, "OPENAI_COMPAT_MAX_UPLOAD_BYTES", 1):
            self.assertEqual(self.request("verbose_json", multipart=True)[0], 413)

    def test_chunked_multipart(self):
        status, body, _ = self.request("verbose_json", multipart=True, chunked=True)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["duration"], 105)
        with patch.object(http, "OPENAI_COMPAT_MAX_UPLOAD_BYTES", 1):
            self.assertEqual(self.request("srt", multipart=True, chunked=True)[0], 413)

    def test_missing_timing_and_silence(self):
        for fmt in ("verbose_json", "srt", "vtt"):
            self.assertEqual(
                self.request(fmt, result={"ok": True, "text": "fala"})[0], 500
            )
            status, body, _ = self.request(
                fmt, result={"ok": True, "text": "", "duration": 10, "segments": []}
            )
            self.assertEqual(status, 200)
            if fmt == "verbose_json":
                self.assertEqual(json.loads(body)["segments"], [])


if __name__ == "__main__":
    unittest.main()
