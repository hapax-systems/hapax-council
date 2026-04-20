# Mode D / Voice-Tier Granular Engine Mutex Design

**Date:** 2026-04-20
**Status:** Design
**Depends on:**
- `docs/research/2026-04-20-vinyl-broadcast-mode-d-granular-instrument.md` (Mode D scene definition)
- `docs/research/2026-04-20-voice-transformation-tier-spectrum.md` (parallel; voice tiers 0–6)
- `docs/research/2026-04-20-audio-normalization-ducking-strategy.md` §4.1 Tier A HARD MUTEX
- `agents/hapax_daimonion/vinyl_chain.py` (`VinylChainCapability`, `MODE_D_SCENE`)
- `agents/hapax_daimonion/vocal_chain.py` (`VocalChainCapability`, 9-dim semantic surface)
- `scripts/hapax-vinyl-mode` (operator CLI, SHM flag writer)

---

## §1. Concrete conflict

Evil Pet contains a single granular engine addressable over one MIDI channel
(EVIL_PET_CH = 0). Mode D (vinyl anti-DMCA) and the proposed voice tiers 5–6
(granular wash, obliterated) both configure this engine. They cannot coexist
for two independent reasons: a **signal-path reason** (audio) and a
**state-space reason** (MIDI).

**Signal-path conflict.** Mode D wiring (per `scripts/hapax-vinyl-mode` §Hardware)
routes L6 channel 4 (vinyl) → AUX 1 → Evil Pet L-in. Voice tiers 5–6 assume
that same Evil Pet L-in carries Hapax TTS (L6 ch 5). If both channels push
signal to AUX 1 simultaneously, the granular engine reads a sum of two
uncorrelated sources. Short grains (≤30 ms, Mode D's defeat region per
Smitelli 2020) randomly alternate between vinyl transients and TTS
formants. Result: intelligibility collapses (formant tracking broken by
vinyl spectral energy) AND Content-ID defeat weakens (TTS smoothness
partially stabilises the spectral-peak constellation the granular scatter
is supposed to break). Both capabilities degrade; neither operates in its
designed regime.

**State-space conflict.** Mode D writes `CC 11 = 120` (grains volume ~94 %),
`CC 40 = 127` (mix fully wet), `CC 94 = 60` (shimmer on), `CC 84 = 40`
(bit-crush saturator), `CC 11` inversion target specifically (vocal chain
baseline keeps grains at 0). Voice tiers 0–4 require `CC 11 = 0`,
`CC 40 ≤ 70`, `CC 94 = 0`, `CC 84 = 10–20` (distortion region). Voice
tiers 5–6 would invert these toward Mode D territory but with different
values tuned for TTS (shorter grain windows for intelligibility
preservation, different reverb, no shimmer for speech). Two writers
competing on the same CC produce last-write-wins thrash; the engine
state is whatever the most recent message specified, with no logical
relationship to what either capability "thinks" is active.

Conclusion: this is not a performance optimisation. It is a correctness
invariant. At most one consumer owns the Evil Pet granular state at a
time, and the signal reaching L-in must match that consumer.

---

## §2. Authoritative state

Single source of truth: `/dev/shm/hapax-compositor/evil-pet-state.json`.

```json
{
  "mode": "voice_tier_N" | "mode_d" | "bypass",
  "tier": 0,
  "active_since": 1713561234.567,
  "writer": "hapax-vinyl-mode" | "vocal_chain" | "director",
  "programme_opt_in": true,
  "heartbeat": 1713561240.123
}
```

Fields:

- `mode` — one of `bypass`, `voice_tier_0` … `voice_tier_6`, `mode_d`.
  `bypass` = grains off, voice-safe base, no active transformation.
- `tier` — numeric (0–6) when `mode == voice_tier_N`; `null` otherwise.
  Redundant with `mode` for ergonomic reads.
- `active_since` — Unix seconds when this mode was entered. Used for
  debounce and handoff-gate timing.
- `writer` — which subsystem wrote the flag. Helps telemetry attribute
  transitions and catches writer contention bugs.
- `programme_opt_in` — snapshot of the governance decision at write
  time. If the active Programme's `monetization_opt_ins` drops
  `mode_d_granular_wash`, any reader sees the stale-permission flag
  and can trigger revert without a secondary governance round-trip.
- `heartbeat` — refreshed every 5 s by the owning writer. Readers older
  than 15 s treat the file as stale and assume `bypass` (fail-safe).

