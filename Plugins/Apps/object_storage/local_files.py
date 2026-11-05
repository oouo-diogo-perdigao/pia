"""Private, session-scoped handles for downloaded objects. No arbitrary paths from UI."""
import secrets
import threading
import time
from pathlib import Path
from src.config_paths import BASE_DIR

ROOT=BASE_DIR/'cache/Apps/object_storage/downloads'
_files={}
_lock=threading.RLock()

def register(path):
    path=Path(path).resolve()
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file() or path.is_symlink():
        raise ValueError('Arquivo local inválido.')
    token=secrets.token_urlsafe(32)
    with _lock:_files[token]=(path,time.monotonic())
    return token

def resolve(token):
    with _lock:record=_files.get(token)
    if not record or time.monotonic()-record[1]>21600:raise ValueError('Arquivo local expirado. Prepare novamente.')
    path=record[0]
    if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError('Arquivo local indisponível.')
    return path
