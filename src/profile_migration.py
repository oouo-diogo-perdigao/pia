"""One-time import of legacy files; verified secrets go to the OS vault first."""
import hashlib
import json
import shutil
import sqlite3
import re
from contextlib import closing
from pathlib import Path
from .settings_store import ROOT,get_store,schema,sensitive
from .user_paths import USER_DIR

FIXED_PATHS={'MUSIC_OUTPUT_DIR','DOWNLOAD_DIR','WORK_DIR','PODCAST_CONFIG','PODCAST_ROOT'}


def portable_settings(rows,old_root='',target_root=USER_DIR):
    result=[]
    for row in rows:
        if row[1] in FIXED_PATHS:continue
        row=list(row)
        if row[3] in ('path','file') and not row[4]:
            value=json.loads(row[2]);normal=value.replace('\\','/')
            base=old_root.replace('\\','/').rstrip('/')
            managed=bool(base and normal.startswith(base+'/files/'))
            if managed:value=str(Path(target_root)/normal[len(base)+1:])
            if not managed and value and not Path(value).exists():value=''
            row[2]=json.dumps(value)
        result.append(row)
    return result


def portable_documents(rows,old_root=''):
    result=[]
    for name,raw in rows:
        value=json.loads(raw)
        if name=='Apps/screenshots' and isinstance(value,dict):value.pop('output_folder',None)
        result.append((name,json.dumps(value)))
    return result


def move_files(source,target,remove_source=True,only=None,recursive=True):
    """Never overwrite user files, and don't traverse symlinks."""
    source=Path(source);target=Path(target)
    if not source.is_dir() or source.is_symlink():return
    if source.resolve()==target.resolve():return
    if target.resolve().is_relative_to(source.resolve()):raise ValueError('Destino da migração não pode ficar dentro da origem.')
    for file in sorted(source.rglob('*') if recursive else source.iterdir()):
        if not file.is_file() or file.is_symlink() or any(p.is_symlink() for p in file.parents if p!=source.parent):continue
        if only and not only(file):continue
        dest=target/file.relative_to(source);dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists():
            if dest.stat().st_size==file.stat().st_size:
                with dest.open('rb') as a,file.open('rb') as b:
                    equal=all(left==right for left,right in iter(lambda:(a.read(1024*1024),b.read(1024*1024)),(b'',b'')))
                if equal:
                    if remove_source:file.unlink()
                    continue
            fingerprint=hashlib.sha256(str(file).encode()).hexdigest()[:10]
            dest=dest.with_name(dest.stem+'.migrated-'+fingerprint+dest.suffix)
            if dest.exists():raise RuntimeError('Conflito de migração; os arquivos de origem foram preservados.')
        shutil.copy2(file,dest)
        # Comparing complete files by stream avoids loading multi-hour audio into RAM.
        def digest(path):
            value=hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
            return value.digest()
        if digest(file)!=digest(dest):raise RuntimeError('Cópia não confirmada; origem preservada.')
        if remove_source:file.unlink()


