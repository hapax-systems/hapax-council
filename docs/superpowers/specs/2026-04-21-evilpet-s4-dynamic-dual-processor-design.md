---
date: 2026-04-21
author: delta
register: scientific, neutral
status: design
related:
  - docs/research/2026-04-21-evilpet-s4-dynamic-dual-processor-research.md (research backing this design)
  - docs/research/2026-04-20-evilpet-s4-routing-permutations-research.md (prior static-topology research)
  - docs/superpowers/specs/2026-04-20-evilpet-s4-routing-design.md (prior R1/R2/R3 siloed-routing spec; superseded by this doc for dual-engine scope)
  - docs/superpowers/plans/2026-04-21-evilpet-s4-dynamic-dual-processor-plan.md (implementation plan for this design)
  - shared/evil_pet_presets.py (13 Evil Pet presets)
  - agents/hapax_daimonion/vocal_chain.py (9-dim → CC emitter)
  - docs/research/2026-04-20-mode-d-voice-tier-mutex.md (Mode D mutex — preserved)
  - docs/research/2026-04-20-voice-transformation-tier-spectrum.md (T0..T6 tier ladder — preserved)
supersedes:
  - docs/superpowers/specs/2026-04-20-evilpet-s4-routing-design.md (R1/R2/R3 siloed-routing model; its contracts are subsumed into the D1..D5 dual-engine classes below)
---

# Evil Pet + S-4 Dynamic Dual-Processor Routing — Formal Design

## §1. Purpose

Define the runtime contract for routing audio through Evil Pet and Torso S-4 such that:

1. **Both processors are engaged simultaneously on every broadcast tick** (*maximal*), subject to hardware availability and governance.
2. **Routing decisions shift in response to context** (*dynamic*): stimmung, programme, impingement, ephemeral broadcaster state.
3. **No source reaches broadcast unprocessed** unless a governance-specified bypass path is active (FORTRESS stance, consent-critical utterance, emergency `hapax-audio-reset-dry`).

The design replaces the prior R1/R2/R3 siloed-routing contract (one engine per source class) with a 12-class topology registry (D1..D5 dual-engine + §5.1..§5.7 single-engine carried forward) and a three-layer control-law arbiter (§6) that selects the active topology + presets per tick.

## §2. Scope

**In scope:**

- PipeWire topology for broadcast audio path (14-ch L-12 USB multitrack capture → filter-chain → `hapax-livestream-tap` → OBS).
- Evil Pet preset registry (13 presets in `shared/evil_pet_presets.py`) and its MIDI CC delivery mechanism.
- Torso S-4 scene library (10 scenes, §4.2) and its MIDI program-change / macro delivery mechanism.
- Dynamic audio-routing agent (`agents/audio_router/dynamic_router.py`) and its state-variable inputs, policy layers, and emission outputs.
- Governance gates (consent-critical, monetization opt-ins, Mode D mutex, intelligibility budget, dual-engine anthropomorphization, Ring-2 WARD classifier pre-render).
- Observability (Prometheus counters/gauges, Langfuse events, `router.jsonl` rotation).
- Operator CLI overrides.

**Out of scope:**

- Vinyl turntable hardware characteristics (Korg Handytrax) — handled by existing `agents/hapax_daimonion/vinyl_chain.py`; this design consumes its Mode-D-active signal but does not redesign it.
- Kokoro TTS engine internals — consumed as the S1 source stream without redesign.
- Studio compositor visual surfaces — independent subsystem; only consumes `hapax-livestream-tap` as audio input.
- Rode Wireless Pro receiver compression / pre-processing — hardware, not software-addressable.

## §3. Contracts

### §3.1 Source → Engine contract

Every broadcast-bound audio source (§4 research doc) declares a **default mode** (`dry` or `modulated`), a **primary engine**, and a **secondary engine**. Operator-toggleable sources keep a per-source mode in a state file (`/dev/shm/hapax-audio-router/source-mode.json`) that the arbiter reads every tick. The contract is:

