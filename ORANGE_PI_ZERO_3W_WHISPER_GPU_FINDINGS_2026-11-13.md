# Whisper GPU offload on the Orange Pi Zero 3W: failures, workarounds and measured results

**Author:** Matthew Kinderwater, iCube Development (Calgary) Ltd.  
**Report date:** 2026-11-13 UTC  
**Evidence through:** `results-20261113T130435Z-YGoQvJ.tar.gz`  
**Latest board-tested matrix suite:** `opi-ggml-vulkan-test-0.6.0.zip`  
**Status:** Correct, substantially improved matrix kernels; full Whisper integration remains unproven.

This report records work on one physical Orange Pi Zero 3W and one Linux PowerVR driver configuration. Diagnostic code and analysis were prepared with AI assistance. Results came from the physical board, not a simulated GPU. Local software Vulkan checks were used separately to check the harness.

## 1. What we were trying to achieve

Our goal was to move expensive Whisper matrix operations off the CPU so the board could continue recording and processing audio reliably around the clock.

The primary objective was **less CPU work without losing transcription correctness or falling behind incoming audio**. GPU elapsed time did not have to beat the CPU on every operation, but the complete application still had to meet its processing deadline and avoid an accumulating queue.

That distinction matters. A GPU operation can take longer while consuming very little CPU time. That can be useful for an audio appliance. It is only useful if the remaining application can run correctly and the workload finishes soon enough.

We therefore needed four separate answers:

1. Does the intended hardware GPU actually execute the work?
2. Are its results correct?
3. How much CPU time does offload remove, and how much elapsed time does it add?
4. Do those savings survive packing, transfers, graph execution, decoding and continuous operation?

We have useful answers to the first three for a bounded set of matrix kernels. We have not completed the fourth for the tuned Vulkan configuration.

## 2. Outcome at this checkpoint

The most useful findings are:

- Explicit SPIR-V round-to-nearest-even execution modes can cause pipeline rejection or incorrect arithmetic on this driver. The minimal exact-input reproducer returns zeros where every result must be exactly 1/16.
- Omitting explicit RTE injection allows the tested captured GGML matrix shaders to compile and pass their exact-input checks while retaining native FP16 storage and arithmetic support. DenormPreserve16 can remain enabled in these tests.
- FP16 inputs and FP32 accumulation performed better than FP16 accumulation in the initial controlled matrix comparisons. Using FP32 accumulation alone did not cure the explicit-RTE pipeline failure.
- The original native-F16 shader compiled its K tile as 32. A similarly named specialization value did not change it. Recompiling BK as 8, then 4, produced major improvements on this board.
- The best configuration tested so far is **BK4, a 64x64 output tile, padding 1 and FP32 accumulation**.
- That configuration still takes approximately **2.4-3.4 times the four-thread CPU elapsed time** in the latest matrix batch, while using approximately **98-99% less process CPU time inside the measured calls**.

These are matrix results. They are not a claim that Whisper is now faster, that the audio service saves 99% CPU, or that production GPU transcription has passed acceptance.

## 3. Hardware, software and provenance

| Item | Tested configuration |
|---|---|
| Board | Orange Pi Zero 3W |
| SoC | Allwinner A733 |
| Architecture | aarch64 |
| Kernel | `6.6.98-sun60iw2`, release marker `#1.0.2` |
| GPU | PowerVR B-Series BXM-4-64 MC1 |
| Vendor / device IDs | `0x1010` / `0x36104183` |
| Linux driver integer | `6603887` |
| Userspace bundle identification | PowerVR DDK `24.2.6603887` |
| Advertised Vulkan API | 1.3.277 |
| Probe Vulkan target | 1.2 |
| Reported hardware subgroup size | 1 |
| Reported GPU timestamp period | 512 ns |
| GGML/Whisper source revision used for captured modules | `d1be6fde11ac6e0407606b4e42fe72d34add8037` |
| CPU reference | Existing GGML CPU/base libraries; four configured threads |
| Active target validation in accepted recent runs | Private Khronos layer 1.4.363 |
| Controlled GPU operating point | 1008 MHz / 960 mV, checked through software interfaces |

