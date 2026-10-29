"""Screenshot app API. No email, network upload or background capture."""
import json
from pathlib import Path
from src.resource_plugins import save_json

ROOT = Path(__file__).resolve().parent
DEFAULTS = {'format': 'png', 'quality': 92, 'prefill_title': True, 'prefill_url': False,
            'border': False, 'output_folder': '', 'auto_save': True, 'auto_copy': True}


def config():
    path = ROOT / 'config.json'
    return {**DEFAULTS, **(json.loads(path.read_text(encoding='utf-8')) if path.exists() else {})}


def handle(action, data, context):
    if action == 'config':
        return config()
    if action == 'save-config':
        value = {**config(), **data['value']}
        if value['format'] not in ('png', 'jpg', 'bmp') or not 1 <= int(value['quality']) <= 100:
            raise ValueError('Formato ou qualidade inválidos.')
        for key in ('prefill_title', 'prefill_url', 'border', 'auto_save', 'auto_copy'):
            if not isinstance(value[key], bool):
                raise ValueError('Preferência inválida.')
        save_json(ROOT / 'config.json', {k: value[k] for k in DEFAULTS})
        return {'ok': True}
    if action == 'status' and context.native_handler is None:
        return {'available': False, 'captures': []}
    allowed = {'status', 'capture', 'image', 'cancel', 'copy', 'save',
               'desktop', 'drag', 'print', 'edit', 'color', 'finalize', 'choose-folder', 'saved-image', 'list-saved', 'delete-saved', 'open-saved', 'copy-saved'}
    if action not in allowed:
        raise ValueError('Operação de captura desconhecida.')
    return context.native('app', {'id': 'screenshots', 'action': action, 'payload': data})
