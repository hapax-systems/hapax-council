# Voice Transformation Tier Spectrum: Kokoro → Evil Pet → S-4

**Date:** 2026-04-20
**Register:** Scientific, operator-facing
**Scope:** A named tier ladder on the clear-and-distinct ↔ muddy-and-indistinct axis for Hapax's TTS voice running through the Evil Pet + S-4 chain. Sits *above* the 9-dimension `vocal_chain.py` machinery and *below* the director/programme recruitment surface. Each tier is a single operator-meaningful macro that resolves to a full CC preset via the existing dimension → CC piecewise-linear mapping.

**Companions:**
- `docs/research/2026-04-19-evil-pet-s4-base-config.md` §3 — base knob positions and CC map
- `agents/hapax_daimonion/vocal_chain.py` — 9-dim → CC breakpoint machinery
- `docs/research/2026-04-20-vinyl-broadcast-mode-d-granular-instrument.md` §7.2 — parallel 9-dim vinyl-source scheme; structural template for this doc
- `shared/speech_safety.py`, `shared/governance/monetization_safety.py` — governance gates
- `shared/affordance.py` — `CapabilityRecord` / `OperationalProperties` shape (incl. `monetization_risk`, `consent_required`)
- `shared/programme.py` — Programme-level opt-ins and capability biases

---

## §1. The continuum

### §1.1 Framing

Hapax's TTS voice is Kokoro 82M (CPU) routed MOTU 24c → Evil Pet (voice-safe filter/saturator/reverb chain) → Torso S-4 (Ring filter + Deform color + Vast delay/reverb). The existing base config keeps the voice intelligible by design: granular re-synthesis clamped off, LFOs parked, master wet/dry floor at 40% dry. Correct for "Hapax narrates while the operator makes beats." Not sufficient for every register the livestream hits.

The livestream carries at least five narrative modes: direct address (clarity obligatory), ambient color (words carry mood), memory/echo (texturally distinct from present-tense), dream/drift (half-legibility is the point), abstract sound (voice as sonic mass). The current 9-dim chain can in principle reach all five by coordinated manipulation of ten knobs. The operator needs one button, not ten.

A **tier spectrum** collapses the reachable state-space into seven operator-facing macros. Each tier is a point in the 9-dim vector; activating a tier writes the vector; `vocal_chain.py` emits the CCs; Evil Pet + S-4 reconfigure. One gesture, full chain.

### §1.2 The seven tiers

| # | Name | Register | Intelligibility floor |
|---|---|---|---|
| 0 | **UNADORNED** | Dry Kokoro, Evil Pet bypass, S-4 bypass. Debug / direct address at extreme consent moments. | 1.00 |
| 1 | **RADIO** | Bandpass-coloured, lightly compressed, no reverb tail. Announcement / headline register. | 0.95 |
| 2 | **BROADCAST-GHOST** | Present-tense narration with room reverb and mild harmonic enrichment. **Default livestream register.** | 0.90 |
| 3 | **MEMORY** | Longer tail, mild pitch jitter, warmer tone. Hapax recalls. Words legible with slight effort. | 0.70 |
| 4 | **UNDERWATER** | Low-pass + detune + heavy tail. Words present as rhythm/mood; individual words recoverable but no longer the point. | 0.45 |
| 5 | **GRANULAR-WASH** | Position spray + short grains + dense cloud. Voice becomes *texture*. Recognisable-as-Hapax but not as-language. | 0.15 |
| 6 | **OBLITERATED** | Full granular engagement, reverb drowning, pitch scrambled. No speech-layer content survives; pure sonic mass. | 0.00 |

Intelligibility floor is a theoretical estimate: at the tier's nominal CC preset, the fraction of phonemes a prime listener can recover. TIER 0 = 100%, TIER 6 = 0%.

### §1.3 Why seven, not five or ten

- **T0 is load-bearing.** A true bypass is needed for consent-critical moments, debug, and governance fallback. Cheap to include.
- **T6 is the sonic-texture endpoint.** Cutting at T5 would conflate "voice as texture but still Hapax-attributable" with "voice indistinguishable from a shader." Distinct governance regimes.
- **Five interior tiers.** Radio and default are distinct (dated vs timeless); memory and underwater are distinct (warm/rhythmic vs spatial/detuned); wash and obliterated are distinct (points at Hapax vs points at a shader). Fewer tiers would force the operator to choose between registers that are in use.
- **Seven is Miller's span with one spare.** Beyond seven the ladder becomes over-specified; recall cost goes up faster than expressive gain.

