"""File-manager UI adapter over the shared Object Storage plugin."""
import base64
import mimetypes
from pathlib import Path
import secrets
import threading
import time
from src.config_paths import BASE_DIR
from src.pia.service import Job
from Plugins.Connectors.object_storage.service import ObjectStorage
_store=None
_uploads={}
_active_paths=set()
_lock=threading.RLock()
def storage():
    global _store
    if _store is None:_store=ObjectStorage()
    return _store

def task(context,worker):
    job=Job();context.jobs[job.id]=job
    def run():
        try:
            result=worker(job)
            job.emit('done',result=result)
        except Exception as exc:job.emit('error',error=str(exc))
    threading.Thread(target=run,daemon=True).start()
    return {'job':job.id}

def handle(action,data,context):
    store=storage();account=data.get('account');bucket=data.get('bucket')
    if action=='accounts':return {'accounts':store.accounts(),'default':store.config().get('default')}
    if action=='buckets':
        metadata=store.account(account)
        if metadata.get('bucket'):return {'buckets':[metadata['bucket']]}
        return {'buckets':[b['Name'] for b in store.client(account).list_buckets()['Buckets']]}
    if action=='list':return store.list(account,bucket,data.get('prefix',''),data.get('cursor'),data.get('limit',100))
    if action=='public-link':return {'url':store.public_url(data['key'],account)}
    if action in ('open-local','drag-local'):
        return context.native('app',{'id':'object_storage','action':action,'payload':{'token':data['token']}})
    if action=='prepare-local':
        if context.native_handler is None:raise ValueError('Abrir e arrastar arquivos locais requer a PIA desktop. No navegador use Baixar.')
        from Plugins.Apps.object_storage import local_files
        import re
        key=store.key(data['key']);client=store.client(account);bucket=store.bucket(account,bucket)
        def download(job):
            if job.cancelled.is_set():raise InterruptedError('Download cancelado.')
            size=client.head_object(Bucket=bucket,Key=key)['ContentLength']
            if size>2*1024**3:raise ValueError('A abertura local aceita arquivos de até 2 GiB. Use Baixar para arquivos maiores.')
            name=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',key.rsplit('/',1)[-1]).strip(' .')[:160] or 'arquivo'
            # Prefix avoids Windows reserved names without changing the extension.
            folder=local_files.ROOT/secrets.token_hex(16);folder.mkdir(parents=True)
            file=folder/('pia_'+name);done=0;last=0;progress_lock=threading.Lock()
            def progress(count):
                nonlocal done,last
                if job.cancelled.is_set():raise InterruptedError('Download cancelado.')
                with progress_lock:
                    done+=count
                    if time.monotonic()-last>.2:
                        job.emit('progress',percent=min(100,done*100/max(1,size)));last=time.monotonic()
            try:
                client.download_file(bucket,key,str(file),Callback=progress)
                if job.cancelled.is_set():raise InterruptedError('Download cancelado.')
                return {'token':local_files.register(file),'name':name}
            except Exception:
                file.unlink(missing_ok=True)
                raise
        return task(context,download)
    if action=='mkdir':store.put(store.key(data['key']).rstrip('/')+'/',b'',account,bucket);return {'ok':True}
    if action=='delete':
        keys=data['keys']
        return task(context,lambda job:store.delete(keys,account,bucket))
    if action=='move-many':
        keys=data['keys'];target=data['target']
        if not isinstance(keys,list) or not keys or any(not isinstance(key,str) for key in keys):raise ValueError('Selecione os objetos a mover.')
        if not isinstance(target,str) or (target and not target.endswith('/')):raise ValueError('Pasta de destino inválida.')
        keys=list(dict.fromkeys(keys))
        keys=[key for key in keys if not any(other!=key and other.endswith('/') and key.startswith(other) for other in keys)]
        for key in keys:
            store.key(key)
            destination=target+key.rstrip('/').rsplit('/',1)[-1]+('/' if key.endswith('/') else '')
            if destination==key or (key.endswith('/') and target.startswith(key)):raise ValueError('Escolha uma pasta fora da origem.')
        def move(job):
            client=store.client(account);bucket_name=store.bucket(account,bucket);plan=[]
            for key in keys:
                destination=target+key.rstrip('/').rsplit('/',1)[-1]+('/' if key.endswith('/') else '')
                sources=[item['Key'] for item in store.objects(account,bucket,key)] if key.endswith('/') else [key]
                for source in sources:
                    dest=destination+source[len(key):] if key.endswith('/') else destination
                    try:client.head_object(Bucket=bucket_name,Key=dest)
                    except client.exceptions.ClientError as exc:
                        if exc.response.get('ResponseMetadata',{}).get('HTTPStatusCode')!=404:raise
                    else:raise ValueError('Já existe um objeto no destino: '+dest)
                    if any(existing==dest for _,existing in plan):raise ValueError('Dois objetos selecionados têm o mesmo destino: '+dest)
                    plan.append((source,dest))
            for index,(source,dest) in enumerate(plan):
                if job.cancelled.is_set():raise InterruptedError('Movimentação cancelada; objetos concluídos foram preservados.')
                store.copy(source,dest,account,bucket,move=True)
                job.emit('progress',percent=(index+1)*100/max(1,len(plan)))
            return {'count':len(plan)}
        return task(context,move)
    if action in ('copy','move'):
        key=store.key(data['key']);target=store.key(data['target'])
        def transfer(job):
            if key.endswith('/'):
                if target.startswith(key) and account==data.get('target_account',account) and bucket==data.get('target_bucket',bucket):raise ValueError('Escolha uma pasta de destino fora da origem.')
                keys=[o['Key'] for o in store.objects(account,bucket,key)]
            else:keys=[key]
            for index,source in enumerate(keys):
                if job.cancelled.is_set():raise InterruptedError('Transferência cancelada; objetos já concluídos foram preservados.')
                destination=target.rstrip('/')+'/'+source[len(key):] if key.endswith('/') else target
                store.copy(source,destination,account,bucket,data.get('target_account'),data.get('target_bucket'),move=action=='move')
                job.emit('progress',percent=round((index+1)*100/max(1,len(keys))),text=source)
            return {'count':len(keys)}
        return task(context,transfer)
    if action=='info':
        info=store.client(account).head_object(Bucket=store.bucket(account,bucket),Key=store.key(data['key']))
        return {'size':info['ContentLength'],'content_type':info.get('ContentType'),'modified':str(info.get('LastModified','')),'etag':info.get('ETag'),'metadata':info.get('Metadata',{})}
    if action=='download':
        key=store.key(data['key'])
        return {'url':store.client(account).generate_presigned_url('get_object',Params={'Bucket':store.bucket(account,bucket),'Key':key,'ResponseContentDisposition':'attachment'},ExpiresIn=300)}
    if action=='cancel':
        context.jobs[data['job']].cancelled.set();return {'ok':True}
    if action=='upload-begin':
        store.account(account);bucket=store.bucket(account,bucket);key=store.key(data['key']);total=int(data['size'])
        if not 0<=total<=100*1024**3:raise ValueError('Arquivo excede 100 GiB.')
        identity=secrets.token_hex(24);folder=BASE_DIR/'cache/Apps/object_storage/uploads';folder.mkdir(parents=True,exist_ok=True)
        with _lock:
            known={r['path'] for r in _uploads.values()}|_active_paths
            for orphan in folder.glob('*.part'):
                if orphan not in known and orphan.stat().st_mtime<time.time()-21600:orphan.unlink(missing_ok=True)
            for old,record in list(_uploads.items()):
                if record['time']<time.time()-21600:
                    record['path'].unlink(missing_ok=True);_uploads.pop(old)
            path=folder/(identity+'.part');path.touch()
            _uploads[identity]=dict(path=path,account=account,bucket=bucket,key=key,size=total,time=time.time())
        return {'id':identity}
    if action in ('upload-chunk','upload-finish','upload-cancel'):
        with _lock:
            record=_uploads.get(data['id'])
            if not record:raise ValueError('Upload expirado. Inicie novamente.')
            if action=='upload-cancel':record['path'].unlink(missing_ok=True);_uploads.pop(data['id']);return {'ok':True}
            if action=='upload-chunk':
                encoded=data['data']
                if not isinstance(encoded,str) or len(encoded)>6*1024*1024:raise ValueError('Chunk maior que 4 MiB.')
                chunk=base64.b64decode(encoded,validate=True)
                if len(chunk)>4*1024**2:raise ValueError('Chunk maior que 4 MiB.')
                offset=record['path'].stat().st_size
                if int(data['offset'])!=offset or offset+len(chunk)>record['size']:raise ValueError('Posição de upload inválida.')
                with record['path'].open('ab') as output:output.write(chunk)
                record['time']=time.time();return {'offset':offset+len(chunk)}
            if record['path'].stat().st_size!=record['size']:raise ValueError('Upload incompleto.')
            _uploads.pop(data['id'])
            _active_paths.add(record['path'])
        def upload(job):
            transferred=0;lock=threading.Lock();last=0
            def progress(size):
                nonlocal transferred,last
                if job.cancelled.is_set():raise InterruptedError('Upload cancelado.')
                with lock:
                    transferred+=size
                    if time.monotonic()-last>.2:
                        job.emit('progress',percent=min(100,round(transferred*100/max(1,record['size']))));last=time.monotonic()
            try:store.upload(record['path'],record['key'],record['account'],record['bucket'],mimetypes.guess_type(record['key'])[0] or 'application/octet-stream',callback=progress)
            finally:
                record['path'].unlink(missing_ok=True)
                with _lock:_active_paths.discard(record['path'])
            return {'key':record['key']}
        return task(context,upload)
    raise ValueError('Operação do Object Storage desconhecida.')
