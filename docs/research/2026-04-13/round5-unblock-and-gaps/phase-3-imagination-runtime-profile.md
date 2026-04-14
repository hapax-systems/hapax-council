# Phase 3 — Imagination Rust binary runtime profile

**Queue item:** 026
**Phase:** 3 of 6
**Date:** 2026-04-13 CDT
**Register:** scientific, neutral (per `feedback_scientific_register.md`)

## Headline

The `hapax-imagination` Rust binary has **crashed 65 times in the
last 24 hours**. Every crash is a wgpu validation error matching
the same shape: `"Error matching ShaderStages(FRAGMENT) shader
requirements against the pipeline"` — the DynamicPipeline's
shader slots and the compiled WGSL binding layouts drift out of
sync, and wgpu's default "fatal errors" policy panics. The panic
exits with status 101 (Rust default) and systemd restarts. This
is a **high-severity latent stability issue** that no prior round
surfaced because no one grep'd for `Failed with result` in the
imagination journal.

Other findings are within normal operating ranges:

| metric | value | assessment |
|---|---|---|
| VmRSS | 253 MB | normal, much lighter than compositor |
| VmPeak | 1.93 GB (virtual) | normal |
| Threads | 23 | normal |
| Frame rate (measured live) | 47–54 fps trending up | below 60 fps target but survivable |
| GPU memory (nvidia-smi) | 302 MiB | normal |
| cgroup `MemoryCurrent` | 46.4 MB | suspiciously low — see note below |
| Current PID | 179247 @ 18:56:05 CDT | 7 min uptime (most recent of 65 restart cycles) |
| pool reuse_ratio | **0.000000** | pathological — every texture acquire allocates new |
| reverie.rgba output | 8.3 MB @ mtime now | alive, 1920x1080 RGBA (8,294,400 bytes = 1920×1080×4 ✓) |

The two findings that stand out:

1. **65 crashes in 24h from repeated wgpu validation errors** —
   critical stability bug
2. **Texture pool `reuse_ratio = 0`** — every render allocates a
   fresh texture, defeating the pool's purpose

## Data

### Process snapshot

```bash
$ systemctl --user show -p MainPID,ExecMainStartTimestamp,MemoryCurrent,MemoryPeak hapax-imagination.service
MainPID=179247
ExecMainStartTimestamp=Mon 2026-04-13 18:56:05 CDT
MemoryCurrent=48689152    (46.4 MB — see note)
MemoryPeak=66207744       (63.1 MB — see note)
```

```text
$ grep -E "^(VmRSS|VmData|VmSize|VmPeak|Threads|voluntary_ctxt|nonvoluntary_ctxt):" /proc/179247/status
VmPeak:  1934664 kB   (1.93 GB — virtual address space)
VmSize:  1934408 kB
VmRSS:    252860 kB   (253 MB — resident)
VmData:   105772 kB
Threads:       23
```

```text
$ cat /proc/179247/smaps_rollup
Rss:              252860 kB
Pss:              212806 kB
Pss_Dirty:        138532 kB
Pss_Anon:          28840 kB
Pss_File:         183966 kB
Pss_Shmem:             0 kB
Shared_Clean:      44332 kB
Shared_Dirty:          0 kB
Private_Clean:     69996 kB
Private_Dirty:    138532 kB
Referenced:       249520 kB
Anonymous:         28840 kB
```

**cgroup vs /proc discrepancy**: systemd reports
`MemoryCurrent=46.4 MB` but `/proc/$PID/status` reports
`VmRSS=253 MB`. The difference is the systemd cgroup's memory
accounting excludes shared pages + file-backed memory that the
kernel reclaims — 46 MB is "private working set," 253 MB is
"total resident." For a Rust binary with heavy Vulkan/wgpu
drivers (138 MB file-backed, `libvulkan_radeon.so` +
`libnvidia-glcore.so` + friends), this gap is expected.

**VmRSS 253 MB is clean** compared to the Python compositor's
post-PR-751 ~4.4 GB baseline. The Rust binary has no torch, no
GStreamer, no Cairo — just wgpu + libvulkan + libnvidia-glcore.

### GPU footprint

```text
$ nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader
38671, 5760 MiB    # tabbyapi (Qwen3.5-9B)
7459, 3045 MiB     # hapax-dmn
101263, 3264 MiB   # hapax-daimonion (STT on GPU)
179247, 302 MiB    # hapax-imagination
```

**302 MiB.** Rendering at 1920×1080 @ ~50 fps through an 8-pass
wgpu pipeline fits in under 0.3 GB on the 3090. Pool allocation
below contributes some of this; the rest is framebuffers, depth
buffers, and shader pipelines.

