"""Processamento de voz do app, usando o mesmo Python instalado pela PIA."""
from datetime import datetime
import atexit
import json
import logging
import os
from pathlib import Path
import re
import sys
import signal
import subprocess
import threading
import unicodedata
from urllib.parse import urlsplit

STAGES = ('Obter ZIP', 'Extrair e identificar', 'Mixar áudio', 'Editar e compilar',
          'Transcrever', 'Gerar legendas', 'Gerar resumo', 'Preparar arquivos',
          'Publicar', 'Atualizar RSS e página', 'Finalizar e limpar')
PROGRESS = re.compile(r'^(.*?):\s*(\d{1,3})%\|[^|]*\|')


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower()) if not unicodedata.combining(c)).strip(' .!?')


class PodcastJob:
    def __init__(self, project):
        self.project = Path(project).resolve()
        self.lock = threading.RLock()
        self.process = None
        self.thread = None
        self.state = 'idle'
        self.session = ''
        self.stage = 'Aguardando início'
        self.percent = None
        self.links = {}
        self.log_path = None
        self.stop_requested = False
        self.returncode = None
        atexit.register(self.stop)

    def snapshot(self):
        with self.lock:
            return dict(state=self.state, session=self.session, stage=self.stage,
                        percent=self.percent, links=dict(self.links), log_path=self.log_path,
                        returncode=self.returncode)

    def child_env(self):
        env = os.environ.copy()
        # A PIA carrega seu próprio .env no processo pai. O podcast precisa ler o dele.
        env_file = self.project / '.env'
        if env_file.exists():
            for key in re.findall(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=', env_file.read_text(encoding='utf-8'), re.MULTILINE):
                from src.env_types import split_key
                env.pop(key, None)
                env.pop(split_key(key)[0], None)
        for key in ('VIRTUAL_ENV', 'UV_PROJECT_ENVIRONMENT', 'PYTHONHOME'):
            env.pop(key, None)
        from src.app_access import issue
        from src.config_paths import BASE_DIR
        self.app_context=issue('podcast_automation')
        env['PIA_APP_CONTEXT']=self.app_context
        env.update(PODCAST_ROOT=str(self.project), CRAIG_GUI_EVENTS='1',
                   PYTHONIOENCODING='utf-8', PYTHONUTF8='1',
                   PYTHONPATH=str(BASE_DIR)+os.pathsep+str(self.project/'src') + os.pathsep + str(self.project))
        return env

    def start(self):
        with self.lock:
            if self.state in ('running', 'stopping'):
                raise RuntimeError('O processamento já está em execução.')
            if not (self.project/'src/podcast_automation/main.py').is_file():
                raise RuntimeError('Arquivos do aplicativo não encontrados na PIA.')
            self.project.joinpath('data/logs').mkdir(parents=True, exist_ok=True)
            self.log_path = self.project/'data/logs'/('pia-podcast-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.log')
            self.session, self.percent, self.links = '', None, {}
            self.stage, self.stop_requested, self.returncode = 'Preparando processamento', False, None
            self.process = subprocess.Popen(
                [sys.executable, '-u', '-m', 'podcast_automation.main', '--once'],
                cwd=self.project, env=self.child_env(), stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == 'nt' else 0,
                start_new_session=(os.name != 'nt'),
            )
            self.state = 'running'
            self.thread = threading.Thread(target=self._read_output, daemon=True, name='podcast-output')
            self.thread.start()

    def consume(self, line):
        clean = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', line).strip()
        with self.lock:
            if clean.startswith('@@CRAIG '):
                try:
                    event = json.loads(clean[8:])
                    kind = event.get('kind')
                    if kind == 'session':
                        self.session = event.get('name', '')
                        self.percent = None
                    elif kind == 'stage' and isinstance(event.get('index'), int) and 0 <= event['index'] < len(STAGES):
                        self.stage, self.percent = STAGES[event['index']], None
                    elif kind == 'complete':
                        self.stage, self.percent = 'Sessão concluída', 100
                    elif kind == 'skipped':
                        self.stage = event.get('reason', 'Sessão dispensada')
                    elif kind == 'failed':
                        self.stage = 'Falha no processamento'
                    logging.info('[PODCAST] %s: %s', self.session, self.stage)
                except (ValueError, AttributeError, TypeError):
                    pass
            else:
                progress = PROGRESS.match(clean)
                if progress and int(progress[2]) <= 100:
                    self.stage, self.percent = progress[1], int(progress[2])
                for url in re.findall(r'https?://[^\s<>]+', clean):
                    url = url.rstrip('.,;)')
                    try:
                        path = urlsplit(url).path
                    except ValueError:
                        continue
                    if path.endswith('rss.xml'):
                        self.links['rss'] = url
                    elif path.endswith('transcripts.html'):
                        self.links['transcricoes'] = url

    def _read_output(self):
        process = self.process
        code = 1
        try:
            with self.log_path.open('w', encoding='utf-8') as log:
                for line in process.stdout:
                    log.write(line)
                    log.flush()
                    self.consume(line)
            code = process.wait()
        except Exception:
            logging.exception('[PODCAST] Falha ao acompanhar subprocesso')
            self.stop()
        finally:
            process.stdout.close()
            from src.app_access import revoke
            revoke(self.app_context)
            with self.lock:
                self.returncode = code
                self.state = 'stopped' if self.stop_requested else 'completed' if code == 0 else 'failed'
                if self.state == 'failed':
                    logging.error('[PODCAST] Processo encerrou com código %s. Log: %s', code, self.log_path)

    def stop(self):
        with self.lock:
            process = self.process
            if process is None or process.poll() is not None:
                return
            self.stop_requested = True
            self.state = 'stopping'
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, timeout=15)
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
