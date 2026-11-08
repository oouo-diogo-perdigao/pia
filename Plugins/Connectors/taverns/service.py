"""Taverns bot operations shared by connector settings and publication jobs."""

import re

import requests

from src.plugin_logs import write
from src.settings_store import get
from Plugins.Connectors.pia_server.remote import managed, runtime

IDENTITY = 'Connectors/taverns'
API_URL = 'https://api.tav.gg/api/v1'
UUID = r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}'
MESSAGE_LIMIT = 2000


def destination_ids(destination):
    if not isinstance(destination, str) or not re.fullmatch(f'{UUID}/{UUID}', destination, re.IGNORECASE):
        raise ValueError('Selecione um canal válido da Tav.gg.')
    return destination.split('/')


class Taverns:
    def __init__(self):
        self.token = (runtime('taverns')['settings'].get('TAVERNS_BOT_TOKEN', '') if managed()
                      else get('TAVERNS_BOT_TOKEN', '', section=IDENTITY)).strip()

    def request(self, method, path, **kwargs):
        if not self.token:
            raise ValueError('Salve o token do bot nas configurações de Taverns.')
        try:
            response = requests.request(
                method, API_URL + path, headers={'Authorization': 'Bot ' + self.token},
                timeout=10, allow_redirects=False, **kwargs,
            )
        except requests.RequestException:
            write(IDENTITY, method, 'Falha de conexão')
            raise RuntimeError('Não foi possível acessar a Tav.gg.') from None
        write(IDENTITY, method, f'HTTP {response.status_code}')
        if not 200 <= response.status_code < 300:
            if response.status_code == 403:
                try:
                    payload = response.json()
                except ValueError:
                    payload = None
                if isinstance(payload, dict) and payload.get('error') == 'AGE_VERIFICATION_REQUIRED':
                    write(IDENTITY, method, 'AGE_VERIFICATION_REQUIRED')
                    raise ValueError(
                        'Tav.gg bloqueou o acesso por restrição etária (AGE_VERIFICATION_REQUIRED). '
                        'Confira se a taverna ou o canal tem restrição de conteúdo adulto. '
                        'Se a classificação estiver correta, consulte o suporte da Tav.gg sobre o acesso do bot.'
                    )
            detail = {
                401: 'Confira o token do bot.',
                403: 'Confira se o bot está instalado e tem permissão no canal.',
                404: 'Confira se o bot ainda tem acesso à taverna e ao canal.',
                429: 'Aguarde antes de tentar novamente.',
            }.get(response.status_code, 'A Tav.gg recusou a operação.')
            raise ValueError(f'Tav.gg respondeu HTTP {response.status_code}. {detail}')
        try:
            return response.json()
        except ValueError:
            raise RuntimeError('A Tav.gg retornou uma resposta inválida.') from None

    def channels(self):
        if not self.token:
            return {'configured': False, 'channels': []}
        result = {}
        for tavern in self.request('GET', '/bots/@me/taverns'):
            tavern_id = tavern['id']
            if not re.fullmatch(UUID, tavern_id, re.IGNORECASE):
                continue
            response = self.request('GET', f'/taverns/{tavern_id}/channels')
            channels = response.get('channels') if isinstance(response, dict) else response
            if not isinstance(channels, list) or any(not isinstance(channel, dict) for channel in channels):
                raise ValueError('A Tav.gg retornou uma lista de canais em formato inesperado.')
            for channel in channels:
                if channel['type'] not in ('TEXT', 'ANNOUNCEMENT') or channel.get('isArchived'):
                    continue
                destination = f"{tavern_id}/{channel['id']}"
                destination_ids(destination)
                result[destination] = {
                    'value': destination,
                    'label': f"{tavern['name']} / #{channel['name']}",
                }
        return {'configured': True, 'channels': sorted(result.values(), key=lambda item: item['label'].casefold())}

    def send(self, text, destination):
        tavern, channel = destination_ids(destination)
        if not isinstance(text, str) or not text.strip() or len(text) > MESSAGE_LIMIT:
            raise ValueError('A mensagem da Tav.gg deve ter de 1 a 2000 caracteres.')
        result = self.request('POST', f'/taverns/{tavern}/channels/{channel}/messages', json={'content': text})
        if not isinstance(result, dict) or not result.get('id') or result.get('status') in ('FILTERED', 'DELETED'):
            raise ValueError('A Tav.gg não confirmou a publicação da mensagem.')
        return {'id': result['id']}
