"""Local web workspace service. No Qt imports; HTTP and native shells share state."""
from __future__ import annotations
from concurrent.futures import Future
import importlib.util
import json
from pathlib import Path
import re
import secrets
import sys
import threading
import time
import tomllib
import types

from src.config_paths import BASE_DIR, CONFIG_DIR
from src.desktop_backend import DesktopBackend, environment_fields


class Job:
    def __init__(self, chat=None):
        self.id = secrets.token_hex(16)
        self.chat = chat
        self.status, self.error, self.text = 'running', None, ''
        self.events = []
        self.cancelled = threading.Event()
        self.changed = threading.Condition()

    def emit(self, kind, **data):
        if kind in ('done','error') and getattr(self,'plugin_identity',None):
            from src.plugin_logs import write
            write(self.plugin_identity,'job',kind)
        with self.changed:
            if kind == 'delta':
                self.text += data['text']
            if kind in ('done', 'error'):
                self.status = kind
                self.error = data.get('error')
            self.events.append({'type': kind, **data})
            self.changed.notify_all()


class Apps:
    def __init__(self, root=None):
        self.root = Path(root or BASE_DIR / 'Plugins' / 'Apps')
        self.modules = {}

    def records(self):
        result = []
        for file in sorted(self.root.glob('*/plugin.toml')):
            data = tomllib.loads(file.read_text(encoding='utf-8'))
            manifest = file.parent / 'pia.json'
            if manifest.exists():
                meta = json.loads(manifest.read_text(encoding='utf-8'))
                data.update(name=meta['nome'], info=meta.get('info', ''), about=meta.get('about'))
                if data.get('web'):
                    data['web']['entrypoint'] = meta.get('home', data['web']['entrypoint'])
            if data.get('enabled', True) and re.fullmatch('[a-z][a-z0-9_]*', data.get('id', '')) and data.get('web'):
                result.append({**data, 'folder': file.parent})
        return result

    def find(self, identity):
        for app in self.records():
            if app['id'] == identity:
                return app
        raise ValueError('Aplicativo não encontrado.')

    def public(self):
        return [{'id': a['id'], 'name': a['name'], 'icon': a.get('icon', 'app'),
                 'info': a.get('info', ''), 'about': '/apps/' + a['id'] + '/' + (a.get('about') or 'about.html'),
                 'url': '/apps/' + a['id'] + '/' + a['web']['entrypoint']} for a in self.records()]

    def load(self, identity):
        app = self.find(identity)
        if identity not in self.modules:
            path = (app['folder'] / app['web']['api']).resolve()
            if not path.is_relative_to(app['folder'].resolve()) or path.suffix != '.py':
                raise ValueError('API do aplicativo inválida.')
            package = '_pia_web_app_' + identity
            module = types.ModuleType(package)
            module.__path__ = [str(app['folder'])]
            sys.modules[package] = module
            spec = importlib.util.spec_from_file_location(package + '.api', path)
            api = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = api
            spec.loader.exec_module(api)
            self.modules[identity] = api
        return self.modules[identity]

    def call(self, identity, action, payload, context):
        return self.load(identity).handle(action, payload, context)


