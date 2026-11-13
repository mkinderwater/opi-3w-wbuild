#!/bin/bash
set -euo pipefail
export LC_ALL=C
export LANG=C
SOURCE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DEFAULT_INPUT=$SOURCE/inputs/zero3w-hardware.tar.gz
[[ -f $DEFAULT_INPUT ]] || DEFAULT_INPUT=$SOURCE/inputs/vendor.img
DONOR=${1:-$DEFAULT_INPUT}
SIZE=${2:-2048}
EXTRACT_ONLY=${3:-0}
NAME=opi-3w-wbuild-0.7.6.img.gz
[[ $# -le 3 && $SIZE =~ ^[0-9]+$ ]] || { echo 'Usage: windows-entry.sh [donor.img] [size-MiB]' >&2; exit 2; }
[[ -f $DONOR && ! -b $DONOR ]] || { echo 'Put your uncompressed, working A733 Zero 3W 1 GB SD image at inputs/vendor.img.' >&2; exit 1; }
[[ $EXTRACT_ONLY == 1 ]] || [[ ! -e $SOURCE/out/$NAME && ! -L $SOURCE/out/$NAME && ! -e $SOURCE/out/$NAME.sha256 && ! -L $SOURCE/out/$NAME.sha256 ]] || {
    echo 'Output already exists. Move the previous image and checksum out of out/ before rebuilding.' >&2; exit 1;
}
if ! grep -Eqi 'microsoft-standard|WSL2' /proc/sys/kernel/osrelease; then
    echo 'Use Debian or Ubuntu under WSL2.' >&2; exit 1
fi
[[ $HOME != /mnt/* ]] || { echo 'WSL home must be inside the Linux filesystem.' >&2; exit 1; }
mkdir -p "$HOME/opi-3w-wbuild" "$SOURCE/out"
DEST=$(mktemp -d "$HOME/opi-3w-wbuild/build-0.7.6-XXXXXXXX")
# Log setup, inspection, build and export. Keep the log even after a failed build.
exec > >(tee "$DEST/build.log") 2>&1
finish() {
    result=$?
    trap - EXIT
    echo "Linux workspace retained: $DEST"
    if (( result != 0 )); then echo 'Build failed. Review out/build.log before retrying.'; fi
    exec 1>&- 2>&-
    wait || true
    cp -- "$DEST/build.log" "$SOURCE/out/build.log" || true
    exit "$result"
}
trap finish EXIT
printf 'Fresh WSL workspace: %s\n' "$DEST"
mkdir "$DEST/source"
# Stage code separately from cached hardware and old output images.
tar -C "$SOURCE" --exclude='./out' --exclude='./inputs' --exclude='__pycache__' -cf - . | tar -C "$DEST/source" -xf -
mkdir -p "$DEST/source/inputs"
if [[ -f $SOURCE/inputs/kernel-headers.deb ]]; then cp -- "$SOURCE/inputs/kernel-headers.deb" "$DEST/source/inputs/"; fi
cd "$DEST/source"
sudo bash ./setup-wsl.sh
if [[ $DONOR == *.tar.gz ]]; then
    cp -- "$DONOR" "$DEST/hardware.tar.gz"
else
    [[ ! -e $SOURCE/inputs/zero3w-hardware.tar.gz ]] || { echo 'Hardware cache already exists. Use it or move it before extracting another donor.' >&2; exit 1; }
    cp --reflink=auto --sparse=always -- "$DONOR" "$DEST/donor.img"
    sudo bash ./extract-hardware.sh "$DEST/donor.img" "$DEST/hardware.tar.gz"
    sudo chown -- "$(id -u):$(id -g)" "$DEST/hardware.tar.gz"
    (set -C; cat "$DEST/hardware.tar.gz" > "$SOURCE/inputs/zero3w-hardware.tar.gz")
    (cd "$SOURCE/inputs"; sha256sum zero3w-hardware.tar.gz > zero3w-hardware.tar.gz.sha256)
    rm -- "$DEST/donor.img"
fi
if [[ $EXTRACT_ONLY == 1 ]]; then
    sudo python3 ./scripts/hardware_bundle.py unpack "$DEST/hardware.tar.gz" "$DEST/checked-hardware"
    echo 'Hardware bundle ready. Future builds need only inputs/zero3w-hardware.tar.gz.'
    exit 0
fi
sudo bash ./build.sh "$DEST/hardware.tar.gz" "$DEST/opi-3w-wbuild.img" "$SIZE"
# The root builder creates a private root-owned image; hand only its outputs
# back to the invoking WSL user before unprivileged compression/export.
sudo chown -- "$(id -u):$(id -g)" "$DEST/opi-3w-wbuild.img" "$DEST/opi-3w-wbuild.img.sha256"
gzip -c "$DEST/opi-3w-wbuild.img" > "$DEST/$NAME"
(cd "$DEST"; sha256sum "$NAME" > "$NAME.sha256")
# noclobber protects outputs if a second launcher was started at the same time.
(set -C; cat "$DEST/$NAME" > "$SOURCE/out/$NAME")
(set -C; cat "$DEST/$NAME.sha256" > "$SOURCE/out/$NAME.sha256")
printf 'Windows output folder: %s/out\n' "$SOURCE"
