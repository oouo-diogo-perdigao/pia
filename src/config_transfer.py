"""Portable authenticated-encryption backup. Passwords/plaintext never touch disk."""
import base64
import json
import os
import re
from contextlib import closing
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from .settings_store import get_store,synchronized
from .user_paths import USER_DIR

MAGIC=b'PIA-BACKUP-1\n'
LIMIT=16*1024**2


def key(password,salt):
    if not isinstance(password,str) or len(password)<12 or len(password)>1024:
        raise ValueError('Use uma senha de 12 a 1024 caracteres para o arquivo de migração.')
    return Scrypt(salt=salt,length=32,n=2**15,r=8,p=1).derive(password.encode('utf-8'))


@synchronized
def export_config(password,store=None):
    store=store or get_store()
    secret_names=[row[0] for row in store.rows('vault_entries')]
    secrets={name:store.vault.get(name) for name in secret_names}
    secrets={name:value for name,value in secrets.items() if value is not None}
    rows=store.rows('settings')
    if any(row[4] and row[4] not in secrets for row in rows):raise ValueError('Há credenciais indisponíveis no cofre. Reconecte as contas antes de exportar.')
    payload={'version':1,'settings':rows,'documents':store.rows('documents'),
             'secrets':secrets,'user_dir':str(store.path.parent),'files':{}}
    files=store.path.parent/'files'
    if files.is_dir():
        for path in files.rglob('*'):
            if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(files.resolve()):
                if path.stat().st_size>5*1024**2:raise ValueError('Arquivo de configuração excede 5 MiB.')
                payload['files'][path.relative_to(files).as_posix()]=base64.b64encode(path.read_bytes()).decode()
    if store.path.exists():
        import sqlite3
        with closing(sqlite3.connect(store.path)) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='values_store'").fetchone():
                payload['preferences']=db.execute("SELECT key,value FROM values_store WHERE key LIKE 'ui:%' OR key='notifications:settings'").fetchall()
    raw=json.dumps(payload).encode('utf-8')
    if len(raw)>LIMIT:raise ValueError('Configurações excedem o limite de 16 MiB.')
    salt=os.urandom(16);nonce=os.urandom(12)
    blob=MAGIC+salt+nonce+AESGCM(key(password,salt)).encrypt(nonce,raw,MAGIC)
    return {'filename':'pia-configuracoes.pia-backup','data':base64.b64encode(blob).decode('ascii')}


def decode(data,password):
    if not isinstance(data,str) or len(data)>24*1024**2:raise ValueError('Arquivo de migração inválido ou maior que 16 MiB.')
    try:blob=base64.b64decode(data,validate=True)
    except ValueError:raise ValueError('Arquivo de migração inválido.') from None
    if not blob.startswith(MAGIC) or len(blob)<len(MAGIC)+44:raise ValueError('Formato de migração não reconhecido.')
    offset=len(MAGIC);salt=blob[offset:offset+16];nonce=blob[offset+16:offset+28]
    try:raw=AESGCM(key(password,salt)).decrypt(nonce,blob[offset+28:],MAGIC)
    except InvalidTag:raise ValueError('Senha incorreta ou arquivo adulterado.') from None
    if len(raw)>LIMIT:raise ValueError('Arquivo excede o limite de 16 MiB.')
    try:value=json.loads(raw)
    except ValueError:raise ValueError('Conteúdo de migração inválido.') from None
    if not isinstance(value,dict) or value.get('version')!=1 or not isinstance(value.get('settings'),list) or not isinstance(value.get('documents'),list) or not isinstance(value.get('secrets'),dict):raise ValueError('Conteúdo de migração inválido.')
    for row in value['settings']:
        if not isinstance(row,list) or len(row)!=5 or not all(isinstance(row[i],str) for i in (0,1,3)):raise ValueError('Configuração inválida no arquivo.')
        if row[4] is not None and (not isinstance(row[4],str) or row[4] not in value['secrets']):raise ValueError('Credencial ausente no arquivo.')
        from .settings_store import sensitive
        if sensitive(row[1],row[3]) and not row[4]:raise ValueError('Credencial sem referência ao cofre no arquivo.')
        if row[4] and row[4]!='setting:'+row[0]+':'+row[1]:raise ValueError('Referência de credencial inválida.')
        if row[3] not in ('string','secret','bool','int','float','path','file'):raise ValueError('Tipo inválido no arquivo.')
        if row[4] is None:
            field=json.loads(row[2])
            if not isinstance(field,str):raise ValueError('Valor de configuração inválido.')
            if row[3] not in ('path','file'):
                from .env_types import validate
                validate(row[1]+'__'+row[3],field)
    if any(not isinstance(row,list) or len(row)!=2 or not isinstance(row[0],str) for row in value['documents']):raise ValueError('Documento inválido no arquivo.')
    for name in value['secrets']:
        if not re.fullmatch(r'(setting|token|client|storage|file):[^\x00\r\n]{1,300}',name):raise ValueError('Entrada de cofre inválida.')
    for _,raw in value['documents']:json.loads(raw)
    from pathlib import PurePosixPath
    if not isinstance(value.get('files',{}),dict):raise ValueError('Arquivos de configuração inválidos.')
    for name,data in value.get('files',{}).items():
        path=PurePosixPath(name)
        if path.is_absolute() or not path.parts or any(part in ('..','.') or ':' in part or '\\' in part for part in path.parts):raise ValueError('Caminho de arquivo inválido.')
        if len(base64.b64decode(data,validate=True))>5*1024**2:raise ValueError('Arquivo de configuração excede 5 MiB.')
    return value


