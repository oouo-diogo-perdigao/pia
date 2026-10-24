"""Descobre projetos de skills em Plugins/Skills e injeta as APIs da PIA."""
from pathlib import Path
import difflib
import importlib.util
import inspect
import logging
import re
import sys
import tomllib
import types

from .state import COMMAND_ACTIONS
from .skills_runtime import get_runtime, normalize

PLUGIN_ROOT = Path(__file__).resolve().parents[1] / 'Plugins' / 'Skills'
_loaded_packages = set()


def load_commands(folder_name=None):
    """Manifestos plugin.toml; projetos desabilitados ou inválidos não são carregados."""
    actions = {}
    for name in list(sys.modules):
        if any(name == prefix or name.startswith(prefix + '.') for prefix in _loaded_packages):
            sys.modules.pop(name, None)
    _loaded_packages.clear()
    for manifest in sorted(PLUGIN_ROOT.glob('*/plugin.toml')):
        try:
            data = tomllib.loads(manifest.read_text(encoding='utf-8'))
            if not data.get('enabled', True):
                continue
            plugin_id = data['id']
            if not re.fullmatch(r'[a-z][a-z0-9_]*', plugin_id):
                raise ValueError('id inválido: use letras minúsculas, números e underscore')
            names = data['commands']
            if not isinstance(names, list) or not names or any(not isinstance(n, str) or not n.strip() for n in names):
                raise ValueError('commands deve ser uma lista de frases')
            names = [normalize(n).strip() for n in names]
            if len(set(names)) != len(names) or any(n in actions for n in names):
                raise ValueError('Comando duplicado')
            entry = (manifest.parent / data.get('entrypoint', 'plugin.py')).resolve()
            if not entry.is_relative_to(manifest.parent.resolve()) or entry.suffix != '.py':
                raise ValueError('entrypoint deve ser um arquivo Python dentro do projeto')
            package_name = '_pia_skill_' + plugin_id
            if package_name in _loaded_packages:
                raise ValueError('id de skill duplicado')
            package = types.ModuleType(package_name)
            package.__path__ = [str(manifest.parent)]
            sys.modules[package_name] = package
            _loaded_packages.add(package_name)
            spec = importlib.util.spec_from_file_location(package_name + '.plugin', entry)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            if not callable(getattr(module, 'execute', None)) or inspect.iscoroutinefunction(module.execute):
                raise ValueError('É necessária uma função execute síncrona')
            for name in names:
                actions[name] = module.execute
            logging.info('[SKILLS] %s: %s', plugin_id, ', '.join(names))
        except Exception:
            logging.exception('[SKILLS] Projeto inválido: %s', manifest)
    # Somente esta atualização altera o registro usado pelo reconhecedor.
    COMMAND_ACTIONS.clear()
    COMMAND_ACTIONS.update(actions)
    def reload_skill():
        load_commands()
    COMMAND_ACTIONS['recarregar comandos'] = reload_skill
    COMMAND_ACTIONS['recarregar skills'] = reload_skill
    logging.info('[SKILLS] %d frase(s) de ativação disponíveis.', len(COMMAND_ACTIONS))


def process_command(text, fallback):
    text_clean = normalize(text).strip()
    if text_clean == 'comando' or text_clean.startswith('comando '):
        action_text = text_clean[len('comando'):].strip().rstrip('.!?')
        matches = difflib.get_close_matches(action_text, list(COMMAND_ACTIONS), n=1, cutoff=0.6)
        if matches:
            name = matches[0]
            get_runtime().activate(name, COMMAND_ACTIONS[name])
            return True
    fallback(text)
    return False
