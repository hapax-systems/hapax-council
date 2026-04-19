# HARDM as Communicative Anchor — Weighted Bias and Narrative Coupling

**Date:** 2026-04-18
**Scope:** task #160 — HARDM's role as Hapax's visual avatar, the
conditions that bias it into presence, and its coupling to voice and
narrative.
**Register:** scientific; neutral; no rhetorical framing.
**Related:** `docs/superpowers/specs/2026-04-18-hardm-dot-matrix-design.md`
(HARDM spec), `docs/superpowers/specs/2026-04-18-homage-framework-design.md`
(HOMAGE framework, voice register, choreographer), `config/hardm-map.yaml`
(signal binding), `scripts/hardm-publish-signals.py` (publisher).

---

## 1. Rationale: HARDM as a Face

HARDM (the Hapax Avatar Representational Dot-Matrix) is a 256×256 px
16×16 cell grid placed upper-right at x=1600, y=20 in the compositor
layout. Each of 16 rows is bound to one system signal; each of 16
columns in that row is a repeated stamp of the same signal state
(`agents/studio_compositor/hardm_source.py`).

HARDM is the single visual surface that external viewers reliably
associate with "Hapax." Other wards come and go — overhead PiPs, album
art, legibility strips — but HARDM is always the same shape, always in
the same corner, always colour-keyed to the active HOMAGE package.
Functionally it occupies the role a face occupies in human
conversation:

- A **known return site** — when viewers lose the thread, their gaze
  can go back to HARDM to re-orient.
- A **visible tell** — micro-state changes in the matrix (a row
  brightening, a column flickering to accent-red, a stance cell
  sliding from muted to magenta) carry information the narrative
  director can refer to.
- An **attentional anchor during voice** — when Hapax is speaking, a
  human interlocutor's gaze settles near the voice source; HARDM is
  the visual surrogate for that source.

The research question is therefore: under what conditions should
HARDM be biased toward presence (the allocator question), and under
what conditions should narrative actively reference HARDM cells (the
narrative question)? This document answers both and specifies the
integration contract across the compositor, director loop, and CPAL
voice chain.

## 2. Conditions That Bias HARDM Toward Presence (Allocator)

The choreographer (`agents/studio_compositor/homage/choreographer.py`)
reconciles pending ward transitions every tick against the active
package's concurrency limits. By default, HARDM participates in
rotation on equal terms with other transitional sources. Task #160
adds a weighted-bias term — `current_salience_bias() -> float in
[0, 1]` — computed from four inputs and exposed as the Prometheus
gauge `hapax_hardm_salience_bias`.

### 2.1 Active voice output (+0.5)

Source: `/dev/shm/hapax-compositor/voice-state.json` (written by
`agents/hapax_daimonion/vad_state_publisher.py` for the operator VAD
path, and extended by the CPAL voice chain to publish
`hardm_emphasis.json` on Hapax TTS begin/end — see §4). When
`hardm-emphasis.json.emphasis == "speaking"` (i.e., Hapax TTS is
producing audio), the bias adds +0.5. Rationale: voice is the
strongest communicative signal; viewer gaze must have somewhere to
settle, and the architectural choice is HARDM rather than any
narrative beat-ward.

### 2.2 Self-referential director intent (+0.3)

Source: the most recent `director-intent.jsonl` record in
`~/hapax-state/stream-experiment/director-intent.jsonl`. If the
intent's narrative text contains self-referential markers — "Hapax
thinks", "I notice", "I'm watching", "let me", "Hapax sees",
"watching the" — the bias adds +0.3. Rationale: self-referential
narrative is a cue to the audience that the forthcoming content is
about Hapax's internal state, which the HARDM matrix visually
represents.

Implementation: `_self_reference_in_intent(intents, n=5)` scans the
last five records for any of a small literal marker list. A more
elaborate LLM classifier is rejected on latency grounds; the bias is
read every compositor tick (~10 Hz) and must be computable in
microseconds from already-resident data.

### 2.3 Active-guest consent state (+0.2)

Source: `axioms/contracts/*.yaml` — each active consent contract
becomes a file in that directory (see
`shared/perceptual_field.py::_read_active_consent_contract_ids`). Any
contract with a filename containing `guest` (e.g., `guest-alice.yaml`)
adds +0.2 to the HARDM bias. Rationale: with a guest in the room,
HARDM serves as a neutral third-party visual anchor that the guest
and operator can both read without either feeling "stared at." This
matches the constitutional posture of `interpersonal_transparency` —
the matrix is a transparent, non-representational surface.

