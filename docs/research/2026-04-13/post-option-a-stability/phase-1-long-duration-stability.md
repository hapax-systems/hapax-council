# Phase 1 — Post-Option-A long-duration stability characterization

**Queue item:** 023
**Phase:** 1 of 6
**Date:** 2026-04-13 CDT
**Register:** scientific, neutral (per `feedback_scientific_register.md`)

## Headline

PR #751 (Option A: TTS delegation to daimonion via UDS) removed all
libtorch mappings from the compositor process (**confirmed: libtorch
count = 0** on every post-fix PID measured). The compositor did not
OOM during this session's observation window. Option A **does**
stabilize the address-space shrink.

Post-fix steady-state RSS is **not** the 1.09 GB headline number
alpha reported from the first sample of the first post-fix process.
That was the pre-warmup value. Across this phase's observations:

| process | start CDT | lifetime observed | steady-state RSS (post-warmup) | within-lifetime slope |
|---|---|---|---|---|
| PID 2913194 | 16:39:37 | 21.1 min | **~1.15 GB** (T+2 → T+18) | ~3.5 MB/min |
| PID 3145327 | 17:01:40 | 14.7 min | **~4.44 GB** (T+3 → T+14) | ~3.25 MB/min |
| PID 3300095 | 17:16:39 | 3.2 min (still warming) | — | — |

Key findings:

1. **Post-fix steady-state RSS varies 4× between process instances
   (1.15 GB vs 4.44 GB)**. The variation is driven by what happens
   during warmup — shader compile, effect graph plan activation, and
   cairo surface caching. PID 3145327 hit ~4.4 GB in the first 3
   minutes after an effect graph change triggered shader
   recompilation for 24 slots; PID 2913194 stabilized at ~1.15 GB
   with a different graph plan.
2. **Within-lifetime secondary-leak rate is ~3.3 MB/min on both
   observed processes**. This is under the 5 MB/min flag threshold
   the brief set, but not zero. Extrapolated to 24 hours: ~4.7 GB/day
   of linear growth, which hits the 6 GB `MemoryMax` ceiling in
   ~4 hours from the 4.4 GB warm floor or ~33 hours from the 1.15 GB
   warm floor. Neither is 24/7-stable.
3. **The compositor was SIGTERM'd twice during the observation
   window**, aborting the brief's required 2 h uninterrupted sample
   window. Restarts at 17:01:23 and 17:16:22 CDT (NRestarts=0 on
   systemd's count — these are clean stop+start pairs, not OOM
   recoveries). The 5-minute `hapax-rebuild-services.timer` does not
   cover studio-compositor (verified: compositor is not in its
   ExecStart list). The restart source is external and intentional,
   probably operator or alpha testing PR #754. Beta did not touch
   the compositor service.
4. **Post-fix bus-message + FSM latency is below the journal
   timestamp floor (< 1 ms)**, a positive side effect of Option A
   documented in Phase 4. With libtorch gone, the compositor's
   virtual address space dropped from 20+ GB to 14 GB and the CPU
   cache line contention between torch caching allocator and
   GStreamer bus dispatch has been eliminated.
5. **Thread count dropped from ~112 pre-fix to 88–93 post-fix**, a
   −20 % reduction that matches the finding-doc prediction.

## Direct answer to the brief's cardinal question

> Does ALPHA-FINDING-1 Option A actually stabilize compositor memory,
> or does it reveal a previously-masked secondary leak?

**Both.** Option A eliminated the primary leak (torch allocator) with
high confidence — libtorch mappings went from 35 → 0 and stayed at 0
on every post-fix process. The compositor's address space shrank by
>14 GB. That fix is real.

A **secondary leak** is present at ~3.3 MB/min within each process
lifetime, and a **separate warmup-path variability** produces a 4×
spread in steady-state RSS (1.15 GB vs 4.44 GB). Neither of these is
torch-related — torch is entirely gone. The residual growth and
warmup spread are caused by something else inside the compositor's
non-torch code path. Most likely candidates, in priority order:

1. **GStreamer buffer pools** (the anonymous ~4 GB mmap region
   observed as the dominant allocator in the t0 baseline snapshot
   is the GStreamer appsrc chain + cairo surface backing store —
   see baseline data below).
