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
    if provider not in ('codex','gemini'):raise ValueError('Escolha codex ou gemini.')
    configured=dotenv_values(ROOT/'.env').get('AGENTS_'+provider.upper()+'_EXECUTABLE')
    return configured or shutil.which(provider) or shutil.which(provider+'.cmd')

def status():
    return {name:{'available':bool(executable(name)),'login':name+' login' if name=='codex' else 'gemini'} for name in ('codex','gemini')}

def ask(provider,prompt):
    if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>32000:raise ValueError('Mensagem inválida (limite: 32 mil caracteres).')
    binary=executable(provider)
    if not binary:raise RuntimeError(f'Instale o CLI {provider} e entre com sua conta antes de conectar à PIA.')
    workspace=BASE_DIR/'cache/Connectors/agents/workspace';workspace.mkdir(parents=True,exist_ok=True)
    flags={'creationflags':subprocess.CREATE_NO_WINDOW} if sys.platform=='win32' else {}
    with tempfile.TemporaryDirectory(dir=workspace) as temporary:
        if provider=='codex':
            output=Path(temporary)/'response.txt'
            command=[binary,'exec','--sandbox','read-only','--skip-git-repo-check','-o',str(output),'-']
        else:command=[binary,'--approval-mode','plan','--output-format','json','-p','Responda à mensagem fornecida pela entrada padrão.']
        # Windows npm shims are batch files. Resolve their JS entrypoint instead
        # of invoking a shell with untrusted text.
        if str(binary).lower().endswith('.cmd'):
            package='@openai/codex/bin/codex.js' if provider=='codex' else '@google/gemini-cli/dist/index.js'
            entry=Path(binary).parent/'node_modules'/package
            node=shutil.which('node')
            if not node or not entry.is_file():raise RuntimeError('Configure o executável nativo ou instale o CLI pelo npm com Node.js disponível.')
            command=[node,str(entry),*command[1:]]
        environment={key:value for key,value in os.environ.items() if not any(part in key.upper() for part in ('API_KEY','SECRET','TOKEN','CREDENTIAL')) and not key.startswith(('PIA_','AGE_','LLM_','STT_'))}
        try:result=subprocess.run(command,input=prompt,env=environment,cwd=temporary,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=300,**flags)
        except subprocess.TimeoutExpired:raise RuntimeError('O agente externo excedeu cinco minutos; a chamada foi encerrada.') from None
        if result.returncode:raise RuntimeError(f'{provider} não concluiu. Abra o CLI para verificar login, aprovação e limites da sua conta (código {result.returncode}).')
        if provider=='codex':answer=output.read_text(encoding='utf-8')
        else:answer=json.loads(result.stdout).get('response','')
        if not answer:raise RuntimeError('O agente externo não retornou texto.')
        return {'provider':provider,'text':answer[:200000]}