The matrix runner selects the expected BXM vendor/device and rejects CPU Vulkan devices in normal operation. It explicitly uses the existing vendor ICD and runtime. It does not silently fall back to software Vulkan.

This report concerns the proprietary PowerVR runtime. It does not establish Mesa performance on this device. We considered Mesa and OpenCL during the investigation, but the successful tuning results below are Vulkan results from the vendor driver. The NPU is a separate accelerator and is outside these measurements.

The captured shader pair was extracted from the existing GGML Vulkan library and compared with generated modules. The native-F16 FP32-accumulation baseline was later rebuilt byte-for-byte with shaderc 2025.2-1, glslang 15.1.0 and the recorded optimization/define set. This removed a shader-compiler change as an explanation for the BK tuning results.

## 4. Where the early evaluation went wrong

We initially asked too much of a single end-to-end timing result. A slow or failed inference could include compilation, memory pressure, data conversion, driver waits, altered decoder work and genuine kernel cost. Those are different problems.

### 4.1 OpenCL: a failed application result did not describe the offloaded region

An early partial OpenCL integration produced these warm means:

| Application path | Elapsed seconds | Process CPU seconds |
|---|---:|---:|
| CPU | 5.640 | 20.312 |
| OpenCL | 14.673 | 19.883 |

Process CPU saving was only 2.1%, below the existing 10% acceptance gate. Transcripts also differed. Activation was blocked and the service remained stopped. That rejection was correct.

However, interpreting it as proof that the GPU removed almost no CPU work was too broad. A subsequent diagnostic separated the 36 offloaded matrix operations from the remaining inference:

| Measured matrix region | Elapsed seconds | Process CPU seconds |
|---|---:|---:|
| Native CPU matrices | 1.424882 | 5.454322 |
| OpenCL offload total | 9.408191 | 1.706841 |

The offloaded region used about 69% less process CPU time while taking much longer. Packing and readback were material costs. The offload-total row includes its component phases and must not be added to them again.

The GPU results also changed the downstream execution trajectory. The diagnostic recorded 37 output tokens for the CPU path and 47 for the GPU path in that run. Whole-inference CPU totals were therefore not measuring identical subsequent work.

A CPU-shadow diagnostic calculated GPU outputs for comparison but fed the original CPU outputs downstream. It restored the CPU-control transcript. This localized a numerical/execution-trajectory problem without pretending that the shadow path itself was a usable offload implementation.

These OpenCL observations are separate from the later Vulkan RTE reproducer. They do not establish that OpenCL and Vulkan shared the same internal driver defect.

### 4.2 Vulkan startup failures were not valid steady-state benchmarks

Early full Whisper Vulkan attempts encountered pipeline failures, then memory pressure and timeout behavior after a workaround. A run that exhausts memory or reaches a 300-second limit without completing a transcript cannot supply a trustworthy steady-state inference speed.

The OOM and swap-assisted timeout records remain useful diagnostics. They do not establish how fast a correct, resident, warm Vulkan inference would be.

### 4.3 We had to audit the harness too

The diagnostic path also needed correction before its numbers could be trusted:

- GGML's `k_split` push constant is the length of the K slice, not a split count. Treating it as 1 would not execute the intended matrix. Accepted matrix runs use K for this field.
- A retained specialization-map value of 16 was not the compiled BK value in the native-F16 module. Specialization ID 3 was absent from that SPIR-V.
- Earlier mixed-sign FP16 comparisons could be affected by accumulation order. We replaced that ambiguity with exact-input fixtures.
- A request for validation was initially being mistaken for active validation. Later suites require the layer to load and report active status.
- An early installation package also failed patches against the revised GUI. That was a packaging/source-version failure, not GPU performance evidence; the original binary/configuration were retained.

The lesson was to verify the actual shader, dispatch geometry, push constants, buffers and validation state before drawing a hardware conclusion.

## 5. The explicit-RTE failure

RTE means round to nearest, ties to even. The driver advertises RTE support for both 16-bit and 32-bit floating-point operations. Its reported rounding-mode independence is NONE, so the matching both-width case is important when examining the failure.

We reduced the problem to three variants of the same minimal matrix calculation:

