import time
import requests
import numpy as np
import pyaudio
import openwakeword
from openwakeword.model import Model
import pygame
import os
import difflib
import importlib
import sys

RATE = int(os.getenv("RATE", 16000))
CHANNELS = int(os.getenv("CHANNELS", 1))
CHUNK = int(os.getenv("CHUNK", 1280))
THRESHOLD = float(os.getenv("THRESHOLD", 0.5))

# URLs dos Serviços
STT_SERVER_URL = os.getenv("STT_SERVER_URL", "http://127.0.0.1:8767")
TTS_SERVER_URL = os.getenv("TTS_SERVER_URL", "http://127.0.0.1:8765")
AGENT_SERVER_URL = os.getenv("AGENT_SERVER_URL", "http://127.0.0.1:8766")

# URLs dos Serviços

StartSound = "..\\sounds\\start.mp3"
EndSound = "..\\sounds\\end.mp3"

pygame.mixer.init()

# Dicionário dinâmico global de comandos
COMMAND_ACTIONS = {}


def send_to_agent(prompt_text: str):
    """Envia a requisição com timeout de leitura mínimo (Fire and Forget)."""
    try:
        print(f"\n[AGENT REQUEST]: Disparando requisição -> '{prompt_text}'")
        # timeout=(timeout_de_conexao, timeout_de_resposta)
        requests.post(
            f"{AGENT_SERVER_URL}/process",
            json={"text": prompt_text},
            timeout=(0.5, 0.1),  # Aguarda no máximo 100ms pela resposta
        )
    except requests.exceptions.ReadTimeout:
        # Ignora o timeout de leitura já que não queremos esperar pela resposta
        print("[AGENT]: Texto enviado com sucesso (sem aguardar resposta).")
    except Exception as e:
        print(f"[AGENT]: Erro na conexão com o servidor Agent: {e}")


def load_commands(folder_name="comandos"):
    """Carrega ou recarrega dinamicamente os arquivos .py na pasta 'comandos'."""
    global COMMAND_ACTIONS
    COMMAND_ACTIONS.clear()

    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())

    if not os.path.exists(folder_name):
        os.makedirs(folder_name)

    print(f"\n[COMANDOS]: Carregando comandos dinamicamente de '{folder_name}'...")

    for file_name in os.listdir(folder_name):
        if file_name.endswith(".py") and not file_name.startswith("__"):
            module_name = f"{folder_name}.{file_name[:-3]}"
            try:
                if module_name in sys.modules:
                    module = importlib.reload(sys.modules[module_name])
                else:
                    module = importlib.import_module(module_name)

                if hasattr(module, "COMMAND_NAME") and hasattr(module, "execute"):
                    cmd_name = module.COMMAND_NAME.lower().strip()
                    COMMAND_ACTIONS[cmd_name] = module.execute
                    print(f"  -> Comando carregado: '{cmd_name}' ({file_name})")
                else:
                    print(
                        f"  [ALERTA] Ignorado '{file_name}': falta COMMAND_NAME ou execute()"
                    )
            except Exception as e:
                print(f"  [ERRO] Falha ao carregar '{file_name}': {e}")

    # Adiciona o comando embutido de recarregar a própria lista
    COMMAND_ACTIONS["recarregar comandos"] = lambda: load_commands(folder_name)
    print(f"[COMANDOS]: Total de {len(COMMAND_ACTIONS)} comando(s) ativo(s).\n")


def speak_tts(text: str):
    """Envia texto para o servidor TTS reproduzir."""
    try:
        payload = {"text": text}
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
    """Filtra 'comando' para rotinas locais. Se não for comando local, envia ao Agent."""
    text_clean = text.lower().strip()

    # 1. Se contiver a palavra 'comando', tenta executar script local
    if "comando" in text_clean:
        action_text = text_clean.replace("comando", "").strip()
        print(f"\n[COMANDO LOCAL DETECTADO]: '{action_text}'")

        best_match = None
        best_ratio = 0.0
        cutoff = 0.6

        for target_cmd in COMMAND_ACTIONS.keys():
            ratio = difflib.SequenceMatcher(None, action_text, target_cmd).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = target_cmd

        if best_match and best_ratio >= cutoff:
            print(f"-> Executando comando ({best_ratio*100:.1f}%): '{best_match}'")
            COMMAND_ACTIONS[best_match]()
            return
        else:
            print(f"-> Comando local não reconhecido. Repassando ao Agent...")

    # 2. Se não for comando local (ou falhar no match), manda para o Agent (Gemini)
    send_to_agent(text_clean)


def start_continuous_session(stream, model):
    """Mantém o servidor STT gravando e processando comandos continuamente."""
    print("\n>>> SESSÃO DE COMANDOS INICIADA (Fale seus comandos...) <<<")

    play_sound(StartSound)
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
                        words = text_lower.split()

                        # Regra solicitada: Frase curta (<= 3 palavras) E terminada em "finalizar" ou "encerra"
                        if (
                            len(words) <= 3
                            and words
                            and (
                                words[-1] == "finalizar"
                                or words[-1].startswith("encerra")
                            )
                        ):
                            print(
                                f"\n[PARADA DETECTADA NO FINAL DA FRASE]: '{text_lower}'"
                            )
                            return

                        # Processa comando via filtro e similaridade
                        if text_lower:
                            process_command(text_lower)

            except Exception as e:
                print(f"Erro ao consultar status: {e}")

            # --- B) Checa inatividade de 3 segundos ---
            if not prompted_inactivity and (now - last_speech_time >= 3.0):
                print("\n[INATIVIDADE DETECTADA] Prompting via TTS...")
                speak_tts("Em que posso ajudá-lo, mestre?")
                prompted_inactivity = True

            # --- C) Checa Wakeword para cancelar ---
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
    # Carrega a pasta de comandos na inicialização
    load_commands("comandos")

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
