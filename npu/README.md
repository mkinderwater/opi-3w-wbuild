# A733 NPU bring-up

A candidate VIPLite inference runtime and a small numerical test for the Orange Pi Zero 3W A733, kernel `6.6.98-sun60iw2`. This is a separate accelerator path from PowerVR.

**Board validation is pending.** Host checks validate the preparation, API call sequence and result checks; they cannot prove the NPU runs.

## Test the existing working card

No image rebuild or reflash is needed for this test. Copy this entire `npu` folder to `/root/npu` on the board, then run as root:

```bash
cd /root/npu
bash install.sh
opi-3w-wbuild-npu-test
```

The installer needs network access. It installs runtime prerequisites and temporary compiler packages, downloads the pinned assets, builds the probe natively, checks library resolution, and removes compiler packages introduced by this installation. Previously installed packages are preserved. It does not alter `/boot`, the kernel or the GPU runtime, and it does not run NPU inference or create an NPU startup service during installation.

For the image builder, `build.sh` calls the same installer with the fresh ARM64 chroot path.

Attach the resulting `npu-*.json` file from `/var/log/opi-3w-wbuild/`. The test prints the exact report path. A JSON-only invocation is available:

```bash
opi-3w-wbuild-npu-test --json
```

## What is installed

The package is isolated under `/opt/opi-3w-wbuild-npu`:

- Matched SDK `v2.0` `libNBGlinker.so` and `libVIPhal.so`.
- The SDK's **v3/A733 LeNet NBG** model, approximately 444 KB.
- The SDK input tensor and a generated synthetic seven input, 784 bytes each.
- A compiled direct VIPLite API probe and independent CPU reference outputs.
- File hashes and the source SDK commit in a manifest.

`pins.json` records each source path, byte count and SHA256. Downloads come from `ZIFENG278/ai-sdk` at `fc90006d0f6569da2f6726c2d8395877686f5aca`. Libraries are checked as AArch64 ELF files. No proprietary libraries or model binaries are redistributed in this source package.

This uses the SDK's pinned runtime pair, rather than guessing which unversioned library from the donor should be mixed with another SDK. Compatibility with the preserved board driver must still be demonstrated by initialization and inference on the board. The original GPU/VPU image builder and its NPU-enabled fork helped identify the donor's `/usr/lib/libVIPhal.so` and `/opt/yolov5` path, but this first test avoids the larger YOLO/OpenCV demo dependency chain.

## What counts as PASS

The explicit test:

1. Checks runtime/model/probe hashes and the running kernel ABI.
2. Uses `/dev/vipcore`; if absent, tries available matching `sunxi_npu`/`vipcore` modules.
3. Initializes VIPLite and requires A733 customer ID `0x1000003b` and one device.
4. Loads the A733 LeNet binary and validates its input/output tensor layout.
5. Runs six inferences, alternating the SDK digit-zero input and a generated seven.
6. Requires positive hardware inference cycle counts from VIPLite profiling.
7. Compares all ten output probabilities per inference against independent CPU reference vectors, with absolute tolerance 0.03 and the expected top class.
8. Rejects API errors, stale outputs, invalid probabilities, missing profiling, timeouts or cleanup failures.

The probe has no CPU inference fallback. CPU reference calculation happens offline, not in the on-board inference path. The reference vectors were independently reproduced using OpenCV 4.10.0's CPU Caffe backend and a separate NumPy implementation of LeNet's layers; agreement was within approximately `1.2e-7`.

`golden.json` records the reference engine information, input hashes, original Caffe weight/prototxt hashes, expected output vectors and tolerance. `reference.py` is an optional host-only reproducer requiring NumPy, OpenCV and the pinned SDK checkout:

```bash
python3 reference.py --sdk /path/to/ai-sdk --output /tmp/reproduced-reference.json
```

A driver which cannot supply the required hardware profile will fail this strict check rather than be reported as verified. That distinction will be visible in the command logs. A PASS establishes this small model's inference and numerical agreement, not general model compatibility, LLM support, sustained throughput or operator coverage for other models.

## Reports and failures

Reports contain kernel identity, module/load observations, command logs, hardware ID, run timings, hardware cycles, output probabilities and reference errors. They do not collect WiFi credentials or account databases.

Typical failures:

| Failure | Next evidence |
| --- | --- |
| `/dev/vipcore` absent | Driver/module availability and kernel probe messages |
| VIPLite initialization or version error | Exact driver/library compatibility |
| NBG creation/preparation error | Model target and runtime support |
| Wrong input/output format | Actual model tensor metadata |
| Missing hardware cycles | Driver profiling support |
| Numerical mismatch | Quantization, preprocessing, model provenance or runtime behavior |

The model/network API timeout is 10 seconds, with an outer process timeout of 60 seconds. No test runs automatically at boot. Keep the working card/image as the checkpoint while testing driver execution.

## References and credit

- [Radxa's A733 VIPLite/vpm_run documentation](https://docs.radxa.com/en/cubie/a7s/app-dev/npu-dev/cubie-vpm-run).
- [ZIFENG278/ai-sdk](https://github.com/ZIFENG278/ai-sdk): runtime, headers, compiled sample and original Caffe model.
- [petayyyy/a733_npu_driver](https://github.com/petayyyy/a733_npu_driver): published A733/Orange Pi bring-up and LeNet conversion evidence, including the `v3` model target and `v2.0` runtime distinction.
- [Incipiens/OrangePiZero3W-GPU-VPU](https://github.com/Incipiens/OrangePiZero3W-GPU-VPU) and [wuclark's NPU-enabled fork](https://github.com/wuclark/OrangePiZero3W-GPU-VPU-NPU): extraction/reference workflows and the original donor NPU asset locations.

SDK/vendor assets retain their upstream licenses. This source package downloads them at installation/build time.

## Existing runtime update

Version 0.7.4 fixed probe API ordering. VIPLite requires
`vip_prepare_network` before attaching input and output buffers. The original
probe failed at `vip_set_input` with status -9 before any inference ran.
The SDK header documents this requirement and its awnn example follows it.

On a board with the candidate runtime already installed, copy this `npu` folder
and run as root:

```sh
bash /root/opi-npu-fix/update.sh
opi-3w-wbuild-npu-test
```

The updater checks existing runtime integrity, recompiles the corrected probe
against retained SDK headers and libraries, updates its manifest hash, and
retains the previous runtime under the printed `/var/tmp/opi-npu-update.*` path.
It installs and removes only the compiler packages added for this update.
It does not fetch another model or replace the kernel, drivers, or device tree.
Do not run another NPU test or update during the update. Hardware inference
remains unvalidated until the corrected test passes on the board.

Version 0.7.5 adds IEEE 754 FP16 output decoding. The pinned model reports
output format 1 (FP16) with quantization 0. The earlier decoder supported
FP32 and integer outputs, so it exited when decoding this model's output.
All 65,536 binary16 encodings are checked against Python's independent half
precision decoder, including signed zero, subnormals, infinity and NaN.
Nonfinite inference results still fail validation. The six alternating hardware
inferences and independent CPU reference tolerances are unchanged.
Tensor metadata and previously silent failure paths now print diagnostics.
Hardware inference remains pending a passing test on the board.
