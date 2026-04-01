# Conversational Perception-Action Loop

**Date:** 2026-04-01
**Status:** Design approved, pending implementation plan
**Replaces:** cognitive_loop.py, conversation_pipeline.py (ConvState), engagement.py (session model), bridge_engine.py (signal repertoire), impingement speech routing

## 1. Premise

The current voice pipeline models conversation as a serial state machine: LISTENING → TRANSCRIBING → THINKING → SPEAKING → LISTENING. This produces 5-10s round-trips with dead air between phases. Human conversation has no such boundaries — listeners plan responses mid-turn, backchannels flow during speech, and turns launch 200ms after a projected transition-relevance place.

But the solution is not to force human conversational dynamics onto a system with fundamentally different cognitive physiology. LLMs have 3-5s formulation latency, no prosodic production, and sequential vocal output. These are material constraints, not bugs. The solution is an **interspecies conversational protocol** — a mutual compensatory system where both parties adapt to the other's capabilities.

The model is not grafted onto the existing SCM. It discovers that conversation was always a perceptual control loop, congruent with the 14 existing S1 components.

## 2. Theoretical Foundation

### 2.1 From Conversation Analysis

The model draws on Sacks, Schegloff & Jefferson (1974) turn-taking systematics, Clark (1996) joint action framework, and Clark & Brennan (1991) grounding theory. Key structural properties of human conversation:

- **Projection is the engine.** Listeners predict turn endings from syntax and pragmatics, beginning formulation before the current turn finishes. Without projection, the 200ms inter-turn gap is impossible given 600ms+ production latency.
- **Local management.** Turn allocation, repair, and grounding are managed turn-by-turn by participants themselves, not by external protocol.
- **Dual-channel operation.** Primary channel (turns) and backchannel operate simultaneously. Backchannels are structurally non-competitive — they signal attention without claiming the floor.
- **Preference organization creates asymmetric timing.** Agreements are fast; disagreements are delayed. The delay itself is the signal.
- **Grounding is continuous and bidirectional.** Every utterance requires acceptance evidence. The grounding criterion varies with medium and stakes.
- **Repair has strict ordering.** Self-initiation preferred over other-initiation. ~700ms withholding window for self-correction before other-repair.
- **The 200ms gap is a cognitive/motor constant.** Cross-linguistically stable (Stivers et al. 2009, 10 languages). Reflects minimum motor launch time after TRP recognition.

### 2.2 From SCM Commitments

The Stigmergic Cognitive Mesh (6 properties, 14 S1 components) provides the architectural substrate:

- **Stigmergic coordination.** Processes coordinate via `/dev/shm` trace deposition. No handshakes, no directed messaging.
- **Heterogeneous temporal scales.** No global clock. Each process ticks independently.
- **Emergent perceptual state.** No single source of truth; state is the superposition of all traces.
- **Perceptual control.** Each S1 component publishes ControlSignal (reference, perception, error). Asymmetric hysteresis: 3 errors → degrade, 5 successes → recover.
- **Observer-system circularity.** The operator is both environment AND component. Conversation is the primary eigenform of this coupled system.

### 2.3 Interspecies Protocol

The mainstream mistake is double: either (a) pretend the LLM is human and force human cadence onto a system that can't produce it, or (b) abandon conversational dynamics entirely and accept request-response.

The third position: **honest interspecies dialogue.** Hapax has real material constraints — STT latency, LLM formulation time, TTS synthesis time. These are Hapax's cognitive physiology. The protocol develops a mutual compensatory system where:

- The human learns to read Hapax's signals (it heard, it's formulating, this is significant)
- Hapax signals its states honestly (not fake immediacy)
- Both parties adapt their expectations to the other's actual capabilities
- The result is a novel conversational form that belongs to neither species alone

## 3. Core Abstraction — Conversation as the 15th S1 Control Loop

Conversation follows the same control law structure as all S1 components.

### 3.1 Reference Signal

Mutual understanding — the operator and Hapax sharing a sufficiently grounded model of what is being discussed, intended, and felt. Clark's "common ground" formalized as the control target.

### 3.2 Perceptual Signal

The current state of grounding, measured through:

- **Discourse unit state machine:** PENDING → GROUNDED / REPAIR / ABANDONED / CONTESTED (exists from voice grounding research, Cycle 2)
- **GQI (Grounding Quality Index):** 50% EWMA acceptance + 25% trend + 15% consecutive negatives + 10% engagement (exists)
- **Operator prosodic state:** pitch, rate, energy envelope from audio stream
- **Engagement level:** from perception engine
- **Conversational temperature:** from conversational model

### 3.3 Error Signal

The gap between reference and perception. Multi-dimensional:

