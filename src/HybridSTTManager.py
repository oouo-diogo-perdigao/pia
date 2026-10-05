from __future__ import annotations

import asyncio
import io
import os
import queue
import tempfile
import threading
import time
import wave

from .STTManager import STTManager as LocalSTTManager, SATState
from .config import (
    logging,
    logger_stt,
    STT_PROVIDERS,
    STT_REMOTE_COOLDOWN_SECONDS,
    STT_GEMINI_API_KEY,
    STT_GEMINI_MODEL,
    GROQ_API_KEY,
    STT_GROQ_MODEL,
)


class RemoteSTTUnavailable(RuntimeError):
    pass


class STTManager(LocalSTTManager):
    """Ordered multi-provider STT facade with local Whisper fallback."""

    def __init__(self):
        super().__init__()
        self.providers = STT_PROVIDERS or ("local",)
        self.remote_result_queue: queue.Queue = queue.Queue()
        self.remote_lock = threading.Lock()
        self.provider_disabled_until: dict[str, float] = {}
        self.provider_disabled_reason: dict[str, str] = {}
        self.active_provider: str | None = None
        self._force_local_worker = False

        logging.info("[STT] Ordem de providers: %s", " -> ".join(self.providers))

    def _provider_configured(self, provider: str) -> bool:
        if provider == "gemini":
            return bool(STT_GEMINI_API_KEY)
        if provider == "groq":
            return bool(GROQ_API_KEY)
        if provider == "local":
            return True
        return False

    def _provider_available(self, provider: str) -> bool:
        if not self._provider_configured(provider):
            return False
        return time.monotonic() >= self.provider_disabled_until.get(provider, 0.0)

    def _disable_provider_temporarily(self, provider: str, reason: str) -> None:
        if provider == "local":
            return
        self.provider_disabled_reason[provider] = reason
        self.provider_disabled_until[provider] = (
            time.monotonic() + STT_REMOTE_COOLDOWN_SECONDS
        )
        logging.warning(
            "[STT] Provider %s indisponível por %ss; tentando o próximo. Motivo: %s",
            provider,
            STT_REMOTE_COOLDOWN_SECONDS,
            reason,
        )

    def _next_available_provider(self) -> str | None:
        for provider in self.providers:
            if self._provider_available(provider):
                return provider
        return None

    def ensure_worker_running(self):
        """Only warm local Whisper when local is the next usable provider."""
        if self._force_local_worker:
            return super().ensure_worker_running()

        provider = self._next_available_provider()
        if provider == "local":
            return super().ensure_worker_running()
        return None

    def _local_send_chunk(self, chunk: bytes) -> None:
        self.active_provider = "local"
        self._force_local_worker = True
        try:
            super().send_chunk(chunk)
        finally:
            self._force_local_worker = False

    def send_chunk(self, chunk):
        """Transcribe recorder audio using providers in configured order."""
        provider = self._next_available_provider()
        if provider == "local":
            return self._local_send_chunk(chunk)

        if provider is None:
            self.remote_result_queue.put(
                {"ok": False, "error": "Nenhum provider STT disponível."}
            )
            return

        threading.Thread(
            target=self._provider_chain_chunk_job,
            args=(bytes(chunk),),
            daemon=True,
            name="STTProviderChain",
        ).start()

    def _provider_chain_chunk_job(self, chunk: bytes) -> None:
        with self.remote_lock:
            for provider in self.providers:
                if not self._provider_available(provider):
                    continue

                if provider == "local":
                    self._local_send_chunk(chunk)
                    return

                try:
                    self.active_provider = provider
                    text = self._transcribe_remote(provider, chunk, language="pt")
                    if text:
                        logger_stt.info(text)
                    self.remote_result_queue.put(
                        {
                            "ok": True,
                            "text": text or None,
                            "provider": provider,
                        }
                    )
                    return
                except Exception as exc:
                    logging.warning(
                        "[STT] Falha no provider %s: %s",
                        provider,
                        exc,
                    )
                    self._disable_provider_temporarily(provider, str(exc))

            self.active_provider = None
            self.remote_result_queue.put(
                {
                    "ok": False,
                    "error": "Todos os providers STT configurados falharam ou estão indisponíveis.",
                }
            )

    def get_result(self, timeout=0.1):
        try:
            return self.remote_result_queue.get_nowait()
        except queue.Empty:
            return super().get_result(timeout=timeout)

    def transcribe_request(
        self,
        audio_bytes: bytes,
        *,
        language: str | None = None,
        prompt: str | None = None,
        temperature: float | None = None,
    ) -> dict:
        if not audio_bytes:
            return {"ok": False, "error": "Arquivo de áudio vazio."}

        language = self._normalize_language(language)
        errors: list[str] = []

        for provider in self.providers:
            if not self._provider_available(provider):
                continue

            if provider == "local":
                self.active_provider = "local"
                self._force_local_worker = True
                try:
                    result = super().transcribe_request(
                        audio_bytes,
                        language=language,
                        prompt=prompt,
                        temperature=temperature,
                    )
                    if result.get("ok"):
                        result["provider"] = "local"
                    return result
                finally:
                    self._force_local_worker = False

            try:
                self.active_provider = provider
                text = self._transcribe_remote(
                    provider,
                    audio_bytes,
                    language=language,
                    prompt=prompt,
                )
                if text:
                    logger_stt.info(text)
                return {
                    "ok": True,
                    "text": text or None,
                    "request_id": None,
                    "provider": provider,
                }
            except Exception as exc:
                errors.append(f"{provider}: {exc}")
                logging.warning("[STT] Falha no provider %s: %s", provider, exc)
                self._disable_provider_temporarily(provider, str(exc))

        self.active_provider = None
        return {
            "ok": False,
            "error": "Todos os providers STT falharam. " + " | ".join(errors),
        }

    def get_status_payload(self) -> dict:
        payload = super().get_status_payload()
        next_provider = self._next_available_provider()
        payload.update(
            {
                # Campos antigos preservados para clientes existentes.
                "stt_provider": self.active_provider or next_provider,
                "stt_remote_available": any(
                    provider != "local" and self._provider_available(provider)
                    for provider in self.providers
                ),
                "stt_fallback": "local" if "local" in self.providers else None,
                # Campos novos para a cadeia ordenada.
                "stt_providers": list(self.providers),
                "stt_active_provider": self.active_provider,
                "stt_provider_available": {
                    provider: self._provider_available(provider)
                    for provider in self.providers
                },
                "stt_provider_disabled_reason": {
                    provider: self.provider_disabled_reason.get(provider)
                    for provider in self.providers
                    if self.provider_disabled_reason.get(provider)
                },
            }
        )
        return payload

    def _transcribe_remote(
        self,
        provider: str,
        audio_bytes: bytes,
        *,
        language: str | None = None,
        prompt: str | None = None,
    ) -> str:
        if provider == "gemini":
            return self._transcribe_gemini_live(audio_bytes, language=language)
        if provider == "groq":
            return self._transcribe_groq_litellm(
                audio_bytes,
                language=language,
                prompt=prompt,
            )
        raise RemoteSTTUnavailable(f"Provider STT desconhecido: {provider}")

    @staticmethod
    def _wav_to_pcm16(audio_bytes: bytes) -> tuple[bytes, int]:
        try:
            with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                if wf.getsampwidth() != 2:
                    raise RemoteSTTUnavailable("Gemini Live exige PCM de 16 bits.")
                if wf.getnchannels() != 1:
                    raise RemoteSTTUnavailable("Gemini Live exige áudio mono.")
                rate = wf.getframerate()
                return wf.readframes(wf.getnframes()), rate
        except wave.Error as exc:
            raise RemoteSTTUnavailable(
                "Gemini Live recebe PCM bruto; use WAV mono/16-bit ou outro provider."
            ) from exc

    def _transcribe_gemini_live(
        self, audio_bytes: bytes, *, language: str | None = None
    ) -> str:
        if not STT_GEMINI_API_KEY:
            raise RemoteSTTUnavailable("STT_GEMINI_API_KEY não configurada.")

        pcm, sample_rate = self._wav_to_pcm16(audio_bytes)
        return asyncio.run(self._transcribe_gemini_live_async(pcm, sample_rate, language))

    async def _transcribe_gemini_live_async(
        self, pcm: bytes, sample_rate: int, language: str | None
    ) -> str:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise RemoteSTTUnavailable(
                "Dependência google-genai ausente. Execute 'uv sync'."
            ) from exc

        language_codes = []
        if language:
            language_codes = ["pt-BR" if language == "pt" else language]

        client = genai.Client(api_key=STT_GEMINI_API_KEY)
        config = types.LiveConnectConfig(
            response_modalities=["TEXT"],
            input_audio_transcription=types.AudioTranscriptionConfig(
                language_codes=language_codes,
                mode="SMART",
            ),
        )

        async with client.aio.live.connect(
            model=STT_GEMINI_MODEL,
            config=config,
        ) as session:
            bytes_per_100ms = max(2, int(sample_rate * 2 * 0.1))
            for offset in range(0, len(pcm), bytes_per_100ms):
                await session.send_realtime_input(
                    audio=types.Blob(
                        data=pcm[offset : offset + bytes_per_100ms],
                        mime_type=f"audio/pcm;rate={sample_rate}",
                    )
                )
            await session.send_realtime_input(audio_stream_end=True)

            async for response in session.receive():
                content = response.server_content
                if content and content.input_transcription:
                    return (content.input_transcription.text or "").strip()

        return ""

    def _transcribe_groq_litellm(
        self,
        audio_bytes: bytes,
        *,
        language: str | None = None,
        prompt: str | None = None,
    ) -> str:
        if not GROQ_API_KEY:
            raise RemoteSTTUnavailable("GROQ_API_KEY não configurada.")

        try:
            import litellm
        except ImportError as exc:
            raise RemoteSTTUnavailable("Dependência litellm ausente.") from exc

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            with open(tmp_path, "rb") as audio_file:
                kwargs = {
                    "model": STT_GROQ_MODEL,
                    "file": audio_file,
                    "api_key": GROQ_API_KEY,
                }
                if language:
                    kwargs["language"] = language
                if prompt:
                    kwargs["prompt"] = prompt
                response = litellm.transcription(**kwargs)

            if isinstance(response, dict):
                return str(response.get("text") or "").strip()
            return str(getattr(response, "text", "") or "").strip()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


__all__ = ["STTManager", "SATState"]