class WorkspaceService:
    def __init__(self, backend=None, apps=None):
        self.boot=secrets.token_hex(12)
        self.native_handler = None
        self.jobs = {}
        self.requests = {}
        self.lock = threading.RLock()
        self.backend = backend or DesktopBackend(self.notify)
        self.store = self.backend.store
        self.apps = apps or Apps()
        from src.notifications import NotificationCenter
        self.notifications=getattr(self.backend,'notifications',None) or NotificationCenter(self.store,self.notify,getattr(self.backend,'speak',lambda text:None))
        from src.media import MediaSessions
        self.media=MediaSessions()

    def notify(self, title, text, speak=False):
        if self.native_handler:
            self.native_handler('notify', dict(title=title, text=text, speak=speak))

    def native(self, action, payload=None):
        if not self.native_handler:
            raise RuntimeError('Esta operação exige a PIA aberta na sessão gráfica.')
        result = self.native_handler(action, payload or {})
        return result.result(timeout=180) if isinstance(result, Future) else result

    def state(self):
        return {'boot':getattr(self,'boot','legacy'),'chats': self.store.chat_records(), 'folders': self.store.folders(), 'apps': sorted(self.apps.public(),key=lambda app:(self.store.get('ui:app-order',[]).index(app['id']) if app['id'] in self.store.get('ui:app-order',[]) else 999)),
                'jobs': [{'id': j.id, 'chat': j.chat, 'status': j.status} for j in self.jobs.values() if j.status == 'running'],
                'native': self.native_handler is not None,
                'notifications':self.notification_counts(),'bots':self.bot_records()}

    def notification_counts(self):
        counts={k:v for k,v in self.notifications.snapshot().items() if k in ('counts','unread','settings')}
        chats=self.store.unread_chats()
        return {**counts,'chat_counts':chats,'chat_unread':sum(chats.values())}

    def bot_records(self):
        records=[]
        for file in sorted((BASE_DIR/'Plugins/Bot').glob('*/pia.json')):
            meta=json.loads(file.read_text(encoding='utf-8'))
            identity=meta.get('app_id','')
            if not re.fullmatch('[a-z][a-z0-9_]*',identity):continue
            records.append({'id':identity,'name':meta['nome'],'avatar':f'/bots/{identity}/avatar.svg' if (file.parent/'avatar.svg').is_file() else None,'description':meta.get('info',''),'url':f'/bots/{identity}/web/'+meta.get('home','index.html')})
        return records

    def publish_notification(self,source,title,text,links=None):
        if source not in dict(self.plugin_folders()):raise ValueError('Plugin não encontrado.')
        return self.notifications.publish(source,title,text,links)

    def send(self, chat, text, request=None):
        if not isinstance(text, str) or not text.strip():
            raise ValueError('Mensagem vazia.')
        if len(text) > 100000:
            raise ValueError('Mensagem muito longa.')
        with self.lock:
            if request and request in self.requests:
                return self.requests[request]
            if not any(c['id'] == chat for c in self.store.chat_records()):
                raise ValueError('Conversa não encontrada.')
            if any(j.chat == chat and j.status == 'running' for j in self.jobs.values()):
                raise ValueError('Aguarde a resposta desta conversa.')
            # Persist the user message before returning 202; the UI never waits for the model.
            history = self.store.messages(chat)
            if not history or history[-1] != {'role': 'user', 'content': text.strip()}:
                self.store.append(chat, 'user', text.strip())
            self.store.set('draft:' + chat, '')
            job = Job(chat)
            self.jobs[job.id] = job
            if request:
                self.requests[request] = job.id
            def work():
                try:
                    def delta(value):
                        if job.cancelled.is_set():
                            raise InterruptedError('Resposta interrompida.')
                        job.emit('delta', text=value)
                    self.backend.reply(chat, text.strip(), on_delta=delta)
                    job.emit('done')
                except InterruptedError:
                    if job.text:
                        self.store.append(chat, 'assistant', job.text)
                    job.emit('done', cancelled=True)
                except Exception as exc:
                    job.emit('error', error=str(exc))
            threading.Thread(target=work, daemon=True, name='pia-web-chat').start()
            return job.id

    def plugin_folders(self):
        result = []
        for kind in ('Apps', 'Bot', 'Connectors', 'Skills', 'Browser'):
            for folder in sorted((BASE_DIR / 'Plugins' / kind).glob('*')):
                if folder.is_dir() and not folder.name.startswith(('.', '_')):
                    result.append((kind + '/' + folder.name, folder))
        return result

    def settings(self):
        from src.env_types import fields, split_key
        def field(name, value, link, sensitive):
            base, kind = split_key(name)
            sensitive = kind == 'secret' or (kind == 'string' and sensitive)
            return dict(name=name, base=base, type=kind, value=value, sensitive=sensitive,
                        configured=bool(value), link=link)
        sections = [{'id': 'general', 'name': 'PIA · Geral', 'fields': [field(*row) for row in environment_fields() if split_key(row[0])[0]!='PODCAST_CONFIG']}]
        for identity, folder in self.plugin_folders():
            example = folder / '.env.example'
            if not example.exists():
                example = folder / 'docs' / 'examples' / '.env.example'
            rows = []
            for name, value in fields(example, folder / '.env'):
                if identity=='Connectors/agents' and split_key(name)[0]=='AGENTS_GEMINI_EXECUTABLE':continue
                if split_key(name)[0] in ('PODCAST_CONFIG','GOOGLE_APPLICATION_CREDENTIALS','GOOGLE_DRIVE_FOLDER_ID'):continue
                sensitive = any(part in name for part in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL'))
                link = ('https://antigravity.google/docs/getting-started?tab=cli' if name.startswith('AGENTS_AGY_') else
                        'https://console.cloud.google.com/apis/credentials' if name.startswith('GOOGLE') else
                        'https://dash.cloudflare.com/' if name.startswith('OBJECT_STORAGE') else
                        'https://huggingface.co/settings/tokens' if name.startswith('HF_') else
                        'https://discord.com/developers/applications' if name.startswith('DISCORD_') else
                        'https://github.com/oouo-diogo-perdigao/pia#readme')
                rows.append(field(name, value, link, sensitive))
            if rows:
                manifest=folder/'pia.json'
                meta=json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {}
                sections.append(dict(id=identity, name=meta.get('nome',identity.replace('/', ' · ')), fields=rows))
        return sections

    def save_settings(self, section, values):
        from dotenv import set_key, unset_key
        from src.env_types import validate, split_key
        available = next((s for s in self.settings() if s['id'] == section), None)
        if available is None:
            raise ValueError('Seção desconhecida.')
        path = CONFIG_DIR / '.env' if section == 'general' else dict(self.plugin_folders())[section] / '.env'
        fields = {f['name']: f for f in available['fields']}
        for name, value in values.items():
            if name not in fields or not isinstance(value, str) or '\x00' in value:
                raise ValueError('Variável inválida.')
            validate(name, value)
        for name, value in values.items():
            set_key(path, name, value, quote_mode='always')
            base, _ = split_key(name)
            if base != name:
                unset_key(path, base)
        return {'ok': True, 'restart_required': True}

    def upload_setting(self, data):
        """A user-selected file is owned by its config section, never publicly served."""
        import base64
        from src.env_types import split_key
        section, name = data['section'], data['name']
        available = next((s for s in self.settings() if s['id'] == section), None)
        field = next((f for f in available['fields'] if f['name'] == name), None) if available else None
        if not field or field['type'] != 'file':
            raise ValueError('Esta variável não é um arquivo gerenciado.')
        encoded=data.get('data')
        if not isinstance(encoded,str) or len(encoded)>7*1024*1024:
            raise ValueError('Arquivo excede 5 MiB ou é inválido.')
        content = base64.b64decode(encoded, validate=True)
        if len(content) > 5 * 1024 * 1024:
            raise ValueError('Arquivo excede 5 MiB.')
        base, _ = split_key(name)
        if base == 'GOOGLE_APPLICATION_CREDENTIALS':
            credentials = json.loads(content)
            if not isinstance(credentials, dict) or credentials.get('type') != 'service_account' or not credentials.get('client_email') or not credentials.get('private_key'):
                raise ValueError('Selecione o JSON de credenciais de uma conta de serviço Google.')
        folder = CONFIG_DIR if section == 'general' else dict(self.plugin_folders())[section]
        extension = Path(str(data.get('filename', ''))).suffix.lower()
        if not re.fullmatch(r'\.[a-z0-9]{1,10}', extension):
            extension = '.bin'
        target = folder / 'files' / (section.split('/')[-1] + '_' + base + extension)
        target.parent.mkdir(exist_ok=True)
        if target.is_symlink() or not target.resolve().is_relative_to(folder.resolve()):
            raise ValueError('Destino inválido.')
        temporary = target.with_name(target.name + '.' + secrets.token_hex(8) + '.tmp')
        with temporary.open('xb') as out:
            out.write(content)
        temporary.chmod(0o600)
        temporary.replace(target)
        self.save_settings(section, {name: str(target.resolve())})
        return {'path': str(target.resolve())}

    def dispatch(self, method, path, data, query):
        from src.plugin_logs import write
        parts=path.strip('/').split('/')
        identity=None
        if len(parts)>=2 and parts[0] in ('apps','bots','integrations') and (parts[0]=='bots' or len(parts)>=3):
            identity={'apps':'Apps','bots':'Bot','integrations':'Connectors'}[parts[0]]+'/'+parts[1]
        elif path.startswith('/accounts/') and data.get('plugin'):
            identity='Connectors/'+data['plugin']
        elif path=='/settings/save' and data.get('section','').startswith(('Apps/','Bot/','Connectors/')):
            identity=data['section']
        try:
            result=self._dispatch(method,path,data,query)
        except Exception as exc:
            if identity:write(identity,parts[-1],type(exc).__name__)
            raise
        if identity and method=='POST' and parts[-1] not in ('status','pipeline','config','accounts','folders','list','logs','channels','buckets','secrets','saved-image','list-saved'):
            write(identity,parts[-1])
            if isinstance(result,dict) and result.get('job') in self.jobs:
                self.jobs[result['job']].plugin_identity=identity
        return result

    def _dispatch(self, method, path, data, query):
        if path=='/notifications/counts':
            return self.notification_counts()
        if path=='/chat/read':
            self.store.read_chat(data['chat'],data['through'])
            return {'ok':True}
        if path=='/notifications':
            value=self.notifications.snapshot()
            value['sources']=[{'id':identity,'name':json.loads((folder/'pia.json').read_text(encoding='utf-8')).get('nome',identity) if (folder/'pia.json').is_file() else identity} for identity,folder in self.plugin_folders() if identity.startswith(('Apps/','Bot/'))]
            return value
        if path=='/notifications/settings':
            self.notifications.configure(data)
            return {'ok':True}
        if path=='/notifications/read':
            self.notifications.read(data.get('id'),data.get('source'));return {'ok':True}
        if path=='/notifications/publish':
            return self.publish_notification(data['source'],data['title'],data['text'],data.get('links'))
        if path=='/media/state':
            playing=self.media.update(data.get('client'),data.get('playing'))
            if self.native_handler:self.native('media-state',{'playing':playing})
            return {'ok':True}
        if path=='/logs/read':
            from src.log_reader import read_log
            return read_log(data['name'],data.get('cursor'),data.get('identity'))
        if path=='/logs/open':
            from src.log_reader import log_path
            from urllib.parse import quote
            log_path(data['name'])
            if self.native_handler:return self.native('open-log',{'name':data['name']})
            return {'url':'/api/pia/logs/file?name='+quote(data['name'],safe='')}
        if path == '/settings/upload':
            return self.upload_setting(data)
        if path == '/preferences':
            if method == 'POST':
                if data.get('language') not in ('pt-BR', 'en'):
                    raise ValueError('Idioma inválido.')
                self.store.set('ui:language', data['language'])
            return {'language': self.store.get('ui:language', 'pt-BR')}
        if path == '/apps/order':
            order=data.get('order',[])
            valid={a['id'] for a in self.apps.public()}
            if not isinstance(order,list) or any(not isinstance(item,str) for item in order) or len(order)!=len(set(order)) or set(order)!=valid:raise ValueError('Ordem de aplicativos inválida.')
            self.store.set('ui:app-order',order)
            return {'ok':True}
        if path == '/state':
            return self.state()
        if path == '/chat/new':
            chat = self.store.new_chat()
            if data.get('folder'):
                self.store.update_chat(chat, folder=data['folder'], move=True)
            return {'id': chat}
        if path == '/chat/messages':
            chat = query.get('chat', [''])[0]
            return {'messages': self.store.message_records(chat), 'draft': self.store.get('draft:' + chat, '')}
        if path == '/chat/send':
            return {'job': self.send(data['chat'], data['text'], data.get('request'))}
        if path == '/chat/cancel':
            self.jobs[data['job']].cancelled.set()
            return {'ok': True}
        if path == '/chat/draft':
            self.store.set('draft:' + data['chat'], str(data.get('text', ''))[:100000])
            return {'ok': True}
        if path == '/chat/update':
            self.store.update_chat(data['chat'], title=data.get('title'), folder=data.get('folder'), move='folder' in data, pinned=data.get('pinned'), archived=data.get('archived'))
            return {'ok': True}
        if path in ('/chat/message', '/chat/delete-many'):
            targets = data.get('chats', []) if path.endswith('delete-many') else [data['chat']]
            with self.lock:
                if (path.endswith('delete-many') or data.get('action') not in ('speak','fork')) and any(j.chat in targets and j.status == 'running' for j in self.jobs.values()):
                    raise ValueError('Interrompa a resposta e aguarde antes de alterar esta conversa.')
                if path.endswith('delete-many'):
                    for chat in targets: self.store.delete_chat(chat)
                    return {'ok': True}
                chat, identity, action = data['chat'], int(data['id']), data['action']
                node = next((n for n in self.store.message_records(chat) if n['id']==identity), None)
                if action == 'select':
                    self.store.select_message(chat, identity)
                    return {'ok': True}
                if node is None: raise ValueError('Mensagem não encontrada na ramificação atual.')
                if action == 'fork': return {'chat': self.store.fork(chat,identity)}
                if action == 'delete':
                    self.store.remove_message(chat,identity)
                    return {'ok': True}
                if action == 'speak':
                    threading.Thread(target=self.backend.speak,args=(node['content'],),daemon=True).start()
                    return {'ok': True}
                if action == 'edit':
                    text = data.get('text','').strip()
                    if not text: raise ValueError('Mensagem vazia.')
                    self.store.select_message(chat,node['parent'],descendants=False)
                    self.store.append(chat,node['role'],text)
                    if node['role']=='assistant': return {'ok': True}
                elif action == 'retry':
                    if node['role']=='assistant':
                        self.store.select_message(chat,node['parent'],descendants=False)
                    else:
                        self.store.select_message(chat,identity,descendants=False)
                    history = self.store.messages(chat)
                    if not history or history[-1]['role']!='user': raise ValueError('Não há mensagem para gerar novamente.')
                    text = history[-1]['content']
                else: raise ValueError('Ação desconhecida.')
                return {'job': self.send(chat,text)}
        if path == '/chat/delete':
            if any(j.chat == data['chat'] and j.status == 'running' for j in self.jobs.values()):
                raise ValueError('Aguarde a resposta antes de excluir.')
            self.store.delete_chat(data['chat'])
            return {'ok': True}
        if path == '/folder/save':
            return {'id': self.store.save_folder(data['name'], data.get('id'))}
        if path == '/folder/delete':
            self.store.remove_folder(data['id'])
            return {'ok': True}
        if path == '/settings':
            return self.settings()
        if path == '/settings/save':
            result=self.save_settings(data['section'], data['values'])
            if self.native_handler:
                def restart_idle():
                    while any(job.status=='running' for job in list(self.jobs.values())):time.sleep(.5)
                    self.native('restart')
                threading.Thread(target=restart_idle,daemon=True,name='pia-settings-restart').start()
                result['restarting']=True
            return result
        if path == '/accounts':
            return {'providers': self.backend.resources.manifests(), 'accounts': self.backend.resources.accounts(),
                    'client_secrets': {p['id']: self.backend.resources.vault.get('client:'+p['id']) or '' for p in self.backend.resources.manifests()},
                    'clients': {p['id']: self.backend.resources.config(p['id']).get('client_id', '') for p in self.backend.resources.manifests()}}
        if path == '/accounts/connect':
            resources = self.backend.resources
            job = Job()
            self.jobs[job.id] = job
            def connect():
                try:
                    resources.configure(data['plugin'], data['client_id'], data.get('client_secret') or None)
                    resources.connect(data['plugin'], data.get('label', ''))
                    job.emit('done')
                except Exception as exc:
                    job.emit('error', error=str(exc))
            threading.Thread(target=connect, daemon=True).start()
            return {'job': job.id}
        if path == '/accounts/disconnect':
            self.backend.resources.disconnect(data['plugin'], data['account'])
            return {'ok': True}
        if path == '/bots':
            return self.bot_records()
        if path == '/bots/secretaria':
            if method == 'POST':
                self.backend.secretary.configure(data)
            from Plugins.Bot.secretaria.bot import MAIL_FILTERS
            return {'filters':[{'id':key,'name':label} for key,(label,_) in MAIL_FILTERS.items()], 'config': self.backend.secretary.config(), 'accounts': self.backend.resources.accounts('google'),
                    'status': [self.store.get('secretary:status:' + a['id'], {}) for a in self.backend.resources.accounts('google')]}
        if path == '/bots/secretaria/poll':
            threading.Thread(target=self.backend.secretary.poll, daemon=True).start()
            return {'ok': True}
        if path.startswith('/integrations/'):
            _,_,plugin,action=path.split('/',3)
            if plugin=='agents':
                from Plugins.Connectors.agents.service import ask,status
                if action=='status':return status()
                if action=='ask':
                    job=Job();self.jobs[job.id]=job
                    def external():
                        try:job.emit('done',result=ask(data['provider'],data['prompt']))
                        except Exception as exc:job.emit('error',error=str(exc))
                    threading.Thread(target=external,daemon=True).start()
                    return {'job':job.id}
            if plugin=='object_storage' and action=='secrets':
                from Plugins.Connectors.object_storage.service import ObjectStorage
                storage=ObjectStorage()
                account=storage.account(data['account'])
                value=storage.legacy() if account['id']=='legacy' else storage.vault.get('storage:'+account['id'])
                return {key:(value or {}).get(key,'') for key in ('access_key','secret_key','session_token')}
            if plugin=='google':
                from Plugins.Connectors.google.drive import Drive
                drive=Drive(self.backend.resources)
                if action=='accounts':return {'accounts':drive.accounts(),'folder':drive.config().get('GOOGLE_DRIVE_FOLDER_ID','')}
                if action=='folders':return drive.list(account=data.get('account'),folder=data.get('folder'),folders_only=True,cursor=data.get('cursor'),search=data.get('search'))
            if plugin=='discord':
                from Plugins.Connectors.discord.service import Discord
                from Plugins.Connectors.discord.runtime import get_runtime
                bot=Discord()
                if action=='status':return {**bot.public(),'gateway':get_runtime().status()}
                if action=='logs':return {'text':bot.logs()}
                if action=='channels':return {'channels':bot.channels()}
                if action=='send':return bot.send(data['text'],data.get('channel'))
                try:
                    if action=='diagnose':return bot.diagnose(data.get('channel'))
                    if action=='test':return bot.send('PIA · Mensagem de teste. A publicação neste canal está funcionando.',data.get('channel'))
                    if action=='register-link':
                        registered=bot.register_link()
                        bot.enable(True)
                        get_runtime().restart()
                        return registered
                    if action=='listener':
                        bot.enable(data['enabled'])
                        if data['enabled']:get_runtime().restart()
                        else:get_runtime().stop()
                        return get_runtime().status()
                    if action=='unlink':return bot.unlink()
                except Exception as exc:
                    bot.log(str(exc),error=True)
                    raise ValueError(bot.clean(str(exc))) from None
            raise ValueError('Integração desconhecida.')
        if path.startswith('/apps/'):
            _, _, identity, action = path.split('/', 3)
            return self.apps.call(identity, action, data, self)
        if path == '/native':
            return self.native(data['action'], data.get('payload', {}))
        if path=='/logs/clear':
            directory=(BASE_DIR/'logs').resolve()
            if data.get('all') is True:files=list(directory.rglob('*.log'))
            else:
                name=data.get('name','')
                if not isinstance(name,str) or '..' in Path(name).parts or Path(name).is_absolute() or not name.endswith('.log'):raise ValueError('Log inválido.')
                files=[directory/name]
            cleared=[]
            for file in files:
                if not file.resolve().is_relative_to(directory) or not file.is_file():raise ValueError('Log não encontrado.')
                with file.open('wb'):pass
                cleared.append(file.relative_to(directory).as_posix())
            return {'cleared':cleared}
        if path == '/logs':
            from src.log_reader import read_log
            result = []
            directory=BASE_DIR/'logs'
            for identity,_ in self.plugin_folders():
                file=directory/'plugins'/(identity+'.log')
                if not file.resolve().is_relative_to(directory.resolve()):continue
                file.parent.mkdir(parents=True,exist_ok=True);file.touch(exist_ok=True)
            for file in sorted(directory.rglob('*.log')):
                if not file.resolve().is_relative_to(directory.resolve()):continue
                result.append(read_log(file.relative_to(directory).as_posix()))
            return result
        raise ValueError('Operação não encontrada.')


_service = None
_service_lock = threading.Lock()


def get_service():
    global _service
    with _service_lock:
        if _service is None:
            _service = WorkspaceService()
        return _service
