# Sprint 7 — Polish, Stress, Physical Layer

**Date:** 2026-04-13 CDT
**Theme coverage:** P1-P6 (control surface latency + ergonomics), L2-L5 (GPU contention, encoder budget, dual-GPU validation, TTS GPU spike), A2-A5 (thermal, physical layer, cable hygiene, power budget), M5 (audio-to-visual latency target validation)
**Register:** scientific, neutral

## Headline

**Eight findings + research vectors in Sprint 7:**

1. **The dual-GPU rig (Sprint 5b) makes Sprint 7's contention-investigation tasks much smaller.** Several Sprint 7 tasks were originally framed as "find which workload to evict from the single GPU" — with two GPUs, the answer is "partition." Re-derived tasks are listed below.
2. **PSU spec is the single highest-priority physical unknown.** Total combined GPU TDP is now 600 W. PSU rating is unverified. The failure mode is a silent throttle under load — exactly when livestream pressure is highest.
3. **Case airflow needs verification.** Two GPUs in vertical stack can starve the upper card of intake air. Need physical inspection.
4. **The control surface (Logos studio view) latency is unmeasured.** When the operator drags a preset chip into a slot, how long until the compositor reflects it? Target: <100 ms perceptual. Measurement path needs design.
5. **Audio-to-visual latency target (50 ms from kick to colorgrade dim) needs end-to-end validation.** Sprint 3 captured the components; Sprint 7 should measure the closed loop.
6. **brio-operator fps deficit re-measurement is the highest-leverage Sprint 7 follow-up.** If Phase 1 of the dual-GPU partition (Sprint 5b F1) eliminates the 28.5 fps deficit, the root cause was inference contention. That answer changes the priority of the entire camera-stability epic.
7. **Kokoro CPU TTS upgrade path opens** with the 5060 Ti's 11 GiB free post-migration. GPU TTS candidates: Coqui XTTS, Bark, ChatTTS, Orpheus. Latency target: <100 ms cold synth, <30 ms streaming.
8. **Blackwell NVENC features unexplored**: AV1 hardware encode (subject to gst plugin gap), 4:2:2 chroma, lower-latency mode. None currently used. Worth a spike post-migration.

## Data + research vectors

### P1 — Control surface latency (Logos studio view → compositor)

**Path** (current best understanding):

```text
Operator drags preset chip → Logos React handles drop event →
  → CommandRegistry.execute("studio.activate_chain", { name }) →
  → Tauri IPC to Rust →
  → Rust writes /dev/shm/hapax-compositor/fx-current.txt OR HTTP POST to logos-api →
  → logos-api writes graph-mutation.json (or fx-current.txt) →
  → compositor's chat_reactor inotify-watcher fires →
  → graph_plan reload + WGSL compile + nvh264enc context update →
  → next frame produces the new chain
```

**Measurement points needed**:

| stage | metric to add | expected ms |
|---|---|---|
| React drop event → CommandRegistry execute | already in command logs | 2 ms |
| Tauri IPC | invoke timer | 5 ms |
| Rust → /dev/shm write | mtime delta | 1 ms |
| inotify fire | file mtime → chat_reactor log | 2 ms |
| Plan reload + WGSL compile | already logged ("Slot N (name): setting fragment") | 50-200 ms (driver shader compile) |
| First frame with new chain | first encoder output frame after plan apply | 16-33 ms |
| **TOTAL** | sum | **80-250 ms** |

**Headline target**: <100 ms operator-perceived. Current is likely on the bad side of 100 ms because of NVIDIA driver shader compilation. Mitigation: pre-compile + cache shader binaries.

**Research vector**: instrument each stage. Add a `command_latency_ms` histogram to logos-api with stages as labels.

### P2 — Preset chain composition ergonomics

(Operator-facing UX, not directly measurable from code. Defer to operator interview / observation.)

### P3 — Sequence programmer + auto-cycling latency

When a sequence auto-advances to the next preset on a timer, the same path as P1 fires. Same measurement strategy. Difference: pacing must be precise (e.g., every 8 bars), so jitter on the auto-advance timer matters more than absolute latency.

**Research vector**: measure auto-advance jitter with `sequence_advance_jitter_ms` histogram.

### P4 — Chat-driven preset reactor