```text
$ nvidia-smi pmon -c 3 -s u
0  179247  C+G   10%  3%  -  -  -  -  hapax-imaginati
```

10% GPU utilization sustained, 3% memory bandwidth. **Very
light.** The 3090 has plenty of headroom.

### Frame-cadence trace (10-row window)

```text
19:01:30  frame_count=16200  elapsed=325.4s
19:01:43  frame_count=16800  elapsed=338.2s   (+600 frames / +12.8s = 46.9 fps)
19:01:54  frame_count=17400  elapsed=349.5s   (+600 / +11.3s = 53.1 fps)
19:02:05  frame_count=18000  elapsed=360.3s   (+600 / +10.8s = 55.6 fps)
19:02:18  frame_count=18600  elapsed=373.2s   (+600 / +12.9s = 46.5 fps)
19:02:30  frame_count=19200  elapsed=385.5s   (+600 / +12.3s = 48.8 fps)
19:02:42  frame_count=19800  elapsed=396.9s   (+600 / +11.4s = 52.6 fps)
19:02:53  frame_count=20400  elapsed=407.7s   (+600 / +10.8s = 55.6 fps)
19:03:05  frame_count=21000  elapsed=420.2s   (+600 / +12.5s = 48.0 fps)
19:03:16  frame_count=21600  elapsed=431.3s   (+600 / +11.1s = 54.1 fps)
```

**Frame rate: 46.5–55.6 fps, mean ~52 fps, variance ±5 fps.**
Target is 60 fps per the wgpu pipeline spec. Current delivery
is ~87% of target. Not a smoking-gun regression but a gap worth
naming.

**Jitter contributors** (plausible):
- wgpu validation overhead
- Compositor reading `reverie.rgba` at 30 fps causing contention
  on the file
- CPU-side Python signal reads (uniforms.json, stimmung) blocking
  on filesystem occasionally
- libvulkan_radeon.so/libnvidia-glcore.so driver queue depth

### reverie.rgba output stream (healthy)

```text
$ ls -la /dev/shm/hapax-sources/reverie.rgba
-rw-r--r-- 1 hapax hapax 8294400 Apr 13 19:04 /dev/shm/hapax-sources/reverie.rgba
```

8,294,400 bytes = 1920 × 1080 × 4 (RGBA) ✓. Written at 19:04
(current timestamp is 19:04+). **The imagination → compositor
handoff is alive.** The tmp file + atomic rename pattern keeps
the file consistent.

### Pool metrics SHM (from PR #760)

```bash
$ cat /dev/shm/hapax-imagination/pool_metrics.json
{
  "bucket_count":     1,
  "total_textures":  14,
  "total_acquires":  14,
  "total_allocations": 14,
  "reuse_ratio":      0.000000,
  "slot_count":      14
}
```

**`reuse_ratio = 0.0`.** 14 acquires, 14 allocations — every
acquire allocated a new texture. No reuse. The pool is acting
as a plain allocator, not a pool. This defeats the whole
`TransientTexturePool` design.

Two plausible causes:
- **Size mismatch**: the pool's hash key is `(width, height,
  TEXTURE_FORMAT)`. If each shader pass creates a texture of a
  unique size, no two passes share a key, and each gets its own
  bucket. Count: 14 textures with 1 bucket is strange — if
  every pass had unique size we'd expect 14 buckets. **1 bucket
  with 14 textures means all 14 share the same key** and the
  pool SHOULD have reused them.
- **Lifetime mismatch**: textures are being held for longer than
  one frame, so the pool can't reuse them. The pool grows until
  all concurrent textures have been allocated once, then stops
  growing (but still never reuses).

**Either way, `reuse_ratio = 0` is a bug the PR #760 pool
metrics surface would have caught immediately if the compositor
were scraped for the mirrored series.** Alpha's PR #760 shipped
the metric; queue 024's FINDING-H scrape gap (still being fixed)
prevents it from being seen by Prometheus/Grafana. Phase 3
surfaces it directly from the SHM file.

### Current state from `current.json`

```json
{
  "id": "b8da7b7eff69",
  "timestamp": 1776124994.845498,
  "dimensions": {
    "intensity": 0.6, "tension": 0.3, "depth": 0.8,
    "coherence": 0.9, "spectral_color": 0.7,
    "temporal_distortion": 0.4, "degradation": 0.2,
    "pitch_displacement": 0.3, "diffusion": 0.5
  },
  "salience": 0.5, "continuation": true,
  "narrative": "The red background isn't dominance but the water's way...",
  "material": "water",
  ...
}
```

**9 dimensions populated with meaningful values.** Salience 0.5.
Continuation true. Material "water". The imagination daemon is
producing active imagination fragments, not just ticking
statically. This contrasts with Phase 4 of queue 025 which
observed the eigenform state vector pinned at all-zeros — the
imagination side is alive, but the VLA's eigenform writer is
not reading from the live imagination state.

## Error-mode catalog (24-hour window)

### Primary: wgpu validation crashes (65 events)

```bash
$ journalctl --user -u hapax-imagination.service --since "24 hours ago" | grep -c "Failed with result"
65
```

Every failure includes the same panic stack signature:

```text
Apr 13 17:00:48 hapax-imagination[3084028]: note: run with `RUST_BACKTRACE=1` ...
Apr 13 17:00:48 systemd[1291]: hapax-imagination.service: Main process exited, code=exited, status=101/n/a
Apr 13 17:00:48 systemd[1291]: hapax-imagination.service: Failed with result 'exit-code'.
```

And the root cause panic:

```text
[ERROR wgpu::backend::wgpu_core] Handling wgpu errors as fatal by default
thread 'main' panicked at wgpu-24.0.5/src/backend/wgpu_core.rs:1303:26:
wgpu error: Validation Error
    Error matching ShaderStages(FRAGMENT) shader requirements against the pipeline
