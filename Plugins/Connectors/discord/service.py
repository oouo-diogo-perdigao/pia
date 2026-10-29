"""Discord REST integration and local publication-channel binding."""
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import threading

import requests
from dotenv import set_key, unset_key, dotenv_values as raw_values
from src.env_types import dotenv_values, split_key
from src.resource_plugins import save_json

ROOT = Path(__file__).resolve().parent
API = 'https://discord.com/api/v10'
_lock = threading.RLock()


class Discord:
    def __init__(self, root=ROOT, session=None, log_path=None):
        self.root = Path(root)
        self.session = session or requests.Session()
        self.log_path = Path(log_path or (ROOT.parents[2] / 'logs/discord.log' if self.root == ROOT else self.root / 'discord.log'))

    def config(self):
        return dotenv_values(self.root / '.env')

    def clean(self, text):
        text = str(text)
        for key, value in raw_values(self.root / '.env').items():
            if value and any(part in key for part in ('TOKEN', 'SECRET')):
                text = text.replace(value, '[REDACTED]')
        return text

    def log(self, text, error=False):
        with _lock:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            logger = logging.getLogger('pia.discord.' + str(self.log_path.resolve()))
            if not logger.handlers:
                handler = RotatingFileHandler(self.log_path, maxBytes=1_000_000, backupCount=2, encoding='utf-8', delay=True)
                handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
                logger.addHandler(handler)
                logger.setLevel(logging.INFO)
                logger.propagate = False
            logger.log(logging.ERROR if error else logging.INFO, self.clean(text))
            # Release the file between writes, including on Windows and in tests.
            for handler in logger.handlers:
                handler.close()

    def logs(self):
        if not self.log_path.exists():
            return ''
        with self.log_path.open('rb') as stream:
            stream.seek(max(0, self.log_path.stat().st_size - 32000))
            return self.clean(stream.read().decode('utf-8', errors='replace'))

    def request(self, method, path, **kwargs):
        token = self.config().get('DISCORD_BOT_TOKEN')
        if not token:
            raise ValueError('Configure o token do bot Discord e salve as variáveis.')
        try:
            response = getattr(self.session, method.lower())(API + path,
                headers={'Authorization': 'Bot ' + token}, timeout=30, **kwargs)
            try:
                if response.status_code >= 400:
                    try:
                        data = response.json()
                    except ValueError:
                        data = {'message': response.text[:4000]}
                    detail = self.clean(json.dumps(data, ensure_ascii=False))[:5000]
                    raise RuntimeError(f'Discord {method} {path}: HTTP {response.status_code} · {detail}')
                return response.json() if response.status_code != 204 else {}
            finally:
                response.close()
        except Exception as exc:
            message = self.clean(str(exc))
            self.log(message, error=True)
            raise RuntimeError(message) from None

    def public(self):
        value = self.config()
        return {'id': value.get('DISCORD_BOT_ID', ''), 'invite_url': value.get('DISCORD_BOT_URL', ''),
                'community_url': value.get('DISCORD_LINK', ''), 'configured': bool(value.get('DISCORD_BOT_TOKEN')),
                'channel': value.get('DISCORD_CHANNEL_ID', ''), 'linked': self.binding(),
                'link_enabled': value.get('DISCORD_LINK_ENABLED', 'false') == 'true'}

    def send(self, text, channel=None):
        channel = channel or self.config().get('DISCORD_CHANNEL_ID')
        if not channel or not re.fullmatch('[0-9]+', str(channel)):
            raise ValueError('Configure o canal do Discord para notificações ou use /link no canal desejado.')
        result = self.request('POST', '/channels/' + str(channel) + '/messages',
            json={'content': str(text)[:2000], 'allowed_mentions': {'parse': []}})
        self.log(f'Mensagem enviada: canal={channel}, mensagem={result["id"]}.')
        return {'id': result['id'], 'channel': str(channel)}

    def diagnose(self, channel=None):
        user = self.request('GET', '/users/@me')
        app = self.request('GET', '/oauth2/applications/@me')
        configured = self.config().get('DISCORD_BOT_ID')
        if not user.get('bot') or (configured and configured != app['id']):
            raise ValueError('DISCORD_BOT_ID não corresponde à aplicação do token informado.')
        result = {'id': app['id'], 'name': app.get('name', user.get('username', '')),
                  'interactions_endpoint': bool(app.get('interactions_endpoint_url'))}
        channel = channel or self.config().get('DISCORD_CHANNEL_ID')
        if channel:
            if not re.fullmatch('[0-9]+', str(channel)):
                raise ValueError('ID do canal inválido.')
            info = self.request('GET', '/channels/' + str(channel))
            result['channel'] = {'id': info['id'], 'name': info.get('name', ''), 'guild': info.get('guild_id', '')}
        self.log(f'Diagnóstico OK: bot={app["id"]}. Token válido; nenhuma mensagem enviada.')
        return result

    def register_link(self):
        # A stale channel must not prevent repairing it via /link.
        app = self.request('GET', '/oauth2/applications/@me')
        configured = self.config().get('DISCORD_BOT_ID')
        if configured and configured != app['id']:
            raise ValueError('DISCORD_BOT_ID não corresponde à aplicação do token informado.')
        if app.get('interactions_endpoint_url'):
            raise ValueError('O bot usa um Interactions Endpoint URL. Remova esse endpoint no Developer Portal para receber /link pela PIA local. Nenhum endpoint foi alterado automaticamente.')
        result = self.request('POST', '/applications/' + app['id'] + '/commands', json={
            'name': 'link', 'description': 'Vincula este canal às publicações da PIA local e informa o ID.',
            'type': 1, 'default_member_permissions': '8', 'contexts': [0], 'integration_types': [0]})
        self.log(f'Comando /link registrado/atualizado: aplicação={app["id"]}, comando={result["id"]}, apenas administradores.')
        return {'id': result['id'], 'application': app['id'], 'name': 'link'}

    def enable(self, enabled):
        if not isinstance(enabled, bool):
            raise ValueError('Estado do listener inválido.')
        with _lock:
            self.set_value('DISCORD_LINK_ENABLED', str(enabled).lower(), preferred='DISCORD_LINK_ENABLED__BOOL')

    def set_value(self, name, value, preferred=None):
        """Respect an existing explicit type and remove legacy aliases that could shadow it."""
        path=self.root / '.env'
        aliases=[key for key in raw_values(path) if split_key(key)[0]==name]
        key=preferred or next((key for key in aliases if split_key(key)[0]!=key),name)
        set_key(path,key,str(value))
        for alias in aliases:
            if alias!=key:unset_key(path,alias)
        path.chmod(0o600)

    def binding(self):
        file = self.root / 'config.json'
        return json.loads(file.read_text(encoding='utf-8')).get('linked', {}) if file.exists() else {}

    def link(self, *, guild, channel, user, permissions, app_permissions, application):
        """Called only by the authenticated Gateway, never exposed as HTTP input."""
        value = self.config()
        if value.get('DISCORD_LINK_ENABLED', 'false') != 'true':
            raise PermissionError('O comando /link está desativado nesta PIA.')
        if not guild or not (int(permissions) & 8):
            raise PermissionError('Somente administradores do servidor podem usar /link. Mensagens diretas não são aceitas.')
        for identity in (guild, channel, user, application):
            if not re.fullmatch('[0-9]+', str(identity)):
                raise ValueError('Identificador do Discord inválido.')
        if value.get('DISCORD_BOT_ID') and str(application) != value['DISCORD_BOT_ID']:
            raise PermissionError('Aplicação do Discord inválida.')
        admins = [s for s in re.split(r'[\s,;]+', value.get('DISCORD_ADMIN_USER_IDS', '').strip()) if s]
        if admins and str(user) not in admins:
            raise PermissionError('Este administrador não está na lista DISCORD_ADMIN_USER_IDS da PIA.')
        app_permissions = int(app_permissions)
        if not (app_permissions & 8) and (app_permissions & 3072) != 3072:
            raise PermissionError('O bot precisa de Ver canal e Enviar mensagens neste canal.')
        with _lock:
            linked = self.binding()
            restricted = value.get('DISCORD_GUILD_ID') or linked.get('guild')
            if restricted and str(guild) != str(restricted):
                raise PermissionError('Esta PIA está vinculada a outro servidor. Remova o vínculo nas configurações locais primeiro.')
            info = self.request('GET', '/channels/' + str(channel))
            if str(info.get('guild_id')) != str(guild) or info.get('type') not in (0, 5):
                raise ValueError('Use /link em um canal de texto ou anúncios do servidor.')
            guild_info=self.request('GET','/guilds/'+str(guild))
            self.set_value('DISCORD_CHANNEL_ID', str(channel))
            file = self.root / 'config.json'
            data = json.loads(file.read_text(encoding='utf-8')) if file.exists() else {}
            channels=data.get('channels',[]) or ([data['linked']] if data.get('linked') else [])
            data['linked'] = dict(guild=str(guild), channel=str(channel), name=info.get('name', ''),
                                  user=str(user), at=datetime.now(timezone.utc).isoformat())
            data['linked']['guild_name']=guild_info.get('name',str(guild))
            channels=[{**item,'guild_name':item.get('guild_name') or guild_info.get('name',str(guild))} for item in channels]
            data['channels']=[c for c in channels if c['channel']!=str(channel)]+[data['linked'].copy()]
            save_json(file, data)
        self.log(f'/link concluído: servidor={guild}, canal={channel}, administrador={user}.')
        return {'channel': str(channel), 'text': f'Canal vinculado à PIA local.\nDISCORD_CHANNEL_ID={channel}\nO valor já foi salvo nas configurações da PIA. Publicações com um canal específico no Podcast Automation continuam usando esse canal; deixe-o vazio para usar o padrão.'}

    def channels(self):
        file=self.root/'config.json'
        data=json.loads(file.read_text(encoding='utf-8')) if file.exists() else {}
        rows=data.get('channels',[])
        if not rows and data.get('linked'):rows=[data['linked']]
        return rows

    def unlink(self):
        with _lock:
            file = self.root / 'config.json'
            data = json.loads(file.read_text(encoding='utf-8')) if file.exists() else {}
            data.pop('linked', None)
            save_json(file, data)
            self.set_value('DISCORD_CHANNEL_ID', '')
        self.log('Vínculo de publicação removido na interface local.')
        return {'ok': True}
