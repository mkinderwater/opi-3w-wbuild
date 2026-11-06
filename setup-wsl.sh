#!/bin/bash
set -euo pipefail
export LC_ALL=C
export LANG=C
BASE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if (( EUID != 0 )); then echo 'Run with sudo inside WSL2 Ubuntu or Debian.' >&2; exit 1; fi
apt-get update
apt-get install -y debootstrap debian-archive-keyring rsync qemu-user-static binfmt-support \
    util-linux fdisk e2fsprogs dosfstools mtools u-boot-tools \
    device-tree-compiler kmod python3 gzip xz-utils zstd ca-certificates git
mkdir -p /proc/sys/fs/binfmt_misc
if ! mountpoint -q /proc/sys/fs/binfmt_misc; then
    mount -t binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc
fi
python3 "$BASE/scripts/enable-arm64.py"
