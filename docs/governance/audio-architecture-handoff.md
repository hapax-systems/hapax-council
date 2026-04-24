# Audio Architecture — handoff for future Claude sessions

**Status:** Phase 1 in flight (2026-04-23). Read this BEFORE touching any audio config.

**Why this exists:** The operator does not want to "mess with faders" or have Claude "adjust levels in software" again. Every numeric audio constant — LUFS targets, dBTP ceilings, sidechain depths, attack/release times, headroom budgets — has exactly one source of truth. Hand-tuning a PipeWire `.conf` outside that source is a regression.

## Single sources of truth

| What | Where | Editable by |
|---|---|---|
| Loudness / dynamics / timing constants | `shared/audio_loudness.py` | yes — change here, regenerate confs |
| Per-source routing policy (Phase 6+) | `config/audio-routing.yaml` | operator + Claude (via `hapax-audio-route` CLI) |
| Generated PipeWire confs (Phase 6+) | `config/pipewire/generated/` | NO — generated from above |
| Phase 1-5 PipeWire confs | `config/pipewire/hapax-*.conf` | only via the spec/plan PRs |

## Spec + plan + research

- Spec: `docs/superpowers/specs/2026-04-23-livestream-audio-unified-architecture-design.md`
- Plan: `docs/superpowers/plans/2026-04-23-livestream-audio-unified-architecture-plan.md`
- Research: `docs/research/2026-04-23-livestream-audio-unified-architecture.md`

## Hard rules

1. **Never hand-tune a `sc4m` threshold, a `hard_limiter` ceiling, a `fast_lookahead_limiter` Limit, or a sidechain depth in any `.conf` file.** Change `shared/audio_loudness.py` and (Phase 6+) regenerate via `scripts/generate-pipewire-audio-confs.py`. During Phase 1-5, the `.conf` files are hand-mirrored to the constants — comments inside each conf cite which constant it tracks.
2. **OBS audio source MUST bind to `hapax-broadcast-normalized`** (or its remap `hapax-obs-broadcast-remap`). Never `hapax-livestream:monitor` — that bypasses the master safety-net limiter. Verify post any restart with `pw-link -l | grep -A1 OBS`. Phase 2 introduces `hapax-obs-ingest` as a string-stable replacement that survives PipeWire restarts.
3. **L-12 mixer faders sit at unity and stay at unity.** The CH11/12 input switch is `LINE` (not `MIC`); trim is at 12 o'clock. Set once during Phase 1, never touched again.
4. **No new ducker implementations.** Phase 4 ships the canonical ducking matrix (sidechain LV2 comps on the master bus); everything else (the `audio_ducking.py` 4-state FSM, the `vad_state_publisher`, the various `*-ducked` sinks) gets retired in Phase 5.
5. **Adding a new audio source = 1 file change** (`config/audio-routing.yaml`, Phase 6+). It MUST NOT require touching upstream stages, and MUST NOT introduce a bespoke loudnorm chain.

## Acceptance verification

- Master loudness check: `scripts/audio-measure.sh [seconds] [node]`
  - Default 30 s on `hapax-broadcast-normalized.monitor`.
  - Phase 1 acceptance: integrated LUFS in [-16, -12], peak TP ≤ -0.5 dBTP.
- OBS-binding check: `pw-link -l | grep -A1 OBS` should show `hapax-broadcast-normalized` (or `hapax-obs-broadcast-remap`).
- L-12 input check: Evil Pet input meter green only on representative loud passage; no clip LED.

## When in doubt

Read the research doc (`docs/research/2026-04-23-livestream-audio-unified-architecture.md`) for the full current-state inventory + pain-point catalogue + best-practice citations. It's 945 lines and exhaustive.
