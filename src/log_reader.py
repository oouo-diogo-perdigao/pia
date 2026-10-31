"""Bounded initial tail and incremental byte cursors, with rotation detection."""
from pathlib import Path
from src.config_paths import BASE_DIR

def log_path(name):
    root=(BASE_DIR/'logs').resolve()
    if not isinstance(name,str) or '..' in Path(name).parts or Path(name).is_absolute() or not name.endswith('.log'):
        raise ValueError('Log inválido.')
    path=(root/name).resolve()
    if not path.is_relative_to(root) or not path.is_file():raise ValueError('Log não encontrado.')
    return path

def read_log(name,cursor=None,identity=None):
    path=log_path(name)
    with path.open('rb') as stream:
        import os
        stat=os.fstat(stream.fileno())
        tag=f'{stat.st_dev}:{stat.st_ino}'
        initial=cursor is None or identity!=tag or not isinstance(cursor,int) or cursor<0 or cursor>stat.st_size
        if initial:
            # Walk backwards only until we have the last 100 lines.
            position=stat.st_size;chunks=[];newlines=0
            while position>0 and newlines<=100:
                count=min(8192,position);position-=count;stream.seek(position)
                part=stream.read(count);chunks.append(part);newlines+=part.count(b'\n')
            raw=b''.join(reversed(chunks))
            text=b'\n'.join(raw.splitlines()[-100:]).decode('utf-8',errors='replace')
            if raw.endswith(b'\n') and text:text+='\n'
            end=stat.st_size
        else:
            stream.seek(cursor)
            raw=stream.read(256*1024)
            # Keep incomplete UTF-8 suffix for the next request.
            try:text=raw.decode('utf-8')
            except UnicodeDecodeError as exc:
                if exc.reason=='unexpected end of data':raw=raw[:exc.start]
                text=raw.decode('utf-8',errors='replace')
            end=cursor+len(raw)
    parts=Path(name).parts
    category=parts[1] if len(parts)>2 and parts[0]=='plugins' else 'Main'
    return {'name':name,'category':category,'text':text,'cursor':end,'identity':tag,'reset':initial}
