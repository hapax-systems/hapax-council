# Phase 6b Threshold Wiring — Status & Design

**Status:** Normative. The original "Phase 6b Parts 2-5 deferred"
framing in `~/.cache/hapax/relay/alpha-post-compaction-handoff-2026-04-25-evening.md:107`
is **superseded** by post-2026-04-25 reality (§1). The remaining work
is exclusively per-signal calibration of the 12 mood-claim signals
fronted by the three `Logos*Bridge` classes in `logos/api/app.py`. §3
splits that work into seven implementable cc-tasks with concrete
prerequisites.
**Scope:** the three mood-claim Bayesian engines wired in `logos/api/app.py`
— `MoodArousalEngine`, `MoodValenceEngine`, `MoodCoherenceEngine` —
and their twelve signal accessors (4 each).
**Driver task:** `phase-6b-threshold-wiring-design` (cc-task, WSJF 5.0).

---

## 1. What's already shipped (Part 1 — the original "trio")

The cc-task spec asked first to "identify the Part 1 trio that shipped
and the remaining Parts 2-5." The 2026-04-25 handoff's framing
predates three subsequent merges. Current ground truth as of
2026-05-01:

**Engines (Part 1.A):**

| PR | Phase | Module |
|----|-------|--------|
| #1368 | Phase 6b-i.A | `agents/hapax_daimonion/mood_arousal_engine.py` |
| #1371 | Phase 6b-ii.A | `agents/hapax_daimonion/mood_valence_engine.py` |
| #1374 | Phase 6b-iii.A | `agents/hapax_daimonion/mood_coherence_engine.py` |

**Lifespan wiring (Part 1.B):**

| PR | Phase | What |
|----|-------|------|
| #1392 | Phase 6b-i.B | `_mood_arousal_tick_loop` + `LogosStimmungBridge` in `logos/api/app.py` |
| #1399 | Phase 6b-ii.B | `_mood_valence_tick_loop` + `LogosMoodValenceBridge` |
| #1403 | Phase 6b-iii.B | `_mood_coherence_tick_loop` + `LogosMoodCoherenceBridge` |

**Status routes + TODO retirement:**

| PR | What |
|----|------|
| #1947 | Three engine status routes (`GET /api/engine/mood_{arousal,valence,coherence}`) + retired the "Phase 6b-X.B partial / Part 1 / follow-up PRs" language in the bridge classes and observation-builder docstrings. |

