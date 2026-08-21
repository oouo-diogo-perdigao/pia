import time
import requests
import numpy as np
import pyaudio
import openwakeword
from openwakeword.model import Model
import pygame
import webbrowser
import os
import difflib

RATE = 16000
CHANNELS = 1
CHUNK = 1280
THRESHOLD = 0.5

# URLs dos Serviços
STT_SERVER_URL = "http://127.0.0.1:8767"  # Servidor STT
TTS_SERVER_URL = "http://127.0.0.1:8765"  # Endpoint da sua rota TTS

StartSound = "..\\sounds\\start.mp3"
EndSound = "..\\sounds\\end.mp3"

pygame.mixer.init()

# Lista de comandos conhecidos para match por similaridade
COMMAND_ACTIONS = {
    "abrir navegador": lambda: webbrowser.open("https://www.google.com"),
    "abrir bloco de notas": lambda: os.system("notepad.exe"),
}


def speak_tts(text: str):
    """Envia texto para o servidor TTS reproduzir."""
    try:
        payload = {"text": text}
        # Tenta enviar para a rota TTS (ajuste o formato/payload se o seu endpoint exigir algo diferente)
        requests.post(f"{TTS_SERVER_URL}/speak", json=payload, timeout=5)

    except Exception as e:
        print(f"[TTS] Erro ao enviar áudio para o servidor TTS: {e}")


def play_sound(file_path):
    try:
        pygame.mixer.music.load(file_path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.05)
    except Exception as e:
        print(f"Erro ao tocar som: {e}")


def process_command(text: str):
    """
    Filtra a palavra 'comando' e busca a ação mais similar na lista de comandos.
    """
    text_clean = text.lower().strip()

    # 1. Filtro obrigatorio: Verifica se contem a palavra 'comando'
    if "comando" not in text_clean:
        print(f"[IGNORADO]: Frase sem a palavra gatilho 'comando' -> '{text_clean}'")
        return

    # Remove a palavra 'comando' da string para isolar a instrução
    action_text = text_clean.replace("comando", "").strip()
    print(f"\n[TEXTO DO COMANDO EXTRAÍDO]: '{action_text}' (Original: '{text_clean}')")

    # 2. Busca por similaridade usando difflib
    best_match = None
    best_ratio = 0.0
    cutoff = 0.6  # Nível de similaridade aceitável (60%)

    for target_cmd in COMMAND_ACTIONS.keys():
        ratio = difflib.SequenceMatcher(None, action_text, target_cmd).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = target_cmd

    if best_match and best_ratio >= cutoff:
        print(
            f"-> Ação encontrada por similaridade ({best_ratio*100:.1f}%): '{best_match}'"
        )
        COMMAND_ACTIONS[best_match]()
    else:
        print(
            f"-> Comando não reconhecido por similaridade suficiente (Melhor match: {best_ratio*100:.1f}%)."
        )


def start_continuous_session(stream, model):
    """
    Mantém o servidor STT gravando e processando comandos continuamente.
    """
    print("\n>>> SESSÃO DE COMANDOS INICIADA (Fale seus comandos...) <<<")

    play_sound(StartSound)

    # Limpeza de memória do áudio para evitar falso duplo acionamento
    model.reset()
    time.sleep(0.5)

    while stream.get_read_available() > 0:
        stream.read(CHUNK, exception_on_overflow=False)

    try:
        requests.post(f"{STT_SERVER_URL}/start", timeout=2)
    except Exception as e:
        print(f"Erro ao conectar ao servidor STT: {e}")
        return

    session_start_time = time.time()
    last_speech_time = time.time()
    prompted_inactivity = False

    try:
        while True:
            time.sleep(0.2)
            now = time.time()

            # --- A) Checa transcrição vinda do Servidor STT ---
            try:
                status_res = requests.get(f"{STT_SERVER_URL}/status", timeout=2)
                if status_res.ok:
                    data = status_res.json()
                    chunks = data.get("text_chunks", [])
                    is_speaking = data.get("is_speaking", False)

                    if chunks or is_speaking:
                        last_speech_time = now

                    for text in chunks:
                        text_lower = text.lower().strip()

                        # Palavras de encerramento direto
                        if "finalizar" in text_lower or "encerra" in text_lower:
                            print("\n[PALAVRA DE PARADA DETECTADA VIA TRANSCRIÇÃO]")
                            return

                        # Processa comando via filtro e similaridade
                        if text_lower:
                            process_command(text_lower)

            except Exception as e:
                print(f"Erro ao consultar status: {e}")

            # --- B) Checa inatividade de 3 segundos no início sem fala ---
            if not prompted_inactivity and (now - last_speech_time >= 3.0):
                print("\n[INATIVIDADE DETECTADA] Prompting via TTS...")
                speak_tts("Em que posso ajudá-lo, mestre?")
                prompted_inactivity = True  # Dispara apenas uma vez por sessão

            # --- C) Checa se o usuário falou a Wakeword de novo (Com Cooldown) ---
            if now - session_start_time > 2.5:
                if stream.get_read_available() >= CHUNK:
                    data = stream.read(CHUNK, exception_on_overflow=False)
                    audio_frame = np.frombuffer(data, dtype=np.int16)
                    predictions = model.predict(audio_frame)

                    for wakeword, score in predictions.items():
                        if score >= THRESHOLD:
                            print(
                                f"\n[WAKEWORD DETECTADA NOVAMENTE: {wakeword}] Encerrando sessão..."
                            )
                            return

    finally:
        try:
            requests.post(f"{STT_SERVER_URL}/stop", timeout=2)
        except Exception:
            pass

        print(">>> SESSÃO DE COMANDOS ENCERRADA <<<\n")
        play_sound(EndSound)
        model.reset()


def main():
    print("Baixando/verificando modelos...")
    openwakeword.utils.download_models()

    print("Carregando modelo...")
    model = Model(wakeword_models=["alexa", "hey_mycroft"])

    audio = pyaudio.PyAudio()
    stream = audio.open(
        format=pyaudio.paInt16,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        frames_per_buffer=CHUNK,
    )

    print("\n" + "=" * 50)
    print("Microfone ativo. Diga 'Hey Mycroft' para começar.")
    print("=" * 50 + "\n")

    last_detection = 0

    try:
        while True:
            data = stream.read(CHUNK, exception_on_overflow=False)
            audio_frame = np.frombuffer(data, dtype=np.int16)
            predictions = model.predict(audio_frame)

            for wakeword, score in predictions.items():
                if score >= THRESHOLD:
                    now = time.time()
                    if now - last_detection >= 2.0:
                        print(f"\nPALAVRA DETECTADA: {wakeword} (score: {score:.2f})")
                        start_continuous_session(stream, model)
                        last_detection = time.time()

    except KeyboardInterrupt:
        print("\nEncerrando...")
    finally:
        stream.stop_stream()
        stream.close()
        audio.terminate()


if __name__ == "__main__":
    main()
