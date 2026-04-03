# Total Affordance Field — Epic Design Specification

**Date:** 2026-04-03
**Status:** Implemented (all phases complete, audit passed)
**Scope:** System-wide architectural epic — three phases, all subsystems
**Depends on:** Unified Semantic Recruitment (2026-04-02), SCM Formalization, Capability Parity, Boredom/Exploration Signal
**Governance gate:** interpersonal_transparency (axiom, weight 88), corporate_boundary (axiom, weight 90), experiment freeze (Cycle 2 Phase A active)

---

## 1. Problem Statement

The system's affordance space is narrow and fragmented. Four independent AffordancePipeline instances serve four daemons, each registering its own capabilities in a shared Qdrant collection but learning independently. The DMN perceives the world through a keyhole of four sensors. Five of eight content affordances are stubs. The imagination loop cannot imagine about weather, music, goals, or the open internet because those signals never reach it. `render_impingement_text()` drops narrative from imagination impingements, making the richest signals in the system invisible to recruitment.

The operator's directive: affordances belong to the world, not to subsystems. Every cognitive faculty should draw from a shared field of everything available — local sensors, personal data, and the open internet — each expressing through its own dynamics.

## 2. Theoretical Justification

### 2.1 Gibson Affordance Theory

An affordance is a relationship between an organism and its environment (Gibson, 1979). The weather affords atmosphere. The desk affords work. Email affords social awareness. Affordances are not properties of subsystems — they are discovered by each faculty through its own perceptual dynamics. The current architecture violates this: `agents/reverie/_affordances.py` declares affordances as Reverie's possessions.

### 2.2 Stigmergic Coordination (SCM Property 1)

New affordances are new pheromone types in the shared field. The SCM coordination model requires: no direct message passing between S1 components, no centralized coordinator, no global clock. Adding affordance sources is composition by addition — each writes traces at its own cadence, each faculty reads at its own. The Qdrant `affordances` collection is explicitly the "shared pheromone field" (USR spec §3.1).

**Constraint:** Per-daemon pipeline instances must be preserved. Consolidation into a single coordinator would be an actor system (explicitly what the SCM is NOT). Learning is shared through Qdrant payload annotations (cross-daemon activation summaries), not through shared state.

### 2.3 Bachelard Material Imagination

The five materials on `ImaginationFragment` (water/fire/earth/air/void) are Bachelardian elements. Material imagination requires material. The DMN's current epistemic horizon (activity, stress, heart rate, game state) starves the imagination of the world-substance it needs to produce meaningful fragments. Expanding the sensor layer completes the Bachelardian commitment.

### 2.4 PCT Control Laws

Every new affordance source follows the established 14-component pattern: controlled variable, reference, error, hysteresis (3:5), three corrective action levels, monotonically reducing. No new coordination mechanism is introduced.

### 2.5 Observer-System Circularity (Property 6 — Caution)

Features that model or modify the operator feedback loop must wait for eigenform analysis. Passive observation affordances (weather, time, music state) have no circularity risk. Active intervention affordances (e.g., "reduce cognitive load when stress is high") are deferred until Property 6 is formalized.

## 3. Axiom Compliance

### 3.1 interpersonal_transparency (weight 88, constitutional)

Email, calendar, and social data contain information about non-operator persons. The axiom requires explicit opt-in consent contracts at the ingestion boundary for each identifiable person whose persistent state the system holds.

**Resolution:** All affordances accessing email/calendar are operator-perspective only. Gibson-verb descriptions are written from the operator's perspective ("Observe the operator's communication cadence", not "Track Alice's response patterns"). The ingestion boundary redacts person-identifying state without active contracts. Social platform data is axiomatically blocked (consent from third parties is structurally impossible at scale).

### 3.2 corporate_boundary (weight 90)

Each new external API requires an operator-approved exception record with compensating controls (API key in pass store, no PII in payloads, graceful degradation, quarterly review). `cb-degrade-001` requires silent failure with informative UI.

### 3.3 Experiment Freeze (Cycle 2 Phase A)

Phase A baseline has zero valid sessions (restarted 2026-04-02). Any change to what enters the system prompt during experiment sessions invalidates baseline. All affordance expansion work must respect the `experiment_mode` gate. Claim 6 (Bayesian Tools) must be pre-registered before tool recruitment changes go live.

**Resolution:** Phase 1 (infrastructure) and Phase 2 (world perception) do not touch `conversation_pipeline.py`. Phase 3 (expression) gates conversation-pipeline work on experiment phase completion or formal DEVIATION record.

## 4. Three-Phase Architecture

### Phase 1: Shared Pheromone Field (Infrastructure)

Fix the broken pipes. Per-daemon pipeline instances stay, but learning becomes visible across daemons via Qdrant payload. Imagination impingements carry their narrative for embedding. Stale references are corrected.