Replaces the existing `/dev/shm/hapax-compositor/mode-d-active` flag
(binary exists/absent). The richer JSON subsumes it; migration handled
by §10 Phase 2. During migration, writers to the JSON file ALSO create
the legacy flag path when `mode == mode_d` for backward compatibility
with `VocalChainCapability` consumers that have not yet switched.

Location rationale: `/dev/shm/hapax-compositor/` is already the
convention for compositor-visible flags (see `scripts/hapax-vinyl-mode`
line 46). Sibling of `mode-d-active`, shares directory ownership and
tmpfs persistence semantics.

---

## §3. Arbitration

Three priority classes, descending:

1. **Operator explicit** — `hapax-vinyl-mode on|off` or an explicit
   voice-tier selection through the operator CLI. Overrides everything
   else. Writer tag `operator`.

2. **Programme opt-in (Mode D)** — an active Programme whose
   `monetization_opt_ins` includes `mode_d_granular_wash` can request
   Mode D via the `VinylChainCapability` affordance. Wins over any
   voice-tier recruitment. Writer tag `programme`.

3. **Director recruitment (voice tiers)** — salience-driven voice-tier
   selection via the `AffordancePipeline`. Lowest authority. Writer
   tag `director`.

Tie-breaking within the same class: **last-explicit-wins** with a debounce
window (§8). Cross-class: higher class always wins; a recruited voice
tier attempting activation while Mode D is active is dropped and the
attempt is logged with `blocked_by=mode_d` for telemetry.

The Programme opt-in gate lives upstream at capability recruitment
(`MonetizationRiskGate`) — consistent with the existing architecture
noted in `vinyl_chain.py` docstring §Governance. The arbitration layer
here does not second-guess the gate; it only prevents simultaneous
engagement when Mode D was recruited AND a voice tier was also
recruited in the same tick (a race the pipeline does not inherently
prevent because voice and vinyl are separate affordance domains).

Rule of thumb: **vinyl beats voice for the engine**, because Mode D is
the narrow reason the engine is engaged at all on the broadcast path.
Voice tiers 5–6 are the exception that must yield when vinyl wants
the engine.

---

## §4. Handoff protocol

Transitions between Mode D and voice tiers must re-write the engine
state in an order that avoids audible discontinuities and CC-race
intermediate states.

**Mode D → voice tier N (N ∈ 0..4, bypass/mild):**

1. `CC 94 = 0` (shimmer off) — must go first; shimmer tails linger.
2. `CC 84 = 10` (saturator type → distortion region, voice-safe).
3. `CC 40 = 64` (mix → 50 %; wet bleed ends).
4. `CC 91 = value_for_tier` (reverb amount, voice-tier target).
5. `CC 11 = 0` (grains volume off) — **last**, because grains-on while
   other CCs are being re-targeted keeps the audible mix continuous;
   dropping grains last produces a clean granular-to-dry fade rather
   than a dry-then-silence gap.
6. After all 5 CCs sent, voice-tier N writes its own dimension CCs
   through `VocalChainCapability._send_dimension_cc`.

**Voice tier N → Mode D:**

1. `CC 80 = 64` (filter type → bandpass) — must go first; bandpass
   response shapes what the granular engine reads. Done before
   engaging grains so the spectral-gating side-effects are in place.
2. `CC 70 = 76` (filter freq, Mode D mid-spectrum centre).
3. `CC 91 = 70` (reverb amount, Mode D deep wash).
4. `CC 93 = 80` (reverb tail, long).
5. `CC 94 = 60` (shimmer on).
6. `CC 40 = 127` (mix fully wet; kills dry signal).
7. `CC 84 = 40` (saturator → bit-crush region).
8. `CC 39 = 50` (saturator amount).
9. `CC 11 = 120` (grains volume → 94 %) — **last**; engine fully
   engages now that everything upstream is Mode-D-shaped.

**Voice tier N → voice tier M (N, M ∈ 0..6):** handled inside
`VocalChainCapability`; no arbitration layer involvement. Voice tiers 5–6
engaging the granular engine for TTS require the same CC 11 = 120
scene but with different filter + reverb settings tuned for speech;
they MUST first acquire the engine via §3 arbitration and write the
state flag to `voice_tier_5` (or `voice_tier_6`) before writing any CCs.

**Crossfade window.** Each transition takes ~200 ms: 14 CC writes at
~14 ms spacing (sleep 0.02 s per write per existing `hapax-vinyl-mode`
convention, halved after smoke-test confirms no MIDI buffer overrun).
The SHM flag is updated **atomically before** the CC sequence starts
(writers know their intent) and **heartbeat-updated** at the end
(writers confirm the state is settled). Readers seeing a flag in its
first 300 ms treat the engine as "transitioning" and hold their own
state changes for one tick. This prevents a third party racing in
mid-crossfade.