| Variant | Added RTE control | Result over three 64x64 dispatches |
|---|---|---|
| Control | None | 12,288 correct outputs |
| Capability control | RoundingModeRTE capability only | 12,288 correct outputs |
| Explicit modes | RTE16 and RTE32 execution modes | 12,288 zero outputs, all incorrect |

Every input is exactly 1/32. Each product is 1/1024. Summing 64 terms must give exactly 1/16. Products and all partial sums are representable in binary16, so ordinary reassociation or fused-versus-separate arithmetic cannot explain zeros.

Both actual input buffers are echoed in the same device context. The input echoes pass. Full primary and packed-half output dumps show the incorrect zeros. The expected primary float bits are `0x3d800000`; the expected half bits are `0x2c00`.

The clean 0.4.1 diagnostic uses active target validation and records zero validation errors for all three cases. Both controls exit successfully; the explicit-mode case exits for numerical failure. The same failure was reproduced after the clock/voltage adjustment.

Other minimal shader forms and actual captured GGML matrix shaders fail earlier, at pipeline creation, with `VK_ERROR_UNKNOWN (-13)` under explicit RTE requests. A successful pipeline is therefore not sufficient evidence of correct execution.

This strongly implicates a driver/compiler interaction for these modules and this configuration. It does not identify an internal compiler pass, establish a defect in every FP16 operation, or certify general Vulkan conformance. Simple FP16 cases do pass.

### 5.1 Validation qualifications

Historical diagnostic runs reported `validation_requested=1` but `validation_active=0`. Their zero-error counter was not a validation pass.

The first exact-input follow-up used an older private layer and received descriptor-limit errors even for the working controls. Replacing that layer with 1.4.363 removed those messages without changing the runtime C code, shader modules or inputs. We did not filter or suppress the messages.

The accepted exact-input and recent GGML results require active target validation. Validation still cannot prove arithmetic correctness, which is why complete numerical checks remain necessary. Runtime float-control requirements also depend on the advertised width-independence properties; see reference [2].

### 5.2 Relationship to earlier public work

This was not the first report of the general problem. On October 6, 2026, `vliutyi` reported RTE-related pipeline failures and incorrect FP16 compute on an A733/BXM device using Android and driver `6643903` [1]. Our Linux driver is `6603887`.

Our contribution is additional Linux reproduction evidence: capability-only controls, exact-input full-output checks, active target validation, a repeat after the operating-point change, and tests of captured GGML modules. Different operating systems, driver builds and storage paths limit direct comparison. We do not claim a vendor acknowledgement or a tested fix in a newer DDK.

## 6. Workarounds and what each one actually fixes

### 6.1 Omit explicit RTE injection, retain the supported half path

Our experimental GGML patch gates FP16 RTE injection with:

```text
GGML_VK_POWERVR_DISABLE_FP16_RTE=1
```

This is a project patch, not a standard upstream GGML option or a vendor-supported switch.

The targeted change avoids adding the problematic explicit RTE mode. It does not globally disable FP16, fake supported features or indiscriminately strip shader decorations.

The captured GGML matrix tests returned:

| Float-control variant | FP16 accumulation | FP32 accumulation |
|---|---|---|
| Raw captured module | Passed exact fixture | Passed exact fixture |
| DenormPreserve16, no explicit RTE | Passed exact fixture | Passed exact fixture |
| RTE16 plus DenormPreserve16 | Pipeline error -13 | Pipeline error -13 |
| Matching RTE16 and RTE32 | Pipeline error -13 | Pipeline error -13 |
| DenormPreserve16 and DenormPreserve32 | Skipped: unsupported requirement | Skipped: unsupported requirement |

This establishes a working path for the tested modules and inputs, not arbitrary model accuracy. Removing an explicit rounding request must not be presented as proof that unrestricted numerical behavior is acceptable for Whisper.

### 6.2 Select FP32 accumulation for the tested matrix path

FP16 input/storage and FP32 accumulation are different choices. Our FP32-accumulation path still uses half inputs and shared storage; it is not a wholly FP32 data path.

In suite 0.2.0, the FFN-up shape took 1753.32 ms with FP16 accumulation and 1144.76 ms with FP32 accumulation. FFN-down took 1848.32 ms and 1174.56 ms respectively. All passed the controlled fixture. Subsequent tuning held FP32 accumulation fixed.

