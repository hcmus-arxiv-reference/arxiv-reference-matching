"""Validated IDs and atomic JSON checkpoints."""
import json, os, re, tempfile
from pathlib import Path

def require_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:\d{4}\.\d{4,5}|[A-Za-z][A-Za-z0-9.\-]*/\d{7})', value):
        raise ValueError('Invalid arXiv base ID')
    return value

def key(value):
    return require_id(value).replace('/', '-').replace('.', '-')

def write_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.tmp-')
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as f:
            json.dump(value, f, ensure_ascii=False, indent=2); f.flush(); os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)

def read_json(path):
    try: return json.loads(Path(path).read_text(encoding='utf8'))
    except (OSError, ValueError): return None
