import threading
import uuid
from src.pia.service import Job
from Plugins.Apps.music import service
_latest=None
_job_lock=threading.Lock()

def handle(action,data,context):
    global _latest
    if action=='library':
        return {'items':service.library(), 'folder':str(service.output_directory()), 'installed':(service.CACHE/'ace-step/.venv').is_dir(), 'job':_latest.id if _latest and _latest.status=='running' else None}
    if action=='cancel':
        context.jobs[data['job']].cancelled.set();return {'ok':True}
    if action not in ('generate','prepare-local'):raise ValueError('Operação musical desconhecida.')
    if action=='generate' and set(data)-{'prompt','lyrics','provider','duration','count'}:raise ValueError('Parâmetros musicais desconhecidos.')
    count=data.get('count',1)
    if type(count) is not int or not 1<=count<=10:raise ValueError('Escolha de 1 a 10 músicas.')
    with _job_lock:
        if _latest and _latest.status=='running':raise ValueError('Já há uma tarefa musical em andamento.')
        job=Job();context.jobs[job.id]=job
        _latest=job
    def worker():
        try:
            report=lambda text:job.emit('log',text=text)
            if action=='prepare-local':result=service.prepare(report)
            else:
                group=uuid.uuid4().hex;items=[]
                arguments={key:value for key,value in data.items() if key!='count'}
                for index in range(count):
                    if job.cancelled.is_set():raise InterruptedError('Geração cancelada; músicas concluídas foram preservadas.')
                    job.emit('progress',value={'percent':index/count*100,'completed':index,'total':count,'label':f'Gerando música {index+1}/{count}','state':'running'})
                    item=service.generate(**arguments,progress=report,cancelled=job.cancelled.is_set)
                    item['batch']=group
                    item['variant']=index+1
                    service.save_json(service.audio_file(item['file']).with_name(item['file']+'.json'),item)
                    items.append(item)
                    job.emit('track',item=item)
                    job.emit('progress',value={'percent':(index+1)/count*100,'completed':index+1,'total':count,'label':'Músicas concluídas','state':'completed' if index+1==count else 'running'})
                result={'items':items,'batch':group}
                if hasattr(context,'publish_notification'):context.publish_notification('Apps/music','Músicas prontas',f'{len(items)} música(s) gerada(s).')
            job.emit('done',result=result)
        except Exception as exc:job.emit('error',error=str(exc))
    threading.Thread(target=worker,daemon=True,name='pia-music').start()
    return {'job':job.id}
