# Screwm Quake Runtime Reset Containment — 2026-05-23

## Scope

Task: `20260523-screwm-quake-texture-ward-migration`

This note records the runtime containment decision after an unexpected host reset
during Screwm -> DarkPlaces migration work. It is evidence intake for the next
hardware-validation pass; it is not a release dossier.

## What Happened

At approximately 2026-05-23 12:42 CDT, `hapax-darkplaces.service` was restarted
to load rebuilt Screwm assets and QuakeC. The renderer started and loaded the
Screwm map. The prior boot journal ends abruptly at 2026-05-23 12:45:02 CDT.
The next boot started at 2026-05-23 12:46:52 CDT.

There is no orderly `systemd` shutdown or reboot sequence in the prior boot
journal. The next boot reported:

```text
x86/amd: Previous system reset reason [0x08000800]: an uncorrected error caused a data fabric sync flood event
```

The EFI filesystem also reported a dirty bit and that it was not properly
unmounted. That supports an abrupt hardware/kernel reset rather than a clean
reboot command.

## Hardware Context

The operator reported that two GPUs were recently installed and workloads were
rebalanced earlier the same day. Current observed NVIDIA topology:

```text
GPU 0: NVIDIA GeForce RTX 5090, PCI 00000000:01:00.0
GPU 1: NVIDIA GeForce RTX 5060 Ti, PCI 00000000:05:00.0
```

Current workload observation after reboot:

```text
GPU 0: KDE / display processes
GPU 1: hapax-imagination, hapax-daimonion
```

The DarkPlaces unit attempted to avoid GPU 0 with `CUDA_VISIBLE_DEVICES=1`, but
DarkPlaces is an OpenGL renderer. The pre-reset DarkPlaces log showed:

```text
GL_RENDERER: NVIDIA GeForce RTX 5090/PCIe/SSE2
```

Therefore the intended CUDA pin did not constrain the OpenGL renderer. The
renderer ran on the display/GL-selected 5090, not necessarily the planned
5060 Ti partition.

Post-containment `glxinfo -B` evidence on `:0` also reports the RTX 5090 as the
default OpenGL renderer. `DRI_PRIME=1` and the usual NVIDIA PRIME offload
environment did not change the reported renderer on this host, so a DarkPlaces
launch on the current display path is not yet validated for the intended GPU.

## Containment Decision

DarkPlaces runtime is opt-in only until a governed hardware-validation session
can test the renderer feed without reproducing the reset.

Applied containment:

- Disabled and stopped `hapax-darkplaces.service`
- Disabled and stopped `hapax-darkplaces-bridge.service`
- Added `ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime` to:
  - `hapax-darkplaces.service`
  - `hapax-darkplaces-bridge.service`
  - `hapax-darkplaces-v4l2.service`
- Added `scripts/darkplaces-runtime-guard.sh` and sourced it from direct launch
  scripts, so terminal invocation also requires explicit acknowledgement.
- Added `scripts/darkplaces-attended-smoke.sh` so the next validation pass has a
  bounded, evidence-producing read-only mode plus explicitly acknowledged
  window/v4l2 launch modes. Launch modes capture DarkPlaces stdout/stderr and
  fail closed before launch if `glxinfo` already reports the wrong display GL
  renderer, and after launch unless DarkPlaces' own `GL_RENDERER` matches the
  expected GPU name.
- Left the production stream on the known-good `hapax-imagination` -> `/dev/video42`
  path.
- Re-enabled `hapax-imagination.service` for boot continuity after confirming it
  is the sole writer to `/dev/video42`; DarkPlaces units remain disabled.

## Next Validation Requirements

Before re-enabling DarkPlaces runtime:

- Capture PCIe link state for both NVIDIA GPUs and the relevant root ports.
- Validate the intended OpenGL/Vulkan GPU selection method; do not assume
  `CUDA_VISIBLE_DEVICES` affects DarkPlaces.
- Run an attended, bounded renderer smoke test with `nvidia-smi pmon`,
  `journalctl -k -f`, and power/temperature capture.
- Use `scripts/darkplaces-attended-smoke.sh --collect-only` before any launch;
  only run `--window` or `--v4l2` with `HAPAX_DARKPLACES_SMOKE_ACK=1` in an
  attended validation window.
- Leave `HAPAX_DARKPLACES_EXPECTED_GPU_INDEX=1` unless the validation owner
  intentionally changes the target GPU; the harness resolves this to the
  current GPU 1 name and checks DarkPlaces' reported `GL_RENDERER`.
- Keep `hapax-imagination` as the stream writer until `/dev/video52` is proven
  stable under DarkPlaces output.
- Do not enable DarkPlaces units at boot until the reset cause is understood.
