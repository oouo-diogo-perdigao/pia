"""Workspace tools route explicit requests to PIA; generated assets survive API cache expiry."""
import base64
import io
import json
from pathlib import Path
import re
import unicodedata
import uuid
import requests
from . import app_access
from .config_paths import BASE_DIR

MARKDOWN_INSTRUCTION='Responda sempre em Markdown legível, em português. Use títulos, listas, tabelas e blocos de código quando ajudarem. Não envolva a resposta inteira em uma cerca de código Markdown. Não afirme que executou uma ação ou criou uma imagem se uma ferramenta não foi executada.'

def save_camera(result):
    root=BASE_DIR/'data/chat-images';root.mkdir(parents=True,exist_ok=True)
    name=uuid.uuid4().hex+'.png'
    (root/name).write_bytes(base64.b64decode(result['data'],validate=True))
    return '![Foto da câmera](/api/pia/chat/assets/'+name+')'

def allowed_tools(text):
    plain=unicodedata.normalize('NFKD',text.lower()).encode('ascii','ignore').decode()
    tools=set()
    if re.search(r'\b(agenda|compromissos?|email|gmail|drive|arquivos|contas|calendario)\b',plain):tools.update(('pia_accounts','pia_resources'))
    if re.search(r'\b(codex|agy|antigravity)\b',plain):tools.add('pia_delegate')
    return tools

def image_intent(text):
    plain=''.join(c for c in unicodedata.normalize('NFD',text.lower()) if not unicodedata.combining(c)).strip()
    if re.match(r'^(como|explique|o que|qual|nao|não)\b',plain):return False
    image=re.search(r'\b(imagem|imagens|image|images|ilustracao|foto|fotografia|desenho|arte)\b',plain)
    purpose=re.search(r'\b(texto|explicacao|tutorial|codigo|prompt|instrucoes)\b',plain)
    if image and purpose and purpose.start()<image.start():return False
    # Explicit imperatives and polite requests; questions about image generation stay textual.
    return bool(re.match(r'^(?:(?:por favor[, ]*|pia[, ]*|agora[, ]*)|(?:voce (?:pode|consegue)\s+)|(?:pode\s+))*'r'(?:(?:gere|gerar|crie|criar|faca|fazer|generate|create)\b[^\n]{0,100}\b(?:imagem|imagens|image|images|ilustracao|foto|fotografia|desenho|arte)\b|(?:desenhe|draw|ilustre)\b)',plain))

class ChatTools:
    def __init__(self,root=None,base_url=None,session=None,timeout=3600):
        self.root=Path(root or BASE_DIR/'data/chat-images');self.base_url=base_url;self.session=session or requests.Session();self.timeout=timeout
        if session is None:self.session.trust_env=False
    def execute(self,text):
        plain=unicodedata.normalize('NFKD',text.lower()).encode('ascii','ignore').decode()
        if re.search(r'\b(tire|tirar|capture|capturar|fotografe)\b',plain) and re.search(r'\b(camera|webcam)\b',plain):
            from .tool_registry import call
            return save_camera(call('pia_camera',{}))
        if re.search(r'\b(gere|gerar|crie|criar|componha|compor)\b',plain) and re.search(r'\b(musica|cancao|song|music)\b',plain):
            from Plugins.Apps.music.service import generate
            result=generate(text,provider='gemini' if 'gemini' in plain or 'lyria' in plain else 'local')
            return f"[Música gerada]({result['audio_url']})"
        if not image_intent(text):return None
        return self.generate_image(text)
    def generate_image(self,prompt):
        context=app_access.issue('pia_chat',routes={'/v1/images/generations'})
        try:
            settings=json.loads(context)
            base=self.base_url or settings['url']
            try:
                response=self.session.post(base.rstrip('/')+'/v1/images/generations',json={'prompt':prompt,'n':1,'response_format':'b64_json'},headers={'X-PIA-App-Token':settings['token']},timeout=self.timeout)
            except requests.RequestException as exc:raise RuntimeError('Não foi possível acessar a rota de geração de imagens da PIA.') from exc
            try:
                data=response.json()
            except ValueError as exc:raise RuntimeError('A rota de imagens não retornou JSON válido.') from exc
            if response.status_code>=400:
                detail=data.get('error',{}).get('message','Falha na geração de imagem.') if isinstance(data,dict) else 'Falha na geração de imagem.'
                raise RuntimeError(f'PIA: geração de imagem retornou HTTP {response.status_code}. {detail}')
            entries=data.get('data',[]) if isinstance(data,dict) else []
            if not entries:raise RuntimeError('A PIA não retornou uma imagem gerada.')
            from PIL import Image
            links=[]
            for entry in entries[:4]:
                encoded=entry.get('b64_json','')
                if not isinstance(encoded,str) or len(encoded)>40*1024**2:raise RuntimeError('A imagem retornada é inválida ou excede 30 MiB.')
                try:
                    raw=base64.b64decode(encoded,validate=True)
                    with Image.open(io.BytesIO(raw)) as image:
                        kind=image.format
                        image.verify()
                    extension={'PNG':'png','JPEG':'jpg','WEBP':'webp'}[kind]
                except Exception as exc:raise RuntimeError('A PIA retornou dados de imagem inválidos.') from exc
                self.root.mkdir(parents=True,exist_ok=True)
                name=uuid.uuid4().hex+'.'+extension
                (self.root/name).write_bytes(raw)
                links.append('![Imagem gerada pela PIA](/api/pia/chat/assets/'+name+')')
            return '\n\n'.join(links)
        finally:app_access.revoke(context)
