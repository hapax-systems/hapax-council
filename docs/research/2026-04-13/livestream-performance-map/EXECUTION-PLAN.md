# Livestream Performance — Execution Plan

**Date:** 2026-04-14
**Author:** alpha (plan derived from beta's 8 research drops)
**Scope:** systematic execution plan covering every finding in sprints 1–7 + 5b dual-GPU partition design. No cherry-picks.
**Register:** scientific, neutral

## 0. Inventory

Beta's drops:

| doc | topic | findings | already-addressed count |
|---|---|---|---|
| `RESEARCH-MAP.md` | 16-theme meta-research plan (~130 topics) | structural | — |
| `sprint-1-foundations.md` | USB topology, VRAM, buffer pool, baseline | 5 | 0 |
| `sprint-2-performance-baseline.md` | Compositor, shader catalog, per-camera fps | 6 | 2 |
| `sprint-3-audio-reactivity.md` | PipeWire, audio DSP, reactivity wire-up | 6 | 0 |
| `sprint-4-ducking-and-routing.md` | TTS ducking, mic ducking, stream mix | 5 | 0 |
| `sprint-5-output-and-streaming.md` | NVENC, V4L2 loopback, RTMP, bitrate | 8 | 2 |
| `sprint-5-dual-gpu-partitioning.md` | Dual-GPU rig design (RTX 5060 Ti + 3090) | 10 | 0 |
| `sprint-6-observability-and-reliability.md` | Metrics, alerts, watchdogs, FSM | 8 | 1 |
| `sprint-7-polish-and-stress.md` | Control surface, PSU, TTS GPU spike | 8 | 0 |
| **totals** | | **56** | **5** |

"Already addressed" = items closed by alpha's prior work this session: S2-F1 hyphen
fix (PR #776), S2-F5 node/preset memory drift, S5-F5 bitrate already 6000, S6-F3
(same hyphen bug, covered by PR #776), S2-F4 cudacompositor INFO-only. None were
cherry-picks in isolation — they were bundled into the earlier close-out push —
but only S2-F1 was high-leverage; the rest were verification or docs-drift.

**The remaining 51 findings are the subject of this plan.**

## 1. Classification

Sorting the 51 findings by action shape (not priority — priority comes in §2).

### Class A — dual-GPU migration (coordinated single change)

S5-F1, S5-F6, S5b-F1, S5b-F2, S5b-F3, S5b-F4, S5b-F5, S5b-F6, S7-F1 (re-measure).

Beta explicitly says this is the **single highest-leverage change in the entire
research map**. Moves compositor + encoder + imagination + display to the idle
5060 Ti; leaves TabbyAPI + DMN alone on the 3090. Has a 4-phase plan in
`sprint-5-dual-gpu-partitioning.md`.

### Class B — observability foundation (must land first)

S1-F5, S6-F1 (Prometheus scrape gap, multi-session carry-over), S6-F2
(node-exporter down), S6-F4 (frame-time histograms, the headline p99 target),
S6-F5 (alerting rules), S6-F6 (per-GPU labels), S6-F7 (postmortem), S6-F8
(structured logging), S3-F5 (audio DSP timing), S2-F3 (per-node wgpu
timestamps), S1 item 172 (compositor VRAM gauge), S5b item 210 (per-GPU
metrics), S4 item 190 (voice_active / music_ducked), S7-F3 (control surface
latency histogram).

14 items. The biggest, longest-carrying bug is W1.1 — the Prometheus scrape
gap. It has been open since queue 024 and no session has closed it.

### Class C — audio ducking architecture (coordinated single change)

S4-F1 (operator-speech ducking), S4-F2 (replace binary TTS mute with envelope),
S4 item 187 (remove mute_all from director_loop after sidechain lands), S4-F4
(HAPAX_TTS_TARGET env var docs + default).

The fix shape is a single PipeWire filter-chain `.conf` file + a Python diff in
`director_loop.py`. Beta recommends **Option A (PipeWire sidechain compressor)**
with threshold -30 dB, 4:1 ratio, 30 ms attack, 350 ms release, 6 dB soft knee.

### Class D — single-file targeted audits (fact-finding, cheap)

S3-F2 (audio_rms/audio_beat alias resolution in modulator.py), S5-F7 (MediaMTX
upstream relay config), S5b-F7 (PCIe link width), S5b-F6 (hapax-dmn 3.3 GiB
allocation), S5b-F9 prep (wgpu env var name verification), S1-F3 (brio-synths
unclaimed interfaces).

Each is ≤1 hour of reading + a short report. No code change guaranteed.

### Class E — refactors + new features (larger, sequenceable)

S3-F1 (sub-frame transient ring buffer smoother), S3-F3 (BPM + beat phase),
S3-F6 (dedupe audio DSP via SHM), S4-F3 (voice/music subgroup for OBS
mix), S4-F5 (youtube ffmpeg → GStreamer), S7-F4 (audio→visual closed-loop
validation script), S7-F3 (command latency histogram already listed in B).

### Class F — research / investigation / spikes

S1-F2 (brio-operator deficit deep dive — may be closed by Class A migration
re-measure), S1-F4 (compositor 3 GB VRAM attribution), S5-F3 (nvav1enc
availability), S5b-F8/S7-F2 (PSU audit + combined-load stress), S5b-F9/S7-F5
(GPU TTS spike), S5b-F10/S7-F6 (Blackwell NVENC feature audit), S7-F7 (case
airflow), S7 L3 (parallel encoders), S7 L4 (dual-GPU validation suite).

### Class G — operator-hand physical actions

S1-F1 (brio-room USB 3.0 cable), S5b-F4 (DisplayPort cable to 5060 Ti),
S7-F7 (airflow inspection), S7-F8 (cable hygiene pass).

### Class H — trivial docs / closed observations

S2-F6 (graph-mutation observation, non-bug), S5-F8 (tee architecture OK),
S3-F4 (sidechain kick already wired — positive finding), S4-F4 (TTS env var
docs), S5-F4 (MediaMTX HLS endpoint doc, no code).

## 2. Sequencing principles

1. **Measurement precedes optimization.** Any performance change needs a
   baseline + a post-change measurement to validate. Class B must mostly
   land before Class A.
2. **Prometheus scrape is the critical path.** W1.1 is a multi-session
   carry-over. Every other observability item is academic without it, because
   the metrics never reach Grafana. Ship it first.
3. **Dual-GPU Phase 1 is cheap + reversible.** `CUDA_VISIBLE_DEVICES=0`
   drop-in for studio-compositor can be rolled back in 30 seconds. Landing
   it early (with baseline measurements captured) is safer than deferring.
4. **Class C (audio ducking) is independent of Class A.** It touches
   PipeWire + Python, not CUDA or GStreamer. Can ship in parallel with
   anything.
5. **Class D audits produce facts that unblock Class A Phase 2 decisions.**
   Run the audits before trying to pin wgpu / hapax-dmn.
6. **Class F research waits for measurement.** The stress test, parallel
   encoder validation, and brio-operator re-measure all need Class B +
   Class A Phase 1 to have shipped.
7. **Class G operator-hand items are scheduled, not blocked.** They run
   whenever the operator has a 5-minute window and happens to be at the
   physical rig.

## 3. The plan

Five waves. Every item cites a finding ID. Waves 1–3 are serial for their
biggest items; Waves 4–5 run concurrent to Waves 1–3 as time permits.

### Wave 1 — Observability foundation  [~1 day, cross-repo]

Goal: **every subsequent change has a dashboard + alert to validate against.**

**W1.1** [critical, cross-repo, operator-gated] **Prometheus scrape job for
studio-compositor.** Add to `llm-stack/prometheus.yml`:

```yaml
- job_name: 'studio-compositor'
  static_configs:
    - targets: ['host.docker.internal:9482']
  scrape_interval: 15s
```

Plus `sudo ufw allow 172.18.0.0/16 → 9482`. Closes S6-F1 / queue 024 FINDING-H /
multi-session carry-over. **Every one of the compositor's 122 metrics goes
live the moment this merges.**

- Decision needed: operator applies the ufw rule (sudo) and owns the llm-stack
  repo. Alpha can prepare the yaml diff.

**W1.2** [critical] **node-exporter restore.** S6-F2. Diagnose whether it's a
docker container or systemd user unit, fix the downed state. Host-level
metrics (CPU, memory, USB errors, disk) are missing.

**W1.3** [high] **Per-camera frame-time histograms.** S6-F4. Add
`prometheus_client.Histogram` per camera role with bucket edges `[5, 10, 16,
20, 25, 30, 33, 40, 50, 67, 100, 200, 500]` ms. Update from the pad probe that
already publishes the frame counter. Required by the research map's headline
"p99 ≤ 34 ms" criterion — currently unmeasurable.

**W1.4** [high] **Prometheus alerting rules + alertmanager → ntfy.** S6-F5.
Add `rules.yml` with 9 alerts (compositor down, RTMP disconnected, camera
fps low, frame stale, encoder errors, watchdog starving, pool reuse low,
GPU memory high, GPU power throttling). Wire alertmanager to ntfy (already
in the stack). No more "operator finds out by looking at the stream."

**W1.5** [high] **Postmortem capture on watchdog/crash.** S6-F7.
`ExecStopPost=` hook saves last metrics snapshot + nvidia-smi dump + /dev/shm
state to `~/hapax-state/postmortem/{ts}/`.

**W1.6** [medium] **Per-GPU label verification in nvidia-gpu exporter.**
S6-F6. Quick `curl :9835/metrics` check. If labels missing, swap to
dcgm-exporter. Foundational for Wave 2 dashboards.

**W1.7** [medium] **Audio DSP per-chunk timing histogram.** S3-F5. Add
`hapax_compositor_audio_dsp_ms` histogram so the 93 fps DSP loop is
observable. Needed for Wave 3 sidechain validation.

**W1.8** [medium] **Structured JSON logging for compositor.** S6-F8. Switch
logger formatter. Journal JSON field-level filtering becomes possible.

**W1.9** [low] **Compositor VRAM gauge.** S1 item 172.
`hapax_compositor_vram_bytes` via `nvidia-smi --query-compute-apps` polled
every 30 s.

Exit criterion for Wave 1: `curl http://127.0.0.1:9090/api/v1/targets` shows
`studio-compositor` UP. Grafana dashboard reads a p99 frame-time histogram.
ntfy fires on a test alert rule.

### Wave 2 — Dual-GPU migration  [~1 day, coordinated]

Goal: move compositor + encoder + imagination + display to the 5060 Ti;
validate TabbyAPI contention hypothesis on brio-operator.

**Pre-conditions:** Wave 1.1 + 1.3 + 1.9 shipped (need Prometheus
observability + frame-time histograms + VRAM gauge to validate migration).
Baseline snapshot captured:
`nvidia-smi > ~/hapax-state/dual-gpu/before-migration.txt`.

**W2.0** [prereq] **hapax-dmn 3.3 GiB investigation.** S5b-F6. Read
`agents/hapax_daimonion/__main__.py` + grep for `torch.device`/`cuda` to
determine the workload type. Decide GPU 0 vs GPU 1 placement before Phase 2.

**W2.1** [HIGH — the big one] **Phase 1: studio-compositor
CUDA_VISIBLE_DEVICES=0 drop-in.** S5b-F1, S5-F1, S5-F6. Single systemd drop-in
file. Reversible in 30 seconds. Beta calls this the single highest-leverage
change in the entire research map.

```ini
# systemctl --user edit studio-compositor.service
[Service]
Environment="CUDA_VISIBLE_DEVICES=0"
```

Expected effects:
- Compositor appears on GPU 0 in `nvidia-smi pmon`
- NVENC H.264 encoding moves to Blackwell (better PSNR per bitrate)
- TabbyAPI regains SM cycles on GPU 1 (expect 30–50% latency improvement)

**W2.2** [HIGH — closes multi-sprint mystery] **Phase 1 validation:
brio-operator re-measure.** S7-F1 / S1-F2 / S2-F2. 5 minutes of
`studio_camera_frames_total` deltas immediately after W2.1. If fps jumps from
28.479 to 30.5, the root cause of the multi-sprint brio-operator deficit is
**TabbyAPI SM contention with the compositor**. If fps stays at 28.479, the
original 4 candidates (hero flag, metrics lock, queue depth, hardware) remain
in play. **Cheapest possible test of a 3-sprint open question.**

**W2.3** [medium] **Phase 2: pin remaining workloads.** S5b-F2, S5b-F5.
Drop-ins for:
- `tabbyapi.service`: `Environment="CUDA_VISIBLE_DEVICES=1"`
- `hapax-imagination.service`: `Environment="WGPU_ADAPTER_NAME=5060"`
  (verify env var name against wgpu version in Cargo.toml)
- `hapax-dmn.service`: based on W2.0 decision

**W2.4** [operator-hand] **Phase 3: physical display cable swap.** S5b-F4.
DisplayPort cable 3090 → 5060 Ti. Hyprland config
`WLR_DRM_DEVICES=/dev/dri/card1` (verify card index first). Reboot. Hyprland
comes up on the 5060 Ti.

**W2.5** [HIGH — stress validation] **Phase 4: validation suite.**
`scripts/dual-gpu-validation.sh` runs the matrix from sprint-7 L4: per-camera
fps stability (each ≥30.0, p99 ≤34 ms), TabbyAPI tokens/sec (≥40), RTMP
bitrate stability (±5% of target), 30-min combined stress (no
`hw_power_brake_slowdown`). S5b-F8 / S7-F2 PSU stress included.

Exit criterion for Wave 2: GPU 0 hosts compositor + encoder + imagination
(~5 GiB used). GPU 1 hosts only TabbyAPI + DMN. brio-operator re-measure
report filed. Stress test clean.

### Wave 3 — Audio ducking architecture  [~0.5 day, independent]

Goal: TTS + operator speech both duck music via a smooth sidechain envelope,
not a binary mute.

**W3.1** [high] **PipeWire sidechain compressor config.** S4-F1 + S4-F2.
New file `~/.config/pipewire/pipewire.conf.d/15-music-sidechain.conf` with a
LADSPA sidechain compressor. Threshold -30 dB, 4:1, 30 ms attack, 350 ms
release, 6 dB soft knee. Sidechain input = `mixer_master` monitor (captures
both TTS and Yeti). Signal path = youtube-audio-* streams.
`systemctl --user restart pipewire`.

**W3.2** [high] **Remove binary mute from director_loop.** S4 item 187.
Once the sidechain is live, the hard `mute_all()`/`mute_all_except()` calls
in `director_loop.py:705` and `:724` become harmful (cliff overrides
envelope). Delete them. TTS plays through the same sink; sidechain handles
ducking.

**W3.3** [medium] **voice_active + music_ducked observability.** S4 item 190.
Prometheus gauges so before/after is visible + ongoing ducking latency is
measurable.

**W3.4** [low] **HAPAX_TTS_TARGET docs + default decision.** S4-F4. Current
state: env var unset, TTS goes through default routing (no EQ). Operator
decision: keep default or pin to `hapax-voice-fx-capture` in the daimonion
unit drop-in?

Exit criterion for Wave 3: a test TTS utterance + music plays. Music dips by
~8 dB over 30 ms, sustains, releases over 350 ms when voice stops. No click
at attack. Operator speech into Yeti causes the same ducking (because Yeti
is in `mixer_master` monitor).

### Wave 4 — Targeted audits + small code fixes  [concurrent with 1–3]

Cheap fact-finding + small fixes that don't block anything.

**W4.1** [high] **audio_rms / audio_beat alias audit.** S3-F2. Read
`agents/effect_graph/modulator.py` for an alias table. If it resolves
`audio_rms → mixer_energy` and `audio_beat → mixer_beat`, the 3 affected
presets are fine. If not, either add the aliases or rename in the preset
files. Either way a 10-min task that closes an open question.

**W4.2** [medium] **MediaMTX upstream relay verification.** S5-F7. Read
`~/.config/mediamtx/mediamtx.yml`. Verify `paths.studio` has a `runOnReady`
or `publish` rule that pipes to YouTube/Twitch ingest. If missing, the
stream terminates at MediaMTX with no public output — document + fix.

**W4.3** [medium] **PCIe link width verification.** S5b-F7.
`sudo lspci -vvs 03:00.0 | grep LnkSta` and same for `07:00.0`. Document
actual gen + width. Flag if either is degraded.

**W4.4** [medium] **wgpu env var name verification.** S5b-F5 prep. Read
`hapax-logos/src-imagination/Cargo.toml` for the wgpu version. Check the
supported env var (`WGPU_ADAPTER_NAME` on newer, `WGPU_POWER_PREFERENCE`
on older). Needed before W2.3.

**W4.5** [medium] **Control surface latency histogram.** S7-F3.
`command_latency_ms{stage="..."}` in logos-api with per-stage labels for
the IPC → Rust → inotify → WGSL compile → first frame pipeline (per
sprint-7 P1 path breakdown).

**W4.6** [low] **MediaMTX HLS endpoint wire.** S5-F4. No code change.
Verify MediaMTX HLS is enabled in its config; document the URL
(`http://127.0.0.1:8888/studio/index.m3u8`) for in-app Logos preview.

**W4.7** [low] **brio-synths unclaimed video interfaces.** S1-F3. 10-min
grep + journal check. No fix expected, just documentation.

### Wave 5 — Refactors, spikes, research  [ongoing, as priority allows]

**W5.1** **wgpu Query::Timestamp per-node timing** (S2-F3). Unblocks
per-shader cost attribution; required for Theme E performance tuning.
2 hours + the existing `reverie_pool_*` gauges.

**W5.2** **Sub-frame transient ring buffer smoother** (S3-F1). Ring buffer
of the last N analysis frames + peak-preserving envelope applied at render
tick. Eliminates the 33 ms render-quantization loss for drum hits.

**W5.3** **BPM tracking + beat_phase signal** (S3-F3). Autocorrelation on
beat history or PLL locked to beat grid. Enables tempo-locked effects.

**W5.4** **Audio feature SHM dedupe** (S3-F6). Compositor publishes
signals, daimonion reads, saves ~1.5 cpu-sec/min on daimonion side.

**W5.5** **youtube-audio ffmpeg → GStreamer refactor** (S4-F5). Single
GStreamer pipeline per slot, eliminates the ffmpeg restart gap on URL
change.

**W5.6** **voice/music/instruments OBS subgroup redesign** (S4-F3). Three
null sinks instead of one `mixer_master`. Wireplumber rules route sources
to the right subgroup. OBS independently controls voice vs music faders.

**W5.7** **Audio→visual latency closed-loop validation script** (S7-F4).
Synthetic kick to mixer_master, v4l2-ctl records, grep for brightness drop,
compute delta. Target ≤50 ms.

**W5.8** **TTS GPU spike — StyleTTS 2 on 5060 Ti** (S7-F5, S5b-F9). Prototype,
compare to Kokoro on naturalness + latency. Decide keep / migrate / hybrid.

**W5.9** **Blackwell NVENC feature audit** (S7-F6, S5b-F10). AV1 encode
(`nvav1enc` plugin availability, gst-plugin-bad 1.26+), 4:2:2 chroma,
low-latency modes.

**W5.10** **Parallel encoder stress test** (S7 L3). 3-encoder + 2-decoder
simultaneous load on GPU 0 for 10 min. Validate NVENC session budget +
power + thermal.

**W5.11** **Compositor VRAM 3 GB attribution** (S1-F4). Cross-ref with
queue 026 P3 `pool_metrics.reuse_ratio = 0`. Pool fix may reduce compositor
VRAM significantly.

### Wave 6 — Operator-hand physical actions  [scheduled whenever]

**W6.1** brio-room USB 3.0 cable swap (S1-F1). 5 minutes at the rig.

**W6.2** DisplayPort cable 3090 → 5060 Ti + reboot (S5b-F4, part of W2.4).

**W6.3** Case airflow inspection (S7-F7). Visual + 30-min thermal stress.

**W6.4** Cable hygiene full pass (S7-F8). Inventory + standardize.

## 4. Dependencies (reverse chronological)

Who waits for whom:

```
W5.10 (parallel encoder stress)
  ← W2.5 (Phase 4 validation)
    ← W2.1 (Phase 1 migration)
      ← W1.3 (frame-time histograms)
      ← W1.1 (Prometheus scrape gap)

W2.2 (brio-operator re-measure)
  ← W2.1 (Phase 1 migration)

W2.3 (Phase 2 pin remaining workloads)
  ← W2.0 (DMN investigation)
  ← W4.4 (wgpu env var verification)

W3.2 (remove binary mute)
  ← W3.1 (sidechain compressor live)
  ← W1.7 (audio DSP timing histograms — observability pre-req)

W5.8 (TTS GPU spike)
  ← W2.5 (Phase 4 validation — need headroom on 5060 Ti proven)

everything alerting-gated
  ← W1.1 (Prometheus scrape)
  ← W1.4 (alertmanager + ntfy)
```

**The critical path has only 3 nodes**: W1.1 → W2.1 → W2.5. Everything else
is parallelizable.

## 5. Decisions needed from the operator

Before execution starts:

1. **Prometheus scrape gap (W1.1):** the change is cross-repo (`llm-stack`)
   + requires `sudo ufw`. Does the operator want alpha to produce the yaml
   diff + document the ufw command, or does alpha own the entire change with
   operator authorisation to sudo? This has been open 3+ sessions.

2. **Dual-GPU migration window (W2):** Phase 1 is 1 minute and reversible.
   Phase 3 is physical (cable + reboot, ~5 min downtime). Needs an operator
   window. Acceptable: "schedule for next break in livestream." Unacceptable:
   "ship blind during a live show."

3. **TabbyAPI explicit pin to GPU 1 (W2.3):** removes fallback. If GPU 1
   fails, TabbyAPI cannot use GPU 0 as a backup. Acceptable for predictability?
   Or prefer `CUDA_VISIBLE_DEVICES=1` not-set + rely on default routing?

4. **PipeWire sidechain parameters (W3.1):** beta proposed
   -30 dB threshold, 4:1 ratio, 30 ms attack, 350 ms release, 6 dB soft knee.
   Is this the starting point to tune from, or does the operator want
   different defaults?

5. **Alertmanager + ntfy (W1.4):** adds a Docker service. Acceptable?
   Alternative: Python sidecar that polls Prometheus and writes to ntfy
   directly (no alertmanager container).

6. **HAPAX_TTS_TARGET default (W3.4):** keep default routing or pin TTS to
   the EQ chain (`hapax-voice-fx-capture`) in the daimonion unit?

## 6. What alpha already shipped (no rework needed)

- **PR #776 — FreshnessGauge hyphen sanitize** (S2-F1 + S6-F3). This was
  flagged as a cherry-pick in retrospect but the fix itself is aligned with
  Wave 1 (observability foundation). Keep.
- **Memory file drift update** (S2-F5). `56 WGSL nodes / 30 presets` now
  reflected in `project_effect_graph.md`. No PR needed (memory file is not
  in git).
- **Verified no-ops**: S5-F5 (bitrate already 6000), S2-F4 (cudacompositor
  already active), S2-F6 (graph-mutation not a bug), S5-F8 (tee architecture
  sound), S3-F4 (sidechain kick already wired).

## 7. Out of scope (deliberately)

- **Content creative decisions.** What the effects should look like
  aesthetically. Research map explicitly excludes.
- **Hardware procurement.** PSU upgrade path (if stress test fails) is an
  operator decision, not an alpha deliverable.
- **Voice daemon LLM tiering + routing.** Covered by queues 022–026,
  out-of-scope for this research.
- **Obsidian plugin.** Except as a content-resolver source to the
  compositor's ground surface.

## 8. Estimated effort

| wave | items | serial time | parallelizable |
|---|---|---|---|
| Wave 1 — observability | 9 | 1 day (with cross-repo) | yes |
| Wave 2 — dual-GPU migration | 6 | 1 day (with operator window) | no |
| Wave 3 — audio ducking | 4 | 0.5 day | yes |
| Wave 4 — targeted audits | 7 | 1 day total (shreddable) | yes |
| Wave 5 — refactors + spikes | 11 | 2 weeks | yes |
| Wave 6 — operator physical | 4 | 30 min total at rig | operator-gated |

**Total critical path**: ~2 days of focused work (W1.1 → W1.3 → W2.1 →
W2.2 → W2.5). After that, Waves 3–5 run in parallel over ~2 weeks.

## 9. What I need from the operator to start

Three yes/no calls unblock ~70% of the plan:

1. **W1.1** — OK to prepare + apply the llm-stack prometheus.yml + ufw
   rule?
2. **W2.1** — OK to ship the `CUDA_VISIBLE_DEVICES=0` drop-in in a
   non-livestream window today?
3. **W3.1** — OK to ship the PipeWire sidechain .conf with beta's
   recommended parameters as starting points?

Yes on all three = alpha starts W1.1 immediately, W2.1 + W3.1 in parallel
worktrees. No on any = alpha presents the alternative and waits.

Everything else (Waves 4–6) flows as time permits while the critical path
is blocked on CI or operator hands.
