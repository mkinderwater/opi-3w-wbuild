#!/usr/bin/env python3
"""Record and compare every vendor /boot file and symlink without rewriting it."""
import argparse
import hashlib
import json
from pathlib import Path
import os
import stat


def snapshot(root):
    root = Path(root)
    if (root/'boot').is_symlink() or not (root/'boot').is_dir():
        raise ValueError('Expected a real /boot directory inside donor root')
    result = {}
    def visit(path):
        mode = path.lstat().st_mode
        name = str(path.relative_to(root))
        if stat.S_ISLNK(mode): result[name] = {'link':os.readlink(path)}
        elif stat.S_ISDIR(mode):
            for child in sorted(path.iterdir()): visit(child)
        elif stat.S_ISREG(mode):
            h=hashlib.sha256()
            with path.open('rb') as source:
                for block in iter(lambda:source.read(1024*1024),b''): h.update(block)
            result[name]={'sha256':h.hexdigest()}
        else: raise ValueError('Unsupported boot entry: '+name)
    visit(root/'boot')
    if not result: raise ValueError('Empty donor /boot')
    return result


def verify(root, expected):
    actual = snapshot(root)
    if actual != expected:
        changed = sorted(k for k in set(actual)|set(expected) if actual.get(k)!=expected.get(k))
        raise ValueError('Vendor /boot changed: '+', '.join(changed))


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=('record','verify'));p.add_argument('root');p.add_argument('manifest')
    a=p.parse_args()
    if a.command=='record':Path(a.manifest).write_text(json.dumps(snapshot(a.root),indent=2)+'\n')
    else:verify(a.root,json.loads(Path(a.manifest).read_text()))
