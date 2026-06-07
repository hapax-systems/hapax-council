# SCREWM Modulation Matrix (SMM) — Control-Surface Design

**Status:** design (holistic-and-fundamental per adversarial review).
**Date:** 2026-06-07.
**Provenance:** holistic research workflow (14 agents) + adversarial critique. Canonical working
record: `~/.cache/hapax/relay/audits/2026-06-07-screwm-modulation-matrix-architecture.md`.
**Lineage:** scrim (2D parasocial scrim — compel/inform/disorient) → scroom (3D scrim room) →
screwm (spiral Tower of Babel) → screwm-in-DarkPlaces (parity-plus). A new iteration name is
TBD — the operator will choose it; the code keeps the `screwm-*` prefix meanwhile.

## 1. Thesis — SCREWM is a loop, not "a control surface for four domains"
SCREWM's purpose is maximal purchase over the DarkPlaces/QuakeC internals to bind **compositing,
audio, geometry, physics** — serving **automation AND perceptual-impingement-recruitment**. The
fundamental object is one bidirectional perceptual-expressive **circuit**:

    external → impingement → recruit → express (in the screwm AND in the world) → re-perceive → impingement …

The four domains are the engine **destinations** the AffordancePipeline expresses through and the
engine **states** it re-perceives from. The "one control surface" is the *realization* of that loop.
The external (studio, world) is made internal; the internal (system states, impingements) is made
external — and fed back in.

## 2. Architecture — five layers
1. **Substrate — one Signal, one blob.** A parameter = a typed function of (time, source-state),
   tagged Analog (continuous) / Digital (discrete) per the TidalCycles Pattern split; the leaf wraps
   the existing flat-float `SignalBus.snapshot()` (adopt the *principle*, not Haskell monads).
   Materialize as ONE versioned struct `/dev/shm/hapax-compositor/screwm-control.bin`, read once per
   frame by a new engine `R_HapaxControl_Update()` beside the verified trio
   `R_HapaxLiveTexture_Update`/`R_HapaxDriftField_Update`/`R_HapaxDriftCurrency_Update`.
2. **Binding — the Modulation Matrix (Source/Via/Target).** Generalize `SignalModulationBinding`
   (smoothing 0.85) + `AudioVisualModulationGovernor` (9 roles × 7 axes + anti-visualizer) into a
   patch-bay: SOURCE (any Signal) → **VIA = `AffordancePipeline.select()`** veto + Thompson cost-weight
   (+ consent / LUFS-panic / face-privacy) → TARGET (any domain param), OSC-addressed
   `/screwm/<domain>/<path>/<param>`. Evaluate as an ECS pass: snapshot Sources, evaluate, write
   Targets — **never read-modify-write within a tick** (structural feedback-runaway guard).
3. **Recruitment — domain-typed affordances through one `select()`.** `AffordancePipeline.select()`
   (`shared/affordance_pipeline.py:686`) is the sole intent→capability gate and the Via of every
   binding. Extend `OperationalProperties.domain` `{content,geometry}` → `+{audio,physics,both}`;
   `intent_family` prefix = the universal namespace (`compositing.*/audio.*/geometry.*/physics.*/drift.*`).
4. **External→internal** (~70% live) — impingement = precision-weighted prediction-error (active
   inference); `unified-reactivity.json` @60Hz + the DMN impingement bus + IR/biometric/voice.
5. **Internal→external→internal** (the missing closure leg) — engine **self-readback** (the engine
   becomes a *sensor*: camera dwell, per-zone drift energy, luma, collisions, `S_` RMS) →
   `screwm.self_perception` impingement per domain (template: `audio_self_perception/analyzer.py`).
   The "beautiful loop." Governance-gated; the expression vocabulary encodes affordance-topology
   position with traversal provenance, **never first-person interiority** (axiom ep-anthro-001).

## 3. Foundational primitives
`Signal` (typed fn of time,source) · **Control Surface Blob** (one /dev/shm struct, one engine
ingest) · **Modulation Slot** (Source/Via/Target, OSC-addressed, many-to-many) · **Domain-typed
Affordance** · **OSC namespace** (SSOT wire format + external authoring + `signal_topology` path-trace
across all four domains) · **Engine self-readback**.

## 4. Roadmap (sequenced by buildability; refined per critique)
- **P0 — complete the per-zone currency channel + attach loop-closure (no engine rebuild).** The Rust
  drain target (#3995) + engine sampler (#3996) exist; the daemon binary was stale (fixed by the
  #4007 auto-deploy pipeline). Remaining: emit currency `(R=family,G=intensity,B=phase,A=consent)`,
  flip `hapax_driftcurrency_enable=1`, register the port-owner, fix the `[0.42,0.92]`→`[0.2,1.0]`
  clamp. **Critique mandate:** prove the *loop* on this one channel end-to-end (a minimal self-readback
  + a **feedback-gain measurement** — loop stability is the thesis), not just outbound.
- **P1 — audio→geometry via currency** (audio's first geometric binding; no rebuild).
- **P2 — recruitment drives the currency** (close recruiter→engine; resolve the two-tree `domain`-schema
  bridge first; activate the inert `R_BlendView_N`).
- **P3 — unified blob + `R_HapaxControl_Update`** — **deferred** (the four channels work; collapsing is
  high-risk/low-margin; CRC-orphan trap is the top engine risk).
- **P4 — self-readback at scale** (full closure; rebalance the ~302/360 curiosity-dominated impingement
  bus toward re-perceiving its own expression).
- **P5 — physics greenfield** (QC-only: `MOVETYPE` flip + velocity/torque from the blob + `traceline`
  proprioception; partially promotable early).
- **P6 — engine audio mixer + retire the QC hot loop** (rebuild; **strictly fence** engine `S_` from the
  broadcast MPC/L-12 chain — PROTECTED INVARIANT).

## 5. Hardest unknowns to de-risk
CRC orphan trap (P3/P6 shader edits) · feedback runaway (ECS snapshot discipline + a P0 gain protocol) ·
deploy durability vs source-activation (merged≠live; #4007 addresses the daemon side) · the two-tree
recruitment bridge · GPU/runtime fragility · engine-`S_` vs the broadcast fence · ODE physics
availability (likely needs a rebuild+dep) · anthropomorphization at loop closure · the curiosity-bus
imbalance · Signal-type over-abstraction (adopt incrementally).

## 6. Reuse vs replace
REUSE: the DarkPlaces per-frame /dev/shm ingest pattern; `AffordancePipeline.select()` (do not add a
parallel ML mapper — Thompson/Hebbian learning lives there); the 27-scalar DriftState contract;
`graph_patch_consumer.py` (proves recruitment→compositing is already closed); `anti_visualizer.py`.
REPLACE: the synthetic sine `_pulse()` drift currency → recruited values; the ~70 `data/*.txt` QC
fopen scalars + ad-hoc cvars → the unified Signal/Blob (P3, deferred).
