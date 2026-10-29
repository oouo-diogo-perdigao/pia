from __future__ import annotations

import io
import json
import os
import time
import warnings
from pathlib import Path

from src.stt_recovery import recover_segments,segment_dict,trim_left_context

from faster_whisper import WhisperModel, download_model

from .config import (
    logging,
    logger_stt,
    STT_MODEL,
    STT_DEVICE,
    STT_COMPUTE_TYPE,
    STT_CPU_THREADS,
    STT_BEAM_SIZE,
    STT_BEST_OF,
    STT_TEMPERATURE,
)

warnings.filterwarnings("ignore", category=UserWarning, module="huggingface_hub")


class VoiceAgent:
    def __init__(self, models_dir: Path, model_name=None):
        self.models_dir = models_dir
        model_name=model_name or STT_MODEL

        logging.info("[STT] Carregando modelo %s em %s (%s)...", model_name, STT_DEVICE, STT_COMPUTE_TYPE)
        model_path = download_model(model_name, output_dir=str(self.models_dir/model_name))

        self.model = WhisperModel(
            model_path,
            device=STT_DEVICE,
            compute_type=STT_COMPUTE_TYPE,
            cpu_threads=STT_CPU_THREADS,
        )
        logging.info("[STT] Modelo pronto: dispositivo=%s, precisão=%s.", self.model.model.device, self.model.model.compute_type)

    @staticmethod
    def ensure_model_downloaded(model_size: str, models_dir: Path) -> None:
        models_dir.mkdir(parents=True, exist_ok=True)
        logging.info("[MODELO] Verificando arquivos no disco (%s)...", model_size)
        download_model(model_size, output_dir=str(models_dir/model_size))
        logging.info("[MODELO] Arquivos confirmados no disco.")

    def transcribe_chunk(
        self,
        audio_bytes: bytes,
        *,
        language: str | None = "pt",
        prompt: str | None = None,
        temperature: float | None = None,
        return_metadata: bool = False,
        progress=None,
    ) -> str | dict:
        """Transcribe an in-memory audio file.

        ``audio_bytes`` may contain WAV, MP3, WebM and other formats supported by
        PyAV/faster-whisper.  The recorder path keeps Portuguese as its default,
        while the OpenAI-compatible HTTP path may pass ``language=None`` to let
        Whisper detect the language automatically.
        """
        if not audio_bytes:
            return ""

        audio_stream = io.BytesIO(audio_bytes)

        transcription_temperature = (
            STT_TEMPERATURE if temperature is None else float(temperature)
        )

        transcribe_kwargs = {
            "language": language or None,
            "beam_size": STT_BEAM_SIZE,
            "best_of": STT_BEST_OF,
            "temperature": transcription_temperature,
            "condition_on_previous_text": False,
            "vad_filter": return_metadata,
            "word_timestamps": return_metadata,
            "vad_parameters": {"min_silence_duration_ms": 500},
        }

        if prompt:
            transcribe_kwargs["initial_prompt"] = prompt

        def report(state, processed=0.0, duration=0.0):
            if progress:
                progress(dict(state=state,processed=processed,duration=duration,percent=(100 if state=='completed' else min(99.9,processed/duration*100)) if duration>0 else 0))
            if return_metadata:
                logger_stt.info('[STT_PROGRESS] %s', json.dumps({
                    'state': state, 'processed': processed, 'duration': duration,
                    'percent': min(99.9, processed / duration * 100) if duration > 0 else 0,
                }))

        report('preparing')
        normalized = []
        try:
            segments, info = self.model.transcribe(audio_stream, **transcribe_kwargs)
            report('transcribing', 0, float(info.duration))
            last_report = time.monotonic()
            def initial():
                nonlocal last_report
                try:
                    for segment in segments:
                        if time.monotonic()-last_report>=1:
                            report('transcribing',float(segment.end),float(info.duration))
                            last_report=time.monotonic()
                        yield segment_dict(segment)
                finally:
                    if hasattr(segments,'close'):segments.close()
            samples=None
            def retry(start,end,attempt):
                nonlocal samples
                if samples is None:
                    from faster_whisper.audio import decode_audio
                    samples=decode_audio(io.BytesIO(audio_bytes),sampling_rate=16000)
                first=max(0,round(max(0,start-2)*16000));last=min(len(samples),round(end*16000))
                if last<=first:raise RuntimeError('Trecho de recuperação STT vazio.')
                settings={**transcribe_kwargs,'language':language or info.language,'condition_on_previous_text':False,'vad_filter':True,'word_timestamps':True,
                          'temperature':min(.8,.2+.2*attempt),'repetition_penalty':1.15,'hallucination_silence_threshold':2.0}
                # Never feed the generated/repeating transcript back as a prompt.
                result,_=self.model.transcribe(samples[first:last],**settings)
                rows=[]
                try:
                    for raw in result:
                        rows.append(segment_dict(raw,first/16000))
                        if len(rows)>10000:raise RuntimeError('Limite de segmentos excedido na recuperação STT.')
                finally:
                    if hasattr(result,'close'):result.close()
                trimmed=trim_left_context(rows,start)
                if trimmed is not None:return {'segments':trimmed,'offset':0}
                # A word crossing the context seam cannot be clipped or dropped.
                first=max(0,round(start*16000))
                result,_=self.model.transcribe(samples[first:last],**settings)
                return {'segments':result,'offset':first/16000}
            normalized=recover_segments(initial(),float(info.duration),retry,report=report)
            report('completed', float(info.duration), float(info.duration))
        except Exception:
            report('error')
            raise
        segments = normalized
        res = " ".join(segment["text"] for segment in segments).strip()

        if res:
            logger_stt.info(res)

        if return_metadata:
            return {"text": res, "segments": segments, "duration": float(info.duration),
                    "language": info.language}
        return res
