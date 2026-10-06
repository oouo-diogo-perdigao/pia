import os
import time
import warnings

import litellm

from ..config import (
    logging,
    logger_llm,
    AGE_GEMINI_API_KEY,
    GROQ_API_KEY,
    LLM_PROVIDERS,
    LLM_REMOTE_COOLDOWN_SECONDS,
    LLM_GEMINI_MODEL,
    LLM_GROQ_MODEL,
    LLM_LOCAL_MODEL,
    LLM_LOCAL_API_BASE,
)

os.environ["LITELLM_LOG"] = "ERROR"
litellm.suppress_debug_info = True
warnings.filterwarnings("ignore", category=UserWarning, module="litellm")


class GenericAgent:
    """Generic chat agent with deterministic provider fallback order."""

    def __init__(self):
        self.providers = LLM_PROVIDERS or ("local",)
        self.provider_disabled_until: dict[str, float] = {}
        logging.info("[LLM] Ordem de providers: %s", " -> ".join(self.providers))

    def _provider_config(self, provider: str) -> dict | None:
        if provider == "gemini":
            api_key = AGE_GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "").strip()
            if not api_key:
                return None
            return {"model": LLM_GEMINI_MODEL, "api_key": api_key}

        if provider == "groq":
            if not GROQ_API_KEY:
                return None
            return {"model": LLM_GROQ_MODEL, "api_key": GROQ_API_KEY}

        if provider == "local":
            return {
                "model": LLM_LOCAL_MODEL,
                "api_base": LLM_LOCAL_API_BASE,
            }

        return None

    def _provider_available(self, provider: str) -> bool:
        return (
            self._provider_config(provider) is not None
            and time.monotonic() >= self.provider_disabled_until.get(provider, 0.0)
        )

    def _disable_provider(self, provider: str, exc: Exception) -> None:
        if provider != "local":
            self.provider_disabled_until[provider] = (
                time.monotonic() + LLM_REMOTE_COOLDOWN_SECONDS
            )
        logging.warning(
            "[LLM] Provider %s falhou; tentando o próximo. Motivo: %s",
            provider,
            exc,
        )

    @staticmethod
    def _messages(prompt: str) -> list[dict]:
        return [
            {
                "role": "system",
                "content": (
                    "Você é uma assistente inteligente, prestativa e sucinta. "
                    "Responda de forma direta em português."
                ),
            },
            {"role": "user", "content": prompt},
        ]

    def run(self, prompt: str) -> str:
        messages = self._messages(prompt)
        errors: list[str] = []

        for provider in self.providers:
            if not self._provider_available(provider):
                continue

            params = self._provider_config(provider)
            try:
                response = litellm.completion(messages=messages, **params)
                answer = response.choices[0].message.content or ""
                used_model = getattr(response, "model", params["model"])
                logger_llm.info(
                    "[LLM] provider=%s model=%s input=%s output=%s",
                    provider,
                    used_model,
                    prompt,
                    answer,
                )
                return answer
            except Exception as exc:
                errors.append(f"{provider}: {exc}")
                self._disable_provider(provider, exc)

        raise RuntimeError(
            "Todos os providers LLM falharam ou estão indisponíveis. "
            + " | ".join(errors)
        )

    def run_stream(self, prompt: str):
        messages = self._messages(prompt)
        errors: list[str] = []

        for provider in self.providers:
            if not self._provider_available(provider):
                continue

            params = self._provider_config(provider)
            emitted = False
            full_response = ""

            try:
                response = litellm.completion(
                    messages=messages,
                    stream=True,
                    **params,
                )

                for chunk in response:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        emitted = True
                        full_response += delta
                        yield delta

                logger_llm.info(
                    "[LLM STREAM] provider=%s model=%s input=%s output=%s",
                    provider,
                    params["model"],
                    prompt,
                    full_response,
                )
                return
            except Exception as exc:
                if emitted:
                    # A resposta já começou a ser enviada ao cliente. Repeti-la em
                    # outro provider produziria texto duplicado/corrompido.
                    raise

                errors.append(f"{provider}: {exc}")
                self._disable_provider(provider, exc)

        raise RuntimeError(
            "Todos os providers LLM falharam ou estão indisponíveis. "
            + " | ".join(errors)
        )
