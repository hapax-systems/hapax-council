---
title: Audio Pipeline Health Monitor Suite — Per-Dimension Continuous Visibility
date: 2026-05-03
author: alpha (Claude Opus 4.7)
audience: operator + alpha + beta + delta + cx-* + epsilon
register: scientific, engineering-normative
status: design spec — implementation gated on the deployment-audit (parallel agent ae5440907f1278971) returning CLEAN. NO daemon code lands in this PR.
operator-directive-load-bearing: |
  "After everything is confirmed 100% working through direct observation, I want
   a series of health monitors created that tracks the actual health of the audio
   pipes in its relevant dimensions." — operator, 2026-05-03

related:
  - agents/audio_signal_assertion/ (H1 already-shipped daemon — Dimension 1, formalised here as the FIRST monitor in the suite)
  - scripts/hapax-audio-safe-restart (H2 pre-flight gate — uses the same probe primitives but is per-restart, not continuous)
  - shared/broadcast_audio_health.py (legacy LUFS + 17.5 kHz marker-tone producer; running every 30s as a oneshot timer; the LEGACY surface this suite extends + integrates with)
  - agents/broadcast_audio_health/l12_broadcast_scene_probe.py (Audit A#6 L-12 BROADCAST scene unloaded probe — already wired to the legacy producer cadence)
  - shared/recovery_counter_textfile.py (Prometheus textfile-collector pattern — every monitor in this suite emits via this primitive)
  - docs/superpowers/specs/2026-05-03-audio-graph-ssot-and-router-daemon-design.md §4.2 EgressCircuitBreaker (the FUTURE auto-mute layer — this suite is the OBSERVABILITY layer that makes the breaker's invariants legible to the operator before the breaker takes write authority)
  - grafana/dashboards/audio-stage-rms.json (per-stage RMS dashboard, audit-B)
  - grafana/dashboards/hapax-audio-recovery.json (recovery-events + LUFS, audit-H3)
  - shared/audio_topology.py (topology descriptor — Monitor 4 reads it as canonical)
  - shared/audio_topology_inspector.py (live-graph reader — Monitor 4 + Monitor 7 reuse its primitives)
  - docs/research/2026-05-03-deployment-pipeline-audit.md (the deployment gap that left the H1 daemon SHIPPED-NOT-RUNNING — this suite's Monitor 0 closes that gap)

constraint: |
  Design only. NO daemon code, NO systemd unit creation, NO PipeWire mutation,
  NO config edits in this PR. The spec ships as docs-only on
  alpha/audio-pipeline-health-monitor-suite-spec. Implementation fires AFTER
  the deployment audit (parallel agent ae5440907f1278971) returns CLEAN —
  that gate is operator-owned.

  Each monitor's cc-task is filed alongside the spec. Implementation is
  partitioned across 6 cc-tasks so monitors ship independently and fail
  independently — the suite's load-bearing property.

---

# §0. What this gives the operator (3 sentences + dashboard)

The audio pipeline today is observable through ONE health surface (`hapax-broadcast-audio-health` LUFS + L-12 scene probe, oneshot every 30s) and one shipped-but-not-running classifier daemon (`hapax-audio-signal-assertion` from PR #2423). This suite **completes the observability**: 6 independent monitors covering 11 distinct failure dimensions, each emitting Prometheus textfile gauges that compose into one operator-facing Grafana dashboard. After the suite ships, every recurring audio failure class — silence, clipping, format-conversion noise, channel collapse, topology drift, USB xrun storms, constitutional leak, latency runaway, service-restart cascade — has its OWN continuous gauge with operator-tunable thresholds and ntfy-on-breach.

```
┌─────────────────────────── Hapax / Audio / Pipeline Health ──────────────────────────────┐
│                                                                                          │
│  M1 SIGNAL CLASS    M2 LUFS-S        M3 CREST/ZCR/SF  M4 INTER-STAGE     M5 PIPEWIRE     │
│  ┌────────────┐    ┌────────────┐    ┌────────────┐  ┌────────────┐    ┌────────────┐   │
│  │ master    M│    │   -19.1    │    │ crest 4.2  │  │ corr 0.97  │    │ xruns 0/s  │   │
│  │ norm      M│    │   LUFS-I   │    │ zcr  0.08  │  │ master⇄norm│    │ underrun 0 │   │
│  │ obs       M│    │  ─────     │    │ sf   0.21  │  │ ──────     │    │ over    0  │   │
│  │ status: OK │    │ ●●●○○ band │    │ status: OK │  │ status: OK │    │ status: OK │   │
│  └────────────┘    └────────────┘    └────────────┘  └────────────┘    └────────────┘   │
│                                                                                          │
│  M6 TOPOLOGY       M7 CONSTITUTIONAL   M8 CHAN-POSITION    M9 LATENCY E2E               │
│  ┌────────────┐   ┌────────────────┐   ┌────────────┐     ┌────────────┐                │
│  │  modules   │   │ private→bcast  │   │ master 2/2 │     │ l12 → obs  │                │
│  │  expected  │   │  watermark     │   │ norm   2/2 │     │   23.1 ms  │                │
│  │  37 / 37   │   │   NOT FOUND ✓  │   │ obs    2/2 │     │ Δbase +1.2 │                │
│  │  status: OK│   │  status: OK    │   │ status: OK │     │ status: OK │                │
│  └────────────┘   └────────────────┘   └────────────┘     └────────────┘                │
│                                                                                          │
│  M10 SERVICE CORRELATION                M11 L-12 USB CONTINUITY    SUITE STATUS         │
│  ┌────────────────────────────┐         ┌──────────────────┐       ┌──────────────────┐ │
│  │ daimonion: running         │         │ device PRESENT   │       │ 11/11 dims UP    │ │
│  │ compositor: running        │         │ rate 48000 Hz    │       │ last breach: -   │ │
│  │ orchestr.: running (stale) │         │ alsa xruns 0/min │       │ next probe: 23s  │ │
│  └────────────────────────────┘         └──────────────────┘       └──────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

Each tile maps to one monitor (or a monitor's sub-dimension). Tile colour follows
gruvbox-hard-dark per `docs/logos-design-language.md` §3 — green / yellow / red on
threshold breach. Numbers refresh at the monitor's own probe cadence; tile status
reflects the most recent probe. Operator sees in <5 s whether anything is
deteriorating, and the title bar links to the relevant runbook anchor on click.

---

# §1. Architectural pattern — independent monitors, shared probe primitives

Each monitor in the suite is its own systemd user service. Each:

1. Reads its OWN config (`HAPAX_AUDIO_HEALTH_<MONITOR>_*` env vars).
2. Probes its OWN dimension at its OWN cadence.
3. Emits its OWN Prometheus textfile gauge (`hapax_audio_health_<dim>_*`).
4. Writes its OWN snapshot JSON to `/dev/shm/hapax-audio-health/<dim>.json`.
5. Ntfys its OWN breach (priority + tags follow severity).
6. Is restartable / disable-able / stoppable INDEPENDENTLY without affecting any other monitor.

### 1.1 Shared probe primitives — `agents/audio_health/`

The H1 daemon's classifier, parecord-driven probes, and transition state machine
are factored out into a reusable package:

```
agents/audio_health/
  ├── __init__.py
  ├── probes.py           # NEW location for capture_and_measure(), discover_broadcast_stages()
  ├── classifier.py       # NEW location for measure_pcm(), classify(), Classification enum
  ├── transitions.py      # NEW location for TransitionDetector hysteresis machine
  ├── pcm_metrics.py      # extension: spectral_flatness(), zero_crossing_rate() (already in classifier),
  │                       # crest_factor() (already in classifier), lufs_short_integrated()
  ├── pipewire_query.py   # NEW: typed wrappers around pactl/pw-cli/pw-top/pw-link
  ├── topology_query.py   # NEW: thin wrappers around shared/audio_topology_inspector.py
  ├── prom_emit.py        # NEW: convenience wrappers around shared/recovery_counter_textfile.py
  │                       # — keeps every monitor's metric-emit < 30 LOC
  ├── livestream_gate.py  # NEW: livestream_active flag-file reader (shared with H1's existing logic)
  └── snapshot.py         # NEW: atomic /dev/shm/hapax-audio-health/<dim>.json writer
```

The H1 daemon (`agents/audio_signal_assertion/`) is **refactored to import these** —
the package keeps its top-level entrypoint, but its internal modules become
thin wrappers around `agents/audio_health/`. This is mechanical refactor work;
no behaviour change.

**Refactor scope is bounded:** H1 retains its own `daemon.py`, its own
`__main__.py`, its own systemd unit, its own metric file, its own snapshot path.
The package extraction is structural only. **Existing PR #2423's tests continue
to pass unchanged** because the import path stays the same — `from
agents.audio_signal_assertion import classify, ProbeMeasurement` still works
via re-export.

### 1.2 Unit naming + textfile naming convention

Every suite monitor follows:

```
systemd unit:    hapax-audio-health-<dim>.service       (Type=notify, WatchdogSec=120s)
                 hapax-audio-health-<dim>.timer         (only for low-cadence monitors;
                                                         high-cadence ones are daemons)
prom textfile:   hapax_audio_health_<dim>.prom          (under /var/lib/node_exporter/textfile_collector/)
metric prefix:   hapax_audio_health_<dim>_*             (snake_case sub-metrics)
shm snapshot:    /dev/shm/hapax-audio-health/<dim>.json
runbook anchor:  docs/runbooks/audio-pipeline-health.md#<dim>
ntfy topic:      audio-health-<dim>-breach
```

`<dim>` slugs:

| `<dim>` | Monitor | Cadence |
|---|---|---|
| `signal-class` | M1 — H1 5-class classifier (extension of existing) | daemon, 30s probe |
| `lufs-s` | M2 — short-term integrated loudness rolling band | daemon, 1s probe (continuous) |
| `crest-flatness` | M3 — crest / ZCR / spectral flatness extension | daemon, 5s probe |
| `inter-stage-corr` | M4 — envelope correlation broadcast-master ↔ broadcast-normalized ↔ obs | daemon, 5s probe |
| `pipewire-xrun` | M5 — `pw-top -b` xrun + buffer-underrun counters | daemon, 10s probe |
| `topology-drift` | M6 — `pactl list modules` signature vs canonical | timer, 5min probe |
| `constitutional-watermark` | M7 — private→broadcast watermark injection (constitutional invariant live-check) | daemon, 60s probe |
| `channel-position` | M8 — capture vs descriptor channel-count consistency (catches 14ch/2ch silent-downmix) | timer, 1min probe |
| `latency-e2e` | M9 — known-input → known-output round-trip via watermark tone | daemon, 5min probe |
| `service-correlation` | M10 — daimonion / compositor / orchestrator restart events vs audio state changes | daemon, 30s probe |
| `l12-usb-continuity` | M11 — alsa xrun counters + device PRESENT/ABSENT + sample-rate drift | daemon, 30s probe |

The naming is **load-bearing**: ops scripts grep on `hapax-audio-health-` to
list the suite, the textfile prefix is what the Grafana dashboard alerts on, and
the runbook anchor format is what the ntfy body links the operator to.

### 1.3 Failure independence + suite-status meta-monitor

Every monitor MUST run as `Restart=on-failure` with `RestartSec=10s` and
WatchdogSec long enough that one slow probe doesn't trip systemd. Crucially:
each monitor's failure must NOT cascade to the others. The suite ships with
ONE meta-monitor (`hapax-audio-health-meta.service`) that:

- Reads each monitor's textfile for staleness (mtime > 5 × probe cadence = stale).
- Emits `hapax_audio_health_suite_up{monitor="<dim>"} 0|1` — a binary up gauge per monitor.
- Emits `hapax_audio_health_suite_freshness_seconds{monitor="<dim>"}` — age of the most recent emit.
- Ntfys the operator when any monitor goes 0 (down) for >2 probe cadences.

The meta-monitor is the operator's "are my monitors working?" surface. It is
**not** the suite-internal degradation detector — the per-monitor breach
notifications are the primary signal. Meta-monitor is purely about
suite-self-observability.

---

# §2. The 6 cc-tasks — monitor groups + WSJF

Operator's framing was "a series of monitors". 11 dimensions split into 6 cc-tasks.
Each cc-task is one PR, ships one or more monitors that share a probe primitive,
and fails independently:

| cc-task | Monitors | WSJF | Effort | Depends on |
|---|---|---|---|---|
| `audio-health-suite-package-extract` (gate task; Monitor 0) | shared `agents/audio_health/` package + H1 refactor + meta-monitor + suite Grafana dashboard skeleton | 12 | 2 | deployment audit CLEAN; H1 unit installed |
| `audio-health-classifier-suite-extend-h1` | M1 signal-class (extend H1) + M2 LUFS-S band + M3 crest/ZCR/flatness | 11 | 3 | `audio-health-suite-package-extract` |
| `audio-health-topology-and-channel-monitors` | M6 topology drift + M8 channel-position consistency | 10 | 2 | `audio-health-suite-package-extract` |
| `audio-health-pipewire-stage-correlation` | M4 inter-stage envelope corr + M5 pw-top xrun + M11 L-12 USB continuity | 10 | 3 | `audio-health-suite-package-extract` |
| `audio-health-constitutional-watermark-and-latency` | M7 watermark constitutional probe + M9 end-to-end latency | 9 | 3 | `audio-health-suite-package-extract` |
| `audio-health-service-correlation-and-grafana` | M10 service-correlation monitor + Grafana dashboard import + waybar widget | 8 | 2 | All others (last to ship; cross-cuts data from 1-5) |

WSJF is anchored against today's reference points:
- `audio-graph-ssot-p1-compiler-validator` = 13 (locks the schema)
- `audio-graph-ssot-p2-daemon-shadow` = 12 (introduces the daemon)
- This suite's gate task = 12 (same tier as P2 — it ships the package + meta-monitor without which the rest cannot exist; both are foundational + non-controversial)
- Most monitor groups = 10 (same tier as `audio-graph-ssot-p3-lock-transaction` which ships the apply lock — operator-visible value, no breaker authority yet)
- Service-correlation last = 8 (cross-cuts existing data; lower marginal value than the new dimensions)

Total effort estimate: 15 effort-days across 6 cc-tasks. Probe primitives are
shared so the package-extract task absorbs the extraction cost up front.

---

# §3. Monitor specs — per-dimension

Each section: probe mechanism + frequency + Prometheus metrics + waybar / Grafana surface + failure modes + thresholds.

## §3.1 Monitor 0 (gate) — `agents/audio_health/` package + meta-monitor

**Purpose:** Ship the shared probe primitive package, refactor H1 to depend on it,
land the suite-status meta-monitor + Grafana dashboard skeleton.

**Probe mechanism:** N/A (this monitor IS the package).

**Deliverables:**
1. `agents/audio_health/__init__.py` exporting all primitives.
2. `agents/audio_health/probes.py` — moved from `agents/audio_signal_assertion/probes.py` with re-export shim left in place.
3. `agents/audio_health/classifier.py` — moved from `agents/audio_signal_assertion/classifier.py` with shim.
4. `agents/audio_health/transitions.py` — moved from `agents/audio_signal_assertion/transitions.py` with shim.
5. `agents/audio_health/pcm_metrics.py` — NEW: `lufs_short_integrated(samples, sample_rate, gating="momentary")` + `spectral_flatness(samples, sample_rate)`. Uses `pyloudnorm` (already a dep via `shared/audio_loudness.py`). Spectral flatness is `geometric_mean(|FFT|^2) / arithmetic_mean(|FFT|^2)`, range 0..1.
6. `agents/audio_health/pipewire_query.py` — typed wrappers: `list_modules()`, `list_sinks_short()`, `pw_top_one_pass()`, `pw_link_table()`. Each returns a Pydantic model so callers don't reinvent parsing.
7. `agents/audio_health/topology_query.py` — thin wrappers around `shared/audio_topology_inspector.py` returning Pydantic models the monitors can directly emit.
8. `agents/audio_health/prom_emit.py` — `emit_dim(dim, metric, labels, value, help)` wrapping `shared.recovery_counter_textfile.write_gauge` with the `hapax_audio_health_<dim>` prefix convention.
9. `agents/audio_health/livestream_gate.py` — `is_livestream_active(now=None)` reading `/dev/shm/hapax-broadcast/livestream-active`.
10. `agents/audio_health/snapshot.py` — `write_snapshot(dim, payload)` atomically writing to `/dev/shm/hapax-audio-health/<dim>.json`.
11. `agents/audio_health_meta/` — meta-monitor daemon. Reads each monitor's textfile mtime, emits `hapax_audio_health_suite_up`, `hapax_audio_health_suite_freshness_seconds`. Ntfys on monitor-down.
12. `systemd/units/hapax-audio-health-meta.service` — `Type=notify`, `WatchdogSec=300s`.
13. **H1 deployment fix:** install `hapax-audio-signal-assertion.service` into the user systemd directory (currently shipped on main but not deployed — deployment audit § C). Validates the `Type=notify` protocol works. The deployment audit's parallel-agent gate is upstream of this; the package-extract task assumes the audit closed the deployment gap. If audit returns DIRTY for H1's unit, fix that first, then ship the package.
14. `grafana/dashboards/hapax-audio-pipeline-health.json` — suite skeleton with one row per monitor, sub-tiles per metric. Monitor groups fill the panels in their own PR.
15. `docs/runbooks/audio-pipeline-health.md` — runbook stub with one anchor per monitor (`#signal-class`, `#lufs-s`, etc.). Each cc-task fills its anchor in its own PR.

**Failure modes this monitor catches:**
- Suite member crashed silently. Without the meta-monitor, the only signal is the absence of recent textfile mtimes, which Prometheus alerting can express but the operator's waybar can't.
- Probe primitive bug (e.g. parecord regression) affecting all monitors. The meta-monitor's `up=0` for every monitor in the suite is a **system-wide audio-observability failure** signal.

**Why this is the gate task:** Every other cc-task imports from `agents/audio_health/`. Without the package, monitor groups would each reinvent probe primitives — exactly the duplication risk the spec wants to avoid. Also the suite is meaningless without a self-test (meta-monitor); a single dead monitor breaching while others observe-only is a known incident pattern from H1's experience.

## §3.2 Monitor 1 — Signal classification per stage (M1, extends H1)

**Purpose:** Continuous 5-class classification (silent / tone / music_voice / noise / clipping) at every broadcast stage. Already shipped per H1.

**Extension scope (in this suite):**
- **Stages probed:** add `hapax-livestream-tap.monitor` to H1's existing 3-stage tuple. Today: master, normalized, obs-remap. Adding livestream-tap gives visibility into the FIRST stage that introduces format/channel changes (the 14ch→2ch downmix), which is where today's #5 silent-downmix bug originated.
- **OBS-bound ntfy stays at the SAME stage** (`hapax-obs-broadcast-remap`). Other stages emit metrics + log transitions but do not page solo.
- **Per-stage textfile metric:** `hapax_audio_health_signal_class_class{stage="<name>",classification="<class>"}` (1.0 active, 0.0 inactive — already H1's shape).
- **Operator runbook anchor:** `docs/runbooks/audio-pipeline-health.md#signal-class`.

**Probe mechanism:** parecord against `<stage>.monitor`, 2s capture, 48 kHz s16le, downmix to mono, classify per `agents/audio_health/classifier.py`. (Already shipped in H1.)

**Frequency:** 30s probe interval (H1 default).

**Hysteresis:** clipping 2s sustain, noise 2s sustain, silence 5s sustain (livestream-active only). Recovery: 10s good-window. (All H1 defaults.)

**Failure modes caught:** silent broadcast (RMS <-55 dBFS sustained 5s with livestream active), clipping noise (peak >-1 dBFS or crest <5 with RMS >-10 dBFS sustained 2s), white-noise / format-conversion artefact (crest in [2.5, 5.0] with ZCR ≥0.25 sustained 2s), DC drone / hum (crest <2.0 sustained 2s).

## §3.3 Monitor 2 — LUFS-S rolling integrated loudness (M2)

**Purpose:** Track ITU-R BS.1770 short-term integrated loudness against a band defined per stage. Today the legacy `shared/broadcast_audio_health.py` measures LUFS but only at one stage and only every 30s. M2 tracks LUFS-S continuously so transient out-of-band events show up.

**Probe mechanism:**
- parecord 0.5s windows from `hapax-broadcast-master.monitor` and `hapax-obs-broadcast-remap.monitor`.
- Pass through `pyloudnorm.Meter(rate, block_size=0.4)` short-term integrated calculation.
- Maintain a 3s rolling buffer per stage; emit gauges every 1s.

**Frequency:** 1s emit cadence; 0.5s capture window; 3s rolling history.

**Prometheus metrics:**
- `hapax_audio_health_lufs_s_value{stage}` — current short-term integrated LUFS.
- `hapax_audio_health_lufs_s_band_breach_count{stage,direction}` — counter of breaches above / below band per stage.
- `hapax_audio_health_lufs_s_in_band{stage}` — 1.0 if current value in band, 0.0 if out.

**Thresholds (env-overridable, defaults per stage):**

| Stage | Band (LUFS-S) | Rationale |
|---|---|---|
| `hapax-broadcast-master` | [-23, -16] | Pre-loudnorm; broad band ok |
| `hapax-obs-broadcast-remap` | [-22, -18] | Post-loudnorm; tight band; YouTube target -14 LUFS-I → -18 to -20 LUFS-S typical |

**Hysteresis:** breach must sustain ≥3s before ntfy (avoids brief track-change excursions).

**Ntfy:** out-of-band on `hapax-obs-broadcast-remap` for >3s = high-priority page. Other stages emit metric + log only.

**Failure modes caught:** post-limiter slam (LUFS spikes high), accidental gain stage (LUFS drift up), bed-music bleed (LUFS spikes), silence-on-stream (LUFS drops to floor).

**Integration with existing legacy:** the legacy `hapax-broadcast-audio-health` 30s timer measures LUFS-I at one stage. **Do NOT duplicate.** M2 is the rolling-short-term continuous version; legacy is the 30s integrated cadence. Legacy stays for the safety-envelope SSOT (`audio_safe_for_broadcast` JSON). M2 is the real-time observability layer.

## §3.4 Monitor 3 — Crest factor + ZCR + spectral flatness (M3)

**Purpose:** Three complementary acoustic content discriminators. Crest stability + ZCR + Wiener entropy / spectral flatness together can distinguish:
- Music / voice (crest 5+, ZCR <0.15, flatness <0.3)
- White noise (crest 2.5–4.5, ZCR ~0.5, flatness >0.6)
- Tone / drone (crest <2, ZCR very low, flatness <0.1)
- Format-conversion artefact (crest 3–5, ZCR irregular, flatness 0.4–0.6)

**Probe mechanism:**
- parecord 5s window from each broadcast stage (covers more harmonic detail than M1's 2s).
- Compute crest, ZCR, spectral flatness via `agents/audio_health/pcm_metrics.py`.
- Spectral flatness via FFT: `exp(mean(log(|FFT|^2 + ε))) / mean(|FFT|^2 + ε)`.

**Frequency:** 5s probe interval (overlapping with H1's 30s but at finer granularity for the discrimination axes).

**Prometheus metrics (per stage):**
- `hapax_audio_health_crest_flatness_crest{stage}`
- `hapax_audio_health_crest_flatness_zcr{stage}`
- `hapax_audio_health_crest_flatness_spectral_flatness{stage}`
- `hapax_audio_health_crest_flatness_drop_below_5_count{stage}` — counter, sudden drop event
- `hapax_audio_health_crest_flatness_rise_above_20_count{stage}` — counter, transient incoming

**Thresholds:**
- Crest sudden drop: from >5 to <5 within 5s → `format-conversion noise entering` ntfy.
- Crest sudden rise: from <10 to >20 within 5s → `transient / clipping incoming` ntfy.
- Spectral flatness sustained >0.6 for 10s → `white noise dominant` ntfy.

**Hysteresis:** drop / rise events require 2 consecutive observations to fire (10s sustained signal change).

**Failure modes caught:** format-conversion noise emergence (the H1 `noise` class), narrow-band feedback / oscillation (crest spike + flatness drop), accidental compressor on (crest drops + flatness rises slightly).

## §3.5 Monitor 4 — Inter-stage envelope correlation (M4)

**Purpose:** Detect signal loss between stages. Master → normalized → obs-remap should have correlated envelopes (>0.9 on real signal). If correlation drops mid-stream, signal has been lost between stages.

**Probe mechanism:**
- parecord 2s windows from `hapax-broadcast-master.monitor`, `hapax-broadcast-normalized.monitor`, `hapax-obs-broadcast-remap.monitor` simultaneously (3 parallel processes).
- Compute envelope via abs() + 100ms moving average (downsample to 10 Hz).
- Compute Pearson correlation across pairs: master ⇄ normalized, normalized ⇄ obs.
- Emit gauges per pair.

**Frequency:** 5s probe interval.

**Prometheus metrics:**
- `hapax_audio_health_inter_stage_corr{pair="master-normalized"}` — float in [-1, 1].
- `hapax_audio_health_inter_stage_corr{pair="normalized-obs"}`.
- `hapax_audio_health_inter_stage_corr_low_count{pair}` — counter, breach events.

**Thresholds:**
- Correlation < 0.7 with both stages above silence floor → `signal lost between <pair>` ntfy.
- Sustained for 10s before fire (avoids transient probe-vs-probe phase mismatch).

**Caveats:**
- Brief silence on all 3 stages → correlation undefined; emit NaN, do NOT page.
- Time-aligned capture is approximate (parallel parecord starts skew by ~50 ms); the correlation is over the envelope (10 Hz), so 50 ms skew is well within the noise floor.

**Failure modes caught:** apply-then-no-signal (today's #4 + #11 from the SSOT spec), stage-internal dropout (e.g. loudnorm filter chain crash), broken pw-link in mid-chain.

## §3.6 Monitor 5 — PipeWire xrun / buffer-underrun counters (M5)

**Purpose:** PipeWire-internal buffer underruns and xruns are an early warning that the kernel scheduler is lagging or a node is stalled. Today there is NO operator-visible signal for this — `pw-top -b` shows it but it's not emitted as a metric.

**Probe mechanism:**
- `pw-top -b -n 1` returns a one-shot snapshot of all nodes with QUANT, RATE, WAIT, BUSY, ERR columns.
- Parse the ERR column per node — it counts xruns since pw-top start.
- Maintain a per-node delta counter. Emit increments only.

**Frequency:** 10s probe interval.

**Prometheus metrics:**
- `hapax_audio_health_pipewire_xruns_total{node}` — counter.
- `hapax_audio_health_pipewire_busy_pct{node}` — gauge, instantaneous BUSY% from pw-top.
- `hapax_audio_health_pipewire_wait_pct{node}` — gauge, instantaneous WAIT%.

**Thresholds:**
- Any node with xrun delta >5 per probe → `<node> xrun storm` ntfy (high priority on broadcast-family nodes).
- Any node with BUSY >90% sustained 30s → `<node> compute-bound` ntfy.

**Failure modes caught:** kernel scheduler regression, USB controller flapping, GPU contention with audio thread (CUDA workload + audio share core), filter-chain compute exceeding quantum budget.

## §3.7 Monitor 6 — Topology drift (M6)

**Purpose:** `pactl list modules` should match a canonical signature. New module appearing → uninvited writer. Module disappearing → silent regression.

**Probe mechanism:**
- `pactl list modules short` returns one line per loaded module.
- Filter to `module-loopback`, `module-null-sink`, `module-pipe-source`, `module-remap-sink` (the topology-affecting kinds).
- Hash the sorted module argument list per module class.
- Compare against the canonical descriptor (`config/audio-topology.yaml` resolved through `shared/audio_topology_inspector.py`).

**Frequency:** 5min probe interval (low cadence — topology changes are rare events).

**Prometheus metrics:**
- `hapax_audio_health_topology_modules_expected` — gauge.
- `hapax_audio_health_topology_modules_observed` — gauge.
- `hapax_audio_health_topology_drift{kind}` — gauge per module class, 0 if aligned, 1 if drift detected.
- `hapax_audio_health_topology_drift_event_count{direction="appeared|disappeared"}` — counter.

**Thresholds:**
- Any drift > 0 → `topology drift: <module> <appeared|disappeared>` ntfy.
- WirePlumber / PipeWire restart events suppress the alert for 30s post-restart (legitimate retransition).

**Failure modes caught:** today's #8 (BT hijack of OBS-monitor loopback), session-edit conflicts (today's audit § E `5 concurrent writers` finding), accidental session-mode flips (e.g. webcam-audio-suppress udev rules failing).

**Integration with SSOT:** Once the `hapax-pipewire-graph` daemon ships (audio-graph-ssot-p4), this monitor's role narrows to "detect drift caused by external writers" — the daemon is the only authorised internal writer. M6 is the canary that detects external (manual / agent / udev) writers; the daemon's own apply transactions emit a different metric (`hapax_pipewire_graph_apply_count`).

## §3.8 Monitor 7 — Constitutional invariants live-check (M7)

**Purpose:** Continuously verify that "private must not reach broadcast" holds at runtime by injecting a unique watermark into private-tagged stages and asserting it does NOT appear at OBS.

**Probe mechanism:**
- Generate a 60-second unique sine-tone watermark at 19.5 kHz (above broadcast content but within Nyquist for 48 kHz). Different watermark per probe so adjacent probes are distinguishable.
- Use `pactl load-module module-pipe-source` to inject the tone into one private-tagged sink at a time (rotate through `hapax-private-monitor`, `hapax-notification-private`, `hapax-music-private` etc.).
- Capture 60s from `hapax-obs-broadcast-remap.monitor`.
- FFT the captured audio; check whether the watermark frequency bucket exceeds noise floor by >20 dB.
- If detected → constitutional violation: private has reached broadcast.

**Frequency:** 60s probe interval (1 watermark per private stage per minute, rotated). Each probe is gated on `livestream_active=True` AND `monitor_via_pactl_load_safe=True` (a flag-file the operator can clear to disable injection during sensitive operator-speech windows).

**Prometheus metrics:**
- `hapax_audio_health_watermark_injected_total{private_stage}` — counter.
- `hapax_audio_health_watermark_detected_at_egress_total{private_stage}` — counter (should always be 0; non-zero is constitutional violation).
- `hapax_audio_health_watermark_last_check_age_seconds{private_stage}` — gauge.

**Thresholds:**
- ANY non-zero `watermark_detected_at_egress_total` → P0 ntfy (constitutional violation, axiom `interpersonal_transparency`-equivalent for private-broadcast-segregation invariant). Includes the private stage's name + the watermark frequency in the body so the operator sees exactly which segregation broke.

**Caveats:**
- The 19.5 kHz tone is below the operator's typical hearing-loss notch (>16 kHz typical for adults) but ABOVE bed-music spectral content (95% of music energy <8 kHz). The operator may hear it briefly during the 60s injection if speakers are out — this is acceptable because the test happens once a minute per private stage and the tone is audible only in extreme listening setups.
- Injection is via `module-pipe-source` so it does NOT modify the operator's existing audio chain — the tone is added in parallel to whatever is already on the private sink.
- **Fail-CLOSED:** if injection fails (pactl returns non-zero, sink absent), emit `hapax_audio_health_watermark_inject_failure_total{private_stage}` and ntfy at warning priority. A failed injection means the test couldn't run; the operator must investigate before assuming all-clear.

**Failure modes caught:** today's #3 (private→L-12 leak), today's missing topology validations that allowed cross-tier audio leaks (which the existing `audio-leak-guard.sh` only catches statically). M7 is the **runtime** version: even if the static graph passes, M7 catches any actual audio leak that reaches OBS.

**Constitutional grounding:** the operator's framing puts "private must not reach broadcast" as an axiom-grade invariant. M7 makes that invariant **continuously testable** — the monitor IS the invariant's dynamic semantics.

## §3.9 Monitor 8 — Channel-position consistency (M8)

**Purpose:** The capture audio.position must match the descriptor's declared channel-count. Today's #5 silent-downmix bug was: 14ch capture node feeding a 2ch declared sink without an explicit downmix → silent.

**Probe mechanism:**
- For each node in the topology descriptor's `nodes[]`:
  - `pactl list sinks long | grep -A 50 'Name: <descriptor.pipewire_name>'` parses live channel count.
  - Compare against `descriptor.channels.count`.
- Mark any mismatch.

**Frequency:** 1min probe interval (channel topology rarely changes).

**Prometheus metrics:**
- `hapax_audio_health_channel_position_match{node}` — gauge, 1 if matched, 0 if mismatched.
- `hapax_audio_health_channel_position_declared{node}` — gauge, declared count.
- `hapax_audio_health_channel_position_observed{node}` — gauge, observed count.

**Thresholds:** ANY mismatch → ntfy with declared vs observed counts. (Explicit downmix nodes are exempted — descriptor flags them via `params.has_downmix=True`.)

**Failure modes caught:** today's #5 (silent-downmix from channel-count mismatch), session edits to `audio.channels=N` lines that don't match the live capture, profile changes (`pro-audio` vs default ALSA profile shifting channel count without conf update).

**Integration with SSOT:** This is the live runtime-side of `FORMAT_COMPATIBILITY` and `CHANNEL_COUNT_TOPOLOGY_WIDE` invariants from the SSOT spec §2.4. When the daemon ships, it will refuse pre-apply on these violations; M8 is the runtime backstop for any drift the daemon doesn't catch (e.g. external writers).

## §3.10 Monitor 9 — End-to-end latency (M9)

**Purpose:** L-12 capture → OBS round-trip time. Drift in latency is an early indicator of buffer-size changes, scheduling regression, or filter-chain reordering.

**Probe mechanism:**
- Inject a unique 200ms wide-band noise burst at `hapax-livestream-tap` input (using `module-pipe-source`).
- Capture from `hapax-obs-broadcast-remap.monitor`.
- Cross-correlate the injected signal against the captured signal; the lag at peak correlation IS the e2e latency.

**Frequency:** 5min probe interval (latency drift is slow; high-cadence probing risks contention with operator audio).

**Prometheus metrics:**
- `hapax_audio_health_latency_e2e_ms` — gauge, current measurement.
- `hapax_audio_health_latency_e2e_baseline_ms` — gauge, 7-day rolling baseline.
- `hapax_audio_health_latency_e2e_drift_ms` — gauge, current minus baseline.

**Thresholds:** Drift > 30ms from baseline → ntfy. Absolute > 100ms → ntfy regardless of drift.

**Failure modes caught:** buffer-size flip (PipeWire `default.clock.quantum` change), filter-chain reordering, USB controller saturation widening the buffer chain.

**Caveats:** noise burst is 200ms; injection happens during a 1s window during which broadcast quality is briefly degraded (low-amplitude noise mixed in at -50 dBFS). This is operator-visible at high listening volumes. **Operator can disable** via `HAPAX_AUDIO_HEALTH_LATENCY_E2E_ENABLED=0` in `~/.config/hapax/audio-health.env`.

## §3.11 Monitor 10 — Service correlation (M10)

**Purpose:** Correlate audio-touching service restart events with audio pipeline state changes. If `hapax-daimonion` restarts and audio goes silent within 5s, that's the cause.

**Probe mechanism:**
- Read systemd journal for service restart events for the audio-touching set: `hapax-daimonion`, `studio-compositor`, `hapax-broadcast-orchestrator`, `hapax-audio-router`, `hapax-audio-ducker`, `hapax-content-resolver`, `pipewire`, `wireplumber`, `pipewire-pulse`.
- Read the H1 daemon's `signal-flow.json` snapshot for state-change timestamps.
- Cross-reference: any state change within 30s of a restart event gets the restart event attached as `correlated_restart`.

**Frequency:** 30s probe interval.

**Prometheus metrics:**
- `hapax_audio_health_service_restart_total{service}` — counter.
- `hapax_audio_health_service_restart_correlated_with_state_change_total{service,state}` — counter (the operator's main lookup: "of all daimonion restarts, how many were followed by audio degradation?").
- `hapax_audio_health_service_restart_seconds_since_last{service}` — gauge.

**Thresholds:** Restart-correlated state-change rate >0.3 per restart → ntfy `<service> restarts cause audio state changes`. (Indicative; operator decides whether the restart is the cause or just temporally adjacent.)

**Failure modes caught:** restart cascade (today's #10), unstable service hotloop, dependency-ordering bugs that surface as audio glitches.

## §3.12 Monitor 11 — L-12 USB capture continuity (M11)

**Purpose:** L-12 USB audio interface is the operator's primary capture device. Disconnects, sample-rate drift, and alsa xrun storms must be visible.

**Probe mechanism:**
- `pactl list cards short | grep usb-ZOOM_Corporation_L-12` — DEVICE PRESENT / ABSENT.
- `cat /proc/asound/Live/pcm0c/sub0/hw_params` — current configured sample rate + period size.
- `dmesg --since "1 hour ago" | grep -i 'xrun\|underrun'` — alsa xrun events.
- Maintain per-probe delta on xrun count.

**Frequency:** 30s probe interval.

**Prometheus metrics:**
- `hapax_audio_health_l12_usb_present` — gauge, 0 / 1.
- `hapax_audio_health_l12_usb_sample_rate_hz` — gauge.
- `hapax_audio_health_l12_usb_xruns_total` — counter (alsa-level).
- `hapax_audio_health_l12_usb_xrun_rate_per_min` — gauge (delta normalized).

**Thresholds:**
- DEVICE ABSENT for >30s → P0 ntfy (no broadcast capture possible).
- Sample rate drift from 48000 Hz → ntfy (downstream chains assume 48 kHz).
- xrun rate > 5 per minute → ntfy.

**Failure modes caught:** USB bus-kick (today's `device descriptor read/64, error -71` at the xHCI controller), L-12 power flicker, sample-rate auto-negotiation regressions (Linux ALSA sometimes flips to 44.1 kHz on profile change).

**Co-existence:** This monitor does NOT trigger any USB recovery. The existing `xhci-death-watchdog` + `usb-bandwidth-preflight` units own recovery; M11 is purely observability.

---

# §4. Critical: don't duplicate H1

H1 (`agents/audio_signal_assertion/`) is the FIRST monitor in the suite (Monitor 1
in §3.2). The package extraction in Monitor 0 (§3.1) **refactors** H1 into the
shared package; it does NOT create a second classifier.

**Refactor invariants:**
- Public import path stays: `from agents.audio_signal_assertion import classify, ProbeMeasurement` continues to work.
- H1's daemon (`agents/audio_signal_assertion/daemon.py`), CLI (`__main__.py`), and systemd unit (`hapax-audio-signal-assertion.service`) keep their current names.
- H1's textfile metric (`hapax_audio_signal_health.prom`) keeps its current name. (Renaming to `hapax_audio_health_signal_class.prom` happens in a future minor version once Grafana queries are migrated.)
- H1's `/dev/shm/hapax-audio/signal-flow.json` snapshot keeps its current location. (Symlink to `/dev/shm/hapax-audio-health/signal-class.json` lands later.)
- H1's runbook (`docs/runbooks/audio-signal-assertion.md`) stays; the new suite runbook (`docs/runbooks/audio-pipeline-health.md`) is the operator-facing index that LINKS to H1's runbook for the signal-class section.

**Why the rename is deferred:** H1 already shipped (PR #2423). The textfile name + snapshot path appear in the operator's existing Grafana dashboards, ntfy topic names, and runbook anchors. A rename now would require a coordinated Grafana / ntfy / runbook migration. The package extraction is structural-only; rename happens after the suite is operator-validated and the rename can be done in one PR with all consumers updated.

---

# §5. Operator-tunable knobs (env vars)

Every monitor reads `HAPAX_AUDIO_HEALTH_<MONITOR>_*` env vars. Defaults match
the thresholds in §3. Common patterns:

```sh
# ~/.config/hapax/audio-health.env

# Globally enable / disable each monitor
HAPAX_AUDIO_HEALTH_SIGNAL_CLASS_ENABLED=1       # M1 (H1 — already env-controlled)
HAPAX_AUDIO_HEALTH_LUFS_S_ENABLED=1             # M2
HAPAX_AUDIO_HEALTH_CREST_FLATNESS_ENABLED=1     # M3
HAPAX_AUDIO_HEALTH_INTER_STAGE_CORR_ENABLED=1   # M4
HAPAX_AUDIO_HEALTH_PIPEWIRE_XRUN_ENABLED=1      # M5
HAPAX_AUDIO_HEALTH_TOPOLOGY_DRIFT_ENABLED=1     # M6
HAPAX_AUDIO_HEALTH_WATERMARK_ENABLED=0          # M7 — DISABLED by default; opt-in (audible during injection)
HAPAX_AUDIO_HEALTH_CHANNEL_POSITION_ENABLED=1   # M8
HAPAX_AUDIO_HEALTH_LATENCY_E2E_ENABLED=0        # M9 — DISABLED by default; opt-in (audible during noise burst)
HAPAX_AUDIO_HEALTH_SERVICE_CORRELATION_ENABLED=1 # M10
HAPAX_AUDIO_HEALTH_L12_USB_ENABLED=1            # M11

# Threshold overrides (per-monitor sections in §3 list the canonical knob names)
HAPAX_AUDIO_HEALTH_LUFS_S_BAND_OBS_LOW=-22
HAPAX_AUDIO_HEALTH_LUFS_S_BAND_OBS_HIGH=-18
HAPAX_AUDIO_HEALTH_INTER_STAGE_CORR_THRESHOLD=0.7
# ... etc
```

The operator-audible monitors (M7, M9) are off by default. Operator opts in
once they decide the suite is stable.

---

# §6. Prometheus + Grafana + waybar wiring

## 6.1 Prometheus textfile collector

Every monitor writes to `/var/lib/node_exporter/textfile_collector/hapax_audio_health_<dim>.prom`.
node_exporter scrapes the directory and emits all metrics under its own job.
The convention (`hapax_audio_health_*` prefix) keeps the metric namespace flat
and queryable by `{__name__=~"hapax_audio_health_.+"}`.

## 6.2 Grafana dashboard

`grafana/dashboards/hapax-audio-pipeline-health.json` lands as part of Monitor 0
(§3.1 — skeleton with one row per monitor). Each subsequent monitor cc-task
fills its own row's panels. Layout matches the §0 dashboard sketch.

## 6.3 waybar widget

`waybar` config gets one new module: `custom/audio-health`. Module reads
`/dev/shm/hapax-audio-health/<each>.json` files, computes worst per-monitor
status (green / yellow / red), shows aggregate icon + click-to-Grafana link.
Module ships in Monitor 10's cc-task (last to ship — depends on data from all others).

## 6.4 ntfy topic per monitor

Each monitor uses its own ntfy topic (`audio-health-<dim>-breach`) so the
operator can mute individual monitors during incidents without losing
visibility into others. Default ntfy priorities:

| Priority | Used for |
|---|---|
| `high` | OBS-bound stage breach (M1, M2, M3, M4); constitutional watermark violation (M7); L-12 disconnect (M11) |
| `default` | Upstream-stage breach; topology drift; service-correlation observation; latency drift |
| `low` | Recovery events (rarely enabled — operator preference is silent recovery) |

---

# §7. Implementation gating + sequencing

The spec is docs-only. Implementation cannot fire until the parallel deployment
audit (agent ae5440907f1278971) returns CLEAN — that's the operator's gate.

After audit returns CLEAN:

1. **Day 0:** Operator confirms gate. Monitor 0 cc-task claimed by alpha (or peer). Package extraction + meta-monitor + H1-deployment-fix ship in one PR. **Critical:** H1's systemd unit MUST be installed in the user systemd directory and verified RUNNING via `Type=notify` `READY=1` ack from the daemon. If the protocol mismatch the deployment audit found is not closed in this step, no further monitor work happens.
2. **Day 1-3:** Three monitor-group cc-tasks run in parallel — different files, no overlap:
   - `audio-health-classifier-suite-extend-h1` (M1+M2+M3)
   - `audio-health-topology-and-channel-monitors` (M6+M8)
   - `audio-health-pipewire-stage-correlation` (M4+M5+M11)
3. **Day 3-5:** Constitutional + latency monitor (M7+M9). Operator opt-in.
4. **Day 5-6:** Service-correlation + Grafana + waybar (M10).

Total: ~7 days from gate-cleared to suite-up. WSJF prioritisation in §2 ensures
gate task ships first.

---

# §8. Open questions / followups

1. **M2 LUFS-S vs legacy LUFS-I:** Should the legacy `hapax-broadcast-audio-health` 30s LUFS-I producer be DEPRECATED in favour of M2 + a periodic LUFS-I integration, or kept indefinitely as the safety-envelope SSOT? Filed as a followup; not blocking suite ship.
2. **M7 watermark frequency rotation:** 19.5 kHz is one frequency. Should we rotate through 18 / 19 / 20 kHz to defeat a hypothetical leak that's frequency-selective? Adds complexity; deferred until M7 is operator-accepted.
3. **M10 cross-correlation window:** The 30s window for restart-vs-state-change correlation is conservative. Operator may want to tune it after observing real data.
4. **Suite shutdown order:** When the operator does `systemctl --user stop hapax-audio-health.target`, monitors should stop in reverse-dependency order (meta-monitor last, M0-package-fixup last). The target unit's `BindsTo=` graph encodes this — to be specified in Monitor 0's cc-task.
5. **Migration path for legacy `audio` health-check group:** `agents/health_monitor/checks/audio.py` today only checks ducker liveness. Should that check group be renamed to `audio-pipeline-health` and absorb the suite's snapshot files? Filed as followup; not blocking.

---

# §9. Closure

This spec defines a 6-cc-task implementation arc for an audio pipeline health
monitor suite. The suite's load-bearing properties:

- **Independent monitors** — each tracks one dimension, fails independently.
- **Shared probe primitives** — one `agents/audio_health/` package; refactored from H1.
- **One textfile, one ntfy topic, one runbook anchor per monitor** — ops grep on `hapax-audio-health-` to list everything.
- **Meta-monitor for self-observability** — the operator sees if the suite itself is healthy.
- **Operator-tunable** — every threshold is env-overridable; M7 + M9 are off-by-default.
- **Implementation gated on the deployment audit** — no daemons land until parallel agent ae5440907f1278971 returns CLEAN.

The dashboard sketch in §0 is the operator-facing artefact. The 6 cc-tasks in §2
are the implementation surface. The 11 dimensions in §3 are the failure-mode
coverage.

Implementation begins after the audit gate clears. This spec ships docs-only.
