"""Bounded, caller-scoped progress for synchronous OpenAI-compatible uploads."""
import re
import threading
import time

_jobs = {}
_lock = threading.RLock()

def create(identity, owner):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{16,80}', identity):
        raise ValueError('X-PIA-Transcription-ID inválido (16–80 caracteres).')
    with _lock:
        now=time.monotonic()
        for key in list(_jobs):
            if now-_jobs[key]['updated']>86400:_jobs.pop(key)
        if identity in _jobs:raise ValueError('Identificador de transcrição já utilizado.')
        if len(_jobs)>=1000:raise ValueError('Limite de acompanhamentos de transcrição atingido.')
        _jobs[identity]={'id':identity,'owner':owner,'state':'queued','percent':0,'updated':now}

def update(identity, **event):
    if not identity:return
    with _lock:
        if identity in _jobs:_jobs[identity].update(event,updated=time.monotonic())

def get(identity, owner):
    with _lock:
        job=_jobs.get(identity)
        if not job or job['owner']!=owner:return None
        return {k:v for k,v in job.items() if k not in ('owner','updated')}
