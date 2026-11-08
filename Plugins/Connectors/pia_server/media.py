"""Local, persistent upload queue for generated media."""

from hashlib import sha256
from pathlib import Path
import time
from urllib.parse import urlsplit
from uuid import uuid4

import requests

from src.plugin_logs import write
from src.settings_store import get_store, values

from .service import SECTION

FORMATS = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
           '.bmp': 'image/bmp', '.mp3': 'audio/mpeg', '.wav': 'audio/wav'}
TABLE = '''CREATE TABLE IF NOT EXISTS pia_server_media_queue(
    id TEXT PRIMARY KEY,device TEXT NOT NULL,path TEXT NOT NULL,mime TEXT NOT NULL,bytes INTEGER NOT NULL,
    modified INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
    retry REAL NOT NULL DEFAULT 0)'''


def device_key(config):
    identity = config['PIA_SERVER_URL'].rstrip('/') + '\n' + config['PIA_SERVER_DEVICE_TOKEN']
    return sha256(identity.encode()).hexdigest()


def enqueue(path):
    try:
        config = values(SECTION)
        if not config.get('PIA_SERVER_DEVICE_TOKEN'):
            return
        path = Path(path).resolve(strict=True)
        mime = FORMATS.get(path.suffix.lower())
        stat = path.stat()
        if not mime or not 0 < stat.st_size <= 100 * 1024 ** 2:
            raise ValueError('Formato ou tamanho inválido.')
        with get_store().connection() as db:
            db.execute(TABLE)
            db.execute('INSERT INTO pia_server_media_queue(id,device,path,mime,bytes,modified) VALUES(?,?,?,?,?,?)',
                       (str(uuid4()), device_key(config), str(path), mime, stat.st_size, stat.st_mtime_ns))
    except Exception:
        write(SECTION, 'mídia', 'Não foi possível enfileirar a cópia. O arquivo local foi preservado.')


def run():
    config = values(SECTION)
    token = config.get('PIA_SERVER_DEVICE_TOKEN', '')
    if not token:
        return
    url = urlsplit(config['PIA_SERVER_URL'])
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('', '/'):
        return
    store = get_store()
    device = device_key(config)
    with store.connection() as db:
        db.execute(TABLE)
    with requests.Session() as session:
        session.headers['Authorization'] = 'Bearer ' + token
        while values(SECTION).get('PIA_SERVER_DEVICE_TOKEN') == token:
            with store.connection() as db:
                item = db.execute('SELECT id,path,mime,bytes,modified,attempts FROM pia_server_media_queue '
                                  'WHERE device=? AND retry<=? ORDER BY rowid LIMIT 1', (device, time.time())).fetchone()
            if not item:
                time.sleep(10)
                continue
            identity, file, mime, size, modified, attempts = item
            path = Path(file)
            try:
                stat = path.stat()
                if stat.st_size != size or stat.st_mtime_ns != modified:
                    raise FileNotFoundError('Arquivo substituído.')
                with path.open('rb') as media:
                    response = session.post(f'https://{url.netloc}/device/media', data=media,
                                            headers={'Content-Type': mime, 'X-PIA-Media-Id': identity},
                                            timeout=(10, 180), allow_redirects=False)
                if response.status_code != 200 or not response.json().get('id'):
                    raise ValueError('Envio não confirmado.')
            except FileNotFoundError:
                write(SECTION, 'mídia', 'Arquivo local movido, removido ou substituído.')
            except (OSError, ValueError, requests.RequestException):
                with store.connection() as db:
                    db.execute('UPDATE pia_server_media_queue SET attempts=attempts+1,retry=? WHERE id=?',
                               (time.time() + min(3600, 30 * 2 ** min(attempts, 7)), identity))
                write(SECTION, 'mídia', 'Envio pendente. A cópia local foi preservada.')
                continue
            with store.connection() as db:
                db.execute('DELETE FROM pia_server_media_queue WHERE id=?', (identity,))
