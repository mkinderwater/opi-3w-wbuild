# PowerVR compute runtime

opi-3w-wbuild 0.7.5 uses fresh Debian 13 main userspace with the working vendor boot bundle. BUILD.bat produces
`out/opi-3w-wbuild-0.7.5.img.gz`. See the main README for configuration and
BOOT-STATUS.TXT diagnostics.

The exact package/source URLs, hashes, kernel ABI, DDK and BVNC are pinned in
pins.json. The userspace package is downloaded from the official Orange Pi
repository and extracted selectively; it is not installed as a system Xorg
replacement. Its files remain under their vendor licenses. They are not included
in the ZIP. The vendor GPL module source is fetched at the pinned commit.

Compute runtime: libPVROCL, libVK_IMG, libsrv_um, libusc, libufwriter,
libpvr_dri_support, libglslcompiler, libpvr_mesa_wsi.so and the matching RGX firmware.
API loaders come from Debian repositories. Additional WSI dependencies
are installed explicitly. The isolated wrapper sets library and ICD paths for one
command. Nothing enables a composited GPU desktop or changes GPU voltage/clocks.

The GPU module must match 6.6.98-sun60iw2 and DDK 24.2.6603887. When not present it
is compiled using the matching donor header package. Kernel helpers are rebuilt
for ARM64; source links are explicitly staged; the OPP diagnostic field guard and
dedicated DDK metadata are retained. The real vendor SID declarations are used.

The driver is blacklisted from normal modalias loading and no opi-3w-wbuild early
load service is created. Explicit `opi-3w-wbuild-gpu-run` / `opi-3w-wbuild-verify`
commands load it after the board boots. No NPU inference or VPU support is claimed.

Host build checks establish package identity, ELF format, module metadata and
native dependency resolution, including dlopen of the WSI helper. Only the board
can establish successful kernel/GPU operation. Verification runs small numerical
OpenCL/Vulkan workloads and saves their outputs. It is not a performance benchmark.