Those comparisons used BK32. We have not exhaustively retested every accumulation choice at every later tile. The final configuration is the best tested combination, not proof of a global optimum.

### 6.3 Set and verify a matched GPU clock/voltage pair

The original image read back 600 MHz and 800 mV. That pair matches the live table's nominal 600 MHz point; this evidence does not show that the original setting was undervolted.

The proprietary driver's fixed-clock path did not find its plain `clk_rate` property. The live table also declared a 1008 MHz / 960 mV point. We configured that matched pair rather than changing frequency alone.

The image-tool change sets the GPU clock property and the supply's minimum/maximum voltage constraints. It verifies supply/OPP identities and audits the device-tree delta. This became the image builder's default in 0.7.6. The current rig's later matrix tests confirm 1008 MHz and 960 mV through software readbacks before and after every case.

These are software interfaces, not an oscilloscope, an external voltage measurement or continuous load-stability telemetry. The RTE reproducer still fails after the adjustment. The setting is not an arithmetic fix. The fresh image builder output also needs its own full build/boot validation, separate from the already modified current rig.

### 6.4 Recompile BK instead of changing an ineffective specialization value

The native-F16 shader source contains:

```glsl
#if defined(DATA_A_F32) || defined(DATA_A_F16)
#define BK 32
#define BK_STEP 4
#else
layout (constant_id = 3) const uint BK = 16;
#define BK_STEP 2
#endif
```

For our native-F16 module, BK was compiled as 32. Setting specialization-map entry 3 to 16 did not change it because that specialization constant was absent.

We rebuilt the same source with BK16, BK8 and BK4, keeping BK_STEP at 4. The rebuilt BK32 module matched the captured original byte-for-byte. Later baseline modules also matched the preceding packages exactly. This made the tuning comparison much stronger than merely using the same shader filename.

In this non-cooperative path, the shared arrays use:

```text
shared bytes = (BM + BN) * (BK / 2 + padding) * 4
```

The factor 4 is the size of each `f16vec2`. With a 64x64 output tile and padding 1:

| Compiled BK | Declared shared bytes |
|---:|---:|
| 32 | 8704 |
| 16 | 4608 |
| 8 | 2560 |
| 4 | 1536 |

BK also changes loop structure and indexing. These tests do not isolate shared-memory allocation as the cause of improvement.

BK4 was tested with ALIGNED=0, where the active input loader reads half pairs. It was not validated here as a general BK4 replacement for the aligned LOAD_VEC=8 path. Copying the define into every upstream shader variant would exceed the evidence.

## 7. Controlled matrix benchmark method

Matrices use `D = A * B-transpose`, with A shaped M by K, B shaped N by K and D shaped M by N. Output storage follows the GGML layout used by the probe.

| Name | M | N | K |
|---|---:|---:|---:|
| Control | 512 | 512 | 512 |
| Projection | 512 | 1500 | 512 |
| FFN up | 2048 | 1500 | 512 |
| FFN down | 512 | 1500 | 2048 |

The three larger shapes are representative of the encoder operations under investigation. They are shape tests with a diagnostic fixture, not actual trained-model tensors.

### 7.1 Correctness controls

- CPU and GPU receive identical complete native-half input arrays.
- Inputs contain zeros and signed 1/32 values with deterministic row/K-dependent patterns.
- At the tested K sizes, every possible partial sum remains exactly representable, so ordinary accumulation-order differences do not invalidate the reference.
- Every output is checked against an integer-derived reference on every repeat.
- All output guards are checked. Complete final outputs and complete inputs are retained for independent CPU/GPU comparison.
- Echo checks cover the first 4096 values of each actual GPU input buffer.
- Target validation must be active. Normal board runs reject software fallback.
- CPU library hashes and shader hashes are retained; the CPU libraries are checked again after the batch.
- GPU clock/voltage are checked before and after each isolated process. CPU governor/frequency and temperatures are recorded without changing settings.

The exact fixture deliberately makes the correctness question unambiguous. It does not cover arbitrary model weights, overflow, denormals, special values or every possible tail shape.

### 7.2 Timing definitions

Each case has one warm-up and three measured repeats. Tables show the mean of repeats 1, 2 and 3, excluding repeat 0.

