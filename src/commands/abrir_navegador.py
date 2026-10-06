import webbrowser

COMMAND_NAME = "abrir navegador"


def execute():
    print("[AÇÃO]: Abrindo navegador no Google...")
    webbrowser.open("https://www.google.com")
