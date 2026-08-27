# comandos/aprender.py
import os

COMMAND_NAME = "aprender novo comando"


def execute():
    """Exemplo de função local para registrar um novo aprendizado dinâmico."""
    print("\n[APRENDER]: Modo de aprendizado ativado.")

    # Nome da nova ação/comando
    novo_nome = "ligar luzes"

    # Código Python a ser gerado
    conteudo_script = f"""COMMAND_NAME = "{novo_nome}"

def execute():
    print("[EXECUÇÃO]: Luzes ligadas com sucesso!")
"""

    caminho_arquivo = os.path.join("comandos", f"{novo_nome.replace(' ', '_')}.py")

    with open(caminho_arquivo, "w", encoding="utf-8") as f:
        f.write(conteudo_script)

    print(f"[APRENDER]: Novo comando salvo em '{caminho_arquivo}'.")
    print("[APRENDER]: Recarregando a lista de comandos...")

    # Dispara o comando interno do wakeword para reler a pasta sem reiniciar a aplicação
    import requests

    try:
        # Chama a ação embutida diretamente
        from __main__ import COMMAND_ACTIONS

        if "recarregar comandos" in COMMAND_ACTIONS:
            COMMAND_ACTIONS["recarregar comandos"]()
    except Exception as e:
        print(f"[APRENDER ERRO]: {e}")
