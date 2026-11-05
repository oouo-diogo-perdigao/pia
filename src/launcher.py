from src.user_paths import user_path
"""Shared desktop launcher used by start.sh, the installer and login."""
import argparse
import os
import subprocess
import sys
import time

from .config_paths import BASE_DIR
from .profile_migration import initialize_profile
from .instance import InstanceLock


def run_desktop():
    if legacy_running():return
    lock = InstanceLock(user_path('pia.lock'))
    if not lock.acquire():
        print('A PIA já está em execução. Use o ícone na bandeja.')
        return
    listener = None
    try:
        if sys.platform != 'win32' and os.getenv('WAYLAND_DISPLAY') and os.getenv('DISPLAY'):
            os.environ.setdefault('QT_QPA_PLATFORM', 'xcb')
        initialize_profile()
        from .cache_paths import migrate
        migrate()
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        listener = subprocess.Popen([sys.executable, '-m', 'src.hotkeys'], cwd=BASE_DIR, creationflags=flags)
        from .server import main as run_server
        run_server()
    finally:
        if listener is not None and listener.poll() is None:
            listener.terminate()
            try:
                listener.wait(timeout=3)
            except subprocess.TimeoutExpired:
                listener.kill()
        lock.close()


def start_background():
    if legacy_running():return
    lock = InstanceLock(user_path('pia.lock'))
    if not lock.acquire():
        print('A PIA já está em execução. Use o ícone na bandeja.')
        return
    lock.close()
    logs = BASE_DIR / 'logs'
    logs.mkdir(exist_ok=True)
    flags = (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if sys.platform == 'win32' else 0
    with (logs / 'launcher.log').open('ab') as output:
        process = subprocess.Popen([sys.executable, '-u', '-m', 'src.launcher', '--foreground'],
            cwd=BASE_DIR, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
            creationflags=flags, start_new_session=(sys.platform != 'win32'))
    time.sleep(0.5)
    if process.poll() not in (None, 0):
        raise RuntimeError('Não foi possível iniciar a PIA. Consulte logs/launcher.log.')
    print('PIA iniciada em segundo plano. Logs: logs/launcher.log')


def legacy_running(quiet=False):
    legacy=BASE_DIR/'data/pia.lock'
    if not legacy.exists():return False
    lock=InstanceLock(legacy)
    if not lock.acquire():
        if not quiet:print('A versão anterior da PIA ainda está em execução. Encerre-a pela bandeja antes de iniciar a migração.')
        return True
    lock.close()
    return False


def main():
    parser = argparse.ArgumentParser(description='Iniciar PIA')
    parser.add_argument('--foreground', action='store_true', help='Executar no terminal para diagnóstico')
    parser.add_argument('--restart-pid',type=int)
    parser.add_argument('--dry-run', action='store_true', help='Exibir o comando sem iniciar')
    options = parser.parse_args()
    if options.restart_pid:
        for _ in range(600):
            lock=InstanceLock(user_path('pia.lock'))
            if lock.acquire():
                lock.close()
                if not legacy_running(quiet=True):break
            time.sleep(.25)
        else:raise RuntimeError('A instância anterior não encerrou; reinício cancelado.')
        start_background()
        return
    if options.dry_run:
        print(f'Python: {sys.executable}\nProjeto: {BASE_DIR}\nComando: python -m src.launcher --foreground')
        return
    if options.foreground:
        run_desktop()
    else:
        start_background()


if __name__ == '__main__':
    main()
