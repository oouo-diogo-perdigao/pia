from .config import logging
import threading
from pathlib import Path


def play_sound_async(sound_path: Path):
    """Reproduz um arquivo de som de forma assíncrona para não bloquear o servidor HTTP."""

    def _play():
        try:
            if sound_path.exists():
                # Tenta usar playsound se disponível, ou fallback para comando do windows se falhar
                try:
                    from playsound import playsound

                    playsound(str(sound_path.resolve()))
                except ImportError:
                    # Fallback nativo no Windows via winmm se playsound não estiver instalado
                    import ctypes

                    alias = f"sound_{abs(hash(str(sound_path)))}"
                    ctypes.windll.winmm.mciSendStringW(
                        f'open "{str(sound_path.resolve())}" type mpegvideo alias {alias}',
                        None,
                        0,
                        None,
                    )
                    ctypes.windll.winmm.mciSendStringW(
                        f"play {alias} wait", None, 0, None
                    )
                    ctypes.windll.winmm.mciSendStringW(f"close {alias}", None, 0, None)
        except Exception:
            logging.exception(f"[Audio] Erro ao reproduzir o som: {sound_path}")

    threading.Thread(target=_play, daemon=True).start()


def insert_text_at_cursor(text: str) -> None:
    if not text or not text.strip():
        return

    import pyperclip
    import time
    import ctypes

    logging.info("[TRANSCRICAO INSERINDO] %s", text)

    # 1. Salva o conteúdo atual da área de transferência para não perdê-lo
    previous_clipboard = pyperclip.paste()

    try:
        # 2. Copia o novo texto
        pyperclip.copy(text.strip() + " ")
        time.sleep(0.02)

        # 3. Simula o Ctrl+V para colar
        VK_CONTROL = 0x11
        VK_V = 0x56
        KEYEVENTF_KEYUP = 0x0002

        user32 = ctypes.windll.user32
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_V, 0, 0, 0)
        user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
        user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)

        # Pequena pausa para garantir que a aplicação receptora processe o evento de colar
        time.sleep(0.05)
    finally:
        # 4. Restaura o clipboard antigo para que você não perca o que estava copiado antes
        pyperclip.copy(previous_clipboard)


def clean_text(text):
    """
    Limpa o texto removendo caracteres indesejados e formatando Markdown.
    """
    import re

    # Remove caracteres nulos
    text = text.replace("\x00", " ")
    # Normaliza quebras de linha
    text = re.sub(r"\r\n?", "\n", text)
    # Remove links Markdown, mantendo apenas o texto visível.
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Remove blocos de código Markdown.
    text = re.sub(r"```(?:\w+)?\s*([\s\S]*?)```", r"\1", text)
    # Remove código inline.
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Remove negrito e itálico Markdown.
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    text = re.sub(r"(?<!\w)\*(.*?)\*(?!\w)", r"\1", text)
    text = re.sub(r"(?<!\w)_(.*?)_(?!\w)", r"\1", text)
    # Remove cabeçalhos Markdown.
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    # Remove citações Markdown.
    text = re.sub(r"(?m)^\s*>\s?", "", text)
    # Remove marcadores de listas.
    text = re.sub(r"(?m)^\s*[-*+]\s+", "", text)
    # Remove marcadores de checkbox.
    text = re.sub(r"(?m)^\s*\[[ xX]\]\s*", "", text)
    # Remove linhas horizontais Markdown.
    text = re.sub(r"(?m)^\s*([-*_])(?:\s*\1){2,}\s*$", "", text)
    # Remove espaços repetidos.
    text = re.sub(r"[ \t]+", " ", text)
    # Reduz excesso de linhas vazias.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
