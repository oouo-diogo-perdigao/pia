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
    STT_PROVIDER,
    STT_REMOTE_COOLDOWN_SECONDS,
    STT_GEMINI_API_KEY,
    STT_GEMINI_MODEL,
    STT_GROK_API_KEY,
    STT_GROK_MODEL,
)


class RemoteSTTUnavailable(RuntimeError):
    pass


class STTManager(LocalSTTManager):
    """Cloud-first STT facade with transparent local Whisper fallback.

    The public interface intentionally matches the original STTManager, so the
    recorder bridge and OpenAI-compatible HTTP endpoint do not need provider-aware
    code. Remote providers are optional and can fail without taking STT offline.
    """

    def __init__(self):
        super().__init__()
        self.provider = STT_PROVIDER
        self.remote_result_queue: queue.Queue = queue.Queue()
        self.remote_lock = threading.Lock()
        self.remote_disabled_until = 0.0
        self.remote_disabled_reason = ""
        self._force_local_worker = False

    def _remote_configured(self) -> bool:
        if self.provider == "gemini":
            return bool(STT_GEMINI_API_KEY)
        if self.provider == "grok":
            return bool(STT_GROK_API_KEY)
        return False

    def _remote_available(self) -> bool:
        if self.provider == "local" or not self._remote_configured():
            return False
        return time.monotonic() >= self.remote_disabled_until

    def _disable_remote_temporarily(self, reason: str) -> None:
        self.remote_disabled_reason = reason
        self.remote_disabled_until = time.monotonic() + STT_REMOTE_COOLDOWN_SECONDS
        logging.warning(
            "[STT] Provider remoto %s indisponível por %ss; usando Whisper local. Motivo: %s",
            self.provider,
            STT_REMOTE_COOLDOWN_SECONDS,
            reason,
        )

    @staticmethod
    def _is_quota_or_auth_error(exc: Exception) -> bool:
        text = str(exc).lower()
        markers = (
            "429",
            "quota",
            "rate limit",
            "resource_exhausted",
            "resource exhausted",
            "insufficient",
            "401",
            "403",
            "unauthorized",
            "forbidden",
            "invalid api key",
            "api key not valid",
        )
        return any(marker in text for marker in markers)

    def ensure_worker_running(self):
        """Do not preload Whisper while the configured cloud provider is healthy."""
        if self._remote_available() and not self._force_local_worker:
            return
        return super().ensure_worker_running()

    def _local_send_chunk(self, chunk: bytes) -> None:
        self._force_local_worker = True
        try:
            super().send_chunk(chunk)
        finally:
            self._force_local_worker = False

    def send_chunk(self, chunk):
        """Prefer the configured remote provider and fallback to local Whisper."""
        if not self._remote_available():
            return self._local_send_chunk(chunk)

        # The recorder bridge is synchronous. Keep it responsive by running the
        # network operation outside the bridge thread and returning the result
        # through the same get_result() contract.
        threading.Thread(
            target=self._remote_chunk_job,
            args=(bytes(chunk),),
            daemon=True,
            name="STTRemoteChunk",
        ).start()

    def _remote_chunk_job(self, chunk: bytes) -> None:
        with self.remote_lock:
            try:
                text = self._transcribe_remote(chunk, language="pt")
                self.remote_result_queue.put({"ok": True, "text": text or None})
                return
            except Exception as exc:
                logging.exception("[STT] Falha no provider remoto %s.", self.provider)
                if self._is_quota_or_auth_error(exc):
                    self._disable_remote_temporarily(str(exc))

            # A mesma fala ainda precisa ser entregue. Reenvia apenas este chunk
            # ao worker local e deixa get_result() coletar a resposta normalmente.
            self._local_send_chunk(chunk)

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
        """Use remote STT first, then transparently retry through local Whisper."""
        if not audio_bytes:
            return {"ok": False, "error": "Arquivo de áudio vazio."}

        language = self._normalize_language(language)
        if self._remote_available():
            try:
                text = self._transcribe_remote(
                    audio_bytes,
                    language=language,
                    prompt=prompt,
                )
                return {"ok": True, "text": text or None, "request_id": None}
            except Exception as exc:
                logging.exception("[STT] Falha no provider remoto %s.", self.provider)
                if self._is_quota_or_auth_error(exc):
                    self._disable_remote_temporarily(str(exc))

        self._force_local_worker = True
        try:
            return super().transcribe_request(
                audio_bytes,
                language=language,
                prompt=prompt,
                temperature=temperature,
            )
        finally:
            self._force_local_worker = False

    def get_status_payload(self) -> dict:
        payload = super().get_status_payload()
        payload.update(
            {
                "stt_provider": self.provider,
                "stt_remote_available": self._remote_available(),
                "stt_fallback": "local",
                "stt_remote_disabled_reason": self.remote_disabled_reason or None,
            }
        )
        return payload

    def _transcribe_remote(
        self,
        audio_bytes: bytes,
        *,
        language: str | None = None,
        prompt: str | None = None,
    ) -> str:
        if self.provider == "gemini":
            return self._transcribe_gemini_live(audio_bytes, language=language)
        if self.provider == "grok":
            return self._transcribe_grok_litellm(
                audio_bytes,
                language=language,
                prompt=prompt,
            )
        raise RemoteSTTUnavailable(f"Provider STT desconhecido: {self.provider}")

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
                "Gemini Live recebe PCM bruto; o fallback local será usado para arquivos que não sejam WAV."
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
            # Gemini accepts BCP-47. Keep Portuguese recorder traffic explicit.
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
            # Google recommends chunks around 100 ms. The recorder already closes
            # utterances locally, so send those utterances in small PCM pieces and
            # explicitly end the stream for low finalization latency.
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

    def _transcribe_grok_litellm(
        self,
        audio_bytes: bytes,
        *,
        language: str | None = None,
        prompt: str | None = None,
    ) -> str:
        if not STT_GROK_API_KEY:
            raise RemoteSTTUnavailable("STT_GROK_API_KEY não configurada.")

        try:
            import litellm
        except ImportError as exc:
            raise RemoteSTTUnavailable("Dependência litellm ausente.") from exc

        # LiteLLM/OpenAI-compatible transcription APIs expect a file-like object
        # with a filename. A temporary WAV keeps that contract reliable on Windows.
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            with open(tmp_path, "rb") as audio_file:
                kwargs = {
                    "model": STT_GROK_MODEL,
                    "file": audio_file,
                    "api_key": STT_GROK_API_KEY,
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
