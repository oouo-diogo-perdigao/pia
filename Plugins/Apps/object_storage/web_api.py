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
    if action=='save-account':return store.save_account(data)
    if action=='remove-account':store.remove_account(data['id']);return {'ok':True}
    if action=='buckets':
        metadata=store.account(account)
        if metadata.get('bucket'):return {'buckets':[metadata['bucket']]}
        return {'buckets':[b['Name'] for b in store.client(account).list_buckets()['Buckets']]}
    if action=='list':return store.list(account,bucket,data.get('prefix',''),data.get('cursor'),data.get('limit',100))
    if action=='mkdir':store.put(store.key(data['key']).rstrip('/')+'/',b'',account,bucket);return {'ok':True}
    if action=='delete':
        keys=data['keys']
        return task(context,lambda job:store.delete(keys,account,bucket))
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
