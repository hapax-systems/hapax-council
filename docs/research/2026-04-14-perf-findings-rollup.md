# Livestream perf findings — rollup + priority ranking

**Date:** 2026-04-14
**Author:** delta (beta role)
**Scope:** Consolidates the six perf drops delta shipped today into
a single prioritized picklist for alpha. Asks: if alpha has one
hour of implementation time, which fix returns the most livestream
smoothness?
**Register:** scientific, neutral
**Status:** organizational — no new investigation, no code change

## How to read this document

Each row is a finding from one of the six prior drops. The
**Impact** column estimates what the fix buys, in specific
currencies (CPU cores freed, visual flickers per hour eliminated,
observability gaps closed). The **Effort** column estimates
cost — S for one file ≤10 LoC, M for one module, L for cross-
cutting. The **Ratio** column is a rough impact-per-effort score.
"Latent" means the code is already written or the fix is a
package / config change; "Research" means the fix needs more
investigation first.

## Top picks (if alpha has limited time)

**1 hour available — pick one:**

1. **glfeedback diff check** (drop 5) — 2 lines of Rust +
   2 lines of Python. Eliminates ~224 wasted shader recompiles/
   hour, ~14 visual flickers/hour, and ~560 journald writes/
   hour. Highest impact-per-effort by a wide margin.
2. **OpenCV CUDA rebuild** (drop 6) — zero code change, package
   install. Reclaims potentially ~1 CPU core when the activated
   studio_fx effect is expensive. Investigation to identify the
   package conflict is required first (~15 min) but the fix is
   just a `pacman -S` or `pip uninstall` after diagnosis.
3. **BudgetTracker instantiation + publish_costs wiring**
   (drop 1) — 30-50 LoC in compositor main. Unblocks every
   future cost-based optimization. Not a direct smoothness
   win, but unblocks alpha from having to do blind
   measurements for anything downstream.

**Second hour — pick a second:**

4. **text_render diagnostic capture** (drop 3) — 5 lines in
   `text_render.py:188`. Logs `sw`, `sh`, `len(style.text)` on
   the next `cairo.Error` burst. Not a fix, a **diagnostic**
   that narrows the overlay_zones root cause from three
   hypotheses to one. After the diagnostic fires once, the
   actual fix is straightforward.
5. **`CUDA_VISIBLE_DEVICES=0` in studio-compositor.service**
   (drop 4) — one env var in a systemd unit. Locks in the
   already-desired GPU partition so it can't drift on reboot.

## Full finding matrix

### Subsystem: compositor telemetry

| # | Finding | Drop | Impact | Effort | Ratio | Type |
|---|---|---|---|---|---|---|
| T1 | BudgetTracker never instantiated — no per-source frame-time data | 1 | **unblocks cost-based optimization** | M (30-50 LoC) | ★★★★ | Latent |
| T2 | `publish_costs` dead path (FreshnessGauge = +Inf) | 1 | same as T1 — paired | S (1 timer call) | same as T1 | Latent |
| T3 | `publish_degraded_signal` dead path — VLA cannot gate on compositor stress | 1 | VLA / SEEKING coordination restored | S (1 timer call) | ★★★ | Latent |
| T4 | 6 camera freshness gauges still missing after sprint-6 F5 hyphen fix | 1 errata | per-camera "is it alive" signal restored | S (hyphen handling in 1 path) | ★★★ | Latent |
| T5 | `studio_camera_kernel_drops_total` is a false-zero — doesn't fire for MJPG | 2 | observability trust restored | M (replace signal source) | ★★ | Research |
| T6 | `_PUBLISH_COSTS_FRESHNESS` log line rate-limit | — | reduce INFO spam | S (log level change) | ★ | Latent |

### Subsystem: compositor rendering hot path