Hardware handoff (operator, on L6): the L6 procedure already documented
in `scripts/hapax-vinyl-mode` covers ch 4 / ch 5 AUX 1 sends. The
mutex layer presumes the operator performs this step; software CC
writes do not substitute for physical routing. If the operator fails
to drop the opposite-source AUX 1 send, the engine gets summed input
(§1 signal conflict); the mutex layer cannot detect this condition and
relies on telemetry (compressor pumping, unusual RMS correlation
between vinyl and TTS sources) to surface it.

---

## §5. L6 hardware — scope note

The L6 OG has two AUX sends (AUX 1, AUX 2). One hypothetical architecture:
AUX 1 = voice path, AUX 2 = vinyl path, two Evil Pets, simultaneous
voice-tier 5–6 AND Mode D.

**Out of scope.** The operator owns one Evil Pet. Adding a second
unit doubles the MIDI mapping surface, calibration load, and
MonetizationRiskGate state model. The present design assumes a single
engine and single AUX bus carrying whichever source currently owns it.
If the rig expands to two Evil Pets in the future, the flag file
schema generalises cleanly (`evil-pet-state.0.json`,
`evil-pet-state.1.json`, owning AUX bus per file), but the mutex
itself remains per-engine.

The operator's current wiring choice (AUX 1 for both, operator-mediated
fader discipline) matches this design. The operator MAY choose to use
AUX 2 for vinyl while leaving voice on AUX 1, which isolates signal
paths physically but still has one Evil Pet — so the mutex still
applies at the MIDI layer even though the audio-cross-modulation
failure mode from §1 disappears.

---

## §6. SHM flag design

Writer semantics:

- Writes go through a helper `shared/evil_pet_state.py::write_state()`.
  Implementation: serialise dict → JSON → write to
  `evil-pet-state.json.tmp` → `os.rename()` to
  `evil-pet-state.json`. `rename()` is atomic on tmpfs; readers never
  observe a partially-written file.
- Only one flag variant per mode. The writer emits EXACTLY the intended
  mode; there is no "both present" state. Voice tier 5 engaging the
  granular engine for speech writes `mode = voice_tier_5`, never
  `mode_d` — the mode name denotes *intent*, not merely *CC footprint*.
- Heartbeat: the owning writer schedules a 5 s timer that re-writes
  the file (preserving `active_since`, updating `heartbeat`). If the
  owning process dies, heartbeat stales after 15 s; the next reader
  infers `bypass` and the next writer can claim the engine without
  contention.
- Legacy compatibility: while `mode == mode_d`, the writer ALSO
  creates the path-level legacy flag
  `/dev/shm/hapax-compositor/mode-d-active` (current convention).
  On `mode_d` exit, both files are removed atomically (delete legacy
  flag first, then update JSON to `bypass`).

Reader semantics:

- Helper `shared/evil_pet_state.py::read_state()` parses the JSON file,
  returns a dataclass. Missing file, parse error, or
  `now - heartbeat > 15` all return a synthetic `bypass` state.
- Callers never check `mode_d_active` as a boolean directly; they
  call `read_state()` and dispatch on `state.mode`. The legacy
  `FLAG.exists()` pattern (as in `hapax-vinyl-mode status`) is
  preserved during migration and retired in Phase 4.

Writer contention: a naive implementation could double-write if two
callers race to claim the engine. The arbitration layer (§3) runs
*before* the CC sequence and the file write; callers must acquire
the engine through a higher-level function
`acquire_evil_pet_engine(target_mode, writer, priority)` which
reads current state, applies §3 rules, and either writes the flag
and returns a handle or returns a refusal. The handle is released
on `deactivate` or on heartbeat failure. This is per-process logical
locking; cross-process race is rare (only one capability pipeline
per daimonion instance) and bounded by the 15 s heartbeat staleness.

---

## §7. Observability

Log line format (single `logger.info` per transition):

```
evil-pet-state: voice_tier_2 → mode_d (writer=operator, reason=hapax-vinyl-mode-on)
```

Prometheus metrics (registered lazily per `_VocalChainMetrics` pattern
in `vocal_chain.py`):

- `hapax_evil_pet_mode_transitions_total{from, to, writer}` — counter,
  increments on every transition.
