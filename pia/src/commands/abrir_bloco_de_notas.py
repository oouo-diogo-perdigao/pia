import os

COMMAND_NAME = "abrir bloco de notas"


def execute():
    print("[AÇÃO]: Abrindo Bloco de Notas...")
    os.system("notepad.exe")
