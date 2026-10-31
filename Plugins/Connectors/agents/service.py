"""Bounded CLI bridges using each installed CLI's own saved login."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from src.config_paths import BASE_DIR
from src.env_types import dotenv_values

ROOT=Path(__file__).resolve().parent

def executable(provider):
    if provider not in ('codex','agy'):raise ValueError('Escolha codex ou agy (Google Antigravity).')
    configured=dotenv_values(ROOT/'.env').get('AGENTS_'+provider.upper()+'_EXECUTABLE')
    found=configured or shutil.which(provider) or shutil.which(provider+'.cmd')
    if not found and provider=='agy':
        locations=[Path.home()/'.local/bin'/('agy.exe' if sys.platform=='win32' else 'agy')]
        if sys.platform=='win32':locations.insert(0,Path(os.getenv('LOCALAPPDATA') or Path.home()/'AppData/Local')/'agy/bin/agy.exe')
        found=next((str(local) for local in locations if local.is_file()),None)
    return found

def status():
    result={}
    for name in ('codex','agy'):
        binary=executable(name)
        result[name]={'available':bool(binary),'executable':binary,'login':'codex login' if name=='codex' else 'agy'}
    return result


def agy_response(stdout):
    try:
        events=[json.loads(line) for line in stdout.splitlines() if line.strip()]
    except (ValueError,TypeError):raise RuntimeError('AGY retornou um fluxo JSON inválido. Atualize o Antigravity CLI.') from None
    results=[event.get('result') for event in events if isinstance(event,dict) and event.get('event')=='result']
    if len(results)!=1 or not isinstance(results[0],dict):
        raise RuntimeError('AGY não retornou o resultado final da consulta.')
    result=results[0]
    if result.get('status')!='SUCCESS':
        raise RuntimeError('AGY não concluiu a consulta. Abra agy para verificar login, permissões e limites da conta.')
    answer=result.get('response')
    if not isinstance(answer,str) or not answer.strip():raise RuntimeError('AGY não retornou texto.')
    return answer

def ask(provider,prompt):
    if provider not in ('codex','agy'):raise ValueError('Escolha codex ou agy (Google Antigravity).')
    if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>32000:raise ValueError('Mensagem inválida (limite: 32 mil caracteres).')
    binary=executable(provider)
    if not binary:raise RuntimeError(f'Instale o CLI {provider} e entre com sua conta antes de conectar à PIA.')
    workspace=BASE_DIR/'cache/Connectors/agents/workspace';workspace.mkdir(parents=True,exist_ok=True)
    flags={'creationflags':subprocess.CREATE_NO_WINDOW} if sys.platform=='win32' else {}
    with tempfile.TemporaryDirectory(dir=workspace) as temporary:
        if provider=='codex':
            output=Path(temporary)/'response.txt'
            command=[binary,'exec','--sandbox','read-only','--skip-git-repo-check','-o',str(output),'-']
        else:command=[binary,'--mode','plan','--input-format','stream-json','--output-format','stream-json','--print-timeout','5m']
        # Windows npm shims are batch files. Resolve their JS entrypoint instead
        # of invoking a shell with untrusted text.
        if str(binary).lower().endswith(('.cmd','.bat')) and provider=='agy':
            native=Path(binary).with_suffix('.exe')
            if not native.is_file():raise RuntimeError('Configure AGENTS_AGY_EXECUTABLE com o agy.exe nativo do instalador oficial do Google.')
            command[0]=str(native)
        elif str(binary).lower().endswith('.cmd'):
            package='@openai/codex/bin/codex.js'
            entry=Path(binary).parent/'node_modules'/package
            node=shutil.which('node')
            if not node or not entry.is_file():raise RuntimeError('Configure o executável nativo ou instale o CLI pelo npm com Node.js disponível.')
            command=[node,str(entry),*command[1:]]
        environment={key:value for key,value in os.environ.items() if not any(part in key.upper() for part in ('API_KEY','SECRET','TOKEN','CREDENTIAL')) and not key.startswith(('PIA_','AGE_','LLM_','STT_'))}
        request=prompt if provider=='codex' else json.dumps({'event':'user','message':{'content':prompt}},ensure_ascii=False)+'\n'
        try:result=subprocess.run(command,input=request,env=environment,cwd=temporary,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=300,**flags)
        except subprocess.TimeoutExpired:raise RuntimeError('O agente externo excedeu cinco minutos; a chamada foi encerrada.') from None
        if result.returncode:raise RuntimeError(f'{provider} não concluiu. Abra o CLI para verificar login, aprovação e limites da sua conta (código {result.returncode}).')
        if provider=='codex':answer=output.read_text(encoding='utf-8')
        else:answer=agy_response(result.stdout)
        if not answer:raise RuntimeError('O agente externo não retornou texto.')
        return {'provider':provider,'text':answer[:200000]}
