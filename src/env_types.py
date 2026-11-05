"""Settings type validation and legacy-file parsing for one-time migration only."""
import math
from pathlib import Path
import re
from dotenv import dotenv_values as raw_values

TYPES = {'bool', 'int', 'float', 'path', 'file', 'secret', 'string'}

def split_key(name):
    base, separator, kind = name.rpartition('__')
    return (base, kind.lower()) if separator and kind.lower() in TYPES else (name, 'string')

def validate(name, value):
    if not isinstance(value, str) or '\x00' in value:
        raise ValueError(f'{name}: valor inválido.')
    if not value:
        return value
    kind = split_key(name)[1]
    try:
        if kind == 'bool' and value not in ('true', 'false'):
            raise ValueError()
        if kind == 'int' and not re.fullmatch(r'[+-]?\d+', value):
            raise ValueError()
        if kind == 'float' and not math.isfinite(float(value)):
            raise ValueError()
        if kind == 'path' and not Path(value).expanduser().exists():
            raise ValueError()
        if kind == 'file' and not Path(value).expanduser().is_file():
            raise ValueError()
    except (ValueError, OSError):
        raise ValueError(f'{name}: esperado {kind}.') from None
    return value

def dotenv_values(path, **kwargs):
    values = raw_values(path, **kwargs)
    result = {k: v for k, v in values.items() if split_key(k)[0] == k}
    for key, value in values.items():
        base, kind = split_key(key)
        if base != key:
            result[base] = (value or '') if kind in ('path', 'file') else validate(key, value or '')
    return result


def fields(example, current):
    defaults, values = raw_values(example), raw_values(current)
    names = {split_key(k)[0]: k for k in defaults}
    for key in values:
        base, kind = split_key(key)
        if base not in names or kind != 'string':
            names[base] = key
    result=[]
    for base,key in names.items():
        value=values.get(key,values.get(base,defaults.get(key))) or ''
        if split_key(key)[1]=='bool' and value:
            value='true' if value.lower() in ('1','true','yes','on','sim') else 'false' if value.lower() in ('0','false','no','off','nao','não') else value
        result.append((key,value))
    return result
