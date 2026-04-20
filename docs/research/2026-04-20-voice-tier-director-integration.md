# Voice-Tier ↔ Programme / Director Integration Design

**Date:** 2026-04-20
**Register:** Scientific, operator-facing
**Scope:** Mechanism by which Hapax's content-programming layer
(`Programme`) and the narrative / structural director cooperatively
select between voice-transformation tiers (`TIER_0` – `TIER_6`) on each
~30-second tick during a livestream. Extends the tier-spectrum research
(`docs/research/2026-04-20-voice-transformation-tier-spectrum.md`), the
Evil Pet + S-4 base map (`docs/research/2026-04-19-evil-pet-s4-base-config.md`),
the voice self-modulation design (`docs/research/2026-04-19-voice-self-modulation-design.md`),
and the Programme primitive (`shared/programme.py`).
**Related tasks:** #164, #165, #190.
**Status:** research + design, not implementation.

---

## Terminology

- *Tier* — one of seven voice-transformation configurations (TIER_0
  dry through TIER_6 granular-dissolution) defined by the tier-spectrum
  doc. Each is a bundle of ≈ 16 MIDI CC values across Evil Pet (ch 0)
  and S-4 (ch 1), plus a Kokoro pace modifier.
- *Band* — contiguous subset of tiers legal in a given context.
- *Pick* — the single tier active on a given tick.
- *Excursion* — a momentary tier drawn from outside the Programme's
  default band but inside its permitted excursion set.

---

## §1. Decision surface — where the tier is chosen

### 1.1 The three structural options

**Option A — Director per-tick picks.** Each ~30 s tick, the narrative
LLM selects a tier from the active Programme's candidate set.

**Option B — Programme declares primary + excursion set.** The
Programme carries `voice_tier_primary` and `voice_tier_excursions`;
director only triggers excursions.

**Option C — Structural director picks the band; narrative director
micro-adjusts within the band.** `structural_director.py` (~150 s
cadence) emits a band as part of `StructuralIntent`. Narrative
director picks a single tier inside that band each tick; impingement
deltas shift the pick within the band.

### 1.2 Chosen approach — Option C

Option A churns: the narrative LLM is stateless across ticks in
`director_loop.py`, so per-tick selection degrades to a nearly-IID
draw from the candidate set. Each flip costs ≈ 16 CCs; four flips
per minute read as noise.

Option B violates the `shared/programme.py` axiom that envelope
fields are *soft priors, never hard gates*. A `voice_tier_primary`
field is effectively a hard gate until the Programme changes.

Option C matches Hapax's cadence hierarchy. The structural director
already owns 150-s moves (scene_mode, preset_family_hint,
homage_rotation_mode); tier band is the same kind of move. The
narrative director already owns 30-s compositional micro-adjustments;
picking within a structurally-chosen band is consistent with that job.

### 1.3 Concrete wiring

Extend existing types; do not invent parallel ones:

1. `shared/voice_tier.py` (new): `VoiceTier(IntEnum)` 0–6 plus
   `TIER_BANDS` named subsets. `IntEnum` permits arithmetic for
   impingement shifts.
2. `StructuralIntent` gains `voice_tier_band_low` and
   `voice_tier_band_high`; validator enforces `low ≤ high`.
3. `ProgrammeConstraintEnvelope` gains
   `voice_tier_band_prior: tuple[VoiceTier, VoiceTier] | None` and
   `voice_tier_excursion_set: set[VoiceTier]` — both soft priors, not
   gates.
4. `DirectorIntent` gains `voice_tier: VoiceTier` (the picked tier).
5. New `VoiceTierSelector` in
   `agents/hapax_daimonion/voice_tier_selector.py`; pure function,
   unit-testable, called once per narrative tick.

Signature:

```python
def pick_tier(
    *,
    structural_band: tuple[VoiceTier, VoiceTier],
    programme: Programme | None,
    stance: Stance,
    impingements: list[CompositionalImpingement],
    operator_override: VoiceTier | None,
    stimmung: SystemStimmung,
    previous_tier: VoiceTier,
    now_ts: float,
) -> VoiceTier: ...
```

The fact that this is a pure function is load-bearing — every test
in §10 depends on it.

---

## §2. Per-Programme-role default tier set

