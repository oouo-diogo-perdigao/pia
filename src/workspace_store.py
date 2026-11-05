"""Local chat history and drafts, independent of Qt and provider SDKs."""
import json
import sqlite3
import time
import uuid
from pathlib import Path
from contextlib import contextmanager


class WorkspaceStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS chats(id TEXT PRIMARY KEY, title TEXT, created REAL);
                CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, chat TEXT, role TEXT, text TEXT);
                CREATE TABLE IF NOT EXISTS values_store(key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS folders(id TEXT PRIMARY KEY, name TEXT, created REAL);
            ''')
            columns = {c[1] for c in db.execute('PRAGMA table_info(chats)')}
            for name, definition in [('folder','TEXT'), ('pinned','INTEGER DEFAULT 0'), ('archived','INTEGER DEFAULT 0'), ('leaf','INTEGER')]:
                if name not in columns:
                    db.execute(f'ALTER TABLE chats ADD COLUMN {name} {definition}')
            if 'parent' not in {c[1] for c in db.execute('PRAGMA table_info(messages)')}:
                db.execute('ALTER TABLE messages ADD COLUMN parent INTEGER')
                for (chat,) in db.execute('SELECT id FROM chats').fetchall():
                    previous = None
                    for (identity,) in db.execute('SELECT id FROM messages WHERE chat=? ORDER BY id', (chat,)).fetchall():
                        db.execute('UPDATE messages SET parent=? WHERE id=?', (previous, identity))
                        previous = identity
                    db.execute('UPDATE chats SET leaf=? WHERE id=?', (previous, chat))
            if 'read_message' not in {c[1] for c in db.execute('PRAGMA table_info(chats)')}:
                db.execute('ALTER TABLE chats ADD COLUMN read_message INTEGER DEFAULT 0')
                # Existing history is not a backlog of new notifications.
                db.execute('UPDATE chats SET read_message=COALESCE((SELECT MAX(id) FROM messages WHERE chat=chats.id),0)')

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def new_chat(self, title='Nova conversa'):
        chat = uuid.uuid4().hex
        with self.connect() as db:
            db.execute('INSERT INTO chats(id,title,created) VALUES(?,?,?)', (chat, title, time.time()))
        return chat

    def chats(self):
        with self.connect() as db:
            return db.execute('SELECT id,title FROM chats ORDER BY created DESC').fetchall()

    def unread_chats(self):
        with self.connect() as db:
            return dict(db.execute('''WITH RECURSIVE active(id,parent,role,chat,seen) AS (
                SELECT m.id,m.parent,m.role,m.chat,c.read_message FROM messages m
                JOIN chats c ON c.leaf=m.id AND c.id=m.chat WHERE m.id>c.read_message
                UNION ALL
                SELECT m.id,m.parent,m.role,m.chat,a.seen FROM messages m
                JOIN active a ON m.id=a.parent AND m.chat=a.chat WHERE m.id>a.seen
            ) SELECT chat,COUNT(*) FROM active WHERE role='assistant' GROUP BY chat''').fetchall())

    def read_chat(self,chat,through):
        if type(through) is not int:raise ValueError('Mensagem inválida.')
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM messages WHERE id=? AND chat=? AND role='assistant'",(through,chat)).fetchone():
                raise ValueError('Mensagem não encontrada.')
            db.execute('UPDATE chats SET read_message=MAX(read_message,?) WHERE id=?',(through,chat))

    def message_records(self, chat):
        with self.connect() as db:
            row = db.execute('SELECT leaf FROM chats WHERE id=?', (chat,)).fetchone()
            leaf = row[0] if row else None
            nodes = {i: dict(id=i, parent=p, role=r, content=t) for i,p,r,t in db.execute(
                'SELECT id,parent,role,text FROM messages WHERE chat=? ORDER BY id', (chat,))}
        path, seen = [], set()
        while leaf in nodes and leaf not in seen:
            seen.add(leaf)
            node = dict(nodes[leaf])
            siblings = [n['id'] for n in nodes.values() if n['parent'] == node['parent']]
            node['alternatives'] = siblings
            node['alternative'] = siblings.index(leaf)
            path.append(node)
            leaf = node['parent']
        return path[::-1]

    def messages(self, chat):
        return [{'role': n['role'], 'content': n['content']} for n in self.message_records(chat)]

    def chat_records(self):
        with self.connect() as db:
            return [dict(id=i,title=t,created=c,folder=f,pinned=bool(p),archived=bool(a)) for i,t,c,f,p,a in db.execute(
                'SELECT id,title,created,folder,pinned,archived FROM chats ORDER BY pinned DESC,created DESC')]

    def select_message(self, chat, identity, descendants=True):
        with self.connect() as db:
            if identity is not None and not db.execute('SELECT 1 FROM messages WHERE id=? AND chat=?', (identity,chat)).fetchone():
                raise ValueError('Mensagem não encontrada.')
            if descendants:
                while True:
                    children = [i for (i,) in db.execute('SELECT id FROM messages WHERE chat=? AND parent=? ORDER BY id', (chat,identity))]
                    if not children: break
                    saved = db.execute('SELECT value FROM values_store WHERE key=?',(f'branch:{chat}:{identity}',)).fetchone()
                    preferred = json.loads(saved[0]) if saved else None
                    identity = preferred if preferred in children else children[-1]
            db.execute('UPDATE chats SET leaf=? WHERE id=?', (identity,chat))
            node = identity
            while node is not None:
                parent = db.execute('SELECT parent FROM messages WHERE chat=? AND id=?',(chat,node)).fetchone()[0]
                db.execute('INSERT OR REPLACE INTO values_store VALUES(?,?)',(f'branch:{chat}:{parent}',json.dumps(node)))
                node = parent

    def fork(self, chat, identity):
        records = self.message_records(chat)
        if identity not in [n['id'] for n in records]: raise ValueError('Mensagem não encontrada.')
        result = self.new_chat('Fork · ' + next(c['title'] for c in self.chat_records() if c['id']==chat))
        for node in records:
            self.append(result,node['role'],node['content'])
            if node['id']==identity: break
        return result

    def remove_message(self, chat, identity):
        with self.connect() as db:
            row = db.execute('SELECT parent FROM messages WHERE id=? AND chat=?',(identity,chat)).fetchone()
            if not row: raise ValueError('Mensagem não encontrada.')
            doomed = [identity]
            for item in doomed:
                doomed.extend(i for (i,) in db.execute('SELECT id FROM messages WHERE chat=? AND parent=?',(chat,item)))
            leaf = db.execute('SELECT leaf FROM chats WHERE id=?',(chat,)).fetchone()[0]
            if leaf in doomed: db.execute('UPDATE chats SET leaf=? WHERE id=?',(row[0],chat))
            db.executemany('DELETE FROM messages WHERE id=?',[(i,) for i in doomed])
            # SQLite can reuse the largest deleted id. Keep future replies unread.
            db.execute('UPDATE chats SET read_message=MIN(read_message,COALESCE((SELECT MAX(id) FROM messages WHERE chat=?),0)) WHERE id=?',(chat,chat))
            if leaf in doomed:
                sibling = db.execute('SELECT id FROM messages WHERE chat=? AND parent IS ? ORDER BY id DESC LIMIT 1',(chat,row[0])).fetchone()
                replacement = sibling[0] if sibling else row[0]
                if sibling:
                    while True:
                        children = [i for (i,) in db.execute('SELECT id FROM messages WHERE chat=? AND parent=? ORDER BY id',(chat,replacement))]
                        if not children: break
                        saved = db.execute('SELECT value FROM values_store WHERE key=?',(f'branch:{chat}:{replacement}',)).fetchone()
                        preferred = json.loads(saved[0]) if saved else None
                        replacement = preferred if preferred in children else children[-1]
                db.execute('UPDATE chats SET leaf=? WHERE id=?',(replacement,chat))

    def folders(self):
        with self.connect() as db:
            return [dict(id=i, name=n) for i, n in db.execute('SELECT id,name FROM folders ORDER BY name COLLATE NOCASE')]

    def save_folder(self, name, folder=None):
        if not isinstance(name, str) or not name.strip():
            raise ValueError('Informe um nome para a pasta.')
        folder = folder or uuid.uuid4().hex
        with self.connect() as db:
            db.execute('INSERT INTO folders(id,name,created) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name',
                       (folder, name.strip()[:120], time.time()))
        return folder

    def remove_folder(self, folder):
        with self.connect() as db:
            db.execute('UPDATE chats SET folder=NULL WHERE folder=?', (folder,))
            db.execute('DELETE FROM folders WHERE id=?', (folder,))

    def update_chat(self, chat, *, title=None, folder=None, move=False, pinned=None, archived=None):
        with self.connect() as db:
            if not db.execute('SELECT 1 FROM chats WHERE id=?', (chat,)).fetchone():
                raise ValueError('Conversa não encontrada.')
            if title is not None:
                if not title.strip():
                    raise ValueError('O título não pode ficar vazio.')
                db.execute('UPDATE chats SET title=? WHERE id=?', (title.strip()[:120], chat))
            for name,value in [('pinned',pinned),('archived',archived)]:
                if value is not None:
                    if not isinstance(value,bool): raise ValueError('Valor inválido.')
                    db.execute(f'UPDATE chats SET {name}=? WHERE id=?',(int(value),chat))
            if move:
                if folder and not db.execute('SELECT 1 FROM folders WHERE id=?', (folder,)).fetchone():
                    raise ValueError('Pasta não encontrada.')
                db.execute('UPDATE chats SET folder=? WHERE id=?', (folder or None, chat))

    def delete_chat(self, chat):
        with self.connect() as db:
            db.execute('DELETE FROM messages WHERE chat=?', (chat,))
            db.execute('DELETE FROM chats WHERE id=?', (chat,))
            db.execute('DELETE FROM values_store WHERE key=?', ('draft:' + chat,))
            db.execute('DELETE FROM values_store WHERE key LIKE ?', ('branch:' + chat + ':%',))

    def append(self, chat, role, text):
        with self.connect() as db:
            row = db.execute('SELECT leaf FROM chats WHERE id=?',(chat,)).fetchone()
            if not row: raise ValueError('Conversa não encontrada.')
            cursor = db.execute('INSERT INTO messages(chat,role,text,parent) VALUES(?,?,?,?)', (chat, role, text,row[0]))
            db.execute('UPDATE chats SET leaf=? WHERE id=?',(cursor.lastrowid,chat))
            db.execute('INSERT OR REPLACE INTO values_store VALUES(?,?)',(f'branch:{chat}:{row[0]}',json.dumps(cursor.lastrowid)))
            if role == 'user':
                db.execute("UPDATE chats SET title=? WHERE id=? AND title='Nova conversa'", (text[:60], chat))

    def get(self, key, default=None):
        with self.connect() as db:
            row = db.execute('SELECT value FROM values_store WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO values_store VALUES(?,?)', (key, json.dumps(value)))

    def claim(self, key):
        """Persistent, atomic deduplication across polling cycles and restarts."""
        with self.connect() as db:
            return db.execute('INSERT OR IGNORE INTO values_store VALUES(?,?)', (key, 'true')).rowcount == 1
