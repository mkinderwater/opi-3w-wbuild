#!/usr/bin/env python3
"""Import donor hardware files using donor-root symlink semantics."""
import argparse
from collections import deque
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat


class Donor:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)

    def resolve(self, name):
        # Never use Path.resolve() on a donor link: /etc/foo means donor /etc/foo.
        pending = deque(PurePosixPath(name).parts)
        parts = []
        links = 0
        while pending:
            item = pending.popleft()
            if item in ('', '.', '/'): continue
            if item == '..':
                if parts: parts.pop()
                continue
            candidate = self.root.joinpath(*parts, item)
            mode = candidate.lstat().st_mode
            if stat.S_ISLNK(mode):
                links += 1
                if links > 40: raise ValueError('Donor symlink loop: ' + str(name))
                target = PurePosixPath(os.readlink(candidate))
                if target.is_absolute(): parts = []
                pending.extendleft(reversed(target.parts))
            else:
                parts.append(item)
                if pending and not stat.S_ISDIR(mode):
                    raise ValueError('Donor path crosses a non-directory: ' + str(name))
        return self.root.joinpath(*parts)

    def copy(self, name, destination, modules=False):
        destination = Path(destination)
        def visit(logical, output, ancestors, relative):
            source = self.resolve(logical)
            mode = source.lstat().st_mode
            if stat.S_ISDIR(mode):
                if source in ancestors: raise ValueError('Donor directory link cycle: ' + str(logical))
                output.mkdir(parents=True, exist_ok=True)
                for child in sorted(source.iterdir()):
                    child_relative = relative / child.name
                    if modules and len(child_relative.parts) == 2 and child.name in ('build','source'):
                        continue  # Kernel development links are not runtime inputs.
                    visit(PurePosixPath(logical)/child.name, output/child.name, ancestors | {source}, child_relative)
                shutil.copystat(source, output)
            elif stat.S_ISREG(mode):
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, output)
            else:
                raise ValueError('Unsupported donor special file: ' + str(logical))
        visit(PurePosixPath(name), destination, set(), PurePosixPath())


def stage(donor, output):
    donor = Donor(donor)
    output = Path(output)
    if output.exists(): raise ValueError('Hardware staging output already exists')
    output.mkdir()
    imported = []
    firmware_seen = set()
    trees = [('lib/modules','lib/modules'),
             ('lib/firmware','usr/lib/firmware'),('usr/lib/firmware','usr/lib/firmware'),
             ('vendor/etc/firmware','vendor/etc/firmware'),('etc/firmware','etc/firmware'),
             ('etc/modules-load.d','etc/modules-load.d'),('etc/modprobe.d','etc/modprobe.d'),
             ('etc/modules','etc/modules')]
    for source, target in trees:
        try: canonical = donor.resolve(source)
        except FileNotFoundError:
            if source=='lib/modules': raise
            continue
        if 'firmware' in source:
            if canonical in firmware_seen: continue
            firmware_seen.add(canonical)
        donor.copy(source, output/target, modules=(source=='lib/modules'))
        imported.append(source)
    (output/'hardware-import.json').write_text(json.dumps({'imported':imported,'symlinks':'dereferenced inside donor root'},indent=2)+'\n')


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('donor');parser.add_argument('output')
    args=parser.parse_args()
    try: stage(args.donor,args.output)
    except (OSError,ValueError) as error:
        parser.exit(1, 'Donor hardware import failed: '+str(error)+'\n')
