"""Dynamic command loader and local command processing (src)."""

from pathlib import Path
import importlib
import logging
import sys
from typing import Callable

from .state import COMMAND_ACTIONS


def load_commands(folder_name: str = "commands") -> None:
    """Load or reload python modules in the commands folder.

    The loader looks for a module-level COMMAND_NAME and execute() callable.
    """
    COMMAND_ACTIONS.clear()

    # Define a pasta com base no diretório do arquivo atual ou cwd
    base_path = Path(__file__).resolve().parent
    folder = base_path / folder_name

    if not folder.exists():
        folder = Path(folder_name)
        folder.mkdir(exist_ok=True)

    if base_path.as_posix() not in sys.path:
        sys.path.insert(0, base_path.as_posix())

    logging.info(f"[COMANDOS] Carregando comandos dinamicamente de '{folder}'...")

    for file in folder.iterdir():
        if file.suffix == ".py" and not file.name.startswith("__"):
            module_name = f"{folder_name}.{file.stem}"
            try:
                if module_name in sys.modules:
                    module = importlib.reload(sys.modules[module_name])
                else:
                    module = importlib.import_module(module_name)

                if hasattr(module, "COMMAND_NAME") and hasattr(module, "execute"):
                    cmd_name = getattr(module, "COMMAND_NAME").lower().strip()
                    COMMAND_ACTIONS[cmd_name] = getattr(module, "execute")
                    logging.info(f" -> Comando carregado: '{cmd_name}' ({file.name})")
                else:
                    logging.warning(
                        f" -> Ignorado '{file.name}': falta COMMAND_NAME ou execute()"
                    )
            except Exception as e:
                logging.error(f" -> Falha ao carregar '{file.name}': {e}")

    # utility command to reload
    COMMAND_ACTIONS["recarregar comandos"] = lambda: load_commands(folder_name)
    logging.info(f"[COMANDOS] Total de {len(COMMAND_ACTIONS)} comando(s) ativo(s).")


def process_command(text: str, fallback: Callable[[str], None]) -> None:
    """Process a command text: run local commands if it begins with 'comando', otherwise call fallback.

    Args:
        text: The recognized text.
        fallback: Callable to call when command is not local (e.g., send to agent).
    """
    text_clean = text.lower().strip()

    if "comando" in text_clean:
        action_text = text_clean.replace("comando", "").strip()
        logging.info(f"[COMANDO LOCAL DETECTADO]: '{action_text}'")

        best_match = None
        best_ratio = 0.0
        import difflib

        cutoff = 0.6
        for target_cmd in COMMAND_ACTIONS.keys():
            ratio = difflib.SequenceMatcher(None, action_text, target_cmd).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = target_cmd

        if best_match and best_ratio >= cutoff:
            logging.info(
                f"-> Executando comando ({best_ratio*100:.1f}%): '{best_match}'"
            )
            COMMAND_ACTIONS[best_match]()
            return
        else:
            logging.info("-> Comando local não reconhecido. Repassando ao Agent...")

    fallback(text_clean)
