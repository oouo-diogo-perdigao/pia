"""Local scheduler. Google data stays in this process; no hosted bot service."""
from datetime import datetime, timedelta, timezone
import json
import re
import logging
from pathlib import Path
import threading
import webbrowser
from urllib.parse import urlsplit

from src.config_paths import BASE_DIR
from src.resource_plugins import save_json

MAIL_FILTERS={'important_unread':('Não lidos importantes','is:unread is:important'),'all_unread':('Todos os não lidos','is:unread'),'inbox_unread':('Não lidos da caixa de entrada','is:unread in:inbox'),'starred_unread':('Não lidos com estrela','is:unread is:starred'),'custom':('Personalizado (avançado)',None)}

DEFAULTS = {'enabled': False, 'accounts': [], 'reminders': True, 'remind_minutes': 10,
            'open_meetings': False, 'meet_minutes': 2, 'important_email': True, 'email_query': 'is:unread is:important',
            'poll_seconds': 30, 'calendar': 'primary', 'email_filter':'important_unread',
            'avatar_primary':'#ad83ff','avatar_accent':'#65d9ff','avatar_eyes':'#faf4ff'}


class Secretary:
    def __init__(self, resources, store, notify, opener=webbrowser.open, config_path=None):
        self.resources, self.store, self.notify, self.opener = resources, store, notify, opener
        self.path = Path(config_path or Path(__file__).with_name('config.json'))
        self.stop_event = threading.Event()
        self.poll_lock = threading.Lock()
        self.thread = None
        self.notification_center=None

    def announce(self,title,text,links=None):
        if self.notification_center:
            return self.notification_center.publish('Bot/secretaria',title,text,links)
        self.notify(title,text,False)

    def bind_notifications(self,center):
        self.notification_center=center
        if not self.store.get('notifications:migrated-secretary',False):
            saved=json.loads(self.path.read_text(encoding='utf-8')) if self.path.is_file() else {}
            if saved.get('speak') and self.store.get('notifications:settings') is None:
                center.configure({'read_aloud':True,'muted':[]})
            self.store.set('notifications:migrated-secretary',True)

    def config(self):
        saved=json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
        data={**DEFAULTS,**saved}
        data.pop('speak',None)
        if 'email_filter' not in saved:data['email_filter']=next((key for key,(_,query) in MAIL_FILTERS.items() if query==data['email_query']),'custom')
        return data

    def configure(self, values):
        data = {**self.config(), **values}
        if 'email_query' in values and 'email_filter' not in values:data['email_filter']=next((key for key,(_,query) in MAIL_FILTERS.items() if query==data['email_query']),'custom')
        if data['email_filter'] not in MAIL_FILTERS:raise ValueError('Filtro de e-mail inválido.')
        if data['email_filter']!='custom':data['email_query']=MAIL_FILTERS[data['email_filter']][1]
        if not isinstance(data['email_query'],str) or len(data['email_query'])>1000:raise ValueError('Filtro personalizado inválido.')
        for color in ('avatar_primary','avatar_accent','avatar_eyes'):
            if not isinstance(data[color],str) or not re.fullmatch('#[a-fA-F0-9]{6}',data[color]):raise ValueError('Cor de avatar inválida.')
        for key in ('enabled', 'reminders', 'open_meetings', 'important_email'):
            if not isinstance(data[key], bool):
                raise ValueError(key + ' deve ser booleano.')
        if not 1 <= int(data['remind_minutes']) <= 1440 or not 15 <= int(data['poll_seconds']) <= 3600:
            raise ValueError('Lembretes: 1–1440 minutos; consulta: 15–3600 segundos.')
        if not 0 <= int(data['meet_minutes']) <= 1440:
            raise ValueError('Antecedência do Meet: 0–1440 minutos.')
        data['meet_minutes'] = int(data['meet_minutes'])
        connected = {a['id'] for a in self.resources.accounts('google')}
        if not isinstance(data['accounts'], list) or set(data['accounts']) - connected:
            raise ValueError('Selecione somente contas Google conectadas.')
        data['remind_minutes'], data['poll_seconds'] = int(data['remind_minutes']), int(data['poll_seconds'])
        save_json(self.path, {k: data[k] for k in DEFAULTS})

    def _events(self, account, config, now):
        token = None
        while True:
            params = dict(calendar=config['calendar'], timeMin=now.isoformat(),
                          timeMax=(now + timedelta(days=1)).isoformat(), singleEvents='true',
                          orderBy='startTime', maxResults=250)
            if token:
                params['pageToken'] = token
            page = self.resources.call('google', 'calendar.list', account=account, **params)
            yield from page.get('items', [])
            token = page.get('nextPageToken')
            if not token:
                break

    def _mail(self, account, config, now):
        since_key = 'secretary:mail-since:' + account
        since = self.store.get(since_key)
        if since is None:
            # A newly enabled account starts now; don't announce its entire unread inbox.
            self.store.set(since_key, int(now.timestamp()))
            return
        query = config['email_query'] + ' after:' + str(since)
        token = None
        ids = []
        while True:
            params = dict(q=query, maxResults=100)
            if token:
                params['pageToken'] = token
            page = self.resources.call('google', 'mail.list', account=account, **params)
            ids.extend(m['id'] for m in page.get('messages', []))
            token = page.get('nextPageToken')
            if not token:
                break
        for identity in ids:
            key = f'secretary:mail:{account}:{identity}'
            if self.store.get(key):
                continue
            message = self.resources.call('google', 'mail.get', account=account, id=identity,
                                          format='metadata', metadataHeaders=['Subject', 'From'])
            headers = {h['name'].lower(): h['value'] for h in message.get('payload', {}).get('headers', [])}
            if self.store.claim(key):
                address=next((a.get('email') or '' for a in self.resources.accounts('google') if a['id']==account),'')
                from urllib.parse import quote
                self.announce('E-mail importante', headers.get('subject', 'Sem assunto') +
                            ' — ' + headers.get('from', ''),[{'label':'Abrir e-mail','url':'https://mail.google.com/mail/?authuser='+quote(address,safe='')+'#all/'+identity}])
        # Overlap tolerates delayed delivery/indexing; persistent IDs prevent duplicates.
        self.store.set(since_key, max(since, int(now.timestamp()) - 3600))

    def poll(self, now=None):
        if not self.poll_lock.acquire(blocking=False):
            return
        try:
            config = self.config()
            if not config['enabled']:
                return
            now = now or datetime.now(timezone.utc)
            for account in config['accounts']:
                errors = []
                if config['reminders'] or config['open_meetings']:
                    try:
                        for event in self._events(account, config, now):
                            if event.get('status') == 'cancelled' or any(
                                a.get('self') and a.get('responseStatus') == 'declined' for a in event.get('attendees', [])):
                                continue
                            value = event.get('start', {}).get('dateTime')
                            if not value:  # all-day events have no timed meeting to join
                                continue
                            start = datetime.fromisoformat(value.replace('Z', '+00:00'))
                            if start.tzinfo is None:
                                continue
                            remaining = (start - now).total_seconds()
                            if remaining < 0:
                                continue
                            key = f"secretary:event:{account}:{event['id']}:{start.isoformat()}"
                            title = event.get('summary', 'Compromisso')
                            if config['reminders'] and remaining <= config['remind_minutes'] * 60:
                                if self.store.claim(key + ':reminder'):
                                    links=[]
                                    if event.get('htmlLink'):links.append({'label':'Abrir compromisso','url':event['htmlLink']})
                                    meet=event.get('hangoutLink') or next((e.get('uri','') for e in event.get('conferenceData',{}).get('entryPoints',[]) if e.get('entryPointType')=='video'),'')
                                    if meet:links.append({'label':'Entrar no Meet','url':meet})
                                    self.announce('Compromisso em breve', title,links)
                            if config['open_meetings'] and remaining <= config['meet_minutes'] * 60:
                                url = event.get('hangoutLink') or next((
                                    e.get('uri', '') for e in event.get('conferenceData', {}).get('entryPoints', [])
                                    if e.get('entryPointType') == 'video'), '')
                                parsed = urlsplit(url)
                                if parsed.scheme == 'https' and parsed.hostname == 'meet.google.com':
                                    if self.store.claim(key + ':open'):
                                        self.opener(url)
                    except Exception as exc:
                        errors.append(type(exc).__name__ + ': ' + str(exc))
                if config['important_email']:
                    try:
                        self._mail(account, config, now)
                    except Exception as exc:
                        errors.append(type(exc).__name__ + ': ' + str(exc))
                self.store.set('secretary:status:' + account,
                               {'checked_at': now.isoformat(), 'errors': errors})
                from src.plugin_logs import write
                write('Bot/secretaria','Consulta de agenda e e-mails', 'erro' if errors else 'ok')
        finally:
            self.poll_lock.release()

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        def work():
            while not self.stop_event.is_set():
                try:
                    self.poll()
                    delay = max(15, int(self.config()['poll_seconds']))
                except Exception:
                    logging.exception('[SECRETARIA] Falha no ciclo local')
                    delay = 60
                self.stop_event.wait(delay)
        self.thread = threading.Thread(target=work, daemon=True, name='pia-secretaria')
        self.thread.start()

    def stop(self):
        self.stop_event.set()