`chat_reactor.py` already has a 30 s cooldown per author and a no-state guarantee for consent. Latency from chat message → preset activation = chat ingestion + reactor logic + plan write + (same cascade as P1).

**Research vector**: end-to-end histogram from chat ingest timestamp → first-frame-with-new-chain timestamp.

### L2 — GPU contention (re-derived under dual-GPU)

**Original framing**: "find which workload to evict from the single GPU when contention spikes."
**Dual-GPU framing**: "partition workloads so contention only happens within their own GPU's quota."

After Sprint 5b Phase 1 lands:

- GPU 0 contention: compositor encode + composite + (eventually) imagination + display surface
- GPU 1 contention: TabbyAPI inference + DMN (TBD)

Each card's contention budget is independently observable. The migration plan in Sprint 5b is the answer to L2.

**New research vector**: per-GPU SM utilization saturation curve. At what total workload does either card start dropping frames or queueing inference requests?

### L3 — Encoder budget (re-derived under dual-GPU)

Currently: 1 active NVENC session (compositor RTMP) on GPU 1.

After migration: 1 active NVENC session on GPU 0 (5060 Ti).

**Headroom on GPU 0**:
- Driver-enforced session limit ~3-5 per consumer card
- Blackwell NVENC has higher throughput than Ampere → can sustain more parallel streams at the same bitrate

**Parallel encoder candidates**:

| use case | encoder | bitrate | impact |
|---|---|---|---|
| YouTube live (current) | nvh264enc 6 Mbps | already running | none |
| OBS local recording | nvh264enc 12 Mbps high-quality | adds 1 session | high (lossless local archive) |
| HLS preview (in-app Logos) | nvh264enc 2 Mbps | adds 1 session | medium |
| Twitch backup ingest | nvh264enc 6 Mbps | adds 1 session | high (multi-platform) |
| Periscope archive | nvh264enc 4 Mbps | adds 1 session | low |

**With the 5060 Ti, all five could in principle run simultaneously.** Practical limit: NVENC session count + power budget + heat.

**Research vector**: sustain 3-encoder + 2-decoder simultaneous load on GPU 0 for 10 minutes, measure power/temp, validate no frame drops on any encoder.

### L4 — Dual-GPU validation suite

**Test matrix to run after Sprint 5b Phase 1**:

| test | duration | success criterion |
|---|---|---|
| brio-operator fps stability | 10 min | mean ≥30.0, p99 frame interval ≤34 ms |
| All-camera fps stability | 10 min | each camera mean ≥30.0 |
| TabbyAPI tokens/sec | 5 prompts × 500 tokens | ≥40 t/s (pre-migration baseline; expect uplift) |
| TabbyAPI cold first-token | 5 trials | ≤500 ms |
| Compositor RTMP bitrate stability | 10 min | rolling 10s average within ±5% of target |
| GPU 0 power | 30 min stress | <170 W sustained, no `hw_power_brake_slowdown` |
| GPU 1 power | 30 min stress | <380 W sustained, no `hw_power_brake_slowdown` |
| Both GPUs simultaneous | 30 min combined load | no thermal throttling, no frame drops |

**Research vector**: build a `scripts/dual-gpu-validation.sh` that runs the matrix and emits a pass/fail report.

### L5 — TTS GPU spike (post-migration)

**Candidate models**:

| model | params | VRAM | quality | latency (cold) |
|---|---|---|---|---|
| Coqui XTTS v2 | 470M | 2-3 GiB | high (16k Hz, voice cloning) | 200-400 ms |
| Bark | 80M base | 2 GiB | medium-high (24k, expressive) | 1-3 s |
| ChatTTS | 200M | 2 GiB | high (Chinese-first, English ok) | 300 ms |
| Orpheus 3B | 3B | 6-7 GiB | excellent (24k, expressive) | 500 ms |
| StyleTTS 2 | 100M | 1 GiB | high (24k, fast) | 100-200 ms |

**Recommendation**: StyleTTS 2 or Coqui XTTS v2. Both <3 GiB, sub-300 ms cold synth, room on GPU 0.

**Research vector**: prototype StyleTTS 2 on GPU 0, compare to Kokoro CPU on naturalness + latency. Decision: keep Kokoro / migrate / hybrid.

### A2 — Thermal validation

