"""Podcast's web API. The PIA host only discovers and dispatches app actions."""
import json
from pathlib import Path
import secrets
import threading
from src.pia.service import Job
from src.resource_plugins import save_json
from .pipeline import initial, apply
from . import power
from .recording_queue import pending_files

ROOT = Path(__file__).resolve().parent
_latest = None
_tasks = {}
_lock = threading.Lock()


def handle(action, data, context):
    global _latest
    if action=='pending-preview':
        from src.env_types import dotenv_values
        config=handle('config',{},context)
        options={**config.get('integrations',{}),**{key:data[key] for key in ('google_account','google_folder') if key in data}}
        env=dotenv_values(ROOT/'.env')
        if str(env.get('DRIVE_PROCESS','true')).lower() in ('false','0'):
            folder=Path(env.get('LOCAL_DRIVE_FOLDER') or 'data/local-drive')
            if not folder.is_absolute():folder=ROOT/folder
            files=[{'id':str(file),'name':file.name} for file in folder.glob('*') if file.is_file() and file.suffix.lower()=='.zip']
            path=str(folder)
        else:
            from Plugins.Connectors.google.drive import Drive
            drive=Drive(context.backend.resources)
            folder=options.get('google_folder') or drive.default_folder
            if not folder or not drive.accounts():return {'configured':False,'pending':[],'message':'Selecione a conta e a pasta de gravações.'}
            account=drive.account(options.get('google_account'))
            files=[];cursor=None;seen=set()
            while True:
                page=drive.list(account,folder,cursor=cursor)
                files.extend(file for file in page.get('files',[]) if file['name'].lower().endswith('.zip'))
                cursor=page.get('nextPageToken')
                if not cursor:break
                if cursor in seen:raise ValueError('O Drive retornou uma página repetida ao consultar gravações.')
                seen.add(cursor)
            path=drive.folder_path(folder,account)
        pending=pending_files(files)
        return {'configured':True,'pending':[{'id':f['id'],'name':f['name']} for f in pending],
                'total':len(files),'processed':len(files)-len(pending),'folder_path':path,'folder':str(folder)}
    if action == 'status':
        task = _tasks.get(_latest)
        return {'cursor': len(task['job'].events) if task else 0,'job': _latest, 'running': bool(task and task['job'].status == 'running'),
                'monitor':task.get('monitor',False) if task else False,
                'shutdown_after':task.get('shutdown_after',False) if task else False,
                'shutdown_pending':task.get('shutdown_pending',False) if task else False,
                'lines': task['lines'][-2500:] if task else [],
                'result': task.get('result') if task else None}
    if action=='clear-log':
        record=_tasks.get(_latest)
        if record:
            record['lines'].clear()
            record['job'].emit('log-clear')
        return {'ok':True}
    if action=='pipeline':
        task=_tasks.get(_latest)
        return task['pipeline'] if task else initial()
    if action == 'config':
        path = ROOT / 'config/config.json'
        if not path.exists():
            path = ROOT / 'docs/examples/config.example.json'
        return json.loads(path.read_text(encoding='utf-8'))
    if action=='save-options':
        config=handle('config',{},context)
        outputs=data.get('outputs',{})
        if not isinstance(outputs,dict) or set(outputs)-{'mp3','resumo.json','srt','vtt','txt'} or any(not isinstance(v,bool) for v in outputs.values()):raise ValueError('Formatos de saída inválidos.')
        integrations=data.get('integrations',{})
        allowed={'google_account','google_folder','google_folder_name','google_folder_path','storage_account','storage_bucket','announce','discord_notify','discord_channel','discord_channels'}
        if not isinstance(integrations,dict) or set(integrations)-allowed:raise ValueError('Integrações inválidas.')
        for key,value in integrations.items():
            if key=='discord_channels':
                if not isinstance(value,list) or any(not isinstance(v,str) or not v.isdigit() for v in value):raise ValueError('Canais Discord inválidos.')
                continue
            if key in ('announce','discord_notify'):
                if not isinstance(value,bool):raise ValueError('Preferência inválida.')
            elif not isinstance(value,str):raise ValueError('Integração inválida.')
        config['outputs']={**{name:True for name in ('resumo.json','srt','txt','vtt')},**outputs,'mp3':True}
        config['integrations']={**config.get('integrations',{}),**integrations}
        if 'discord_channels' in integrations:config['integrations'].pop('discord_channel',None)
        save_json(ROOT/'config/config.json',config)
        return {'ok':True}
    if action == 'save-config':
        value = data['value']
        if not isinstance(value, dict) or any(not isinstance(value.get(k), dict) for k in (
                'nomes_reais', 'campaign_details', 'publication', 'audio', 'processing')):
            raise ValueError('Configuração de campanhas inválida.')
        # Campaign editing must not overwrite newer account/folder selections.
        existing=handle('config',{},context)
        value={**value,**{key:existing[key] for key in ('integrations','outputs') if key in existing}}
        save_json(ROOT / 'config/config.json', value)
        return {'ok': True}
    if action == 'stop':
        with _lock:
            record=_tasks.get(_latest)
            if record:
                record['job'].cancelled.set()
        context.backend.stop_podcast()
        return {'ok': True}
    if action=='cancel-shutdown':
        with _lock:
            record=_tasks.get(_latest)
            if not record or not record.get('shutdown_pending'):raise ValueError('Não há desligamento agendado.')
            power.cancel()
            record['shutdown_pending']=False
        return {'ok':True}
    if action != 'start':
        raise ValueError('Ação desconhecida do podcast.')
    with _lock:
        if _latest and _tasks[_latest]['job'].status == 'running':
            raise ValueError('Já há uma tarefa em execução.')
        task = data.get('task')
        monitor=data.get('monitor',False);shutdown_after=data.get('shutdown_after',False)
        if not isinstance(monitor,bool) or not isinstance(shutdown_after,bool):raise ValueError('Opções de processamento inválidas.')
        if monitor and shutdown_after:raise ValueError('Monitoramento automático e desligamento são opções mutuamente exclusivas.')
        if shutdown_after and task!='process':raise ValueError('Desligamento só pode acompanhar o processamento de sessões.')
        if _latest and _tasks[_latest].get('shutdown_pending'):raise ValueError('Cancele o desligamento agendado antes de iniciar outra tarefa.')
        args = []
        output = None
        if task == 'process':
            module = 'podcast_automation.main'
            args = [] if data.get('monitor') else ['--once']
        elif task == 'rebuild':
            module = 'utilities.rebuild_feeds'
        elif task in ('merge_srt', 'merge_vtt'):
            module = 'utilities.' + task
            kind = task.split('_')[1]
            directory = ROOT / 'data/web-tasks' / secrets.token_hex(8)
            directory.mkdir(parents=True)
            for key in ('first', 'second'):
                value = data.get(key)
                if not isinstance(value, str) or len(value) > 5 * 1024 * 1024:
                    raise ValueError('Selecione duas legendas válidas (até 5 MiB cada).')
                (directory / (key + '.' + kind)).write_text(value, encoding='utf-8-sig' if kind == 'srt' else 'utf-8')
            output = directory / ('merged.' + kind)
            args = [directory / ('first.' + kind), directory / ('second.' + kind), '-o', output]
        else:
            raise ValueError('Tarefa desconhecida.')
        process = context.backend.start_podcast_task(module, *args)
        job = Job()
        context.jobs[job.id] = job
        _latest = job.id
        record = {'job': job, 'lines': [], 'result': None, 'pipeline':initial(),
                  'monitor':monitor,'shutdown_after':shutdown_after,'shutdown_pending':False}
        _tasks[job.id] = record
        def read():
            try:
                with process.stdout:
                    for line in process.stdout:
                        if line.startswith('@@CRAIG '):
                            try:
                                event=json.loads(line[len('@@CRAIG '):]);apply(record['pipeline'],event)
                                job.emit('pipeline',value=json.loads(json.dumps(record['pipeline'])))
                                continue
                            except (ValueError,KeyError,TypeError):pass
                        if '[STT_PROGRESS]' in line or ('%|' in line and 'it/s' in line):continue
                        record['lines'].append(line.rstrip())
                        from src.plugin_logs import write
                        write('Apps/podcast_automation',line.rstrip())
                        if len(record['lines']) > 2500:
                            del record['lines'][:500]
                        job.emit('log', text=line.rstrip())
                code = process.wait()
                if code:
                    if not record['pipeline'].get('error'):apply(record['pipeline'],{'kind':'failed','error':f'Processo encerrou com código {code}.'})
                    job.emit('pipeline',value=record['pipeline'])
                    job.emit('error', error=f'A tarefa terminou com código {code}. Consulte a saída.')
                else:
                    if output:
                        record['result'] = {'name': output.name, 'text': output.read_text(encoding='utf-8-sig')}
                    with _lock:
                        if shutdown_after and not monitor and not job.cancelled.is_set() and not record['pipeline'].get('error'):
                            try:power.shutdown()
                            except Exception:
                                raise RuntimeError('Os arquivos foram processados, mas o sistema não permitiu agendar o desligamento. Verifique as permissões de energia do usuário.') from None
                            record['shutdown_pending']=True
                            message='Todos os arquivos foram processados. Computador será desligado em 60 segundos.'
                            record['lines'].append(message);job.emit('log',text=message)
                        job.emit('done', result=record['result'],shutdown_pending=record['shutdown_pending'])
            except Exception as exc:
                apply(record['pipeline'],{'kind':'failed','error':str(exc)})
                job.emit('pipeline',value=record['pipeline'])
                job.emit('error', error=str(exc))
        threading.Thread(target=read, daemon=True, name='pia-podcast-web').start()
        return {'job': job.id}
