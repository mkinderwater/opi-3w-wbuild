# opi-3w-wbuild 0.7.2

Fresh Debian 13 ARM64, using hardware assets extracted from the known working
A733 Zero 3W vendor image. Future builds use a compressed hardware archive.
The vendor root filesystem is never copied into the new image.

## Naming

The project and build outputs are named `opi-3w-wbuild` as of 0.7.2.
The image is `opi-3w-wbuild-0.7.2.img.gz`; WSL workspaces are under
`~/opi-3w-wbuild/build-0.7.2-*`. After flashing this release, commands are
`opi-3w-wbuild-verify`, `opi-3w-wbuild-status`, `opi-3w-wbuild-expand` and
`opi-3w-wbuild-gpu-test`. Services, release file and state/report paths use the
same prefix. This is a fresh-image rename, not an in-place upgrade of existing cards.
Reuse the existing `inputs/zero3w-hardware.tar.gz` hardware bundle.

## Windows build

1. Extract this ZIP into a new folder. Use Debian under WSL2.
2. Put the original working, uncompressed vendor image in `inputs/vendor.img`.
   Do not use a generated opi-3w-wbuild image as the donor.
3. If needed, place matching headers in `inputs/kernel-headers.deb`. Otherwise,
   the extractor retains the vendor's `/opt/linux-headers*sun60iw2*.deb`.
4. Run `EXTRACT.bat` once. It creates `inputs/zero3w-hardware.tar.gz` and checksum.
5. Run `BUILD.bat`. The archive takes precedence over `vendor.img`.
6. Flash `out/opi-3w-wbuild-0.7.2.img.gz` and edit its CONFIG.TXT.

BUILD.bat also performs extraction automatically when only vendor.img is present.
The original image remains untouched. After validating a bundle/build, you can
archive the original elsewhere. Reusing the bundle does not need it. Keep the
bundle with its checksum. Changing donors requires moving the existing bundle
before extracting again. Extraction size is reported on disk; it depends on the
vendor's firmware and kernel development package.

PowerShell options:

```powershell
.\Build.ps1 -Distribution Debian -ExtractOnly
.\Build.ps1 -Distribution Debian -DonorImage 'D:\assets\zero3w-hardware.tar.gz'
.\Build.ps1 -Distribution Debian -ImageMiB 4096
```

Native Linux, after setup-wsl.sh:

```bash
sudo bash extract-hardware.sh inputs/vendor.img inputs/zero3w-hardware.tar.gz
sudo bash build.sh inputs/zero3w-hardware.tar.gz /home/matthew/opi-3w-wbuild.img 2048
```

## What is extracted

| Asset | Purpose |
| --- | --- |
| Raw reserved boot area, including boot0 and boot package | Preserve the working vendor bootloader at its original offsets |
| Entire /boot tree and symlinks | Kernel, initramfs, scripts and DTBs |
| Matching modules, firmware and module configuration | Board peripherals and hardware support |
| Matching kernel header package, when available | Rebuild the PowerVR module; excluded from the final OS |
| Hashes, selected DTB profile and original filesystem profile | Validate extraction and assembly |

No vendor accounts, home directories, package database, general applications or
services are extracted. The retained vendor initramfs contains early boot
userspace. Modules and firmware are kept broadly for repurposing the board.
PowerVR userspace is still downloaded separately from the pinned official package;
the small builder ZIP does not redistribute those binaries. Builds need network
access for Debian, PowerVR and pinned source inputs.

The original donor is mounted read-only during extraction. Archives have an
allowlisted inventory, file hashes, boot payload checksums and guarded extraction.
Cached builds do not copy the full vendor image into the WSL workspace. Generated
Linux donor copies are removed after successful extraction; extraction workspaces
retain only staged hardware assets and metadata for diagnosis.

## Compact image and full-card expansion

The default raw image is 2048 MiB. A fresh ext4 filesystem is populated directly
from the new Debian tree. Explicit ext4 features, 4 KiB blocks, 256-byte inodes
and the original UUID match the known vendor profile. Host defaults cannot add
64bit, metadata checksums or orphan_file. Unsupported donor profiles fail closed.
There are no discarded vendor filesystem blocks to carry into the output.

Boot reserve occupies 0-32 MiB, FAT32 /config 32-96 MiB, then expandable ext4 root.
Root remains partition 1 for vendor scripts; FAT is partition 2 but physically
precedes root. Boot code, disk ID and raw boot payloads are checked after assembly.
Only root geometry and the second MBR entry change.

opi-3w-wbuild-expand grows the root partition count, refreshes kernel geometry using
partx, then runs resize2fs. It preserves the partition start and UUID. This follows
the working BPI builder sequence. Failure is recorded and retried next boot;
WiFi and SSH provisioning continue. Verification checks actual partition and
filesystem sizes rather than trusting a completion marker.

As root, without sudo:

```bash
opi-3w-wbuild-expand --check
lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINTS
df -h /
opi-3w-wbuild-verify
```

0.5.0 passed board tests for fresh Debian, WiFi, SSH and actual OpenCL/Vulkan
compute. Initial 0.7.0 did not boot. A diagnostic copy with boot files rewritten
to fully allocated files booted on the board with the same 2 GiB image, boot
payloads, root UUID and relocated root. The kernel changed from 347 sparse holes
and an extent-tree block to one continuous extent. A mount-only control was also
produced but its board result is pending; this does not yet isolate holes from
journal initialization or extent layout as the exact cause.

0.7.2 integrates that normalization after mkfs population: mount only the newly
created root.ext4, preallocate/write every regular boot file, verify no holes,
check unchanged hashes, symlinks, owners and modes, then unmount and check the
filesystem. Boot code and partition geometry are unaffected. It records an audit
under /usr/share/opi-3w-wbuild/boot-allocation.json and retains detailed inode
reports beside root.ext4 in the Linux workspace. Sparse storage of the outer raw
image is fine; sparse file allocation inside /boot is the difference addressed.

