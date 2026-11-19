"""Bounded CLI bridges using each installed CLI's own saved login."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from src.config_paths import BASE_DIR
from src.settings_store import values as section_values, document, save_document

ROOT = Path(__file__).resolve().parent


def executable(provider):
    if provider not in ('codex', 'agy'):
        raise ValueError('Escolha codex ou agy (Google Antigravity).')
    configured = section_values('Connectors/agents').get('AGENTS_' + provider.upper() + '_EXECUTABLE')
    found = configured or shutil.which(provider) or shutil.which(provider + '.cmd')
    if not found and provider == 'agy':
        locations = [Path.home() / '.local/bin' / ('agy.exe' if sys.platform == 'win32' else 'agy')]
        if sys.platform == 'win32':
            locations.insert(0, Path(os.getenv('LOCALAPPDATA') or Path.home() / 'AppData/Local') / 'agy/bin/agy.exe')
        found = next((str(local) for local in locations if local.is_file()), None)
    return found


def _sanitized_env():
    return {
        key: value
        for key, value in os.environ.items()
        if not any(part in key.upper() for part in ('API_KEY', 'SECRET', 'TOKEN', 'CREDENTIAL'))
        and not key.startswith(('PIA_', 'AGE_', 'LLM_', 'STT_'))
    }


def _resolve_command(provider, binary, args):
    command = [binary, *args]
    # Windows npm shims are batch files. Resolve their JS entrypoint instead
    # of invoking a shell with untrusted text.
    if str(binary).lower().endswith(('.cmd', '.bat')) and provider == 'agy':
        native = Path(binary).with_suffix('.exe')
        if not native.is_file():
            raise RuntimeError('Configure AGENTS_AGY_EXECUTABLE com o agy.exe nativo do instalador oficial do Google.')
        command[0] = str(native)
    elif str(binary).lower().endswith('.cmd'):
        package = '@openai/codex/bin/codex.js'
        entry = Path(binary).parent / 'node_modules' / package
        node = shutil.which('node')
        if not node or not entry.is_file():
            raise RuntimeError('Configure o executável nativo ou instale o CLI pelo npm com Node.js disponível.')
        command = [node, str(entry), *args]
    return command


def status():
    result = {}
    for name in ('codex', 'agy'):
        binary = executable(name)
        result[name] = {
            'available': bool(binary),
            'executable': binary,
            'login': 'codex login' if name == 'codex' else 'agy',
        }
    return result


def login_status(provider):
    """Non-paid check of CLI installation and login state."""
    if provider not in ('codex', 'agy'):
        raise ValueError('Escolha codex ou agy (Google Antigravity).')
    binary = executable(provider)
    if not binary:
        return {'provider': provider, 'status': 'not_installed', 'available': False, 'executable': None, 'detail': ''}
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
    env = _sanitized_env()
    try:
        if provider == 'codex':
            command = _resolve_command('codex', binary, ['login', 'status'])
            res = subprocess.run(command, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10, **flags)
            combined = f'{res.stdout or ""}\n{res.stderr or ""}'.lower()
            if res.returncode == 0 and 'not logged in' not in combined and 'logged out' not in combined:
                return {'provider': 'codex', 'status': 'connected', 'available': True, 'executable': binary, 'detail': ''}
            if 'not logged in' in combined or 'login' in combined or res.returncode != 0:
                return {'provider': 'codex', 'status': 'login_required', 'available': True, 'executable': binary, 'detail': ''}
            return {'provider': 'codex', 'status': 'login_required', 'available': True, 'executable': binary, 'detail': ''}
        # AGY: verify native executable responds to --version without paid prompt
        command = _resolve_command('agy', binary, ['--version'])
        res = subprocess.run(command, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10, **flags)
        combined = f'{res.stdout or ""}\n{res.stderr or ""}'.lower()
        if 'login' in combined or 'auth' in combined and 'required' in combined:
            return {'provider': 'agy', 'status': 'login_required', 'available': True, 'executable': binary, 'detail': ''}
        if res.returncode == 0:
            return {'provider': 'agy', 'status': 'connected', 'available': True, 'executable': binary, 'detail': ''}
        return {'provider': 'agy', 'status': 'login_required', 'available': True, 'executable': binary, 'detail': ''}
    except RuntimeError as exc:
        return {'provider': provider, 'status': 'error', 'available': True, 'executable': binary, 'detail': str(exc)}
    except Exception:
        return {'provider': provider, 'status': 'login_required', 'available': True, 'executable': binary, 'detail': ''}


def start_login(provider):
    """Attempt to launch the official CLI login flow without touching external tokens."""
    if provider not in ('codex', 'agy'):
        raise ValueError('Escolha codex ou agy (Google Antigravity).')
    cmd_label = 'codex login' if provider == 'codex' else 'agy'
    binary = executable(provider)
    if not binary:
        return {'started': False, 'command': cmd_label, 'status': 'not_installed'}
    env = _sanitized_env()
    try:
        args = ['login'] if provider == 'codex' else []
        command = _resolve_command(provider, binary, args)
        subprocess.Popen(
            command,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=(sys.platform != 'win32'),
        )
        return {'started': True, 'command': cmd_label, 'status': login_status(provider)['status']}
    except Exception:
        return {'started': False, 'command': cmd_label, 'status': login_status(provider)['status']}


def _extract_agy_result(stdout):
    try:
        events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    except (ValueError, TypeError):
        raise RuntimeError('AGY retornou um fluxo JSON inválido. Atualize o Antigravity CLI.') from None
    results = [event.get('result') for event in events if isinstance(event, dict) and event.get('event') == 'result']
    if len(results) != 1 or not isinstance(results[0], dict):
        raise RuntimeError('AGY não retornou o resultado final da consulta.')
    result = results[0]
    if result.get('status') != 'SUCCESS':
        raise RuntimeError('AGY não concluiu a consulta. Abra agy para verificar login, permissões e limites da conta.')
    answer = result.get('response')
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError('AGY não retornou texto.')
    usage = result.get('usage') if isinstance(result.get('usage'), dict) else None
    return answer, usage


def agy_response(stdout):
    answer, _ = _extract_agy_result(stdout)
    return answer


def _terminate_process(proc):
    try:
        if sys.platform == 'win32':
            subprocess.run(
                ['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def ask(provider, prompt, model=None, cancel_event=None):
    if provider not in ('codex', 'agy'):
        raise ValueError('Escolha codex ou agy (Google Antigravity).')
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 32000:
        raise ValueError('Mensagem inválida (limite: 32 mil caracteres).')
    binary = executable(provider)
    if not binary:
        raise RuntimeError(f'Instale o CLI {provider} e entre com sua conta antes de conectar à PIA.')
    workspace = BASE_DIR / 'cache/Connectors/agents/workspace'
    workspace.mkdir(parents=True, exist_ok=True)
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
    with tempfile.TemporaryDirectory(dir=workspace) as temporary:
        if provider == 'codex':
            output = Path(temporary) / 'response.txt'
            args = ['exec', '--sandbox', 'read-only', '--skip-git-repo-check']
            if model and model not in ('codex', 'default'):
                args.extend(['--model', str(model)])
            args.extend(['-o', str(output), '-'])
        else:
            args = ['--mode', 'plan', '--input-format', 'stream-json', '--output-format', 'stream-json', '--print-timeout', '5m']
            if model and model not in ('agy', 'default'):
                args.extend(['--model', str(model)])
        command = _resolve_command(provider, binary, args)
        environment = _sanitized_env()
        request = prompt if provider == 'codex' else json.dumps({'event': 'user', 'message': {'content': prompt}}, ensure_ascii=False) + '\n'

        if cancel_event is None:
            try:
                result = subprocess.run(
                    command,
                    input=request,
                    env=environment,
                    cwd=temporary,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    timeout=300,
                    **flags,
                )
            except subprocess.TimeoutExpired:
                raise RuntimeError('O agente externo excedeu cinco minutos; a chamada foi encerrada.') from None
            returncode = result.returncode
            stdout = getattr(result, 'stdout', '') or ''
        else:
            if cancel_event.is_set():
                raise InterruptedError('Resposta interrompida.')
            proc = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
                cwd=temporary,
                text=True,
                encoding='utf-8',
                errors='replace',
                **flags,
            )
            try:
                if proc.stdin:
                    proc.stdin.write(request)
                    proc.stdin.close()
                deadline = time.monotonic() + 300
                while proc.poll() is None:
                    if cancel_event.is_set():
                        _terminate_process(proc)
                        raise InterruptedError('Resposta interrompida.')
                    if time.monotonic() >= deadline:
                        _terminate_process(proc)
                        raise RuntimeError('O agente externo excedeu cinco minutos; a chamada foi encerrada.')
                    time.sleep(0.05)
                stdout = proc.stdout.read() if proc.stdout else ''
                if proc.stderr:
                    proc.stderr.read()
                returncode = proc.returncode
            except InterruptedError:
                raise
            except Exception:
                if proc.poll() is None:
                    _terminate_process(proc)
                raise

        if returncode:
            raise RuntimeError(f'{provider} não concluiu. Abra o CLI para verificar login, aprovação e limites da sua conta (código {returncode}).')
        usage = None
        if provider == 'codex':
            answer = output.read_text(encoding='utf-8')
        else:
            answer, usage = _extract_agy_result(stdout)
        if not answer:
            raise RuntimeError('O agente externo não retornou texto.')
        return {'provider': provider, 'text': answer[:200000], 'usage': usage}