### 2.4 SEEKING stance (+0.2)

Source: `/dev/shm/hapax-stimmung/state.json` field `overall_stance`
(see `shared/stimmung.py:31` — `Stance` enum with `NOMINAL`,
`SEEKING`, `CAUTIOUS`, `DEGRADED`, `CRITICAL`). When
`overall_stance == "seeking"`, the bias adds +0.2. Rationale:
exploratory cognition (boredom → SEEKING per
`docs/superpowers/specs/2026-04-01-boredom-curiosity-pct-formalization.md`)
is most legible via HARDM — the stance cell on row 9 changes colour,
the stimmung cell on row 11 modulates alpha, and viewers see the
system "reaching" without any narrative beat being required.

### 2.5 Aggregation

The bias is `min(1.0, sum(contributions))`. No smoothing is applied
at the computation layer — the allocator already smooths via the
concurrency slice — and no minimum floor is enforced so quiescent
conditions resolve to 0.0, allowing HARDM to cycle out of rotation
when it has nothing to contribute.

The **unskippable threshold** is 0.7. When `current_salience_bias() >
0.7`, HARDM is forcibly enqueued in the choreographer's
pending-transitions queue every tick under the default_entry
transition (`ticker-scroll-in` under BitchX grammar). This is the
mechanism by which voice + self-reference, or voice + guest, or voice
+ SEEKING, reliably lock HARDM into presence. At bias ≤ 0.7, HARDM
participates in normal rotation.

## 3. Conditions Biasing HARDM Toward Being Referenced (Narrative)

The narrative director
(`agents/studio_compositor/director_loop.py::_build_unified_prompt`)
assembles a context prompt every tick. Task #160 prefixes the prompt
with a HARDM status line:

```
HARDM is [visible|emphasized|quiescent]; bias={bias:.2f}; emphasis=<speaking|quiescent>
```

This gives the director a deterministic handle on a first-class
visual state. Two conditions push the director toward explicit HARDM
reference:

### 3.1 Voice register = ANNOUNCING

Read from `/dev/shm/hapax-compositor/homage-voice-register.json` via
`shared/voice_register.py`. When `register == ANNOUNCING`, narrative
beats have a broader license to point viewers at specific HARDM
cells — "HRV elevated, watch the row-5 pulse", "MIDI is live, row 0
cyan". The register signals broadcast-mode delivery where
deictic reference is appropriate. Under `CONVERSING`, the register
suppresses these references (they would interrupt turn-taking).

### 3.2 Operator sidechat cue

Command: `point-at-hardm <cell>` (e.g., `point-at-hardm 9`). Parsed
in the sidechat consumer
(`agents/hapax_daimonion/run_loops_aux.py::sidechat_consumer_loop`).
On match, a narrative impingement is written to
`/dev/shm/hapax-director/operator-cue.json`:

```json
{
  "cue": "point-at-hardm",
  "cell": 9,
  "signal_name": "director_stance",
  "ts": 1776563400.123
}
```

