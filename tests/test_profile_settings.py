import base64
import json
from pathlib import Path
import pytest
from types import SimpleNamespace
from src.settings_store import SettingsStore,get,get_store,document
from src.config_transfer import export_config,preview_config,import_config
from src.profile_migration import initialize_profile
from src.workspace_store import WorkspaceStore

class Vault:
    def __init__(self):self.data={};self.reject=None
    def get(self,name):return self.data.get(name)
    def set(self,name,value):
        if name==self.reject:raise RuntimeError('Cofre bloqueado')
        self.data[name]=value
    def delete(self,name):self.data.pop(name,None)


def test_no_env_override_and_secrets_never_enter_sqlite(isolated_profile,monkeypatch):
    monkeypatch.setenv('PORT','9999')
    isolated_profile.save('general',{'PORT':'8763','OPENAI_COMPAT_API_KEY':'fixture-secret'})
    assert get('PORT')=='8763'
    assert get('OPENAI_COMPAT_API_KEY')=='fixture-secret'
    assert b'fixture-secret' not in isolated_profile.path.read_bytes()
    assert isolated_profile.vault.get('setting:general:OPENAI_COMPAT_API_KEY')=='fixture-secret'


@pytest.mark.parametrize('path', ['/settings/export', '/settings/import-preview', '/settings/import', '/settings/google-backup'])
def test_manual_credential_transfer_routes_are_removed(path):
    from src.pia.service import WorkspaceService

    with pytest.raises(ValueError, match='Operação não encontrada'):
        WorkspaceService._dispatch(SimpleNamespace(), 'POST', path, {}, {})


def test_encrypted_roundtrip_and_tamper_rejection(tmp_path):
    source=SettingsStore(tmp_path/'source.db',Vault());target=SettingsStore(tmp_path/'target.db',Vault())
    source.save('general',{'PORT':'1234','GEMINI_API_KEY':'private-fixture'})
    source.set_document('Connectors/google',{'client_id':'client','accounts':[{'id':'personal'}]})
    source.vault.set('token:google:personal',{'access_token':'fixture-token'});source.register_secret('token:google:personal')
    bundle=export_config('uma senha longa e privada',source)
    assert b'private-fixture' not in base64.b64decode(bundle['data'])
    assert preview_config(bundle['data'],'uma senha longa e privada')['credentials']==2
    with pytest.raises(ValueError,match='Senha incorreta'):import_config(bundle['data'],'outra senha longa',target)
    assert not target.path.exists()
    import_config(bundle['data'],'uma senha longa e privada',target)
    assert target.values('general')['GEMINI_API_KEY']=='private-fixture'
    assert target.vault.get('token:google:personal')['access_token']=='fixture-token'
    assert b'private-fixture' not in target.path.read_bytes()
    bad=bytearray(base64.b64decode(bundle['data']));bad[-1]^=1
    with pytest.raises(ValueError,match='adulterado'):preview_config(base64.b64encode(bad).decode(),'uma senha longa e privada')


def test_import_rolls_back_vault_and_database_on_failure(tmp_path):
    source=SettingsStore(tmp_path/'source.db',Vault());target=SettingsStore(tmp_path/'target.db',Vault())
    source.save('general',{'GEMINI_API_KEY':'new','GROQ_API_KEY':'second'})
    target.save('general',{'GEMINI_API_KEY':'old','PORT':'8764'})
    target.vault.reject='setting:general:GROQ_API_KEY'
    bundle=export_config('senha suficiente para teste',source)
    with pytest.raises(RuntimeError,match='bloqueado'):import_config(bundle['data'],'senha suficiente para teste',target)
    assert target.values('general')['GEMINI_API_KEY']=='old'
    assert target.values('general')['PORT']=='8764'


def test_migration_preserves_history_moves_files_and_only_removes_confirmed_sources(tmp_path):
    root=tmp_path/'app';profile=tmp_path/'documents/pia';(root/'config').mkdir(parents=True)
    (root/'config/.env').write_text('GEMINI_API_KEY__SECRET=fixture\nPORT__INT=8763\n')
    (root/'data/chat-images').mkdir(parents=True);(root/'data/chat-images/a.png').write_bytes(b'png')
    old=WorkspaceStore(root/'data/workspace.sqlite3');chat=old.new_chat('Mesa');old.append(chat,'user','Oi')
    store=SettingsStore(profile/'workspace.sqlite3',Vault())
    initialize_profile(root,store,profile)
    assert WorkspaceStore(store.path).messages(chat)[0]['content']=='Oi'
    assert store.values('general')['PORT']=='8763'
    assert store.vault.get('setting:general:GEMINI_API_KEY')=='fixture'
    assert not (root/'config/.env').exists() and not (root/'data/workspace.sqlite3').exists()
    assert (profile/'chat/a.png').read_bytes()==b'png'
    initialize_profile(root,store,profile)
    assert len(WorkspaceStore(store.path).messages(chat))==1