- `hapax_evil_pet_mode_active{mode}` — gauge, `1` for the currently
  active mode and `0` for all others. Simplifies "what mode am I in
  right now" Grafana queries.
- `hapax_evil_pet_mode_blocked_total{requested, active, writer}` —
  counter, increments when arbitration blocks a transition (e.g.,
  director recruitment requesting `voice_tier_5` while `mode_d` is
  active).
- `hapax_evil_pet_mode_heartbeat_age_seconds` — gauge, seconds since
  last heartbeat. Alerting target: > 20 s should page (writer crashed
  mid-mode).
- `hapax_evil_pet_handoff_duration_seconds` — histogram of handoff
  completion times. Validates the 200 ms budget and catches MIDI
  buffer back-pressure regressions.

Langfuse event: `evil_pet_mode_transition` with metadata `from`, `to`,
`writer`, `programme_opt_in`, `blocked_by`. Allows retrospective
session analysis ("did vinyl ever interrupt TTS? for how long?
caused by what impingement?").

---

## §8. Failure modes

**MIDI port unavailable.** `mido.open_output` raises or returns nothing.
CC writes fail silently per existing `vinyl_chain.activate_mode_d` pattern
(logs at warning level, no-op). The flag file write PROCEEDS anyway
because downstream consumers (CPAL TTS defer, compositor UI) rely on
the flag independently of whether the CCs landed. An observability
check then flags the discrepancy: flag says `mode_d` but no CC emit
counter incremented → alert `hapax_evil_pet_cc_write_failed_total > 0`.

**Operator rapid-toggles.** `hapax-vinyl-mode on; hapax-vinyl-mode off;
hapax-vinyl-mode on;` within 2 s. Without protection, each invocation
triggers a full CC sequence, saturating the Evil Pet with duplicate
writes. Debounce: the helper `acquire_evil_pet_engine` rejects any
transition where `active_since` is within `DEBOUNCE_WINDOW = 0.5 s`
of `now`. The operator sees "debounced, current mode retains" and
the CLI exits 0 without re-writing. CLI exits non-zero (code 2) only
when the *requested* mode differs from the current mode AND the
window has elapsed AND arbitration rejects — three conditions a
debounce alone cannot satisfy.

**Programme `monetization_opt_in` revoked mid-session.** The Programme
loader publishes changes to the active-Programme cache. A watcher
(`agents/monetization_risk_gate.py` or a companion) subscribes to
that cache and, on a transition where `mode_d_granular_wash` leaves
`monetization_opt_ins` while `state.mode == mode_d`, forces
`VinylChainCapability.deactivate_mode_d()` and writes `mode = bypass`.
This revert is **immediate** (no debounce), writer tag `governance`,
logged at warning level. The operator receives an `ntfy` notification:
"Mode D revoked mid-session by Programme; engine released". CCs
revert through the Mode D → bypass handoff sequence in §4.

**Stale heartbeat with CCs still in Mode-D state.** Writer crashed;
flag file shows stale `mode_d` but actual Evil Pet CCs are still
configured for granular wash. Readers see `bypass` (stale expiry
fallback). The NEXT writer claiming the engine through
`acquire_evil_pet_engine` triggers a safety-revert CC sequence
(deactivate Mode D scene) *before* writing its own target CCs, even
if its target mode also uses granular. This ensures a known-good
starting state regardless of what the crashed writer left behind.

**Double-engine request inside one tick.** The affordance pipeline
recruits Mode D and voice tier 5 in the same tick. Both try to
acquire. The arbitration lock serialises them; Programme opt-in wins,
director recruitment's voice-tier activation is dropped with
`blocked_by=programme_mode_d`. The dropped recruitment logs at
info level; the Thompson-sampling bandit records the failure (so
the director learns voice tier 5 is not a productive recruitment
target while a vinyl programme is active).

---

## §9. Test strategy

Unit tests (`tests/hapax_daimonion/test_evil_pet_mutex.py`):

- State-file round-trip: write, read, verify all fields including
  heartbeat.
- Atomic rename: write while reader is looping; reader never observes
  partial JSON.
- Heartbeat expiry: write state with `heartbeat = now - 20`; reader
  returns `bypass`.
- Arbitration: table-driven, one row per (current_mode, writer_class,
  requested_mode) → expected outcome (accept / block / debounce).
- Transition sequence order: `acquire → deactivate → CC sequence →
  write flag` ordering verified via mock MIDI + mock filesystem
  with strict call-order assertions.
- Debounce: consecutive acquire calls within 0.5 s return debounced;
  after 0.5 s the next call succeeds.

Integration tests (`tests/integration/test_vinyl_voice_mutex.py`):

- Start with `bypass`. Invoke `hapax-vinyl-mode on`. Assert flag file
  shows `mode_d`, CCs emitted in expected order, metrics counter
  incremented.
- Invoke `VocalChainCapability.activate_dimension("vocal_chain.coherence", …)`
  while Mode D is active. Assert the activation is blocked for
  granular-touching dimensions only (tiers 5–6); tiers 0–4 still write
  their CCs because they do not contest the granular engine.
  (This is subtle: `vocal_chain.coherence` writes `CC 40`, which IS
  contested. The test confirms the mutex gate applies per-CC, not
  per-dimension.)
- Revoke Programme opt-in mid-Mode-D. Assert forced revert within
  one tick; CCs return to voice-safe base; ntfy fired.
- Crash simulation: start Mode D, kill the writer process, wait 20 s,
  attempt voice-tier activation. Assert the safety-revert CC sequence
  fires before the new mode's CCs.

Hardware smoke test: `scripts/studio-mutex-smoke.sh` — triggers a
Mode D ↔ voice-tier 5 crossfade five times, captures Evil Pet audio
output via the monitor path, asserts no audible silence gap > 50 ms
and no double-granular artefacts at transition boundaries. Runs
nightly as part of studio health timer once hardware is available.

---

## §10. Implementation plan

**Phase 1 — State schema + helper (1 PR, direct to main from alpha).**
- Create `shared/evil_pet_state.py` with `EvilPetState` dataclass,
  `read_state()`, `write_state()`, `acquire_evil_pet_engine()`.
- Migrate `hapax-vinyl-mode on|off|status` to use the new helper; keep
  the legacy `mode-d-active` flag in sync during transition window.
- Unit tests for schema + arbitration.

**Phase 2 — VinylChainCapability + VocalChainCapability integration.**
- `VinylChainCapability.activate_mode_d` acquires the engine via
  `acquire_evil_pet_engine(target_mode="mode_d", writer="programme",
  priority=2)`; on acquisition failure, logs and no-ops.
- `VinylChainCapability.deactivate_mode_d` releases the engine and
  writes `bypass` state.
- `VocalChainCapability._send_dimension_cc` checks the engine state
  before writing any CC in the contested set (CC 11, 40, 84, 94).
  Uncontested CCs (filter freq, reverb for tier-0..4 voice) write
  unconditionally.
- Heartbeat thread (`threading.Timer`-based, 5 s cadence) for both
  capabilities while their mode is active.

**Phase 3 — Observability + governance watcher.**
- Prometheus metrics registered, Langfuse events wired.
- `agents/monetization_risk_gate.py` subscribes to active-Programme
  changes; invokes forced revert on opt-in revocation.
- Ntfy wire-up for governance-driven reverts.
- Grafana panel for `hapax_evil_pet_mode_active` + transitions rate.

**Phase 4 — Voice tier 5–6 integration + smoke test + legacy flag
retirement.**
- Voice-tier spectrum research (`2026-04-20-voice-transformation-
  tier-spectrum.md`) lands; its implementation of tiers 5–6 uses
  `acquire_evil_pet_engine` in `VocalChainCapability` when the target
  tier crosses the granular threshold.
- Hardware smoke-test script lands and runs green.
- Legacy `/dev/shm/hapax-compositor/mode-d-active` flag removed from
  all consumers; migration grace window ends.

Total: 4 PRs, estimated ~1 week of alpha-session work assuming the
voice-tier spectrum research lands within the window. Phases 1–3
can ship independently of the voice-tier spectrum; Phase 4 is gated
on it.

---

**Open questions for operator review:**

1. Should voice-tier 5–6 require its own `monetization_opt_ins` entry
   (`voice_tier_granular`) separately from Mode D's
   `mode_d_granular_wash`? Argument for: they are distinct broadcast
   risks (re-synthesised TTS vs re-synthesised copyrighted vinyl).
   Argument against: operator cognitive overhead, two flags for
   similar capabilities.

2. Debounce window of 500 ms — conservative. If operator reports
   flicker during rehearsal, lower to 200 ms; if accidental rapid
   toggles surface, raise to 1 s.

3. Heartbeat cadence of 5 s — chosen to match typical daimonion tick.
   Not load-bearing; can be 1 s if monitoring wants tighter
   crash-detection.

These belong in a follow-up calibration pass, not in the initial
implementation PRs.
