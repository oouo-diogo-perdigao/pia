import requests
from src.config import SAT_SERVER_URL


def speak_tts(text: str):
    """Envia texto para o servidor TTS reproduzir em áudio."""
    try:
        payload = {"text": text}
        requests.post(f"{SAT_SERVER_URL}/speak", json=payload)
    except Exception as e:
        print(f"[SAT] Erro ao enviar áudio para o servidor SAT: {e}")
