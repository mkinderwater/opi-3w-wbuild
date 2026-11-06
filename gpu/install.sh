#!/bin/bash
# Called by the root image builder after Debian and donor modules are installed.
set -euo pipefail
BASE=$1
R=$2
DONOR=$3
WORK=$4
ABI=$5
[[ $ABI == 6.6.98-sun60iw2 ]] || { echo 'PowerVR candidate supports only 6.6.98-sun60iw2.' >&2; exit 1; }
mkdir -p "$WORK/powervr"
python3 "$BASE/scripts/powervr.py" runtime "$R" "$WORK/powervr" "$BASE/gpu/pins.json"
# Debian owns the API loaders. Vendor libraries stay isolated under /opt.
chroot "$R" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    libvulkan1 vulkan-tools ocl-icd-libopencl1 clinfo libdrm2 libx11-6 libx11-xcb1 libxcb1 libstdc++6 \
    libxcb-dri3-0 libxcb-present0 libxcb-sync1 libxcb-dri2-0 libxcb-randr0 \
    libxcb-shm0 libxcb-xfixes0 libxcb-glx0 libxshmfence1 libexpat1 libudev1 zlib1g
MODULE=''
while IFS= read -r candidate; do
    magic=$(modinfo -F vermagic "$candidate")
    version=$(modinfo -F opi_3w_wbuild_ddk "$candidate")
    if [[ -z $version ]]; then version=$(modinfo -F version "$candidate"); fi
    if python3 - "$BASE/scripts" "$ABI" "$magic" "$version" <<'PY'
import sys
sys.path.insert(0,sys.argv[1])
from powervr import check_module
check_module(*sys.argv[2:])
PY
    then MODULE=$candidate; break; fi