| # | Finding | Drop | Impact | Effort | Ratio | Type |
|---|---|---|---|---|---|---|
| R1 | **glfeedback shader-recompile storm** — 336 recompiles/hour, ~224 are byte-identical | 5 | ~14 flickers/hour, 40-80 ms of GL work saved per `activate_plan` | S (Python + Rust diff check, ~4 LoC) | ★★★★★ | Latent |
| R2 | `overlay_zones` cairo invalid-size burst — 50+ exceptions per 4-second window | 3 | eliminate 50 traceback/burst, ~30 KB/s journald | M (diagnostic then fix, ~10 LoC) | ★★★ | Research |
| R3 | `studio_fx` OpenCV CUDA path silently disabled — ~70-130% CPU wasted | 6 | up to ~1 CPU core | S (package reinstall, 0 LoC) | ★★★★★ | Latent |
| R4 | `studio_fx` silent CPU fallback — no warning log on CUDA-unavailable | 6 | observability | S (1 log line) | ★★ | Latent |
| R5 | `studio_fx` effects `classify`/`screwed`/`pixsort`/`vhs`/`slitscan` have no GPU path at all | 6 | additional CPU savings after R3 lands | L (per-effect) | ★★ | Research |

### Subsystem: compositor capture

| # | Finding | Drop | Impact | Effort | Ratio | Type |
|---|---|---|---|---|---|---|
| C1 | **brio-operator 27.94 fps sustained deficit (6.9% frame loss, ~45k frames in 6h)** | 2 | +6.9 % frame count on one camera | S (physical cable / port swap test to diagnose) → M (root cause fix) | ★★★ | Research |
| C2 | `nvh264enc` not pinned via `cuda-device-id` | 4 | encoder GPU durability (already right at runtime) | S (1 env var in unit) | ★★★ | Latent |
| C3 | `cudacompositor` not pinned via `cuda-device-id` | 4 | same as C2 (paired) | S (same env var) | same as C2 | Latent |
| C4 | `nvh264enc` → `nvautogpuh264enc` swap | 4 | live dual-GPU selection | S (1 line in rtmp_output.py) | ★★ | Latent |

### Subsystem: compositor pipeline / RTMP

| # | Finding | Drop | Impact | Effort | Ratio | Type |
|---|---|---|---|---|---|---|
| P1 | RTMP bin constructed-but-detached until `toggle_livestream` | 4 | (expected design, not a bug — informational) | — | — | Info |
| P2 | MediaMTX `paths:` block is empty — no `studio` path, no upstream YouTube/Twitch relay | 4 | full upstream path | M (mediamtx.yml + runOnReady rule) | ★★★ | Latent |
| P3 | HLS cheap path blocked on (a) livestream toggle and (b) `all_others` publish behavior verification | 4 | Logos in-app HLS preview | S (verify + test) | ★★ | Research |
| P4 | `nvav1enc` plugin still missing | 4 | AV1 codec availability | M (gst-plugin-bad ≥1.26 check) | ★ | Research |
| P5 | bitrate already at 6 000 kbps (sprint-5 F5) | 4 | **already satisfied — close backlog item 195** | — | — | Done |

### Subsystem: compositor observability (sprint-6 follow-ups)

| # | Finding | Drop | Impact | Effort | Ratio | Type |
|---|---|---|---|---|---|---|
| O1 | No appsrc back-pressure metric | 1 | pipeline stall detection | M (pad probe + gauge) | ★★★ | Research |
| O2 | No DTS jitter metric | 1 | pacing smoothness signal | M (pad probe + histogram) | ★★★ | Research |
| O3 | No interpipe hot-swap counter | 1 | camera failover visibility | S (pad-swap hook counter) | ★★ | Research |
| O4 | No NVENC encode latency metric | 1 | encoder pacing | M (pad probe or `nvidia-smi` poll) | ★★★ | Research |
| O5 | No encoder queue depth metric | 1 | upstream back-pressure | S (queue-size probe) | ★★ | Research |

### Subsystem: logos webview (shipped this session)

| # | Finding | Drop | Impact | Effort | Ratio | Type |
|---|---|---|---|---|---|---|
| L1 | DetectionOverlay off-screen rAF leak | (shipped ac927debc) | WebKit 85 % → 74 % steady-state | S | — | Shipped |
| L2 | AmbientShader 60 Hz rAF vs 5 fps target | (shipped ac927debc) | same as L1 — paired | S | — | Shipped |
| L3 | Residual: overlapping polling in `useBatchSnapshotPoll` + `PerceptionCanvas` | (CPU audit followup) | further WebKit CPU reduction | M (unified polling layer) | ★★ | Research |

### Subsystem: infrastructure (shipped this session)