| Source class | Default | Primary | Secondary | Operator toggle | Must-bypass on |
|--------------|---------|---------|-----------|-----------------|-----------------|
| Voice (TTS, Rode) | modulated | Evil Pet | S-4 Track 1 | no — always modulated per directive | consent-critical, FORTRESS |
| Music (YT, SoundCloud) | modulated | S-4 Track 2 | Evil Pet (coloration) | no — always modulated per directive | programme `dry_music_only=true` |
| Vinyl (Handytrax) | **dry** | (dry) | Evil Pet Mode D | **`hapax-source-mode vinyl modulated\|dry`** | — |
| Sampler (MPC) | **dry** | (dry) | Evil Pet (AUX send) + S-4 Track 3 | **`hapax-source-mode mpc modulated\|dry`** | — |
| Operator SFX (assistant chimes) | **dry** | (dry) | Evil Pet T1 | **`hapax-source-mode sfx modulated\|dry`** | — |
| Contact mic (Cortado) | bypassed | — | — | no — always private | always bypassed |

Hardware-absence fallback: if secondary is unavailable (e.g., S-4 not USB-enumerated), source degrades to primary-only with no governance penalty.

**Operator-toggleable sources** (vinyl, mpc, sfx) are modulated only when their entry in the state file is `"modulated"`. Absent file, missing key, invalid value, or any parse error fails **safe to default** (dry). Toggles take effect at the next arbiter tick (≤ 200 ms @ 5 Hz). The CLI `scripts/hapax-source-mode` is the canonical writer; arbiter (§6) is the canonical reader. Voice and music ignore the file — they are always modulated per the "no naked signal" directive (operator 2026-04-22).

The data contract is in `shared/source_mode.py` (`SourceMode` Enum + `read_modes()` / `write_mode()`).

### §3.2 Engine → Preset contract

Each engine has a finite, versioned preset registry:

- **Evil Pet**: 13 presets in `shared/evil_pet_presets.PRESETS`. Names: 7 voice tiers (T0..T6) + `hapax-mode-d` + `hapax-bypass` + 4 music presets (`hapax-sampler-wet`, `hapax-bed-music`, `hapax-drone-loop`, `hapax-s4-companion`). Each preset is a `dict[int, int]` CC map.
- **S-4**: 10 scenes in a new registry `shared/s4_scenes.SCENES` (to be created in plan Phase B4). Scenes: `VOCAL-COMPANION`, `VOCAL-MOSAIC`, `MUSIC-BED`, `MUSIC-DRONE`, `MEMORY-COMPANION`, `UNDERWATER-COMPANION`, `SONIC-RITUAL`, `BEAT-1`, `RECORD-DRY`, `BYPASS`. Each scene is a `S4Scene` dataclass with `material`, `granular`, `filter`, `color`, `space` slots + per-slot CC overrides.

Preset recall is atomic-per-CC, non-atomic-per-preset (graceful degradation on partial failure; logged per CC).

### §3.3 Context → Routing contract

The arbiter (§6) reads a **runtime state tuple** `(stance, stimmung_vector, programme, impingements_active, broadcaster_state, intelligibility_budget, hardware_state)` and emits a **routing intent** `(topology_class, evilpet_preset, s4_scenes_per_track, software_gains)` per tick (5 Hz).

Topology classes are §5.1..§5.12 from the research doc (12 total). Only one class is active at a time; transitions between classes are latency-budgeted (§3.6).

### §3.4 Operator → Override contract

Operator CLI commands (§6.8 research) always win over arbiter output, with the exception of **safety clamps** (consent-critical, Mode D mutex, monetization gate). Overrides persist until explicitly released OR until utterance boundary expires (§6.4 research).

### §3.5 Observability contract

Every routing decision emits:

- Prometheus metric update (per-tick for gauges; per-transition for counters).
- Langfuse event (for tier / scene / topology-class transitions).
- JSONL log entry at `~/hapax-state/audio-router/router.jsonl` (per-tick decision log; 10 MB / keep 5 rotation).

The `capability_health.voice_tier_{0..6}_reliability` gauge is the feedback channel from performed-state back to recruitment: the director reads this and biases future tier requests away from unreliable ones.

### §3.6 Latency contract

Maximum allowed latencies for each switching mechanism:

| Switch | Max latency | Escalation |
|--------|-------------|------------|
| Single CC emit (Evil Pet) | 20 ms | failure counter |
| Full preset recall (Evil Pet, 15 CCs) | 300 ms | failure counter; allow partial |
| S-4 program change | 50 ms | failure counter; skip tick |
| S-4 full scene reload (per-slot CCs) | 200 ms | failure counter; allow partial |
| Handoff sequence (Mode D ↔ voice-tier) | 300 ms | failure counter |
| Full topology swap (D1 ↔ D5) | 2000 ms | operator-gesture-triggered only; non-recurring |
| Arbiter tick period | 200 ms (5 Hz) | structural; no escalation |