done < <(find "$R/lib/modules/$ABI" -type f -name 'pvrsrvkm.ko*')
# Record runtime packages before temporarily installing native ARM64 build tools.
chroot "$R" dpkg-query -W -f='${binary:Package}\n' | sort > "$WORK/powervr/packages-before"
chroot "$R" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential bc bison flex libssl-dev libelf-dev libvulkan-dev ocl-icd-opencl-dev glslang-tools
B=/var/tmp/opi-3w-wbuild-powervr-build
mkdir -p "$R$B/checks"
cp "$BASE/gpu/"{opencl-check.c,vulkan-check.c,gpu-shader.comp} "$R$B/checks/"
if [[ -z $MODULE ]]; then
    echo 'No matching donor GPU module. Building against donor kernel headers.'
    HEADER_LIST=()
    if [[ -f $BASE/inputs/kernel-headers.deb ]]; then
        HEADER_LIST=("$BASE/inputs/kernel-headers.deb")
    else
        mapfile -t HEADER_LIST < <(find "$DONOR/opt" -maxdepth 1 -type f -name 'linux-headers*sun60iw2*.deb' 2>/dev/null || true)
    fi
    (( ${#HEADER_LIST[@]} == 1 )) || { echo 'Need one matching donor /opt/linux-headers*.deb or inputs/kernel-headers.deb.' >&2; exit 1; }
    # Extract headers into a private location, without package scripts.
    mkdir "$R$B/headers"
    dpkg-deb -x "${HEADER_LIST[0]}" "$R$B/headers"
    mapfile -t RELEASES < <(find "$R$B/headers/usr/src" -path '*/include/config/kernel.release' -type f)
    KERNELDIR=''
    for release in "${RELEASES[@]}"; do
        if [[ $(cat "$release") == "$ABI" ]]; then KERNELDIR=${release%/include/config/kernel.release}; break; fi
    done
    [[ -n $KERNELDIR && -s $KERNELDIR/Module.symvers ]] || { echo 'Headers must have matching kernel.release and Module.symvers.' >&2; exit 1; }
    cp "$BASE/gpu/prepare-headers.py" "$R$B/prepare-headers.py"
    chroot "$R" python3 "$B/prepare-headers.py" "${KERNELDIR#"$R"}" "$ABI"
    HEADER_SHA=$(sha256sum "${HEADER_LIST[0]}" | cut -d' ' -f1)
    printf '%s\n' "$HEADER_SHA" > "$R/opt/opi-3w-wbuild-powervr/kernel-headers.sha256"
    read -r REPO COMMIT < <(python3 - "$BASE/gpu/pins.json" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]));print(p['kernel_repo'],p['kernel_commit'])
PY
)
    SOURCE="$WORK/powervr/kernel-source"
    git init -q "$SOURCE"
    git -C "$SOURCE" remote add origin "$REPO"
    git -C "$SOURCE" sparse-checkout set bsp/modules/gpu/img-bxm bsp/include
    git -C "$SOURCE" fetch --depth 1 --filter=blob:none origin "$COMMIT"
    git -C "$SOURCE" checkout --detach FETCH_HEAD
    TREE=bsp/modules/gpu/img-bxm/linux/rogue_km
    cp -a "$SOURCE/$TREE" "$R$B/source"
    grep -q '6603887' "$R$B/source/include/pvrversion.h"
    grep -q '36.56.104.183' "$R$B/source/build/linux/sunxi_linux/Makefile"
    # Guard the OPP diagnostic with the same DVFS condition as its struct fields.
    chroot "$R" patch --batch --forward --fuzz=0 -p1 -d "$B/source" < "$BASE/gpu/sunxi-opp-guard.patch"
    (cd "$BASE/gpu"; sha256sum sunxi-opp-guard.patch opi_3w_wbuild_ddk_metadata.c) > "$R/opt/opi-3w-wbuild-powervr/module-source-patch.sha256"
    # Publish the pinned source header's version as dedicated module metadata.
    cp "$BASE/gpu/opi_3w_wbuild_ddk_metadata.c" "$R$B/source/services/server/env/linux/"
    printf '\n# opi-3w-wbuild DDK provenance\n$(PVRSRV_MODNAME)-y += services/server/env/linux/opi_3w_wbuild_ddk_metadata.o\n' >> "$R$B/source/services/server/env/linux/Kbuild.mk"
    # Use the actual vendor SID declarations, never fabricated chip-ID stubs.
    mkdir -p "$KERNELDIR/include/linux" "$KERNELDIR/bsp/include"
    if [[ ! -f $KERNELDIR/include/linux/sunxi-sid.h ]]; then
        cp "$SOURCE/bsp/include/sunxi-sid.h" "$KERNELDIR/include/linux/sunxi-sid.h"
    fi
    cp "$SOURCE/bsp/include/sunxi-sid.h" "$KERNELDIR/bsp/include/sunxi-sid.h"
    # Prepare links explicitly after bridge generation, before Linux Kbuild.
    # Modern kernel/make rules cannot be relied on to create the DDK's C links.
    python3 "$BASE/scripts/stage_kbuild.py" patch "$R$B/source"
    chroot "$R" env LICHEE_TOOLCHAIN_PATH=/usr/bin LICHEE_CROSS_COMPILER= \
        make -C "$B/source/build/linux/sunxi_linux" ARCH=arm64 BUILD=release KERNELDIR="${KERNELDIR#"$R"}"
    MODULE=$(find "$R$B/source" -type f -name pvrsrvkm.ko -print -quit)
    [[ -n $MODULE ]] || { echo 'GPU compilation produced no module.' >&2; exit 1; }
fi
MODULE_DDK=$(modinfo -F opi_3w_wbuild_ddk "$MODULE")
if [[ -z $MODULE_DDK ]]; then MODULE_DDK=$(modinfo -F version "$MODULE"); fi
echo "Selected module vermagic: $(modinfo -F vermagic "$MODULE")"
echo "Selected module DDK metadata: $MODULE_DDK"
echo "Standard module version: $(modinfo -F version "$MODULE")"
python3 - "$BASE/scripts" "$ABI" "$(modinfo -F vermagic "$MODULE")" "$MODULE_DDK" <<'PYCODE'
import sys
sys.path.insert(0,sys.argv[1])
from powervr import check_module
check_module(*sys.argv[2:])
PYCODE
mkdir -p "$R/lib/modules/$ABI/updates/opi-3w-wbuild"
# Stage before removing older candidates, including the selected donor file.
case "$MODULE" in
    *.xz) xz -dc -- "$MODULE" > "$WORK/powervr/selected-module" ;;
    *.zst) zstd -dc -- "$MODULE" > "$WORK/powervr/selected-module" ;;
    *.gz) gzip -dc -- "$MODULE" > "$WORK/powervr/selected-module" ;;
    *) cp "$MODULE" "$WORK/powervr/selected-module" ;;