The tier-spectrum doc defines seven tiers. For every `ProgrammeRole`
the table below gives (a) a *default band* (structural-director prior;
the narrative director will pick inside it) and (b) an *excursion
set* (tiers the narrative director may dip into for specific
impingement-driven beats, outside the default band).

| Role | Default band | Excursion set | Rationale |
|---|---|---|---|
| `LISTENING` | TIER_0 – TIER_2 | TIER_3 only as a *leave* marker | Speech must stay intelligible; the Programme's purpose is the operator hearing chat. TIER_3+ breaks words; allow only a one-shot TIER_3 when Hapax explicitly breaks to silence. |
| `SHOWCASE` | TIER_1 – TIER_3 | TIER_4 | Demos want some color to mark the demo-voice vs. ordinary speech, but intelligibility dominates. TIER_4 permitted once per showcase as a climax. |
| `RITUAL` | TIER_0 *or* TIER_5 – TIER_6 | — | Ritual programmes deliberately juxtapose dry speech with full dissolution. The picker flips between the anchor band (0) and the marker band (5-6) on explicit ritual beats; no middle band. |
| `INTERLUDE` | TIER_2 – TIER_3 | TIER_4 | Interludes are texture-first; voice is already ornamental. Middle-tier default, one step up under high audience engagement. |
| `WORK_BLOCK` | TIER_0 – TIER_1 | TIER_2 | Work blocks need the operator and chat to read code-narration. TIER_2 permitted when narration switches to abstract commentary. |
| `TUTORIAL` | TIER_0 only | TIER_1 | Tutorials must be verbatim-intelligible. Excursion at TIER_1 permitted only for section-transition markers. |
| `WIND_DOWN` | TIER_2 – TIER_4 | TIER_5 | Wind-down tolerates dissolution. Default floor at TIER_2 so the voice reads as different from work-mode; ceiling at TIER_4. TIER_5 only at the programme's exit. |
| `HOTHOUSE_PRESSURE` | TIER_3 – TIER_5 | TIER_6 | Pressure programmes intentionally lean hot. TIER_6 single-burst permitted when a hothouse breakthrough moment fires. |
| `AMBIENT` | TIER_0 – TIER_2 | — | Ambient programmes rarely speak. When they do, hold CLEAR. No excursions — ambient must not abruptly wake the room. |
| `EXPERIMENT` | TIER_0 – TIER_6 | — | By construction experimental. The structural director is free to pick any band; the narrative director is free to pick any tier inside it. |
| `REPAIR` | TIER_0 only | TIER_1 | Repair programmes are error-recovery; intelligibility must be maximized. TIER_1 only for repair-flavored self-narration ("rolling back X"). |
| `INVITATION` | TIER_0 – TIER_1 | TIER_2 | Invitations address humans directly. Intelligibility dominates; a single TIER_2 excursion permitted at the close. |

### 2.1 Coverage check

All twelve `ProgrammeRole` values (enumerated in `shared/programme.py`,
lines 64–75) are covered exactly once. All seven tiers appear in at
least one role's default band. TIER_6 appears only in `EXPERIMENT` and
as excursion for `HOTHOUSE_PRESSURE` and `RITUAL` — correct, because
TIER_6 drives the granular engine into pure dissolution and is
monetization-risky (§5).

### 2.2 Storage

Role → band/excursion table lives as `_ROLE_TIER_DEFAULTS` in
`shared/voice_tier.py`, beside the enum. It is a module-level constant
so consumers (structural director, narrative director, selector) all
read the same data. The Programme envelope's
`voice_tier_band_prior` field, when set by the Hapax-authored
programme planner, overrides the role default for that Programme
instance; if unset, the role default is used verbatim. This matches
the existing soft-prior pattern — an unset prior reads as "no
preference, use the role default", never as an exclusion.

---

## §3. Stance × tier coupling

`shared/stimmung.py` defines five stances: `NOMINAL`, `SEEKING`,
`CAUTIOUS`, `DEGRADED`, `CRITICAL`. Stance coupling applies as a
bias *on top of* the structural band — it does not change the band
(Option C forbids that) but does shift the preferred tier *within*
the band, and caps the top of the band under degradation.

### 3.1 Bias function