Failure-handling: log to Prometheus, decrement `capability_health`, continue with next decision (no retry; no cascading).

## §4. Affordances

### §4.1 Hardware affordances (verified 2026-04-21)

Evil Pet: standalone analog FX processor + granular synthesizer. Mono 1/4" TS in/out. MIDI ch 1 via Erica Dispatch (L-12 hardware loop: MONITOR A → IN, OUT → CH1 XLR → CH6 input → AUX5).

Torso S-4: USB-C class-compliant 10-in/10-out + 2× mono 1/4" TR analog line I/O. 4 parallel stereo tracks × 5 slots each (Material → Granular → Filter → Color → Space). MIDI receives program change + CC. **Not currently USB-enumerated**; design treats S-4 as plan-present-hardware-absent and degrades gracefully.

ZOOM L-12: 14-ch USB multitrack capture (UAC2) + analog-surround-40 playback. Physical channels CH1..CH12 expose as AUX0..AUX11 in capture; CH13/14 are MASTER L/R (dropped from broadcast).

Ryzen HDA: analog stereo line-out feeds L-12 CH11/12 as the default PC fan-out.

MIDI Dispatch (Erica Synths): USB MIDI patchbay, card 11, 1+ output lanes. Currently one lane wired to Evil Pet; second lane available for S-4 when plugged.

### §4.2 S-4 scene library (10 scenes)

Each scene is a 5-slot configuration (Material, Granular, Filter, Color, Space) + per-slot CC overrides. Stored in `shared/s4_scenes.SCENES: Final[dict[str, S4Scene]]`. Scenes:

| # | Name | Purpose | Material | Granular | Filter | Color | Space |
|---|------|---------|----------|----------|--------|-------|-------|
| 1 | `VOCAL-COMPANION` | Subtle voice complement to Evil Pet | Bypass | None | Ring (2 kHz, Q 0.4, wet 35%) | Deform (drive 20, comp 40) | Vast (size 30, bright, wet 40%) |
| 2 | `VOCAL-MOSAIC` | Textural voice (SEEKING stance) | Bypass | Mosaic (density 70%, drift 30%) | Ring (Q 0.7, wet 50%) | Deform (drive 15) | Vast (tail 60%, dark) |
| 3 | `MUSIC-BED` | Low-impact music processing | Bypass | None | Peak (1 kHz, Q 0.3, wet 20%) | Deform (drive 10) | Vast (wet 30%, neutral) |
| 4 | `MUSIC-DRONE` | Sustained granular music texture | Bypass | Mosaic (density 40%, length 200 ms) | Peak (wet 35%) | Deform (drive 20) | Vast (tail 70%, dark) |
| 5 | `MEMORY-COMPANION` | Paired with Evil Pet T3 memory preset | Bypass | None | Peak (1.2 kHz, Q 2.0, wet 30%) | Deform (vintage tape) | Vast (medium tail, dark) |
| 6 | `UNDERWATER-COMPANION` | Paired with Evil Pet T4 underwater | Bypass | None | Ring (LPF 800 Hz, Q 0.5, wet 70%) | Deform (soft drive) | Vast (long tail, muffled) |
| 7 | `SONIC-RITUAL` | Dual-granular with Evil Pet T5 (programme-gated) | Bypass | Mosaic (density 90%, rate drift) | Ring (resonance 60%, wet 70%) | Deform (heavy bit-crush; governance) | Vast (huge room, 60% tail) |
| 8 | `BEAT-1` | Sample-based percussion sequencer | Tape (kick-snare-hi-hat) | None | Peak (HPF 150 Hz) | Deform (light drive) | None |
| 9 | `RECORD-DRY` | Record-only passthrough | Tape (record) | None | None | None | None |
| 10 | `BYPASS` | All slots off (governance fallback) | Bypass | None | None | None | None |

Scene recall mechanism: MIDI program change (primary, <50 ms) OR per-slot CC bursts (fallback, <200 ms).

### §4.3 Evil Pet preset registry (13 presets, preserved from 2026-04-20)

