"""Provider local Supertonic 3 (ONNX)."""

from __future__ import annotations

import io
import json
import logging
import threading
import unicodedata
import urllib.request
import wave
from pathlib import Path
from typing import Any

from .base import AudioResult, MIME_BY_FORMAT, TTSProvider
from .local_catalog import (
    install_artifacts,
    is_manifest_installed,
    model_dir,
    uninstall_artifacts,
)

logger = logging.getLogger(__name__)

_MODEL_ID = "supertonic-3"
_HF_BASE = "https://huggingface.co/Supertone/supertonic-2/resolve/main"
_SUPERTONIC_VOICES = [
    {"id": "F1", "name": "Voz feminina 1", "lang": "multi", "gender": "female"},
    {"id": "F2", "name": "Voz feminina 2", "lang": "multi", "gender": "female"},
    {"id": "F3", "name": "Voz feminina 3", "lang": "multi", "gender": "female"},
    {"id": "F4", "name": "Voz feminina 4", "lang": "multi", "gender": "female"},
    {"id": "F5", "name": "Voz feminina 5", "lang": "multi", "gender": "female"},
    {"id": "M1", "name": "Voz masculina 1", "lang": "multi", "gender": "male"},
    {"id": "M2", "name": "Voz masculina 2", "lang": "multi", "gender": "male"},
    {"id": "M3", "name": "Voz masculina 3", "lang": "multi", "gender": "male"},
    {"id": "M4", "name": "Voz masculina 4", "lang": "multi", "gender": "male"},
    {"id": "M5", "name": "Voz masculina 5", "lang": "multi", "gender": "male"},
]
_VALID_VOICE_IDS = {v["id"] for v in _SUPERTONIC_VOICES}
_ARTIFACTS = [
    {
        "filename": "tts.json",
        "url": f"{_HF_BASE}/onnx/tts.json",
        "size_bytes": 8_699,
    },
    {
        "filename": "unicode_indexer.json",
        "url": f"{_HF_BASE}/onnx/unicode_indexer.json",
        "size_bytes": 262_196,
    },
    {
        "filename": "duration_predictor.onnx",
        "url": f"{_HF_BASE}/onnx/duration_predictor.onnx",
        "size_bytes": 1_521_526,
    },
    {
        "filename": "text_encoder.onnx",
        "url": f"{_HF_BASE}/onnx/text_encoder.onnx",
        "size_bytes": 27_431_318,
    },
    {
        "filename": "vector_estimator.onnx",
        "url": f"{_HF_BASE}/onnx/vector_estimator.onnx",
        "size_bytes": 132_471_364,
    },
    {
        "filename": "vocoder.onnx",
        "url": f"{_HF_BASE}/onnx/vocoder.onnx",
        "size_bytes": 101_405_066,
    },
    *[
        {
            "filename": f"voice_styles/{vid}.json",
            "url": f"{_HF_BASE}/voice_styles/{vid}.json",
            "size_bytes": 420_000,
        }
        for vid in ("F1", "F2", "F3", "F4", "F5", "M1", "M2", "M3", "M4", "M5")
    ],
]
_CORE_FILES = (
    "tts.json",
    "unicode_indexer.json",
    "duration_predictor.onnx",
    "text_encoder.onnx",
    "vector_estimator.onnx",
    "vocoder.onnx",
)


