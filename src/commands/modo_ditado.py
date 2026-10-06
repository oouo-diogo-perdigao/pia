import pyautogui
import requests
from src.utils import speak_tts
from src.config import PUBLIC_BASE_URL

COMMAND_NAME = "modo ditado"

# Flags de estado global da sessão
dictation_active = False
last_typed_text = ""


def execute():
    global dictation_active, last_typed_text
    dictation_active = True
    last_typed_text = ""
    print("\n[MODO DITADO]: Ativado!")
    speak_tts("Modo ditado habilitado!")


def disable_dictation():
    global dictation_active
    dictation_active = False
    print("\n[MODO DITADO]: Desativado!")
    speak_tts("Modo ditado desabilitado!")


def process_dictation_chunk(text: str) -> bool:
    """
    Processa o texto capturado pelo SAT enquanto o Modo Ditado estiver ativo.
    Retorna True se o modo ditado interceptou e processou a entrada.
    """
    global dictation_active, last_typed_text

    if not dictation_active:
        return False

    text_clean = text.lower().strip()

    # --- Comando de Encerramento ---
    if "encerrar modo ditado" in text_clean or "desativar modo ditado" in text_clean:
        disable_dictation()
        return True

    # --- Tratamento de Comandos Específicos de Ação ---
    if text_clean in ["apagar", "deletar"]:
        if last_typed_text:
            # Apaga exatamente o número de caracteres digitados na última iteração
            pyautogui.press("backspace", presses=len(last_typed_text))
            last_typed_text = ""
            print("[DITADO - AÇÃO]: ÚLTIMA INSERÇÃO APAGADA")
        return True

    elif text_clean in ["enviar", "enter"]:
        pyautogui.press("enter")
        last_typed_text = ""
        print("[DITADO - AÇÃO]: ENTER ENVIADO")
        return True

    elif text_clean in ["selecionar tudo", "selecionar todo"]:
        pyautogui.hotkey("ctrl", "a")
        print("[DITADO - AÇÃO]: SELECIONAR TUDO EXECUTADO")
        return True

    elif text_clean in ["copiar"]:
        pyautogui.hotkey("ctrl", "c")
        print("[DITADO - AÇÃO]: COPIAR EXECUTADO")
        return True

    elif text_clean in ["colar"]:
        pyautogui.hotkey("ctrl", "v")
        print("[DITADO - AÇÃO]: COLAR EXECUTADO")
        return True

    # --- Inserção do Texto via LocalActions HTTP API ---
    if text.strip():
        value = text.strip() + " "
        response = requests.post(
            f"{PUBLIC_BASE_URL}/action/text-at-cursor",
            json={"text": value},
            timeout=2.0,
        )
        response.raise_for_status()

        # Armazena o que foi inserido para permitir a ação 'apagar' na próxima iteração
        last_typed_text = value
        print(f"[DITADO - INSERIDO]: '{last_typed_text}'")

    return True