Let `band = (low, high)` be the structural band and
`baseline` be the band's midpoint rounded toward `high` (so a band
of `[1, 3]` has baseline 2, `[0, 2]` has baseline 1). Define
`stance_tier_delta(stance, stimmung) -> int` as:

```
NOMINAL   → 0         (no shift; baseline prevails)
SEEKING   → +1        (lean more expressive; tracks exploration_deficit)
CAUTIOUS  → 0         (hold baseline; infrastructure warnings do not
                       change voice character by themselves)
DEGRADED  → cap at max(low, 3); no additive shift
CRITICAL  → clamp to low; override any impingement-driven shift
```

### 3.2 DEGRADED + CRITICAL as safety overrides

DEGRADED caps the selectable tier at `min(high, 3)` — it must not
silently leave the band. If the band's low is already > 3, DEGRADED
clamps to band-low (the most-intelligible tier the Programme allows).
CRITICAL forces tier = band-low regardless of impingement; voice must
be maximally intelligible for recovery narration. CRITICAL is the one
case where the selector's output is not a function of impingements.

### 3.3 SEEKING + exploration_deficit

SEEKING is the only stance that positively raises the tier. Per
`shared/stimmung.py`, SEEKING enters when infra is NOMINAL *and*
`exploration_deficit > 0.35` sustained for 3 ticks. The `+1` reflects
the spec's intent — a voice reaching further. Further shift requires
an impingement.

### 3.4 Signal-honest, not performative

Per `feedback_no_expert_system_rules` and §4.4 of
`2026-04-19-voice-self-modulation-design.md`: stance tracks an
internal configuration the operator can verify on the stimmung
gauges. Voice tier *tracks* stance; it does not *perform* a tier.

---

## §4. Impingement-driven tier shifts

Within a tick, after the stance shift in §3, the narrative director
reads the compositional impingements it just composed and applies a
bounded delta.

### 4.1 Signal → delta

Using the impingement taxonomy already present in
`shared/director_intent.py`:

| Impingement property | Condition | Delta | Cap |
|---|---|---|---|
| `salience` | ≥ 0.80 | +1 | no more than one +1 per tick |
| `intent_family == "voice.register_shift"` | always | +1 | composes additively with salience |
| `intent_family == "overlay.emphasis"` | always | 0 | emphasis is visual, not vocal |
| `stimmung.arousal_spike` | > 0.7 over last 5 s | +1 | one per 30-s window |
| `stimmung.grounding_quality` | < 0.3 | −1 | downgrades until grounding recovers |
| `stimmung.exploration_deficit` | < 0.10 for ≥ 60 s | floor = band_low | tied to "bored-voice" recovery |
| operator `direct_comm` utterance just arrived | within 3 s | clamp to band_low | operator address = maximum intelligibility |

After stance and impingement deltas, clamp the pick to
`[structural_band_low, structural_band_high]` *except* when an
excursion trigger fires (§4.2).

### 4.2 Excursion triggers

The Programme's excursion set (§2) is a whitelist of tiers the
narrative director may jump to for a single tick, bypassing the
structural band clamp. Each excursion needs an *explicit* trigger;
the narrative LLM must emit `excursion_request: VoiceTier` in its
`DirectorIntent` output and the selector must validate it against
the Programme's `voice_tier_excursion_set`. If the request is not in
the set, the request is logged and dropped — the pick falls back to
the within-band pick.

Excursion triggers have a hard rate limit: at most one excursion per
60 s per Programme instance, regardless of how many impingements fire.
This is the selector's only stateful guard (previous-tick memory is
stateless bookkeeping; the 60-s excursion clock is the single
time-based bookkeeping field).

### 4.3 Signal path

```
SystemStimmung (60-s sliding window)
        │
        ▼
DMN impingement dispatch (existing)
        │
        ▼
director_loop composes CompositionalImpingement list (~30 s cadence)
        │
        ▼
VoiceTierSelector.pick_tier(...)
    1. baseline = midpoint(structural_band)
    2. + stance_tier_delta(stance, stimmung)       [§3]
    3. + impingement_delta(impingements, stimmung) [§4.1]
    4. apply excursion request if legal            [§4.2]
    5. apply mode-D mutex                          [§6]
    6. clamp to band (unless excursion)
    7. apply operator_override if set              [§8]
    8. debounce against previous_tier              [§7]
    9. emit tier + transition plan
        │
        ▼
DirectorIntent.voice_tier populated; vocal_chain reads it, writes CCs
```