Reuse the existing inputs/zero3w-hardware.tar.gz; no donor extraction is needed.
The exact fresh 0.7.2 build still needs a complete WSL build and board verification.
The successful diagnostic image passed opi-3w-wbuild-verify on the board, including
WiFi, SSH, actual OpenCL/Vulkan computation, hardware/runtime hashes, no failed
units, and full-card expansion. Root starts at sector 196608 (96 MiB), expands to
499974144 sectors on a 500170752-sector card, and df -h reports a 235G ext4 root.
The mount-only control result and NPU inference remain untested. Keep this working
image as the checkpoint.

## Configuration and boot diagnostics

Edit CONFIG.TXT on the flashed card:

```text
SSID=Your WiFi network
PSK=Your WiFi password
COUNTRY=CA
HIDDEN=false
TIMEZONE=America/Edmonton
ROOT_PASSWORD=Your unique root password
```

Use literal values, without quotes. WPA/WPA2 Personal with IPv4 DHCP is supported.
SSID is 1-32 UTF-8 bytes. PSK is 8-63 printable ASCII characters. The root password
is 8-64 characters excluding colon and line breaks. The timezone must exist in
the installed tzdata package. There is no vendor account or default login password.
Root starts locked; SSH waits for credentials to be committed by provisioning.

First boot generates the machine identity and SSH host keys. The early status
service writes BOOT-STATUS.TXT before network provisioning. Setup verifies root
credentials and SSH before attempting Wi-Fi. It detects the NetworkManager Wi-Fi
interface and writes a private profile, rather than assuming wlan0. Retries reuse
the connection UUID. A regulatory-domain error is recorded without blocking SSH.

| BOOT-STATUS.TXT stage | Meaning |
| --- | --- |
| BUILD-ONLY | The early Linux status service has not updated FAT yet |
| LINUX_STARTED | Linux reached systemd and mounted the config partition |
| SSH_READY | Root credentials and SSH setup completed |
| WAITING_FOR_WIFI_DEVICE | Looking for a NetworkManager Wi-Fi device |
| WIFI_PROFILE_READY | Private Wi-Fi profile written |
| WAITING_FOR_DHCP | Activating Wi-Fi and waiting for an address |
| CONFIGURED | IPv4 obtained; the address is included |
| SETUP_FAILED | Failed phase and error category, without passwords or raw command output |
| PREVIOUSLY_CONFIGURED | A later boot; stored NetworkManager settings reconnect |

Find `opi-3w-wbuild-XXXXXXXX` in the router, or read the IP in BOOT-STATUS.TXT:

```bash
ssh root@DEVICE_IP
```

If no address appears, power off, read the card in Windows and attach
BOOT-STATUS.TXT. Do not attach CONFIG.TXT. BUILD-ONLY does not identify the exact
failure: kernel, initramfs, systemd or FAT mount failures can all prevent the
status service from writing.

Successful setup blanks PSK and ROOT_PASSWORD in CONFIG.TXT. NetworkManager keeps
the derived WPA key in a mode-0600 profile. Interrupted scrubbing finishes on the
next run. Status reports exclude passwords and SSIDs; they include boot ID, times
and local IPv4. Config scrubbing is not secure erasure of flash media.

## Verify on the board

```bash
opi-3w-wbuild-status
opi-3w-wbuild-verify
```

Verification requires Debian 13 ARM64, the matched kernel, preserved root UUID,
unchanged boot tree, matching runtime/hardware hashes, configured networking and
services, and real numerical OpenCL/Vulkan tests. Reports and command logs are
saved under /var/log/opi-3w-wbuild in a dated tar.gz bundle. Attach that bundle when
reviewing results.

The vendor Zero 3W DTS incorrectly contains model `sun60iw2` and compatible
`xunlong,orangepi-4-pro`, `arm,sun60iw2p1`. The verifier does not accept that label
alone. It requires the explicitly selected Zero 3W DTB, its recorded file hash,
and matching live model/compatible data. The known label is then reported as a
warning, with the boot-tree integrity check still required. It does not rewrite
the DTB or claim that this generic label independently identifies the hardware.

The PowerVR DDK remains 24.2.6603887 / BVNC 36.56.104.183. The WSI helper and its
native dependencies are included. Kernel module source, header preparation, source
staging, OPP diagnostic guard and DDK metadata checks remain as in the working
baseline. The new module is not configured to load automatically; explicit GPU
commands load it after boot. The build also tests loading the WSI helper under
emulation, which checks dependencies but not GPU operation.

A GPU enumeration result or FP16 extension advertisement does not establish a
numerical workload. The supplied tests verify actual OpenCL and Vulkan results.
No new VPU stack, graphics feature-faking layer, or GPU clock/voltage overlay is
enabled. NPU inference remains NOT TESTED. Bluetooth, microphone and other board
peripherals require their own tests; retaining firmware is not proof of operation.

## Host validation

```bash
python3 -m unittest discover -s tests -v
bash -n build.sh extract-hardware.sh setup-wsl.sh windows-entry.sh gpu/install.sh
```

Boot allocation tests cover real sparse files, hardlinks and metadata preservation.
Host assembly tests substitute loop mounting; WSL uses the real mounted filesystem.
Native archive/assembly tests need rsync, device-tree-compiler, e2fsprogs and
dosfstools. They create real filesystems and synthetic boot payloads, verify
boot preservation, exclude vendor OS files and reject unsafe archives. Expansion
tests cover partition guards, kernel refresh failure, retry and real ext4 growth.
GPU SDK-dependent host tests skip when their development packages are absent.
