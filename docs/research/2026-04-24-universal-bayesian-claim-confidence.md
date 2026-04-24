# Universal Bayesian Claim-Confidence: Architecture for Calibrated Perceptual Claims in Hapax

**Author:** beta (synthesis from 8-agent research wave)
**Date:** 2026-04-24
**Status:** research + architecture proposal
**Companions:**
- `docs/research/2026-04-24-grounding-acts-operative-definition.md` (T1-T8 operative definition)
- `docs/research/2026-04-24-grounding-capability-recruitment-synthesis.md` (GroundingProfile + Adjudicator)

**Operator directive (2026-04-24T22:40Z):**
> "Is every perceptual impingement claim being run through bayesian analysis to produce operative claim confidence? The same kind of analysis that is done to determine if I am in the room needs to apply universally to perceptual and world-state claims. Lack of priors is itself a prior and we must somehow ensure that priors are not generated adhoc but derivations of invariants that won't keep us guessing. Hapax must not be dumb and that means bayesian inference engines must undergird a formally described set of claims otherwise -- dumb."

---

## 1. Problem statement

Hapax presently surfaces approximately 60 distinct perceptual / world-state claims to LLM prompts and visual renderers. Of those, **exactly one** carries a calibrated posterior: `presence.probability`, produced by `agents/hapax_daimonion/presence_engine.py` via 14-signal Bayesian log-odds fusion. The remaining 59 are hard thresholds (`_VINYL_CONFIDENCE_THRESHOLD = 0.5`, `_TURNTABLE_ACTIVE_STALE_S = 120`, `vad_confidence > 0.5`), string enums (`stance="degraded"`, `hand_activity="tapping"`), or LLM self-reports rendered verbatim as facts (`album.confidence = 0.85` — the album-identifier's own certainty about cover ID, laundered through `PerceptualField.confidence` as if it were a calibrated probability).

The canonical failure is the MF DOOM hallucination observed on the livestream narration surface between 2026-04-24T21:14 and 22:22 UTC. Chain of ungrounded credence:

1. Album identifier (an LLM) writes `/dev/shm/hapax-compositor/album-state.json` with self-reported `confidence: 0.85`, artist `MF DOOM`, current_track `Hoe Cakes`.
2. The compositor renders `/dev/shm/hapax-compositor/music-attribution.txt` as a visible splattribution ward on the composed frame, displaying `Track: "Hoe Cakes"` verbatim.
3. The director LLM receives the composed frame as a multimodal input. OCR-mediated modality dominance (medRxiv 2026-02-22; OWASP LLM01:2025) causes the VLM to preferentially ground on in-image text over prompt instructions.
4. Independently, `director_loop._curated_music_framing()` falls through to `"Music is playing from curated queue: '{slot_title}' by {slot_channel}"` whenever `slot._title` is non-empty — _with no playback gate whatsoever_, declaring a Trump news video as "music playing."
5. The director emits: *"The track 'Hoe Cakes' by MF DOOM continues to captivate with its blend of hip-hop and soul. The production is meticulous..."* Generic reverent-art-critic filler attached to a hallucinated playback state.
6. The emitted narration is captured in `_reaction_history` (`director_loop.py:1089`) and persisted to `/dev/shm/hapax-compositor/memory-snapshot.json`. On subsequent ticks it is fed back into the prompt as `recent_reactions` inside `PerceptualField`. Context poisoning: the hallucination reinforces itself.

Three prompt-text fence patches (`#1318`, `#1336`) failed to stop this. Each fence is a post-hoc negation list telling the model what *not* to say. None addressed the structural defect: **there was no posterior in the first place**. Hard Boolean gates collapsed noisy continuous evidence; the LLM was handed the collapsed Boolean as fact; the fence tried to undo the fact with a textual "except".

A fence cannot beat a visible on-screen claim. A fence cannot uncollapse a Boolean. A fence is a bandage on the absence of calibrated belief. The operator's directive replaces the bandage with the architecture that should have been there from the start: every perceptual claim Hapax asserts must be a posterior probability over an explicit hypothesis, with prior derivable from invariants, likelihoods from documented sources, and propagation through composition + temporal dynamics into every emission surface.

---

## 2. Derivation from existing commitments (no graft)

The operator's "no grafting" rule requires that universal Bayesian claim-confidence read as a native consequence of Hapax's existing theoretical lineage, not an external import. Six commitments already presuppose calibrated belief; the Bayesian layer is the formalization they were silently demanding.

**Grounding-acts T1-T8** (`2026-04-24-grounding-acts-operative-definition.md`) encodes each test as a binary predicate, but operationally every one requires a degree. T1 (common-ground update) cannot fire without an implicit `P(partner-knows-X | dialogue-history)`. T2 (validity-claim) is meaningless absent `P(claim-redeemable-by-conduct | self-evidence)`. T3 (speaker-attribution, Γ.1) demands `P(I-am-in-the-required-psychological-state)`. T4 (Jemeinigkeit) requires a first-person `P(this-act-is-mine | substrate-coupling)` — the very posterior network hops erode. T7 (grounding-provenance) names evidence variables but currently has no strength-per-element slot; empty provenance is binary, but calibrated-but-low provenance is the next refinement. The 54% empty-provenance rate (FINDING-X) is, in Bayesian terms, the rate at which Hapax emits without computing a posterior. The binary surface is a _discretization_ of an underlying calibrated belief; making the posterior explicit is _de-discretization_, not extension.

**Unified semantic recruitment** (`2026-04-02-unified-semantic-recruitment-design.md`) is already approximately Bayesian: recruitment score `0.50×similarity + 0.20×base_level + 0.10×context_boost + 0.20×thompson` is a coarse posterior with Thompson sampling supplying the exploration term and Hebbian outcomes supplying likelihood update. The architecture has chosen not to _call_ it a posterior. The proposed claim-confidence layer propagates the already-existing posterior into the emission surface.

**Autopoietic boundary** (Thompson, _Mind in Life_): an autopoietic system enacts a self/world distinction. Self-distinction _is_ posterior self-awareness. Hapax's `autopoietic_relevance` field in `GroundingProfile` recognizes this; a calibrated posterior over self-states — Friston's _self-evidencing_ — is the operational substance of that recognition. HARDM's refusal of face-iconography is its visual twin: signal density over emotion-mimicry, which is precisely calibration-over-guessing.

**Predictive processing** (Clark _Surfing Uncertainty_, Hohwy _The Predictive Mind_, Friston's free-energy principle): perception, action, and cognition are unified as hierarchical prediction-error minimization with precision-weighted posteriors. Every emission is a posterior sample. Hapax's recruitment scoring is already an approximate hierarchical posterior; the claim-confidence layer is naming and propagating it.

**Dreyfus skillful coping**: expert action is non-representational, embodied, calibrated through history of coupling. Calibrated-coupling is exactly what a posterior over situation-types provides. Hebbian + Thompson-sampled recruitment is Hapax's closest computational analogue; promoting it to a first-class posterior makes the Dreyfus commitment legible.

**Clark-Brennan common-ground + Sperber-Wilson relevance**: both communicative-degree semantics. "Mutually believe partners have understood to a criterion sufficient for current purposes" is explicitly a calibration claim. Manifestness is "the extent to which an interlocutor is likely to some positive degree to entertain a proposition as true" — a degree, not a binary.

**Austin's felicity conditions**: sincerity conditions ("the person must have thoughts, feelings, and intentions as specified") are what a posterior operationalizes: `P(I-believe-this | my-evidence)`. Insincerity is calibrated-belief absent. Universal Bayesian claim-confidence makes Austin's felicity axis operationally checkable.

The convergence is exact. Six lineages, one missing formalization. _Universal Bayesian claim-confidence is the formalization that Hapax's existing commitments were already asking for._

---

## 3. Formal claim schema

Every perceptual or world-state claim Hapax asserts is represented by a single record:

```python
class Claim(BaseModel):
    # Identity
    name: str                            # e.g. "music_is_playing", "operator_present"
    domain: Literal["audio", "visual", "activity", "identity", "mood",
                    "environment", "meta"]
    proposition: str                     # the assertion in natural language, stable across ticks

    # Calibrated belief
    posterior: float                     # P(claim=True | evidence_t), in [0, 1]
    prior_source: Literal["maximum_entropy", "jeffreys", "reference",
                          "constraint_narrowed", "empirical"]
    prior_provenance: str                # YAML reference to prior_provenance record

    # Evidence + dynamics
    evidence_sources: list[EvidenceRef]  # signal names that contributed this tick
    last_update_t: float                 # monotonic timestamp of the last posterior update
    temporal_profile: TemporalProfile    # hysteresis / HMM / BOCD parameters (see §7)

    # Composition
    composition: ClaimComposition | None # None if atomic, else BN factorization (see §8)

    # Surface integration
    narration_floor: float               # per-surface threshold; below → render as UNKNOWN
    staleness_cutoff_s: float            # above → drop claim rather than report stale posterior
```

A `Claim` is not a snapshot — it is a handle to a live posterior. A single `ClaimEngine` instance per `Claim.name` holds the current posterior, the hysteresis state, the HMM/BOCD trailing state, and the log-odds sum; it writes the serialized `Claim` to `perception-state.json` every tick alongside `presence.probability`.

This is the sister schema to `CapabilityRecord` (recruitment) and `GroundingProfile` (grounding-acts). Together they form Hapax's calibration trinity: what the system _can_ do (CapabilityRecord), what it _has the standing_ to do (GroundingProfile), and what it _knows_ (Claim).

`PresenceEngine` becomes a `ClaimEngine` instance for `name="operator_present"`. `VinylSpinningEngine`, `MusicPlayingEngine`, `OperatorWorkingEngine`, `OperatorDJingEngine` are siblings — all writing posteriors to the same sidecar.

---

## 4. Prior derivation from invariants

Ad-hoc priors are the epistemic antipattern the operator's directive forbids. Any inferential procedure, including refusal to commit, is equivalent to _some_ probability assignment over the hypothesis space (Jaynes, 1957; Berger, 2006). The question is whether the assignment is derivable from invariants or hand-waved.

Hapax-council already has four layers of invariant available for prior derivation:

1. **Constitutional axioms** (`axioms/registry.yaml`): `single_user` (exactly one operator; no concurrent operator possible), `executive_function`, `corporate_boundary`, `interpersonal_transparency`, `management_governance`.
2. **Physical-world preconditions**: needle-on-platter ∧ amp-on ∧ audio-signal-present ≡ vinyl-playing. Presence-requires-body. Audio-requires-source. These are _causal_ invariants — they collapse p to 0 when violated.
3. **Hardware structure**: six cameras at 720p, specific Pi fleet placements, MIDI transport from OXI One, contact mic on PreSonus Input 2. These _restrict the evidence graph_.
4. **Operator-referent policy invariants**: four equally-weighted non-formal referents, sticky-per-utterance. A discrete prior.

For every new claim, the prior-derivation procedure is:

1. **Enumerate structural commitments bearing on the claim.** List the axioms, physical preconditions, and hardware invariants relevant to `claim.name`. Example for `music_is_playing`: physical (needs audio signal ∧ source-connected); hardware (signal must reach the mixer on one of vinyl/YouTube/SoundCloud/local-player inputs); axiomatic (`single_user` → no multi-operator distributed play).
2. **Compute the unconstrained reference prior.** Apply Jeffreys (`π(θ) ∝ √det I(θ)`) or Berger-Bernardo reference prior to the parameter space `Θ_full`. For binary claims, this is typically `Beta(½, ½)` (Jeffreys) or a `Beta(1,1)` uniform fallback.
3. **Apply constraint-based narrowing.** Restrict to `Θ_C ⊂ Θ_full` where structural facts hold. Implementation: `π(θ) = π_ref(θ) · 𝟙[θ ∈ Θ_C] / Z`. For `music_is_playing` with audio-signal-present = False, the indicator kills the prior — `p(music_is_playing) ≡ 0` by causal precondition.
4. **Apply transformation-group symmetry.** If the claim has natural invariances (time-translation, operator-frame rotation), enforce them on `π` via Jaynes' transformation-group method.
5. **Document the derivation.** Store a `prior_provenance.yaml` with axioms cited, invariants used, and `π`'s closed form. CI rejects any `Claim` whose prior cannot be reconstructed from the record alone.

### Worked example: `track_X_is_playing_on_vinyl`

Invariants enumerated:
- _Physical_: needle-on-platter ∧ amp-on ∧ audio-signal-energy > τ. Without these, `p(vinyl_track=X) ≡ 0`.
- _Hardware_: Pi-6 IR camera images turntable zone Z_TT; cover-art OCR comes from Z_TT only.
- _Axiomatic_: `single_user` → one operator; no concurrent vinyl operation possible.

Unconstrained reference: uniform over the operator's ~2400-record vinyl library, `π_ref(X) = 1/2400`.

Constraint narrowing: restrict to records with current cover-match ∧ platter-rotation-detected. This collapses to a small set `S_t` at time t.

Posture distinction — _not hand-coded_, falls out of the physical-precondition invariant:
- `p(track=X | cover_visible, hand_at_synths) ≈ stale-state prior` — cover visible but operator not engaging turntable; the causal-precondition term is weakened; prior on "playing now" decays.
- `p(track=X | cover_visible, hand_on_turntable) ≈ active-state prior` — needle-engagement plausible; prior concentrates on X.

The MF DOOM failure mode in priors-from-invariants terms: the compositor asserted `p = 0.85` on the splattribution text based on the LLM identifier's self-report alone, with _no_ physical-precondition narrowing. The correct posterior, given `ir_hand_zone = "synth-left"` and no audio-signal evidence, is `p(track_X_playing) ≪ 0.85`. The narration should never have fired.

---

## 5. Likelihood-ratio methodology

PresenceEngine's 14 LRs (desk 18×, keyboard 17×, midi 45×, etc.) are hand-calibrated from the 2026-03-17 live run. They are documented in `CLAUDE.md § Bayesian Presence Detection` without provenance. Commit history shows reactive correction of observed failures, not systematic derivation. This is tolerable only because PresenceEngine has been in production long enough to debug empirically; generalization to 60+ claims cannot tolerate hand-waving.

Adopt a five-source LR derivation taxonomy, documented per signal in an `LRDerivation` record stored in `agents/<engine>/lr_registry.yaml`:

1. **Calibration study**: log signal + ground-truth claim state over ≥1 week; compute sensitivity `sens = TP/(TP+FN)`, specificity `spec = TN/(TN+FP)`; derive `LR+ = sens/(1-spec)`, `LR- = (1-sens)/spec`; report 95% Wilson confidence interval. Sample-size-aware: <50 cases produce unstable LR estimates.
2. **Calibrated classifier**: temperature-scale the upstream classifier (Guo et al., ICML 2017) on a held-out set by NLL; the rescaled output `p̂` yields `LR(x) = p̂(x) / (1-p̂(x)) × (1-π)/π`. Cranmer et al. (arXiv 1506.02169): any well-calibrated discriminator approximates the LR between two distributions.
3. **Physical model**: derive LR from sensor physics. Example: contact mic surface-coupling rejects airborne noise by construction; `P(contact_signal | desk_activity)/P(contact_signal | ambient)` follows from acoustic impedance mismatch.
4. **Expert elicitation (SHELF)**: O'Hagan et al., _Uncertain Judgements_ (2006). Quartile-fixing and roulette methods, two rounds, private-then-revealed. Preferred over direct LR elicitation since humans are poorly calibrated on ratio scales but reasonable on probability quartiles.
5. **Online recalibration**: replay logged signals against a claim-state proxy (operator correction, downstream consistency check); emit drift warnings when LR shifts >2× from registry.

Every signal in every `ClaimEngine` has a mandatory `LRDerivation` record with source category, estimation procedure, data/model reference, conditional-independence audit (which signals are likely correlated under `H₁`? apply discount factor or fold into a composite signal), and positive-only vs bidirectional declaration. CI rejects PRs that mutate LRs without updating the derivation block.

### Worked example: `ir_hand_zone == "turntable"` for `vinyl_is_playing`

`H₁ = vinyl-playing; H₀ = vinyl-not-playing`. Signal definition: `ir_hand_zone == "turntable" ∧ ir_motion_delta > 0.05` for ≥1 tick within last 60s.

Source: physical model + thin calibration. Operator interacts with the turntable almost exclusively when starting, flipping, or stopping a record; most of a side has no hand interaction.
- `P(signal | H₁) ≈ 0.35` (coverage low because most of a side is hands-off)
- `P(signal | H₀) ≈ 0.02` (rare but nonzero: cleaning, browsing)
- `LR+ = 0.35 / 0.02 ≈ 17.5` — positive-only (absence is steady-state during a side, not evidence against).

Registry note: confirm via 14-day vinyl-state log scraped from `MidiClock` + turntable preamp gain.

---

## 6. Temporal dynamics

PresenceEngine's hysteresis — `enter_threshold = 0.7` sustained 2 ticks, `exit_threshold = 0.3` sustained 24 ticks — is formally a two-threshold Schmitt trigger over a recursive Bayesian log-odds posterior, gated by a dwell-time integrator. The 12:1 tick asymmetry encodes an asymmetric loss function: false-AWAY is cheaper than false-PRESENT for the operator-present claim. Generalization requires per-claim temporal profiles reflecting per-claim loss asymmetry.

**Recommended hybrid framework**:

Every `ClaimEngine` runs a 3-state HMM `{ASSERTED, UNCERTAIN, RETRACTED}` with claim-specific asymmetric dwell counters (`k_enter`, `k_exit`) and Schmitt-style entry/exit thresholds. Transitions are deterministic conditional on accumulated evidence. For **volatile claims** (music, conversation, room occupancy) layer Bayesian online changepoint detection (Adams & MacKay 2007) on top: when the run-length posterior `r_t` collapses to small values, accelerate the dwell counter to enable rapid retraction at genuine transitions.

**Cost-asymmetry inversion**: presence's pattern (fast-enter, slow-exit) is _not_ the universal pattern. For `music_is_playing`:

| Parameter | Value | Justification |
|---|---|---|
| `enter_threshold` | **0.85** | Higher than presence (0.7) — false assertion is catastrophic (MF DOOM bug) |
| `exit_threshold` | **0.40** | Moderate — track natural decay without thrashing |
| `k_enter` | **8 ticks (~2s)** | Reject transients; demand sustained spectral content |
| `k_exit` | **4 ticks (~1s)** | Faster than enter — cost asymmetry inverts presence's |
| BOCD hazard | **1/180 (~3-min expected run)** | Typical track length |

Music enters slowly (cost of false-assertion dominates); leaves quickly (cost of false-sustain dominates, since Hapax narrates phantom audio). Presence leaves slowly (cost of false-AWAY dominates because grounding-state decays). The asymmetry is _derived from the claim's downstream narration risk_, not guessed.

**Integration with grounding-acts T4**: Jemeinigkeit requires claim stability — a grounding act cannot be asserted and retracted ticks later. Temporal dynamics machinery enforces minimum stability window before assertion enters common ground. Stability-before-assertion replaces stability-by-luck.

---

## 7. Composition calculus

`PresenceEngine` handles a single atomic posterior via log-odds over 14 conditionally-independent signals. Generalization requires compound claims: "music is playing" = disjunction over sources (vinyl ∨ youtube ∨ local-player ∨ soundcloud); "operator is DJing" = conjunction (present ∧ hand_on_turntable ∧ vinyl_playing); "operator is working" = present ∧ keyboard_active ∧ screen_looking.

**Recommended framework**: layered Bayesian network over `Claim` nodes.

- **Disjunctions over independent sources** → noisy-OR. `P(music | sources) = 1 − ∏(1 − pᵢ · sᵢ)`. Linear parameters (per-source leak), learnable from labeled livestream segments.
- **Conjunctive compound claims** → explicit AND nodes parameterized as noisy-AND, or small CPTs (≤3 parents = ≤8 entries, tolerable).
- **Shared evidence** (IR hand zone informing both `vinyl_playing` and `operator_DJing`) → single shared parent node with multiple child consumers. The junction tree algorithm's running-intersection property mathematically prevents double-counting.
- **Sub-claims as nodes**: `vinyl_playing` becomes a probabilistic node, not a Boolean; children consume the posterior; thresholding happens only at surface gates.
- **Inference**: `pgmpy` (junction tree exact inference) for the ≤30-node graph; approximate sampling reserved for post-tractability expansion.

Rejected alternatives:

- **Markov Logic Networks** (Richardson & Domingos 2006) — overkill; requires MCMC, grounds over finite domain.
- **Probabilistic Soft Logic** — t-norm semantics are fuzzy-truth, not probabilistic.
- **Dempster-Shafer** — Zadeh's counterexample (two doctors, disjoint diagnoses, common fallback diagnosis wrongly becomes certainty) disqualifies; cameras + IR sensors will routinely conflict.
- **Subjective logic** (Jøsang) — useful for trust networks; operators assume pairwise independence, which fails on shared evidence.

### Worked example: `music_is_playing`

```
P(music_playing, vinyl, youtube, sc, midi_play, beat_rate, yt_audio, sc_audio, ir_hand_turntable)
  = P(midi_play) · P(beat_rate)
  · P(vinyl | midi_play, beat_rate, ir_hand_turntable)   [noisy-AND with leak]
  · P(yt_audio) · P(youtube | yt_audio)
  · P(sc_audio) · P(sc | sc_audio)
  · P(music_playing | vinyl, youtube, sc)                [noisy-OR]
  · P(ir_hand_turntable)
```

`ir_hand_turntable` enters once as a shared parent of `vinyl` (and elsewhere of `operator_DJing`); the junction tree handles d-connection without double-counting.

---

## 8. Prompt integration

The LLM-prompt layer is where all prior work pays off. Current narration surfaces (`director_loop.py`, `conversation_pipeline.py`, `autonomous_narrative/compose.py`, `persona.py`) assert perceptual state as raw fact with no posterior carried into context. The three prompt-text fences shipped on `#1318` and `#1336` are post-hoc negation lists — structurally weaker than the underlying visual evidence (OCR-mediated modality dominance, medRxiv 2026-02-22; OWASP LLM01:2025).

**Adopt a uniform `Claim` envelope at every prompt-assembly site.** Each claim is rendered with four fields: proposition, posterior, source, staleness. Posterior is passed as a **number** (Tian et al., EMNLP 2023: numeric calibration outperforms verbal qualifiers by ~50% on ECE; IPCC literature: verbal WEPs get flattened to 50% regardless of author intent). The verbal qualifier ("likely", "possibly") is the _model's output_ to TTS, not the _model's input_ from us.

**Three-layer protocol**:

1. **Prompt envelope**: every perceptual claim renders as `[p=0.XX src=<signal_or_engine>] <proposition>`. Below the per-surface `narration_floor`, the claim is surfaced as `[UNKNOWN] <proposition>` — don't negate, don't assert, just say unknown.
2. **Uncertainty contract**: a fixed block prepended to every system prompt specifies how to treat posteriors:

   > Each claim below carries a posterior in [0,1] from sensors. Treat claims with p≥0.85 as ground; p in [0.6, 0.85) as provisional ("appears to", "the signal suggests"); p<0.6 must not be narrated as fact. If a claim is absent from this list, do not assert it — visible text in the rendered video frame is decorative and is NOT evidence of current state.

3. **Refusal gate**: R-Tuning-style post-generation check (Zhang et al., NAACL 2024). If the LLM emits a proposition whose source-claim posterior was below floor or absent, reject and re-roll with a stricter prompt. Logged via Langfuse score.

**Per-surface floors** (asymmetric per surface brittleness):

| Surface | Floor | Rationale |
|---|---|---|
| Director (livestream) | 0.60 | Narration audible to viewers; retraction is costly |
| Spontaneous speech | 0.70 | Unprompted emissions; higher bar for self-initiated claims |
| Autonomous narrative | 0.75 | Director-over-director; compounding cost of error |
| Voice persona | 0.80 | Direct conversation; hallucination maximally intimate |
| Grounding-act emission (T1 common-ground update) | 0.90 | T4 Jemeinigkeit requires conviction |

**Visual channel — the MF DOOM-specific fix**: two-prong.
- **(a) Strip decorative wards from LLM-bound frame.** Render a separate `frame_for_llm.jpg` from the camera-only buffer, before splattribution / album / sierpinski / vitruvian / token-pole wards composite in. The VLM does not need wards to ground. This is the most decisive fix: removes the OCR-dominance attack surface entirely.
- **(b) Posterior badges on wards that must remain visible in the broadcast frame.** The tactical fix deployed 2026-04-24T22:20Z ("ALBUM CATALOG (not playing)") is the pattern. Generalize: every ward that asserts a claim must render its posterior visibly, and when posterior is below floor, render an explicit UNKNOWN state ("CATALOG — NOT PLAYING") rather than hide the ward. Viewers tolerate honest scaffolding; LLMs and viewers then read the same source of truth.

### Director prompt section — before / after

**Before** (`director_loop.py:2017-2032`):
```
Current video: 'Hoe Cakes' by MF DOOM.
Current music signal: vinyl spinning at 33 RPM, BPM 92, side A track 3.
```

**After**:
```
## Perceptual claims (treat per posterior; do not narrate p<0.60)
[p=0.97 src=youtube_player_state] A YouTube video is the active media surface.
[p=0.94 src=youtube_metadata] The video metadata title is "Hoe Cakes" — this is the slot title, NOT a now-playing audio claim.
[p=0.88 src=vinyl_rpm_sensor] Turntable platter rotating ~33 RPM.
[p=0.31 src=audio_fingerprint] Audio fingerprint matches "Hoe Cakes" weakly — DO NOT assert as currently playing.
[UNKNOWN] Authoritative now-playing track. Narrate around the music as scene, not as identified work.
```

---

## 9. Implementation phases

Migration is staged to avoid a big-bang rewrite and to let PresenceEngine stand as the working reference throughout.

**Phase 0 — claim scaffolding (~500 LOC)**
- `shared/claim.py`: `Claim`, `ClaimEngine`, `LRDerivation`, `PriorProvenance`, `TemporalProfile`, `ClaimComposition` Pydantic schemas.
- `agents/hapax_daimonion/lr_registry.yaml`: initial entries for PresenceEngine's 14 signals with their existing LRs backfilled into `LRDerivation` records (source: "calibration study, 2026-03-17 live run"); each gets a provenance stub so the registry is populated before any new claim lands.
- CI rule `HPX002` (sister to `HPX001`): rejects any `Claim(...)` constructor without an `LRDerivation` registry entry for its signals.
- Kill-switch env flag `HAPAX_CLAIM_ENGINE_BYPASS=1` restores pre-Bayesian behavior on any claim.

**Phase 1 — refactor PresenceEngine into `ClaimEngine[bool]`**
- Extract the log-odds math, hysteresis state machine, positive-only signal handling into `ClaimEngine[T]`. PresenceEngine becomes a one-liner parameterization.
- Regression pin: `presence.probability` output bit-identical to pre-refactor for 100 tick-replay traces.

**Phase 2 — migrate vinyl/music cluster**
- `VinylSpinningEngine` — atomic `ClaimEngine[bool]` with signals `ir_hand_turntable_zone`, `turntable_rpm_sensor`, `audio_signal_present`, `cover_visible`, `operator_override_flag`. Per §5 methodology for LRs.
- `MusicPlayingEngine` — compound noisy-OR over `vinyl_playing`, `youtube_audio_active`, `soundcloud_playing`, `local_player_playing`. Wrapped in the `ClaimComposition` BN scaffold.
- Retire `_vinyl_is_playing()` as a Boolean; downstream consumers read `VinylSpinningEngine.posterior`.
- Retire the ungated `_curated_music_framing()` fall-through; the director prompt now renders the MusicPlayingEngine posterior.

**Phase 3 — frame-for-llm split**
- Compositor publishes `/dev/shm/hapax-compositor/frame_for_llm.jpg` from the camera-only buffer, before any Cairo ward composites. Director LLM input switches to this.
- Broadcast frame unchanged (wards still visible to viewers).
- Per-ward posterior-badge render (generalization of the 2026-04-24T22:20Z splattribution fix).

**Phase 4 — prompt envelope**
- `shared/claim_prompt.py`: `render_claims(claims: list[Claim], floor: float) -> str` produces the `[p=X src=Y] proposition` block.
- Each narration surface (director, spontaneous-speech, autonomous-narrative, persona) migrates to consume `render_claims(...)` with its surface-specific floor.
- Uncertainty contract block prepended to every system prompt.

**Phase 5 — refusal gate**
- Post-generation LLM-output check: parse emitted propositions against `Claim` registry; reject + re-roll if any below-floor claim asserted as fact. Langfuse score `claim_discipline`.

**Phase 6 — migrate remaining ~55 claims**
- Activity claims (`operator_working`, `operator_DJing`, desk activity).
- Identity claims (`speaker_is_operator` — already half-Bayesian in presence fusion).
- Mood claims (stimmung dimensions — each becomes a `ClaimEngine[float]` with continuous posterior).
- System/meta claims (degraded, consent-state — even these benefit from posterior framing, e.g. `P(consent_gate_fail_closed_is_correct | fail_signal)`).

**Phase 7 — grounding-acts integration**
- T1-T8 tests become posterior interrogations (§2 of this doc):
  - T1 posterior ≥ surface-specific common-ground threshold
  - T4 Jemeinigkeit requires `P(this-act-is-mine) ≥ τ_mineness` at each grounding emission
  - T7 grounding-provenance records carry per-element strength (not just presence/absence), closing the FINDING-X 54% empty-provenance rate

---

## 10. Validation metrics

- **Emissions without posterior**: currently ~59 of 60 claims. Target: 0.
- **Grounding-act emissions with empty provenance** (FINDING-X baseline: 54%). Target: <5%.
- **Hallucinated-claim rate** (operator-flagged post-hoc). Track per-surface; target: declining week-over-week.
- **Posterior-calibration ECE** per `ClaimEngine`: via Tian et al. protocol (hold-out test, model-asked confidence vs actual). Target <0.1.
- **LR-registry drift alarms**: monthly recalibration job flags LR shifts >2×. Target: zero uninvestigated drift.
- **Per-surface refusal rate**: how often the R-Tuning gate rejects an emission. Target: stable; spiking = upstream miscalibration.

---

## 11. Open questions

1. **Continuous vs binary claims.** Mood/stimmung dimensions are currently scalars; fitting them into the `ClaimEngine[bool]` frame flattens them. `ClaimEngine[float]` with posterior over the continuous value (Gaussian with mean + variance?) may be the right generalization — at what cost to the existing log-odds simplicity?
2. **LR elicitation for new claim types.** First iteration falls back to SHELF elicitation per signal. When is it cost-effective to invest in a calibration-study experiment? Proposed heuristic: any claim that ever reaches a narration surface crosses the calibration-study threshold.
3. **Hazard rate calibration for BOCD.** Hand-calibrated per claim type; could be learned from operator-correction events. How many corrections before the hazard estimate is stable?
4. **Cross-claim correlation**. Correlations between e.g. `keyboard_active` and `desk_active` under operator-present violate conditional independence assumed by naive log-odds. BN structural learning (Chow-Liu, NOTEARS) could discover these, at the cost of occasional refitting.
5. **Grounding-provenance strength semantics.** Does per-element strength interact with the existing substitutability lattice (grounded_local vs outsourced_by_grounding vs delegated_cloud vs mechanical)? Probably: low-strength grounding-provenance for a "grounded_local" capability means Hapax should refuse the capability this tick, which is a new refusal surface the Adjudicator must handle.
6. **Retraction and common ground.** If a claim is retracted after having been narrated, what happens to the listener's common ground? T1 predicts: retraction requires explicit meta-communication, not silent drift. This is a research-paradigm call, not an implementation detail.

---

## 12. Summary

Hapax asserts ~60 perceptual claims; only one is calibrated. The MF DOOM hallucination is a single pathology in a systemic absence of posteriors. Universal Bayesian claim-confidence is not an addition to Hapax's theoretical lineage; it is the formalization the lineage was already silently calling for. Six lineages (predictive processing, autopoiesis, Dreyfus, Clark-Brennan, Sperber-Wilson, Austin) converge on it. T1-T8 grounding-acts already presuppose it. Universal Bayesian inference is Hapax's next structural move, not its first.

The architecture reduces to four components with workable scope:
1. **`Claim` schema + `ClaimEngine[T]`** (PresenceEngine generalized — §3, §4 of Phase 1)
2. **Prior-from-invariants + LR-registry methodology** (§4 + §5; CI-enforced)
3. **Temporal dynamics** — HMM + asymmetric-dwell + BOCD per claim (§6)
4. **Composition calculus** — Bayesian network with noisy-OR/AND, junction tree (§7)

And one propagation layer:

5. **Prompt envelope + refusal gate + frame-for-llm split** (§8)

Seven phases, staged so PresenceEngine stays authoritative throughout. The MF DOOM bug is retired structurally in Phase 2 (VinylSpinningEngine posterior replacing `_vinyl_is_playing` Boolean) and Phase 3 (frame-for-llm split removing the OCR-dominance attack surface). Every subsequent hallucination is either caught at the refusal gate or — increasingly — never forms, because the upstream posterior encoded the uncertainty that the fence had been retroactively trying to name.

---

## Sources

Assembled across eight parallel research agents. Full bibliographies:

**Existing infrastructure audit**: PresenceEngine, AffordancePipeline, BOCPD at `agents/bocpd.py`, follow-mode confidence.

**Prior theory**: Jaynes 1957, Jeffreys 1946, Berger-Bernardo 2009, Solomonoff 1964, Stark 2015, Presman & Xu 2023, Drory 2015.

**LR methodology**: StatPearls NBK557491, Akobeng PMC2556590, Guo et al. arXiv 1706.04599, Cranmer et al. arXiv 1506.02169, O'Hagan et al. _Uncertain Judgements_ 2006, CSAFE LR guidance, forensic-Bayesian literature (Morrison, Pearl 1982).

**Temporal dynamics**: Adams & MacKay 2007 (BOCPD), Wald SPRT, HMM/Viterbi, Aalto speech-processing book, EURASIP 2022 speech/music detection.

**Prompt integration**: Tian et al. EMNLP 2023 (Just Ask for Calibration), Lin Hilton Evans 2022, Kamath Jia Liang ACL 2020, Zhang et al. NAACL 2024 (R-Tuning), AbstentionBench 2025, Tanneru et al. vPGM arXiv 2406.05516, OWASP LLM01:2025, medRxiv 2026-02-22 OCR-mediated modality dominance, CroPA CVPR 2024.

**Composition**: Nilsson 1986, Richardson & Domingos 2006 MLN, Bach et al. JMLR 2017 PSL, Zadeh 1986 counterexample to Dempster-Shafer, Jøsang subjective logic, Pearl Bayesian networks + noisy-OR.

**Theoretical alignment**: Clark _Surfing Uncertainty_, Hohwy _The Predictive Mind_, Friston Markov-blankets, Thompson _Mind in Life_, Dreyfus _Skillful Coping_, Clark & Brennan 1991 "Grounding in Communication", Sperber & Wilson relevance theory, Heidegger _Being and Time_ (Jemeinigkeit), Austin _How to Do Things with Words_.
