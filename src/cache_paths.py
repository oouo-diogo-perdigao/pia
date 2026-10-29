"""Contextual cache locations and conservative migration of known legacy paths."""
from pathlib import Path
import shutil
from .config_paths import BASE_DIR

CACHE=BASE_DIR/'cache'
MAPPING={'.cache':'main/downloads','open-webui_data':'Apps/open_webui/data','stripe-directory.md':'main/integrations/stripe/directory.md','Kokoro-82M':'main/tts/kokoro','ice_images':'main/images/output','comfyui_models':'main/images/models',
         'local_actions':'main/actions','memory':'main/memory','imports':'main/imports','openai_images':'main/images/openai',
         'storage-uploads':'Apps/object_storage/uploads','desktop-preview':'main/desktop/previews',
         'sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01':'main/wakeword/sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01'}

def cache_path(value,default):
    if not value:return CACHE/default
    path=Path(value).expanduser()
    absolute=(BASE_DIR/path).resolve() if not path.is_absolute() else path.resolve()
    if absolute==CACHE.resolve():return CACHE/default
    for old,new in MAPPING.items():
        if absolute==(CACHE/old).resolve():return CACHE/new
    return path

def migrate(root=BASE_DIR):
    cache=Path(root)/'cache'
    for old,new in MAPPING.items():
        source,target=cache/old,cache/new
        if not source.exists() or target.exists() or source.is_symlink():continue
        if not source.resolve().is_relative_to(cache.resolve()) or not target.resolve().is_relative_to(cache.resolve()):continue
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.move(str(source),str(target))
    # Older Whisper wrote one model flat into cache/. Preserve it as a legacy model,
    # without assuming which model it was or mixing its weights with medium.
    for name in ('model.bin','config.json','preprocessor_config.json','tokenizer.json','vocabulary.json'):
        source,target=cache/name,cache/'main/stt/legacy'/name
        if source.is_file() and not target.exists():
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.move(str(source),str(target))
    source,target=Path(root)/'logs/selectedVoices.json',cache/'main/tts/selectedVoices.json'
    if source.is_file() and not target.exists():
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.move(str(source),str(target))
