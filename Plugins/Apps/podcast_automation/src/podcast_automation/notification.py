"""Optional publication announcements through shared PIA/Discord integrations."""
import requests
from src.app_access import current,headers
from .settings import get_config

def announce_publication(episode,campaign,links=None):
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
            discord_text=text+'\n'+'\n'.join(f'{label}: {url}' for label,url in (links or {}).items() if isinstance(url,str) and url.startswith(('https://','http://')))
            messages=[];message=''
            for line in discord_text.splitlines():
                if len(line)>2000:raise ValueError('Um link de publicação excede o limite de mensagem do Discord.')
                if message and len(message)+len(line)+1>2000:
                    messages.append(message);message=''
                message=(message+'\n'+line).strip()
            if message:messages.append(message)
            channels=options.get('discord_channels') or [options.get('discord_channel')]
            for channel in dict.fromkeys(channels):
                for message in messages:Discord().send(message,channel)
        except Exception:
            print('Aviso: Discord não confirmou a notificação; os arquivos continuam publicados.')
            ok=False
    return ok
