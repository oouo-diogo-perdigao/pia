import os
import threading
import time
import warnings

import litellm

from ..config import logging, logger_llm, LLM_REMOTE_COOLDOWN_SECONDS
from ..llm_routing import select_models

os.environ["LITELLM_LOG"] = "ERROR"
litellm.suppress_debug_info = True
warnings.filterwarnings("ignore", category=UserWarning, module="litellm")


class GenericAgent:
    """Shared model policy and fallback for internal and HTTP chat clients."""

    def __init__(self):
        self.model_disabled_until = {}
        self._lock = threading.Lock()

    def _candidates(self, model):
        candidates = select_models(model)
        if not candidates:
            raise ValueError("O seletor LLM não selecionou nenhum modelo configurado.")
        for candidate in candidates:
            with self._lock:
                disabled = self.model_disabled_until.get(candidate.key, 0)
            params = candidate.params()
            if params is not None and time.monotonic() >= disabled:
                yield candidate, params

    def _failed(self, candidate, exc):
        # One exhausted Gemini model must not disable all other Gemini models.
        if candidate.provider != "local":
            with self._lock:
                self.model_disabled_until[candidate.key] = (
                    time.monotonic() + LLM_REMOTE_COOLDOWN_SECONDS
                )
        logging.warning(
            "[LLM] Modelo %s falhou (%s); tentando o próximo.",
            candidate.model,
            type(exc).__name__,
        )

    @staticmethod
    def _messages(prompt):
        return [
            {
                "role": "system",
                "content": "Você é uma assistente inteligente, prestativa e sucinta. Responda de forma direta em português.",
            },
            {"role": "user", "content": prompt},
        ]

    def complete(self, messages, model=None, **options):
        for candidate, params in self._candidates(model):
            try:
                response = litellm.completion(messages=messages, **options, **params)
                if not response.choices:
                    raise RuntimeError("Resposta LLM sem choices.")
                logger_llm.info(
                    "[LLM] provider=%s model=%s", candidate.provider, candidate.model
                )
                return response
            except Exception as exc:
                self._failed(candidate, exc)
        raise RuntimeError(
            "Todos os modelos LLM selecionados falharam, estão em cooldown ou não possuem credenciais."
        )

    def complete_stream(self, messages, model=None, **options):
        for candidate, params in self._candidates(model):
            emitted = False
            response = None
            try:
                response = litellm.completion(
                    messages=messages, stream=True, **options, **params
                )
                # Buffer metadata so a pre-content failure can safely fall back.
                pending = []
                for chunk in response:
                    pending.append(chunk)
                    meaningful = any(
                        getattr(choice.delta, "content", None)
                        or getattr(choice.delta, "tool_calls", None)
                        or getattr(choice.delta, "function_call", None)
                        or getattr(choice.delta, "refusal", None)
                        for choice in chunk.choices
                    )
                    if meaningful:
                        emitted = True
                    if emitted:
                        yield from pending
                        pending.clear()
                if not emitted:
                    raise RuntimeError("Stream LLM vazio.")
                yield from pending
                return
            except Exception as exc:
                self._failed(candidate, exc)
                if emitted:
                    # Never restart a response after content/tool calls were sent.
                    raise
            finally:
                if response is not None and hasattr(response, "close"):
                    try:
                        response.close()
                    except Exception:
                        logging.debug("[LLM] Falha ao fechar stream.")
        raise RuntimeError(
            "Todos os modelos LLM selecionados falharam, estão em cooldown ou não possuem credenciais."
        )

    def run(self, prompt, model=None):
        return (
            self.complete(self._messages(prompt), model).choices[0].message.content
            or ""
        )

    def run_stream(self, prompt, model=None):
        for chunk in self.complete_stream(self._messages(prompt), model):
            for choice in chunk.choices:
                if choice.delta.content:
                    yield choice.delta.content