**Deliverables:**
- `render_impingement_text()` includes narrative for imagination-sourced impingements
- Cross-daemon activation summaries written to Qdrant point payloads on `save_activation_state()`
- Stimmung stance field mismatch fixed (`stance` not `overall_stance`)
- Plan defaults cache invalidated on graph rebuild
- Visual chain physarum references retargeted to actual vocabulary nodes
- `can_resolve()` bypass paths removed
- ContentScheduler folded into affordance recruitment (VLA bypass removed)
- `FRAGMENT_TO_SHADER` in `shared/expression.py` updated (remove physarum refs)

### Phase 2: World Perception (Input Expansion)

Give the DMN access to the whole world. Register all available data sources as affordances with Gibson-verb descriptions. Comply with axiom constraints.

**Deliverables:**
- DMN sensor layer expanded: weather, time/season/circadian, MIDI beat/tempo, vault goals, sprint state, profile dimensions, phone notifications, mixer spectral bands
- Affordance domain taxonomy: 9 domains, ~80 affordances with Gibson-verb descriptions
- All 22 perception backends registered as affordances
- External data feeds registered: weather (Open-Meteo), web search, image search, Wikipedia
- Exception records per external API
- Operator-perspective redaction at ingestion boundary for email/calendar
- Each new source gets a ControlSignal and 3-level degradation path
- Stimmung dimensions emit impingements on significant change (not just stance transitions)

### Phase 3: Total Expression (Output Expansion)

Every faculty expresses through every channel it can. Content stubs become real resolvers. Multi-modal expression routing works.

**Deliverables:**
- `activate_content()` implemented for all five stub affordances
- Content resolution pipeline: narrative text → Pillow render, episodic recall → Qdrant query, knowledge recall → RAG, profile recall → profile-facts, waveform viz → PipeWire energy
- `inject_url()` and `inject_search()` wired as recruited content resolvers
- ExpressionCoordinator given dispatch capability (not just logging)
- Medium-aware routing: same affordance expressed visually AND vocally
- FAST/SLOW two-tier async staging: FAST resolves within tick, SLOW queued for next tick
- Notification affordances (ntfy, phone push)
- Content slot TTL and opacity from recruitment combined score
- **Gated on experiment:** Tool recruitment changes require DEVIATION record or Phase A/B completion

## 5. Affordance Domain Taxonomy

Nine domains, operator-perspective Gibson-verb descriptions. Three-level Rosch structure: Domain (organizational) → Affordance (embedded in Qdrant) → Instance (metadata payload).

### 5.1 Environment
- `env.weather_conditions` — Sense current weather to ground atmospheric context
- `env.weather_forecast` — Anticipate coming weather to prepare for environmental shifts
- `env.time_of_day` — Orient to the current time and its rhythmic significance
- `env.season_phase` — Sense the seasonal context and its affective qualities
- `env.lunar_phase` — Observe the moon's current phase for temporal grounding
- `env.ambient_light` — Sense ambient illumination level in the workspace

### 5.2 Body
- `body.heart_rate` — Sense cardiac rhythm as a ground of physiological arousal
- `body.heart_variability` — Sense autonomic balance through heart rate variability
- `body.stress_level` — Sense accumulated physiological stress load
- `body.sleep_quality` — Recall recent sleep quality to contextualize energy
- `body.activity_state` — Sense current physical activity mode (walking, sitting, resting)
- `body.circadian_phase` — Sense alignment with the circadian cycle
- `body.skin_temperature` — Sense peripheral temperature as arousal/comfort proxy

### 5.3 Studio
- `studio.midi_beat` — Synchronize with the musical beat for rhythmic expression
- `studio.midi_tempo` — Sense the current tempo to calibrate temporal dynamics
- `studio.mixer_energy` — Sense total acoustic energy from the mixer output
- `studio.mixer_bass` — Sense low-frequency energy as weight and grounding
- `studio.mixer_mid` — Sense midrange presence as warmth and body
- `studio.mixer_high` — Sense high-frequency energy as brightness and air
- `studio.desk_activity` — Sense physical desk engagement through vibration
- `studio.desk_gesture` — Recognize specific desk gestures (typing, tapping, drumming, scratching)
- `studio.speech_emotion` — Sense the emotional quality of detected speech
- `studio.music_genre` — Sense the current genre of music production
- `studio.flow_state` — Sense the degree of creative flow engagement
- `studio.audio_events` — Sense ambient audio events (applause, laughter, music)
- `studio.contact_mic_spectral` — Sense spectral character of desk vibration