**Pre-migration baseline**:
- 5060 Ti idle: 37°C
- 3090 load: 60°C

**Post-migration expected**:
- 5060 Ti load: 65-72°C (acceptable)
- 3090 load: 50-55°C (improved by removing visual workload)

**Research vector**: case airflow inspection. If the 5060 Ti is in the upper PCIe slot, it may be starved by the 3090 below it. Possible mitigations:
- Reverse the slot positions (3090 upper, 5060 Ti lower)
- Add intake fan
- Vertical mount one card
- Liquid cooling on the 3090

### A3 — Physical layer + cable hygiene

**Carry-over** from Sprint 1 F1: brio-room USB cable swap. Operator-hand action, not yet executed.

**New** for Sprint 7: DisplayPort cable swap from 3090 to 5060 Ti (Sprint 5b Phase 3). Same physical-action class.

**Research vector**: full cable inventory pass. Document every USB cable, every DisplayPort cable, every audio cable. Identify any that look damaged or loose. Standardize on known-good models.

### A4 — Power budget verification

**Today**:
- 5060 Ti at idle: 13 W of 180 W
- 3090 at load: 201 W of 420 W
- Combined max possible: 600 W

**PSU spec needed**: read PSU label (or operator query). Common gaming-rig PSUs: 850 W (marginal), 1000 W (comfortable), 1200 W (overkill).

**Research vector**:
1. Confirm PSU rating (operator query or `dmidecode`)
2. Stress test: 30 min combined load with `nvidia-smi` watching `power.draw` for both GPUs simultaneously
3. Record peak combined draw + safety margin
4. If margin <20%, recommend PSU upgrade

### A5 — Storage hygiene

(Tangential to livestream performance, but worth noting because storage exhaustion can crash the encoder via /dev/shm filling up.)

`/dev/shm/hapax-compositor/` is on tmpfs (RAM-backed). RAM budget must not be exhausted. Verify:

```bash
df -h /dev/shm
du -sh /dev/shm/hapax-*
```

If `/dev/shm/hapax-compositor/` grows unbounded (e.g., from un-rotated metric snapshots or postmortem dumps), the compositor will eventually OOM. Sprint 6 F7 (postmortem dumps) should write to `~/hapax-state/postmortem/`, not /dev/shm.

### M5 — Audio-to-visual latency closed loop

Sprint 3 broke down the components: kick onset → audio_capture analysis → modulation → visual chain → GPU uniform → next frame render → encoder output → display.

**Sprint 7 measurement**: introduce a synthetic kick at a known timestamp, record the visual frame timestamp at which colorgrade brightness drops, compute the delta.

**Method**:
- Audio test signal: 100 ms 60 Hz sine click via `gst-launch-1.0 audiotestsrc wave=ticks` to mixer_master
- Visual capture: `v4l2-ctl --device=/dev/video42 --stream-mmap --stream-count=300` records 10 s of frames with timestamps
- Post-process: find the first frame with brightness drop > threshold; subtract the audio click timestamp

