"""Music providers. Local ACE-Step is isolated from PIA's Torch environment."""
import atexit
import base64
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit
import uuid
import requests
from src.config_paths import BASE_DIR
from src.env_types import dotenv_values
from src.resource_plugins import save_json

ROOT=Path(__file__).resolve().parent
CACHE=BASE_DIR/'cache/Apps/music'
OUTPUT=BASE_DIR/'data/music'
REVISION='ca1e85fe9430179831e6bc6be790c332190a3866'
_engine=None
_token=secrets.token_urlsafe(40)
_lock=threading.Lock()
_generation_lock=threading.Lock()

def settings():return dotenv_values(ROOT/'.env')
def base_url():
    url=settings().get('MUSIC_LOCAL_URL') or 'http://127.0.0.1:8015'
    parsed=urlsplit(url)
    if parsed.scheme!='http' or parsed.hostname not in ('localhost','127.0.0.1','::1') or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment:raise ValueError('ACE-Step deve usar uma URL HTTP de loopback sem caminho ou credenciais.')
    return url.rstrip('/')

def prepare(report=lambda text:None):
    uv=shutil.which('uv');git=shutil.which('git')
    if not uv or not git:raise RuntimeError('Instale uv e Git para preparar o motor local.')
    CACHE.mkdir(parents=True,exist_ok=True);repo=CACHE/'ace-step'
    flags={'creationflags':subprocess.CREATE_NO_WINDOW} if sys.platform=='win32' else {}
    with _lock:
        if not (repo/'.git').exists():
            report('Baixando código oficial do ACE-Step para um ambiente separado…')
            subprocess.run([git,'clone','--filter=blob:none','https://github.com/ace-step/ACE-Step-1.5.git',str(repo)],check=True,capture_output=True,timeout=300,**flags)
        subprocess.run([git,'-C',str(repo),'checkout','--detach',REVISION],check=True,capture_output=True,timeout=120,**flags)
        report('Instalando dependências do motor local. O download pode ocupar vários GB.')
        subprocess.run([uv,'sync','--project',str(repo),'--python','3.12'],check=True,capture_output=True,timeout=3600,**flags)
    report('Motor instalado. Os pesos serão baixados pelo ACE-Step no primeiro início.')
    return {'installed':True}

def _json(response):
    try:
        if not 200<=response.status_code<300:raise RuntimeError(f'O provedor musical retornou HTTP {response.status_code}. Confira acesso, cotas e credenciais.')
        return response.json()
    finally:response.close()

def engine(session,progress,cancelled):
    global _engine
    url=base_url()
    key=settings().get('MUSIC_LOCAL_KEY') or (_token if _engine is not None and _engine.poll() is None else '')
    headers={'Authorization':'Bearer '+key} if key else {}
    try:
        health=_json(session.get(url+'/health',headers=headers,timeout=2,allow_redirects=False))
        if health.get('data',{}).get('service')!='ACE-Step API':raise RuntimeError('O endereço local não é um motor ACE-Step.')
        return url,headers
    except requests.ConnectionError:pass
    with _lock:
        repo=CACHE/'ace-step';uv=shutil.which('uv')
        if not uv or not (repo/'.venv').is_dir():raise RuntimeError('Prepare o motor local pelo botão Instalar motor local no app Música.')
        if _engine is None or _engine.poll() is not None:
            env=os.environ.copy();env.update(ACESTEP_API_HOST='127.0.0.1',ACESTEP_API_PORT=str(urlsplit(url).port or 80),ACESTEP_API_KEY=_token,ACESTEP_LM_BACKEND='pt',ACESTEP_OFFLOAD_TO_CPU='true',ACESTEP_USE_FLASH_ATTENTION='false',HF_HOME=str(CACHE/'models'))
            log=BASE_DIR/'logs/plugins/Apps/music-engine.log';log.parent.mkdir(parents=True,exist_ok=True)
            with log.open('ab') as stream:
                _engine=subprocess.Popen([uv,'run','--project',str(repo),'acestep-api'],cwd=repo,env=env,stdout=stream,stderr=subprocess.STDOUT,**({'creationflags':subprocess.CREATE_NO_WINDOW} if sys.platform=='win32' else {}))
    headers={'Authorization':'Bearer '+_token}
    progress('Iniciando ACE-Step e carregando modelos…')
    for _ in range(600):
        if cancelled():raise InterruptedError('Geração musical cancelada.')
        if _engine.poll() is not None:raise RuntimeError('O motor local encerrou. Consulte o log music-engine.log.')
        try:
            _json(session.get(url+'/health',headers=headers,timeout=2,allow_redirects=False));return url,headers
        except (requests.RequestException,RuntimeError):time.sleep(2)
    raise RuntimeError('O motor não ficou pronto em 20 minutos. Consulte seus logs.')