def _encode_wav_int16(samples: Any, sample_rate: int) -> bytes:
    import numpy as np

    arr = np.asarray(samples, dtype=np.float32).reshape(-1)
    arr = np.clip(arr, -1.0, 1.0)
    pcm = (arr * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def _text_to_ids(
    text: str,
    indexer: list[int],
    *,
    lang: str = "pt",
    multilingual: bool = True,
) -> list[int]:
    clean = unicodedata.normalize("NFC", (text or "").strip())
    if multilingual and clean and not (clean.startswith("<") and "</" in clean):
        clean = f"<{lang}>{clean}</{lang}>"
    decomposed = unicodedata.normalize("NFKD", clean)
    ids: list[int] = []
    n_idx = len(indexer)
    for ch in decomposed:
        code = ord(ch)
        if code < n_idx and indexer[code] >= 0:
            ids.append(int(indexer[code]))
    if not ids:
        space_id = (
            indexer[ord(" ")] if ord(" ") < n_idx and indexer[ord(" ")] >= 0 else 0
        )
        ids.append(int(space_id))
    return ids


class _SupertonicRuntime:
    """Cache thread-safe das sessões ONNX e estilos de voz do Supertonic 3."""

    def __init__(self, base_dir: Path) -> None:
        import onnxruntime as ort

        self.base_dir = base_dir
        self.cfg = json.loads((base_dir / "tts.json").read_text(encoding="utf-8"))
        self.indexer: list[int] = json.loads(
            (base_dir / "unicode_indexer.json").read_text(encoding="utf-8")
        )
        providers = ["CPUExecutionProvider"]
        self.dp = ort.InferenceSession(
            str(base_dir / "duration_predictor.onnx"), providers=providers
        )
        self.text_enc = ort.InferenceSession(
            str(base_dir / "text_encoder.onnx"), providers=providers
        )
        self.vec_est = ort.InferenceSession(
            str(base_dir / "vector_estimator.onnx"), providers=providers
        )
        self.vocoder = ort.InferenceSession(
            str(base_dir / "vocoder.onnx"), providers=providers
        )
        self._styles: dict[str, tuple[Any, Any]] = {}
        self._lock = threading.Lock()

    def get_style(self, voice_id: str) -> tuple[Any, Any]:
        import numpy as np

        vid = voice_id if voice_id in _VALID_VOICE_IDS else "F1"
        with self._lock:
            if vid in self._styles:
                return self._styles[vid]
        style_path = self.base_dir / "voice_styles" / f"{vid}.json"
        if not style_path.is_file():
            style_path.parent.mkdir(parents=True, exist_ok=True)
            url = f"{_HF_BASE}/voice_styles/{vid}.json"
            req = urllib.request.Request(
                url, headers={"User-Agent": "PIA-TTS-Installer/1.0"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                style_path.write_bytes(resp.read())
        data = json.loads(style_path.read_text(encoding="utf-8"))
        style_dp = np.array(data["style_dp"]["data"], dtype=np.float32).reshape(
            data["style_dp"]["dims"]
        )
        style_ttl = np.array(data["style_ttl"]["data"], dtype=np.float32).reshape(
            data["style_ttl"]["dims"]
        )
        with self._lock:
            self._styles[vid] = (style_dp, style_ttl)
        return style_dp, style_ttl

    def synthesize_wav(
        self, text: str, voice_id: str, speed: float, total_steps: int = 5
    ) -> bytes:
        import numpy as np

        multilingual = self.cfg.get("split") == "opensource-multilingual"
        ids = _text_to_ids(text, self.indexer, lang="pt", multilingual=multilingual)
        text_ids = np.array([ids], dtype=np.int64)
        text_mask = np.ones((1, 1, len(ids)), dtype=np.float32)
        style_dp, style_ttl = self.get_style(voice_id)

        spd = max(0.5, min(2.0, float(speed or 1.0)))
        dur_raw = self.dp.run(
            None,
            {"text_ids": text_ids, "style_dp": style_dp, "text_mask": text_mask},
        )[0]
        duration = max(0.1, float(dur_raw.reshape(-1)[0]) / spd)
        text_emb = self.text_enc.run(
            None,
            {"text_ids": text_ids, "style_ttl": style_ttl, "text_mask": text_mask},
        )[0]

        sr = int(self.cfg["ae"]["sample_rate"])
        chunk_size = int(self.cfg["ae"]["base_chunk_size"]) * int(
            self.cfg["ttl"]["chunk_compress_factor"]
        )
        ldim = int(self.cfg["ttl"]["latent_dim"]) * int(
            self.cfg["ttl"]["chunk_compress_factor"]
        )
        wav_len = max(1, int(duration * sr))
        lat_len = max(1, (wav_len + chunk_size - 1) // chunk_size)
        lat_mask = np.ones((1, 1, lat_len), dtype=np.float32)
        latent = np.random.randn(1, ldim, lat_len).astype(np.float32) * lat_mask
        total_arr = np.array([float(total_steps)], dtype=np.float32)

        with self._lock:
            for step in range(total_steps):
                latent = self.vec_est.run(
                    None,
                    {
                        "noisy_latent": latent,
                        "text_emb": text_emb,
                        "style_ttl": style_ttl,
                        "latent_mask": lat_mask,
                        "text_mask": text_mask,
                        "current_step": np.array([float(step)], dtype=np.float32),
                        "total_step": total_arr,
                    },
                )[0]
            wav_out = self.vocoder.run(None, {"latent": latent})[0]

        samples = wav_out.reshape(-1)[:wav_len]
        return _encode_wav_int16(samples, sr)


_runtime_lock = threading.Lock()
_runtime_cache: dict[Path, _SupertonicRuntime] = {}


def _get_runtime(base_dir: Path) -> _SupertonicRuntime:
    resolved = base_dir.resolve()
    with _runtime_lock:
        rt = _runtime_cache.get(resolved)
        if rt is None:
            rt = _SupertonicRuntime(resolved)
            _runtime_cache[resolved] = rt
        return rt


def _clear_runtime_cache() -> None:
    with _runtime_lock:
        _runtime_cache.clear()


class Supertonic3Provider(TTSProvider):
    id = "supertonic3"
    name = "Supertonic 3 (local)"
    kind = "local"
    description = "Lê as respostas em voz alta neste computador, em 31 idiomas"

    def models(self) -> list[dict[str, Any]]:
        return [
            {
                "id": _MODEL_ID,
                "name": "Supertonic 3",
                "description": self.description,
                "size_mb": 260,
            }
        ]

    def _model_root(self) -> Path | None:
        managed = model_dir(self.id, _MODEL_ID)
        if is_manifest_installed(self.id, _MODEL_ID) and all(
            (managed / f).is_file() for f in _CORE_FILES
        ):
            return managed
        if all((managed / f).is_file() for f in _CORE_FILES):
            return managed
        return None

    def is_available(self, model_id: str | None = None) -> bool:
        if model_id and model_id != _MODEL_ID:
            return False
        return self._model_root() is not None

    def capabilities(self, model_id: str | None = None) -> dict[str, Any]:
        return {
            "install": True,
            "uninstall": True,
            "formats": ["wav"],
            "speed": {
                "supported": True,
                "min": 0.5,
                "max": 2.0,
                "step": 0.05,
                "default": 1.0,
            },
        }

    def list_voices(self, model_id: str | None = None) -> list[dict[str, Any]]:
        if model_id and model_id != _MODEL_ID:
            return []
        return list(_SUPERTONIC_VOICES)

    def install(
        self,
        model_id: str | None = None,
        *,
        job_id: str,
        progress_cb=None,
        cancel_event=None,
    ):
        mid = model_id or _MODEL_ID
        if mid != _MODEL_ID:
            raise ValueError(f"Modelo Supertonic desconhecido: {mid}")
        return install_artifacts(
            self.id,
            mid,
            _ARTIFACTS,
            job_id=job_id,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
        )

    def uninstall(self, model_id: str | None = None) -> bool:
        mid = model_id or _MODEL_ID
        if mid != _MODEL_ID:
            raise ValueError(f"Modelo Supertonic desconhecido: {mid}")
        _clear_runtime_cache()
        return uninstall_artifacts(self.id, mid)

    def synthesize(
        self,
        text: str,
        voice: str,
        speed: float,
        response_format: str,
        *,
        model: str | None = None,
        style: str | None = None,
        device: str | None = None,
    ) -> AudioResult:
        base_dir = self._model_root()
        if base_dir is None:
            raise RuntimeError("Supertonic 3 não está instalado localmente.")
        if model and model != _MODEL_ID:
            raise ValueError(f"Modelo Supertonic desconhecido: {model}")
        fmt = (response_format or "wav").lower().strip()
        if fmt not in MIME_BY_FORMAT:
            fmt = "wav"
        runtime = _get_runtime(base_dir)
        wav_bytes = runtime.synthesize_wav(
            text=text,
            voice_id=voice or "F1",
            speed=float(speed),
        )
        if fmt != "wav":
            from src.TTSManager import TTSManager

            wav_bytes = TTSManager()._convert_format(wav_bytes, fmt)
        return AudioResult(
            audio=wav_bytes,
            mime=MIME_BY_FORMAT.get(fmt, "audio/wav"),
            format=fmt,
        )
