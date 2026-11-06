"""Atomic private files and secret-free boot milestones shared by setup and expansion."""
import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone

def atomic(path, text, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'w') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def write_status(stage, detail='', root=Path('/'), mounted=os.path.ismount):
    config = root / 'config'
    if not mounted(config):
        raise RuntimeError('Configuration partition is not mounted')
    state = root / 'var/lib/opi-3w-wbuild'
    boot_id = (root / 'proc/sys/kernel/random/boot_id').read_text().strip()
    now = datetime.now(timezone.utc).isoformat()
    history_file = state / 'boot-stages.json'
    history = []
    if history_file.exists():
        try:
            previous = json.loads(history_file.read_text())
            if previous.get('boot_id') == boot_id: history = previous['stages'][-15:]
        except (ValueError, KeyError, TypeError): pass
    history.append(dict(time=now, stage=stage, detail=detail))
    atomic(history_file, json.dumps(dict(boot_id=boot_id,stages=history),indent=2)+'\n')
    text = 'opi-3w-wbuild 0.7.5 boot\nBoot ID: ' + boot_id + '\n'
    text += '\n'.join(item['time']+' '+item['stage']+(' '+item['detail'] if item['detail'] else '') for item in history)+'\n'
    atomic(config / 'BOOT-STATUS.TXT', text)

