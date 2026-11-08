"""Read-only recording classification shared by preview and processing."""
from datetime import datetime, timezone


def waiting_for_metadata(expires, now=None):
    if not isinstance(expires, str):
        return False
    try:
        deadline = datetime.fromisoformat(expires)
    except ValueError:
        return False
    return deadline.tzinfo is not None and deadline > (now or datetime.now(timezone.utc))


def pending_files(files):
    return [file for file in files if file['name'].lower().endswith('.zip') and
            not file['name'].lower().endswith(('-ok.zip', '-ok-omitido.zip')) and
            not waiting_for_metadata((file.get('appProperties') or {}).get('piaMetadataEditableUntil'))]
