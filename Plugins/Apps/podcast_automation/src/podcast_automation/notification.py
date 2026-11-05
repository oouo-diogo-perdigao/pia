"""Optional publication announcements through shared PIA/Discord integrations."""
import requests
import re
from src.app_access import current,headers
from .settings import get_config

def announce_publication(episode,campaign,links=None,season=None,number=None,players=()):
    options=get_config().get('integrations',{})
    text=f"Episódio '{episode}' da mesa {campaign} publicado."
    ok=True
    if options.get('announce'):
        try:
            response=requests.post(current()['url']+'/tts/speak',json={'text':text},headers=headers(),timeout=30)
            ok=response.status_code==200
        except requests.RequestException:ok=False
    if options.get('discord_notify'):
        try:
            from Plugins.Connectors.discord.service import Discord
            code=f'S{int(season):02d}E{int(number):02d}' if season is not None and number is not None else ''
            heading=' - '.join(part for part in (campaign,code,episode) if part)
            links=links or {}
            entries={'MP3':links.get('MP3'),'RSS':links.get('RSS'),
                     'TRANSCRIÇÃO':links.get('Transcrições gerais') or links.get('Transcrição TXT')}
            discord_text=heading+'\n'+'\n'.join(f'{label}: {url}' for label,url in entries.items() if isinstance(url,str) and url.startswith(('https://','http://')))
            mapping=get_config().get('discord_users',{})
            if not isinstance(mapping,dict):raise ValueError('discord_users deve mapear nomes de jogadores para IDs do Discord.')
            mentions=list(dict.fromkeys(str(mapping[player]) for player in players if player in mapping and re.fullmatch(r'[0-9]{1,20}',str(mapping[player]))))
            if mentions:discord_text+='\n'+' '.join('<@'+identity+'>' for identity in mentions)
            messages=[];message=''
            for line in discord_text.splitlines():
                if len(line)>2000:raise ValueError('Um link de publicação excede o limite de mensagem do Discord.')
                if message and len(message)+len(line)+1>2000:
                    messages.append(message);message=''
                message=(message+'\n'+line).strip()
            if message:messages.append(message)
            channels=options.get('discord_channels') or [options.get('discord_channel')]
            for channel in dict.fromkeys(channels):
                for message in messages:
                    if mentions:Discord().send(message,channel,mentions=mentions)
                    else:Discord().send(message,channel)
        except Exception:
            print('Aviso: Discord não confirmou a notificação; os arquivos continuam publicados.')
            ok=False
    return ok
