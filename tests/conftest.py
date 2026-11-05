"""Every test gets an isolated profile and vault; never touch personal credentials."""
import pytest
import tempfile

class MemoryVault:
    def __init__(self):self.items={}
    def get(self,name):return self.items.get(name)
    def set(self,name,value):self.items[name]=value
    def delete(self,name):self.items.pop(name,None)

# Collection imports config modules before fixtures execute.
from src import settings_store,user_paths
from pathlib import Path
_collection_profile=tempfile.TemporaryDirectory(prefix='pia-test-profile-')
user_paths.USER_DIR=Path(_collection_profile.name)
settings_store._store=settings_store.SettingsStore(user_paths.USER_DIR/'workspace.sqlite3',MemoryVault())

@pytest.fixture(autouse=True)
def isolated_profile(tmp_path,monkeypatch):
    from src import settings_store,user_paths
    store=settings_store.SettingsStore(tmp_path/'profile/workspace.sqlite3',MemoryVault())
    monkeypatch.setattr(settings_store,'_store',store)
    monkeypatch.setattr(user_paths,'USER_DIR',tmp_path/'profile')
    return store