**CPU elapsed and process CPU:** the existing GGML graph-compute call, using four threads. Process CPU sums work across threads and can exceed elapsed time.

**GPU elapsed and process CPU:** host submit/fence-wait interval for the matrix dispatch. CPU work performed by the measured process during that interval is recorded separately from wall time.

Input preparation, reference scanning and output-file writes are outside those intervals. Pipeline creation is logged separately. Whole-process startup, validation, compilation and output costs remain in the per-case metrics.

GPU timestamp durations are retained only as diagnostics. Earlier minimal runs sometimes reported converted GPU durations longer than their corresponding host submit/wait interval. We did not resolve that inconsistency, so GPU timestamps do not select winners or support GFLOP/s claims.

The tests use the validation layer and fixed sequential order. Driver caches were not cleared. Three warm repeats are a bounded tuning screen, not a statistical study, a cold-start benchmark or sustained-load acceptance. CPU timing varies between batches; compare variants within a batch rather than treating separate runs as one simultaneous experiment.

### 7.3 Process and service controls

The runner holds the existing build/test lock, stops the audio service during measurement and preserves its initial state. Initially stopped audio stays stopped. Initially active audio is restored at exit. Each process has a 90-second limit; GPU fence waits have a 60-second limit. Failed cases are recorded, and the overall batch remains failed if any case fails.

There is no automatic production activation. No GPU busy-percentage, energy-saving or continuous utilization claim is derived from these timings.

## 8. Results: compiled K-tile comparison

Suite 0.4.0 held the output tile at 64x64, padding at 1 and accumulation at FP32.

Elapsed milliseconds, warm means:

| Shape | CPU | BK32 | BK16 | BK8 |
| --- | --- | --- | --- | --- |
| Control | 9.24 | 91.59 | 38.31 | 19.55 |
| Projection | 18.63 | 312.87 | 112.75 | 57.56 |
| FFN up | 67.96 | 1114.15 | 448.30 | 232.02 |
| FFN down | 65.60 | 1261.38 | 445.80 | 226.23 |

BK8 delivered a 4.7-5.6x elapsed-time speedup over BK32 in this batch. This was the major tuning improvement. The CPU control's timing differs from subsequent batches, which is why each table retains its own CPU result.

## 9. Results: BK4 and removing padding

Suite 0.5.0 tested two independent changes against BK8: BK4 with padding retained, and BK8 with padding removed. The changes were not combined.

Elapsed milliseconds, warm means:

| Shape | CPU | BK8 | BK4 | BK8, padding 0 |
| --- | --- | --- | --- | --- |
| Control | 6.53 | 20.31 | 19.31 | 25.33 |
| Projection | 17.84 | 60.64 | 54.89 | 73.88 |
| FFN up | 67.84 | 240.10 | 213.09 | 298.06 |
| FFN down | 65.53 | 223.33 | 218.08 | 283.73 |

BK4 reduced elapsed time by 2-11% relative to BK8. Removing padding increased BK8 elapsed time by 22-27%, even though declared shared memory fell from 2560 to 2048 bytes. Reducing the shared-memory byte count alone was not a reliable predictor of speed.

## 10. Results: smaller output tiles at BK4

An earlier BK32 screen had already found smaller output tiles slower. Suite 0.6.0 repeated the question at BK4 using two valid profiles:

| Profile | Output tile | Workgroup invocations | Declared shared bytes |
|---|---|---:|---:|
| medium64 | 64x64 | 128 | 1536 |
| compact32 | 32x32 | 32 | 768 |
| compact16 | 16x16 | 32 | 384 |

These profiles change coupled specialization values and dispatch counts. They are not a single-variable test of tile dimensions alone.

Elapsed milliseconds, warm means:

| Shape | CPU | 64x64 | 32x32 | 16x16 |
| --- | --- | --- | --- | --- |
| Control | 7.67 | 18.38 | 22.60 | 28.27 |
| Projection | 20.55 | 54.61 | 67.34 | 80.03 |
| FFN up | 68.01 | 213.94 | 256.22 | 319.71 |
| FFN down | 65.15 | 222.12 | 285.79 | 324.41 |