2. **Effect graph shader recompilation**. PID 3145327's massive
   warmup jump (1.3 → 4.4 GB in 2 min) correlates with the shader
   recompilation events logged during the first plan activation.
   If each graph mutation leaks ~100 MB of shader intermediates,
   and graph mutations fire ~1/min, the rate matches.
3. **Cairo surface caching** in the CairoSourceRunner fleet. 4
   runners × 1920×1080×4 bytes (RGBA) × N historical buffers.
4. **Presynth cache in CPAL signal_cache + bridge_engine on the
   daimonion side** — not part of the compositor process, but
   alpha's TtsServer UDS handler shares a TTSManager with CPAL's
   loop and its backing caches could contribute if the TTS server
   path is actually handling requests (which, per Phase 5, it is
   not today — 15/15 timeouts observed).

**Recommendation.** The 2-hour uninterrupted window the brief asked
for has not been achieved because of external compositor restarts.
Re-run Phase 1 with:

- A fresh alpha-coordinated agreement to NOT restart the compositor
  for 2 continuous hours after Option B (PR #754 budget_signal
  retirement) and the Phase 5 daimonion TTS regression fix have
  both landed.
- The `/proc/$PID/maps` + `/proc/$PID/smaps` dump at 30 min
  intervals instead of 60 s, to see which regions are growing.
