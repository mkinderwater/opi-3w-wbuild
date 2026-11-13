# Validation of 0.7.6

This release makes GPU 1008 MHz / 960 mV the normal image-build setting.
The selected DTB is changed directly, not through an optional overlay.

Local suite: 97 tests run; 11 skips. The skipped groups require unavailable
native filesystem tools or OpenCL/Vulkan/VIPLite development headers. They
are not recorded as passed. Existing provisioning, expansion logic, module
staging, Windows launchers and verification tests remain in the suite.

The new tests execute real dtc/fdtput operations and verify the intended DTB
changes, unchanged CPU and microphone properties, original-DTB retention,
original/configured manifest checks, rejection of wrong supply/OPP/shared-rail
inputs, rejection of unrelated DT/boot changes, and runtime readback results.
Missing clock readback leaves operating-point confirmation false.

The full returned live DTB from power-20261113T041757Z-PQhzEc.tar.gz was also
processed locally. Full node/property/memory-reservation comparison passed:
only GPU clk_rate and the GPU regulator min/max voltage constraints changed.
The virtual dcdc4 consumer was recognized; no other supply consumer was allowed.
This does not execute the DTB on the board.

The source compiles as Python, and build.sh passes Bash syntax checking.
A complete fresh WSL build and a board boot of the resulting 0.7.6 image are
still pending. The current board was not remotely changed. No Whisper speedup
or FP16 arithmetic fix is claimed before those measurements.