**Net result:** the three engines run on the asyncio event loop in
the lifespan, each ticks at its cadence, posteriors stay at their
Beta-prior values because every bridge accessor returns `None` ("skip
this signal for this tick" per `ClaimEngine.tick` semantics). The
posterior plumbing is fully live; the only thing missing is real
signal evidence flowing through the bridges.

So **the "Parts 2-5 deferred" framing is no longer accurate.** The
deferred work is now per-signal calibration of 12 individual signals,
not 4 monolithic "parts."

---

## 2. The 12 deferred signals + calibration semantics

Each of the three engines consumes exactly four signals. Each signal
has a calibration model (quantile, baseline, threshold, or volatility
window) and a polarity (bidirectional or positive-only). Until each
backend's reference is calibrated against production data, the
matching bridge accessor returns `None` and the engine skips that
signal for the tick.

### 2.1 MoodArousalEngine — `LogosStimmungBridge`

| # | Signal | Source backend | Calibration model | Polarity |
|---|--------|----------------|--------------------|----------|
| 1 | `ambient_audio_rms_high` | room mic via `agents/hapax_daimonion/backends/ambient_audio.py` | rolling-window quantile (e.g. >P75 of last 24h) | bidirectional |
| 2 | `contact_mic_onset_rate_high` | Cortado MKIII via `agents/hapax_daimonion/backends/contact_mic.py` | rolling-window quantile of onsets/s | positive-only |
| 3 | `midi_clock_bpm_high` | OXI One via `agents/hapax_daimonion/backends/midi_clock.py` | hard tempo cutoff (e.g. >120 BPM = high-arousal regime) | bidirectional |
| 4 | `hr_bpm_above_baseline` | Pixel Watch via `agents/hapax_daimonion/backends/health.py` | session baseline (e.g. resting-HR + 15 BPM) | bidirectional |

### 2.2 MoodValenceEngine — `LogosMoodValenceBridge`

| # | Signal | Source backend | Calibration model | Polarity |
|---|--------|----------------|--------------------|----------|
| 5 | `hrv_below_baseline` | Pixel Watch HRV → `health.py` | rolling-30d HRV baseline minus stress-meaningful delta | bidirectional |
| 6 | `skin_temp_drop` | Pixel Watch skin temp → `health.py` | rolling-baseline minus vasoconstriction-meaningful delta | positive-only |
| 7 | `sleep_debt_high` | Pixel Watch sleep → `health.py` | tolerance threshold (e.g. <6.5h avg over last 7 nights) | positive-only |
| 8 | `voice_pitch_elevated` | speech analyzer (`agents/hapax_daimonion/voice_*` or LLM-side STT pitch) | session-baseline pitch + stress-meaningful delta | positive-only |

### 2.3 MoodCoherenceEngine — `LogosMoodCoherenceBridge`

| #  | Signal | Source backend | Calibration model | Polarity |
|----|--------|----------------|--------------------|----------|
| 9  | `hrv_variability_high` | Pixel Watch HRV beat-to-beat CV → `health.py` | rolling-window CV threshold | bidirectional |
| 10 | `respiration_irregular` | Pixel Watch respiration → `health.py` | rolling-window respiration-rate variance threshold | positive-only |
| 11 | `movement_jitter_high` | Pixel Watch accelerometer → `health.py` | rolling-window accelerometer micro-movement variance | positive-only |
| 12 | `skin_temp_volatility_high` | Pixel Watch skin temp delta → `health.py` | rolling-window |Δskin_temp/Δt| volatility | positive-only |

**Polarity rule:** `positive-only` signals contribute `True` when
detected but `None` (skip-this-signal) when absent. Only structurally
reliable signals where absence is unambiguous use `bidirectional`
contribution. This mirrors the `PresenceEngine` design pin
(positive-only for unreliable sensors). See council CLAUDE.md
§Bayesian Presence Detection.

---

## 3. Implementation cc-tasks split (replaces "Parts 2-5")

The remaining work splits cleanly along **backend ownership** rather
than along the engine boundaries, because each backend has its own
quantile/baseline persistence model and most of the 8 health-derived
signals share the Pixel Watch ingest path. Filing seven tasks (one per
backend group) gives each task a single point of responsibility and
single set of acceptance criteria.

### 3.1 P6B-T1 — Ambient audio RMS quantile tracker
**Backend:** `agents/hapax_daimonion/backends/ambient_audio.py`
**Signal:** `ambient_audio_rms_high` (signal #1)
**Calibration:** rolling-window quantile (recommend 24h sliding window,
P75 cutoff). Persistence: in-memory ring buffer + on-disk snapshot
under `~/.cache/hapax/calibration/ambient-audio-rms-quantile.json`.
**Acceptance:** `LogosStimmungBridge.ambient_audio_rms_high()` returns
`bool` (not `None`) once the quantile has ≥1h of warm-up data;
`None` only during cold-start.
**Wsjf:** 5.0 (medium — signal already exists; this is calibration plumbing).

### 3.2 P6B-T2 — Contact mic onset-rate quantile tracker
**Backend:** `agents/hapax_daimonion/backends/contact_mic.py` (Cortado MKIII DSP layer)
**Signal:** `contact_mic_onset_rate_high` (signal #2)
**Calibration:** same rolling-window quantile pattern as P6B-T1.
**Acceptance:** `LogosStimmungBridge.contact_mic_onset_rate_high()`
returns `True` when onset rate exceeds P75 over the last 24h; positive-
only semantics retained (returns `None`, not `False`, when below).
**WSJF:** 4.5.

### 3.3 P6B-T3 — MIDI clock BPM cutoff
**Backend:** `agents/hapax_daimonion/backends/midi_clock.py` (OXI One MIDI clock)
**Signal:** `midi_clock_bpm_high` (signal #3)
**Calibration:** hard cutoff (no quantile needed — the operator's
performed tempo IS the signal; e.g. >120 BPM = high-arousal regime).
Cutoff value should be operator-tunable via `config/`.
**Acceptance:** bridge accessor returns `bool` based on the configured
threshold; clock-not-running returns `None`.
**WSJF:** 4.0 (small; threshold-only, no persistence).

### 3.4 P6B-T4 — Pixel Watch baseline tracker (HR + HRV + skin temp)
**Backend:** `agents/hapax_daimonion/backends/health.py`
**Signals:** `hr_bpm_above_baseline` (4), `hrv_below_baseline` (5),
`skin_temp_drop` (6).
**Calibration:** rolling-30d session-baseline per metric. Baseline =
median over 30d, "meaningful delta" = MAD (median absolute deviation)
× 2.0 above/below baseline.
**Persistence:** `~/.cache/hapax/calibration/pixel-watch-baseline.json`
(daily-rotated; 30 days retained).
**Acceptance:** all three bridge accessors return `bool` once baseline
has ≥7d of warm-up data.
**WSJF:** 6.0 (highest — three signals at once + baseline persistence
infrastructure that subsequent tasks reuse).

### 3.5 P6B-T5 — Pixel Watch sleep deficit
**Backend:** `agents/hapax_daimonion/backends/health.py`
**Signal:** `sleep_debt_high` (7)
**Calibration:** sleep-tolerance threshold (e.g. <6.5h average over
last 7 nights). Operator-tunable.
**Persistence:** reuses pixel-watch-baseline.json (P6B-T4).
**Acceptance:** `LogosMoodValenceBridge.sleep_debt_high()` returns
`True` when 7-night-average sleep is below the configured threshold;
positive-only.
**WSJF:** 4.5. **Depends on:** P6B-T4 (shared baseline plumbing).

### 3.6 P6B-T6 — Voice pitch baseline tracker
**Backend:** speech-side — likely under
`agents/hapax_daimonion/persona.py`'s STT path or a new
`agents/hapax_daimonion/backends/voice_pitch.py`.
**Signal:** `voice_pitch_elevated` (8)
**Calibration:** session-baseline pitch (median F0 over current
session) + stress-meaningful delta (e.g. +25 Hz). Reset on
session-boundary.
**Persistence:** in-memory only (session-scoped); no on-disk baseline.
**Acceptance:** `LogosMoodValenceBridge.voice_pitch_elevated()` returns
`True` when the most recent utterance's F0 exceeds session baseline +
delta; positive-only.
**WSJF:** 5.0. **Blocker:** depends on STT pitch extraction being
exposed at the persona / observation layer.

### 3.7 P6B-T7 — Pixel Watch volatility tracker
**Backend:** `agents/hapax_daimonion/backends/health.py`
**Signals:** `hrv_variability_high` (9), `respiration_irregular` (10),
`movement_jitter_high` (11), `skin_temp_volatility_high` (12).
**Calibration:** rolling-window variance/CV per signal (recommend
60-min window for sub-tick volatility; P75 cutoff per signal).
**Persistence:** reuses pixel-watch-baseline.json (P6B-T4).
**Acceptance:** all four bridge accessors return `bool` when window
has ≥30min of warm-up data; positive-only semantics for #10-12,
bidirectional for #9.
**WSJF:** 5.5. **Depends on:** P6B-T4.

---

## 4. Cross-task prerequisites

Two cross-cutting prerequisites the implementation tasks share:

### 4.1 Calibration persistence directory

`~/.cache/hapax/calibration/` does not exist as a convention yet. The
first task that lands (recommended: P6B-T4 since three signals depend
on it) should establish the directory + a small helper module
(`shared/calibration_store.py`) for atomic JSON read/write with
schema versioning. All subsequent tasks reuse this helper.

### 4.2 Warm-up + cold-start contract

Every quantile/baseline tracker has a cold-start window during which
no signal can fire (the rolling window doesn't have enough data). The
bridge accessor MUST return `None` during cold-start, not `False`,
because false-as-evidence would push the posterior toward the wrong
tier. This is the same `None`-means-skip semantics already documented
in `agents/hapax_daimonion/backends/mood_arousal_observation.py`. A
shared decorator or helper (e.g. `@warm_up_required(window_s=86400)`)
in `shared/calibration_store.py` would enforce this consistently.

---

## 5. What stays unchanged

- `agents/hapax_daimonion/mood_{arousal,valence,coherence}_engine.py`
  — engines are stable; calibration is upstream of them.
- `agents/hapax_daimonion/backends/mood_{arousal,valence,coherence}_observation.py`
  — observation builders consume the bridge accessors as `bool | None`;
  no changes needed.
- `logos/api/app.py` lifespan tick loops + `Logos*Bridge` class shape
  — bridge classes only need their accessor bodies replaced (currently
  `return None`) once each calibration backend is live.
- `shared/prior_provenance.yaml` — Beta priors stay as-is; calibration
  refines posteriors via evidence, not priors.
- `GET /api/engine/mood_{arousal,valence,coherence}` routes — these
  already serve real posteriors (defaulting to the prior under no
  evidence); no changes needed when calibration goes live.

---

## 6. Recording superseded threshold work

The original 2026-04-25 framing names "Phase 6b Parts 2-5 — per-signal
threshold wiring." That framing is **superseded** by the post-#1947
landscape:

- The "wiring" part was always Phase 6b-X.B (lifespan + bridge); those
  shipped #1392 / #1399 / #1403.
- The "thresholds" part is the calibration-of-12-signals work that
  this design doc reframes into seven backend-owned tasks (§3).
- No separately-numbered "Parts 2/3/4/5" exist in the codebase
  today — the engine-major-version letters (.A / .B / .C) are the
  authoritative subdivision, and .A + .B are merged for all three
  engines.

A future agent landing on the `~/.cache/hapax/relay/alpha-post-compaction-handoff-2026-04-25-evening.md`
handoff should read this status doc as the authoritative successor.
The handoff's line 107 framing remains historically accurate but no
longer reflects the codebase.

---

## 7. Closure criteria for this design task

- [x] Identified the Part 1 trio that shipped (§1: engines + lifespan
  wiring + status routes — six PRs total #1368, #1371, #1374, #1392,
  #1399, #1403, plus #1947 for routes/cleanup).
- [x] Defined backend quantile/baseline dependencies for all 12
  signals (§2.1–2.3).
- [x] Produced a design splitting implementation into seven cc-tasks
  with clear blockers and inter-task dependencies (§3 + §4).
- [x] Recorded the original "Parts 2-5 deferred" framing as
  superseded with evidence (§6).

The seven follow-up cc-tasks (P6B-T1 through P6B-T7) can be filed as
individual vault tasks once this design lands. WSJF estimates per
task are documented in §3 to seed the WSJF queue.