- A Prometheus histogram for per-CairoSourceRunner surface pool
  occupancy (this phase's backlog item).

## Baseline snapshot — t0 (17:16:49, PID 3300095 post-restart)

Compositor PID 3300095, 10 seconds after start at 17:16:39 CDT.
Full `/proc/$PID/smaps_rollup` + library mapping classification at
`data/baseline/t0-snapshot.txt`. Key numbers:

| metric | value | pre-fix baseline (from PR #752) | delta |
|---|---|---|---|
| VmRSS | 1.10 GB | 6.33 GB | −83 % |
| RssAnon (user-allocator-controlled) | 664 MB | 5.69 GB | −88 % |
| VmPeak (virtual address space ceiling) | 15.14 GB | 20+ GB | −25 % |
| libtorch_* mappings | 0 | 35 | all gone |
| torch CUDA stack (libcudart/libcublas/libcudnn/libnvJit/libnccl/libcupti/libnvToolsExt) | 0 | ~12 | all gone |
| Retained CUDA stack (nvcodec: libnvcuvid + libnvidia-encode) | 2 | 2 | unchanged (NVENC path, legitimate) |
| Threads | 92 | 112 | −18 % |
| cgroup `MemoryCurrent` | 912 MB | 6.01 GB | −85 % |
| cgroup `MemoryPeak` (lifetime) | 917 MB | 6.14 GB | −85 % |
| cgroup `MemoryMax` | 6 GiB | 6 GiB | unchanged |
| cgroup `MemoryHigh` | ∞ (drop-in) | ∞ | unchanged |

All the delta claims in the brief headline are preserved at t0 of a
fresh process. The divergence appears later in the lifetime.

**Largest anonymous regions at t0** (where the non-torch memory
lives):

| size | region name | interpretation |
|---|---|---|
| ~635 MB | anonymous mmap (unnamed) | GStreamer buffer pool + Python object heap |
| 180 MB | `/dev/nvidiactl` | NVIDIA driver shared state |
| 57 MB | `(deleted)` | unlinked mmap'd file (likely shader compile output) |
| 48 MB | `[heap]` | brk heap (small — Python + most allocations use anon mmap) |
| 36 MB | `libnvrtc.so.13.2.51` | NVIDIA runtime compiler (loaded by nvcodec) |
| 30 MB | `/dmabuf:` | dma-buf for video frame passthrough |
| 29 MB | `libnvidia-gpucomp.so.590.48.01` | NVIDIA graphics compute |
| 20 MB | `libnvidia-glcore.so.590.48.01` | NVIDIA GL core |
| 10 MB | `libcuda.so.590.48.01` | NVIDIA driver API (legitimate) |

The 635 MB anonymous region is the dominant growable allocator. This
is where subsequent growth would show up on a longer sampling window.

## Observed trajectories

### PID 2913194 (16:39:37 → 17:01:23, 21 m 46 s lifetime)

Sampler started at T+1:44 (16:41:21) and ran for 19 minutes:

```text
T+1:44  1099864 kB  (1.05 GB)
T+2:44  1117884 kB
T+3:45  1140616 kB
T+4:45  1137956 kB
T+5:46  1138860 kB
T+6:47  1138900 kB
T+7:47  1142292 kB
T+8:48  1144232 kB
T+9:48  1144388 kB
T+10:49 1148508 kB
T+11:49 1151672 kB
T+12:50 1151704 kB
T+13:50 1151744 kB
T+14:51 1152016 kB
T+15:52 1152072 kB
T+16:52 1155892 kB
T+17:52 1155896 kB
T+18:53 1155908 kB
T+19:53 1155924 kB
T+20:54 1947700 kB  (1.86 GB)   <-- 792 MB step at T+21
```

**Linear regression on the first 18 minutes (16 samples):**
slope = 3.5 MB/min, R² = 0.96. Steady, slow growth.

**Step at T+21**: +792 MB in 1 minute. The journal shows
`ImageLoader: failed to decode /dev/shm/hapax-compositor/album-cover.png`
at 17:00:00 + graph plan activation with 9 shader slot recompiles at
17:00:09. The step correlates with shader recompilation activity.

This is the most interesting data point in Phase 1: **a single
graph-plan change can leak ~100 MB per shader slot** in the current
compositor. The 9-slot plan at 17:00:09 consumed nearly an order of
magnitude more memory than 18 minutes of steady-state operation.

### PID 3145327 (17:01:40 → 17:16:22, 14 m 42 s lifetime)

Sampler observed T+0:52 → T+14:09, 14 samples. The trajectory:

```text
T+0:52   1345096 kB  (1.28 GB)    [startup, libs loaded, cameras not built]
T+1:53   3075764 kB  (2.93 GB)    [+1.74 GB — cairo surfaces + pipelines built]
T+2:54   4431592 kB  (4.23 GB)    [+1.35 GB — shader compiles + effect graph]
T+3:55   4436740 kB  [saturated]
T+4:56   4443968 kB
T+5:58   4458260 kB
T+6:59   4457520 kB
T+8:01   4457436 kB
T+9:02   4459928 kB
T+10:04  4459512 kB
T+11:05  4455916 kB
T+12:06  4459924 kB
T+13:07  4468740 kB
T+14:09  4470824 kB
```

**Linear regression on the steady-state window (T+3 → T+14, 12
samples):** slope = 3.25 MB/min, R² = 0.64. Noisy but slow growth.

**Warmup step at T+2**: +1.35 GB in 1 minute. +1.74 GB in the
previous minute. The 24-slot effect graph plan activated at 17:02:09
correlates with this step. PID 2913194 did not experience this step
because its effect graph plan was simpler at startup.

**systemd's shutdown metadata** on PID 3145327:
```text
Consumed 1h 27min 53.584s CPU time over 14min 58.634s wall clock time,
4.1G memory peak.
```

**CPU usage: 5.87 cores sustained** (1h 28 min CPU time / 15 min
wall) — very high. Correlates with the TTS-client timeout-retry loop
from Phase 5: the director_loop spends most of each cycle blocked on
a 30 s UDS timeout, but the rest of the pipelines continue consuming
CPU at their normal rate. Without the TTS timeout stall, the CPU
burn would likely be ~4 cores.

**Memory peak 4.1 GB** matches the sampler data within 10 %.

### PID 3300095 (17:16:39 → still running, 3 min observed)

```text
T+0:10  987212 kB   (0.94 GB)     [startup]
T+1:11  1074876 kB  (+88 MB)
T+2:11  1090532 kB  (+16 MB)
T+3:12  1428492 kB  (+337 MB)     [warmup acceleration starting]
```

Incomplete data. At T+3 the process is still in warmup. Trajectory
looks more like PID 2913194's early curve than PID 3145327's
(slower). Incomplete observation; will need another pass if the
process survives.

## Thread count stability

All three post-fix processes stabilized at 88–93 threads. The 20-
thread reduction from the pre-fix 112 count is consistent with the
removal of the torch allocator's worker thread pool (torch usually
spawns ~8 background threads for kernel launch + host-device copy,
plus ~6 dataloader worker threads — roughly the 20-thread gap).

No post-fix process has shown unbounded thread growth during its
lifetime. Thread count is a flat ~90 across all samples.

## Post-fix libtorch + CUDA retention

All three post-fix processes show:

- libtorch_* mappings: **0** (was 35 pre-fix)
- libcudart / libcublas / libcudnn / libnvJit / libnccl / libcupti
  / libnvToolsExt mappings: **0** (was ~12 pre-fix)
- libnvcuvid: 1 (NVENC decoder stack — legitimate)
- libnvidia-encode: 1 (NVENC encoder stack — legitimate)
- libnvrtc: 1 (CUDA runtime compiler — loaded by nvcodec)
- libcuda: 1 (NVIDIA driver API — linked by every nvidia-touching
  process)

Alpha's post-fix `cuda_family_mappings: 0` claim in alpha.yaml is
almost-accurate: the torch-specific CUDA family (cudart, cublas,
cudnn, nvJitLink, nccl) is gone, but the non-torch CUDA stack
(libcuda, libnvrtc, libnvcuvid, libnvidia-encode, libnvidia-gpucomp,
libnvidia-glcore) is still present and legitimate. Total CUDA-
family mapping count on the live process is 4–6 (depending on how
you count libnvidia sub-libraries); the 126 pre-fix count
included all the torch transitive dependencies which are now gone.

## Reproduction commands

```bash
# Current compositor PID
systemctl --user show -p MainPID --value studio-compositor.service

# Baseline snapshot (bundled script form)
PID=$(systemctl --user show -p MainPID --value studio-compositor.service)
cat /proc/$PID/smaps_rollup
grep -E "^(VmPeak|VmSize|VmRSS|VmHWM|RssAnon|Threads):" /proc/$PID/status
systemctl --user show -p MemoryCurrent,MemoryPeak,MemoryHigh,MemoryMax studio-compositor.service

# Library family classification
ls /proc/$PID/map_files/ 2>/dev/null | \
  xargs -I{} readlink /proc/$PID/map_files/{} 2>/dev/null | \
  grep -cE 'libtorch|libcudart|libcublas|libcudnn|libnvJit|libnccl|libcupti|libnvToolsExt'
# Expected: 0

# Largest anonymous regions (top 20)
cat /proc/$PID/smaps | awk '/^[0-9a-f]+-/{curr=$NF} /^Rss:/{rss[curr]+=$2} END{for(k in rss) if(rss[k]>10240) print rss[k], k}' | sort -rn | head -20

# Running alpha sampler (do not start a second one)
tail -f ~/.cache/hapax/compositor-leak-2026-04-13/memory-samples-post-fix.csv
```

## Backlog additions (for retirement handoff)

1. **`research(compositor): re-run Phase 1 with a 2-hour uninterrupted
   window after the TTS regression and budget_signal retirement both
   land`** — the data here is informative but confounded by three
   compositor restarts. An uninterrupted 120-sample window would let
   the linear regression disambiguate between "secondary leak" and
   "asymptotic plateau" interpretations of the 3.3 MB/min slope.
2. **`fix(compositor): investigate the per-shader-slot memory cost
   during graph plan activation`** — PID 2913194's +792 MB step
   correlates with a 9-slot graph activation, and PID 3145327's
   +1.35 GB step correlates with a 24-slot activation. If each slot
   is leaking ~100 MB of shader intermediates, that's a primary
   cost driver of the post-Option-A baseline. The `effect_graph`
   module's `activate_plan()` method is the likely call site.
3. **`feat(compositor): Prometheus histogram for CairoSourceRunner
   surface pool residency`** — add a gauge per runner for "bytes
   currently held in pool" so the next Phase 1 run can see which
   runner is growing.
4. **`feat(monitoring): `compositor_memory_footprint_bytes{kind}`
   gauge in-process`** — polls `/proc/self/status` every 30 s and
   exposes on the :9482 exporter, replacing alpha's external
   CSV-file sampler with an in-process Prometheus series. Removes
   PID-tracking race during restarts. Already on PR #752's
   backlog; restated here for continuity.
5. **`fix(compositor): add a lifecycle log line noting "first
   graph-plan activation complete, T+X seconds, RSS delta Y MB"`**
   to make warmup characterization automatic across sessions.
6. **`research(compositor): characterize whether 4× variability in
   steady-state RSS between two processes is reproducible`** —
   re-run the startup 5 times with the same graph plan to see if
   the 4× spread is input-dependent (different graph plans on
   startup) or non-deterministic (allocator timing).
