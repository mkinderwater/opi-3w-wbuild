#!/bin/bash
# Read the original donor once. Never modify it.
set -euo pipefail
BASE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
(( EUID == 0 && $# == 2 )) || { echo 'Usage: sudo bash extract-hardware.sh DONOR.img NEW-HARDWARE.tar.gz' >&2; exit 2; }
DONOR=$(realpath -- "$1")
OUTPUT=$(realpath -m -- "$2")
[[ ! -e $OUTPUT && ! -L $OUTPUT ]] || { echo 'Output exists.' >&2; exit 1; }
WORK=$(mktemp -d /var/tmp/opi-hardware.XXXXXXXX)
LOOP=''
cleanup() {
    set +e
    mountpoint -q "$WORK/donor" && umount "$WORK/donor"
    [[ -z $LOOP ]] || losetup -d "$LOOP"
    echo "Extraction workspace retained: $WORK"
}
trap cleanup EXIT
python3 "$BASE/scripts/image_layout.py" inspect "$DONOR" > "$WORK/layout.json"
read -r OFFSET LENGTH < <(python3 - "$WORK/layout.json" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]))['partitions'][0];print(p['start']*512,p['sectors']*512)
PY
)
mkdir "$WORK/donor"
LOOP=$(losetup --find --show --read-only --offset "$OFFSET" --sizelimit "$LENGTH" "$DONOR")
mount -t ext4 -o ro,noload "$LOOP" "$WORK/donor"
HEADERS=()
[[ ! -f $BASE/inputs/kernel-headers.deb ]] || HEADERS=(--headers "$BASE/inputs/kernel-headers.deb")
python3 "$BASE/scripts/hardware_bundle.py" create "$DONOR" "$WORK/donor" "$WORK/payload" "${HEADERS[@]}"
python3 "$BASE/scripts/powervr.py" preflight "$WORK/payload/root" "$WORK/payload/root" "$BASE/inputs" "$BASE/gpu/pins.json"
python3 "$BASE/scripts/hardware_bundle.py" pack "$WORK/payload" "$OUTPUT"
sha256sum "$OUTPUT"
echo 'Hardware bundle created. The original vendor image was left unchanged.'
