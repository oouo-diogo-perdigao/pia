"""Read-only recording classification shared by preview and processing."""
def pending_files(files):
    return [file for file in files if file['name'].lower().endswith('.zip') and
            not file['name'].lower().endswith(('-ok.zip','-ok-omitido.zip'))]
