import threading
from src.pia.service import Job
from Plugins.Apps.music import service
_latest=None

def handle(action,data,context):
    global _latest
    if action=='library':
        import json
        return {'items':[json.loads(path.read_text(encoding='utf-8')) for path in sorted(service.OUTPUT.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)][:100], 'installed':(service.CACHE/'ace-step/.venv').is_dir(), 'job':_latest.id if _latest and _latest.status=='running' else None}
    if action=='cancel':
        context.jobs[data['job']].cancelled.set();return {'ok':True}
    if action not in ('generate','prepare-local'):raise ValueError('Operação musical desconhecida.')
    if action=='generate' and set(data)-{'prompt','lyrics','provider','duration'}:raise ValueError('Parâmetros musicais desconhecidos.')
    job=Job();context.jobs[job.id]=job
    _latest=job
    def worker():
        try:
            report=lambda text:job.emit('log',text=text)
            result=service.prepare(report) if action=='prepare-local' else service.generate(**data,progress=report,cancelled=job.cancelled.is_set)
            job.emit('done',result=result)
        except Exception as exc:job.emit('error',error=str(exc))
    threading.Thread(target=worker,daemon=True,name='pia-music').start()
    return {'job':job.id}