Reuse the existing `shared/evil_pet_presets.PRESETS` registry without modification. Preset-to-scene pairing recommendations (non-binding; operator can override):

| Evil Pet preset | Paired S-4 scene | Use case |
|-----------------|------------------|----------|
| `hapax-unadorned` (T0) | `BYPASS` | UC7 emergency clean |
| `hapax-radio` (T1) | `VOCAL-COMPANION` | UC4 operator duet (operator voice coloration) |
| `hapax-broadcast-ghost` (T2) | `VOCAL-COMPANION` | UC1 dual voice character, default |
| `hapax-memory` (T3) | `MEMORY-COMPANION` | UC9 impingement-driven tier shift |
| `hapax-underwater` (T4) | `UNDERWATER-COMPANION` | UC3 seeking stance |
| `hapax-granular-wash` (T5) | `SONIC-RITUAL` | UC10 programme-gated |
| `hapax-obliterated` (T6) | `SONIC-RITUAL` | UC10 rare, governance-critical |
| `hapax-mode-d` | (vinyl doesn't use S-4) | UC5 live performance |
| `hapax-bypass` | `BYPASS` | UC7 emergency clean (fallback) |
| `hapax-sampler-wet` | `BEAT-1` or none | UC5 sampler chops |
| `hapax-bed-music` | `MUSIC-BED` | UC2 default music |
| `hapax-drone-loop` | `MUSIC-DRONE` | UC2 drone passages |
| `hapax-s4-companion` | `MUSIC-BED` or `MUSIC-DRONE` | UC3 D3 swap (Evil Pet on music) |

## §5. Routing topology classes (12 total, 7 preserved + 5 new)

Classes §5.1..§5.7 are preserved verbatim from the 2026-04-20 research (single-engine linear variants). Classes §5.8..§5.12 are new dual-engine classes (D1..D5).

| ID | Name | Pattern | Primary use |
|----|------|---------|-------------|
| §5.1 | Evil-Pet linear | TTS → EP → broadcast | Single-engine fallback |
| §5.2 | S-4 linear | Music → S-4 → broadcast | Single-engine fallback |
| §5.3 | Serial EP→S-4 | TTS → EP → S-4 → broadcast | Deepest texture (rare) |
| §5.4 | Parallel dry/EP | TTS → (dry AND EP) → broadcast | Operator dry-wet blend |
| §5.5 | Parallel EP+S-4 | TTS → (EP AND S-4) → broadcast | Two granular characters |
| §5.6 | MIDI-coupled | S-4 sequencer modulates EP CCs | Rhythmic gating |
| §5.7 | Hybrid sampler | Sampler → (dry AND EP AUX) → broadcast | Sampler with texture |
| §5.8 **D1** | Dual-parallel voice | TTS → (EP AND S-4 via loopback) → broadcast | UC1 default dual voice |
| §5.9 **D2** | Complementary split | Voice→EP, music→S-4, simultaneous | UC2 baseline livestream |
| §5.10 **D3** | Cross-character swap | Engine assignments swap on state | UC3 SEEKING |
| §5.11 **D4** | MIDI-coupled dual | D1+D2 with S-4 LFO modulating EP | UC5 live performance |
| §5.12 **D5** | Serial-fallback-parallel | Parallel baseline, serial on gesture | UC specialised aesthetic |

Each class has: pattern, control surface, failure modes, latency, feedback risk, governance fit (§5 research doc).

## §6. Control-law layer

### §6.1 State variables (inputs to arbiter)

Ten state surfaces (§7.1 research). The arbiter reads these at each tick and emits routing intent. Canonical schemas:

```python
# shared/audio_router_state.py (new)
from typing import Literal, Optional
from pydantic import BaseModel, Field

Stance = Literal["NOMINAL", "ENGAGED", "SEEKING", "ANT", "FORTRESS", "CONSTRAINED"]

class StimmungState(BaseModel):
    stance: Stance
    energy: float = Field(ge=0.0, le=1.0)
    coherence: float = Field(ge=0.0, le=1.0)
    focus: float = Field(ge=0.0, le=1.0)
    intention_clarity: float = Field(ge=0.0, le=1.0)
    presence: float = Field(ge=0.0, le=1.0)
    exploration_deficit: float = Field(ge=0.0, le=1.0)
    timestamp: float  # unix ts

class ProgrammeState(BaseModel):
    role: Optional[str]
    monetization_opt_ins: list[str] = Field(default_factory=list)
    voice_tier_target: Optional[int] = None
    intelligibility_gate_override: bool = False

class BroadcasterState(BaseModel):
    operator_voice_active: bool = False  # Rode VAD
    mode_d_active: bool = False
    sampler_active: bool = False
    sfx_emitting: bool = False

class HardwareState(BaseModel):
    evilpet_midi_reachable: bool
    s4_usb_enumerated: bool
    l12_monitor_a_integrity: bool  # operator-set, rarely changes

class IntelligibilityBudget(BaseModel):
    t5_remaining_s: float = 120.0  # 120s per 300s window
    t6_remaining_s: float = 15.0   # 15s per 300s window
    window_start: float  # unix ts

class AudioRouterState(BaseModel):
    stimmung: StimmungState
    programme: ProgrammeState
    broadcaster: BroadcasterState
    hardware: HardwareState
    intelligibility: IntelligibilityBudget
    capability_health: dict[str, float]  # tier → reliability [0..1]
```

Each surface has a dedicated writer and publishes to a canonical `/dev/shm` path. Paths verified against live code 2026-04-21:

- `/dev/shm/hapax-stimmung/state.json` — stimmung + 6-dim vector (VLA writer, continuous)
- `/dev/shm/hapax-compositor/voice-tier-override.json` — voice-tier override (hapax-voice-tier CLI, on-demand)
- `/dev/shm/hapax-compositor/evil-pet-state.json` — granular-engine ownership ledger (vocal_chain / vinyl_chain when claimed, on-demand)

ProgrammeManager state is in-memory + RAG-persisted; the dynamic router reads ProgrammeManager directly rather than via a `/dev/shm` file. VAD state is consumed by the voice-gate upstream (alpha's B1) and is not a state-surface of the router.

"On-demand" surfaces are absent when no claim is active; the audit CLI distinguishes this from "missing" (continuous surface that should exist but doesn't) — see `scripts/hapax-audio-state-audit`.

### §6.2 Three-layer policy

The arbiter applies three sequential layers per tick:

**Layer 1 — Safety clamps (fail-closed):**

```python
def apply_safety_clamps(intent: RoutingIntent, state: AudioRouterState) -> RoutingIntent | None:
    if state.broadcaster.consent_critical_utterance_pending:
        return RoutingIntent.all_bypass(reason="consent_critical")
    if state.programme.voice_tier_target and state.programme.voice_tier_target < intent.tier:
        intent = intent.clamp_tier(state.programme.voice_tier_target, reason="programme_ceiling")
    if state.intelligibility.budget_exhausted_for(intent.tier):
        intent = intent.clamp_tier(3, reason="intelligibility_budget")
    if intent.tier >= 5 and state.broadcaster.mode_d_active:
        intent = intent.reroute_voice_to_s4_mosaic(reason="mode_d_mutex")
    if not intent.monetization_opt_in_ok(state.programme.monetization_opt_ins):
        intent = intent.clamp_tier(4, reason="monetization_gate")
    if not state.hardware.evilpet_midi_reachable:
        intent = intent.freeze_evilpet(reason="midi_unreachable")
    if not state.hardware.s4_usb_enumerated:
        intent = intent.downgrade_topology_to_single(reason="s4_absent")
    return intent
```

**Layer 2 — Context lookup (stance × programme → target tier + scene):**

See §7.2 research doc for the 6×6 lookup table. Implemented as `shared/audio_router_policy.STANCE_PROGRAMME_TABLE: dict[tuple[Stance, str | None], tuple[int, str]]`.

**Layer 3 — Salience modulation (impingement deltas, max-composition not sum):**

```python
def apply_salience(intent: RoutingIntent, impingements: list[Impingement]) -> RoutingIntent:
    deltas = [impingement_delta(i) for i in impingements if i.active]
    if not deltas:
        return intent
    max_delta = max(deltas, key=lambda d: abs(d.tier_shift))
    return intent.shift_tier(max_delta.tier_shift, reason=max_delta.source)
```

Max-composition prevents multiple mild impingements from stacking into anthropomorphization risk.

### §6.3 Arbitration order (when multiple sources want conflicting tiers)

1. Consent-critical clamp (always wins).
2. Mode D mutex re-route (R3 rule).
3. Monetization gate (opt-in check).
4. Intelligibility budget (T5/T6 clamping).
5. Operator CLI override (explicit user intent).
6. Programme target (role-based floor/ceiling).
7. Director recruitment (salience-derived).
8. Stance default (Layer 2 fallback).

### §6.4 Ramp-time responsiveness

```python
def ramp_seconds(stimmung_velocity: float) -> float:
    return max(0.2, min(2.5, 0.8 / max(stimmung_velocity, 0.1)))
```

Applied to Evil Pet CC interpolation only. S-4 scene recall is step (single program change); during ramp < 0.3 s the arbiter holds S-4 scene and interpolates Evil Pet alone.

### §6.5 Utterance-boundary semantics

Tier sticks for 10 s after TTS silence (configurable via `HAPAX_AUDIO_TIER_STICK_S` env). After 10 s, router reverts to stance-default. Operator override persists until explicit release via CLI.

Impingement arrivals during silence window may re-trigger tier shifts (the "sticky" is a weak default, not a lock).

### §6.6 Dual-engine anthropomorphization governance

If both engines simultaneously engage voice-granular (Evil Pet T5+ AND S-4 Track 1 Mosaic on), governance triggers:

- Intelligibility budget consumption charged at 1.5× normal rate.
- `monetization_opt_ins.dual_granular_simultaneous` MUST be present on programme; else clamp to T4 on Evil Pet and `VOCAL-COMPANION` on S-4.
- Duration ceiling: 60 s per 300 s window (tighter than T5 alone).
- Ring-2 WARD classifier pre-render check required (§6.7).

### §6.7 Pre-render WARD classifier gate

Before a dual-engine tier transition commits:

1. Arbiter routes the proposed preset combination through `UC8` pre-cue path (monitor-only sink).
2. 500 ms sample emitted to Ring-2 WARD classifier (alpha's #215/#218 work).
3. Classifier returns {PASS, WARN, REJECT} based on legibility + consent-safety invariants.
4. On REJECT, arbiter aborts the transition, logs `ward_rejected`, retains prior state.
5. On WARN, arbiter proceeds but increments a telemetry counter; operator gets ntfy if WARN-count > threshold.

## §7. Governance

### §7.1 Preserved gates

- **Consent contracts** — `axioms/contracts/` for dual-granular simultaneous and cross-character swaps that may surprise audience.
- **Mode D mutex** — Evil Pet granular engine exclusive to one claimant per tick.
- **HARDM anti-anthropomorphization** — shimmer clamped 0 on voice paths; no breath/sigh/pitch-LFO.
- **Intelligibility budget** — rolling 5-min window, T5/T6 clamped after caps exhausted.
- **Monetization opt-ins** — `voice_tier_granular`, `mode_d_granular_wash` required on programme for T5+/Mode D.
- **Consent-critical override** — utterances flagged `consent_critical: true` force T0 regardless.

### §7.2 New gates

- **Dual-engine anthropomorphization** (§6.6) — new opt-in `dual_granular_simultaneous`; budget consumption × 1.5.
- **Pre-render WARD classifier** (§6.7) — Ring-2 legibility check before dual-engine commits.
- **Hardware-degradation discipline** — if Evil Pet or S-4 unavailable, degrade gracefully to single-engine without governance penalty (absence is not a gate violation).

## §8. Rollout phases

Three phases, summarized here. See the plan doc for TDD task details.

**Phase A (software-only, S-4 absent; 5 tasks, ~100 LOC):**
- A1: Filter-chain drift fix (remove `gain_pc_l/r` from `hapax-l12-evilpet-capture.conf`).
- A2: Hardware loop verification runbook (operator action, documented).
- A3: Notification-sink isolation (new PipeWire conf; notifications never reach broadcast).
- A4: State-surface audit (verify/reinstate stimmung, voice-tier, programme writers).
- A5: Static S-4 sink producer (loopback from `hapax-yt-loudnorm` to `hapax-s4-content`, no-op until S-4 plugs).

**Phase B (S-4 online; 6 tasks, ~500 LOC):**
- B1: S-4 USB enumeration + producer wiring.
- B2: S-4 MIDI lane (Erica Dispatch OUT 2).
- B3: Dynamic router agent (`agents/audio_router/dynamic_router.py`).
- B4: S-4 scene library (`shared/s4_scenes.py` + 10 scenes).
- B5: Dual-engine preset pack extension (companion pairs; update `shared/evil_pet_presets.py`).
- B6: UC1..UC10 integration tests.

**Phase C (production dynamism; 5 tasks, ~200 LOC):**
- C1: Ramp-time responsiveness (§6.4 formula).
- C2: Utterance-boundary sticky (§6.5 semantics).
- C3: Observability closure (Prometheus + Langfuse + router.jsonl).
- C4: Dry-run preview (`UC8` monitor-only sink).
- C5: WARD classifier pre-render gate (§6.7).

## §9. Testing strategy

| Phase | Unit tests | Integration tests | Regression pins | Governance tests |
|-------|-----------|-------------------|-----------------|------------------|
| A | Filter-chain schema, notification isolation, yt-loudnorm loopback | PipeWire restart + live-graph verification | `test_evilpet_s4_gain_discipline.py` (updated) | — |
| B | S-4 scene schema, router policy layers, preset pack extension | S-4 sink visibility, MIDI lane, UC1–UC10 | — | Consent-critical clamp, Mode D mutex, monetization opt-ins |
| C | Ramp formula, sticky-state timer, Prometheus registration | Router tick cadence, dry-run latency, WARD classifier integration | — | Dual-engine anthropomorphization, pre-render WARD |

Existing tests preserved:
- `tests/pipewire/test_s4_loopback_conf.py` (conf file schema)
- `tests/pipewire/test_s4_loopback_runtime_safety.py` (new, from Phase A of prior plan; shipped in this bundle)
- `tests/shared/test_evilpet_s4_gain_discipline.py` (gain discipline; updated for A1 drift fix)
- `tests/audio/test_s4_topology.py` (topology descriptor)

## §10. Success criteria

Design is live when:

1. Phase A shipped → livestream broadcast has no bypass path active (AUX10/11 no longer summed); notifications isolated; state surfaces writing.
2. Phase B shipped → arbiter agent ticking 5 Hz; UC1..UC10 pass integration tests with S-4 plugged in.
3. Phase C shipped → ramp-responsive tier transitions audible; dry-run CLI functional; WARD classifier gates dual-engine.
4. 24-hour live operation with zero `ward_rejected` counter increments under normal usage.
5. Operator sign-off on aesthetic quality of D1, D2, D3 default topologies.

## §11. Open questions (answered, defaults chosen)

All open questions from §11 research doc are answered here with "always build, always wire" defaults:

1. **S-4 connection**: Both USB (primary, Phase B1) and analog (fallback via CH7/CH8, Phase B1 extension).
2. **Dual-granular coexistence**: Allow via §6.6 governance gate (dual_granular_simultaneous opt-in + budget × 1.5 + WARD).
3. **Ramp preference**: Smooth default (2.5 s at low stimmung velocity), aggressive under high velocity.
4. **Pre-cue**: PipeWire sink (software; enables metering and programmatic WARD integration).
5. **MIDI-coupled modulation**: Routine-allowed (no programme gate); operator gesture (`hapax-midi-couple on`) activates.
6. **Filter-chain mutation**: Mutation-safe for gain/param writes; restart for topology link create/destroy.
7. **Phase A rollout**: Ship all five A-tasks in one PR (coherent review surface).
8. **Dual-granular opt-in**: Graded (`dual_granular_simultaneous: allow | allow_with_budget_halved | deny`).
9. **S-4 scene custody**: Delta drafts in plan B4; operator ratifies CC values per scene in review.
10. **D5 serial gesture**: Single CLI (`hapax-serial-mode on`) with internal confirmation log, no double-prompt.

## §12. References

- Research: `docs/research/2026-04-21-evilpet-s4-dynamic-dual-processor-research.md`.
- Plan: `docs/superpowers/plans/2026-04-21-evilpet-s4-dynamic-dual-processor-plan.md`.
- Preserved contracts: `docs/research/2026-04-20-voice-transformation-tier-spectrum.md`, `docs/research/2026-04-20-mode-d-voice-tier-mutex.md`.
- Code: `shared/evil_pet_presets.py`, `agents/hapax_daimonion/vocal_chain.py`, `agents/hapax_daimonion/vinyl_chain.py`.
- Axioms: `axioms/registry.yaml` (interpersonal_transparency, management_governance).