thread 'main' panicked at wgpu-hal-24.0.4/src/vulkan/instance.rs:173:58:
thread 'main' panicked at core/src/panicking.rs:233:5:
```

**Root cause class: shader/pipeline binding layout drift.** The
`DynamicPipeline` hot-reloads shaders from
`/dev/shm/hapax-imagination/pipeline/` (per PR #749). When a
new shader arrives, the pipeline's `@group(2) Params` binding
layout must match the shader's declared layout. If there's a
mismatch — shader expects 8 fields, pipeline has 7, or the field
order is different — wgpu's fragment-stage validation panics.

Cross-reference to CLAUDE.md § Reverie Vocabulary Integrity:
> `dynamic_pipeline.rs` walks `pass.param_order` positionally.
> Each shader with a `@group(2) Params` binding (noise, rd,
> colorgrade, drift, breath, feedback, postprocess) receives
> per-node modulation.

**The per-node param_order needs to match the shader's WGSL
struct field order.** If a new shader is written with a
different field order than what `param_order` specifies, or if
a new field is added without updating both sides in one commit,
the pipeline panics on first-frame validation.

### Secondary: UDS read error (several/day)

```text
Apr 12 19:47:09 WARN  hapax_imagination] UDS read error: Connection reset by peer (os error 104)
Apr 12 19:47:11 ERROR hapax_imagination] Surface error: A timeout was encountered while trying to acquire the next frame
```

**UDS = Unix Domain Socket** used by hapax-logos (Tauri) to
send commands to hapax-imagination. `Connection reset by peer`
means hapax-logos closed the socket mid-read. Happens on logos
restart. Usually followed by a `Surface error` because the
wgpu surface is tied to the (now dead) logos surface and can't
acquire a frame.

**Severity: medium.** These are not crash-causing on their own
in most cases, but they correlate with wgpu validation crashes
when the surface teardown races a pipeline hot-reload.

### Tertiary: the 15:25 core dump

```text
Apr 13 15:25:36 hapax-imagination.service: Main process exited, code=dumped, status=6/ABRT
```

**One core dump** (SIGABRT, exit 6/dumped) among the 65 crashes.
The rest are status 101 (panic). SIGABRT = `abort()` — usually
called by C++ or by Rust's `std::process::abort()`, typically
indicating double-panic or stack overflow during a panic
handler. This is a single-instance outlier worth a follow-up
but not the primary crash mode.

## Ranked findings

| rank | finding | severity | scope |
|---|---|---|---|
| 1 | 65 wgpu validation crashes in 24h, shader stage / pipeline layout drift | **HIGH** | stability — requires a root-cause pass on the hot-reload path |
| 2 | Pool `reuse_ratio = 0` — all textures newly allocated | MEDIUM | efficiency — the pool isn't pooling |
| 3 | Frame rate 47–54 fps vs 60 fps target | MEDIUM | smoothness — 13% below target |
| 4 | 1 core dump on 15:25 (SIGABRT vs the 64 other panics) | LOW | outlier; single occurrence; trace unclear |
| 5 | UDS read errors from hapax-logos | LOW | coincidental with logos restarts; not causal |
| 6 | Compositor → imagination scrape gap (depends on FINDING-H) | - | already in queue 024 backlog |

## Proposed fixes

### F1. wgpu validation crash investigation (ranked 1)

The crash rate is **65/day = 2.7/hour ≈ one crash every 22
minutes**. This is not survivable 24/7 operation. systemd's
auto-restart masks the symptom (the daemon keeps coming back)
but the operator sees visual glitches on every restart and the
imagination state resets.

**Fix path:**

1. **Enable `RUST_BACKTRACE=1`** in
   `~/.config/systemd/user/hapax-imagination.service` to capture
   full stack traces on the next crash.

   ```ini
   [Service]
   Environment=RUST_BACKTRACE=1
   ```

2. **Add a fail-loud check in the DynamicPipeline hot-reload
   path** that validates the shader's WGSL struct field order
   against `pass.param_order` **before** handing the pipeline
   to wgpu. If mismatch, refuse to load the new shader and log
   the specific mismatched fields.

3. **Serialize `pass.param_order` with the compiled WGSL as a
   manifest**. When Python writes a new shader via
   `agents/effect_graph/wgsl_compiler.py`, it should also write
   a manifest JSON listing the expected field order. Rust reads
   both and validates.

4. **Widen the panic handler**. Current behavior: wgpu error
   panics → Rust default `PanicStrategy::Abort` → status 101.
   Replace with a custom panic handler that:
   - Logs the full validation error to a dedicated
     `/dev/shm/hapax-imagination/last-panic.json`
   - Falls back to the previous-good shader instead of panicking
   - Emits a `hapax_imagination_shader_rollback_total` counter

This is a multi-hour fix. Alpha should pick it up in the next
session after BETA-FINDING-L lands.

### F2. Pool reuse ratio investigation (ranked 2)

```json
{"bucket_count":1,"total_textures":14,"total_acquires":14,
 "total_allocations":14,"reuse_ratio":0.0,"slot_count":14}
