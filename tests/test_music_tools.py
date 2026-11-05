import json
from types import SimpleNamespace
import pytest
from Plugins.Apps.music import service
from src import tool_registry


def test_music_rejects_invalid_inputs_before_network():
    for data in ({'prompt':''}, {'prompt':'song','duration':True},
                 {'prompt':'song','provider':'flow'}, {'prompt':'song','duration':181}):
        with pytest.raises(ValueError):
            service.generate(**data)


def test_music_only_loopback(monkeypatch):
    for url in ('https://example.com', 'http://127.0.0.1/other', 'http://user@localhost'):
        monkeypatch.setattr(service,'settings',lambda:{'MUSIC_LOCAL_URL':url})
        with pytest.raises(ValueError):service.base_url()


def test_local_music_polls_and_saves(monkeypatch,tmp_path):
    monkeypatch.setattr(service,'settings',lambda:{})
    class Response:
        status_code=200
        content=b'fake mp3 bytes'
        def __init__(self,data=None):self.data=data
        def json(self):return self.data
        def close(self):pass
    class Session:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,**kwargs):
            if url.endswith('/release_task'):
                assert kwargs['json']['audio_duration']==30
                return Response({'data':{'task_id':'one'}})
            return Response({'data':[{'status':1,'result':json.dumps([{'file':'/v1/audio?path=test.mp3'}])}]})
        def get(self,url,**kwargs):return Response()
    monkeypatch.setattr(service,'OUTPUT',tmp_path)
    monkeypatch.setattr(service.requests,'Session',Session)
    monkeypatch.setattr(service,'engine',lambda *args:('http://127.0.0.1:8015',{}))
    result=service.generate('piano')
    assert service.audio_file(result['file']).read_bytes()==b'fake mp3 bytes'
    assert result['requested_duration']==30
    assert json.loads((tmp_path/(result['file']+'.json')).read_text())==result


def test_music_cancellation_releases_lock():
    with pytest.raises(InterruptedError):service.generate('piano',cancelled=lambda:True)
    assert not service._generation_lock.locked()


def test_registry_rejects_extra_arguments():
    from jsonschema import ValidationError
    with pytest.raises(ValidationError):tool_registry.call('pia_camera',{'shell':'bad'})


def test_tool_loop_uses_results_and_allowlist(monkeypatch):
    class Message:
        content='Finished'
        tool_calls=None
        def model_dump(self,**kwargs):return {'role':'assistant','tool_calls':[]}
    first=Message()
    first.tool_calls=[SimpleNamespace(id='t',function=SimpleNamespace(name='pia_accounts',arguments='{}'))]
    responses=iter([first,Message()])
    class Agent:
        def complete(self,history,**kwargs):
            if len(history)>1:assert history[-1]['role']=='tool'
            return SimpleNamespace(choices=[SimpleNamespace(message=next(responses))])
    monkeypatch.setattr(tool_registry,'call',lambda *args:[{'id':'account'}])
    assert tool_registry.complete_with_tools(Agent(),[{'role':'user','content':'accounts'}],allowed=['pia_accounts'])=='Finished'
    responses=iter([first])
    with pytest.raises(ValueError):tool_registry.complete_with_tools(Agent(),[],allowed=['pia_music'])
