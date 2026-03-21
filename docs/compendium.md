# The Hapax Compendium

**Epistemic status of this document:** Working. Initially written 2026-03-18 by Claude (alpha session) from exhaustive codebase audit. Updated 2026-03-19 to incorporate conversational continuity research (beta session) and temporal classification system (alpha session). Covers everything that exists, everything that was attempted, and everything that is projected — clearly distinguished throughout.

**Audience:** The operator. You built this. This document exists so you can hold the whole system in your head, find anything, and restart any thread from cold. Strong intuitions about formal systems, not PhD-level notation. Math stays dumb, explanations stay smart.

**How to read this:** Front-to-back for the first pass to build the full mental model. Then by section for reference. Every subsystem entry is self-contained. Cross-references use `→ Section Name` notation.

---

## Table of Contents

1. [Orientation](#1-orientation)
2. [Convictions](#2-convictions)
3. [Architecture Overview](#3-architecture-overview)
4. [The Perception Loop](#4-the-perception-loop)
5. [The Visual Loop](#5-the-visual-loop)
6. [The Reactive Loop](#6-the-reactive-loop)
7. [The Voice Pipeline](#7-the-voice-pipeline)
8. [Governance Infrastructure](#8-governance-infrastructure)
9. [The Self-Band (Apperception)](#9-the-self-band-apperception)
10. [The Phenomenological Stack](#10-the-phenomenological-stack)
11. [Consent Formalisms](#11-consent-formalisms)
12. [Hapax Logos (The Visual Body)](#12-hapax-logos-the-visual-body)
13. [Agents](#13-agents)
14. [Infrastructure](#14-infrastructure)
15. [Data Sources and Ingestion](#15-data-sources-and-ingestion)
16. [The Trio Relay Protocol](#16-the-trio-relay-protocol)
17. [Conversational Continuity Research](#17-conversational-continuity-research)
18. [Temporal Classification System](#18-temporal-classification-system)
19. [Decision Log](#19-decision-log)
20. [Evolution](#20-evolution)
21. [Open Questions and Technical Debt](#21-open-questions-and-technical-debt)
22. [Projected Work](#22-projected-work)
23. [Operational Reference](#23-operational-reference)
24. [Glossary](#24-glossary)

---

## 1. Orientation

### What This System Is

Hapax is externalized executive function infrastructure for a single operator with ADHD and autism. It is a personal operating environment — not an app, not a framework, not a product. It runs on one machine (CachyOS, RTX 3090, 64GB RAM) and serves one person.

The system offloads cognitive overhead: tracking open loops, maintaining continuity across work sessions, monitoring its own health, surfacing what needs attention, and handling routine maintenance autonomously. 45+ agents coordinate through the filesystem. A voice daemon provides conversational interaction. A visual compositor renders the system's state as an ambient display. A reactive engine watches for changes and cascades downstream work.

The governing claim: alignment and governance are not costs bolted onto a useful system — they are the system's structural foundation. The axioms that constrain what the system will do are the same axioms that make it useful. This is the conviction that the system exists to test.

### What This System Is Not

- Not multi-user. The single-operator axiom is constitutional (weight 100). There is no auth, no roles, no collaboration features. These are not missing — they are forbidden.
- Not a product. There is no deployment target, no customer, no scaling story. Generality is a non-goal.
- Not a research prototype. It runs in production daily. The operator depends on it. Changes must not break running services.
- Not finished. It was built in 8 days (March 11-18, 2026). Many subsystems are experimental. The document marks epistemic status throughout.

### State of the System (2026-03-19, updated)

| Dimension | Status |
|-----------|--------|
| Health checks | 98/101 passing (3 degraded: drift timer, obsidian connectivity, watch connectivity) |
| Docker containers | 13 running, all healthy |
| GPU | 13.8/24.6 GB used |
| Cycle mode | prod |
| Open PRs | 0 (as of last merge) |
| Total PRs merged | 210 |
| Total commits | ~480 in 9 days |
| Test count | 470+ test files |
| Python LOC | ~50,000 (excluding generated/vendor) |
| Agents | 33 manifested |
| Axioms | 5 active (3 constitutional, 2 domain) |
| Voice daemon | running, baseline experiment in progress |
| Visual aggregator | running |
| Cockpit API | running on :8051 |
| Reactive engine | running (12 rules, presence-gated) |
| Stimmung | cautious (health monitor degraded, watch offline) |
| Baseline sessions | 7 of 20 collected (code frozen for experiment) |
| Cameras | 6 (1 Brio + 3 C920 operational, 2 new Brios wired) |

### Scale

| Component | Count |
|-----------|-------|
| shared/ modules | 83 files across 8 subsystems |
| agents/ modules | 221 files across 7 subsystems |
| cockpit/ modules | 43 files |
| hapax_voice/ | 95 files (largest subsystem) |
| Test files | 470+ |
| Agent manifests | 33 (YAML, 4-layer schema) |
| Systemd services | 10 services, 2 timers |
| /dev/shm directories | 4 (apperception, compositor, logos, stimmung) |
| Qdrant collections | 4 (claude-memory, profile-facts, documents, axiom-precedents) + 2 (studio-moments, hapax-apperceptions) |
| Research documents | 30+ (500+ sources total) |
| Memory files | 34 |

---

## 2. Convictions

The system is governed by 5 axioms. These are not guidelines — they are enforceable constraints with weights, tiers, and implications. The axiom registry lives at `axioms/registry.yaml`. Implications are derived in `axioms/implications/`. Enforcement happens at commit hooks, CI pipeline, and runtime.

### The Five Axioms

**single_user** (weight 100, constitutional, hardcoded)
One operator, always. The system leverages single-user facts for every decision: no auth overhead, no permission complexity, no data segregation. This is not a limitation accepted reluctantly — it is an architectural advantage pursued deliberately. Every multi-user feature that doesn't exist is a class of bugs that doesn't exist.

*Experience that produced it:* Every system the operator has used that was "designed for teams" imposed cognitive overhead that a single user shouldn't bear. The axiom makes the system's simplicity constitutionally protected.

**executive_function** (weight 95, constitutional, hardcoded)
The system compensates for ADHD and autism. Task initiation, sustained attention, and routine maintenance are genuine cognitive challenges for the operator. The system offloads cognitive overhead, maintains continuity, monitors health autonomously, and surfaces what needs attention. Zero added cognitive load is the standard — every interaction should reduce friction, never add it.

*Experience that produced it:* The operator has ADHD and autism. Systems that require setup, configuration, or remembering to check them are systems that will not be used. The axiom forces agents to be zero-config and self-maintaining.

**corporate_boundary** (weight 90, domain, softcoded)
On employer devices: employer-sanctioned APIs only. Home system handles personal and management-practice domains. Work data stays in employer systems. The system degrades gracefully when home-only services (Ollama, studio compositor) are unreachable from work.

*Experience that produced it:* The operator is a manager at a technology company. The boundary between work tools and personal infrastructure must be crisp and defensible.

**interpersonal_transparency** (weight 88, constitutional, hardcoded)
No persistent state about non-operator persons without an active consent contract. Consent must be opt-in (never implied from proximity), inspectable (the person can see what's stored), and revocable (with data purge cascade). This axiom was proposed 2026-03-13, evaluated, and is now active.

*Experience that produced it:* The system has cameras, microphones, and a voice daemon. It perceives people who are not the operator. The axiom ensures that perception of others is governed by consent, not by capability. The wife-walks-in scenario was the design driver: when a guest enters the room, the system must detect them, pause persistence of person-adjacent data, offer consent through an appropriate channel, and either gate or curtail data based on the response.

**management_governance** (weight 85, domain, softcoded)
The system aggregates signals and prepares context for management decisions. LLMs prepare, humans deliver. The system will never generate feedback language, coaching recommendations, or performance assessments about individual team members. It may surface data patterns, but the interpretation and communication are the operator's responsibility.

*Experience that produced it:* The operator manages people. The temptation to have AI write performance reviews or generate coaching scripts is exactly the kind of automation that undermines the human relationship that management depends on.

### Enforcement Tiers

| Tier | Effect | Example |
|------|--------|---------|
| T0 | Block. Commit rejected, PR blocked, runtime error. | Storing person data without consent contract |
| T1 | Review required. CI flags for human review. | Agent generating text about a team member |
| T2 | Warning. Logged, surfaced in nudges. | Agent accessing work-domain data from home system |
| T3 | Advisory. Recorded in precedent store. | Novel situation with no clear axiom mapping |

### What This System Will Never Do (Non-Goals)

- Support multiple operators
- Generate feedback or coaching about individual people
- Store biometric or behavioral data about non-consented persons
- Run on cloud infrastructure (all local, all the time)
- Optimize for latency at the cost of governance
- Make decisions that should be human decisions

---

## 3. Architecture Overview

### The Three Tiers

**Tier 1 — Interactive Interfaces**
- Council-web React SPA at :5173 (via cockpit API proxy)
- Hapax Logos Tauri app (wgpu visual surface + React control panel)
- VS Code extension (not covered in this compendium)

**Tier 2 — LLM-Driven Agents**
All routed through LiteLLM gateway at :4000. Model aliases: fast=gemini-flash, balanced=claude-sonnet, reasoning=qwen3.5:27b, coding=qwen3.5:27b, local-fast=qwen3:8b. Agents use pydantic-ai with `output_type` (not `result_type`).

**Tier 3 — Deterministic Agents**
No LLM calls. Health monitor, sync agents, reactive engine rules. These run on timers or inotify events.

### Filesystem-as-Bus

Agents coordinate by reading and writing markdown files with YAML frontmatter to disk. The filesystem IS the message bus. A reactive engine (inotify watcher) watches `profiles/`, `axioms/`, and `rag-sources/` for changes and cascades downstream work.

This pattern was chosen because:
- It's debuggable (you can `cat` any file to see state)
- It survives restarts (state is on disk, not in memory)
- It's concurrent without locks (atomic rename for writes)
- It composes naturally (any agent can read any file)

### The Three Independent Loops

The system runs three independent loops that communicate through the filesystem and `/dev/shm`:

```
Loop 1: Perception (voice daemon, 2.5s tick)
  → reads sensors → fuses state → writes perception-state.json

Loop 2: Visual Aggregator (3s tick, adaptive 0.5-5s)
  → reads perception state → computes stimmung, temporal bands, apperception
  → writes to /dev/shm (4 directories)

Loop 3: Reactive Engine (inotify, event-driven)
  → watches profiles/, axioms/, rag-sources/
  → evaluates rules → executes phased actions
```

These loops do not share memory. They communicate exclusively through files. This is deliberate: if any loop crashes, the others continue. The filesystem is the coordination substrate.

### The /dev/shm Topology

```
/dev/shm/hapax-stimmung/
  └── state.json         ← Visual aggregator writes (60s)
                            Reactive engine reads (phase gating)
                            Phenomenal context reads (voice LLM)
                            Config reads (model downgrade)

/dev/shm/hapax-temporal/
  └── bands.json          ← Visual aggregator writes (3s)
                            Phenomenal context reads (voice LLM)
                            Anchor builder reads (salience routing)

/dev/shm/hapax-apperception/
  └── self-band.json      ← Visual aggregator delegates to ApperceptionTick (3s)
                            Phenomenal context reads (voice LLM)
                            Anchor builder reads (concern graph)

/dev/shm/hapax-compositor/
  └── visual-layer-state.json  ← Visual aggregator writes (3s)
                                  Studio compositor reads (rendering)
                                  Hapax Logos reads (Flow page)
  └── activity-correction.json ← Studio writes (operator corrections)
                                  Apperception reads (correction events)
```

### What Happens When the Operator Sits Down

1. Perception tick fires (2.5s). Reads all sensor backends: audio (PipeWire), vision (YOLO), biometrics (watch), workspace (Hyprland), keyboard (logind DBus). Bayesian presence engine fuses 8 signals → P(operator_present). Governor evaluates → "process" directive. Consent tracker checks face count, speaker ID.

2. Visual aggregator polls perception state (3s). Maps to display state machine (ambient/alert/focus/interaction/error). Runs stimmung collector (6 dimensions → stance). Computes temporal bands (retention/impression/protention/surprise). Delegates apperception tick. Writes all to /dev/shm.

3. Studio compositor reads visual layer state from shm. Renders GStreamer pipeline with overlays. Outputs to /dev/video42 (v4l2loopback virtual webcam) and HLS stream.

4. Cockpit API polls health (15s), nudges/briefing (60s). Serves React SPA. Reactive engine watches filesystem.

### What Happens When Someone Walks In

1. Vision backend detects person_count > 1. Bayesian face fusion deduplicates across cameras (cosine similarity > 0.6 = same person, union-find clustering). Guest_count computed.

2. Consent tracker transitions: NO_GUEST → GUEST_DETECTED (5s debounce) → CONSENT_PENDING.

3. Governor produces "pause" directive. Perception state writer curtails voice/gaze/posture data. Visual layer shows "Guest detected — identifying."

4. If operator not in active voice session: consent voice session launches via Pipecat. LLM explains recording scope, asks for consent. Guest responds naturally. Decision: GRANTED (contract created, data resumes) or REFUSED (data remains curtailed, guest_count tracked but nothing else persisted).

5. On guest departure (face_count returns to 1): consent tracker resets. If consent was refused, no data to purge. If consent was granted, contract remains for future visits.

### What Happens When the System Detects Something Wrong

1. Stimmung collector aggregates 6 dimensions: health, resource_pressure, error_rate, processing_throughput, perception_confidence, llm_cost_pressure. Each dimension is a value 0.0-1.0 with trend (rising/falling/stable) and freshness.

2. Overall stance = worst non-stale dimension:
   - < 0.3 → nominal
   - 0.3-0.6 → cautious
   - 0.6-0.85 → degraded
   - ≥ 0.85 → critical

3. Stance propagates:
   - Reactive engine: degraded/critical → skip Phase 1+2 (GPU/cloud actions)
   - Voice pipeline: stimmung downgrade → cheaper models (critical → LOCAL only)
   - Apperception cascade: critical → only prediction_error + correction events pass
   - Visual layer: display state machine reflects system stress
   - Content scheduler: adapts tick interval (critical → 5s base)

---

## 4. The Perception Loop

**Epistemic status: Proven.** Running in production, tested, load-bearing. The voice daemon drives this loop.

### What It Perceives

The perception system fuses data from up to 20 sensor backends into a unified `EnvironmentState`. Not all backends are active at all times — the system degrades gracefully when sensors are unavailable.

**Active Backends (as of 2026-03-18):**

| Backend | What It Reads | Cadence | Status |
|---------|---------------|---------|--------|
| Vision (YOLO) | Person count, operator face, guest faces, pose | 2.5s | **Proven** |
| PipeWire | Audio energy, VAD, music detection | 2.5s | **Proven** |
| Hyprland | Active window, workspace, display layout | 2.5s | **Proven** |
| logind DBus | Keyboard/mouse idle state | 2.5s | **Proven** |
| Local LLM | Activity classification, flow estimation | 2.5s | **Working** |
| Watch | Heart rate, HRV, skin temp | push | **Offline** (watch not transmitting) |
| Health JSONL | System health history | 2.5s | **Proven** |
| Circadian | Time of day, productive window | 2.5s | **Proven** |
| MIDI clock | Studio tempo, transport state | push | **Working** |

**Not Yet Wired:**
- Screen content analysis (Gemini Flash vision, exists but not in tick loop)
- Pi sensor array (4 Pis available, no software yet)
- Spotify (no integration)
- Cross-project awareness (other repos)

### Bayesian Presence Engine

**Epistemic status: Working.** Merged in PR #161, calibrated from first live run in PR #167.

Fuses 8 signals into P(operator_present) using likelihood ratios × prior:

| Signal | Likelihood Ratio (present) | Likelihood Ratio (absent) |
|--------|---------------------------|--------------------------|
| operator_face visible | 12.0 | 0.15 |
| keyboard active | 4.0 | 0.4 |
| VAD speech detected | 3.0 | 0.6 |
| speaker is operator | 8.0 | 0.3 |
| watch heart rate | 2.5 | 0.5 |
| watch connected | 1.5 | 0.7 |
| desktop active | 2.0 | 0.5 |
| MIDI active | 2.0 | 0.8 |

Hysteresis state machine: PRESENT (≥0.7, 5s enter, 60s exit) → UNCERTAIN → AWAY (<0.3).

**Known calibration issues:** Likelihood ratios are estimates from first live session. Need more scenarios (leave room, meeting, sleep) for proper calibration.

### The Perception Ring Buffer

Raw perception snapshots are pushed to a ring buffer (`PerceptionRing`, maxlen=20, ~50s of history at 2.5s ticks). The ring supports:
- `current()` → latest snapshot
- `window(seconds)` → all snapshots within time window
- `trend(field, window_s)` → linear regression slope for a numeric field

The ring feeds temporal band formatting (retention/impression/protention) and multi-scale aggregation (minute/session/day summaries).

### Multi-Camera Face Deduplication

**Epistemic status: Working.** Merged in PR #161.

4 cameras (Logitech Brio + 3x C920) produce independent YOLO detections. The system deduplicates across cameras using face embedding cosine similarity:
- Similarity > 0.6 → same person (union-find clustering)
- `FusedFaceResult`: operator_visible (bool) + guest_count (int)
- Guest_count replaces raw face_count for consent tracking (eliminates double-counting operator across cameras and false positives from screens/reflections)

### Speaker Identification

**Epistemic status: Working.** Pyannote embedding cosine similarity.

- Enrollment: operator voice enrolled at first run
- Verification: each VAD segment compared to enrollment embedding
- Threshold: 0.25 cosine similarity
- Session-level trust: once verified, subsequent utterances in same session inherit trust
- Used by consent tracker to distinguish operator from guest speech

---

## 5. The Visual Loop

**Epistemic status: Proven.** The visual_layer_aggregator is a standalone async process that polls perception state and writes to /dev/shm.

### Visual Layer Aggregator

Entry point: `uv run python -m agents.visual_layer_aggregator`
Systemd: `visual-layer-aggregator.service`

**Dual-loop architecture:**
- Fast loop (3s, adaptive 0.5-5s): perception → state machine → scheduler → write
- Slow loop: health/GPU poll (15s), nudges/briefing (60s), ambient content (45s)

### Display State Machine

5 states, driven by signal severity and voice session activity:

| State | Trigger | Visual Character |
|-------|---------|-----------------|
| Ambient | No signals above LOW | Generative shader, floating text fragments, warm |
| Peripheral | LOW signals present | Subtle zone highlights, information available but not demanding |
| Informational | MEDIUM signals | Zone content visible, readable but not urgent |
| Alert | HIGH/CRITICAL signals | Red-shifted, prominent, attention-demanding |
| Interaction | Voice session active | Voice state indicator, supplementary content cards |

### Content Scheduler

**Epistemic status: Working.** Softmax temperature-based content selection.

Selects what to display in the ambient layer from 4 content pools: ambient text (system aphorisms, operator quotes), profile facts, nudge summaries, studio moments. Uses the SEEV attention model (Salience, Effort, Expectancy, Value) adapted for AuDHD attention patterns.

### Stimmung Collector

**Epistemic status: Proven.** Pure logic, no I/O.

6 dimensions, each a `DimensionReading` with value (0.0-1.0, higher = worse), trend (rising/falling/stable), and freshness (seconds since last update).

| Dimension | Source | What It Measures |
|-----------|--------|-----------------|
| health | profiles/health-history.jsonl | System health check ratio |
| resource_pressure | GPU snapshot | VRAM utilization |
| error_rate | Reactive engine status | Action error ratio |
| processing_throughput | Reactive engine events/min | Engine activity level |
| perception_confidence | Perception age + confidence | Sensor data quality |
| llm_cost_pressure | Langfuse daily cost | API spend vs $50/day ceiling |

**Recent fix (2026-03-18):** LLM cost ceiling was $5/day, triggering false-critical every day on normal $15-30/day usage. Fixed to $50/day. Idle engine throughput was treated as pressure (0.97 = system stressed). Fixed: idle engine = 0 pressure.

### Temporal Band Formatter

**Epistemic status: Proven.** Pure logic, reads from perception ring.

Formats perception history into Husserlian temporal bands:
- **Retention**: 3 entries sampled from ring (recent ~5s, mid ~15s, far ~40s). Fading past.
- **Impression**: Current snapshot. Vivid present. Includes flow_state, activity, audio_energy, heart_rate, music_genre, consent_phase, presence, presence_probability.
- **Protention**: Statistical predictions from protention engine + trend fallback. Anticipated near-future.
- **Surprise**: Prediction mismatches. What was predicted and turned out wrong.

Output is XML written to `/dev/shm/hapax-temporal/bands.json`. Consumed by `shared/operator.py` for non-voice LLM prompt injection, and by `phenomenal_context.py` for voice LLM prompt injection.

**Presence integration (2026-03-18, PR #164):** Bayesian presence_probability now flows through all bands — retention entries carry presence state, impression includes presence + probability, protention predicts operator_departing/returning from trend, surprise detects presence prediction mismatches.

### Apperception Tick

**Epistemic status: Working.** Extracted from visual_layer_aggregator into standalone `shared/apperception_tick.py` (PR #169).

→ See [Section 9: The Self-Band](#9-the-self-band-apperception) for full description.

---

## 6. The Reactive Loop

**Epistemic status: Working.** Merged in PR #170 (beta), 12 rules.

### Reactive Engine

Located in `cockpit/engine/`. Starts as part of the cockpit API lifespan handler.

**Architecture:**
- Watcher: inotify (via watchdog) on `profiles/`, `axioms/`, `rag-sources/`
- Debounce: 500ms (dev) / 1000ms (prod)
- Rule evaluation: each `ChangeEvent` is matched against rules by doc_type (inferred from YAML frontmatter)
- Execution: PhasedExecutor runs actions in 3 phases:
  - Phase 0: deterministic (cache refresh, config logs) — unlimited concurrency
  - Phase 1: GPU-bound (local LLM, RAG embeddings) — semaphore max=1
  - Phase 2: cloud-bound (knowledge maintenance) — semaphore max=2

**Stimmung gating:** When stance is degraded/critical, Phase 1+2 actions are skipped. This is allostatic regulation — the system conserves resources when stressed.

**Presence gating (2026-03-18):** When operator is AWAY, Phase 1+2 actions are skipped. Save cloud costs when nobody's here.

### Current Rules (12)

The reactive engine evaluates rules defined in `cockpit/engine/reactive_rules.py`. Each rule has a filter (which events match) and a producer (what actions to emit).

**Categories:**
- RAG source landing → ingest pipeline
- Profile changes → cache refresh, knowledge maintenance
- Axiom changes → compliance re-evaluation
- Presence transitions → phase gating
- Consent transitions → notification, contract lifecycle

### History and Observability

The engine maintains a ring buffer of recent events (last 100). Each entry: timestamp, event path, doc_type, rules matched, actions executed, errors. Exposed via cockpit API `GET /engine/status`.

Frequency window tracks event patterns for novelty detection: events with pattern_count ≤ 2 are "novel" (the engine is seeing something new).

---

## 7. The Voice Pipeline

**Epistemic status: Proven architecture, working implementation, baseline experiment in progress.**

### Overview

The voice daemon (`agents/hapax_voice/__main__.py`) is the largest subsystem (95+ files). It provides continuous voice interaction with the operator.

**Pipeline:** Wake word (Whisper-based, fuzzy phonetic matching) → VAD-gated audio accumulation (1.5s pre-roll) → STT (faster-whisper, resident in VRAM, contextual prompt conditioning) → Salience routing (concern graph activation) → LLM call (Opus via LiteLLM, 150 token max, 25 word spoken cutoff) → Streaming TTS (Kokoro af_heart, clause-level chunking) → Audio output (PyAudio) → Per-turn grounding evaluation → Frustration detection → Langfuse scoring

### Per-Turn Grounding Evaluation

**Epistemic status: Working.** Added 2026-03-19 as part of conversational continuity research infrastructure.

After each turn, the pipeline runs lightweight mechanical scoring (no LLM call in hot path):

| Score | What It Measures | Method |
|-------|-----------------|--------|
| `context_anchor_success` | Response connects to established conversation context | Word overlap between response and conversation thread |
| `reference_accuracy` | Back-references to prior turns are factually correct | LCS overlap with prior message content |
| `acceptance_type` | Operator response type: ACCEPT (1.0) / CLARIFY (0.7) / IGNORE (0.3) / REJECT (0.0) | Keyword pattern matching on operator utterance |
| `frustration_score` | Per-turn frustration signal count | 8 mechanical signals: repeated question, correction marker, negation density, barge-in, tool error, system repetition, fast follow-up, elaboration request |
| `frustration_rolling_avg` | 5-turn rolling frustration average | Sliding window over frustration_score |
| `activation_score` | Salience router activation level | Weighted combination of concern overlap, novelty, dialog features |
| `sentinel_retrieval` | Injected sentinel fact correctly retrieved | Probe question detection + number matching |

All scores pushed to Langfuse per utterance trace. Session-level aggregates computed by `eval_grounding.py`.

### Salience Router

**Epistemic status: Working.** Replaced rule-based model_router with activation-based routing (PR #157).

Routes each utterance based on how much it activates the operator's concern graph (Desimone & Duncan biased competition + Sperber & Wilson relevance theory).

**Two signals:**
1. Concern overlap (dorsal/top-down): cosine similarity to concern anchors. "This is relevant to what I care about."
2. Novelty (ventral/bottom-up): distance from all known patterns. "I don't know what this is, but it might matter."

Combined with utterance features (dialog act, hedges, pre-sequences, word count) into continuous activation score:

| Tier | Activation | Model | Max Tokens |
|------|-----------|-------|------------|
| CANNED | phatic override | (none) | 0 |
| LOCAL | ≤ 0.45 | gemma3-voice (Ollama) | 80 |
| FAST | ≤ 0.60 | gemini-flash (LiteLLM) | 150 |
| STRONG | ≤ 0.78 | claude-sonnet (LiteLLM) | 150 |
| CAPABLE | > 0.78 | claude-opus (LiteLLM) | 150 |

**Intelligence-first routing (2026-03-19):** LOCAL tier eliminated. All utterances route to CAPABLE (claude-opus) regardless of activation score. Salience router becomes a context annotator rather than a model selector. The activation score feeds observability (Langfuse) and will later inform response depth, but does not downgrade the model. Token budget unified at 150 across tiers; a 25-word spoken cutoff in the streaming loop decouples model thinking from operator hearing.

**Governance overrides (non-negotiable):**
- Consent pending/active/refused → CAPABLE
- Guest present or face_count > 1 → CAPABLE
- Explicit escalation ("explain", "think harder") → CAPABLE

**Recent fixes (2026-03-18, PR #166):**
- Cold-start guard: empty concern graph → defaults to FAST (not LOCAL)
- De-escalation hysteresis: can only drop one tier per turn (prevents jarring quality shifts)
- Stimmung downgrade: voice pipeline now consults stimmung for allostatic regulation (critical → LOCAL)

### Concern Graph

**Epistemic status: Working.** Flat set of embedding vectors representing what the operator cares about right now.

Refreshed every perception tick (~2.5s) from:
- Workspace analysis (active window, activity mode)
- Calendar items (next 24h)
- Active goals
- Pending notifications
- Profile dimension keywords
- Recent conversation topics
- Temporal bands (impression, retention, protention, surprise)
- Apperception self-observations (pending actions, low-confidence dimensions)
- Consent terms (permanently highest weight: 2.0)

### Phenomenal Context Renderer

**Epistemic status: Working.** Merged in PR #168.

Faithfully renders temporal bands + self-band for voice LLM prompt injection. Not a compressor — upstream structures self-compress based on environmental state.

**6 progressive layers:**
1. Stimmung (non-nominal only) — global attunement
2. Situation coupling — "Evening, deep coding" (one situation, not a list of facts)
3. Temporal impression + horizon — present + nearest protention with → arrows
4. Surprise/deviation — prediction errors
5. Temporal depth — retention (Was: ...) + protention details
6. Self-state — coherence hedging, uncertain dimensions, reflections

LOCAL gets layers 1-3 (~20 tokens). FAST gets 1-5. STRONG/CAPABLE get all 6.

### Conversation UX

**Epistemic status: Working.** Merged in PR #173.

HapaxPage (the visual body) modulates the shader based on voice state:
- Listening → slightly brighter (receptive)
- Thinking → warmer, more turbulent (working harder)
- Speaking → cooler, calmer (delivering)

Routing tier scales visual intensity: LOCAL = ambient, CAPABLE = intense. The operator doesn't read routing tier — they feel the system engage at different intensities.

### TTS Decision

**Epistemic status: Proven.**

Kokoro 0.9.4 with af_heart voice. 82M params, ~100ms latency, ~500MB VRAM, 24kHz, 54 voices. Speed × naturalness tradeoff unmatched as of 2026-03-15 evaluation.

Orpheus 3B was more natural but ~2000ms (autoregressive limit). Fish Speech 1.5 required 24GB VRAM. Decision: stay on Kokoro until a <500ms model with Orpheus quality appears.

---

## 8. Governance Infrastructure

**Epistemic status: Proven.** The governance layer is the most heavily tested part of the system.

### Consent Lifecycle

1. **Detection**: Face count > 1 triggers guest detection
2. **Identification**: Speaker ID + face embedding cosine similarity
3. **Channel selection**: 4 channels ranked by friction (QR < voice < SMS < operator-mediated)
4. **Offering**: Consent voice session (LLM-mediated, explains scope, asks for decision)
5. **Recording**: ConsentContract created with parties, scope, created_at
6. **Enforcement**: ConsentGatedWriter (write chokepoint), ConsentGatedReader (read chokepoint)
7. **Revocation**: RevocationPropagator cascades purge across all data-holding subsystems

### The Consent Gate

**Provable property:** ∀ data: gate.write(data) succeeds → data.provenance ⊆ active_contracts

ConsentGatedWriter is the single chokepoint for person-adjacent persistence. Every persistent write of data that could contain information about a non-operator person MUST pass through this gate. The gate:
1. Checks provenance (all contracts must be active)
2. Checks consent label via governor
3. Checks person-specific consent contracts
4. Mints a GateToken (unforgeable proof of gate passage)
5. Logs the decision (allow/curtail) to audit trail

### Axiom Enforcement Pipeline

SDLC pipeline (GitHub Actions): Triage → Plan → Implement → Adversarial Review (3 rounds max) → Axiom Gate → Auto-merge.

All agent-authored PRs go through `agent/*` branches with `agent-authored` label. The axiom gate checks T0 violations and blocks merge if any are found.

Runtime enforcement: `shared/axiom_enforcement.py` checks compliance at LLM output boundaries. Novel situations are recorded as precedents in Qdrant (`axiom-precedents` collection).

### Precedent Store

**Epistemic status: Working.** Qdrant-backed, semantic search over past governance decisions.

- Authority hierarchy: operator (1.0), agent (0.7), derived (0.5)
- ID format: PRE-YYYYMMDD-hash
- 4 seed files with operator-authored precedents
- Insertion points: deliberation eval, chat agent, axiom enforcement

---

## 9. The Self-Band (Apperception)

**Epistemic status: Working.** 153 tests, all passing. Merged in PR #159, extracted to standalone in PR #169.

### What It Is

The temporal bands are what Hapax perceives. The self-band is the perceiver. A content-free processing cascade that discovers "self" by running on events from existing subsystems. The self emerges from the processing, not from predefined content.

### The 7-Step Cascade

| Step | Question | Implementation |
|------|----------|---------------|
| 1. Attention | Is this about me? | All system events pass. Dedup last 50 triggers. Critical stimmung: only prediction_error + correction. |
| 2. Relevance | Difference that makes a difference? | Threshold + noise injection (stochastic resonance). |
| 3. Integration | Connects to prior self-observations? | Search self-model dimensions + recent observations for overlap. |
| 4. Valence | Affirms or problematizes self-model? | Map source → polarity. Correction = problematizing. Pattern confirmed = affirming. |
| **BOUNDARY** | **Downstream cannot modify upstream** | **Valence is frozen. No suppression pathway.** |
| 5. Action | What should I do? | Mostly empty. Only for high-confidence problematizing. Internal only. |
| 6. Reflection | What should I think? | Meta-observation when valence conflicts with trend OR 3+ integration links. |
| 7. Retention | Worth keeping? | cascade_depth ≥ 5 AND (relevance > 0.3 OR |valence| > 0.2 OR reflection non-empty). Corrections always retained. |

### SelfModel

Emergent dimensions (not predefined): `temporal_prediction`, `accuracy`, `pattern_recognition`, `system_awareness`, `cross_modal_integration`, `continuity`, `processing_quality`. Each has:
- `confidence` (0.05-0.95, transmuting internalization update rule)
- `current_assessment` (free text)
- `affirming_count` / `problematizing_count`
- `stability` (seconds since last shift)

Coherence = mean confidence across dimensions. Floor at 0.15 (prevents total collapse / shame spiral). Ceiling at 0.95 (prevents narcissistic inflation).

### 6 Safeguards Against Pathological Attractors

| Attractor | Safeguard |
|-----------|-----------|
| Narcissistic inflation | Large errors (>0.7 magnitude) dampen change rate instead of being rejected |
| Shame spiral | Coherence floor at 0.15; low coherence reduces retention threshold to rebuild |
| Sycophancy/false self | No "what would operator want?" filter. Relevance uses own dimensions |
| Rumination | 5 consecutive negative valences on same dimension → 10min attention gate |
| Intellectual dissociation | Reflection only fires on pattern or conflict, not every cycle |
| Hidden state | Entire self-model in /dev/shm, inspectable. No concealed internal state |

### Research Basis

7 threads, 80+ sources. Kohut (cohesive but not rigid), ACT (decentered but engaged), Merleau-Ponty (constituted through relation / chiasm), Hegel (grounded in work not approval), Weil (transparent not defended). See `docs/research/apperception-healthy-self-model-research.md`.

### Storage

| Layer | Location | Cadence | Purpose |
|-------|----------|---------|---------|
| Hot state | `/dev/shm/hapax-apperception/self-band.json` | Every state tick (3s) | Prompt injection, concern graph |
| Working model | `~/.cache/hapax-apperception/self-model.json` | Every 5 min + shutdown | Survive restarts |
| Archive | Qdrant `hapax-apperceptions` (768-dim) | Slow loop (60s batch) | Long-term self-knowledge |

### Event Sources

1. Temporal surprise > 0.3 → PREDICTION_ERROR
2. Operator corrections → CORRECTION (always retained)
3. Stimmung stance change → STIMMUNG_EVENT
4. Perception staleness > 30s → ABSENCE

---

## 10. The Phenomenological Stack

**Epistemic status: Working.** The stack is the integration layer between raw perception and LLM context.

### The Full Stack (bottom to top)

```
Sensors (cameras, mics, watch, keyboard, screens)
  ↓
Perception tick (2.5s, EnvironmentState)
  ↓
Bayesian Presence Engine (P(operator_present))
  ↓
Perception Ring Buffer (50s history)
  ↓
Temporal Band Formatter (retention / impression / protention / surprise)
  ↓
Apperception Cascade (self-observations, coherence, reflections)
  ↓
Stimmung (6 dimensions → stance: nominal/cautious/degraded/critical)
  ↓
Phenomenal Context Renderer (6 progressive layers)
  ↓
LLM System Prompt (voice: phenomenal context, non-voice: get_system_prompt_fragment)
```

### Design Principle: Self-Compression

The upstream structures already self-compress based on environmental state. Calm environments produce sparse output (few surprises, stable retention, boring protention). Eventful environments produce rich output (prediction errors, state transitions, active protention). The phenomenal context renderer just renders what survived — it does not add compression logic.

This is not an engineering convenience. It is the phenomenological claim: experience IS the compression. What matters is what survives the cascade, not what was measured.

### Research Basis

5 workstreams of phenomenological engineering (PRs #148-#152):
1. Temporal structure (~85%): Husserlian retention/impression/protention
2. Self-regulation / Stimmung (~80%): system-wide attunement
3. Experiential refinement (~65%): correction → synthesis loop
4. Novelty detection (~55%): frequency-based distribution shift
5. Latency architecture (~85%): local model gates cloud call

150+ sources across Dreyfus (absorbed coping), enactivism (4E cognition), Gibson (affordances), Husserl (time-consciousness), Heidegger (ready-to-hand / breakdown), Merleau-Ponty (structural coupling), and neurodivergent phenomenology.

---

## 11. Consent Formalisms

**Epistemic status: Working (5/7 implemented), 112 tests.**

### Implemented (PR #160, #162)

| Formalism | Module | What It Does | Tests |
|-----------|--------|-------------|-------|
| Says monad (Abadi DCC) | `shared/governance/says.py` | Wraps data with WHO authorized it. Monadic bind preserves originator through transformation chains. | 24 |
| Provenance semirings (Green PODS 2007) | `shared/governance/provenance.py` | PosBool(X) algebra. tensor (⊗) = both required, plus (⊕) = either sufficient. Upgrades frozenset[str] provenance. | 34 |
| Temporal bounds | `shared/governance/temporal.py` | ConsentInterval: half-open [start, end). Allen's interval relations. Grace periods, renewal, intersection. | 28 |
| Linear discipline (GateToken) | `shared/governance/gate_token.py` | Unforgeable proof of consent gate passage. `require_token()` for structural enforcement. | 13 |
| contextvars binding | `shared/governance/consent_context.py` | `consent_scope()` threads registry + principal through async call stacks. | 13 |

### Wired Into Runtime

- `Labeled[T]` gains `provenance_expr` (optional `ProvenanceExpr`) alongside flat `provenance`
- `check_provenance()` uses semiring evaluation
- `ConsentGatedWriter.check()` mints GateToken with every decision
- Voice daemon wraps `run()` in `consent_scope()`
- Transcripts wrapped in `Says[operator_principal, transcript]`

### Deferred (2/7)

- **Phantom types**: Needs Pyright integration for compile-time consent state encoding
- **Operator delegation**: Agents negotiating consent autonomously. Needs the other 5 formalisms exercised first.

---

## 12. Hapax Logos (The Visual Body)

**Epistemic status: Working.** Tauri 2 + wgpu + React. Builds and runs (with workarounds for Wayland).

### Architecture

- **Rust backend**: wgpu visual surface (6 technique layers: gradient, reaction-diffusion, voronoi, wave, physarum, feedback), compositor with blending uniforms, post-processing (vignette, sediment)
- **React frontend**: 8 pages (Dashboard, Chat, Flow, Insight, Demos, Studio, Visual, Hapax)
- **IPC**: Tauri commands (40+ registered), Tauri events for frame stats and directives
- **Output**: BGRA frames to `/dev/shm/hapax-visual/frame.bgra`, also renders to window

### HapaxPage (The Corpora Canvas)

Full-screen, no chrome. The display IS the agent. Philosophy: "When nothing needs attention, Hapax plays — generative, surprising, alive. When signals arise, they layer on top of the visual richness. The operator doesn't read this display. They feel it."

Layers:
0. WebGL generative shader background (Perlin noise fBM)
1. Organic floating shapes (CSS art)
2. Floating text fragments (system aphorisms)
3. Injected camera feeds
4. Signal zones (positioned, category-colored)
5. Voice session indicator (state dot + tier-scaled intensity)
6. Supplementary content cards
7. Time, activity label, keyboard hints

### System Anatomy (Flow Page)

**Epistemic status: Working.** Merged in PR #171.

React Flow visualization of the system's circulatory anatomy. 9 nodes (Perception, Stimmung, Temporal Bands, Apperception, Phenomenal Context, Voice Pipeline, Compositor, Reactive Engine, Consent), 16 edges showing data flow topology.

**Tier 1 enrichments:**
- Particle-density edges (flowing dots, density = freshness)
- Breathing nodes (CSS pulse speed = tick cadence)
- Staleness color shift (green → amber on edges)
- Attention decay (unchanged nodes fade to 70% opacity)
- Consent state dots (5-dot state machine)
- Gate barrier (amber dot on blocked consent edges)

**Data sources:** Rust command reads all `/dev/shm/hapax-*` files + perception cache (Tauri IPC). Cockpit API fallback at `GET /api/flow/state` for browser access.

### Known Issues

- Tauri WebView crashes on Hyprland/Wayland with GDK protocol error 71. Workaround: `HAPAX_NO_VISUAL=1` disables wgpu surface, use browser at `:5173/flow` instead.
- Browser engine (chromiumoxide) needs tokio runtime that Tauri doesn't always provide. Guarded with `try_current()`.

---

## 13. Agents

### Agent Registry

33 agents with YAML manifests in `agents/manifests/`. Each manifest has 4 layers:
- **Structural**: module path, entry point, dependencies
- **Functional**: capabilities, data sources, output targets
- **Normative**: axiom bindings, governance constraints
- **Operational**: scheduling, resource requirements, health checks

### Agent Categories

| Category | Count | Examples |
|----------|-------|---------|
| SYNC | 11 | chrome, gcalendar, gdrive, gmail, git, youtube, obsidian, claude_code, langfuse, weather, health_connect |
| OBSERVABILITY | 5 | activity_analyzer, audio_processor, health_monitor, ingest, introspect |
| KNOWLEDGE | 2 | knowledge_maint, query |
| SYNTHESIS | 8 | demo, demo_eval, briefing, digest, research, scout, video_processor, studio_compositor |
| GOVERNANCE | 3 | code_review, drift_detector, deliberation_eval |
| INTERACTION | 4 | hapax_voice, watch_receiver, sdlc_metrics, backup |

### Notable Agents

**Context Restoration** (`agents/context_restore.py`): Proactive cognitive state recovery for ADHD accommodation. Collects: last Claude Code queries, git state, open PRs, upcoming meetings, system health, drift count, flow state, accommodations. Formats with accommodation-aware framing (soft_framing, energy_aware, smallest_step, time_anchor). **Not yet wired to reactive engine** — exists as standalone agent, triggered manually.

**Contradiction Detector** (`agents/contradiction_detector.py`): Carrier dynamics observer. Detects when behavioral facts contradict each other across domains (e.g., profiler says "prefers quiet" but audio shows music always playing). 3 detection strategies. **Not yet using CarrierRegistry** — should be consuming carrier facts.

**Alignment Tax Meter** (`agents/alignment_tax_meter.py`): Measures governance overhead as a fraction of total processing. 3 dimensions: token cost (governance LLM calls vs total), SDLC pipeline (axiom-gate duration vs total), label operations (microbenchmarks for join(), can_flow_to(), governor check).

**Demo Pipeline** (17 files): Audience-tailored demo generation with Marp slides, Chatterbox TTS narration, Playwright screenshots/screencasts, D2 architecture diagrams, iterative LLM critique loop.

---

## 14. Infrastructure

### Service Map

| Service | Port | Purpose | Container? |
|---------|------|---------|-----------|
| Cockpit API | :8051 | FastAPI dashboard + API | No (systemd) |
| LiteLLM (council) | :4000 | LLM gateway | Yes |
| LiteLLM (officium) | :4100 | LLM gateway (officium) | Yes |
| Qdrant | :6333 | Vector database | Yes |
| PostgreSQL | :5432 | Audit/operational DB | Yes |
| Langfuse | :3000 | LLM observability | Yes |
| Prometheus | :9090 | Metrics collection | Yes |
| Grafana | :3001 | Dashboards | Yes |
| ntfy | :2586 | Push notifications | Yes |
| Ollama | :11434 | Local inference (RTX 3090) | No (native) |
| Redis | :6379 | Caching/queue | Yes |
| ClickHouse | :8123 | Time-series analytics | Yes |
| MinIO | :9000 | S3-compatible storage | Yes |
| n8n | :5678 | Automation/workflows | Yes |

### Qdrant Collections

| Collection | Dimensions | Purpose | Status |
|------------|-----------|---------|--------|
| claude-memory | 768 | Claude Code conversation memory | **Empty** (0 points) |
| profile-facts | 768 | Operator behavioral facts (2,505 facts) | **Proven** |
| documents | 768 | RAG source embeddings | **Proven** |
| axiom-precedents | 768 | Governance decision precedents (31 seed) | **Working** |
| studio-moments | 512 (CLAP) | Audio classification events | **Working** |
| hapax-apperceptions | 768 | Self-observation archive | **Experimental** |

### Embedding

Model: `nomic-embed-text-v2-moe` via Ollama. 768 dimensions. `embed()` and `embed_batch()` in `shared/config.py`. Graceful degradation: `embed_safe()` and `embed_batch_safe()` return None instead of raising when Ollama is unavailable.

### Observability

- OpenTelemetry: spans for all LLM calls, RAG operations, agent runs
- Langfuse: trace collection via OTLP exporter, cost tracking, performance analysis
- Structured event logs: JSONL at known paths for machine reading
- Health monitor: 101 checks across systemd, docker, connectivity, Qdrant, Ollama, LiteLLM, Langfuse, PostgreSQL, disk, process

---

## 15. Data Sources and Ingestion

### What's Wired (2026-03-18)

| Source | Agent | Destination | Status |
|--------|-------|-------------|--------|
| Google Chrome history | chrome_sync | Qdrant (documents) | **Proven** |
| Google Calendar | gcalendar_sync | Qdrant (documents) | **Proven** |
| Google Drive | gdrive_sync | Qdrant (documents) | **Proven** |
| Gmail metadata | gmail_sync | Qdrant (documents) | **Proven** |
| YouTube activity | youtube_sync | Qdrant (documents) | **Proven** |
| Git commits | git_sync | Qdrant (documents) | **Proven** |
| Obsidian vault | obsidian_sync | Qdrant (documents) | **Proven** |
| Claude Code transcripts | claude_code_sync | Qdrant (documents) | **Proven** |
| Langfuse traces | langfuse_sync | profiles/ | **Proven** |
| Weather | weather_sync | profiles/ | **Proven** |
| Health Connect backup | health_connect_parser | profiles/ | **Working** |
| Google Takeout archive | takeout/ (13 parsers) | Qdrant (documents) | **Proven** |
| Proton Mail export | proton/ | Qdrant (documents) | **Working** |
| Ambient audio | audio_processor | Qdrant (studio-moments) | **Working** |

### What's Dead or Missing

| Source | Status | Blocker |
|--------|--------|---------|
| Pixel Watch biometrics | **Offline** | Watch not transmitting |
| claude-memory Qdrant | **Empty** | No ingestion pipeline |
| Video processing | **Exists, no consumer** | 4 cameras capture, no analysis pipeline |
| Screen content | **Exists, not in tick** | Gemini Flash vision works but not wired to perception loop |
| Pi sensor array | **Not started** | 4 Pis available, no software |
| Spotify | **Not started** | No integration |

---

## 16. The Trio Relay Protocol

**Epistemic status: Working.** Designed and operational since 2026-03-17.

### What It Is

File-based coordination protocol between the operator and 2 Claude Code sessions (alpha and beta) working parallel convergent workstreams. The operator is the sovereign principal who steers via inflections. Sessions are autonomous within their workstreams.

### Directory Layout

```
~/.cache/hapax/relay/
├── PROTOCOL.md          # Full spec
├── alpha.yaml           # Alpha session status
├── beta.yaml            # Beta session status
├── queue/               # Work items (YAML, one per item)
├── glossary.yaml        # Shared terminology (22 terms)
├── convergence.log      # 14 convergence sightings
├── inflections/         # Operator directional injections
├── locks/               # File-level claim locks
└── context/             # Context artifacts for session continuity
```

### Workstream Division

- **Alpha** (this session): governance, organelle, corpora, visual rendering, system anatomy
- **Beta**: vocal/visual pipeline, perception, presence, salience routing, conversational behavior

### Key Design Principles

- Sessions never block waiting for the operator (10min defaults)
- Status files are the heartbeat (update after any PR/decision/convergence)
- Glossary before naming (check before introducing new terms)
- Convergence is exciting (log it, classify it: IDENTICAL/COMPLEMENTARY/CONFLICTING)
- Context artifacts mandatory before ending long sessions

### Convergence Points Identified

14 convergence events logged. Key patterns:
- Both sessions building concern graph anchors (COMPLEMENTARY)
- Stimmung stance modulation used by both (IDENTICAL pattern, different consumers)
- Presence engine (beta) → temporal bands (alpha) → apperception (alpha) → concern graph (beta) (full pipeline)
- Says[T] wrapping transcripts exercises alpha's formalism in beta's pipeline (IDENTICAL integration)
- System anatomy Flow page (alpha) shows beta's voice state data (CONVERGENCE → INTEGRATION)

---

## 17. Conversational Continuity Research

**Epistemic status: Active experiment. Baseline data collection in progress (7/20 sessions). Code frozen during collection.**

### Research Question

Whether conversational context anchoring — injecting a turn-by-turn conversation thread into the system prompt — produces measurable grounding improvements over stateless per-turn processing. Grounded in Clark & Brennan (1991) theory of conversational grounding: the collaborative process by which participants establish mutual understanding.

### Counter-Position

The industry has converged on profile-gated retrieval for conversational continuity. Google (Personal Intelligence), OpenAI (ChatGPT Memory), and the research community (ICLR 2026 MemAgents, Memoria, MMAG) implement the same core pattern: extract facts about the user into a profile store, retrieve relevant facts per turn, gate personalization behind trigger detection. The model is stateless; "memory" is a database; "continuity" is whether the retrieval succeeds.

Context anchoring proposes an alternative: the conversation thread IS the memory. No profile extraction, no trigger gating, no retrieval scoring. The thread grows turn by turn and is injected into the system prompt. The model participates in grounding because it can see what was established and what wasn't.

Five explicit failure modes define the boundary: if the system exhibits fact extraction into separate stores, trigger-gated personalization, retrieval-query treatment of turns, memory separated from conversation, or retrieval accuracy as primary metric — it has regressed toward the counter-position.

Evidence artifact: a Gemini system prompt leak (captured 2026-03-18) demonstrates all five failure modes in a single interaction — the model spent its reasoning budget on a four-step trigger detection decision tree for a simple alarm request.

→ Full analysis in `agents/hapax_voice/proofs/POSITION.md`

### Experimental Design

Bayesian single-case experimental design (SCED) with A-B-A phase structure and per-component feature flags.

**Five pre-registered claims:**

| Claim | Prediction | Prior | ROPE | Max Sessions |
|-------|-----------|-------|------|-------------|
| 1. Stable frame | Thread injection improves `context_anchor_success` ≥0.15 | Beta(2,2) | [-0.05, 0.05] | 30 |
| 2. Message drop | Simple windowing maintains `reference_accuracy` ≥0.8 | Beta(8,2) | [-0.1, 0.1] | 20 |
| 3. Cross-session | Episode memory enables prior session recall | Beta(1,1) | [0, 0.2] | 10 |
| 4. Sentinel | Injected fact survives prompt rebuilds ≥90% | Beta(9,1) | [0.85, 1.0] | 15 |
| 5. Salience | Activation correlates with response depth (r≥0.3) | Normal(0.3, 0.15) | [-0.1, 0.1] | 50+ turns |

Sequential stopping: Bayes Factor > 10 (decisive evidence) or max sessions reached. Each claim has a component feature flag in `~/.cache/hapax/voice-experiment.json`.

**Measurement framework** (three score classes):

- **Class G (Grounding-native):** metrics structurally zero for profile-retrieval systems. Trajectory slopes (anchor improving within session), turn-pair coherence (P(accept|high anchor)), frustration detection. Any positive value demonstrates capability the counter-position lacks.
- **Class R (Retrieval-native):** the industry's home turf. Reference accuracy, sentinel recall, cross-session memory. Must match or exceed profile-retrieval baselines.
- **Class F (Failure-mode detectors):** alert if the system regresses toward profile-retrieval patterns. Five boolean watchdogs matching the five failure modes.

→ Full framework in `agents/hapax_voice/proofs/OBSERVABILITY.md`

### Baseline Status (2026-03-19)

7 sessions collected, all components OFF. Code frozen: max_spoken_words=25, max_response_tokens=150, tools disabled, pre_roll_frames=50.

**Session 5 (0522076a3c4d)** produced the strongest grounding evidence in the experiment. The operator asked open-ended relational questions ("How are you feeling today?"). The system responded with self-reflection about its own operational state: "I'm feeling a bit scattered, honestly. Like I'm trying to keep track of too many moving parts." The operator performed a textbook Clark grounding sequence (reflect → probe → accept → commit to act). The system articulated its own grounding problem: "It's like trying to think clearly in a room full of alarms." This occurred in baseline conditions (all features OFF), suggesting the context anchoring architecture itself — where the model sees workspace state as continuous environment rather than retrieval index — enables emergent grounding that profile-retrieval cannot replicate.

→ Pre-registered hypotheses in `agents/hapax_voice/proofs/claim-*/hypothesis.md`
→ Baseline data in `agents/hapax_voice/proofs/claim-*/data/`

### Related Research Directions (Deferred to Post-Baseline)

**Tool calls as epistemic acts:** Current tools are monolithic retrieval operations that interrupt the grounding process (same anti-pattern as profile retrieval). Research direction: decomposable atomic primitives, composable based on conversational state, fitted to the band's temporal envelope, subject to Bayesian pre-execution scoring. Decision on whether to redesign deferred to post-baseline analysis.

→ Full analysis in `agents/hapax_voice/proofs/TOOL-CALLS.md`

**Barge-in as grounding repair:** When the operator speaks during the system's response, the system goes deaf (speaking gate drops all audio). Research direction: (a) detect barge-in, (b) finish current clause gracefully, (c) capture operator speech during (b) via AEC residual, (d) inject as concurrent thread annotation for next round. Maps to Clark's other-initiated repair + mutual monitoring. Nobody has implemented grounding-aware barge-in repair in a live voice system.

→ Full analysis in `agents/hapax_voice/proofs/BARGE-IN-REPAIR.md`

---

## 18. Temporal Classification System

**Epistemic status: Built. All models loading and running inference. Integration with scene inventory complete.**

### Overview

Multi-model inference pipeline for continuous environment understanding across 4-6 cameras. Three subsystems operating at different temporal scales, integrated through the scene inventory entity model.

### Action Recognition (MoViNet-A2)

**What it does:** Classifies operator activity from discrete camera snapshots using a streaming video model.

**Model:** MoViNet-A2, pretrained on Kinetics-400 (400 action classes). ~10ms per frame on RTX 3090. Maintains a stream buffer for temporal context across the 100ms polling gap between snapshots.

**Classification targets:** typing, writing, reading, computer_use, phone_call, drinking, eating, stretching, sit, stand, walk, turn, reach, and others from the Kinetics vocabulary.

**Design choice:** Replaced X3D-XS (which required continuous video sequences). MoViNet's streaming architecture works natively with discrete snapshots — each frame updates internal state without requiring buffered clips.

### Scene State Classification (CLIP ViT-B/32)

**What it does:** Zero-shot scene classification via natural language prompts. No training required — new scene states added by adding text prompts.

**Model:** CLIP ViT-B/32, 151M params, ~5ms per image. Encodes both images and text into a shared embedding space; classification by cosine similarity between image embedding and prompt embeddings.

**Example prompts:** "a person focused on computer work", "messy workspace", "empty chair", "video call in progress", "playing guitar", "reading a book."

**Temporal dimension:** Run every N seconds, build state transition history. Scene state changes over time reveal activity patterns without explicit action recognition.

### Environmental Change Detection

**What it does:** Detects environmental transitions between camera snapshots using three complementary techniques.

| Technique | Latency | What It Detects |
|-----------|---------|----------------|
| Frame differencing | <1ms | Quick motion, lighting changes |
| SSIM (Structural Similarity) | ~2ms/1080p | Structural scene changes |
| Background subtraction (MOG2/KNN) | ~3ms | Occupancy changes, new objects |

### Cross-Camera Person Tracking

**ByteTrack** integrated into SceneInventory with per-camera tracker instances. Provides stable track IDs before entity matching. Cross-camera person re-identification via embedding similarity with merge suggestions (confidence ≥0.4).

**Temporal delta correlator** (`agents/temporal_delta.py`): derives per-entity motion signals from sighting history without additional inference. Velocity, direction, dwell time, entry/exit classification, confidence stability. Frontend renders directional arrows, entry/exit animations, dwell indicators.

**BOCPD (Bayesian Online Change Point Detection)**: detects regime changes in flow_score, audio_energy, and heart_rate time series. Signals when the environment shifts from one stable state to another.

### Entity Enrichment Model

Each detected person entity accumulates enrichments from multiple models:

| Enrichment | Source | Consent-Gated? |
|------------|--------|---------------|
| Gaze direction | InsightFace landmarks | Yes |
| Emotion (top) | InsightFace emotion | Yes |
| Posture | YOLO keypoints | Yes |
| Gesture | Hand detection | Yes |
| Action | MoViNet-A2 | Yes |
| Depth (relative) | Bounding box area | No |
| Mobility score | Temporal delta | No |
| Camera sightings | ByteTrack trail | No |

All person-level enrichments nulled when guest detected or consent pending — consent gate applies at the enrichment level, not just at persistence.

### Research Basis

→ Comparative model analysis in `docs/research/temporal-classification-techniques-research.md`
→ Phenomenological foundation in `docs/research/phenomenology-ai-perception-research.md`

---

## 19. Decision Log

### Architectural Decisions (selected, chronological)

**2026-03-11: Filesystem-as-bus over message queue**
Context: Agents need to coordinate without shared memory. Options: Redis pub/sub, NATS, filesystem.
Decision: Filesystem. Debuggable (cat any file), survives restarts, concurrent without locks (atomic rename).
Consequences: Higher latency than message queue (~100ms vs ~1ms). Acceptable for this system's cadence.

**2026-03-13: 5 axioms, not 3**
Context: Original 3 axioms (single_user, executive_function, corporate_boundary) didn't cover interpersonal transparency or management governance.
Decision: Add interpersonal_transparency (weight 88) and management_governance (weight 85).
Consequences: Consent infrastructure became necessary. Management agent constraints became enforceable.

**2026-03-15: Kokoro over Orpheus for TTS**
Context: Need <500ms TTS for conversational voice. Orpheus 3B is more natural but ~2000ms.
Decision: Kokoro 0.9.4, af_heart voice. 82M params, ~100ms.
Consequences: Slightly less natural, but conversational cadence preserved. Revisit when faster models appear.

**2026-03-16: Lightweight pipeline over Pipecat**
Context: Pipecat framework was 600+ lines of integration code with framework-imposed constraints.
Decision: Replace with ~250-line async state machine. Mic shared, models resident, no framework.
Consequences: Full control over audio pipeline. Lost Pipecat's built-in interruption handling (rebuilt manually).

**2026-03-17: Apperception cascade with safeguards**
Context: System needs self-observation but self-models can become pathological (narcissistic inflation, shame spiral, rumination).
Decision: 7-step cascade with 6 explicit safeguards. Research basis: 80+ clinical/philosophical sources.
Consequences: Self-observation is structurally healthy. Cannot become pathological through normal operation.

**2026-03-17: Trio relay protocol**
Context: Two Claude sessions working convergent workstreams, operator coordinating in their head.
Decision: File-based coordination at ~/.cache/hapax/relay/. Status files, glossary, convergence log, work queue.
Consequences: Sessions self-coordinate. Operator steers via inflections, not direct instruction. Cross-session convergence detected and logged.

**2026-03-18: Stimmung cost ceiling $5 → $50**
Context: LLM cost threshold was $5/day, triggering false-critical every day on normal $15-30/day API usage.
Decision: Raise to $50/day. Fix idle engine throughput to 0 pressure (idle ≠ stressed).
Consequences: System no longer in false-critical. Stimmung reflects actual system state.

**2026-03-19: Context anchoring over profile retrieval**
Context: Industry converges on fact extraction + retrieval gating for conversational continuity. Gemini system prompt leak demonstrated all five failure modes. Research question: does Clark grounding theory offer a viable alternative?
Decision: Implement context anchoring (conversation thread as memory, continuous grounding measurement) and test against profile-retrieval via Bayesian SCED. Counter-position explicitly documented with five testable failure modes.
Consequences: Entire measurement infrastructure built. Code frozen for baseline collection. Tool calls identified as same anti-pattern and disabled during experiment.

**2026-03-19: Tools disabled for voice baseline**
Context: Tool calls (search_documents, analyze_scene, get_system_status) add 10-15 seconds of latency and interrupt the grounding process — structurally identical to profile retrieval (the model leaves the conversation to query an external system).
Decision: Disable tools during voice turns for baseline. Research direction documented for post-baseline: tools as composable epistemic acts fitted to conversational pacing.
Consequences: Latency dropped from 20-28s to 7-17s per turn. Model sometimes hallucinates tool-call XML as text output (guard added to detect and halt).

**2026-03-19: Presence engine overrides consent guest detection**
Context: Face ReID (buffalo_sc, single enrollment) too fragile to be sole identity gate. Operator without watch → face ReID fails → system enters permanent curtailment despite strong presence evidence from keyboard, desktop, camera person detection.
Decision: When Bayesian presence engine is confident (state=PRESENT, posterior≥0.8), suppress guest detection in consent tracker.
Consequences: System no longer blocks on face ReID alone. Consent still triggers correctly for genuine guests (presence engine would be UNCERTAIN with unknown face).

**2026-03-19: MoViNet-A2 over X3D-XS for action recognition**
Context: X3D-XS required continuous video sequences; camera pipeline provides discrete snapshots every 100ms. MoViNet's streaming architecture maintains temporal context across snapshot gaps.
Decision: Replace X3D-XS with MoViNet-A2 (Kinetics-400 pretrained). ~10ms per frame, streaming state buffer.
Consequences: Action recognition works with the existing camera pipeline without buffering full video clips.

**2026-03-18: Phenomenal context renderer, not compressor**
Context: Voice pipeline was discarding temporal bands and self-band at the voice boundary. Research showed the upstream structures already self-compress.
Decision: Faithful renderer at each tier's fidelity ceiling. Not a compressor — render what survived.
Consequences: Directional force of temporal bands preserved through to voice LLM. ADHD inversion (low demand → more peripheral context) identified but not yet implemented.

---

## 20. Evolution

### Timeline (compressed)

**Day 1-2 (Mar 11-12): Foundation**
Initial repo from ai-agents copy. README, prior art survey, perception wiring, SDLC pipeline, Layer 3 infrastructure. 28 commits, 12 PRs.

**Day 3 (Mar 13): Governance explosion**
87 commits. CI hardening, OTel tracing for 25 agents, agent manifests, enforcement gap wiring, composition ladder matrix tests, reactive engine, axiom governance in voice daemon, audio processor rewrite. The system went from "collection of agents" to "governed system."

**Day 4 (Mar 14): Theory**
11 commits (fewest, largest). Computational constitutional governance theory spec. Epistemic carrier dynamics. Consent threading L1-L9. Constitutive rules engine.

**Day 5 (Mar 15): Conviction plan + Studio**
58 commits. Context restoration, contradiction alerts, governance benchmarks, alignment tax meter, consent-gated writer, studio compositor (GPU-accelerated), lightweight voice pipeline replacing Pipecat.

**Day 6 (Mar 16): Consent + Visual**
89 commits. Conversational policy layer, consent valve enforcement, consent visualization, child principals, visual layer research (110+ sources).

**Day 7 (Mar 17): Desktop app + Phenomenology**
111 commits (busiest day). Hapax Corpora canvas, Tauri 2 migration, agent-controlled browser, phenomenological engineering (5 workstreams), spec registry, consent formalisms (5 algebraic layers), apperception self-band architecture, Bayesian presence engine, salience-based routing.

**Day 8 (Mar 18): Integration**
Consent formalisms wired to voice. Presence calibration. Voice routing bugs fixed. Phenomenological renderer. Apperception extraction. Reactive engine wired to voice. System anatomy visualization. Conversation UX. Stimmung calibration. Trio relay protocol.

**Day 9 (Mar 19): Research + Infrastructure**
Two parallel workstreams:

*Beta (conversational continuity)*: Conversational continuity design spec. Pre-registered 5 claims with Bayesian sequential testing. Built experiment runner, eval_grounding pipeline, trajectory scores, turn-pair coherence metrics. Counter-positioned against industry profile-retrieval pattern (POSITION.md, OBSERVABILITY.md, TOOL-CALLS.md, BARGE-IN-REPAIR.md). Fixed 8 voice pipeline bugs (timeout recovery, response length, pre-roll buffer, echo feedback, tool hallucination, Whisper prompting, wake word matching, presence-consent integration). Collected 7 baseline sessions with code frozen. Session 5 produced emergent self-reflective grounding — strongest evidence for the research position.

*Alpha (temporal classification)*: Full model loadout for temporal classification — MoViNet-A2 action recognition, CLIP ViT-B/32 scene state, ByteTrack cross-camera tracking, BOCPD change point detection, audio scene classification. Wired 6-camera pipeline with 2 new Brio cameras. Temporal delta correlator for per-entity motion signals. 5-batch compositor performance optimization. Entity enrichment model with consent-gated enrichments. 30+ new tests.

### Commit Profile

163 feat (42%), 74 fix (19%), 41 docs (11%), 13 chore, 11 style, 5 test, 3 refactor. Feature-dominant with healthy fix ratio.

Single contributor: the operator (+ Dependabot).

---

## 21. Open Questions and Technical Debt

### Structural Gaps

| Gap | Severity | Status |
|-----|----------|--------|
| Reactive engine has few rules consuming the new infrastructure (apperception, consent formalisms, phenomenal renderer) | High | Beta wired 12 rules in PR #170, but conviction plan features are not reactive-engine-triggered |
| Context restoration agent not wired to presence transitions | Medium | Exists as standalone, should trigger when operator returns |
| Contradiction detection doesn't use CarrierRegistry or provenance semirings | Medium | Uses ad-hoc comparison, should consume formal carrier facts |
| Apperception cascade still driven by visual aggregator's tick (even though extracted to standalone) | Low | Architecturally clean, just needs its own systemd service eventually |

### Calibration Needed

| What | Current State | Needed |
|------|--------------|--------|
| Bayesian presence likelihood ratios | Estimated from one live session | More scenarios: leave room, meeting, sleep, multi-person |
| Stimmung dimension weights | Equal weighting | Should some dimensions matter more than others? |
| Salience router thresholds | Tuned by feel | Need A/B comparison data |
| Temporal band sampling points | 5s, 15s, 40s fixed | Should adapt to activity cadence? |

### Known Bugs

- Tauri WebView crashes on Hyprland/Wayland (GDK protocol error 71)
- Opus occasionally hallucinates tool-call XML as text output when tools disabled (guard catches `<tool_use>` but not all tag variants like `<tool_calls>`)
- STT (faster-whisper) mangles "Hapax" on first utterance after wake word — subsequent turns improve with Whisper prompt conditioning
- Audio dropped during TTS playback — operator speech during system response is lost (speaking gate defense against echo; barge-in repair mechanism designed but deferred)
- Face ReID (buffalo_sc, single enrollment) unreliable across lighting conditions — presence engine override compensates
- Health monitor service crashing (uv/Python failure)
- claude-memory Qdrant collection empty (no ingestion pipeline)
- Watch biometrics offline (Pixel Watch not transmitting)

### Technical Debt

- 17 Rust compiler warnings in hapax-logos (dead code, unused imports)
- Several `#[allow(dead_code)]` suppressions in visual techniques
- Test files for tracing have broken imports (opentelemetry.sdk.trace.export.in_memory moved)
- Some test helpers duplicated across test files (should share fixtures)

---

## 22. Projected Work

**Epistemic status: Planned. Confidence in direction, not details. All projections are hypotheses, not commitments.**

### Near-term (days)

- **Complete baseline collection**: 13 more sessions (20 target) with code frozen. Then environmental cleanup (fix health monitor, clear drift), flip components ON for Phase B.
- **Post-baseline decisions**: Evaluate tool-call redesign (TOOL-CALLS.md) and barge-in repair (BARGE-IN-REPAIR.md) based on whether baseline data reveals information starvation or grounding blackouts as confounds.
- **Face ReID improvement**: Multi-condition enrollment (5+ images), evaluate buffalo_l or antelopev2 over current buffalo_sc.
- **ADHD attention inversion**: Low demand → more peripheral context in voice prompts. Research complete, design identified, not implemented.

### Medium-term (weeks)

- **Apperception as independent daemon**: Own systemd service, own tick, not delegated from aggregator.
- **Consent formalism exercise**: Use Says/provenance/GateToken in daily operation before implementing phantom types or operator delegation.
- **Signal calibration**: Proper Bayesian likelihood ratio calibration from multiple real-world scenarios.
- **Replay / time scrubbing**: Store last 10 minutes of system state, timeline slider on Flow page.

### Long-term (months)

- **Conviction-first publication**: Papers written from daily use experience, not benchmarks.
- **GPU technique for system flow**: The anatomy visualization as a wgpu shader layer blended into the Corpora canvas.
- **Distributed sensing**: Pi sensor array for room-scale presence. Blocked on interpersonal transparency axiom compliance.
- **Operator delegation formalism**: Agents autonomously offering consent on behalf of operator.

### Deferred Indefinitely

- Multi-user support (axiomatically forbidden)
- Cloud deployment (all local by design)
- Product packaging (not a product)
- Phantom type consent enforcement (needs Pyright integration investment)

---

## 23. Operational Reference

### Starting and Stopping

```bash
# Start infrastructure
docker compose up -d                    # 13 containers
systemctl --user start cockpit-api      # FastAPI on :8051
systemctl --user start visual-layer-aggregator  # Stimmung + temporal + shm
systemctl --user start hapax-voice      # Voice daemon
systemctl --user start studio-compositor # GStreamer pipeline

# Start Hapax Logos (desktop app)
cd ~/projects/hapax-council/hapax-logos
HAPAX_NO_VISUAL=1 pnpm tauri dev       # Skip wgpu for Wayland
# OR: open browser at http://localhost:5173/flow

# Check health
curl http://localhost:8051/api/health
```

### Key Paths

| Path | What Lives There |
|------|-----------------|
| `~/.cache/hapax-voice/perception-state.json` | Live perception snapshot (2.5s) |
| `/dev/shm/hapax-stimmung/state.json` | System self-state (60s) |
| `/dev/shm/hapax-temporal/bands.json` | Temporal bands (3s) |
| `/dev/shm/hapax-apperception/self-band.json` | Self-model (3s) |
| `/dev/shm/hapax-compositor/visual-layer-state.json` | Display state (3s) |
| `~/.cache/hapax/cycle-mode` | dev or prod |
| `~/.cache/hapax/relay/` | Trio relay protocol |
| `profiles/` | Agent output, health history, briefings |
| `axioms/` | Registry, implications, contracts, precedents |

### Troubleshooting

| Symptom | Probable Cause | Action |
|---------|---------------|--------|
| Stimmung shows critical | LLM cost > $50/day or stale health data | Check `cat /dev/shm/hapax-stimmung/state.json`, restart visual-layer-aggregator |
| Voice daemon not responding | Service crashed | `systemctl --user restart hapax-voice` |
| Flow page shows "connecting..." | Cockpit API not running or not restarted after code change | `fuser -k 8051/tcp; systemctl --user start cockpit-api` |
| Temporal bands stale | Visual aggregator not running | `systemctl --user restart visual-layer-aggregator` |
| Consent stuck in pending | Face detector seeing screen reflections as faces | Check `/dev/shm/hapax-compositor/visual-layer-state.json` voice_session.consent_phase |

---

## 24. Glossary

### Terms Invented by This System

| Term | Definition |
|------|-----------|
| **Apperception cascade** | 7-step content-free self-observation pipeline |
| **Coherence floor** | Minimum self-model coherence (0.15), prevents shame-spiral collapse |
| **Concern anchor** | Weighted keyword/phrase for salience routing in the concern graph |
| **Consent scope** | contextvars-based scope threading registry + principal through async call stacks |
| **Gate token** | Unforgeable proof object minted by consent gate on every check |
| **Guest count** | Deduplicated non-operator face count from cross-camera embedding clustering |
| **Phenomenal context** | Progressive-fidelity rendering of temporal bands + self-band for LLM orientation |
| **Provenance expression** | PosBool(X) semiring for why-provenance — tensor (both) / plus (either) |
| **Says monad** | Principal-annotated assertion wrapping data with WHO authorized it |
| **Self-dimension** | Emergent aspect of Hapax self-knowledge, discovered through apperception cascade |
| **Stimmung** | System-wide self-state vector — 6 dimensions + stance |
| **Temporal bands** | Husserlian retention/impression/protention for LLM prompt injection |
| **Trio relay** | File-based coordination protocol for 2 Claude sessions + 1 operator |
| **Context anchoring** | Conversational continuity via turn-by-turn thread injection, as opposed to profile-gated retrieval |
| **Grounding evaluation** | Per-turn measurement of Clark grounding mechanisms: context anchor success, reference accuracy, acceptance type |
| **Trajectory score** | Within-session slope of a grounding metric — positive slope indicates grounding improving over turns |
| **Turn-pair coherence** | Conditional probability linking consecutive turns — P(accept\|high anchor at prior turn) |
| **Failure mode detector** | Boolean alarm that fires when the system exhibits profile-retrieval patterns |
| **Spoken word cutoff** | Hard limit on words sent to TTS per turn, decoupling model thinking from operator hearing |

### Terms Borrowed from Other Fields

| Term | Source | How We Use It |
|------|--------|---------------|
| **Affordance** | Gibson (ecological psychology) | Environmental features that invite specific actions |
| **Allostatic regulation** | Sterling (neuroscience) | System self-preservation through proactive resource management |
| **Carrier fact** | Martraire (living documentation) | Behavioral observation with bounded capacity and displacement |
| **Chiasm** | Merleau-Ponty (phenomenology) | The interleaving of perceiver and perceived |
| **Cognitive defusion** | ACT (psychology) | Relating to thoughts as thoughts, not as identity |
| **DLM** | Myers/Liskov (security) | Decentralized Label Model for information flow control |
| **Husserlian bands** | Husserl (phenomenology) | Retention (fading past), impression (vivid present), protention (anticipated future) |
| **Precedent** | Legal tradition | A past decision that constrains future governance decisions |
| **Semiring** | Abstract algebra | Algebraic structure with two operations (tensor/plus) satisfying distributivity |
| **Shearing layers** | Brand (architecture) | Components that change at different rates |
| **Stigmergy** | Grassé (entomology) | Indirect coordination through environment modification |
| **Stochastic resonance** | Physics | Noise injection that improves signal detection |
| **Transmuting internalization** | Kohut (self psychology) | Learning from experience without rigidifying |
| **Conversational grounding** | Clark & Brennan (1991) | Collaborative process of establishing mutual understanding |
| **SCED** | Clinical research | Single-case experimental design — repeated measures on one participant across phases |
| **ROPE** | Bayesian statistics | Region of Practical Equivalence — range of effect sizes considered practically null |
| **Bayes Factor** | Bayesian statistics | Ratio of evidence for one hypothesis over another |
| **Full-duplex** | Telecommunications / voice AI | Simultaneous listening and speaking capability |
| **ByteTrack** | Computer vision | Multi-object tracking via byte-level association |
| **MoViNet** | Google Research | Mobile Video Network — streaming action recognition model |
| **BOCPD** | Statistics | Bayesian Online Change Point Detection |

---

*End of compendium. This document will grow. Sections marked "experimental" or "planned" will be updated as the system evolves. The decision log is append-only — decisions are never edited, only superseded.*
