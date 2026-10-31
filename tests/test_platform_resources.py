from types import SimpleNamespace
from unittest.mock import Mock
import threading
import time
import pytest
from src.workspace_store import WorkspaceStore
from src.notifications import NotificationCenter
from src import log_reader
from src.media import MediaSessions
from Plugins.Apps.music import service as music,web_api


def test_notifications_persist_read_and_mute(tmp_path):
    store=WorkspaceStore(tmp_path/'workspace.db');notice=Mock();speak=Mock()
    center=NotificationCenter(store,notice,speak)
    item=center.publish('Apps/music','Pronto','2 músicas',[{'url':'javascript:bad()'},{'url':'https://example.com/event','label':'Evento'}])
    assert center.snapshot()['counts']=={'Apps/music':1}
    assert len(item['links'])==1
    center.read(item['id']);assert center.snapshot()['unread']==0
    center.configure({'muted':['Bot/secretaria'],'read_aloud':False})
    center.publish('Bot/secretaria','Evento','Em breve')
    assert notice.call_count==1 and center.snapshot()['unread']==1
    assert NotificationCenter(store,notice,speak).snapshot()['items'][0]['source']=='Bot/secretaria'


def test_notifications_auto_speech_and_invalid_settings(tmp_path):
    called=threading.Event()
    center=NotificationCenter(WorkspaceStore(tmp_path/'db'),Mock(),lambda text:called.set())
    center.configure({'muted':[],'read_aloud':True});center.publish('Bot/secretaria','Título','Texto')
    assert called.wait(2)
    with pytest.raises(ValueError):center.configure({'muted':[],'read_aloud':'true'})
    with pytest.raises(ValueError):center.publish('Other/shell','bad','bad')


def test_logs_initial_tail_and_unlimited_session_delta(tmp_path,monkeypatch):
    monkeypatch.setattr(log_reader,'BASE_DIR',tmp_path)
    path=tmp_path/'logs/plugins/Apps/music.log';path.parent.mkdir(parents=True)
    path.write_text(''.join(f'old {n}\n' for n in range(230)),encoding='utf-8')
    first=log_reader.read_log('plugins/Apps/music.log')
    assert len(first['text'].splitlines())==100 and first['text'].startswith('old 130\n')
    with path.open('a',encoding='utf-8') as stream:stream.write(''.join(f'new {n}\n' for n in range(180)))
    delta=log_reader.read_log(first['name'],first['cursor'],first['identity'])
    assert len(delta['text'].splitlines())==180 and not delta['reset']
    assert delta['category']=='Apps'
    path.write_text('reset\n',encoding='utf-8')
    assert log_reader.read_log(first['name'],delta['cursor'],delta['identity'])['reset']
    with pytest.raises(ValueError):log_reader.log_path('../outside.log')


def test_media_sessions_do_not_stop_other_window_and_expire(monkeypatch):
    import src.media as module
    clock=[10.0];monkeypatch.setattr(module.time,'monotonic',lambda:clock[0])
    state=MediaSessions()
    assert state.update('one',True) and state.update('two',True)
    assert state.update('one',False)
    clock[0]=30
    assert not state.update('three',False)


def test_music_batch_keeps_tracks_and_progress(tmp_path,monkeypatch):
    monkeypatch.setattr(web_api,'_latest',None)
    def generate(**kwargs):
        name=f'{len(list(tmp_path.glob("*.mp3")))+1:032x}.mp3'
        (tmp_path/name).write_bytes(b'audio')
        return {'file':name,'prompt':kwargs['prompt'],'audio_url':'/api/pia/music/files/'+name}
    monkeypatch.setattr(music,'generate',generate)
    monkeypatch.setattr(music,'audio_file',lambda name:tmp_path/name)
    context=SimpleNamespace(jobs={},publish_notification=Mock())
    response=web_api.handle('generate',{'prompt':'piano','count':3},context)
    job=context.jobs[response['job']]
    with job.changed:
        assert job.changed.wait_for(lambda:job.status!='running',timeout=3)
    assert job.status=='done',job.error
    tracks=[event['item'] for event in job.events if event['type']=='track']
    assert len(tracks)==3 and len({item['batch'] for item in tracks})==1
    progress=[event['value'] for event in job.events if event['type']=='progress']
    assert progress[-1]['percent']==100 and progress[-1]['completed']==3
    context.publish_notification.assert_called_once()
    with pytest.raises(ValueError):web_api.handle('generate',{'prompt':'p','count':11},context)


