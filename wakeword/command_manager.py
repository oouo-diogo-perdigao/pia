import os
import importlib
import sys

COMMAND_ACTIONS = {}


def load_commands(folder_name="comandos"):
    """
    Varre a pasta de comandos e carrega/recarrega dinamicamente todos os módulos .py.
    """
    global COMMAND_ACTIONS
    COMMAND_ACTIONS.clear()

    # Garante que o diretório atual está no PATH
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())

    if not os.path.exists(folder_name):
        os.makedirs(folder_name)
        print(f"[COMANDOS]: Pasta '{folder_name}' criada.")
        return

    print(f"\n[COMANDOS]: Carregando comandos dinamicamente de '{folder_name}'...")

    for file_name in os.listdir(folder_name):
        if file_name.endswith(".py") and not file_name.startswith("__"):
            module_name = f"{folder_name}.{file_name[:-3]}"

            try:
                # Se o módulo já foi importado antes, força o reload; senão, importa
                if module_name in sys.modules:
                    module = importlib.reload(sys.modules[module_name])
                else:
                    module = importlib.import_module(module_name)

                # Verifica se o arquivo segue o padrão esperado
                if hasattr(module, "COMMAND_NAME") and hasattr(module, "execute"):
                    cmd_name = module.COMMAND_NAME.lower().strip()
                    COMMAND_ACTIONS[cmd_name] = module.execute
                    print(f"  -> Comando carregado: '{cmd_name}' ({file_name})")
                else:
                    print(
                        f"  [ALERTA] Arquivo '{file_name}' ignorado: não possui COMMAND_NAME ou execute()"
                    )

            except Exception as e:
                print(f"  [ERRO] Falha ao carregar '{file_name}': {e}")

    print(f"[COMANDOS]: Total de {len(COMMAND_ACTIONS)} comando(s) ativo(s).\n")