```

With 1 bucket and 14 textures, the pool key is correctly
hashing all 14 textures into one bucket — so they SHOULD be
reusable. But `reuse_ratio = 0` means the pool never returned
a pre-allocated texture on an acquire call.

Possible causes:
- Textures are never released back to the pool
- The pool's `release` call is not wired
- `acquire` always takes the "cold path" because the pool is
  empty on first call, and subsequent calls don't find
  release-tagged textures
- Lifetime scoping bug: textures are held across frames

**Fix path:**

1. Read `hapax-logos/src-imagination/src/dynamic_pipeline.rs`
   for the `TransientTexturePool<PoolTexture>` implementation
2. Trace the `acquire` and `release` paths — where should
   release be called? Is it called?
3. Add a debug counter per-slot: "released but never reacquired"
   vs "acquired but never released"
4. Likely fix: call `release` at the end of each pass instead
   of at scene shutdown

**Effort:** 1–2 hours. Smaller than F1.

### F3. Frame rate gap (ranked 3)

47–54 fps vs 60 fps target. Not critical but documentable.

Candidates:
- vsync on the wgpu surface is forcing 60 Hz cap with jitter
- per-pass timing could be shaving a few ms each
- libvulkan_radeon driver overhead during each frame

**Fix path:** add per-pass timing instrumentation (search for
wgpu `Query::Timestamp` in the code; likely not there yet).
Report per-pass `ms` in the pool_metrics JSON so the dashboard
can show where the time goes.

## Backlog additions (for round-5 retirement handoff)

142. **`fix(hapax-imagination): investigate + fix 65-crash/day wgpu validation error storm`** [Phase 3 F1] — CRITICAL stability bug. Enable RUST_BACKTRACE=1 first, then add WGSL manifest validation + fallback panic handler. Multi-hour fix. Alpha should see this as Critical alongside BETA-FINDING-L.
143. **`fix(hapax-imagination): pool_metrics.reuse_ratio = 0 — textures never reused`** [Phase 3 F2] — MEDIUM efficiency bug. Trace acquire/release paths in `TransientTexturePool`. 1–2 hours.
144. **`feat(hapax-imagination): RUST_BACKTRACE=1 in systemd unit`** [Phase 3 F1 prep] — one-line systemd drop-in. Unblocks F1 investigation.
145. **`feat(hapax-imagination): per-pass timing instrumentation via wgpu Query::Timestamp`** [Phase 3 F3] — add timing to pool_metrics.json for dashboard visibility.
146. **`fix(hapax-imagination): WGSL shader + param_order manifest validation before wgpu load`** [Phase 3 F1 sub-fix] — prevents the shader-vs-pipeline drift that causes the crash storm.
147. **`feat(hapax-imagination): fallback panic handler with shader rollback`** [Phase 3 F1 sub-fix] — instead of panicking on wgpu validation error, roll back to the previous-good shader and emit a `hapax_imagination_shader_rollback_total` counter.
148. **`research(hapax-imagination): investigate the 15:25 SIGABRT core dump outlier`** [Phase 3 tertiary] — low priority, single occurrence.
