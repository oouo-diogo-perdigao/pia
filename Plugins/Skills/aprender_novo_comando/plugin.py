"""Cria um scaffold pessoal, sem gerar/executar código sugerido por LLM."""
from pathlib import Path
import re
import unicodedata


def execute(piaSTT, piaTTS):
    piaTTS('Diga o nome da nova skill. Vou criar um projeto de exemplo para você editar.')
    def listen(text):
        name = text.strip(' .!?')
        clean = ''.join(c for c in unicodedata.normalize('NFD', name.lower()) if not unicodedata.combining(c))
        plugin_id = 'pessoal_' + re.sub(r'[^a-z0-9]+', '_', clean).strip('_')
        base = Path(__file__).resolve().parent.parent
        folder = base / plugin_id
        if len(plugin_id) <= len('pessoal_') or folder.exists():
            piaTTS('Nome inválido ou projeto já existente. Diga outro nome.')
            return
        import json
        folder.mkdir()
        (folder / 'plugin.toml').write_text('id = ' + json.dumps(plugin_id) + '\ncommands = [' + json.dumps(name, ensure_ascii=False) + ']\nentrypoint = "plugin.py"\nenabled = true\n', encoding='utf-8')
        (folder / 'plugin.py').write_text('def execute(piaTTS):\n    piaTTS("Sua nova skill está pronta para ser personalizada.")\n', encoding='utf-8')
        (folder / 'pyproject.toml').write_text('[project]\nname = "' + plugin_id.replace('_', '-') + '"\nversion = "0.1.0"\nrequires-python = ">=3.12"\ndependencies = []\n', encoding='utf-8')
        (folder / '.gitignore').write_text('.venv/\n__pycache__/\n.env\n', encoding='utf-8')
        unsubscribe()
        piaTTS('Projeto criado. Edite o plugin e diga comando recarregar skills para ativar.')
    unsubscribe = piaSTT(listen)