def test_music_stops_only_owned_process_and_uses_destination(tmp_path,monkeypatch):
    process=Mock();process.poll.return_value=None
    monkeypatch.setattr(music,'_engine',process)
    music.stop_engine();process.terminate.assert_called_once();process.wait.assert_called_once()
    assert music._engine is None
    monkeypatch.setattr(music,'settings',lambda:{'MUSIC_OUTPUT_DIR':str(tmp_path)})
    assert music.output_directory()==tmp_path


def test_secretary_uses_center_and_migrates_voice_setting(tmp_path):
    from Plugins.Bot.secretaria import Secretary
    import json
    file=tmp_path/'secretary.json';file.write_text(json.dumps({'speak':True}),encoding='utf-8')
    store=WorkspaceStore(tmp_path/'db');notice=Mock()
    center=NotificationCenter(store,notice,Mock())
    secretary=Secretary(Mock(),store,Mock(),config_path=file)
    secretary.bind_notifications(center)
    assert center.snapshot()['settings']['read_aloud']
    center.configure({'read_aloud':False,'muted':[]})
    secretary.bind_notifications(center)
    assert not center.snapshot()['settings']['read_aloud']
    secretary.announce('Evento','Reunião',[{'url':'https://meet.google.com/abc','label':'Meet'}])
    assert center.snapshot()['items'][0]['links'][0]['label']=='Meet'
    assert 'speak' not in secretary.config()


def test_audio_ranges_allow_seek_without_full_file(tmp_path):
    from src.pia.http import audio_response
    import io
    file=tmp_path/'audio.mp3';file.write_bytes(b'0123456789')
    for request,status,expected in [('bytes=2-5',206,b'2345'),('bytes=-3',206,b'789'),('bytes=99-',416,b'')]:
        handler=SimpleNamespace(headers={'Range':request},send_response=Mock(),send_header=Mock(),end_headers=Mock(),wfile=io.BytesIO())
        audio_response(handler,file)
        handler.send_response.assert_called_once_with(status)
        assert handler.wfile.getvalue()==expected


def test_unread_chat_tracks_only_active_branch_and_read_watermark(tmp_path):
    store=WorkspaceStore(tmp_path/'db')
    chat=store.new_chat('Chat');store.append(chat,'user','hello');store.append(chat,'assistant','one')
    first=store.message_records(chat)[-1]['id']
    assert store.unread_chats()=={chat:1}
    store.read_chat(chat,first);assert store.unread_chats()=={}
    store.append(chat,'user','more');store.append(chat,'assistant','two')
    second=store.message_records(chat)[-1]['id'];assert store.unread_chats()=={chat:1}
    store.select_message(chat,first,descendants=False)
    assert store.unread_chats()=={}
    store.select_message(chat,second,descendants=False)
    assert store.unread_chats()=={chat:1}
    with pytest.raises(ValueError):store.read_chat(chat,99999)
    store.read_chat(chat,second);store.read_chat(chat,first)
    assert store.unread_chats()=={}


def test_notifications_read_by_source_preserves_other_unread(tmp_path):
    center=NotificationCenter(WorkspaceStore(tmp_path/'db'),Mock(),Mock())
    center.publish('Apps/music','One','ready');center.publish('Bot/secretaria','Two','event')
    center.read(source='Apps/music')
    assert center.snapshot()['counts']=={'Bot/secretaria':1}


def test_read_state_migration_does_not_mark_old_history_unread(tmp_path):
    import sqlite3
    file=tmp_path/'legacy.db'
    with sqlite3.connect(file) as db:
        db.executescript("CREATE TABLE chats(id TEXT PRIMARY KEY,title TEXT,created REAL);CREATE TABLE messages(id INTEGER PRIMARY KEY,chat TEXT,role TEXT,text TEXT);INSERT INTO chats VALUES('old','Old',1);INSERT INTO messages VALUES(1,'old','user','question');INSERT INTO messages VALUES(2,'old','assistant','answer');")
    store=WorkspaceStore(file)
    assert store.unread_chats()=={}
    store.append('old','assistant','new')
    assert store.unread_chats()=={'old':1}
    assert WorkspaceStore(file).unread_chats()=={'old':1}


def test_deleting_read_reply_does_not_hide_next_reply(tmp_path):
    store=WorkspaceStore(tmp_path/'db');chat=store.new_chat()
    store.append(chat,'user','hello');store.append(chat,'assistant','first')
    identity=store.message_records(chat)[-1]['id'];store.read_chat(chat,identity)
    store.remove_message(chat,identity);store.append(chat,'assistant','replacement')
    assert store.unread_chats()=={chat:1}
