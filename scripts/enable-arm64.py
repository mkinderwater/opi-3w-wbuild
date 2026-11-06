#!/usr/bin/env python3
"""Enable packaged ARM64 binfmt rules without assuming an update-binfmts database."""
from pathlib import Path
import re
import subprocess


def ready(entry):
    try:
        text = entry.read_text()
    except FileNotFoundError:
        return False
    flags = re.search(r'^flags:\s*(\S+)', text, re.M)
    return text.startswith('enabled\n') and bool(flags and 'F' in flags[1])


def enable(root=Path('/'), run=subprocess.run):
    entry = root / 'proc/sys/fs/binfmt_misc/qemu-aarch64'
    # WSL distributions share kernel registrations. A working F handler needs
    # no update-binfmts database entry in this particular distribution.
    if not ready(entry):
        config = root / 'usr/lib/binfmt.d/qemu-aarch64.conf'
        loader = root / 'usr/lib/systemd/systemd-binfmt'
        if config.is_file() and loader.is_file():
            # Invoke the loader directly; no running systemd service is needed.
            run([str(loader), str(config)], check=True)
        elif (root / 'usr/share/binfmts/qemu-aarch64').is_file():
            run(['update-binfmts', '--import', 'qemu-aarch64'], check=True)
            run(['update-binfmts', '--enable', 'qemu-aarch64'], check=True)
        else:
            raise RuntimeError('No packaged ARM64 binfmt definition/loader found; reinstall QEMU binfmt packages.')
    if not ready(entry):
        raise RuntimeError('ARM64 emulation needs an enabled binfmt handler with fix-binary (F).')
    print('ARM64 build emulation enabled')


if __name__ == '__main__':
    try:
        enable()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error))