The selector runs once per narrative tick. It is stateless except for
(i) the previous tier (carried in `director_loop`'s tick state) and
(ii) the last-excursion timestamp per Programme (kept on a runtime
side-table, not on the Programme primitive — the primitive stays
JSON-round-trippable).

### 4.4 Why not let the LLM emit tier directly

The LLM cannot enforce debounce (no cross-tick memory), cannot
deterministically honor the band (attention is on salience, not the
envelope), and cannot guarantee the mode-D mutex (§6). The selector
is the deterministic arbiter; the LLM contributes (a) composed
impingements and (b) an optional `excursion_request` the selector
validates.

---

## §5. HOMAGE / GEM ward coupling

### 5.1 HOMAGE package × voice tier

`HomagePackage` carries a `VoiceRegister` (TEXTMODE for BitchX). Tier
and register are orthogonal but must be consistent — register governs
what Hapax says and how CPAL frames the prompt; tier governs Kokoro's
downstream transformation.

Coupling rule (additive prior, not gate):

- `voice_register == TEXTMODE` → raise the band floor by one tier for
  the active Programme. Bands whose low was TIER_0 become TIER_1
  (IRC-lineage voice shouldn't be fully dry). Excursion set preserved.
- `voice_register == ANNOUNCING` → grant excursion-only access to
  TIER_{default_high + 1} if not already permitted. No change to the
  default band.
- `voice_register == CONVERSING` → no change.

`PerceptualField.homage` (HOMAGE Phase 9) selects which package is
active per research condition; the tier rule reads the active package.

### 5.2 GEM ward × voice tier

GEM (Graffiti Emphasis Mural, task #191) is a visual surface for
Hapax ASCII/glyph expression. While GEM is *foregrounded* by the
choreographer (not merely alive in the registry), the selector
clamps the tier ceiling to TIER_3 regardless of Programme band —
glyph-forward wards are reading wards, and heavy granular voice
damages legibility. Clamp releases when GEM backgrounds.

The coupling is deliberately one-way (GEM → voice, not voice → GEM):
GEM is the more-specific signal; voice is the general channel and
should defer.

### 5.3 Storage

`homage_package.voice_register` already lives on `HomagePackage`;
GEM foregrounding state is tracked by the HOMAGE FSM. The selector
reads both via small existing APIs (`voice_register_reader`,
`homage_fsm.foregrounded_ward()`). No new persistence.

---

## §6. Mutex with Mode D (vinyl granular wash)

Voice tiers 5 and 6 engage the Evil Pet granular engine (CC 11,
GRAINS VOLUME ≠ 0). Mode D — the vinyl-granular-wash mode used when
the operator spins a record and the compositor routes the vinyl audio
through Evil Pet — also engages the granular engine, but with
completely different preset values. Both cannot be on at once. The
granular engine is a single-state physical resource.

### 6.1 Ownership model

Single-owner resource with two possible owners: `voice` (tier
selector) and `vinyl` (Mode D controller). State lives in
`agents/studio_compositor/granular_engine_owner.py` (new). Taking the
lease is atomic (O_CREAT | O_EXCL on `/dev/shm/hapax-granular-owner`);
release is `os.unlink` by the holder. Stale lease TTL = 30 s permits
steals (logged at WARN).

### 6.2 Contention behavior

If the selector wants TIER_5/6 and `vinyl` holds the lease, the
selector downgrades to TIER_4 for that tick (TIER_4 is the highest
tier that does not touch GRAINS VOLUME) and increments
`mode_d_mutex_deferral`. If no owner holds the lease, the selector
takes it and holds while the pick stays at TIER_5/6; releases on the
first tick the pick drops below TIER_5.

Symmetric on the Mode D side: if `voice` owns the lease when Mode D
wants to activate, Mode D defers one narrative tick (~30 s) and
retries. Voice wins the tiebreak — the narrative moment is more
time-bound than the vinyl state.

### 6.3 Observability

Gauge `hapax_granular_engine_owner{owner}` (values 0/1 per label),
counter `hapax_granular_engine_contention_total{loser}`. Both in
`granular_engine_owner.py`.

---

## §7. CC emission rate limiting

A tier transition writes ≈ 16 MIDI CCs. Sending them blindly produces
artifacts — zipper noise on resonant filters, reverb-tail jumps, and
audible envelope re-triggers. The selector must debounce transitions
and crossfade their parameters.

### 7.1 Debounce

Rule: *do not transition twice within 500 ms*. The selector tracks
`last_transition_ts` in caller state; if
`now - last_transition_ts < 0.5`, returns `previous_tier` and
increments `tier_debounce_suppressed`.

Why 500 ms: Programme-boundary transitions can fire off-tick and
must be guarded against near-simultaneous impingement shifts.
Kokoro's first-sample latency is 150–250 ms
(`2026-04-19-voice-self-modulation-design.md` §5.1); 500 ms ≥ 2×
that ensures parameter writes don't land mid-first-utterance. It
remains short enough that the next excursion feels reactive
(lands ≤ 30 s out on the next narrative tick).

### 7.2 Crossfade via per-dimension ramps

Rather than bursting all 16 CCs, pace them across a `crossfade_ms`
window: compute per-dimension deltas, emit intermediate values at
50 ms intervals, final value at the end. Dimensions whose delta ≤ 2
CC units skip intermediates.

Crossfade window scales with tier distance:

| `|new_tier − old_tier|` | Crossfade window |
|---|---|
| 1 | 100 ms |
| 2 | 200 ms |
| 3 | 350 ms |
| ≥ 4 | 500 ms |

Larger jumps get more time because they travel farther in every
dimension. The 500 ms ceiling matches the debounce interval so two
back-to-back large jumps cannot overlap.

### 7.3 Implementation

New `TierTransitionEmitter` in
`agents/hapax_daimonion/vocal_chain.py`, reusing `MidiOutput.send_cc`
and `CCMapping.breakpoints`. Tier-level ramping layers on top of the
existing per-dimension level interpolation.

### 7.4 MIDI throughput budget

Per `2026-04-19-evil-pet-s4-base-config.md` §5.3, DIN MIDI budget is
~1000 msg/s; current dimension ceiling is 360 msg/s. A large tier
transition (16 CCs × 5 intermediates × 2 devices in 500 ms) is
64 msg/s, well inside the budget even overlapping dimension activity.

---

## §8. Operator override

The operator must be able to force a tier from the Stream Deck or the
CLI, independent of the director's preference.

### 8.1 Surface

- Stream Deck button: `voice.tier.{0..6}` as seven buttons in the
  "voice" folder on the control surface. Each button is a
  `RemoteTrigger` action that writes to the command registry.
- CLI verb: `hapax-voice-tier <0-6|auto>`. `auto` releases the
  override and returns control to the selector.

Both routes write to `/dev/shm/hapax-voice-tier-override.json`
(atomic tmp+rename) with fields
`{tier: int|null, set_at: float, ttl_s: float}`. The selector reads
this file on every pick call. If the override is set and fresh (file
mtime + ttl_s ≥ now), the selector uses it; otherwise it ignores the
file (the override is gone when stale).

### 8.2 TTL

Default TTL is 600 s (10 min). The operator sets a Stream Deck button
and, ten minutes later, control returns to the selector without
requiring them to remember to un-press. This prevents forgotten
overrides from leaking across sessions.

### 8.3 Governance gating

Three guardrails clamp the override's effective output:

1. **No manual TIER_6 with `ANNOUNCING` register.** Broadcast +
   granular dissolution together flag reliably against monetization
   fingerprinters (`2026-04-19-voice-self-modulation-design.md` §5.6).
   Request accepted, pick clamped to TIER_5, governance note to
   `audit.jsonl`, ntfy to operator.
2. **No manual tier change during `DEGRADED-STREAM` mode** (task #122).
   Override queued; applies on DEGRADED-STREAM exit.
3. **No manual override during active sidechat (`direct_comm`).**
   Tier clamps to `band_low` regardless of override, per §4.1.

These are not fail-closed consent-gate blocks; they are output
clamps. `MonetizationRiskGate` already owns the tier-6 / announcing
check for medium-risk Programmes; the override branch extends it.

### 8.4 Observability of overrides

A counter `hapax_voice_tier_operator_override_total{tier}` records
every applied override. A companion counter
`hapax_voice_tier_operator_override_rejected_total{tier,reason}`
records each governance-gated rejection with its reason
(`announcing_tier6`, `degraded_stream`, `sidechat_active`). These
surface on the voice-subsystem Grafana dashboard next to the
per-tier time-in-tier gauges.

---

## §9. Observability

The metrics surface mirrors the existing `_VocalChainMetrics`
pattern in `vocal_chain.py` — Prometheus counters + a gauge, labels
kept low-cardinality (`tier` is 7 values, `programme_role` is 12,
`stance` is 5; the product is well under the 1k-label-combo
recommendation).

### 9.1 Counters and gauges

| Metric | Type | Labels | Semantics |
|---|---|---|---|
| `hapax_voice_tier_active` | gauge | `tier` | 1 for the currently active tier, 0 for the rest |
| `hapax_voice_tier_transition_total` | counter | `from_tier`, `to_tier` | Increment on each tier change |
| `hapax_voice_tier_transition_duration_seconds` | histogram | `tier_distance` | Buckets 0.05, 0.1, 0.2, 0.35, 0.5; observes the crossfade window actually emitted |
| `hapax_voice_tier_debounce_suppressed_total` | counter | — | Increment on each debounced transition |
| `hapax_voice_tier_excursion_total` | counter | `programme_role`, `tier` | Increment when an excursion fires |
| `hapax_voice_tier_excursion_rejected_total` | counter | `reason` | `outside_whitelist`, `rate_limited`, `mode_d_mutex` |
| `hapax_voice_tier_operator_override_total` | counter | `tier` | Override applied |
| `hapax_voice_tier_operator_override_rejected_total` | counter | `tier`, `reason` | Governance-gated rejection |
| `hapax_voice_tier_stance_clamp_total` | counter | `stance` | DEGRADED/CRITICAL clamp fired |
| `hapax_voice_tier_time_in_tier_seconds` | counter | `tier` | Wall time spent at each tier |
| `hapax_granular_engine_owner` | gauge | `owner` | One of `{voice, vinyl, free}` holds the lease |
| `hapax_granular_engine_contention_total` | counter | `loser` | Mutex deferrals |

### 9.2 Grafana

A new row on the voice-subsystem dashboard:

- Time-series chart of `hapax_voice_tier_active` stacked to 1.0 —
  visually "what tier is on, moment by moment".
- Histogram of transition durations.
- Bar chart of excursion count per programme role.
- Single-stat: override rate per hour.
- Single-stat: mutex deferrals per hour.

### 9.3 Langfuse

Each `pick_tier` call emits a `hapax_span` (pattern in
`shared/telemetry.py`) with metadata `{tier_chosen, stance,
programme_role, band_low, band_high, impingement_count,
excursion_applied, override_applied}`. This enables per-run traces
correlating tier choice with LLM-composed impingement narrative,
useful for LRR post-hoc analysis.

---

## §10. Test strategy

### 10.1 Unit tests (selector as pure function)

Files: `tests/hapax_daimonion/test_voice_tier_selector.py`.

Cases:

1. *Stance = NOMINAL, empty impingements, band = (1,3)* → pick = 2
   (midpoint).
2. *Stance = SEEKING, empty impingements, band = (1,3)* → pick = 3
   (midpoint + 1 clamped to band high).
3. *Stance = DEGRADED, band = (3,5)* → pick = 3 (DEGRADED caps at 3,
   but band low is 3, so pick = 3).
4. *Stance = CRITICAL, band = (2,4)* → pick = 2 (CRITICAL clamps to
   band low).
5. *Impingement with salience 0.9* → pick = baseline + 1.
6. *Impingement with `grounding_quality < 0.3`* → pick = baseline − 1.
7. *Excursion request outside whitelist* → request dropped, pick
   stays in band, `excursion_rejected` counter increments.
8. *Excursion request inside whitelist, first in window* → pick =
   requested.
9. *Excursion request inside whitelist, second in 60 s* → request
   dropped, pick stays in band.
10. *Mode D owns granular lease, selector wants TIER_5* → pick =
    TIER_4, mutex counter increments.
11. *Operator override TIER_6 with announcing register* → pick =
    TIER_5, rejection counter increments with
    `reason=announcing_tier6`.
12. *Debounce: last_transition_ts = now − 0.3 s, new pick would
    differ* → pick = previous_tier, debounce counter increments.
13. *Previous tier = 2, new pick = 2* → no transition, no counter
    changes. (Regression: spurious transitions must not emit CCs.)

Each case uses a hand-built `SystemStimmung`, a hand-built
`Programme`, and deterministic impingement lists.

### 10.2 Integration test (director → vocal_chain)

Files: `tests/studio_compositor/test_director_tier_integration.py`.

Scenario: instantiate a `DirectorLoop` with a fake LLM that emits a
known `DirectorIntent` containing a known `voice_tier`. Verify:

- The selector called from the director receives the LLM's tier as
  `excursion_request`, validates it against the active Programme, and
  either accepts or falls back.
- The resulting tier is written to
  `/dev/shm/hapax-director/intent.json`.
- A mock `MidiOutput` receives the expected CC writes, pacing
  consistent with the crossfade window (using a
  `unittest.mock.patch` on `time.monotonic`).

### 10.3 Live smoketest (canned sequence)

`scripts/voice-tier-smoketest.sh` (new) runs a 5-minute scripted
sequence:

1. `WORK_BLOCK` + NOMINAL + no impingements → TIER_0/1 for 60 s.
2. Inject `salience=0.9` impingement → one +1 shift, crossfade < 350 ms.
3. Switch to `HOTHOUSE_PRESSURE` → band widens to [3,5], pick lands
   within one tick.
4. Force DEGRADED → clamp to TIER_3 within one tick.
5. CLI `hapax-voice-tier 6` → rejection if announcing, else TIER_6.
6. Return NOMINAL + `AMBIENT` → TIER_0/1 within one tick.

Human observer listens; `pw-cat --record` captures 3 s at each
transition for post-hoc waveform inspection.

### 10.4 Replay regression

Per LRR Phase 2 replay (task #29), the scripted sequence also runs
in the replay harness against a prior livestream snapshot. The
replay tier timeline is diffed against
`tests/data/voice_tier_golden_timeline.jsonl`; drift flags the
regression.

---

## §11. Implementation plan

Six phases, each independently shippable. LOC estimates are for new
or substantively modified Python only; config and tests scale with
the feature but are not itemised.

### Phase 1 — `VoiceTier` enum + role defaults

Files: `shared/voice_tier.py` (new, ~120 LOC), one unit test file
(~150 LOC tests), one import tweak in `shared/__init__.py`.

Adds the enum, the `_ROLE_TIER_DEFAULTS` table, and the
`_TIER_TO_CC` table (the concrete Evil Pet + S-4 CC bundle per tier).
No wiring yet. Ships by itself as a pure data addition.

### Phase 2 — Programme + StructuralIntent fields

Files: `shared/programme.py` (+ ~40 LOC to add the two new envelope
fields with validators), `agents/studio_compositor/structural_director.py`
(+ ~30 LOC for the two tier-band fields on `StructuralIntent` and an
update to the LLM prompt to emit them), tests (+ ~120 LOC).

After this phase the structural director's output carries the band,
but no consumer reads it yet. Ships as a schema extension; consumers
default to "no band preference" when the fields are unset.

### Phase 3 — `VoiceTierSelector` and director integration

Files:
`agents/hapax_daimonion/voice_tier_selector.py` (new, ~220 LOC),
`agents/studio_compositor/director_loop.py` (+ ~60 LOC to call the
selector after impingement composition and write `voice_tier` into
`DirectorIntent`), `shared/director_intent.py` (+ ~10 LOC field),
tests in `test_voice_tier_selector.py` (~400 LOC).

After this phase the selector is deterministic and has its full
§10.1 unit coverage. `DirectorIntent.voice_tier` is populated but
the vocal_chain side still writes its old per-dimension CCs only.

### Phase 4 — `TierTransitionEmitter` + vocal_chain wiring

Files: `agents/hapax_daimonion/vocal_chain.py` (+ ~180 LOC for the
emitter class + tier-level CC bundles), an additional test file
(~200 LOC). The emitter reads `voice_tier` out of the incoming
impingement (or, preferably, out of `DirectorIntent` piped through the
impingement consumer), translates to the CC bundle, and emits the
crossfaded transition.

After this phase tier selection becomes audible. Phase 1's data
table is now active.

### Phase 5 — Mode D mutex + operator override

Files:
`agents/studio_compositor/granular_engine_owner.py` (new, ~90 LOC),
CLI script `scripts/hapax-voice-tier` (new, ~40 LOC),
Stream Deck config additions (not Python), a selector update to read
the override file (+ ~25 LOC), governance check in the selector for
announcing+TIER_6 (+ ~15 LOC).

Ships the §6 mutex and the §8 override path together; they share the
same state-file pattern and benefit from being tested together (a
Mode-D-active + override-TIER_6 scenario exercises both).

### Phase 6 — HOMAGE + GEM coupling, Prometheus, Grafana dashboard

Files: selector update to read `HomagePackage` and HOMAGE FSM
(+ ~40 LOC), Prometheus metric definitions (+ ~70 LOC in the selector
+ emitter + mutex modules), Grafana JSON panel addition (not
Python). Shipping this phase closes the observability loop in §9.

### 11.1 Rollout order and interdependencies

Phases 1 → 2 → 3 must ship in strict order; each one's outputs feed
the next. Phases 4, 5, 6 can ship in any order after Phase 3, but the
recommended order above puts audible feedback first (4), then safety
(5), then dashboards (6). Each phase can be behind a feature flag
(`HAPAX_VOICE_TIER_ENABLE=0|1`, default `0` until Phase 4 is merged
and smoketest in §10.3 passes).

### 11.2 Risk and rollback

Phase 4 is the only phase whose reversion requires reverting
behaviour live. Rollback is a single env-var flip
(`HAPAX_VOICE_TIER_ENABLE=0`) that returns `vocal_chain.py` to its
pre-Phase-4 per-dimension-only CC path. The tier-level bundle in
`_TIER_TO_CC` is ignored while the flag is off. This matches the
"live-iterate via DEGRADED-STREAM mode" directive
(`project_homage_go_live_directive`) and the "verify before
claiming done" feedback memory — each phase's local smoketest must
pass before declaring it live.

---

## Sources

- `shared/programme.py` — Programme primitive, 12-role enum, soft-
  prior envelope.
- `agents/studio_compositor/director_loop.py` — narrative director,
  impingement composition.
- `agents/studio_compositor/structural_director.py` — ~150-s
  cadence, scene_mode + preset_family + homage_rotation_mode.
- `agents/hapax_daimonion/vocal_chain.py` — 9-dim semantic MIDI
  modulation, CC mappings, Prometheus metrics pattern.
- `shared/stimmung.py` — Stance enum (NOMINAL / SEEKING / CAUTIOUS /
  DEGRADED / CRITICAL), stance derivation, hysteresis.
- `shared/voice_register.py` — VoiceRegister enum
  (ANNOUNCING / CONVERSING / TEXTMODE).
- `shared/homage_package.py` — HomagePackage abstraction.
- `shared/governance/monetization_safety.py` —
  MonetizationRiskGate.
- `docs/research/2026-04-19-voice-self-modulation-design.md` —
  signal path audit, latency budget, feedback-loop mitigations, §4.2
  signal → dimension mapping.
- `docs/research/2026-04-19-evil-pet-s4-base-config.md` — Evil Pet
  and S-4 CC map, rate-limit ceiling, base preset values, signal-
  compatibility audit.
- `docs/research/2026-04-20-voice-transformation-tier-spectrum.md` —
  seven-tier definition (referenced as sibling doc; read alongside
  this document for the CC bundle per tier).
- `docs/superpowers/specs/2026-04-02-unified-semantic-recruitment-design.md`
  — AffordancePipeline soft-prior semantics.
- `docs/superpowers/specs/2026-04-18-homage-framework-design.md` —
  HOMAGE package, voice register coupling, choreographer FSM.
- `hapax-council/CLAUDE.md` — Unified Semantic Recruitment, Reverie
  Vocabulary Integrity, Voice FX Chain sections.
- project memories `project_vocal_chain`, `project_programmes_enable_grounding`,
  `feedback_hapax_authors_programmes`, `project_hardm_anti_anthropomorphization`,
  `feedback_no_expert_system_rules`, `feedback_grounding_exhaustive`.