def test_blocked_vault_leaves_original_credentials_in_place(tmp_path):
    root=tmp_path/'app';(root/'config').mkdir(parents=True)
    original=root/'config/.env';original.write_text('GEMINI_API_KEY__SECRET=fixture\n')
    vault=Vault();vault.reject='setting:general:GEMINI_API_KEY'
    store=SettingsStore(tmp_path/'profile/workspace.sqlite3',vault)
    with pytest.raises(RuntimeError):initialize_profile(root,store,tmp_path/'profile')
    assert original.exists()


def test_migration_merges_into_existing_profile_and_keeps_active_branch(tmp_path):
    root=tmp_path/'app';(root/'data').mkdir(parents=True)
    source=WorkspaceStore(root/'data/workspace.sqlite3');chat=source.new_chat('Antiga')
    source.append(chat,'user','Pergunta');source.append(chat,'assistant','Resposta antiga')
    original=source.message_records(chat)[-1]['id']
    source.select_message(chat,source.message_records(chat)[0]['id'],descendants=False)
    source.append(chat,'assistant','Alternativa')
    source.select_message(chat,original)
    profile=tmp_path/'profile';profile.mkdir()
    target=WorkspaceStore(profile/'workspace.sqlite3');other=target.new_chat('Atual');target.append(other,'user','Nova')
    store=SettingsStore(target.path,Vault())
    initialize_profile(root,store,profile)
    assert target.messages(chat)[-1]['content']=='Resposta antiga'
    assert target.messages(other)[0]['content']=='Nova'
    assert len(target.message_records(chat)[-1]['alternatives'])==2


def test_managed_configuration_files_and_credential_files_are_portable(tmp_path):
    source=SettingsStore(tmp_path/'one/workspace.sqlite3',Vault());target=SettingsStore(tmp_path/'two/workspace.sqlite3',Vault())
    path=source.path.parent/'files/general/example.txt';path.parent.mkdir(parents=True);path.write_text('configuration')
    source.save('general',{'INPUT_FILE__FILE':str(path)})
    source.save_file('general','PRIVATE_KEY_FILE','private.pem',b'private fixture')
    assert not (source.path.parent/'files/private.pem').exists()
    bundle=export_config('senha longa para migracao',source)
    import_config(bundle['data'],'senha longa para migracao',target)
    destination=target.path.parent/'files/general/example.txt'
    assert destination.read_text()=='configuration'
    assert target.values('general')['INPUT_FILE']==str(destination)
    assert target.vault.get('setting:general:PRIVATE_KEY_FILE')['data']==base64.b64encode(b'private fixture').decode()
    assert b'private fixture' not in target.path.read_bytes()


def test_os_vault_chunks_large_credentials_and_keeps_old_value_on_failure(monkeypatch):
    import sys
    from src.settings_store import SystemVault
    class Backend:
        priority=5
        def __init__(self):self.items={};self.fail=False
        def get_password(self,service,name):return self.items.get(name)
        def set_password(self,service,name,value):
            assert len(value)<=1000
            if self.fail and ':chunk:' in name:raise RuntimeError('Cofre bloqueado')
            self.items[name]=value
        def delete_password(self,service,name):self.items.pop(name,None)
    backend=Backend();monkeypatch.setitem(sys.modules,'keyring',SimpleNamespace(get_keyring=lambda:backend))
    vault=SystemVault();value={'access_token':'x'*6000,'filename':'credencial'}
    vault.set('token:google:fixture',value)
    assert vault.get('token:google:fixture')==value
    backend.fail=True
    with pytest.raises(RuntimeError):vault.set('token:google:fixture',{'access_token':'y'*7000})
    assert vault.get('token:google:fixture')==value
    backend.fail=False;vault.delete('token:google:fixture')
    assert backend.items=={}


def test_migration_relocates_managed_file_references(tmp_path):
    root=tmp_path/'app';files=root/'config/files';files.mkdir(parents=True)
    asset=files/'example.txt';asset.write_text('fixture')
    (root/'config/.env').write_text('INPUT_FILE__FILE='+asset.as_posix())
    store=SettingsStore(tmp_path/'profile/workspace.sqlite3',Vault())
    initialize_profile(root,store,store.path.parent)
    saved=Path(store.values('general')['INPUT_FILE'])
    assert saved==store.path.parent/'files/config/example.txt'
    assert saved.read_text()=='fixture'
    assert not asset.exists()
