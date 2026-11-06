#!/bin/bash
# Fresh Debian userspace with the verified vendor boot path and root identity.
set -euo pipefail
export LC_ALL=C
export LANG=C
BASE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ ${1:-} == --inspect && $# == 2 ]]; then exec python3 "$BASE/scripts/image_layout.py" inspect "$2"; fi
if (( $# < 2 || $# > 3 )); then
    echo 'Usage: sudo bash build.sh HARDWARE.tar.gz NEW-OUTPUT.img [size-MiB, default 2048]' >&2
    exit 2
fi
(( EUID == 0 )) || { echo 'Run with sudo inside Debian WSL2.' >&2; exit 1; }
DONOR=$(realpath -- "$1")
OUTPUT=$(realpath -m -- "$2")
SIZE=${3:-2048}
[[ $SIZE =~ ^[0-9]+$ && ! -e $OUTPUT && ! -L $OUTPUT && $OUTPUT != /mnt/* ]] || {
    echo 'Need a new image path inside the WSL Linux filesystem and an integer size.' >&2; exit 1;
}
for cmd in debootstrap rsync mkfs.ext4 losetup mount umount mountpoint mkfs.vfat mcopy mkimage fdtget chroot python3 e2fsck debugfs resize2fs; do
    command -v "$cmd" >/dev/null || { echo "Missing $cmd. Run setup-wsl.sh." >&2; exit 1; }
done
WORK=$(mktemp -d /var/tmp/opi-3w-wbuild.XXXXXXXX)
R=$WORK/root
COMPLETE=false
cleanup() {
    set +e
    for point in "$R/run" "$R/dev/pts" "$R/dev" "$R/proc" "$R/sys"; do
        mountpoint -q "$point" && umount "$point"
    done
    if [[ $COMPLETE != true ]]; then echo 'No completed image was exported.'; fi
    echo "Build workspace retained at $WORK"
}
trap cleanup EXIT
python3 "$BASE/scripts/hardware_bundle.py" unpack "$DONOR" "$WORK/hardware"
H=$WORK/hardware/root
python3 - "$WORK/hardware/manifest.json" "$WORK" <<'META'
import json,sys,pathlib
m=json.load(open(sys.argv[1]));w=pathlib.Path(sys.argv[2])
for name,key in [('vendor-boot','vendor_boot'),('board-profile','board_profile'),('donor-layout','donor_layout')]:
    (w/(name+'.json')).write_text(json.dumps(m[key],indent=2)+'\n')
META
python3 "$BASE/scripts/assemble_image.py" plan "$WORK/hardware" "$SIZE" > "$WORK/layout.json"
ABI=6.6.98-sun60iw2
python3 "$BASE/scripts/powervr.py" preflight "$H" "$H" "$BASE/inputs" "$BASE/gpu/pins.json"
debootstrap --arch=arm64 --foreign --variant=minbase --include=ca-certificates trixie "$R" https://deb.debian.org/debian
chroot "$R" /debootstrap/debootstrap --second-stage
mkdir -p "$R/lib/modules" "$R/usr/lib/firmware" "$R/usr/local/sbin" "$R/run" "$R/config" "$R/var/lib/opi-3w-wbuild" "$R/usr/share/opi-3w-wbuild"
rsync -aH "$H/boot/" "$R/boot/"
rsync -aH "$H/lib/modules/" "$R/lib/modules/"
for path in usr/lib/firmware vendor/etc/firmware etc/firmware etc/modules-load.d etc/modprobe.d; do
    if [[ -d $H/$path ]]; then mkdir -p "$R/$path"; rsync -aH "$H/$path/" "$R/$path/"; fi
done
if [[ -f $H/etc/modules ]]; then cp "$H/etc/modules" "$R/etc/modules"; fi
mkimage -l "$R/boot/uImage" > "$WORK/kernel-header.txt"
fdtget "$R/boot/dtb/allwinner/sun60i-a733-orangepi-zero3w.dtb" / compatible > "$WORK/dtb-compatible.txt"
cat > "$R/etc/apt/sources.list" <<'APT'
deb https://deb.debian.org/debian trixie main
deb https://deb.debian.org/debian trixie-updates main
deb https://security.debian.org/debian-security trixie-security main
APT
mount --bind /dev "$R/dev"
mount --bind /dev/pts "$R/dev/pts"
mount -t proc proc "$R/proc"
mount -t sysfs sysfs "$R/sys"
mount -t tmpfs tmpfs "$R/run"
# Move absolute symlinks intact before creating temporary chroot files.
if [[ -e $R/etc/resolv.conf || -L $R/etc/resolv.conf ]]; then mv "$R/etc/resolv.conf" "$WORK/resolv.original"; fi
cp -L /etc/resolv.conf "$R/etc/resolv.conf"
if [[ -e $R/usr/sbin/policy-rc.d || -L $R/usr/sbin/policy-rc.d ]]; then mv "$R/usr/sbin/policy-rc.d" "$WORK/policy.original"; fi
printf '#!/bin/sh\nexit 101\n' > "$R/usr/sbin/policy-rc.d"
chmod +x "$R/usr/sbin/policy-rc.d"
chroot "$R" apt-get update
chroot "$R" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    systemd-sysv systemd-resolved systemd-timesyncd dbus network-manager wpasupplicant \
    python3 iw wireless-regdb bluez openssh-server procps iproute2 tzdata ca-certificates kmod e2fsprogs util-linux
chroot "$R" /bin/sh -c 'command -v partx && command -v resize2fs && command -v udevadm && command -v findmnt'
bash "$BASE/gpu/install.sh" "$BASE" "$R" "$H" "$WORK" "$ABI"
bash "$BASE/npu/install.sh" "$R"
install -m755 "$BASE/overlay/firstboot.py" "$R/usr/local/sbin/opi-3w-wbuild-firstboot"
install -m755 "$BASE/overlay/expand.py" "$R/usr/local/sbin/opi-3w-wbuild-expand"
install -m755 "$BASE/overlay/opi-3w-wbuild-status" "$R/usr/local/sbin/opi-3w-wbuild-status"
install -m755 "$BASE/overlay/opi-3w-wbuild-verify.py" "$R/usr/local/sbin/opi-3w-wbuild-verify"
install -D -m644 "$BASE/lib/pvr_version.py" "$R/usr/local/lib/opi-3w-wbuild/pvr_version.py"
install -m644 "$BASE/scripts/boot_manifest.py" "$BASE/lib/boot_status.py" "$R/usr/local/lib/opi-3w-wbuild/"
install -m644 "$BASE/overlay/opi-3w-wbuild-firstboot.service" "$BASE/overlay/opi-3w-wbuild-boot-status.service" "$BASE/overlay/opi-3w-wbuild-expand.service" "$R/etc/systemd/system/"
mkdir -p "$R/config" "$R/var/lib/opi-3w-wbuild" "$R/etc/ssh/sshd_config.d"
ROOTUUID=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["filesystem"]["uuid"])' "$WORK/layout.json")
printf 'UUID=%s / ext4 defaults,noatime 0 1\nLABEL=OPICONFIG /config vfat defaults,umask=0077,nofail,x-systemd.device-timeout=10s 0 2\n' "$ROOTUUID" > "$R/etc/fstab"
mkdir -p "$R/etc/systemd/system/ssh.service.d" "$R/etc/NetworkManager/conf.d"
printf '[Unit]\nConditionPathExists=|/var/lib/opi-3w-wbuild/ssh-ready\nConditionPathExists=|/var/lib/opi-3w-wbuild/configured\n' > "$R/etc/systemd/system/ssh.service.d/opi-3w-wbuild.conf"
printf '[main]\ndns=systemd-resolved\n' > "$R/etc/NetworkManager/conf.d/opi-3w-wbuild.conf"
cat > "$R/etc/apt/preferences.d/vendor-kernel" <<'PIN'
Package: linux-image-* linux-dtb-* linux-u-boot-*
Pin: version *
Pin-Priority: -1
PIN
chroot "$R" passwd -l root
chroot "$R" systemctl enable opi-3w-wbuild-boot-status opi-3w-wbuild-expand opi-3w-wbuild-firstboot NetworkManager systemd-resolved systemd-timesyncd ssh
chroot "$R" systemctl set-default multi-user.target
printf 'opi-3w-wbuild\n' > "$R/etc/hostname"
printf '127.0.0.1 localhost\n::1 localhost ip6-localhost\n' > "$R/etc/hosts"
printf 'opi-3w-wbuild 0.7.5\nFresh Debian 13 ARM64; verified vendor boot path; kernel %s\n' "$ABI" > "$R/etc/opi-3w-wbuild-release"
cp "$WORK/"{donor-layout.json,layout.json,kernel-header.txt,dtb-compatible.txt,vendor-boot.json,board-profile.json} "$R/usr/share/opi-3w-wbuild/"
sha256sum "$DONOR" > "$R/usr/share/opi-3w-wbuild/hardware-bundle.sha256"
chroot "$R" dpkg-query -W > "$R/usr/share/opi-3w-wbuild/packages.txt"
chroot "$R" apt-get clean
rm -f "$R/etc/resolv.conf" "$R/usr/sbin/policy-rc.d"
ln -s /run/systemd/resolve/stub-resolv.conf "$R/etc/resolv.conf"

# Generic machine identity and credentials are generated on the board.
rm -f "$R/etc/ssh/ssh_host_"* "$R/var/lib/dbus/machine-id"
: > "$R/etc/machine-id"
ln -s /etc/machine-id "$R/var/lib/dbus/machine-id"
python3 "$BASE/scripts/boot_manifest.py" verify "$R" "$WORK/vendor-boot.json"
(cd "$R"; for path in boot lib/modules usr/lib/firmware vendor/etc/firmware etc/firmware etc/modules-load.d etc/modprobe.d etc/modules; do
    if [[ -e $path ]]; then find "$path" -type f -exec sha256sum '{}' +; fi
done) > "$R/usr/share/opi-3w-wbuild/hardware.sha256"
for point in run dev/pts dev proc sys; do umount "$R/$point"; done
read -r FATBYTES < <(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["config_bytes"])' "$WORK/layout.json")
truncate -s "$FATBYTES" "$WORK/config.fat"
mkfs.vfat -F 32 -n OPICONFIG "$WORK/config.fat"
mcopy -i "$WORK/config.fat" "$BASE/config/CONFIG.TXT.template" ::CONFIG.TXT
printf 'BUILD-ONLY: Linux has not reported a boot yet.\n' > "$WORK/BOOT-STATUS.TXT"
mcopy -i "$WORK/config.fat" "$WORK/BOOT-STATUS.TXT" ::BOOT-STATUS.TXT
python3 "$BASE/scripts/assemble_image.py" build "$WORK/hardware" "$R" "$WORK/config.fat" "$WORK/root.ext4" "$OUTPUT" "$WORK/layout.json"
sha256sum "$OUTPUT" > "$OUTPUT.sha256"
COMPLETE=true
echo "Built $OUTPUT from fresh Debian and extracted hardware assets."
echo 'Hardware boot/GPU testing is still required.'
