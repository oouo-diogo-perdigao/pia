"""Move legacy podcast integration settings without logging secret values."""
from pathlib import Path
import shutil
from dotenv import dotenv_values,set_key,unset_key
from .config_paths import BASE_DIR
from .env_types import split_key, dotenv_values as normalized_values

def migrate(root=BASE_DIR):
    root=Path(root)
    migrate_connectors(root)
    app=root/'Plugins/Apps/podcast_automation'
    source=app/'.env'
    if not source.exists():return
    values=dotenv_values(source)
    for prefix,plugin in [('OBJECT_STORAGE_','object_storage'),('GOOGLE_','google'),('DISCORD_','discord')]:
        target=root/'Plugins/Connectors'/plugin/'.env'
        target.parent.mkdir(parents=True,exist_ok=True)
        existing=normalized_values(target) if target.exists() else {}
        for name,value in values.items():
            if not name.startswith(prefix):continue
            base,_=split_key(name)
            if base=='GOOGLE_APPLICATION_CREDENTIALS' and value:
                credential=Path(value)
                if not credential.is_absolute():credential=app/credential
                if credential.is_file():
                    destination=target.parent/'secrets/service-account.json'
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    if not destination.exists():shutil.copy2(credential,destination)
                    value=str(destination.resolve())
            if existing.get(base) and existing[base]!=value:
                # Retain conflicts rather than silently replace configured credentials.
                continue
            set_key(target,name,value or '',quote_mode='always')
            unset_key(source,name)
        if target.exists():target.chmod(0o600)
    for name in values:
        if name.startswith(('LLM_','PIA_','WHISPER_')) or name in ('TRANSCRIPTION_PROVIDER','HF_HOME'):
            unset_key(source,name)


def migrate_connectors(root):
    """Preserve ignored local configuration when upgrading the tracked folder name."""
    root=Path(root)
    old,new=root/'Plugins/Plugins',root/'Plugins/Connectors'
    if not old.is_dir():return
    for file in old.rglob('*'):
        if not file.is_file() or file.is_symlink() or any(p in ('__pycache__','.venv') for p in file.parts):continue
        relative=file.relative_to(old)
        if file.name not in ('.env','config.json','accounts.json') and not any(p in ('secrets','files') for p in relative.parts):continue
        target=new/relative
        if not target.exists():
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(file,target)
            target.chmod(0o600)
        if target.exists():target.chmod(0o600)
