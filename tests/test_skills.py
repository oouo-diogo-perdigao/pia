"""Testes offline de skills e playback: não abrem programas, microfone ou rede."""
import ast
from concurrent.futures import Future
import importlib.util
import io
import json
import logging
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import Mock, MagicMock, patch
import wave

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('skills_under_test', ROOT / 'src/skills_runtime.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def wait_until(predicate):
    deadline = time.monotonic() + 2
    while not predicate() and time.monotonic() < deadline:
        time.sleep(.005)
    if not predicate():
        raise AssertionError('Estado esperado não foi alcançado')


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.services = Mock()
        self.engine = runtime.SkillRuntime(self.services)

    def test_simple_auto_close_and_explicit_close(self):
        executed = threading.Event()
        self.engine.activate('simples', lambda: executed.set())
        wait_until(lambda: executed.is_set() and not self.engine.active)
        self.services.close.assert_called_once()

    def test_waits_for_real_tts_completion(self):
        speech = Future()
        self.services.speak.return_value = speech
        session = self.engine.activate('tempo', lambda piaTTS: piaTTS('Previsão'))
        wait_until(lambda: session.finished)
        self.assertTrue(self.engine.active)
        self.services.close.assert_not_called()
        speech.set_result(True)
        self.assertFalse(self.engine.active)
        self.services.close.assert_called_once()

    def test_stop_words_never_reach_listener(self):
        received = []
        session = self.engine.activate('ditado', lambda piaSTT: piaSTT(received.append))
        wait_until(lambda: session.finished)
        self.engine.dispatch('Texto com Acentuação')
        self.engine.dispatch('Encerrar.')
        self.assertEqual(received, ['Texto com Acentuação'])
        self.assertTrue(session.cancelled.is_set())
        self.assertFalse(self.engine.active)
        self.engine.dispatch('Depois')
        self.assertEqual(len(received), 1)

    def test_own_speech_does_not_feed_listener_and_stop_still_works(self):
        speech = Future()
        self.services.speak.return_value = speech
        received = []
        def skill(piaSTT, piaTTS):
            piaSTT(received.append)
            piaTTS('Olá')
        session = self.engine.activate('exemplo', skill)
        wait_until(lambda: session.finished)
        self.engine.dispatch('Olá')
        self.assertEqual(received, [])
        self.engine.dispatch('finalizar')
        self.assertTrue(session.cancelled.is_set())

    def test_cancelled_skill_cannot_affect_next_session(self):
        speech = Future()
        self.services.speak.return_value = speech
        first = self.engine.activate('primeira', lambda piaTTS: piaTTS('A'))
        wait_until(lambda: first.finished)
        second = self.engine.activate('segunda', lambda piaSTT: piaSTT(lambda text: None))
        wait_until(lambda: second.finished)
        speech.set_result(True)
        first.close()
        first.insert('não deve inserir')
        self.assertIs(self.engine.session, second)
        self.services.insert.assert_not_called()
        self.engine.cancel()

    def test_visual_state_restored_and_listener_error_closes(self):
        def skill(piaSTT, piaInterface):
            piaInterface('processing', True)
            def listen(text):
                raise ValueError('erro de teste')
            piaSTT(listen)
        session = self.engine.activate('efeito', skill)
        wait_until(lambda: session.finished)
        with self.assertLogs(level='ERROR'):
            self.engine.dispatch('teste')
        self.assertFalse(self.engine.active)
        self.services.interface.assert_any_call('processing', False)

    def test_tts_error_closes_session(self):
        speech = Future()
        self.services.speak.return_value = speech
        session = self.engine.activate('tempo', lambda piaTTS: piaTTS('Previsão'))
        wait_until(lambda: session.finished)
        with self.assertLogs(level='ERROR'):
            speech.set_exception(RuntimeError('falha de áudio'))
        self.assertFalse(self.engine.active)


class LoaderTests(unittest.TestCase):
    def load_loader(self):
        package = types.ModuleType('_skill_loader_test')
        package.__path__ = [str(ROOT / 'src')]
        state = types.ModuleType('_skill_loader_test.state')
        state.COMMAND_ACTIONS = {}
        with patch.dict(sys.modules, {'_skill_loader_test': package, '_skill_loader_test.state': state,
                                    '_skill_loader_test.skills_runtime': runtime}):
            spec = importlib.util.spec_from_file_location('_skill_loader_test.commands_loader', ROOT / 'src/commands_loader.py')
            loader = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(loader)
        return loader

    def test_bundled_skills_and_relative_weather_import(self):
        loader = self.load_loader()
        with patch.dict(sys.modules, {'requests': Mock()}):
            loader.load_commands()
        for name in ('abrir bloco de notas', 'abrir navegador', 'previsao do tempo', 'modo ditado', 'exemplo de skill'):
            self.assertIn(name, loader.COMMAND_ACTIONS)
        host = Mock()
        fallback = Mock()
        with patch.object(loader, 'get_runtime', return_value=host):
            loader.process_command('comando previsão do tempo!', fallback)
        self.assertEqual(host.activate.call_args.args[0], 'previsao do tempo')
        fallback.assert_not_called()

    def test_disabled_and_invalid_projects_do_not_break_other_skills(self):
        loader = self.load_loader()
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for name, manifest in [('disabled', 'id="off"\ncommands=["off"]\nenabled=false'),
                                   ('bad', 'id="bad"\ncommands=["bad"]\nentrypoint="../../escape.py"'),
                                   ('good', 'id="good"\ncommands=["teste"]')]:
                project = folder / name
                project.mkdir()
                (project/'plugin.toml').write_text(manifest, encoding='utf-8')
                (project/'plugin.py').write_text('def execute(piaClose): piaClose()\n', encoding='utf-8')
            loader.PLUGIN_ROOT = folder
            with self.assertLogs(level='ERROR'):
                loader.load_commands()
            self.assertIn('teste', loader.COMMAND_ACTIONS)
            self.assertNotIn('off', loader.COMMAND_ACTIONS)
            self.assertNotIn('bad', loader.COMMAND_ACTIONS)

    def test_dictation_uses_injected_apis(self):
        loader = self.load_loader()
        with patch.dict(sys.modules, {'requests': Mock()}):
            loader.load_commands()
        listen, insert, key, close = Mock(), Mock(), Mock(), Mock()
        loader.COMMAND_ACTIONS['modo ditado'](listen, insert, key, close)
        callback = listen.call_args.args[0]
        callback('Olá Mundo')
        insert.assert_called_once_with('Olá Mundo ')
        callback('enviar')
        key.assert_called_with('enter')


class PlayerTests(unittest.TestCase):
    def manager(self):
        tree = ast.parse((ROOT/'src/TTSManager.py').read_text(encoding='utf-8'))
        node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'TTSManager')
        namespace = dict(threading=threading, queue=queue, io=io, wave=wave, logging=logging, Path=Path, BASE_DIR=ROOT)
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'TTSManager.py', 'exec'), namespace)
        manager = namespace['TTSManager'].__new__(namespace['TTSManager'])
        manager.lock = threading.RLock()
        manager.queue = queue.Queue()
        manager._stop_event = threading.Event()
        manager._resolve_output_device = Mock(return_value=None)
        return manager

    def wav(self):
        data = io.BytesIO()
        with wave.open(data, 'wb') as stream:
            stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(16000)
            stream.writeframes(b'\0\0' * 160)
        return data.getvalue()

    def test_future_resolves_only_after_playback(self):
        manager = self.manager()
        future = Future()
        future.add_done_callback(lambda _: manager._stop_event.set())
        manager.queue.put(dict(jobName='skill', wav_bytes=self.wav(), device=None, completion=future, cancelled=threading.Event()))
        sd = Mock()
        sd.get_stream.return_value.active = False
        sd.play.side_effect = lambda *args, **kwargs: self.assertFalse(future.done())
        with patch.dict(sys.modules, {'sounddevice': sd, 'numpy': MagicMock()}):
            manager._play_loop()
        self.assertTrue(future.result())
        sd.play.assert_called_once()

    def test_tts_consumer_preserves_future_until_player_handoff(self):
        manager = self.manager()
        future = Future()
        cancelled = threading.Event()
        jobs = queue.Queue()
        jobs.put(dict(text='fala', voice='voz', speed=1, style=None, device=None,
                      job_name='skill', completion=future, cancelled=cancelled))
        manager.tts_job_queues = {'kokoro': jobs}
        manager.generate = Mock(return_value=self.wav())
        manager.add_audio_job = Mock(side_effect=lambda *args, **kwargs: manager._stop_event.set())
        manager._tts_consumer_loop('kokoro')
        self.assertIs(manager.add_audio_job.call_args.kwargs['completion'], future)
        self.assertIs(manager.add_audio_job.call_args.kwargs['cancelled'], cancelled)
        self.assertFalse(future.done())
        self.assertEqual(jobs.unfinished_tasks, 0)

    def test_tts_generation_error_reaches_skill_future(self):
        manager = self.manager()
        future = Future()
        future.add_done_callback(lambda _: manager._stop_event.set())
        jobs = queue.Queue()
        jobs.put(dict(text='fala', voice='voz', speed=1, style=None, device=None,
                      job_name='skill', completion=future))
        manager.tts_job_queues = {'kokoro': jobs}
        manager.generate = Mock(side_effect=RuntimeError('falha no sintetizador'))
        with self.assertLogs(level='ERROR'):
            manager._tts_consumer_loop('kokoro')
        self.assertIsInstance(future.exception(), RuntimeError)
        self.assertEqual(jobs.unfinished_tasks, 0)

    def test_cancelled_skill_does_not_play_queued_audio(self):
        manager = self.manager()
        future = Future()
        future.add_done_callback(lambda _: manager._stop_event.set())
        cancelled = threading.Event(); cancelled.set()
        manager.queue.put(dict(jobName='skill', wav_bytes=self.wav(), device=None, completion=future, cancelled=cancelled))
        sd = Mock()
        with patch.dict(sys.modules, {'sounddevice': sd, 'numpy': MagicMock()}):
            manager._play_loop()
        self.assertTrue(future.cancelled())
        sd.play.assert_not_called()


if __name__ == '__main__':
    unittest.main()