The 32x32 profile took 20-29% longer than 64x64. The 16x16 profile took 46-54% longer. The baseline won on every shape, despite its larger declared shared-memory requirement.

All 16 processes in each of suites 0.4.0, 0.5.0 and 0.6.0 exited successfully. Independent readback checks confirmed identical full CPU/GPU input bytes, matching final output arrays, intact guards, zero validation errors, stable CPU library hashes and the expected before/after power readings.

### 10.1 CPU work in the latest batch

| Shape | CPU baseline: CPU ms | GPU call: CPU ms | Process CPU reduction | GPU / CPU elapsed |
| --- | --- | --- | --- | --- |
| Control | 24.477 | 0.425 | 98.27% | 2.40x |
| Projection | 78.746 | 0.705 | 99.10% | 2.66x |
| FFN up | 267.207 | 2.478 | 99.07% | 3.15x |
| FFN down | 257.494 | 2.767 | 98.93% | 3.41x |

The saving is calculated as `1 - GPU_process_CPU / CPU_process_CPU` for the measured intervals. It does not include the complete inference, kernel threads in other processes, all system CPU activity or energy consumption.

This is why the kernel result is promising despite longer elapsed time: the measured process does very little CPU work while the GPU executes. Whether the rest of the audio application benefits still requires integration testing.

### 10.2 A separate geometry finding

The source-derived stock-small specialization tuple for subgroup size 1 failed our output-coverage audit: it assigned four logical warps where its tile required one. We did not dispatch that tuple. The compact32 profile above uses a valid different subdivision.

This is a static source/indexing finding. We did not capture a live Whisper dispatch using that invalid tuple, so it is not established as the cause of the earlier model timeout. Logical shader WARP geometry must also not be confused with the hardware-reported subgroup size of 1.

## 11. Best tested configuration and current limits

| Setting | Best tested value |
|---|---|
| Runtime | Existing Linux PowerVR Vulkan bundle |
| Input and shared storage | Native FP16 |
| Accumulation / output | FP32 / FP32 |
| Explicit RTE injection | Disabled for the experimental path |
| DenormPreserve16 | Retained |
| Compiled BK / BK_STEP | 4 / 4 |
| Output tile | 64x64 |
| Shared padding | 1 |
| Workgroup invocations | 128 |
| ALIGNED | 0 |
| GPU operating point | 1008 MHz / 960 mV software readbacks |

The source-reconstructed medium64 specialization map, IDs 0 through 11, is
`128,64,64,16,8,32,2,4,2,1,8,0`. Entry 3 is inactive in this module; compiled
BK is 4. These values configure the standalone probe and are not a captured
live Whisper dispatch.

This configuration is verified in the standalone matrix harness. It has not been established as the active configuration throughout an integrated Whisper graph.

The practical outcome is a corrected diagnosis and a substantially improved kernel baseline. We moved from an unqualified statement that GPU offload was simply slow to specific, reproducible findings about correctness, compilation, K tiling, padding, output geometry and CPU work.

**The original 24/7 Whisper-offload goal is not yet complete.** No tuned Vulkan end-to-end transcript/latency/CPU acceptance run has passed, and no production service activation is claimed.

## 12. What is still required for full Whisper acceptance

1. Integrate the tested native-F16, unaligned BK4 path into an isolated GGML build without changing unrelated CPU compiler flags, decoder settings or model configuration.
2. Capture the actual selected shader, specialization tuple, push constants and dispatch geometry from the integrated workload. Do not assume the standalone profile is automatically selected by GGML.
3. Use the same model bytes, audio bytes, thread count, decoding options and operating point for CPU and GPU comparisons. Separate model/pipeline startup from warm inference.
4. Verify real intermediate tensors and complete transcripts. Keep the existing transcript-difference gate until any alternative numerical or accuracy criterion is explicitly defined and justified. Do not loosen a gate merely to approve a result.
5. Measure complete process CPU, elapsed time, packing/transfers, encoder, decoder, memory use and fallback behavior. A changed transcript can change the amount of decoder work and invalidate a simple CPU-saving comparison.
6. Check the actual audio arrival rate and sustained queue behavior. A kernel taking three times the CPU elapsed time can still be useful only if the complete application meets its deadline.
7. Run sustained audio with thermal/memory monitoring and recovery checks before enabling the GPU path for normal service.

