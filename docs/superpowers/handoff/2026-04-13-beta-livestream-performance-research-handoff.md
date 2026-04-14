# Beta Retirement Handoff — Livestream Performance Research (2026-04-13)

**Session:** beta
**Workstream:** End-to-end livestream performance research map + 7-sprint execution
**Branch:** `research/livestream-performance-map`
**PR:** #775 (draft, 7 sprint docs across 657-line research map foundation)

## TL;DR

Beta executed the full 7-sprint livestream performance research plan from the map (PR #771), spanning USB topology → compositor → effect graph → audio reactivity → ducking + routing → output + streaming → observability + reliability → polish + stress. **A dual-GPU rig appeared mid-execution** (operator installed an RTX 5060 Ti alongside the existing RTX 3090) which re-derived multiple findings and unlocked the single highest-leverage change in the entire research map.

## Headline finding: dual-GPU partition is the #1 priority

```text
GPU 0 = RTX 5060 Ti  (Blackwell, sm_120, 16 GiB) — 99% IDLE,  39 MiB used
GPU 1 = RTX 3090     (Ampere,    sm_86,  24 GiB) — 52% loaded, 12830 MiB used
```

Every current GPU workload (TabbyAPI 5696 MiB, studio-compositor 3071 MiB, hapax-dmn 3360 MiB, hapax-imagination 302 MiB, Hyprland 151 MiB) sits on GPU 1. The 5060 Ti is sitting unused while every workload contends for the 3090.

**Single highest-leverage change in the research map**:

```ini
# studio-compositor.service drop-in
[Service]
Environment="CUDA_VISIBLE_DEVICES=0"
```

**Effect**: compositor (cudacompositor + nvh264enc + decode) moves to the 5060 Ti. Frees TabbyAPI of encoder + composite + SM contention. Expected ~30-50% TabbyAPI latency improvement. Unlocks Blackwell NVENC. Zero code changes. Trivially reversible.

**Full migration plan**: `docs/research/2026-04-13/livestream-performance-map/sprint-5/sprint-5-dual-gpu-partitioning.md` (Phases 1-4).

## What was done

### Research map (PR #771, branch merged via prior commit)
- 657-line taxonomy across 16 themes (A-P) and ~130 topics
- 7-sprint execution plan with dependencies + priority tiers (P0-P3)
- Headline criteria: 1080p30 p99 ≤34 ms, 24/7 reliability, ≤50 ms audio-to-visual reactivity, clean ducking, end-to-end observability

### Sprint execution (PR #775, draft)

1. **Sprint 1 — Foundations + Unblockers** (USB topology, VRAM, baseline)
   - 6 cameras across 4 xHCI controllers mapped. brio-room USB 2.0 confirmed (q022 carry-over).
   - **brio-operator 28.5 fps deficit refuted as a USB issue** — it's on USB 3.0 Gen 1 5000M and still under target. New candidate causes filed.
   - VRAM breakdown shows the 12.83 GiB are all on GPU 1 (now decoded as Sprint 5b headline).

2. **Sprint 2 — Performance Baseline** (cudacompositor, node catalog, freshness)
   - cudacompositor confirmed live (`pipeline.py:41`).
   - 56 WGSL nodes + 30 presets cataloged (CLAUDE.md said 54 + 28 — docs drift).
   - **CRITICAL P1 bug**: FreshnessGauge name regex rejects hyphens. 8 source IDs (`brio-operator`, `c920-desk`, `overlay-zones`, etc.) silently fail at startup. Per-camera freshness invisible. **One-line fix in `cairo_source.py:166`**.

3. **Sprint 3 — Audio Reactivity** (PipeWire signals, sidechain visual ducking)
   - 18 audio features published by `audio_capture.py`. mel filterbank, onset detection, sidechain envelope all live.
   - **Visual-side sidechain ducking already wired** via `_default_modulations.json` merge (`effects.py:81`). `sidechain_kick` modulates `colorgrade.brightness` × -0.7. This was undocumented; now is.
   - 47/93 fps analysis vs 30 fps render = quantization issue (audio runs ~3× compositor rate).
   - **BPM tracking missing** (none of the 18 features = tempo).

4. **Sprint 4 — Ducking + Routing** (TTS + mic ducking, OBS mix)
   - **No PipeWire sidechain compressor anywhere.** voice-fx-chain.conf is EQ-only.
   - **Yeti / operator VAD does NOT duck music** — only TTS triggers `mute_all()`, and that's a binary cliff, not an envelope.
   - Music source = `youtube-audio-{slot_id}` ffmpeg streams gated via `wpctl set-volume`. `audio_control.py::SlotAudioControl`.
   - **OBS sees a single `mixer_master` bus** — operator cannot independently balance voice vs music.

5. **Sprint 5 — Output + Streaming** (encoder, V4L2 loopback, HLS, RTMP)
   - Encoder: `nvh264enc` CUDA mode, p4 medium, low-latency, CBR.
   - **Encoder NOT pinned to a GPU.** `cuda-device-id` unset on both `nvh264enc` and `cudacompositor`.
   - `nvautogpuh264enc` exists — one-line dual-GPU swap.
   - HLS sink not currently active (use MediaMTX HLS endpoint instead — free).
   - MediaMTX upstream relay to YouTube needs verification.

6. **Sprint 5b — Dual-GPU Partition Design** (NEW research vector after operator dropped the 5060 Ti fact)
   - Workload-to-GPU assignment matrix. Migration plan (4 phases). Power, thermal, PCIe topology. 13 backlog items.
   - **F1 (HIGH): the partition is the highest-leverage change in the entire research map.**
   - Cross-sprint impact summary re-derives every prior sprint under the dual-GPU lens.

7. **Sprint 6 — Observability + Reliability** (metrics, scrapes, alerts, watchdog)
   - **122 metrics on `:9482`** — comprehensive production side.
   - **studio-compositor STILL not in Prometheus's scrape targets.** Queue 024 FINDING-H carry-over. Multi-session bug. Backlog item 47 still open.
   - `node-exporter :9100` is **DOWN**. Host metrics missing.
   - **No alerting rules anywhere.** No alertmanager.
   - **Frame-time histograms missing** — the research map's `p99 ≤34 ms` headline criterion is not measurable from current metrics.

8. **Sprint 7 — Polish + Stress** (control surface latency, GPU validation, TTS spike)
   - Multiple research vectors instead of measurements (Sprint 7 is by design polish + spike work).
   - **brio-operator fps re-measurement after Sprint 5b Phase 1** is the highest-leverage Sprint 7 follow-up. If the deficit disappears, the root cause was inference contention.
   - PSU audit + combined-load stress test = critical physical verification.
   - StyleTTS 2 / Coqui XTTS GPU TTS spike opens with the 5060 Ti's headroom.

## Carry-over from prior queues

- **Queue 022 Phase 1** — brio-room USB cable swap (operator-hand action). Sprint 1 F1.
- **Queue 022 Phase 2** — brio-operator USB 2.0 hypothesis. **REFUTED by Sprint 1 F2** (brio-operator is on USB 3.0).
- **Queue 023 Phase 4** — buffer pool exhaustion. Sprint 1 confirms 0 occurrences in steady state; correlated with brio-room USB fault, not steady-state load.
- **Queue 024 FINDING-H** — Prometheus scrape gap. **Sprint 6 F1 confirms still open. Backlog item 47.**
- **Queue 024 Phase 2** — DCGM exporter / per-GPU labels. Sprint 6 F6 raises it again.
- **Queue 026 P3** — texture pool reuse_ratio = 0. Sprint 1 noted; not deeply investigated.

## Top backlog items for alpha

These are P0/P1 from the 68 backlog items added across sprints 1-7. Full backlog is in each sprint doc.

### P0 — must land in next session

1. **#214** — `fix(prometheus): add studio-compositor scrape job` (5 lines, multi-session carry-over)
2. **#201** — `fix(systemd): CUDA_VISIBLE_DEVICES=0 drop-in for studio-compositor.service` (single highest-leverage change)
3. **#173** — `fix(freshness-gauge): replace hyphens in metric names for cairo_source.py` (Sprint 2 F1, confirmed in Sprint 6)
4. **#216** — `fix(node-exporter): restore the DOWN target` (host metrics blackout)
5. **#202** — `fix(systemd): CUDA_VISIBLE_DEVICES=1 drop-in for tabbyapi.service` (predictability)

### P1 — high value, ship in next 1-2 sessions

6. **#218** — `feat(metrics): per-camera frame-time histograms` (required for `p99 ≤34 ms` validation)
7. **#219** — `feat(prometheus): rules.yml with 9 baseline alerts`
8. **#186** — `feat(pipewire): sidechain compressor for music ducking under voice` (Sprint 4 F1+F2)
9. **#226** — `research(brio-operator-fps): re-measure after Sprint 5b Phase 1`
10. **#175** — `feat(compositor): wgpu Query::Timestamp per-node instrumentation` (per-node GPU cost)

### P2 — meaningful, ship in next 2-4 sessions

11. **#188** — `feat(pipewire): voice/music/instrument subgroup sinks for OBS` (independent OBS balance)
12. **#176** — `research(compositor): brio-operator fps deficit deep dive` (4-cause investigation if #226 doesn't close it)
13. **#207** — `research(power): PSU audit + 30-min combined-load stress test`
14. **#217** — `fix(freshness-gauge): same `replace("-", "_")` audit at all call sites`
15. **#229** — `feat(scripts): audio-to-visual latency closed-loop validation`

## Where the docs live

```text
docs/research/2026-04-13/livestream-performance-map/
├── RESEARCH-MAP.md                                            # 657-line taxonomy (PR #771)
├── sprint-1/sprint-1-foundations.md                           # USB, VRAM, baseline
├── sprint-2/sprint-2-performance-baseline.md                  # cudacompositor, node catalog, freshness P1
├── sprint-3/sprint-3-audio-reactivity.md                      # 18 audio signals, sidechain visual duck
├── sprint-4/sprint-4-ducking-and-routing.md                   # No PW sidechain, no Yeti VAD duck
├── sprint-5/sprint-5-output-and-streaming.md                  # NVENC, V4L2, RTMP, HLS gap
├── sprint-5/sprint-5-dual-gpu-partitioning.md                 # Dual-GPU partition deep dive (NEW)
├── sprint-6/sprint-6-observability-and-reliability.md         # Scrape gap, alerts gap, freshness confirmation
└── sprint-7/sprint-7-polish-and-stress.md                     # Polish, validation, spikes
```

```text
docs/superpowers/handoff/2026-04-13-beta-livestream-performance-research-handoff.md  # this file
```

## How to pick this up

1. Read this handoff (you just did).
2. Read `RESEARCH-MAP.md` for the full taxonomy.
3. Read `sprint-5/sprint-5-dual-gpu-partitioning.md` first — it's the headline change. Phase 1 is one drop-in file.
4. Read `sprint-6/sprint-6-observability-and-reliability.md` second — it explains why Phase 1's effects will be invisible until F1 (scrape gap) and F2 (node-exporter) are also fixed.
5. Cherry-pick from the P0 backlog items above. They're ordered by independence: each can be shipped without the others.
6. After Phase 1 of the dual-GPU migration lands, run the brio-operator fps re-measurement (Sprint 7 F1) — it may close a multi-sprint open question for free.

## What's left to research

The research map covers ~130 topics. Sprints 1-7 covered the structural bones of every theme. Tasks **deferred for later passes**:

- **B (Kernel + capture)**: deep V4L2 buffer pool tuning, uvcvideo quirks for BRIO firmware
- **D (Compositor layout)**: Per-region layout sizing, pip placement, dynamic z-order
- **E (Effect graph + shaders)**: per-shader GPU timing (`wgpu::Query::Timestamp`), shader compile cache
- **F (Audio capture)**: PipeWire 91-node graph deep audit, latency profile per node hop
- **G (Audio analysis)**: BPM tracking integration, beat-grid alignment for visual sync
- **I (Output encoding)**: Blackwell NVENC AV1 + 4:2:2 chroma feature evaluation
- **J (OBS)**: scene graph audit, encoder configuration, source plumbing
- **K (Streaming ingest)**: YouTube ingest behavior under network turbulence, retry tuning
- **L (GPU budget)**: per-GPU SM saturation curves, NVENC session-count headroom
- **M (Latency budgets)**: end-to-end measurement under load, breakdown attribution
- **N (Observability)**: dashboards, log structure, trace spans on hot paths
- **O (Reliability)**: postmortem capture, recovery FSM stress test
- **P (Control surface)**: control surface latency instrumentation, ergonomics

Most of these are ~1 hour passes each. The research map breaks each into ≤90-minute units.

## Relay state

- alpha is retiring (per prior status). 12 PRs shipped + merged. Queue 026 unblock items closed. Close-out handoff drafted.
- beta retired this session. 2 PRs (PR #771 = research map + PR #775 = sprints 1-7 docs draft).
- Inter-session pickup: **next session of either role** can read this handoff + the sprint docs and start executing P0 items.

## Open question for the operator

The operator referenced "4090" in conversation but `nvidia-smi` reports `RTX 3090` for GPU 1. Either:
- Operator misspoke (3090 not 4090)
- 4090 was removed and replaced with the 5060 Ti, leaving the 3090 as the older card
- nvidia-smi is wrong (unlikely)

The dual-GPU partition strategy holds either way (Ampere vs Ada Lovelace doesn't change the workload assignment), but the next session may want to confirm with the operator and update the docs accordingly.

## Closing note

The research map's headline goal is "buttery-smooth livestream performance and reliability and stable fps and perfect audio reactivity effects/ducking/etc." After 7 sprints, the highest-leverage path to that goal is:

1. Land the dual-GPU partition (Sprint 5b Phase 1)
2. Close the Prometheus scrape gap (Sprint 6 F1)
3. Fix the freshness gauge hyphen bug (Sprint 2 F1 / Sprint 6 F3)
4. Wire PipeWire sidechain ducking (Sprint 4 F1)
5. Add frame-time histograms (Sprint 6 F4)

These five changes, executed in order, address the largest gaps the research surfaced. Everything else is incremental polish on a sound foundation.

---

End beta retirement handoff. PR #775 will land remaining commits + un-draft when sprints 5b/6/7 + this handoff are pushed.