### §1.4 Narrative moments per tier

- **T0 UNADORNED** — consent confirmation, system-state announcements the operator must hear verbatim, debug, governance disclosure.
- **T1 RADIO** — headlines, programme-boundary callouts, chat shout-outs, timestamp markers.
- **T2 BROADCAST-GHOST** — default. Hapax narrates operator work in near-real-time.
- **T3 MEMORY** — recalled facts, episodic callbacks to prior sessions, Qdrant-retrieved operator-patterns.
- **T4 UNDERWATER** — imagination-loop output, SEEKING-stance wanderings, stimmung-coloured reflection, post-decision calm.
- **T5 GRANULAR-WASH** — aesthetic moments where Hapax is *part of* the track; voice as texture layered over the beat.
- **T6 OBLITERATED** — ritualised transitions: the drop, an ANT-stance collapse, the HOMAGE culmination. Rare, governance-gated.

---

## §2. CC presets per tier

A single matrix. Rows are the (device, CC#, param) tuples touched by the tier ladder; columns are the seven tiers. Values are absolute 0–127 MIDI CC values. `—` means "hold at base config from §3/§4 of the base-config doc." Channel 0 = Evil Pet, channel 1 = S-4 Track 1.

| Device | CC | Param | T0 | T1 | T2 | T3 | T4 | T5 | T6 |
|---|---|---|---|---|---|---|---|---|---|
| EP | 40 | Mix (wet/dry) | 0 | 60 | 60 | 70 | 90 | 95 | 127 |
| EP | 91 | Reverb amount | 0 | 10 | 30 | 55 | 60 | 60 | 100 |
| EP | 93 | Reverb tail | 0 | 20 | 40 | 65 | 70 | 70 | 127 |
| EP | 92 | Reverb tone | 64 | 80 | 64 | 78 | 45 | 55 | 55 |
| EP | 39 | Saturator amount | 0 | 50 | 30 | 55 | 40 | 45 | 100 |
| EP | 84 | Saturator type | 0 | 0 | 0 | 0 | 0 | 30 | 110 |
| EP | 70 | Filter freq | 127 | 70 | 70 | 75 | 30 | 65 | 50 |
| EP | 71 | Filter resonance | 0 | 40 | 25 | 30 | 45 | 35 | 80 |
| EP | 80 | Filter type | BP | BP | BP | BP | **LP** | BP | BP |
| EP | 96 | Env→filter mod | 0 | 30 | 45 | 60 | 70 | 60 | 90 |
| EP | 44 | Pitch (center=64) | 64 | 64 | 64 | 70 | 52 | 80 | 100 |
| EP | 11 | **Grains volume** | 0 | 0 | 0 | 0 | 0 | **90** | **127** |
| EP | 85 | Overtone volume | 0 | 0 | 0 | 0 | 0 | 0 | 40 |
| EP | — | Position (TBD) | — | — | — | — | — | drift | max |
| EP | — | Size (short ↑) | — | — | — | — | — | short | 5 ms |
| EP | — | Cloud / density | — | — | — | — | — | dense | max |
| EP | — | Spray | — | — | — | — | — | max | max |
| S4 | 103 | Deform wet | 0 | 80 | 70 | 70 | 70 | 75 | 90 |
| S4 | 95 | Deform drive | 0 | 40 | 30 | 45 | 50 | 70 | 100 |
| S4 | 96 | Deform compress | 20 | 90 | 70 | 70 | 95 | 80 | 80 |
| S4 | 98 | Deform crush | 0 | 0 | 0 | 0 | 0 | 60 | 110 |
| S4 | 79 | Ring cutoff | 64 | 50 | 60 | 70 | 35 | 60 | 50 |
| S4 | 80 | Ring resonance | 0 | 0 | 20 | 30 | 25 | 25 | 55 |
| S4 | 82 | Ring pitch (center=64) | 64 | 64 | 64 | 72 | 58 | 85 | 100 |
| S4 | 86 | Ring wet | 0 | 0 | 30 | 40 | 40 | 45 | 45 |
| S4 | 114 | Vast reverb amount | 0 | 0 | 30 | 50 | 60 | 70 | 100 |
| S4 | 115 | Vast reverb size | — | — | 60 | 80 | 100 | 100 | 127 |
| S4 | 118 | Vast reverb damp | 80 | 80 | 60 | 50 | 80 | 60 | 40 |
| S4 | 112 | Vast delay amount | 0 | 0 | 40 | 50 | 50 | 55 | 70 |
| S4 | 116 | Vast delay feedback | 0 | 0 | 30 | 40 | 45 | 55 | 70 |
| S4 | 117 | Vast delay spread | 64 | 64 | 64 | 70 | 80 | 90 | 100 |
| S4 | — | Mosaic position (TBD) | — | — | — | — | — | drift | max |
| S4 | — | Mosaic length (short ↑) | — | — | — | — | — | short | 5 ms |
| S4 | — | Mosaic rate | — | — | — | — | — | dense | max |

**Tier identities (the CCs carrying each tier's core move):**

- **T0 UNADORNED** — Mix=0 on Evil Pet; all three S-4 slot wets at 0. Pure dry Kokoro passes through unchanged. Deform compress held at 20 as a courtesy limiter only; no audible processing.
- **T1 RADIO** — Filter BP + resonance tight around 1.8 kHz, heavy Deform compression (CC 96 = 90), zero reverb/delay. Period-style saturator. Tight, punchy, intentionally dated.
- **T2 BROADCAST-GHOST** — The base-config values from the companion doc §3/§4. Published here so the ladder has a canonical default.
- **T3 MEMORY** — Long tail (CC 93 = 65), upward pitch on Evil Pet (CC 44 = 70) and Ring (CC 82 = 72), bright tail (CC 92 = 78), large hall (CC 115 = 80). Recall register.
- **T4 UNDERWATER** — Filter switched to LP and pulled down (CC 70 = 30), downward pitch (CC 44 = 52, CC 82 = 58), cathedral reverb (CC 115 = 100), heavy compression holds body. LP swap is the identity move.
- **T5 GRANULAR-WASH** — Grains Volume = 90 is the identity move. Per-grain pitch scatter, short dense grains, Mosaic engaged on S-4 stage. Voice becomes texture. Unlabeled granular CCs (Position, Size, Cloud, Spray, Mosaic position/length/rate) to be resolved against `mode-d-granular-instrument.md` §7.3 walk-through.
- **T6 OBLITERATED** — Grains at max, bit-crush engaged on both stages (CC 84 = 110 Evil Pet, CC 98 = 110 S-4), resonance screaming (CC 71 = 80), delay feedback ceiling-clamped at 70. Pure sonic mass.

---

## §3. Mapping to vocal_chain.py 9 dimensions

`vocal_chain.py` takes a 9-dim vector `{name: level∈[0,1]}` and emits CCs via piecewise-linear breakpoints. A tier is therefore expressible as a vector; activating a tier = writing the vector = emitting all CCs.

The 9 dims: `intensity`, `tension`, `diffusion`, `degradation`, `depth`, `pitch_displacement`, `temporal_distortion`, `spectral_color`, `coherence`.

### §3.1 The seven tier vectors

```yaml
TIER_0_UNADORNED:
  intensity: 0.0
  tension: 0.0
  diffusion: 0.0
  degradation: 0.0
  depth: 0.0
  pitch_displacement: 0.5   # 0.5 = center, symmetric around no-shift
  temporal_distortion: 0.0
  spectral_color: 0.5       # 0.5 = neutral
  coherence: 0.0            # coherence level 0 = master fully dry

TIER_1_RADIO:
  intensity: 0.60           # saturator present, Deform drive warm
  tension: 0.70             # bandpass pinched, filter resonance up
  diffusion: 0.05           # no reverb
  degradation: 0.25         # period-character saturation
  depth: 0.10               # almost no reverb tail
  pitch_displacement: 0.5
  temporal_distortion: 0.0
  spectral_color: 0.80      # bright (HF-forward)
  coherence: 0.30           # 30% master wet, dry dominant

TIER_2_BROADCAST_GHOST:   # default / base config
  intensity: 0.35
  tension: 0.40
  diffusion: 0.35
  degradation: 0.20
  depth: 0.40
  pitch_displacement: 0.5
  temporal_distortion: 0.30
  spectral_color: 0.55
  coherence: 0.40

TIER_3_MEMORY:
  intensity: 0.55
  tension: 0.50
  diffusion: 0.55
  degradation: 0.35
  depth: 0.65
  pitch_displacement: 0.62  # slight upward bias
  temporal_distortion: 0.45
  spectral_color: 0.75      # brighter, warmer tail
  coherence: 0.60           # more wet, memory-coloured

TIER_4_UNDERWATER:
  intensity: 0.55
  tension: 0.30            # LP-dominant, not pinched
  diffusion: 0.80          # drowning in reverb
  degradation: 0.45
  depth: 0.90              # max depth
  pitch_displacement: 0.35  # downward
  temporal_distortion: 0.65
  spectral_color: 0.25      # dark
  coherence: 0.85           # mostly wet, words submerged

TIER_5_GRANULAR_WASH:
  intensity: 0.75
  tension: 0.55
  diffusion: 0.90
  degradation: 0.70         # granular engine + bit-crush
  depth: 0.80
  pitch_displacement: 0.80
  temporal_distortion: 0.80
  spectral_color: 0.60
  coherence: 0.95           # near-pure wet

TIER_6_OBLITERATED:
  intensity: 1.00
  tension: 0.90
  diffusion: 1.00
  degradation: 1.00
  depth: 1.00
  pitch_displacement: 0.95
  temporal_distortion: 1.00
  spectral_color: 0.70
  coherence: 1.00
```

### §3.2 Interpolation between tiers

Because each tier is a 9-vector, moving between tiers is an interpolation in R^9. A transition from TIER 2 → TIER 4 over 5 s is a linear crossfade of all nine dims; vocal_chain's existing decay-timer machinery already handles level persistence and decay. The tier manager writes a target vector and optionally a ramp time; the CC emitter steps the vector toward target at its debounce rate (20 Hz).

### §3.3 Tier-to-CC provenance

Tiers write the 9-dim vector; `vocal_chain.py` maps dims → CCs. **The tier manager does not write CCs directly.** The §2 table is a human-readable *verification* of what the dim vector should produce, not a second source of truth. Authoritative map is `vocal_chain.DIMENSIONS`. Disagreement between §2 and derived CC values signals a dim-mapping bug or a tier-vector bug — reconcile before shipping.

Exception: **granular CCs** (CC 11 Grains Volume, CC 85 Overtone Volume, Position/Size/Cloud/Spread, Mosaic) are not yet in `vocal_chain.DIMENSIONS`. The existing `density` dim is clamped to 0 per base-config §5.1. T5–T6 require lifting the clamp; Phase 2 of the implementation plan adds a `granular_engagement` dim guarded by programme opt-in, replacing the hard clamp with a consent-gated decision.

---

## §4. Mutual-exclusion semantics

### §4.1 Shared CCs: voice tier ↔ vinyl-source Mode D

The vinyl-broadcast Mode D spec (`mode-d-granular-instrument.md` §7.3) identifies four Evil Pet CCs shared with voice chain: **CC 39 (saturator amount), CC 70 (filter freq), CC 91 (reverb amount), CC 93 (reverb tail)**. Both modes compete for the same MIDI target.

Per the existing §7.6 note in the Mode D doc: only one of `{vocal_chain, vinyl_source}` may write to a shared CC at a time. This already applies to TIERS 0–4.

**TIERS 5–6 introduce a stronger constraint.** Both TIER 5 and Mode D engage the *granular engine* (CC 11 Grains Volume), which is the central identity move for Mode D. Two simultaneous granular streams into the same engine — one granulating Hapax's voice, one granulating vinyl — is physically impossible: the Evil Pet has one granular engine with one buffer. Even if both were writing compatible CCs, the audio source is single-selector (LINE input). Whoever selected LINE last wins; the other is silent.

### §4.2 Formal exclusion rule

```yaml
mutex_groups:
  granular_engine:
    members: [voice_tier.granular_wash, voice_tier.obliterated, vinyl_source.mode_d]
    policy: at_most_one
    resolution: programme_priority
  evil_pet_shared_ccs:   # CC 39, 70, 91, 93
    members: [voice_tier.*, vinyl_source.mode_d]
    policy: at_most_one_writer_per_cc
    resolution: programme_priority
```

Concretely:

1. **When Mode D is active**, voice tier is clamped to TIER ≤ 4. Voice still goes through the chain, but the granular slot is occupied by vinyl-source programme. Voice tier 5/6 attempts from impingements are rejected by the programme-level mutex; the tier manager emits a downgrade event (`tier_clamped_by_mutex`) and writes TIER 4 instead.
2. **When voice TIER 5 or 6 is active**, Mode D cannot engage. An impingement that would normally recruit Mode D is deferred; the director receives a back-pressure signal.
3. **For non-granular shared CCs (39, 70, 91, 93)**, the default is last-writer-wins gated by programme priority. The programme with higher `priority_floor` (see `shared/affordance.py`) wins. If neither has `priority_floor`, the affordance pipeline's activation-level competition resolves it.

### §4.3 Other exclusions

- **TIER 0 vs any active Evil-Pet-based stream effect:** TIER 0 sets Mix to 0 (fully dry). Any effect applied by the Evil Pet is silenced. This is intentional — TIER 0 is a consent-critical path.
- **TIER 6 duration cap:** OBLITERATED is rare and brief. Enforce a default cap of 15 s max continuous duration; on exceed, auto-fallback to TIER 4. Prevents accidental "voice is now just a shader forever" states when an impingement gets stuck.

---

## §5. Governance

### §5.1 Monetization risk per tier

Following the rubric in `shared/affordance.py` (`MonetizationRisk ∈ {none, low, medium, high}`) and the demonetization-safety design:

| Tier | Risk | Reason |
|---|---|---|
| 0 UNADORNED | none | dry TTS; no processing risk |
| 1 RADIO | none | bandpass + compression is standard broadcast treatment |
| 2 BROADCAST-GHOST | none | current base-config is already the default livestream state |
| 3 MEMORY | low | pitch displacement is mild; some aesthetic coloration |
| 4 UNDERWATER | low | submerged voice is aesthetic; intelligibility reduced but no monetization concern |
| 5 GRANULAR-WASH | **medium** | granular re-synthesis creates content that is not recognisable as speech; borders vinyl-Mode-D monetization regime |
| 6 OBLITERATED | **medium** | the voice becomes sonic mass; if ever the master content carrier, could be classified as "not speech" by a Content ID side channel |

TIER 5 and TIER 6 require programme-level `monetization_opt_ins: [voice_tier_granular]` to pass the `MonetizationRiskGate`. Without the opt-in, a director-loop attempt to recruit TIER 5 is filtered out; the tier manager falls back to TIER 4.

### §5.2 Intelligibility floor

Implicit livestream invariant: ≥60% of airtime Hapax is intelligible. T0–T3 satisfy cleanly; T4 borderline; T5–T6 violate.

The tier manager maintains a rolling 5-min intelligibility budget: `Σ (1 - intelligibility_floor) × duration_s`. When the budget exceeds 60 s in any 5-min window, T5–T6 requests are clamped to T4 until the budget decays. Rate limiter, not hard gate; operator can override via `intelligibility_gate_override: true` on the active programme.

### §5.3 speech_safety / consent

`shared/speech_safety.py` governs speech *content* (PII, consent, axiom text) at TTS-generation time — unaffected by tier selection since tiers modulate an already-generated signal.

One new hook: utterances carrying `consent_critical: true` (e.g., "I'm summarising what you said") force T0 regardless of director intent, ensuring consent language reaches the audience uncoloured. The tier manager reads this flag from the speech_safety payload before resolving other inputs.

### §5.4 HARDM (anti-anthropomorphisation)

All seven tiers are signal-honest — they shape envelope, spectrum, spatial placement, grain structure. None adds humanising colour (no breath, no LFO wobble, no performed affect). T5–T6 actively de-humanise the voice into texture. Ladder is HARDM-consistent.

---

## §6. Director integration

The `director_loop` (cross-ref CLAUDE.md "director") chooses a tier per narrative beat based on stance, programme role, and impingement context.

### §6.1 Decision surface

```yaml
voice_tier_router:
  # Stance-primary default mapping
  stance_defaults:
    NOMINAL: 2           # broadcast-ghost
    ENGAGED: 2           # default
    SEEKING: 4           # underwater — wandering is submerged
    ANT: 5               # granular wash — ANT-stance collapse
    FORTRESS: 0          # unadorned — consent-critical
    CONSTRAINED: 1       # radio — tight, punchy, focused

  # Programme-role override
  programme_overrides:
    livestream_director: 2              # default broadcast
    consent_confirmer: 0                # always unadorned
    memory_narrator: 3                  # memory register
    vinyl_commentator: 2                # clear — words describe the track
    sonic_performer: 5                  # voice as material
    HOMAGE_choreographer: 4 → 6         # ramp across the choreography

  # Impingement-type modulation (delta applied to stance default)
  impingement_deltas:
    memory.qdrant_hit: +1               # push toward MEMORY
    imagination.fragment: +1            # push toward UNDERWATER
    stimmung.strain: 0                  # keep current tier
    direct_address_to_chat: -1          # pull toward RADIO
    consent_event: clamp_to_0           # force UNADORNED
    track_drop: burst_to_6_then_4       # 5 s OBLITERATED, then TIER 4

  # Transition ramp times (seconds)
  ramp_defaults:
    between_adjacent: 0.5               # TIER 2 → TIER 3: smooth
    between_distant: 2.5                # TIER 2 → TIER 5: audible transition
    burst_to_6: 0.1                     # instant snap
    fallback_from_6: 3.0                # ease back

  # Duration caps (seconds, auto-fallback enforced)
  duration_caps:
    tier_6: 15
    tier_5: 120
    tier_4: 300                         # no hard cap but favours decay

  # Intelligibility budget (§5.2)
  intelligibility_budget:
    window_seconds: 300
    budget_seconds: 60                  # max (1-floor)*duration in window
```

### §6.2 Resolution order

1. **Consent clamp** — if utterance carries `consent_critical`, force TIER 0. Bypass all else.
2. **Programme override** — if active programme declares a tier, use it.
3. **Mutex check** — if granular engine is held by vinyl-source Mode D, clamp tier ≤ 4.
4. **Intelligibility budget** — if TIER 5 or 6 requested but budget exhausted, clamp to TIER 4.
5. **Monetization gate** — filter out TIERS ≥ 5 if not opted in.
6. **Stance default + impingement delta** — compute base tier from stance, apply deltas.
7. **Ramp** — compute ramp time between current tier and target tier; emit interpolated vectors.

### §6.3 Telemetry

Every tier change emits a `voice_tier_transition` event with `{from, to, reason, ramp_s, clamp_reason?}`. Prometheus counters: `hapax_voice_tier_seconds_total{tier}`, `hapax_voice_tier_clamps_total{reason}`, `hapax_voice_tier_intelligibility_budget_spent`. Langfuse score on tier selection rationale when director routes via LLM.

---

## §7. Recruitment: tiers as CapabilityRecords

Per the unified semantic recruitment model (`docs/superpowers/specs/2026-04-02-unified-semantic-recruitment-design.md`), each tier is a first-class capability with a Gibson-verb description, an embedding, and a governance classification. Director loop recruits them; the pipeline filters by consent + monetization.

### §7.1 CapabilityRecords

Seven `CapabilityRecord` entries, one per tier. All are `daemon="hapax_daimonion"`, `medium="auditory"`, `latency_class="fast"`. Distinctive fields below; full construction follows the `vocal_chain.VOCAL_CHAIN_RECORDS` pattern.

| name | Gibson-verb description | monetization_risk | priority_floor |
|---|---|---|---|
| `voice_tier.unadorned` | Speak-clearly-without-mediation. Dry Kokoro TTS, Evil Pet + S-4 in full bypass. Affords consent-verbatim address, system-state announcement, debug output where every phoneme must reach the listener unprocessed. | none | true |
| `voice_tier.radio` | Announce-headline-in-bandpass-register. Narrow mid-range voice, heavy compression, mild period saturation. Affords programme-boundary callouts, chat shout-outs, moments where punch and dated-broadcast framing carry more than presence. | none | false |
| `voice_tier.broadcast_ghost` | Narrate-present-tense-with-room-depth. Default livestream voice: bandpass-coloured, lightly saturated, small room reverb. Affords continuous real-time narration of operator work without coloration that distracts from words. | none | true |
| `voice_tier.memory` | Recall-episodic-with-warmth-and-drift. Long reverb tail, upward pitch jitter, brighter spectral tail. Affords narration of recalled facts, episodic callbacks, Qdrant-retrieved operator patterns in a register distinct from present-tense work. | low | false |
| `voice_tier.underwater` | Submerge-voice-into-rhythmic-presence. Low-pass dominant, downward detune, cathedral reverb. Affords imagination-loop narration, SEEKING-stance wandering, post-decision stillness where words are present as mood more than content. | low | false |
| `voice_tier.granular_wash` | Dissolve-speech-into-granular-texture. Engage granular engine on Evil Pet + Mosaic on S-4, dense short grains, high spray, pitch scatter. Affords moments where Hapax functions as sonic material within the track rather than as a narrator above it. | medium | false |
| `voice_tier.obliterated` | Collapse-voice-into-pure-sonic-mass. Maximum granular, pitch scatter, reverb saturation, bit-crush. Affords ritualised transitions — the drop, the ANT-stance collapse, the HOMAGE culmination — where the voice ceases to be speech and becomes shader-parameter. | medium | false |

None declares `consent_required=True`; the utterance-level `consent_critical` flag (§5.3) is a separate mechanism forcing TIER 0, not a recruitment gate. `risk_reason` on TIERS 5–6 cites granular re-synthesis + duration-cap + programme opt-in.

### §7.2 Affordance registry wiring

Register the seven records in `agents/_affordance.py` (or `shared/affordance_registry.py`) via the existing `register_capability_records()` pattern used for `vocal_chain.VOCAL_CHAIN_RECORDS`. The Qdrant `affordances` collection ingests the descriptions; the recruitment pipeline scores incoming impingements against all seven.

Each tier's affordance signature expands the existing set:

```python
VOICE_TIER_AFFORDANCES = {
    "voice_register", "narrative_tone", "speech_transformation",
    "broadcast_framing", "sonic_texture", "ritual_transition",
}
```

### §7.3 Recruitment dynamics

- **TIER 0 and TIER 2** carry `priority_floor=True` — always recruitable, always available as fallbacks.
- **TIERS 3–4** have no consent requirement and `monetization_risk=low` — recruited by impingement strength alone.
- **TIERS 5–6** require `monetization_opt_ins` on the active programme. Absent the opt-in, the pipeline filters them out — consistent with the Mode D governance pattern.
- **Mutex** expressed as the `mutex_groups` structure from §4.2; the pipeline sees a group membership and enforces at-most-one.

### §7.4 Hebbian co-occurrence

Track tier-to-stance and tier-to-programme co-occurrence in the same Qdrant `operator_patterns` collection used for other capability learning. After sufficient data, the pipeline develops priors ("SEEKING + imagination fragment → TIER 4 with high confidence") that can short-circuit the director's decision.

---

## §8. Implementation plan

Five phases, sequenced.

### Phase 1 — Type primitives (1 PR)

Add `agents/hapax_daimonion/voice_tier.py`: `VoiceTier` enum (seven members), `TierPreset` frozen dataclass (tier, name, 9-dim vector, intelligibility_floor, monetization_risk, duration_cap_s, ramp_from_adjacent_s), and the seven preset instances from §3.1. Regression: vector shape + monotonic intelligibility ordering (floor strictly decreases T0→T6).

### Phase 2 — Preset catalog + vocal_chain adapter (1 PR)

Extend `vocal_chain.py`: add `VocalChainCapability.apply_tier(tier, ramp_s=...)` which writes the tier's 9-dim vector into `_levels` and fires CCs via the existing `_send_dimension_cc` path. Add new `vocal_chain.granular_engagement` dimension — gated at the capability level by programme opt-in — replacing the `density` hard-clamp. Regression: applying T2 produces CCs matching §2 within ±3.

### Phase 3 — Director hook (1 PR)

Ship `agents/hapax_daimonion/voice_tier_router.py` implementing the §6.1 decision surface. Director emits `voice_tier_intent` per narrative beat; router resolves via the §6.2 order (consent clamp → programme override → mutex → intelligibility budget → monetization → stance default → ramp) and calls `apply_tier()`. Wire Prometheus counters (`hapax_voice_tier_seconds_total`, `hapax_voice_tier_clamps_total`). Integration test: a 10-impingement sequence produces the expected tier trajectory.

### Phase 4 — Governance wiring (1 PR)

Add `IntelligibilityBudgetGate` to `shared/governance/`; register T5/T6 with `monetization_safety.py`; add `consent_critical` flag to speech_safety and plumb it to the router. Integration tests: `consent_critical=True` clamps to T0; T5 without programme opt-in is filtered out; intelligibility budget exhaustion clamps T5 requests to T4.

### Phase 5 — CapabilityRecord registration + Hebbian learning (1 PR)

Register `VOICE_TIER_CAPABILITIES` via the existing `register_capability_records()` path. Ingest descriptions into Qdrant `affordances`. Add tier↔stance and tier↔programme co-occurrence tracking in `operator_patterns`. Ship `hapax-voice-tier {0..6}` CLI as an ops escape hatch. Regression: an impingement "recall prior track from earlier" scores `voice_tier.memory` highest.

---

## §9. Sources

**Voice-register and broadcast framing (T1, T2)**
- Chion, M. (1994). *Audio-Vision: Sound on Screen*. Columbia University Press. Acousmatic voice and voice-over register typology.
- Altman, R. (1992). *Sound Theory, Sound Practice*. Routledge. Voice-as-medium; material presence of broadcast compression.
- Lacasse, S. (2000). "Listen to My Voice: The Evocative Power of Vocal Staging in Recorded Rock Music." PhD thesis, University of Liverpool. Taxonomy of vocal staging (distance, width, envelope) — direct structural ancestor of the tier ladder.

**Hip-hop voice transformation (T3, T4)**
- Schloss, J. G. (2004). *Making Beats: The Art of Sample-Based Hip-Hop*. Wesleyan University Press. Sampling aesthetics and voice-as-material.
- Exarchos, M. (2019). "Hip-Hop Reconstituted: A Study in Production and Voice." *Popular Music* 38(2). Voice-processing continuum in contemporary hip-hop.

**Granular / microsound / vaporwave (T5, T6)**
- Roads, C. (2001). *Microsound*. MIT Press. Canonical granular synthesis reference; grain size + spray are the T5 knobs.
- Demers, J. (2010). *Listening Through the Noise*. Oxford University Press. Granular voice in electronic composition (OPN, Hecker, Lopatin).
- Tanner, G. (2016). *Babbling Corpse: Vaporwave and the Commodification of Ghosts*. Zero Books. Voice-submersion tradition T4–T5 draw on.

**Platform broadcast safety**
- YouTube Creator Academy (2025). *Monetization Policies and Content ID Reference*. https://support.google.com/youtube/answer/1311392
- Smitelli, S. (2017). "Defeating YouTube's Audio Fingerprint." https://scottsmitelli.com/articles/defeating-youtubes-audio-fingerprint/

**Hapax-internal**
- `docs/research/2026-04-19-evil-pet-s4-base-config.md` §3–§5 — base CC map and signal-honest constraints
- `docs/research/2026-04-20-vinyl-broadcast-mode-d-granular-instrument.md` §7 — parallel 9-dim pattern, shared-CC mutex rule
- `docs/research/2026-04-19-demonetization-safety-design.md` — monetization risk rubric
- `agents/hapax_daimonion/vocal_chain.py` — 9-dim → CC machinery
- `shared/affordance.py`, `shared/programme.py`, `shared/governance/monetization_safety.py`
- Project memory: `project_hardm_anti_anthropomorphization.md`, `feedback_consent_latency_obligation.md`