If the graph needs unsupported or failing operations, explicit CPU fallback may be necessary. It must be recorded as fallback, not concealed as GPU execution. The right outcome may be selective offload rather than putting the entire model on the GPU.

## 13. Reproduction artifacts and evidence map

The document is self-contained as a findings report. The named diagnostic packages and archives are separate artifacts; the Markdown alone does not contain their source or binary output dumps.

| Artifact | Purpose |
|---|---|
| `POWERVR_BXM_RTE_VENDOR_REPRO_1.2.zip` | Focused exact-input RTE reproduction, with historical evidence separated |
| `opi-vulkan-diagnostic-0.4.1.zip` | Minimal arithmetic controls with active private validation |
| `opi-ggml-vulkan-capture-0.1.0.zip` | Captured existing GGML modules, source and build provenance |
| `opi-ggml-vulkan-test-0.4.0.zip` | BK32 / BK16 / BK8 controlled matrix batch |
| `opi-ggml-vulkan-test-0.5.0.zip` | BK8 / BK4 / BK8 without padding |
| `opi-ggml-vulkan-test-0.6.0.zip` | BK4 with medium64 / compact32 / compact16 |
| `opi-3w-wbuild-0.7.6.zip` | Image builder incorporating the matched GPU clock/voltage default |

For the current test rig, the latest matrix package runs as root:

```bash
unzip opi-ggml-vulkan-test-0.6.0.zip
cd opi-ggml-vulkan-test-0.6.0
bash run.sh
```

It depends on the existing board runtime, pinned GGML source headers and CPU libraries. It is not a universal installer for another SBC. It builds small native C probes, reuses the CPU libraries, uses bundled shaders and a private validation layer, preserves initial service state and prints one evidence archive.

To reproduce the minimal failure separately:

```bash
unzip POWERVR_BXM_RTE_VENDOR_REPRO_1.2.zip
cd POWERVR_BXM_RTE_VENDOR_REPRO_1.2
bash run.sh
```

A numerical failure exit is expected if the explicit-RTE bug reproduces. Review the case logs rather than treating every nonzero exit as the same problem.

### 13.1 Evidence archives

All archive timestamps below are UTC. Archive names identify the original physical-board runs.

| Archive | What it establishes | SHA-256 |
| --- | --- | --- |
| `work-20261113T010712Z-pwtWWg-evidence.tar.gz` | Early OpenCL activation rejection | `8d27838adef489a46a9732a507a7a1c270fcd676fa90bd241c81e9842ac524b6` |
| `results-20261113T013853Z-w7EUCA.tar.gz` | OpenCL phase and CPU-shadow diagnostic | `3d8685a5c8a97aa4ecbfdc8affdf93925ea348eed72e5e5c31c67ad5b5a291e8` |
| `results-20261113T040521Z-Y8U5XN.tar.gz` | Exact-input RTE, clean target validation | `ab04738a0db5332ca15e08f237617911a7facd62b898f59b7eb7359e74a8c07b` |
| `power-20261113T041757Z-PQhzEc.tar.gz` | Original operating-point investigation | `bcdb187900d0bbc7744e2ce2ed2895010b57bad3b32b460c893d1aef9bad67a4` |
| `results-20261113T044845Z-Es9CHX.tar.gz` | Exact-input RTE repeat after power adjustment | `1ae31674c10948ad1ce1f5348e2b67340484187eac9a939b4d5b814254fb2650` |
| `capture-20261113T045036Z-4SvyqV.tar.gz` | Captured GGML/source provenance | `be6c405800516101bdf51343841afa3304105813d06ac24e30ab3e8062dfae9c` |
| `results-20261113T050148Z-nxGbEw.tar.gz` | Captured GGML float-control matrix | `8f30ec4d87b986df93969154bd4e38e7a4f2e927e3567be7995b14b7b3ad2729` |
| `results-20261113T052218Z-BZh2ox.tar.gz` | Initial CPU/FP16-acc/FP32-acc shapes | `95dabc1e2167680ea94820a87263d0bab2d05e17494256106b3fe919d90454b3` |
| `results-20261113T123023Z-AZfqNM.tar.gz` | Earlier BK32 output-tile screen | `ef9b01e4ee6a3ee72fdba1064f43a56233d6b3d6c01543ff58b2d7402344c2d1` |
| `results-20261113T124701Z-wn2lXy.tar.gz` | BK32/16/8 batch | `7ace856bcdf410cba235f9e6c9ff5b0f5b94f8b69e2660d23e88c88577aeeee6` |
| `results-20261113T125507Z-DStGPN.tar.gz` | BK4 and padding batch | `975bad1cdb7b68cbe024cfa66346ea70beb5381e4eee9ab91ea212fdf0ce8b9e` |
| `results-20261113T130435Z-YGoQvJ.tar.gz` | BK4 output-tile batch | `21a36c1ddd542403db592f5ba43f36bc9a048ce12c1e203b3fae8cda30385713` |