def merge_workspace(old,target):
    """Merge legacy chat trees with remapped numeric IDs, preserving active branches."""
    from .workspace_store import WorkspaceStore
    WorkspaceStore(target)
    with closing(sqlite3.connect(old)) as source,closing(sqlite3.connect(target)) as dest:
        source.row_factory=sqlite3.Row
        tables={row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'chats' not in tables:return
        if 'folders' in tables:
            for row in source.execute('SELECT * FROM folders'):dest.execute('INSERT OR IGNORE INTO folders(id,name,created) VALUES(?,?,?)',(row['id'],row['name'],row['created']))
        for row in source.execute('SELECT * FROM chats'):
            row=dict(row)
            if dest.execute('SELECT 1 FROM chats WHERE id=?',(row['id'],)).fetchone():continue
            mapping={None:None};previous=None
            dest.execute('INSERT INTO chats(id,title,created,folder,pinned,archived) VALUES(?,?,?,?,?,?)',(row['id'],row['title'],row['created'],row.get('folder'),row.get('pinned',0),row.get('archived',0)))
            for message in source.execute('SELECT * FROM messages WHERE chat=? ORDER BY id',(row['id'],)):
                message=dict(message);parent=message.get('parent',previous)
                identity=dest.execute('INSERT INTO messages(chat,role,text,parent) VALUES(?,?,?,?)',(row['id'],message['role'],message['text'],mapping.get(parent))).lastrowid
                mapping[message['id']]=identity;previous=message['id']
            dest.execute('UPDATE chats SET leaf=?,read_message=? WHERE id=?',(mapping.get(row.get('leaf',previous)),mapping.get(row.get('read_message',previous),0) or 0,row['id']))
            if 'values_store' in tables:
                prefix='branch:'+row['id']+':'
                for name,raw in source.execute('SELECT key,value FROM values_store WHERE key LIKE ?',(prefix+'%',)):
                    parent=name[len(prefix):]
                    parent=None if parent=='None' else int(parent)
                    selected=json.loads(raw)
                    if selected in mapping:
                        dest.execute('INSERT OR IGNORE INTO values_store VALUES(?,?)',(prefix+str(mapping.get(parent)),json.dumps(mapping[selected])))
        if 'values_store' in tables:
            for key,value in source.execute('SELECT key,value FROM values_store'):
                if key.startswith('branch:'):continue
                dest.execute('INSERT OR IGNORE INTO values_store VALUES(?,?)',(key,value))
        dest.commit()


def initialize_profile(root=ROOT,store=None,target=None):
    root=Path(root);target=Path(target or USER_DIR);store=store or get_store()
    if any(name=='migration' and value=='1' for name,value in store.rows('profile_meta')):return
    target.mkdir(parents=True,exist_ok=True)
    old=root/'data/workspace.sqlite3'
    if old.is_file() and old.resolve()!=store.path.resolve():
        if not store.path.exists():
            store.path.parent.mkdir(parents=True,exist_ok=True)
            with closing(sqlite3.connect(old)) as source,closing(sqlite3.connect(store.path)) as dest:source.backup(dest)
        else:merge_workspace(old,store.path)
    from dotenv import dotenv_values
    from .env_types import split_key
    sections=[('general',root/'config')]
    media=[];notes=[]
    if (root/'.env').is_file():sections.append(('general',root))
    sections.extend((folder.relative_to(root/'Plugins').as_posix(),folder) for folder in (root/'Plugins').glob('*/*') if folder.is_dir())
    for section,folder in sections:
        file=folder/'.env'
        if file.is_file():
            values={};kinds={}
            definitions={item['name']:item['type'] for item in schema(section)}
            for raw,value in dotenv_values(file).items():
                name,kind=split_key(raw)
                if name=='MUSIC_OUTPUT_DIR' and value:
                    path=Path(value).expanduser();media.append((path if path.is_absolute() else folder/path,'music'))
                if name in FIXED_PATHS:continue
                if kind=='string':kind=definitions.get(name,kind)
                if kind=='bool' and value:
                    value={'1':'true','0':'false','yes':'true','no':'false','on':'true','off':'false'}.get(value.lower(),value.lower())
                if kind in ('path','file') and value:
                    path=Path(value).expanduser()
                    if not path.is_absolute():
                        path=next((candidate for candidate in (folder/path,root/path) if candidate.exists()),path)
                    if not path.exists() and name!='GOOGLE_APPLICATION_CREDENTIALS':value=''
                    else:
                        value=str(path)
                        managed=folder/'files'
                        if path.is_file() and path.resolve().is_relative_to(managed.resolve()) and not sensitive(name,kind):
                            move_files(managed,target/'files'/folder.name,remove_source=False)
                            value=str(target/'files'/folder.name/path.resolve().relative_to(managed.resolve()))
                values[name]=value or '';kinds[name]=kind
            credential_file=values.pop('GOOGLE_APPLICATION_CREDENTIALS',None)
            kinds.pop('GOOGLE_APPLICATION_CREDENTIALS',None)
            if credential_file:
                import base64
                source=Path(credential_file)
                if not source.is_absolute():source=folder/source
                if source.is_file():
                    if source.stat().st_size>5*1024**2:raise ValueError('Arquivo de credenciais excede 5 MiB.')
                    ref='file:'+section+':GOOGLE_APPLICATION_CREDENTIALS'
                    content={'filename':source.name,'data':base64.b64encode(source.read_bytes()).decode()}
                    store.vault.set(ref,content)
                    if store.vault.get(ref)!=content:raise RuntimeError('O cofre não confirmou o arquivo de credenciais.')
                    store.register_secret(ref)
                    if source.resolve().is_relative_to(root.resolve()):source.unlink()
            if section=='Connectors/object_storage' and values.get('OBJECT_STORAGE_ACCESS_KEY_ID'):
                config=store.document(section,{'accounts':[]})
                account=dict(id='legacy',name='Storage migrado',provider='s3',endpoint=values.get('OBJECT_STORAGE_ENDPOINT',''),region=values.get('OBJECT_STORAGE_REGION') or 'auto',bucket=values.get('OBJECT_STORAGE_BUCKET_NAME',''),public_url=values.get('OBJECT_STORAGE_URL',''))
                ref='storage:legacy'
                if store.vault.get(ref) is None:
                    secret={'access_key':values['OBJECT_STORAGE_ACCESS_KEY_ID'],'secret_key':values.get('OBJECT_STORAGE_SECRET_ACCESS_KEY','')}
                    store.vault.set(ref,secret)
                    if store.vault.get(ref)!=secret:raise RuntimeError('Não foi possível confirmar a migração da conta de storage.')
                store.register_secret(ref)
                if not any(a['id']=='legacy' for a in config['accounts']):config['accounts'].insert(0,account)
                config.setdefault('default','legacy');store.set_document(section,config)
                values={key:value for key,value in values.items() if key=='OBJECT_STORAGE_ACCOUNT_COLORS'}
                kinds={key:value for key,value in kinds.items() if key in values}
            store.save(section,values,kinds,overwrite=False)
            file.unlink()
        json_file=folder/'config.json' if section!='Apps/podcast_automation' else folder/'config/config.json'
        if json_file.is_file():
            value=json.loads(json_file.read_text(encoding='utf-8'))
            if section=='Apps/screenshots' and value.get('output_folder'):
                path=Path(value['output_folder']).expanduser();media.append((path if path.is_absolute() else folder/path,'screenshots'))
                value.pop('output_folder',None)
            name=section+'/campaigns' if section=='Apps/podcast_automation' else section
            current=store.document(name)
            if current is None:store.set_document(name,value)
            elif section=='Connectors/object_storage':
                ids={a['id'] for a in current.get('accounts',[])}
                current['accounts']+= [a for a in value.get('accounts',[]) if a['id'] not in ids]
                if value.get('default'):current['default']=value['default']
                store.set_document(name,current)
            # Register existing cofre entries so export includes previously connected accounts.
            if section.startswith('Connectors/'):
                plugin=section.split('/')[-1]
                for account in value.get('accounts',[]):
                    ref='storage:'+account['id'] if plugin=='object_storage' else 'token:'+plugin+':'+account['id']
                    store.register_secret(ref)
                if plugin in ('google','microsoft'):store.register_secret('client:'+plugin)
            json_file.unlink()
    for name in ('keywords.txt','models.yaml','shortcuts.yaml'):
        path=root/'config'/name
        if path.is_file():
            if store.document('main/'+name) is None:store.set_document('main/'+name,path.read_text(encoding='utf-8'))
            path.unlink()
    move_files(root/'data/screenshots/raw',root/'logs/screenshots/legacy')
    for source,dest in [('data/chat-images','chat'),('data/music','music'),('data/screenshots','screenshots')]:move_files(root/source,target/dest)
    move_files(root/'Plugins/Apps/podcast_automation/data',target/'apps/podcast_automation')
    move_files(root/'cache/main/actions',target/'images',only=lambda file:file.suffix.lower() in ('.png','.jpg','.jpeg','.bmp','.webp'))
    for source,kind in media:
        destination=target/kind
        if destination.resolve().is_relative_to(source.resolve()) and source.resolve()!=destination.resolve():
            notes.append('Arquivos anteriores em '+str(source)+' foram preservados na origem por sobreposição de pastas.');continue
        if kind=='music':predicate=lambda file:bool(re.fullmatch(r'[a-f0-9]{32}\.(mp3|wav|flac)(\.json)?',file.name))
        else:predicate=lambda file:file.suffix.lower() in ('.png','.jpg','.jpeg','.bmp','.webp')
        move_files(source,destination,remove_source=source.resolve().is_relative_to(root.resolve()),only=predicate,recursive=False)
    for _,folder in sections:
        if (folder/'files').is_dir():move_files(folder/'files',target/'files'/folder.name)
    if old.is_file() and old.resolve()!=store.path.resolve():
        old.unlink()
        for suffix in ('-wal','-shm'):Path(str(old)+suffix).unlink(missing_ok=True)
    (root/'data/pia.lock').unlink(missing_ok=True)
    move_files(root/'data',target/'legacy')
    if notes:store.set_document('migration/notes',notes)
    with store.connection() as db:db.execute('INSERT OR REPLACE INTO profile_meta VALUES(?,?)',('migration','1'))