def preview_config(data,password):
    value=decode(data,password)
    return {'settings':len(value['settings']),'documents':len(value['documents']),'credentials':len(value['secrets']),
            'sections':sorted(set(row[0] for row in value['settings']))}


@synchronized
def import_config(data,password,store=None):
    value=decode(data,password);store=store or get_store();undo=[];file_undo=[]
    # Runtime locations are recomputed on the destination. Paths to external tools
    # and user-selected resources must be reviewed in the UI after moving OS.
    from .profile_migration import portable_settings,portable_documents
    settings=portable_settings(value['settings'],value.get('user_dir',''),store.path.parent)
    documents=portable_documents(value['documents'],value.get('user_dir',''))
    with store.connection() as db:
        try:
            for name,secret in value['secrets'].items():
                undo.append((name,store.vault.get(name)));store.vault.set(name,secret)
                if store.vault.get(name)!=secret:raise RuntimeError('O cofre não confirmou a importação.')
                db.execute('INSERT OR IGNORE INTO vault_entries VALUES(?)',(name,))
            for row in settings:db.execute('INSERT OR REPLACE INTO settings VALUES(?,?,?,?,?)',row)
            for row in documents:db.execute('INSERT OR REPLACE INTO documents VALUES(?,?)',row)
            for name,encoded in value.get('files',{}).items():
                target=store.path.parent/'files'/name
                if target.is_symlink() or not target.resolve().is_relative_to((store.path.parent/'files').resolve()):raise ValueError('Destino de arquivo inválido.')
                file_undo.append((target,target.read_bytes() if target.exists() else None))
                target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(base64.b64decode(encoded));target.chmod(0o600)
            preferences=value.get('preferences',[])
            db.execute('CREATE TABLE IF NOT EXISTS values_store(key TEXT PRIMARY KEY,value TEXT)')
            for name,raw in preferences:
                if name.startswith('ui:') or name=='notifications:settings':
                    json.loads(raw);db.execute('INSERT OR REPLACE INTO values_store VALUES(?,?)',(name,raw))
        except Exception as error:
            db.rollback()
            failures=[]
            for target,old in reversed(file_undo):
                try:
                    if old is None:target.unlink(missing_ok=True)
                    else:target.write_bytes(old)
                except Exception:failures.append('arquivos')
            for name,old in reversed(undo):
                try:
                    if old is None:store.vault.delete(name)
                    else:store.vault.set(name,old)
                except Exception:failures.append('cofre')
            if failures:raise RuntimeError('A importação falhou e o banco foi revertido; não foi possível reverter todas as alterações em '+', '.join(sorted(set(failures)))+'. Restaure o backup antes de continuar.') from error
            raise
    return {'ok':True,**preview_config(data,password),'restart_required':True}
