import requests
from src.config import TTS_SERVER_URL


def speak_tts(text: str):
    """Envia texto para o servidor TTS reproduzir em áudio."""
    try:
        payload = {"text": text}
        requests.post(f"{TTS_SERVER_URL}/speak", json=payload, timeout=5)
    except Exception as e:
        print(f"[TTS] Erro ao enviar áudio para o servidor TTS: {e}")