**Target**: ≤50 ms (research map's headline criterion for audio reactivity).

**Sprint 7 deliverable**: a one-shot validation script + measurement report.

## Findings + fix proposals

### F1 (HIGH): re-measure brio-operator fps post-dual-GPU migration

**Finding**: Sprint 1 F2 left the 28.479 fps deficit as an open mystery with 4 candidate causes (hero=True, metrics lock contention, queue depth, hardware). One cause not on the original list: **GPU SM contention with TabbyAPI inference**. The compositor (PID 12311) and TabbyAPI (PID 1488) both run on GPU 1 and both have non-trivial SM usage (18% + 21%).

**Fix proposal**: After Sprint 5b Phase 1 (compositor pinned to GPU 0), re-measure brio-operator fps for 5 minutes. If fps hits 30.5 (matching the other cameras), the root cause is inference contention. If fps stays at 28.5, the original 4 candidates remain in play.

**Priority**: HIGH. Cheapest investigation in the entire research map; potentially closes a multi-sprint open question.

### F2 (HIGH): PSU spec audit + combined load stress test

**Finding**: 600 W combined GPU TDP, PSU rating unverified, no combined-load stress test on record.

**Fix proposal**: Operator query for PSU rating. 30-min stress test running TabbyAPI + compositor + imagination + reverie shaders simultaneously. Watch `nvidia-smi --query-gpu=power.draw,clocks_throttle_reasons.hw_power_brake_slowdown --format=csv -l 1` on both GPUs.

**Priority**: HIGH. The failure mode is silent. Power throttling = clocks down = frame time up = stream stutters under load.

### F3 (MEDIUM): control surface latency unmeasured

**Finding**: P1 path needs instrumentation. Currently no end-to-end measurement of "operator drops chip → compositor reflects."

**Fix proposal**: Add `command_latency_ms` histogram to logos-api with per-stage labels. Add similar in chat_reactor.py for chat-driven activation.

**Priority**: MEDIUM. Quality-of-life metric; needed before tuning.

### F4 (MEDIUM): audio-to-visual latency closed-loop validation

**Finding**: M5 components measured (Sprint 3) but closed loop not validated against the 50 ms target.

**Fix proposal**: Build the validation script described above. One-shot run, baseline number, decision on whether to optimize.

**Priority**: MEDIUM.

### F5 (RESEARCH): TTS GPU candidate spike

**Finding**: Kokoro is CPU. With 11 GiB free on GPU 0 post-migration, several GPU TTS models become viable.

**Fix proposal**: Prototype StyleTTS 2 (smallest fast option). Compare naturalness + latency to Kokoro.

**Priority**: RESEARCH. Operator-driven decision after data.

### F6 (RESEARCH): Blackwell NVENC features audit

**Finding**: AV1, 4:2:2 chroma, lower-latency modes available on Blackwell. None used.

**Fix proposal**: After migration, audit `nvh264enc` Blackwell-only properties. Document what's available. Pick the highest-impact one (likely 4:2:2 chroma for cleaner color grading) for a spike.

**Priority**: RESEARCH.

### F7 (MEDIUM): case airflow inspection

**Finding**: Two GPUs in series may starve the upper one. Physical inspection needed.

**Fix proposal**: Operator visual inspection. Run thermal stress test post-migration. If the upper card sustains >75°C under load, recommend airflow improvements.

**Priority**: MEDIUM.

### F8 (LOW): cable hygiene full pass

**Finding**: USB + DisplayPort + audio cables not formally inventoried. Sprint 1 F1 (brio-room cable) is one known item.

**Fix proposal**: Operator documentation pass. Identify damaged cables; standardize on known-good models.

**Priority**: LOW.

## Sprint 7 backlog additions (items 226+)

226. **`research(brio-operator-fps): re-measure after Sprint 5b Phase 1`** [Sprint 7 F1, Sprint 1 F2 carry-over] — 5-minute test post-migration. Closes a multi-sprint open question if positive.
227. **`research(power): PSU audit + 30-min combined-load stress test`** [Sprint 7 F2, Sprint 5b F8] — verify the rig can sustain combined GPU load.
228. **`feat(metrics): control surface latency histogram`** [Sprint 7 F3] — `command_latency_ms{stage="..."}` series in logos-api.
229. **`feat(scripts): audio-to-visual latency closed-loop validation`** [Sprint 7 F4] — synthetic kick → visual frame timestamp → delta. One-shot script + report.
230. **`research(tts-gpu): StyleTTS 2 spike on the 5060 Ti`** [Sprint 7 F5] — prototype, compare to Kokoro, decide.
231. **`research(nvenc-blackwell): audit Blackwell NVENC properties on the 5060 Ti`** [Sprint 7 F6] — 4:2:2 chroma, AV1, low-latency modes.
232. **`research(thermal): case airflow inspection + 30-min thermal stress`** [Sprint 7 F7] — operator visual + nvidia-smi temp monitoring.
233. **`research(cables): cable hygiene full pass + standardization`** [Sprint 7 F8] — USB + DP + audio inventory.
234. **`feat(scripts): dual-gpu-validation.sh test matrix runner`** [Sprint 7 L4] — automated post-migration validation suite.
235. **`research(parallel-encoders): sustain 3-encoder load on GPU 0`** [Sprint 7 L3] — verify NVENC session count + power + heat under multi-stream workload.
236. **`feat(systemd): nvidia-persistenced enabled at boot`** [Sprint 7 polish] — keeps GPUs in performance state, avoids cold-start latency on first encoder session.