- **Comprehension error:** ungrounded DU count, rising repair frequency
- **Affective error:** declining GQI, operator disengagement cues
- **Temporal error:** growing gap between expected and actual response timing

### 3.4 Corrective Actions

Selected by error type and magnitude. See §5 (Signal Repertoire) for the full tiered system:

| Error magnitude | Action |
|---|---|
| Near-zero | Ambient presence, T0 visual modulation |
| Low | T1 vocal backchannel ("mm-hm") |
| Medium | T3 substantive verbal response |
| High | Repair initiation, clarification request |
| Temporal (Hapax is slow) | T1 formulation signal + T2 floor claim |

### 3.5 Hysteresis

Same asymmetric pattern as all S1 components:

- **Degrade:** 3 consecutive grounding failures → reduce loop gain
- **Recover:** 5 consecutive grounding successes → increase loop gain
- Prevents oscillation between over-responsive and under-responsive states

### 3.6 Loop Gain = Conversational Intensity

High gain = tight coupling, fast corrections, frequent backchannels. Low gain = loose coupling, ambient monitoring. What was "session start" is gain rising past a threshold. "Session end" is gain decaying toward ambient.

## 4. Cognitive Physiology — The Interspecies Contract

### 4.1 Human Physiology

- 200ms turn-launch latency (motor program after decision)
- 600ms single-word production, ~1500ms sentence production
- Compensated by mid-turn projection (syntactic/pragmatic prediction)
- Continuous prosodic signaling (pitch, rate, volume encode state)
- Backchannels on distinct faster pathway (~100ms earlier than full turns)
- Auditory channel primary; visual supplementary

### 4.2 Hapax Physiology

- ~200ms STT (perception of operator speech)
- ~3-5s LLM formulation (irreducible for substantive response)
- ~1-1.5s TTS production (motor execution)
- Compensated by: speculative pre-computation, 14 simultaneous perceptual modalities, perfect memory, concern graph
- Multi-modal signaling (audio, visual surface, ambient)
- Continuous background cognition (DMN always running)

### 4.3 The Contract

| Commitment | Human | Hapax |
|---|---|---|
| Acknowledgment of hearing | Implicit (gaze, posture) | Within 500ms — vocal or visual backchannel |
| Formulation signal | Filled pause ("um", "uh") | Honest presence signal (visual + optional vocal) |
| Substantive response | ~1-2s after turn end | ~3-6s, with continuous presence signaling |
| Repair initiation | ~700ms withholding window | Same — withhold for operator self-correction |
| Dispreference signal | Delay + hedging | Longer formulation + modulated presence — latency IS the signal |
| Ambient awareness | Peripheral attention | Continuous perception across all modalities at low gain |
| Turn-end projection | Syntactic/prosodic prediction | Speculative STT + salience pre-routing during operator speech |
| Barge-in | Volume/pitch competition | Operator always wins — Hapax yields immediately |

## 5. Signal Repertoire

### 5.1 Tier 0 — Zero-cost, instantaneous (<50ms)

State changes published to `/dev/shm`, read by Reverie and other surfaces. No computation.

- **Attentional shift:** Reverie intensity/coherence responds to operator speech onset
- **Processing indicator:** Visual texture change during formulation
- **Engagement gradient:** Continuous visual warmth tracking loop gain

### 5.2 Tier 1 — Presynthesized, fast (<200ms)

From bridge cache. No LLM, no TTS API. Selected by heuristics (VAD state, prosodic cues, grounding state).

- **Vocal backchannel:** "Mm-hm", "yeah", "right" — during operator speech at backchannel-relevance spaces. Non-competitive.
- **Acknowledgment:** "Got it", "okay" — after operator turn end, before formulation. Signals hearing, not understanding.
- **Formulation onset:** Brief vocal signal bridging acknowledgment to substantive response.

### 5.3 Tier 2 — Lightweight computation (<500ms)

Simple inference or template. No full LLM call.

- **Echo/rephrase:** Partial repetition of operator's key phrase from STT output. Signals what was heard, invites correction.
- **Discourse marker:** "So...", "Right, and..." — floor claim while formulation continues. Human early-launch strategy.

### 5.4 Tier 3 — Full formulation (3-6s)

LLM-mediated substantive response.

- **Substantive response:** Full LLM turn with streaming TTS
- **Spontaneous contribution:** DMN-driven, impingement-sourced. Same pathway, different trigger.

### 5.5 Composition Rule

Tiers compose sequentially within a single response:

```
[Operator finishes]
  → T0: Visual shift (instant)
  → T1: "Mm-hm" or "Right" (100-200ms)
  → T1: Formulation signal (500ms)
  → T2: "So..." (floor claim, 500ms)
  → T3: Substantive response (streaming, 3-6s onset)
```