The narrative director reads this file on the next prompt build,
injects a one-line instruction into the prompt (*"Operator cue:
reference HARDM cell 9 (director_stance) in your next narrative
beat"*), and deletes the file once consumed. Rationale: the operator
always has explicit veto or amplification control; this is the
fastest on-stream way to say "look at that cell now" without
touching the narrative prompt authoring path.

## 4. Anchoring Contract

HARDM's role as communicative anchor imposes three obligations on
adjacent subsystems:

### 4.1 Visual contract

When HARDM is visible and present in the rotation, the viewer should
be able to read it as "this is where Hapax is." To preserve this,
HARDM's rendering must remain shape-invariant across HOMAGE package
swaps — only the palette changes, never the geometry. This is
already enforced in `hardm_source.py` (package-invariant geometry
per spec §2) and is regression-pinned by
`TestGeometry::test_sixteen_primary_signals`.

### 4.2 Voice-HARDM coordination contract

When Hapax TTS begins, HARDM's currently active cells brighten
subtly (brightness multiplier applied to non-idle cells). When TTS
ends, the cells return to quiescent brightness. The mechanism:

- `agents/hapax_daimonion/cpal/production_stream.py` writes
  `/dev/shm/hapax-compositor/hardm-emphasis.json` with
  `{"emphasis": "speaking", "ts": ...}` at the start of T1/T2/T3
  production.
- The same module writes `{"emphasis": "quiescent", "ts": ...}` on
  completion.
- `hardm_source.HardmDotMatrix.render_content` reads this file and
  applies a brightness multiplier (1.18 for active cells, 1.0 for
  idle) during the speaking phase. Idle (muted) cells are **not**
  brightened — the coupling is selective so the grid itself doesn't
  pulse wholesale, only the currently informative cells do. A
  wholesale pulse would obscure the per-cell information content.

### 4.3 Operator-gaze contract (forward-compatible)

The IR perception backend (`agents/hapax_daimonion/backends/ir_presence.py`)
publishes `ir_gaze_zone`. When that zone falls on HARDM's canvas
bounds, it should be treated as attentional investment — the
narrative director can acknowledge ("I notice you're reading the
matrix"), and the allocator can add a small bias increment
(≤ +0.1, currently unimplemented per task #160 scope but noted as
follow-up #161). The current scope does not consume IR gaze; it is
documented here so the follow-on task has a contract to satisfy.

## 5. Integration Surfaces (Explicit, Not Exhaustive)

### 5.1 Ward allocator (compositor)

`agents/studio_compositor/hardm_source.py`:

- `current_salience_bias() -> float` — pure function, reads four SHM
  paths, returns `[0.0, 1.0]`.
- `HARDM_EMPHASIS_FILE` — canonical path constant.
- `_read_emphasis_state()` — returns `"speaking"` or `"quiescent"`;
  default `"quiescent"` on missing / stale (>2s) / malformed.
- `HardmDotMatrix.render_content` — applies brightness modulation
  when emphasis is `"speaking"`.
- Prometheus gauge `hapax_hardm_salience_bias` updated on every
  `current_salience_bias()` call (registered in
  `shared/director_observability.py`).

Choreographer coupling
(`agents/studio_compositor/homage/choreographer.py::reconcile`):

- Before concurrency reconciliation, read
  `hardm_source.current_salience_bias()`.
- If `bias > 0.7` and no pending HARDM transition is present, inject
  a synthetic `PendingTransition(source_id="hardm_dot_matrix",
  transition=package.transition_vocabulary.default_entry,
  enqueued_at=now, salience=bias)`. This is the "unskippable" path.
- The synthetic entry participates in the normal concurrency slice;
  it is not privileged beyond its salience score. Under
  `weighted_by_salience` rotation mode, bias > 0.7 typically wins;
  under `sequential` and `random`, it takes a deterministic slot.

### 5.2 Director narrative prompt

`agents/studio_compositor/director_loop.py::_build_unified_prompt`:

- Prefix line: `HARDM is [visible|emphasized|quiescent]; bias=X.XX;
  emphasis=<state>` — where `visible` means HARDM is currently in the
  active layout, `emphasized` means `bias > 0.7`, `quiescent` means
  neither.
- After the Current-Situation block: an optional operator-cue
  sentence (`"Operator cue: reference HARDM cell {N} ({signal_name})
  in your next narrative beat."`) read from
  `/dev/shm/hapax-director/operator-cue.json` and then deleted.

### 5.3 CPAL voice chain signal

`agents/hapax_daimonion/cpal/production_stream.py::ProductionStream`:

- `produce_t1`, `produce_t2`, `mark_t3_start`, `mark_t3_end`, and
  `interrupt` write `hardm-emphasis.json` atomically (tmp+rename).
- Begin-of-speaking writes `{"emphasis": "speaking", "ts": now}`.
- End-of-speaking (success or interrupt) writes
  `{"emphasis": "quiescent", "ts": now}`.
- Failure paths (e.g., missing audio_output) fall through to
  quiescent so the HARDM brightness never sticks at "speaking" after
  a dead production call.

### 5.4 Sidechat command

`agents/hapax_daimonion/run_loops_aux.py::sidechat_consumer_loop`:

- Before affordance dispatch, run `parse_point_at_hardm(msg.text)`.
- If it returns an integer cell index in `[0, 255]`, write the
  operator-cue file (at `/dev/shm/hapax-director/operator-cue.json`),
  then continue through the normal affordance pipeline so the
  utterance still appears in the standard observability trail.
- `parse_point_at_hardm` lives in `hardm_source` as a pure string
  parser; testable without any filesystem touch.

## 6. Failure Modes and Fallbacks

- **Missing `voice-state.json`**: bias reads "voice inactive";
  emphasis = quiescent. No penalty.
- **Missing stimmung state**: stance SEEKING contribution = 0. No
  penalty.
- **Stale `hardm-emphasis.json` (>2s)**: HARDM returns to quiescent
  brightness. The 2s cutoff matches the register-bridge staleness
  cutoff so both sides of the wire use the same convention.
- **Cell index out of range in operator cue**: cue file is not
  written; a `log.warning` records the rejected cell. The sidechat
  utterance still dispatches normally through the affordance
  pipeline.
- **Choreographer synthetic enqueue collides with real enqueue**:
  the choreographer's concurrency slice deduplicates by
  `source_id`; a doubled entry consumes two slots if both are in
  the same tick, but `default_entry` under BitchX is non-conflicting
  (both map to ticker-scroll-in on the same source). The spec's
  `max_simultaneous_entries` bound continues to hold.
- **Consent-safe flag active**: HARDM still renders geometry per
  spec §2 (cells in package's muted role). The bias is unchanged —
  HARDM's anchor role persists under consent-safe layout because
  the viewer still needs a return site. Emphasis brightness
  modulation is suppressed (muted cells are not brightened).

## 7. Non-Goals (Task #160 Scope Bound)

Out of scope for this task, documented for traceability:

- **IR-gaze feedback loop** — task #161 (inferred operator gaze
  toward HARDM → +0.1 bias, narrative acknowledgment).
- **Per-cell LLM-authored reference** — the narrative prompt exposes
  the HARDM status line; it does not synthesize novel cell-specific
  phrasings. Generating per-cell narrative is a LiteLLM-cost
  question deferred to the prompt-compression phase-3 plan.
- **HARDM layout re-placement based on bias** — bias only affects
  presence / absence in rotation, not spatial layout. Layout is
  owned by `config/compositor-layouts/default.json` and the
  live-change path (see `2026-04-16-live-change-safe-mode-design.md`).
- **Multi-HARDM composition** — there is exactly one HARDM per
  stream by constitutional axiom (single_user, single face).

## 8. Observability

Metrics (`shared/director_observability.py`):

- `hapax_hardm_salience_bias` — gauge, float in `[0, 1]`. Updated on
  every `current_salience_bias()` call.
- `hapax_hardm_emphasis_state` — gauge, `{speaking: 1, quiescent: 0}`.
- `hapax_hardm_operator_cue_total` — counter, labelled by `cell`.

Grafana panel (`grafana/dashboards/lrr-stimmung.json` has the
stimmung panel; HARDM bias can sit next to it as a time-series with
a horizontal line at 0.7 marking the unskippable threshold).

## 9. Test Coverage

`tests/studio_compositor/test_hardm_anchoring.py`:

- **Salience bias math** — voice active → bias ≥ 0.5; stance
  SEEKING + consent-active → ≥ 0.7; aggregated ceiling at 1.0.
- **Unskippable threshold** — when bias > 0.7, HARDM is included
  every tick (synthetic enqueue happens in choreographer reconcile).
- **TTS begin/end emphasis file** — `ProductionStream.produce_t1`
  round-trip: file written, read, file emptied to quiescent on
  completion.
- **`parse_point_at_hardm` string parser** — valid cell, invalid
  cell, out-of-range, non-hardm command.
- **Operator cue file write + cleanup** — sidechat dispatch writes
  the operator-cue file; after directorial consumption (simulated
  via direct file ops), file is gone.
- **Render-time brightness modulation** — rendering with emphasis
  `"speaking"` on an active cell produces brighter pixels than
  `"quiescent"` on the same cell; idle cells do not change.

## 10. References

- `docs/superpowers/specs/2026-04-18-hardm-dot-matrix-design.md`
- `docs/superpowers/specs/2026-04-18-homage-framework-design.md`
- `docs/superpowers/specs/2026-04-01-boredom-curiosity-pct-formalization.md`
- `docs/superpowers/specs/2026-04-17-volitional-grounded-director-design.md`
- `axioms/persona/posture-vocabulary.md` (stance table)
- `shared/voice_register.py` (register enum)
- `shared/stimmung.py` (stance enum)
- `agents/studio_compositor/hardm_source.py` (consumer)
- `agents/studio_compositor/homage/choreographer.py` (allocator)
- `agents/hapax_daimonion/cpal/production_stream.py` (TTS emission)
- `agents/hapax_daimonion/run_loops_aux.py` (sidechat consumer)