| # | Finding | Drop | Impact | Effort | Ratio | Type |
|---|---|---|---|---|---|---|
| I1 | redis mem_limit 768 MB (at limit, bgsave thrashing), cpus 0.25 (throttled) | (shipped, llm-stack) | 83.9 % → 1.9 % redis CPU, LiteLLM cache unblocked | S | — | Shipped |
| I2 | MinIO mem_limit 2 GB → 4 GB (near limit) | (shipped, llm-stack) | headroom for Langfuse blob growth | S | — | Shipped |

## Recommended order for alpha

**Latent wins first (ship faster):**

1. **R1 glfeedback diff check** — 4 LoC across two files. Most bang per line of code.
2. **R3 studio_fx OpenCV CUDA** — 0 LoC, package diagnosis and reinstall. Run the 3 follow-ups listed in drop 6 § 7 first (~15 min) to know whether it's a pacman package bug or a pip shadow.
3. **C2 + C3 `CUDA_VISIBLE_DEVICES=0`** — 1 line in studio-compositor.service. Lock in GPU partition durability.
4. **T1 + T2 + T3 BudgetTracker instantiation** — 30-50 LoC in compositor main + one timer. Unblocks all future cost-based work.
5. **T4 camera freshness hyphen fix completion** — a few lines in the registration path. Restores per-camera signal.

**Research-first items (measure, then fix):**

6. **R2 overlay_zones diagnostic** — ship the 5-line capture (drop 3 § 5), wait for one burst, then ship the targeted fix. Could resolve in < 24 h.
7. **C1 brio-operator** — run the cable/port swap test (drop 2 § 4 item 1). 60 s operator-in-the-loop action, unambiguous. After the result, the fix is either hardware or firmware.
8. **T5 kernel_drops false-zero** — find or replace the signal source. Related to C1 because we can't diagnose brio-operator's loss location without this.

**Sprint-6 observability backlog (separate day):**

9. **O1–O5 missing pipeline metrics** — these are a sprint of work, not individual fixes. Batch under a single spec like "compositor pipeline health baseline".

## Cross-drop themes

Three patterns repeat across the six drops:

### A — "Fire on any change" instead of "fire on actual change"

R1 (glfeedback), T4 (camera freshness gauge registration), potentially
T5 (v4l2 sequence gap detector). Each case is a state-change signal
that fires on any write rather than on a true delta. The fix
pattern is the same: `if old != new { mark_dirty }`. Worth
considering a lint or a `DirtyFlag<T>` helper that enforces the
diff at the type level.

### B — "Code exists, runtime disables it"

T1 / T2 / T3 (budget tracker installed, never instantiated) and
R3 (GpuAccel wired, CUDA package not functional) are the same
shape: significant infrastructure was written, tested, and
committed — but the wiring to activate it is missing. Worth a
follow-up drop asking **"what else is in the codebase that has
the same latent shape?"** A text search for phrases like
"falls back to" or "opt-in" would probably surface more.

### C — "No counter, no data"

C1 (brio-operator deficit unattributable because kernel_drops is
false-zero), O1–O5 (pipeline health counters absent), R2
(overlay_zones burst inputs not captured). Alpha's cost-based
optimization plans routinely run into "we can't measure this
yet". A single meta-drop about metric coverage gaps — what
doesn't exist but should — might be worth writing as a
dedicated research follow-up.

## References

- `2026-04-14-compositor-frame-budget-forensics.md` (drop 1) —
  T1, T2, T3, O1-O5
- `2026-04-14-compositor-frame-budget-forensics-errata.md` —
  T4, updated metric census
- `2026-04-14-brio-operator-producer-deficit.md` (drop 2) — C1, T5
- `2026-04-14-overlay-zones-cairo-invalid-size.md` (drop 3) — R2
- `2026-04-14-sprint-5-delta-audit.md` (drop 4) — C2, C3, C4, P1-P5
- `2026-04-14-glfeedback-shader-recompile-storm.md` (drop 5) — R1
- `2026-04-14-studio-fx-cpu-opencv-gpu-gap.md` (drop 6) — R3, R4, R5
- CPU audit earlier this session (not a drop; bash-only) — L1, L2, L3, I1, I2

All six drops and this rollup are in `docs/research/`, committed
to `main`, timestamped 2026-04-14.