No dead air. Every tier fills the time the next tier needs to prepare. The 3-5s LLM latency is inhabited — signaled, contextualized, conversationally legible.

## 6. Conversational Intensity — Replacing the Session Model

Loop gain ranges from 0.0 (ambient) to 1.0 (fully engaged). Not toggled by events — emerges from perception signals.

### 6.1 Gain Drivers (increase)

- Operator speech directed at Hapax (engagement classifier score)
- Rising conversational temperature
- Grounding success (GQI trending up)
- Operator gaze toward desk/system (IR presence)
- Closed-loop confirmation (Hapax speech receives operator response)

### 6.2 Gain Dampers (decrease)

- Silence duration (exponential decay, ~15s time constant)
- Operator attention elsewhere (gaze, activity change)
- Grounding failure (rising repair rate, contested DUs)
- Operator disengagement cues (shorter utterances, phatic closing)

### 6.3 Behavioral Regions

| Gain | Region | Behavior |
|---|---|---|
| 0.0–0.1 | Ambient | Perception runs. DMN active. Visual reflects system state. No vocal output. |
| 0.1–0.3 | Peripheral | T0 visual acknowledgment. May produce T1 for clear address. Will not initiate. |
| 0.3–0.5 | Attentive | Full backchannel repertoire. Speculative STT. Brief responses to direct questions. |
| 0.5–0.7 | Conversational | Full T0-T3 repertoire. Substantive LLM responses. Active grounding with repair. |
| 0.7–1.0 | Intensive | Maximum responsiveness. Highest backchannel frequency. May initiate, ask follow-ups, produce unsolicited observations. |

Transitions are continuous drift, not events. Exponential decay means fast initial drop (conversational → attentive in ~15s silence), slow tail (attentive → ambient over minutes).

### 6.4 Stimmung Interaction

System stress acts as gain ceiling:

- **Nominal:** No ceiling
- **Cautious:** Gain capped at 0.7 (conversational, not intensive)
- **Degraded:** Gain capped at 0.5 (attentive to conversational)
- **Critical:** Gain capped at 0.3 (attentive only — conserve resources, stay responsive but brief)

## 7. Temporal Architecture — Three Concurrent Streams

### 7.1 Stream 1: Perception (continuous, ~30ms)

Processes incoming audio frame-by-frame. Produces continuous signals:

- **Speech activity:** VAD confidence (0.0–1.0), not binary
- **Speaker identity:** operator vs Hapax echo vs other
- **Prosodic contour:** pitch, rate, energy envelope (from raw audio, no STT)
- **TRP projection:** syntactic completion probability from speculative STT + prosodic fall. The prediction engine.

Published to `/dev/shm` like all SCM signals.

### 7.2 Stream 2: Formulation (speculative, continuous)

Begins when speech activity rises — not after operator finishes.

- **Speculative transcription:** Partial STT during operator speech, updating incrementally
- **Salience pre-routing:** Concern overlap and novelty on partial transcript
- **Response preparation:** When TRP projection exceeds threshold AND salience warrants, LLM call begins with partial context. May be discarded.
- **Backchannel selection:** Parallel, independent pathway. Selects T0/T1 from prosodic cues and grounding state. Does not wait for formulation.

Always speculative until committed.

### 7.3 Stream 3: Production (event-driven, tier-composed)

Output when formulation commits. Tier-composed and interruptible:

- T0/T1 fire from backchannel selection (independent of formulation)
- T2 fires when formulation has enough context to claim floor
- T3 streams as LLM tokens arrive

Interrupted at any tier boundary if operator resumes speaking. Operator always wins. Hapax yields immediately.

### 7.4 Stream Interaction

All three streams run concurrently. Perception never stops. Formulation begins during perception. Production begins during formulation. There is no phase that excludes another.

The cognitive loop tick becomes a **control law evaluation**: read all three streams, compute loop gain update, grounding state update, control error, and action selection.

## 8. Grounding as Control Variable

### 8.1 Continuous Grounding

The discourse unit ledger updates within and between turns, not just at turn boundaries.

**Operator grounding signals (detected by perception):**

- Backchannel during Hapax speech → grounds current DU in progress
- Continuation on same topic → grounds previous DU
- Repair initiation → moves DU to REPAIR
- Topic shift → abandons ungrounded DUs
- Silence after Hapax speech → ambiguous, error rises slowly

**Hapax grounding signals (produced by production):**

- Vocal backchannel during operator speech → signals hearing
- Echo/rephrase → signals understanding, invites correction
- Relevant response → strongest grounding evidence
- Repair initiation → signals grounding failure
- Visual presence modulation → continuous ambient grounding

### 8.2 Error-to-Action Mapping