### 5.4 Space
- `space.ir_presence` — Sense whether a person occupies the room via infrared
- `space.ir_hand_zone` — Sense where hands are active in the workspace
- `space.ir_motion` — Sense movement dynamics in the room
- `space.ir_brightness` — Sense infrared illumination level (body heat proxy)
- `space.overhead_perspective` — Observe workspace layout from above (= content.overhead_perspective)
- `space.desk_perspective` — Observe the operator's immediate work surface (= content.desk_perspective)
- `space.operator_perspective` — Observe the operator directly (= content.operator_perspective)
- `space.room_occupancy` — Sense the number of persons in the room
- `space.gaze_direction` — Sense where the operator is looking
- `space.posture` — Sense the operator's physical posture
- `space.scene_objects` — Sense what objects are visible in the environment

### 5.5 Digital Life (operator-perspective only)
- `digital.active_application` — Sense which application the operator is focused on
- `digital.workspace_context` — Sense the current desktop workspace arrangement
- `digital.browsing_cadence` — Sense the operator's web browsing rhythm and intensity
- `digital.communication_cadence` — Sense the operator's email/message send-receive rhythm (redacted: no person-identifying state)
- `digital.calendar_density` — Sense how packed the operator's schedule is today
- `digital.next_meeting_proximity` — Sense time until the next scheduled commitment
- `digital.git_activity` — Sense the operator's recent coding commit patterns
- `digital.clipboard_intent` — Sense what kind of content was just copied (url/code/text)

### 5.6 Knowledge
- `knowledge.vault_search` — Search the operator's personal knowledge base for relevant notes
- `knowledge.episodic_recall` — Recall and surface past experiences similar to the current moment
- `knowledge.profile_facts` — Recall known facts about the operator's preferences and patterns
- `knowledge.document_search` — Search ingested documents and notes for relevant knowledge
- `knowledge.web_search` — Search the open web for current information (consent_required=True)
- `knowledge.wikipedia` — Look up encyclopedic knowledge on a topic (consent_required=True)
- `knowledge.image_search` — Find relevant images from the open web (consent_required=True)

### 5.7 Social (operator-perspective, axiom-constrained)
- `social.phone_notifications` — Sense incoming phone notification activity level
- `social.phone_battery` — Sense the phone's charge state
- `social.phone_media` — Sense what media is playing on the phone
- `social.sms_activity` — Sense unread message count (no person-identifying content without contract)
- `social.meeting_context` — Sense the nature of the current or next meeting (topic, not attendees, unless consent contracts exist)

### 5.8 System
- `system.health_ratio` — Sense overall infrastructure health
- `system.gpu_pressure` — Sense GPU memory utilization pressure
- `system.error_rate` — Sense the current error frequency across services
- `system.drift_signals` — Sense accumulated system drift from intended state
- `system.exploration_deficit` — Sense the system's need for novelty
- `system.stimmung_stance` — Sense the overall attunement state
- `system.cost_pressure` — Sense LLM spending rate relative to budget

### 5.9 Open World (consent_required=True, corporate_boundary exception required)
- `world.news_headlines` — Sense current news headlines for situational context
- `world.rss_feed` — Sense updates from subscribed RSS feeds
- `world.music_metadata` — Look up metadata about a track or artist
- `world.weather_elsewhere` — Sense weather in a location the operator is thinking about
- `world.stock_market` — Sense broad market conditions (not financial advice)
- `world.astronomy` — Sense current celestial events (moon phase, planet visibility)

## 6. Taxonomy Theoretical Status

The nine-domain taxonomy is a **pragmatic Roschian categorization of the operator's niche**, not a recovery of natural kinds. No established framework in phenomenology, ecological psychology, or cognitive science proposes a fixed content taxonomy of affordances — Gibson explicitly refused to do so, and the field has deliberately left this space open.

### What is naturally justified

- **The three-level Rosch structure** (domain → affordance → instance) has direct support from prototype theory (Rosch 1978). Basic-level categories maximize within-category similarity and between-category distinctiveness.
- **The concentric spatial structure** (space → env → world) maps to Schutz's phenomenological zones of reach (world within reach → restorable reach → attainable reach).
- **The body domain** maps to Damasio's interoception and Merleau-Ponty's lived body (Leib).
- **The social domain** maps to Neisser's interpersonal self (1988) and Gibson's "affordances of other persons."
- **The knowledge domain** maps to Neisser's extended self.
- **Competitive recruitment across domains** mirrors Cisek's affordance competition hypothesis (2007) and Baars' Global Workspace Theory.
- **Stimmung as orthogonal modulator** (not a domain) is phenomenologically correct per Heidegger — Befindlichkeit discloses the world as a whole; it determines which affordances solicit and which recede.

### What is pragmatically imposed but defensible