def stop_engine():
    if _engine is not None and _engine.poll() is None:_engine.terminate()
atexit.register(stop_engine)

def audio_file(name):
    if not re.fullmatch(r'[a-f0-9]{32}\.(mp3|wav|flac)',name):raise ValueError('Áudio inválido.')
    path=OUTPUT/name
    if not path.is_file():raise ValueError('Áudio não encontrado.')
    return path

def generate(prompt,lyrics='',provider='local',duration=30,progress=lambda text:None,cancelled=lambda:False):
    if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>8000:raise ValueError('Descrição obrigatória (até 8000 caracteres).')
    if not isinstance(lyrics,str) or len(lyrics)>16000:raise ValueError('Letra inválida.')
    if isinstance(duration,bool) or not isinstance(duration,int) or not 10<=duration<=180:raise ValueError('Duração deve estar entre 10 e 180 segundos.')
    if provider not in ('local','gemini'):raise ValueError('Escolha local ou gemini. Flow Music é usado na interface oficial.')
    if not _generation_lock.acquire(blocking=False):raise RuntimeError('Já existe uma geração musical em andamento.')
    try:
        if cancelled():raise InterruptedError('Geração musical cancelada antes de iniciar.')
        with requests.Session() as session:
            session.trust_env=False
            if provider=='local':
                url,headers=engine(session,progress,cancelled)
                result=_json(session.post(url+'/release_task',headers=headers,json={'prompt':prompt,'lyrics':lyrics or '[Instrumental]','audio_duration':duration,'batch_size':1,'audio_format':'mp3','thinking':False},timeout=30,allow_redirects=False))
                identity=result['data']['task_id']
                progress('Gerando música localmente…')
                for _ in range(900):
                    if cancelled():raise InterruptedError('A espera foi cancelada. O motor ACE-Step pode continuar sua tarefa em segundo plano.')
                    response=_json(session.post(url+'/query_result',headers=headers,json={'task_id_list':[identity]},timeout=10,allow_redirects=False))
                    rows=response.get('data',[])
                    if rows and rows[0]['status']==2:raise RuntimeError('ACE-Step não conseguiu gerar a música. Consulte o log do motor.')
                    if rows and rows[0]['status']==1:
                        result=rows[0]['result'];entries=json.loads(result) if isinstance(result,str) else result
                        resource=entries[0]['file']
                        parsed=urlsplit(resource)
                        if parsed.scheme or parsed.netloc or parsed.path!='/v1/audio':raise RuntimeError('O motor retornou um endereço de áudio inválido.')
                        response=session.get(url+resource,headers=headers,timeout=60,allow_redirects=False)
                        try:
                            if response.status_code!=200:raise RuntimeError('Não foi possível obter o áudio do motor.')
                            raw=response.content
                        finally:response.close()
                        break
                    time.sleep(2)
                else:raise RuntimeError('O motor musical excedeu 30 minutos.')
                extension='mp3'
            else:
                from src.config import STT_GEMINI_API_KEY
                key=os.getenv('GEMINI_API_KEY') or os.getenv('AGE_GEMINI_API_KEY') or STT_GEMINI_API_KEY
                if not key:raise RuntimeError('Configure a chave Gemini da PIA. A autorização Gmail/Drive não concede acesso à API Lyria.')
                progress('Gerando música com Lyria pela API Gemini…')
                data=_json(session.post('https://generativelanguage.googleapis.com/v1beta/interactions',headers={'x-goog-api-key':key},json={'model':settings().get('MUSIC_GEMINI_MODEL') or 'lyria-3.5','input':f'{prompt}\nTarget duration: {duration} seconds.\n'+('Lyrics:\n'+lyrics if lyrics else 'Instrumental only. No vocals.')},timeout=600))
                audios=[content for step in data.get('steps',[]) if step.get('type')=='model_output' for content in step.get('content',[]) if content.get('type')=='audio']
                if not audios:raise RuntimeError('Gemini não retornou áudio. Verifique a disponibilidade do modelo e as cotas de sua API.')
                raw=base64.b64decode(audios[0]['data'],validate=True);extension='wav' if audios[0].get('mime_type')=='audio/wav' else 'mp3'
            if cancelled():raise InterruptedError('Geração cancelada antes de salvar o resultado.')
            if not raw or len(raw)>100*1024**2:raise RuntimeError('Áudio musical vazio ou maior que 100 MiB.')
            OUTPUT.mkdir(parents=True,exist_ok=True)
            name=uuid.uuid4().hex+'.'+extension
            (OUTPUT/name).write_bytes(raw)
            result={'file':name,'provider':provider,'prompt':prompt,'lyrics':lyrics,'requested_duration':duration,'audio_url':'/api/pia/music/files/'+name}
            save_json(OUTPUT/(name+'.json'),result)
            return result
    finally:_generation_lock.release()