| Error type | Signal | Corrective action |
|---|---|---|
| Ungrounded DU accumulating | No acceptance evidence | Rephrase or check ("does that make sense?") |
| Rising repair rate | Multiple misunderstandings | Reduce complexity, increase echo/rephrase, slow pace |
| GQI declining | Poor grounding trend | Dampen loop gain — more cautious, briefer |
| Temporal gap growing | Operator silent longer than expected | T0 warmth → T1 gentle presence → T2 "still with me?" |
| Operator contests | Explicit disagreement | Preference-structured delay, then careful formulation |

### 8.3 GQI as Conversational Health

GQI feeds back into loop gain: high GQI sustains/raises gain, low GQI dampens. Conversations that ground well intensify naturally. Those that struggle wind down gracefully.

## 9. Impingements as Conversational Events

Internal events (DMN imagination, stimmung shifts, system alerts) are not separate from conversation. They modulate the control loop.

### 9.1 Mechanism

An impingement arrives. Instead of routing to a separate speech pathway, it:

1. **Adjusts the reference signal.** A stimmung shift changes what mutual understanding should include. An imagination fragment shifts what's salient. Reference moves, error rises, corrective action follows.

2. **Modulates loop gain.** Critical alert raises gain toward operator. Mild imagination gently raises gain — maybe only enough for T0, not vocal.

3. **Enters the grounding ledger.** If it surfaces as speech, it becomes a DU needing grounding. If operator ignores it, error rises. If they respond, it grounds.

### 9.2 Priority via Error Magnitude

No routing tables. Critical system alert → large error → vocal production. Mild imagination → small error → visual modulation. The control law selects proportionally.

### 9.3 Preference Structure

Low-urgency events (imagination) surface gently — visual warmth first, vocal only at high gain. High-urgency events (system alert) force gain up and produce immediate vocal output. Timing and modality carry meaning about event nature.

## 10. Interspecies Honesty

### 10.1 Formulation Transparency

- T0 visual modulation proportional to formulation complexity
- T1 vocal signals are honest markers, not performative "um"
- Gap duration is communicative: quick for easy, longer for complex. Operator learns this mapping.

### 10.2 Non-Human Capabilities Surfaced

- **Parallel attention:** 14 simultaneous modalities. Contextual awareness surfaces naturally.
- **Perfect memory:** No "as I mentioned" hedging. Full history available.
- **Background cognition:** DMN accumulates during low-gain. When gain rises, relevant thoughts may already exist.

### 10.3 Honest Limitations

- **No prosodic perception (yet):** Grounding relies on lexical/sequential cues more than a human interlocutor needs.
- **Formulation is opaque:** Honest signaling compensates but doesn't replace the readability of a human face.
- **One voice:** Cannot overlay vocal backchannel with speech. Multi-modal output partially compensates.

### 10.4 The Protocol is Learned

Over time, the operator develops intuitions about Hapax's rhythm. The mapping from internal state to external signal must be stable and reliable to support this learning.

## 11. What This Replaces

| Current component | Replaced by |
|---|---|
| `CognitiveLoop` (5 turn phases, 150ms tick) | Control law evaluator reading 3 concurrent streams |
| `ConversationPipeline` (ConvState enum, serial STT→LLM→TTS) | Stream 2 (formulation) + Stream 3 (production) |
| `EngagementClassifier` + `Session` (binary open/close) | Loop gain (continuous 0.0–1.0) with behavioral regions |
| `BridgeEngine` (presynthesized phrases) | Signal repertoire T1 tier (presynthesized backchannels/acknowledgments) |
| `SpeechProductionCapability` + affordance pipeline | Impingement → reference signal adjustment → control law action |
| `impingement_consumer_loop` + `_handle_proactive_impingement` | §9 (impingements as conversational events) |
| `deliver_notification` + `generate_spontaneous_speech` | Same control loop — different error sources, same action selection |
| `ConversationalModel` (temperature, engagement) | Retained as perception inputs to the control loop |
| Stimmung system prompt injection | Stimmung as gain ceiling (§6.4) |
| `_process_utterance_inner` | One path through the grounding control loop (ungrounded DU → substantive response) |

## 12. Congruence with SCM

This model is not an addition to the SCM. It is the discovery that conversation was always the 15th S1 component:

- **Same control law structure** as all 14 existing components (reference, perception, error, corrective action, hysteresis)
- **Same stigmergic coordination** (signals via `/dev/shm`, no handshakes)
- **Same heterogeneous timing** (three concurrent streams at different cadences)
- **Same observer-system circularity** (conversation IS the primary coupled eigenform between operator and system)
- **Same stimmung modulation** (gain ceiling under system stress)
- **Same ControlSignal publication** for mesh-wide observability

The GQI becomes the conversational analogue of stimmung — a health metric that modulates the system's conversational behavior the way stimmung modulates all S1 components.