esac
python3 - "$BASE/scripts" "$WORK/powervr/selected-module" <<'PYCODE'
import sys
sys.path.insert(0,sys.argv[1])
from powervr import check_elf
check_elf(sys.argv[2])
PYCODE
find "$R/lib/modules/$ABI" -type f -name 'pvrsrvkm.ko*' -delete
install -m644 "$WORK/powervr/selected-module" "$R/lib/modules/$ABI/updates/opi-3w-wbuild/pvrsrvkm.ko"
modinfo "$R/lib/modules/$ABI/updates/opi-3w-wbuild/pvrsrvkm.ko" > "$R/opt/opi-3w-wbuild-powervr/module.txt"
chroot "$R" depmod "$ABI"
chroot "$R" glslangValidator -V "$B/checks/gpu-shader.comp" -o "$B/checks/gpu-shader.spv"
python3 "$BASE/gpu/shader-header.py" "$R$B/checks/gpu-shader.spv" "$R$B/checks/gpu-shader.h"
mkdir -p "$R/opt/opi-3w-wbuild-powervr/bin"
chroot "$R" gcc -O2 -Wall -Wextra "$B/checks/opencl-check.c" -lOpenCL -o /opt/opi-3w-wbuild-powervr/bin/opencl-check
chroot "$R" gcc -O2 -Wall -Wextra "$B/checks/vulkan-check.c" -lvulkan -o /opt/opi-3w-wbuild-powervr/bin/vulkan-check
python3 - "$R" "$ABI" <<'PYCODE'
from pathlib import Path
import hashlib,json,sys
root=Path(sys.argv[1]);runtime=root/'opt/opi-3w-wbuild-powervr'
p=runtime/'manifest.json';manifest=json.loads(p.read_text())
paths=[runtime/'bin/opencl-check',runtime/'bin/vulkan-check',root/'lib/modules'/sys.argv[2]/'updates/opi-3w-wbuild/pvrsrvkm.ko']
for path in paths:
    manifest['files'][str(path.relative_to(root))]=hashlib.sha256(path.read_bytes()).hexdigest()
p.write_text(json.dumps(manifest,indent=2)+'\n')
PYCODE
# Confirm all selected libraries resolve against Debian + the isolated runtime.
for file in "$R/opt/opi-3w-wbuild-powervr/lib/"*.so*; do
    [[ -L $file ]] && continue
    chroot "$R" env LD_LIBRARY_PATH=/opt/opi-3w-wbuild-powervr/lib ldd "${file#"$R"}" > "$WORK/powervr/ldd.txt"
    if grep -q 'not found' "$WORK/powervr/ldd.txt"; then cat "$WORK/powervr/ldd.txt"; exit 1; fi
done
# Exercise the dynamically loaded WSI helper without opening a GPU device.
chroot "$R" env LD_LIBRARY_PATH=/opt/opi-3w-wbuild-powervr/lib python3 - <<'PY'
import ctypes, os
ctypes.CDLL('/opt/opi-3w-wbuild-powervr/lib/libpvr_mesa_wsi.so', mode=os.RTLD_NOW)
print('PowerVR WSI helper loads with all native dependencies resolved')
PY
# No automatic GPU loading. Explicit tests load it after the headless OS boots.
mkdir -p "$R/etc/modprobe.d"
printf 'blacklist pvrsrvkm\n' > "$R/etc/modprobe.d/opi-3w-wbuild-powervr.conf"
python3 - "$R" <<'PY'
from pathlib import Path
import sys
r=Path(sys.argv[1])
for p in [r/'etc/modules',*(r/'etc/modules-load.d').glob('*.conf')]:
    if p.is_file():
        p.write_text(''.join(l for l in p.read_text().splitlines(keepends=True)
                             if not l.strip().split('#')[0].strip().startswith('pvrsrvkm')))
PY
install -m755 "$BASE/gpu/opi-3w-wbuild-gpu-test" "$BASE/gpu/opi-3w-wbuild-gpu-run" "$R/usr/local/sbin/"
chroot "$R" dpkg-query -W -f='${binary:Package}\n' | sort > "$WORK/powervr/packages-after"
comm -13 "$WORK/powervr/packages-before" "$WORK/powervr/packages-after" > "$WORK/powervr/build-only-packages"
if [[ -s $WORK/powervr/build-only-packages ]]; then
    xargs -r chroot "$R" env DEBIAN_FRONTEND=noninteractive apt-get purge -y -- < "$WORK/powervr/build-only-packages"
fi
rm -rf "$R$B"
# Kernel/firmware hashes will also be included in the main image manifest.
echo 'PowerVR candidate installed. Hardware computation remains unverified.'