- **The studio domain** is niche-specific (hip hop production environment). Gibson would call it a "niche" — the affordance landscape of this organism in this environment.
- **The digital domain** extends affordance theory into virtual technology (grounded in Norman's perceived affordances).
- **The system domain** is metacognitive self-monitoring — no phenomenological analog, but necessary for an artificial cognitive system.
- **The nine-domain count** reflects engineering convenience, not cognitive architecture.

### Known theoretical gaps

- **Temporal experience** (Husserl's retention/protention, van Manen's lived time) — distributed across env.time_of_day and body.circadian_phase rather than a dedicated domain; this may be phenomenologically sounder than reifying time as a domain.
- **Affective/emotional** (Heidegger's Befindlichkeit) — operator's felt emotion absent except as inferred from body signals; Stimmung covers system-level affect.
- **Motor/action** (Gibson's core definition) — the taxonomy is perception-weighted; tools handle action through Layer 2 (tool affordances) but the domain structure doesn't reflect it.
- **Proprioception** (Merleau-Ponty) — sensor hardware limitation, not architectural gap.

### Openness guarantee

The taxonomy does not need to be closed. Domains are **prototypical centers of a radial category system** (Lakoff 1987), not exhaustive containers. The `world.*` domain plus `capability_discovery` meta-affordance provide the explicit mechanism for the taxonomy to grow. The competitive recruitment mechanism (cosine similarity across the full embedding space) is domain-agnostic — it does not respect domain boundaries during selection, only during dispatch.

The honest framing: **domains organize registration and dispatch; the embedding space organizes recruitment.** These serve different purposes. The domains are a pragmatic partition for human legibility and handler routing. The embedding space is inherently open-ended.

## 7. Implementation Phasing and Experiment Gate

| Phase | Touches conversation_pipeline.py? | Experiment conflict? | Gate |
|---|---|---|---|
| 1: Shared Pheromone Field | No | No | None — proceed |
| 2: World Perception | No (DMN sensor layer only) | No | None — proceed |
| 3: Total Expression | Yes (tool recruitment, content routing) | Yes (Claim 6) | DEVIATION record or Phase A/B complete |

Phases 1 and 2 can proceed in parallel with the active experiment. Phase 3 is gated.

## 7. Success Criteria

1. Grafana "Technique Confidence (Live)" shows >15 distinct affordances recruited per hour (currently ~5)
2. DMN imagination fragments reference weather, time, music, goals — not just activity/stress
3. `render_impingement_text()` for imagination impingements produces semantically meaningful text (cosine similarity to capability descriptions >0.3)
4. Cross-daemon Thompson sampling visible in Qdrant payload annotations
5. All five content stub affordances produce visible output on the Reverie surface
6. No T0 axiom violations (automated scan)
7. No experiment contamination (Phase A sessions unaffected)

## 9. Implementation Status (2026-04-03)

All three phases implemented. Code review audit passed with 4 critical bugs found and fixed.

**PRs:** #571, #573, #574, #576, #577, #579, #580, #581

**Key files created:**
- `shared/affordance_registry.py` — 87 affordances, 9 domains
- `agents/reverie/_content_resolvers.py` — 5 content resolution handlers
- `agents/notification_capability.py` — salience→priority notification wrapper
- `agents/hapax_daimonion/proofs/research/protocols/deviations/DEVIATION-040-total-affordance-field.md`

**Key files modified:**
- `shared/impingement.py` — narrative in render_impingement_text
- `shared/affordance_pipeline.py` — activation_summary + medium in Qdrant payload
- `shared/expression.py` — FRAGMENT_TO_SHADER retargeted
- `agents/visual_chain.py` — physarum → vocabulary nodes
- `agents/imagination.py` — expanded assemble_context (weather, time, music, goals, fortress)
- `agents/dmn/sensor.py` — sensor promotion in read_all()
- `agents/reverie/_affordances.py` — imports from shared registry
- `agents/reverie/_content_capabilities.py` — activate_content dispatch + CAMERA_MAP
- `agents/reverie/mixer.py` — knowledge.* and space.* dispatch
- `agents/hapax_daimonion/init_pipeline.py` — indexes ALL_AFFORDANCES
- `agents/hapax_daimonion/run_loops_aux.py` — world routing + notification + ExpressionCoordinator dispatch
- `agents/hapax_daimonion/_perception_state_writer.py` — 5 new fields + PII curtailment
- `agents/hapax_daimonion/discovery_affordance.py` — search() implemented
- `agents/stimmung_sync.py` — dimension-level impingement emission
- `agents/visual_layer_aggregator/aggregator.py` — scheduler_enabled flag
- `axioms/enforcement-exceptions.yaml` — Open-Meteo + DuckDuckGo exceptions

**Feature flag:** `~/.cache/hapax/world-routing-enabled` (touch to enable, rm to disable)

**Remaining architectural items (deferred by design):**
- `can_resolve()` deprecation — documented as intentional secondary gates
- ContentScheduler folding — flag added, full folding requires VLA architectural work
- Claim 6 pre-registration — architectural snapshot documented, formal pre-reg after Claim 1 cycle
