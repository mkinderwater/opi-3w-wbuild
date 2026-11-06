#!/bin/bash
# Recompile only the probe, retaining pinned runtime assets and a rollback copy.
set -euo pipefail
BASE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DEST=/opt/opi-3w-wbuild-npu
(( EUID == 0 )) || { echo 'Run as root.' >&2; exit 1; }
[[ $(uname -m) == aarch64 && $(uname -r) == 6.6.98-sun60iw2 ]] || { echo 'Need the A733 board running 6.6.98-sun60iw2.' >&2; exit 1; }
exec 9>/run/opi-npu-update.lock
flock -n 9 || { echo 'Another NPU update is running.' >&2; exit 1; }
python3 - "$BASE" "$DEST" <<'PY'
import importlib.util,sys
from pathlib import Path
base,root=map(Path,sys.argv[1:])
spec=importlib.util.spec_from_file_location('npu_test',base/'test.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
module.integrity(root)
PY
WORK=$(mktemp -d /var/tmp/opi-npu-update.XXXXXXXX)
cp -a -- "$DEST" "$WORK/runtime"
cp -- "$BASE/probe.c" "$WORK/probe.c"
dpkg-query -W -f='${binary:Package}\n' | sort > "$WORK/packages-before"
apt-get update
env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends gcc libc6-dev
gcc -std=c11 -D_POSIX_C_SOURCE=200809L -O2 -Wall -Wextra -Werror -Wno-misleading-indentation \
    -I"$WORK/runtime/sdk" "$WORK/probe.c" \
    -L"$WORK/runtime/lib" -Wl,-rpath,'$ORIGIN/../lib' -lNBGlinker -lVIPhal -lm \
    -o "$WORK/runtime/bin/npu-probe"
python3 "$BASE/prepare.py" seal "$WORK/runtime"
env LD_LIBRARY_PATH="$WORK/runtime/lib" ldd "$WORK/runtime/bin/npu-probe" > "$WORK/dependencies.txt"
if grep -q 'not found' "$WORK/dependencies.txt"; then cat "$WORK/dependencies.txt"; exit 1; fi
# Preserve the previous runtime; restore it if the staged rename fails.
mv -- "$DEST" "$WORK/previous-runtime"
if ! mv -- "$WORK/runtime" "$DEST"; then
    mv -- "$WORK/previous-runtime" "$DEST"
    exit 1
fi
install -m755 "$BASE/test.py" /usr/local/sbin/opi-3w-wbuild-npu-test
dpkg-query -W -f='${binary:Package}\n' | sort > "$WORK/packages-after"
mapfile -t ADDED < <(comm -13 "$WORK/packages-before" "$WORK/packages-after")
if (( ${#ADDED[@]} )); then env DEBIAN_FRONTEND=noninteractive apt-get purge -y "${ADDED[@]}"; fi
apt-get clean
echo "NPU probe updated. Previous runtime retained: $WORK/previous-runtime"
echo 'Run as root: opi-3w-wbuild-npu-test'
