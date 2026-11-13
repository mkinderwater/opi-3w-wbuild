# GPU clock and voltage finding, image default in 0.7.6

## Observed on the running board

Evidence: power-20261113T041757Z-PQhzEc.tar.gz, captured 2026-11-12 at
22:17:57 UTC-06:00. The driver had selected its fallback 600000000 Hz because
the GPU node lacked the plain clk_rate property. The regulator interface
reported 800000 microvolts on axp8191-dcdc4; the clock summary reported
600000000 Hz for gpu0, gated while idle. These are software readbacks, not
external meter measurements or a sustained-load stability test.

The live table contains:

| GPU frequency | Default voltage |
|---|---|
| 400 MHz | 800 mV |
| 600 MHz | 800 mV |
| 800 MHz | 840 mV |
| 1008 MHz | 960 mV |

GPU gpu-supply points to dcdc4. The only additional recorded supply consumer
is the vendor's virtual dcdc4 test consumer, with zero users in the capture.
There is no GPU devfreq node in the captured image; the NPU devfreq control
must not be mistaken for a GPU governor.

The proprietary driver's fixed-clock path can ignore the standard OPP clock
and voltage selection. Setting frequency alone would leave the pair mismatched.
The original 600 MHz / 800 mV pair matches the table's nominal 600 MHz point;
these observations do not establish undervoltage at the old setting.

## Implemented default

Every normal build now sets:

- /soc@3000000/gpu@1800000: clk_rate = 1008000000.
- /soc@3000000/twi@7083000/pmu@36/regulators@0/dcdc4:
  regulator-min-microvolt = regulator-max-microvolt = 960000.

scripts/gpu_opp.py edits the selected DTB directly. It verifies original donor
hashes, GPU/regulator identities, supply and OPP phandles, the declared
1008 MHz / 960 mV default point, regulator limits and expected consumers.
Unexpected inputs fail the build. It compares every property, node and memory
reservation after editing and accepts only these three GPU property changes.
No CPU, NPU, DDR or microphone property is changed. The OPP table itself stays
unchanged, including its bin-specific voltage entries.

The original hardware bundle, U-Boot, kernel, initramfs and boot environment
are retained. The selected DTB is the one documented boot-file exception.
There is no new overlay or first-boot voltage script. The kernel regulator
constraints and the existing driver apply the pair when the GPU is initialized.

The image retains gpu-opp-original.dtb, gpu-opp.json and vendor-boot.json under
/usr/share/opi-3w-wbuild/. The final hashes are in configured-boot.json, and
board-profile.json records both the original and configured DTB hashes.
Assembly rechecks the original-to-final delta and uses the final manifest for
boot allocation and preservation checks. Unrelated changes still fail.

The board verifier checks the live DT properties after compute tests load the
GPU. It records regulator voltage and the gpu0 clock from readable interfaces.
A mismatch fails; unavailable readback is WARN and leaves confirmed=false.
It does not silently substitute the NPU frequency or a requested DT clock for
an actual reported GPU clock.

## Validation and limits

The complete returned live DTB was edited locally with fdtput. Full-tree and
memory-reservation comparison confirmed only the three intended GPU properties
changed. Tests also cover wrong supply/OPP rejection, unrelated DT or boot-file
changes, original-DTB preservation, final manifest validation and actual/missing
voltage and clock readbacks.

The fresh 0.7.6 image has not yet completed a WSL build or booted on this board.
After flashing and provisioning, run opi-3w-wbuild-verify and return its archive.
A firmware setting in the image is distinct from a confirmed runtime readback.
Rerun the unchanged exact-input Vulkan diagnostic 0.4.1 to determine whether
the FP16 RTE failure persists at this operating point. No Whisper speedup or
arithmetic fix is claimed by setting clock and voltage.

## Related FP16 correctness evidence

The separate 0.4.1 diagnostic ran with active Khronos validation and zero
validation errors. Both input echoes and off/capability-only controls passed.
Explicit RTE16+RTE32 returned zero instead of exactly 1/16 for all 12288 matrix
values across three repeats. Exact inputs remove accumulation-order ambiguity.
This strongly implicates driver/compiler behavior, while supply stability and
the internal cause remain separate questions. It is not a blanket FP16 pass.

## Sources

1. Same-board clock and matching-voltage change: https://github.com/orangepi-xunlong/linux-orangepi/pull/138
2. Vendor device-tree source: https://github.com/orangepi-xunlong/linux-orangepi/blob/2ac08e8c7cdc28abbdc5c9a9dd812f887ae9c79f/arch/arm64/boot/dts/allwinner/sun60iw2p1.dtsi
