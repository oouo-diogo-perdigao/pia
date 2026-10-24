"""Sessões de skills: APIs injetadas, cancelamento e ciclo de vida sem dependências desktop."""
from concurrent.futures import Future
import inspect
import logging
import re
import threading
import unicodedata


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower()) if not unicodedata.combining(c))


def is_stop_phrase(text):
    words = re.findall(r"\w+", normalize(text))
    return bool(words and len(words) <= 4 and (
        words[-1] == 'finalizar' or words[-1].startswith('encerra')
        or ' '.join(words) in ('parar pia', 'pare pia', 'parar skill', 'cancelar skill',
                              'encerrar modo ditado', 'desativar modo ditado')))


class SkillSession:
    def __init__(self, runtime, name):
        self.runtime, self.name = runtime, name
        self.cancelled = threading.Event()
        self.lock = threading.RLock()
        self.listener = None
        self.pending = set()
        self.finished = False
        self.running_callback = False
        self.effects = {}

    def close(self):
        self.runtime.close(self)

    def stt(self, listener):
        if not callable(listener):
            raise TypeError('piaSTT exige uma função que recebe texto.')
        with self.lock:
            if self.cancelled.is_set():
                return lambda: None
            self.listener = listener
        def unsubscribe():
            with self.lock:
                if self.listener is listener:
                    self.listener = None
            self.maybe_close()
        return unsubscribe

    def tts(self, text, **options):
        with self.lock:
            if self.cancelled.is_set():
                future = Future()
                future.cancel()
                return future
            future = self.runtime.services.speak(text, self.cancelled, **options)
            self.pending.add(future)
        def done(result):
            with self.lock:
                self.pending.discard(result)
            if not result.cancelled() and result.exception() is not None:
                logging.error('[SKILL %s] Falha no TTS: %s', self.name, result.exception())
                self.close()
            else:
                self.maybe_close()
        future.add_done_callback(done)
        return future

    def interface(self, action, enabled=True):
        with self.lock:
            if self.cancelled.is_set():
                return
            self.runtime.services.interface(action, enabled)
            if action != 'blink':
                self.effects[action] = bool(enabled)

    def view(self, image):
        if not self.cancelled.is_set():
            return self.runtime.services.view(image)

    def insert(self, text):
        if not self.cancelled.is_set():
            return self.runtime.services.insert(text)

    def key(self, *keys):
        if not self.cancelled.is_set():
            return self.runtime.services.key(*keys)

    def maybe_close(self):
        with self.lock:
            ready = self.finished and not self.listener and not self.pending and not self.running_callback
        if ready:
            self.close()

    def call(self, execute):
        apis = dict(piaClose=self.close, piaSTT=self.stt, piaTTS=self.tts,
                    piaInterface=self.interface, piaView=self.view, piaInsert=self.insert,
                    piaKey=self.key, piaCancelled=self.cancelled)
        try:
            signature = inspect.signature(execute)
            kwargs = apis if any(p.kind == p.VAR_KEYWORD for p in signature.parameters.values()) else {
                name: value for name, value in apis.items() if name in signature.parameters}
            execute(**kwargs)
        except Exception:
            logging.exception('[SKILL %s] Falha em execute', self.name)
            self.close()
        finally:
            with self.lock:
                self.finished = True
            self.maybe_close()


class SkillRuntime:
    def __init__(self, services):
        self.services = services
        self.lock = threading.RLock()
        self.session = None

    @property
    def active(self):
        with self.lock:
            return self.session is not None

    def activate(self, name, execute):
        self.cancel(close_interface=False)
        session = SkillSession(self, name)
        with self.lock:
            self.session = session
        threading.Thread(target=session.call, args=(execute,), daemon=True, name='skill-' + name).start()
        return session

    def close(self, session, close_interface=True):
        with self.lock:
            if session is not self.session:
                return
            self.session = None
            session.cancelled.set()
            with session.lock:
                session.listener = None
                effects = dict(session.effects)
            for action, enabled in effects.items():
                if enabled:
                    try:
                        self.services.interface(action, False)
                    except Exception:
                        logging.exception('Falha ao restaurar interface da skill')
            if close_interface:
                self.services.close()

    def cancel(self, close_interface=True):
        with self.lock:
            session = self.session
        if session:
            self.close(session, close_interface)

    def dispatch(self, text):
        # Encerramento tem prioridade: nunca é entregue ao listener de ditado.
        if is_stop_phrase(text):
            self.cancel()
            return True
        with self.lock:
            session = self.session
        if session is None:
            return False
        with session.lock:
            listener = session.listener
            # Não dita/transcreve o áudio da própria skill enquanto ela está falando.
            if session.pending:
                return True
            if session.cancelled.is_set():
                return True
            session.running_callback = True
        try:
            if listener:
                listener(text)
        except Exception:
            logging.exception('[SKILL %s] Falha no listener', session.name)
            session.close()
        finally:
            with session.lock:
                session.running_callback = False
            session.maybe_close()
        return True


_runtime = None

def get_runtime():
    global _runtime
    if _runtime is None:
        from .skill_services import PiaServices
        _runtime = SkillRuntime(PiaServices())
    return _runtime
