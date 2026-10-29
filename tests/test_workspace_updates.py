import base64
from http.client import HTTPConnection
import json
from pathlib import Path
import queue
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import uuid

from src.cache_paths import migrate
from src.pia.service import WorkspaceService,Apps,Job
from src.workspace_store import WorkspaceStore
from Plugins.Apps.podcast_automation.pipeline import initial,apply


class WorkspaceUpdateTests(unittest.TestCase):
    def test_pipeline_stages_failure_skip_progress_and_links(self):
        state=initial();apply(state,{'kind':'session','name':'Sessão 1'});apply(state,{'kind':'stage','index':0});apply(state,{'kind':'stage','index':4})
        self.assertEqual(state['stages'][0]['status'],'done')
        self.assertEqual(state['stages'][2]['status'],'skipped')
        apply(state,{'kind':'progress','percent':42,'processed':42,'duration':100})
        self.assertEqual(state['progress']['percent'],42)
        apply(state,{'kind':'artifact','name':'MP3','url':'https://example.invalid/podcast.mp3'})
        apply(state,{'kind':'failed','error':'Falha real'})
        self.assertEqual(state['stages'][4]['status'],'error')
        self.assertEqual(state['error'],'Falha real')
        apply(state,{'kind':'session','name':'Sessão 2'})
        self.assertEqual(state['history'][0]['artifacts'][0]['name'],'MP3')

    def test_order_is_persisted_and_rejects_unknown_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            store=WorkspaceStore(Path(directory)/'workspace.db')
            service=WorkspaceService(backend=SimpleNamespace(store=store))
            order=[item['id'] for item in reversed(service.apps.public())]
            service.dispatch('POST','/apps/order',{'order':order},{})
            self.assertEqual([item['id'] for item in service.state()['apps']],order)
            for invalid in (['unknown'],[order[0],order[0]],[{}]):
                with self.assertRaises(ValueError):service.dispatch('POST','/apps/order',{'order':invalid},{})

    def test_known_cache_migration_is_idempotent_and_preserves_conflicts(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);old=root/'cache/Kokoro-82M';old.mkdir(parents=True);(old/'voices.bin').write_bytes(b'fixture')
            flat=root/'cache/model.bin';flat.write_bytes(b'whisper-fixture')
            migrate(root);migrate(root)
            self.assertEqual((root/'cache/main/tts/kokoro/voices.bin').read_bytes(),b'fixture')
            self.assertEqual((root/'cache/main/stt/legacy/model.bin').read_bytes(),b'whisper-fixture')
            old.mkdir();(old/'voices.bin').write_bytes(b'conflict');migrate(root)
            self.assertEqual((old/'voices.bin').read_bytes(),b'conflict')

    def test_medium_only_and_remote_failure_have_local_fallback(self):
        from test_transcription import hybrid,local,transcript
        manager=hybrid.STTManager.__new__(hybrid.STTManager);manager.providers=('groq',);manager._provider_available=Mock(return_value=True);manager._disable_provider_temporarily=Mock();manager._transcribe_groq_litellm=Mock(side_effect=RuntimeError('remote failed'))
        with patch.object(local.STTManager,'transcribe_request',return_value=transcript()) as method:
            self.assertTrue(manager.transcribe_request(b'file',local_model='medium',require_timestamps=True)['ok'])
            self.assertEqual(method.call_args.kwargs['local_model'],'medium')
            manager._transcribe_groq_litellm.assert_not_called()
            self.assertTrue(manager.transcribe_request(b'file',require_timestamps=True)['ok'])
            self.assertEqual(method.call_count,2)

    def test_progress_queue_is_request_scoped_and_preserves_result(self):
        from test_transcription import local,transcript
        manager=local.STTManager.__new__(local.STTManager);manager.api_lock=threading.Lock();manager.timeout=1;manager.api_result_queue=queue.Queue();manager.ensure_worker_running=Mock();manager.audio_chunk_queue=Mock()
        def queued(task):
            self.assertEqual(task['model'],'medium')
            manager.api_result_queue.put({'request_id':task['request_id'],'kind':'progress','event':{'percent':42}})
            manager.api_result_queue.put({**transcript(),'request_id':task['request_id']})
        manager.audio_chunk_queue.put.side_effect=queued
        callback=Mock();result=manager.transcribe_request(b'file',local_model='medium',progress=callback,request_timeout=100)
        callback.assert_called_once_with({'percent':42});self.assertEqual(result['segments'],transcript()['segments'])

    def test_settings_restart_waits_for_the_active_job(self):
        with tempfile.TemporaryDirectory() as directory:
            service=WorkspaceService(backend=SimpleNamespace(store=WorkspaceStore(Path(directory)/'workspace.db')))
            service.save_settings=Mock(return_value={'ok':True})
            called=threading.Event()
            service.native_handler=lambda action,data:called.set() if action=='restart' else None
            job=Job();service.jobs[job.id]=job
            result=service.dispatch('POST','/settings/save',{'section':'general','values':{}},{})
            self.assertTrue(result['restarting']);self.assertFalse(called.wait(.05))
            job.emit('done');self.assertTrue(called.wait(2))

    def test_progress_endpoint_preserves_openai_format_and_auth(self):
        from test_transcription import http,transcript
        from http.server import ThreadingHTTPServer
        identity=uuid.uuid4().hex
        server=ThreadingHTTPServer(('127.0.0.1',0),http.HTTPServer)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def transcribe(audio,**options):
            self.assertEqual(options['local_model'],'medium');self.assertGreaterEqual(options['request_timeout'],3600)
            options['progress']({'state':'transcribing','percent':42,'processed':42,'duration':100})
            return transcript()
        def request(method,path,body=None,token='local'):
            connection=HTTPConnection(*server.server_address,timeout=5)
            headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','X-PIA-Transcription-ID':identity}
            connection.request(method,path,json.dumps(body) if body else None,headers)
            response=connection.getresponse();result=(response.status,json.loads(response.read()));connection.close();return result
        try:
            with patch.object(http.STT_MANAGER,'transcribe_request',side_effect=transcribe):
                status,result=request('POST','/v1/audio/transcriptions',{'input_audio':{'data':base64.b64encode(b'file').decode(),'format':'wav'},'model':'local/medium','response_format':'verbose_json'})
                self.assertEqual(status,200);self.assertEqual(result['segments'],transcript()['segments'])
                progress=request('GET','/v1/audio/transcriptions/progress/'+identity)
                self.assertEqual(progress[0],200);self.assertEqual(progress[1]['percent'],100)
                self.assertEqual(request('GET','/v1/audio/transcriptions/progress/'+identity,token='wrong')[0],401)
                self.assertEqual(request('GET','/v1/audio/transcriptions/progress/missing')[0],404)
        finally:server.shutdown();server.server_close()


if __name__=='__main__':unittest.main()
