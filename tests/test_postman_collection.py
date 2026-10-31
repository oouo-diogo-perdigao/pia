"""Offline catalogue checks: method/auth boundaries and absence of phantom routes."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pia_postman_generator', ROOT / 'postman/generate_collection.py')
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


def test_catalogue_matches_generated_artifact_and_real_dispatch():
    collection = generator.build()
    assert collection == json.loads(generator.OUT.read_text(encoding='utf-8'))
    requests = [item['request'] for folder in collection['item'] for item in folder['item']]
    routes = {(r['method'], r['url'].split('?')[0].removeprefix('{{base_url}}')) for r in requests}
    assert ('POST', '/protocols/mcp') in routes
    assert ('POST', '/action/camera') in routes
    assert ('GET', '/v1/audio/transcriptions/progress/{{transcription_id}}') in routes
    assert ('POST', '/api/pia/apps/podcast_automation/start') in routes
    assert ('POST', '/api/pia/apps/podcast_automation/google_account') not in routes
    assert not any('/protocols/acp' in path or '/protocols/a2a' in path for _, path in routes)
    for request in requests:
        if '/api/pia/' in request['url']:
            assert request['auth']['type'] == 'noauth'
            assert {'key': 'Origin', 'value': '{{base_url}}'} in request['header']
    formats = set()
    for request in requests:
        if request['url'] == '{{base_url}}/v1/audio/transcriptions':
            assert not any(h['key'] == 'Content-Type' for h in request['header'])
            formats.add(next(f['value'] for f in request['body']['formdata'] if f['key'] == 'response_format'))
    assert formats == {'json', 'text', 'verbose_json', 'srt', 'vtt'}
    assert next(v for v in collection['variable'] if v['key'] == 'api_key')['value'] == ''
