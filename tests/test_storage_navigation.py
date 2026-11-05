from src.settings_store import get_store,save_document,document
"""Storage jobs use simulated clients, never real buckets or credentials."""
from types import SimpleNamespace
from unittest.mock import Mock
from pathlib import Path
import threading
import json
import pytest
from botocore.exceptions import ClientError
from Plugins.Apps.object_storage import web_api,local_files
from Plugins.Connectors.object_storage.service import ObjectStorage


def run_action(monkeypatch,store,action,data):
    monkeypatch.setattr(web_api,'storage',lambda:store)
    finished=threading.Event();events=[]
    class Job:
        id='fixture';cancelled=threading.Event()
        def emit(self,kind,**values):
            events.append((kind,values))
            if kind in ('done','error'):finished.set()
    monkeypatch.setattr(web_api,'Job',Job)
    context=SimpleNamespace(jobs={},native_handler=Mock())
    result=web_api.handle(action,data,context)
    assert result=={'job':'fixture'}
    assert finished.wait(5)
    return events


def storage():
    client=Mock();client.exceptions.ClientError=ClientError
    client.head_object.side_effect=ClientError({'Error':{'Code':'404'},'ResponseMetadata':{'HTTPStatusCode':404}},'HeadObject')
    store=Mock();store.client.return_value=client;store.bucket.return_value='bucket'
    store.key.side_effect=lambda key:key
    return store,client


def test_drag_move_keeps_nested_paths_and_rejects_descendants(monkeypatch):
    store,client=storage()
    store.objects.return_value=[{'Key':'source/a.txt'},{'Key':'source/deep/b.txt'}]
    events=run_action(monkeypatch,store,'move-many',{'account':'a','bucket':'bucket','keys':['source/','source/a.txt'],'target':'dest/'})
    assert events[-1][0]=='done'
    assert [(c.args[0],c.args[1]) for c in store.copy.call_args_list]==[('source/a.txt','dest/source/a.txt'),('source/deep/b.txt','dest/source/deep/b.txt')]
    with pytest.raises(ValueError,match='fora da origem'):
        web_api.handle('move-many',{'keys':['source/'],'target':'source/child/'},None)


def test_drag_move_preflights_conflicts_before_any_copy(monkeypatch):
    store,client=storage();client.head_object.side_effect=None
    events=run_action(monkeypatch,store,'move-many',{'keys':['a.txt'],'target':'dest/'})
    assert events[-1][0]=='error'
    assert 'Já existe' in events[-1][1]['error']
    store.copy.assert_not_called()


def test_local_download_is_bounded_and_uses_opaque_handles(monkeypatch,tmp_path):
    store,client=storage();client.head_object.side_effect=None
    client.head_object.return_value={'ContentLength':3}
    def download(bucket,key,path,Callback):Path(path).write_bytes(b'abc');Callback(3)
    client.download_file.side_effect=download
    monkeypatch.setattr(local_files,'ROOT',tmp_path)
    events=run_action(monkeypatch,store,'prepare-local',{'account':'a','bucket':'bucket','key':'folder/CON.txt'})
    value=events[-1][1]['result']
    assert local_files.resolve(value['token']).read_bytes()==b'abc'
    assert 'path' not in value
    with pytest.raises(ValueError):local_files.resolve(str(tmp_path/'elsewhere'))
    client.head_object.return_value={'ContentLength':3*1024**3}
    client.download_file.reset_mock()
    events=run_action(monkeypatch,store,'prepare-local',{'key':'huge.bin'})
    assert events[-1][0]=='error'
    client.download_file.assert_not_called()


def test_account_colors_are_stable_and_env_overrides_validated(monkeypatch,tmp_path):
    (tmp_path/'config.json').write_text('{"accounts":[{"id":"one","name":"One"},{"id":"two","name":"Two"}]}')
    store=ObjectStorage(root=tmp_path)
    save_document('Connectors/object_storage',json.loads((tmp_path/'config.json').read_text()))
    first=store.accounts()
    assert store.accounts()==first
    (tmp_path/'.env').write_text('OBJECT_STORAGE_ACCOUNT_COLORS=\'{"one":"#123456"}\'')
    get_store().save('Connectors/object_storage',{'OBJECT_STORAGE_ACCOUNT_COLORS':'{"one":"#123456"}'})
    assert store.accounts()[0]['color']=='#123456'
    (tmp_path/'.env').write_text('OBJECT_STORAGE_ACCOUNT_COLORS=\'{"one":"red"}\'')
    get_store().save('Connectors/object_storage',{'OBJECT_STORAGE_ACCOUNT_COLORS':'{"one":"red"}'})
    with pytest.raises(ValueError,match='Cor de conta'):store.accounts()


def test_native_drag_copies_prepared_file_and_open_uses_system_handler(monkeypatch,tmp_path):
    from Plugins.Apps.object_storage import native
    from PyQt6.QtCore import Qt
    file=tmp_path/'fixture.txt';file.write_text('fixture')
    monkeypatch.setattr(native,'resolve',lambda token:file)
    drag=Mock();factory=Mock(return_value=drag)
    monkeypatch.setattr(native,'QDrag',factory)
    monkeypatch.setattr(native.QApplication,'mouseButtons',lambda:Qt.MouseButton.LeftButton)
    monkeypatch.setattr(native.QDesktopServices,'openUrl',Mock(return_value=True))
    app=native.NativeApp(SimpleNamespace(window=Mock()),None)
    app.handle('drag-local',{'token':'fixture'})
    assert Path(drag.setMimeData.call_args.args[0].urls()[0].toLocalFile())==file
    drag.exec.assert_called_once_with(Qt.DropAction.CopyAction)
    app.handle('open-local',{'token':'fixture'})
    native.QDesktopServices.openUrl.assert_called_once()
