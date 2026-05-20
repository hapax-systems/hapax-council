# 60fps egress cadence feasibility + VRAM impact analysis

**Date:** 2026-05-20
**Task:** `60fps-egress-feasibility-research`
**Authority:** `CASE-SDLC-QUEUE-CLEARANCE-2026-05-17`
**Status:** research + deterministic sizing helper

## Headline

Do **not** flip the live compositor to 60fps yet. At 720p, 60fps does not
meaningfully increase standing VRAM by itself, because the relevant GStreamer
queues and SHM rings are frame-count bounded. It does double post-FX, BGRA,
NV12, SHM, v4l2, HLS, and encoder throughput. The current runtime evidence is
not ready for that: the deployed compositor is in `HAPAX_3D_COMPOSITOR=1`, the
camera source publisher is intentionally capped at 6fps, and the live metrics
currently show no v4l2/shmsink egress frames.

The safe next move is a controlled 60fps canary only after the egress path is
back to proven 30fps with fresh v4l2/HLS evidence.

## Current code path

The source defaults remain `1280x720@30` in
`agents/studio_compositor/models.py` and `agents/studio_compositor/config.py`.
`build_pipeline()` carries that `fps` through:

- compositor caps: `video/x-raw,format=BGRA,width=...,height=...,framerate=fps/1`
- v4l2 bridge branch: `output_tee -> queue-v4l2-egress -> interpipesink`
- shmsink bridge: `interpipesrc -> videorate -> NV12 -> shmsink`
- HLS branch: `output_tee -> queue -> valve -> videorate -> cudaupload -> nvh264enc`
- RTMP bins: detached by default, with `gop_size=fps * 2`

So changing `CompositorConfig.framerate` to 60 is mechanically plausible for
the GStreamer path, but it is not a proof that real source frames or public
egress run at 60fps. Low-rate cameras will be duplicated by `videorate`, not
made more temporally real.

## Deterministic sizing

The source helper `shared.egress_cadence_feasibility` records the byte-rate and
standing-buffer math used here. For `1280x720`:

| Item | 30fps | 60fps | Delta |
| --- | ---: | ---: | ---: |
| NV12 stream | 39.55 MiB/s | 79.10 MiB/s | +39.55 MiB/s |
| BGRA stream | 105.47 MiB/s | 210.94 MiB/s | +105.47 MiB/s |
| SHM write + v4l2 bridge write | 79.10 MiB/s | 158.20 MiB/s | +79.10 MiB/s |
| Standing queue/ring allocation | unchanged | unchanged | +0 MiB |

The standing allocation stays flat because queue depths are expressed as frame
counts (`shmsink` ring 8 frames, bridge queue 5, appsink 2, HLS queue 20, RTMP
queue 30). Cadence changes how often those buffers turn over, not their size.

CLI:

```bash
scripts/hapax-60fps-egress-feasibility --json
```

## Live evidence captured

Snapshot commands used:

- `scripts/compositor-vram-snapshot.sh`
- `curl -sf http://127.0.0.1:9482/metrics`
- `systemctl --user cat studio-compositor.service`
- `nvidia-smi --query-gpu=index,name,memory.total,memory.used,utilization.gpu,utilization.memory`

Observed at `2026-05-20T04:2xZ`:

- `studio-compositor.service` is active from the source-activation worktree,
  not from this task checkout.
- A local drop-in sets `HAPAX_3D_COMPOSITOR=1`, which bypasses the GStreamer
  compositing/FX/v4l2 output path in `pipeline.py`.
- The incident containment drop-in sets `HAPAX_CAMERA_SOURCE_PUBLISH_FPS=6`
  and `HAPAX_CAMERA_FRAME_CACHE_TARGET_FPS=6`.
- Metrics show `studio_compositor_v4l2sink_frames_total 0`,
  `studio_compositor_shmsink_frames_total 0`, and both last-frame gauges at
  `9999`.
- `studio_compositor_gpu_vram_bytes` reports `0`, which is consistent with the
  current 3D bypass not exercising the historical GStreamer compositor VRAM
  gauge.
- GPU totals: RTX 3090 `21920/24576 MiB`, RTX 5060 Ti `12062/16311 MiB`.

That means the live system cannot currently prove even 30fps v4l2/shmsink
egress from the GStreamer branch, so 60fps should not be enabled from this
state.

## VRAM impact

Expected standing VRAM delta for 720p30 -> 720p60 is small. The same resolution
uses the same frame sizes and frame-count-bounded queues. The risk is not
static buffer allocation; the risk is doubled per-second churn through:

- post-FX output tee and BGRA caps
- NV12 conversion/upload for HLS and bridge output
- NVENC encode scheduling for HLS/RTMP
- SHM write plus sidecar `os.write()` into `/dev/video42`
- any proof snapshots or downstream pixel checks if accidentally raised with
  cadence

Prior VRAM attribution on 2026-04-14 found the compositor's 3GB footprint was
structural. This task does not overturn that. For 60fps, expect a canary to
watch GPU utilization, encoder utilization, write-error deltas, and RSS growth
more closely than standing VRAM.

## Recommendation

1. Keep production at 30fps until v4l2/HLS metrics again show healthy 30fps
   egress from the path being changed.
2. Do not combine a 60fps canary with 3D-mode restoration, camera source
   publisher uncapping, or source-activation worktree reconciliation.
3. For a canary, use a branch/drop-in that changes only output cadence and
   captures before/after:
   `studio_compositor_render_stage_frames_total`, HLS parser FPS,
   bridge writer FPS, `hapax_v4l2_bridge_write_errors_total`, GPU memory,
   GPU/NVENC utilization, and `studio_compositor_memory_footprint_bytes`.
4. Accept 60fps only if stage FPS is >=54fps, v4l2/HLS write errors remain
   flat, RSS growth is below 128MiB, VRAM growth is below 256MiB, and no
   source-publisher containment flag remains below the target cadence.