### 13.2 Key identities

| Identity | SHA-256 |
| --- | --- |
| PowerVR ICD | `ab5b2819883f46a3722c8304a1a5fdd68c257c16d2a4918def0b274ef3472a0e` |
| Captured raw FP32-accumulation module | `1bfac2fc609f14a41cb652df6085f32f6f1e90835c33afe1fce8bc600988d829` |
| BK32 with DenormPreserve16 | `73a4b8a7771a28ce47ecb8bbe5d8cab9fe16b5868feb881970f78c9769e15c45` |
| BK8 with DenormPreserve16 | `ace8bc86617c970ecb178701cea7167de0bf13b6dc9c6052d211edb9610676a0` |
| BK4 with DenormPreserve16 | `eb55db99dad0c6b7ee29c193653505f4f3007dfb0bfee0015a57ce3fd395179e` |
| PowerVR Vulkan library, recorded on board | `6bbb29dff35d3b80886d6007aab45f892e399789dcc7a1b2586361a15242db12` |
| Existing GGML CPU library, recorded on board | `ef1a10bbe4dbd6ab321252aecd7fdae301e044cf0dab6f3f580f975b45b9349d` |
| Existing GGML base library, recorded on board | `c252482bc425e22920a6ce3771d522725fb8e67d6d8f5ca2e2e1630d46a3da1f` |

Each package/result archive also retains its own SHA-256 manifests and compiler/source provenance. Baseline byte equality was checked separately from filename equality.

## 14. Questions this evidence can help answer

For developers encountering a similar BXM problem:

- Does removing only explicit RTE requests change pipeline creation or exact numerical output?
- Is the validation layer actually active, and are runtime feature/float-control requirements satisfied?
- Is the tested BK value compiled into the module or exposed as a live specialization constant?
- Does an apparently smaller tile increase dispatch count or produce a worse workgroup/indexing configuration?
- Are host elapsed time, process CPU time, pipeline creation and GPU event durations being mixed together?
- Did different numerical output cause the decoder to do different work?

For a driver/compiler investigation, the remaining central question is why the explicit-RTE modules fail or return zeros on an implementation that advertises the corresponding support. An internal compiler trace and independent reproduction on another board or DDK would be useful. This report does not invent an answer to that question.

## References and credit

[1] vliutyi, PowerVR Developer Community Forums, October 6, 2026. Earlier report of RTE-related pipeline failure and incorrect FP16 compute on A733/BXM under Android with a different DDK build:  
[Reference 1](https://forums.imgtec.com/t/bxm-4-64-vkcreatecomputepipelines-fails-vk-error-unknown-on-valid-spir-v-using-roundingmoderte-16-and-fp16-compute-returns-wrong-results/4305)

[2] Khronos Vulkan Specification, Vulkan Environment for SPIR-V. Runtime float-control and independence requirements:  
[Reference 2](https://docs.vulkan.org/spec/latest/appendices/spirvenv.html)

The matched clock/voltage investigation also drew on the community A733/PowerVR bring-up work recorded in our image-tool documentation, including `davidhfrankelcodes/pvr-a733-armbian` and the Orange Pi kernel/device-tree sources. That credit does not imply those projects produced these measurements or endorsed these conclusions.

Custom diagnostic code carries its package license; upstream GGML, Vulkan headers and validation-layer notices remain with their respective artifacts. No upstream merge, vendor endorsement or production certification is implied.
