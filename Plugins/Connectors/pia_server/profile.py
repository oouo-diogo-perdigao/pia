"""Serialization for the shared profile stored by PIA Server."""

import base64
import json

from src.config_transfer import PLAIN_MAGIC, decode, export_config

from .service import SECTION
from .remote import SECTIONS, managed_secret

TABLES = {
    'folders': ('id', 'name', 'created'),
    'chats': ('id', 'title', 'created', 'folder', 'pinned', 'archived', 'leaf', 'read_message'),
    'messages': ('id', 'chat', 'role', 'text', 'parent'),
}


def pack(payload):
    return base64.b64encode(PLAIN_MAGIC + json.dumps(payload, ensure_ascii=False).encode()).decode()


def history_rows(db):
    history = {name: db.execute(f"SELECT {','.join(columns)} FROM {name} ORDER BY id").fetchall()
               for name, columns in TABLES.items()}
    history['branches'] = db.execute("SELECT key,value FROM values_store WHERE key LIKE 'branch:%' ORDER BY key").fetchall()
    return {name: [list(row) for row in rows] for name, rows in history.items()}


def snapshot(store):
    backup = export_config('')
    payload = decode(backup['data'], '')
    payload['settings'] = [row for row in payload['settings'] if row[0] not in SECTIONS and row[0] != SECTION]
    payload['documents'] = [row for row in payload['documents'] if row[0] not in SECTIONS]
    payload['secrets'] = {key: secret for key, secret in payload['secrets'].items()
                          if not managed_secret(key) and not key.startswith('setting:' + SECTION + ':')}
    payload['preferences'] = [row for row in payload.get('preferences', []) if row[0] != 'notifications:settings']
    with store.connect() as db:
        db.execute('BEGIN')
        history = history_rows(db)
    return {'version': 1, 'backup': pack(payload), 'chats': history}


def validate_history(history):
    for name, columns in TABLES.items():
        rows = history.get(name)
        if not isinstance(rows, list) or any(not isinstance(row, list) or len(row) != len(columns) or
            any(value is not None and type(value) not in (str, int, float) for value in row) for row in rows):
            raise ValueError('Histórico do servidor inválido.')
        if len({row[0] for row in rows}) != len(rows):
            raise ValueError('Histórico do servidor contém registros duplicados.')
    branches = history.get('branches', [])
    if not isinstance(branches, list) or any(not isinstance(row, list) or len(row) != 2 or
        not all(isinstance(value, str) for value in row) or not row[0].startswith('branch:') for row in branches):
        raise ValueError('Ramificações de conversa inválidas.')
    return history


def shared_backup(data):
    payload = decode(data, '')
    if (any(row[0] in SECTIONS or row[0] == SECTION for row in payload['settings']) or
        any(row[0] in SECTIONS for row in payload['documents']) or
        any(managed_secret(key) or key.startswith('setting:' + SECTION + ':') for key in payload['secrets']) or
        any(row[0] == 'notifications:settings' for row in payload.get('preferences', []))):
        raise ValueError('O perfil remoto contém configurações locais do computador.')
    return payload


def update_history(db, before, after):
    tables = {**TABLES, 'values_store': ('key', 'value')}
    for table, columns in tables.items():
        group = 'branches' if table == 'values_store' else table
        previous, current = before[group], after[group]
        db.executemany(f'DELETE FROM {table} WHERE {columns[0]}=?',
                       ((key,) for key in previous.keys() - current.keys()))
        db.executemany(f"INSERT OR REPLACE INTO {table}({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                       (row for key, row in current.items() if previous.get(key) != row))
