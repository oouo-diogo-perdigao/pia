"""Hardware, audio playback and external accounts are never accessed by these tests."""
import io
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock,patch
import unittest
import numpy as np
from src import camera,voice_interrupt,interop
from src.piamini.controls import HoverBlink
from Plugins.Connectors.agents import service as agents

class CameraTests(unittest.TestCase):
    def test_capture_releases_device_on_success_and_failure(self):
        cv=Mock();device=cv.VideoCapture.return_value;device.isOpened.return_value=True
        device.read.return_value=(True,Mock());cv.imencode.return_value=(True,SimpleNamespace(tobytes=lambda:b'PNG'))
        with patch.dict(sys.modules,{'cv2':cv}):
            self.assertEqual(camera.capture(),b'PNG');device.release.assert_called_once()
            device.release.reset_mock();device.read.return_value=(False,None)
            with self.assertRaises(RuntimeError):camera.capture()
            device.release.assert_called_once()
    def test_invalid_settings_do_not_open_camera(self):
        for data in ({'device':True},{'device':-1},{'width':10000},{'height':None}):
            with self.subTest(data=data),self.assertRaises(ValueError):camera.capture(**data)

class VoiceTests(unittest.TestCase):
    def test_onset_ignores_short_noise_and_fires_once_per_utterance(self):
        detector=voice_interrupt.SpeechOnset(.16)
        self.assertFalse(detector.feed(True,.05));self.assertFalse(detector.feed(False,.05))
        self.assertFalse(detector.feed(True,.1));self.assertTrue(detector.feed(True,.1));self.assertFalse(detector.feed(True,.2))
        detector.feed(False,.05);self.assertTrue(detector.feed(True,.2))
    def test_playback_correlation_rejects_own_echo_but_not_independent_speech(self):
        generator=np.random.default_rng(42);audio=generator.normal(0,.2,16000).astype('float32')
        with patch('src.voice_interrupt.time.monotonic',return_value=10):voice_interrupt.begin_playback(audio,16000)
        self.assertTrue(voice_interrupt.is_echo(audio[6000:7024,None],16000,now=10.5))
        self.assertFalse(voice_interrupt.is_echo(generator.normal(0,.2,(1024,1)),16000,now=10.5))
        voice_interrupt.end_playback()
    def test_interrupt_stops_both_synthesis_queue_and_playback(self):
        manager=Mock();generation=voice_interrupt.epoch()
        with patch.dict(sys.modules,{'src.HTTPServer':SimpleNamespace(TTS_MANAGER=manager)}):voice_interrupt.interrupt()
        self.assertNotEqual(generation,voice_interrupt.epoch());manager.stop.assert_called_once();manager.stop_tts_queue.assert_called_once()
    def test_hover_is_random_edge_triggered_and_rate_limited(self):
        hover=HoverBlink()
        with patch('src.piamini.controls.random.choice',return_value='look_left'):
            self.assertEqual(hover.update(True,0),'look_left');self.assertIsNone(hover.update(True,10))
            hover.update(False,10);self.assertEqual(hover.update(True,11),'look_left')
            hover.update(False,11);self.assertIsNone(hover.update(True,12))
        hover.update(False,20)
        with patch('src.piamini.controls.random.choice',return_value=None):self.assertIsNone(hover.update(True,20))

class AgentBridgeTests(unittest.TestCase):
    def test_codex_uses_stdin_saved_login_and_read_only_mode(self):
        def execute(command,**options):
            Path(command[command.index('-o')+1]).write_text('Resposta',encoding='utf-8')
            self.assertEqual(options['input'],'Mensagem; $(no shell)')
            self.assertNotIn('AGE_GEMINI_API_KEY',options['env'])
            self.assertNotIn('shell',options)
            return SimpleNamespace(returncode=0)
        with TemporaryDirectory() as directory,patch.object(agents,'BASE_DIR',Path(directory)),patch.object(agents,'executable',return_value='codex.exe'),patch.object(agents.subprocess,'run',side_effect=execute) as run,patch.dict('os.environ',{'AGE_GEMINI_API_KEY':'fixture'}):
            result=agents.ask('codex','Mensagem; $(no shell)')
            self.assertEqual(result['text'],'Resposta');self.assertIn('read-only',run.call_args.args[0])
    def test_gemini_plan_and_missing_cli(self):
        with patch.object(agents,'executable',return_value=None),self.assertRaises(RuntimeError):agents.ask('gemini','Olá')
        with TemporaryDirectory() as directory,patch.object(agents,'BASE_DIR',Path(directory)),patch.object(agents,'executable',return_value='gemini'),patch.object(agents.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='{"response":"Olá"}')) as run:
            self.assertEqual(agents.ask('gemini','Teste')['text'],'Olá')
            self.assertIn('plan',run.call_args.args[0]);self.assertEqual(run.call_args.kwargs['input'],'Teste')

class ProtocolTests(unittest.TestCase):
    def request(self,method,params=None,protocol='mcp'):
        return interop.rpc({'jsonrpc':'2.0','id':1,'method':method,'params':params or {}},protocol)
    def test_mcp_initialization_list_and_bounded_dispatch(self):
        self.assertEqual(self.request('initialize')['result']['protocolVersion'],'2025-11-25')
        self.assertTrue(self.request('tools/list')['result']['tools'])
        result=self.request('tools/call',{'name':'arbitrary_shell','arguments':{'command':'echo bad'}})
        self.assertTrue(result['result']['isError'])
        self.assertEqual(self.request('unknown')['error']['code'],-32601)
        self.assertIsNone(interop.rpc({'jsonrpc':'2.0','method':'notifications/initialized'},'mcp'))
    def test_a2a_send_and_get_task(self):
        with patch.object(interop,'run',return_value='Resposta'):
            result=self.request('message/send',{'message':{'role':'user','messageId':'abc','parts':[{'kind':'text','text':'Olá'}]}},'a2a')['result']
        self.assertEqual(result['status']['state'],'completed')
        self.assertEqual(self.request('tasks/get',{'id':result['id']},'a2a')['result'],result)
    def handler(self,path,body,auth=True):
        encoded=json.dumps(body).encode()
        handler=Mock(path=path,command='POST',headers={'Content-Length':str(len(encoded))},rfile=io.BytesIO(encoded),wfile=io.BytesIO())
        handler._authorize_openai_request.return_value=auth
        return handler
    def test_camera_authentication_and_origin_are_checked_before_capture(self):
        with patch.object(camera,'capture') as capture:
            handler=self.handler('/action/camera',{},False);interop.route(handler);capture.assert_not_called()
            handler=self.handler('/action/camera',{});handler.headers['Origin']='https://attacker.invalid';handler.server.server_address=('127.0.0.1',8762)
            interop.route(handler);capture.assert_not_called();handler.send_json.assert_called_once()
    def test_agui_event_order_and_error_terminal(self):
        handler=self.handler('/protocols/ag-ui',{'threadId':'thread','runId':'run','messages':[{'role':'user','content':'Olá'}]})
        def run(text,context=None,on_delta=None):on_delta('Resposta')
        with patch.object(interop,'run',side_effect=run):self.assertTrue(interop.route(handler))
        events=[json.loads(line[6:]) for line in handler.wfile.getvalue().decode().splitlines() if line.startswith('data: ')]
        self.assertEqual([e['type'] for e in events],['RUN_STARTED','TEXT_MESSAGE_START','TEXT_MESSAGE_CONTENT','TEXT_MESSAGE_END','RUN_FINISHED'])
