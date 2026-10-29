"""Per-plugin operational logs. Never persist request payloads or credentials."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import threading
from src.config_paths import BASE_DIR
_lock=threading.RLock()

def write(identity, operation, outcome='ok'):
    if not re.fullmatch(r'(Apps|Bot|Connectors|Skills|Browser)/[a-zA-Z0-9_-]+',identity):return
    path=BASE_DIR/'logs/plugins'/Path(identity+'.log')
    logger=logging.getLogger('pia.plugin.'+identity)
    with _lock:
        if not logger.handlers:
            path.parent.mkdir(parents=True,exist_ok=True)
            handler=RotatingFileHandler(path,maxBytes=1_000_000,backupCount=2,encoding='utf-8',delay=True)
            handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
            logger.addHandler(handler);logger.setLevel(logging.INFO);logger.propagate=False
    logger.info('%s · %s', str(operation).replace('\r',' ').replace('\n',' ')[:2000], outcome)
