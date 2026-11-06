#!/bin/bash
# Install into a fresh chroot or onto the running A733 board.
set -euo pipefail
BASE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
R=$(realpath -- "${1:-/}")
(( EUID == 0 )) || { echo 'Run as root.' >&2; exit 1; }
[[ -d $R/etc && -d $R/usr ]] || { echo 'Need an installed Linux root.' >&2; exit 1; }
if [[ $R == / && $(uname -m) != aarch64 ]]; then echo 'Run this installer on the A733 board, or supply the ARM64 chroot root.' >&2; exit 1; fi
if [[ $R == / && $(uname -r) != 6.6.98-sun60iw2 ]]; then echo 'Need kernel 6.6.98-sun60iw2.' >&2; exit 1; fi
DEST=${R%/}/opt/opi-3w-wbuild-npu
[[ ! -e $DEST && ! -L $DEST ]] || { echo 'NPU runtime already exists. Use opi-3w-wbuild-npu-test, or move the old runtime before reinstalling.' >&2; exit 1; }
run_root(){ if [[ $R == / ]]; then "$@"; else chroot "$R" "$@"; fi; }
WORK=$(mktemp -d "${R%/}/var/tmp/opi-npu-build.XXXXXXXX")
TARGET_WORK=$WORK
[[ $R == / ]] || TARGET_WORK=${WORK#"$R"}
run_root apt-get update
run_root env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3 ca-certificates kmod
run_root dpkg-query -W -f='${binary:Package}\n' | sort > "$WORK/packages-before"
run_root env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends gcc libc6-dev
python3 "$BASE/prepare.py" prepare "$WORK/runtime"
cp "$BASE/probe.c" "$WORK/probe.c"
run_root gcc -std=c11 -D_POSIX_C_SOURCE=200809L -O2 -Wall -Wextra -Werror -Wno-misleading-indentation \
    -I"$TARGET_WORK/runtime/sdk" "$TARGET_WORK/probe.c" \
    -L"$TARGET_WORK/runtime/lib" -Wl,-rpath,'$ORIGIN/../lib' -lNBGlinker -lVIPhal -lm \
    -o "$TARGET_WORK/runtime/bin/npu-probe"
python3 "$BASE/prepare.py" seal "$WORK/runtime"
# Check native dependencies only. Do not initialize hardware during installation.
run_root env LD_LIBRARY_PATH="$TARGET_WORK/runtime/lib" ldd "$TARGET_WORK/runtime/bin/npu-probe" > "$WORK/dependencies.txt"
if grep -q 'not found' "$WORK/dependencies.txt"; then cat "$WORK/dependencies.txt"; exit 1; fi
mkdir -p "${R%/}/opt" "${R%/}/usr/local/sbin"
mv -- "$WORK/runtime" "$DEST"
install -m755 "$BASE/test.py" "${R%/}/usr/local/sbin/opi-3w-wbuild-npu-test"
run_root dpkg-query -W -f='${binary:Package}\n' | sort > "$WORK/packages-after"
mapfile -t ADDED < <(comm -13 "$WORK/packages-before" "$WORK/packages-after")
if (( ${#ADDED[@]} )); then run_root env DEBIAN_FRONTEND=noninteractive apt-get purge -y "${ADDED[@]}"; fi
run_root apt-get clean
echo 'NPU candidate runtime installed. No NPU inference has been run.'
echo 'Run as root: opi-3w-wbuild-npu-test'
echo "Build diagnostics retained: $WORK"
