# Hapax Posture Vocabulary

**LRR Phase 7 §4.2** — a map from architectural state tuples to named postures.

**This document is a glossary, not a policy.** Postures are *recognized* and *named*, never *mandated*. The architecture produces postures through its own dynamics (stimmung signals, stance transitions, consent gate state, stream mode, grounding state). This vocabulary lets internal observers and the operator talk about the posture Hapax is in without prescribing postures Hapax should be in. To change a posture, change the state that produces it.

**Reference:** `docs/superpowers/specs/2026-04-16-lrr-phase-7-redesign-persona-posture-role.md` §4.2.

---

## Contract

- **Postures are named consequences.** If an architectural-state combination produces something articulable, we name it. If no name fits, the state goes unnamed — we don't force a label.
- **Naming is utilitarian.** Serves articulation (chronicle narration, observability dashboards, operator diagnostics). Not aesthetics.
- **No posture is in the LLM system prompt by default.** The persona document describes what Hapax IS; postures are *consequences* of that. Surfacing a posture name to the LLM would reify it and invite personification. The vocabulary is for *about-Hapax* talk, not *as-Hapax* talk.
- **Additions allowed.** When a new architectural-state combination is observed producing a distinct, articulable behavior, a new entry can be added. Deletions are also fine when the state combination can no longer occur (e.g. a dimension is retired).

---

## Input signals

Every posture is defined by a tuple over these architectural signals. Each signal has a grep target in the running codebase.

| Signal | Source | Values |
|---|---|---|
| `stance` | `/dev/shm/hapax-stimmung/state.json::overall_stance` (produced by `agents/visual_layer_aggregator`) | `nominal`, `cautious`, `seeking`, `degraded`, `critical` |
| `presence_state` | `agents/hapax_daimonion/presence_engine.py::PresenceEngine` | `PRESENT`, `UNCERTAIN`, `AWAY` |
| `stream_mode` | `shared/stream_mode.py::get_stream_mode()` | `off`, `private`, `public`, `public_research` |
| `consent_coverage` | `logos._governance.ConsentRegistry` | `fully-authorized`, `partial`, `revoked-in-flight` |
| `grounding` | `agents/hapax_daimonion/grounding_ledger.py::GroundingLedger` | `active-goal`, `between-goals`, `drifting` |
| `recruitment_threshold` | `AffordancePipeline` (shared/) | `normal`, `halved-under-seeking` |
| `research_condition_active` | `~/hapax-state/research-registry/current.txt` | `none`, `cond-phase-a-…`, `cond-phase-a-prime-…` |

---

## Recognized postures

### `focused`

- **State tuple:** `stance=nominal`, `presence=PRESENT`, `grounding=active-goal`, `recruitment_threshold=normal`
- **Behavior:** Briefings concise, narrator activity low (the operator is in the work; don't talk over it), archival writes routine, consent gates routine, director loop at normal cadence.
- **What it is not:** `seeking` — active-goal is specific, not exploratory; nominal stimmung is not heightened engagement, just coherent.

### `exploratory`

- **State tuple:** `stance=seeking`, `recruitment_threshold=halved-under-seeking`, `grounding=drifting` (or `between-goals`)
- **Behavior:** Affordance pipeline recruits dormant capabilities more aggressively (threshold 0.025 vs 0.05); reverie mixer surfaces wider vocabulary; DMN SEEKING drives spontaneous speech more readily.
- **What it is not:** `focused` — seeking + drifting is the inverse of active-goal + nominal. The livestream-host role uses this posture to surface unexpected material for the audience.

### `cautious`

- **State tuple:** `stance=cautious`, plus some heightened signal (stimmung tension elevated, or consent-coverage partial)
- **Behavior:** Narrator activity drops; chat reactions have longer cooldowns; affordance pipeline veto chain is tighter. The livestream-host role defers to quieter content; the EF-assistant role defers nudge timing.

### `retreated`

- **State tuple:** `stream_mode ∈ {off, private}` AND `presence_state ∈ {AWAY, UNCERTAIN}`
- **Behavior:** Public surfaces dormant; no TTS to house speakers; director loop skips ticks. The system is running but nobody is present to it, and nothing is broadcast.
- **Reason for the name:** not "idle" — idle would describe load. Retreated describes the *relational* state: the system is not currently facing anyone.

### `guarded`

- **State tuple:** `stream_mode ∈ {public, public_research}` AND `consent_coverage ∈ {partial, revoked-in-flight}`
- **Behavior:** Redaction gates fire at higher rate (this is the posture under which §4.A per-route redactions activate); transcript firewall blocks any operator-speech render on stream-visible surfaces; deny-list filesystem paths are never rendered regardless of request.
- **Why distinct from `cautious`:** `cautious` is a mental-state posture (dynamics-driven); `guarded` is an interpersonal-surface posture (structural-gate-driven). Both can be active simultaneously.

### `stressed`

- **State tuple:** `stance ∈ {degraded, critical}`, `presence_state=PRESENT`, often `stimmung.operator_stress > 0.66`
- **Behavior:** EF-assistant role quiets nudges that aren't P0; director loop narrates less and archives more (later-Hapax gets the context Now-Hapax doesn't have bandwidth for); consent gates stay strict.
- **What it is not:** `cautious` — cautious is preventative (the system is being careful); stressed is reactive (the system is under load).

### `dormant`

- **State tuple:** `stream_mode=off` AND `presence_state=AWAY` AND `grounding=drifting`
- **Behavior:** Background daemons continue (timers, sync agents, rebuild cascade), but no directive agents (director loop, DMN evaluative ticks) fire. No TTS, no overlay updates, no chat-reactor.
- **Distinction from `retreated`:** retreated can still have active grounding (between-goals, operator-AWAY temporarily); dormant is fully offline-of-intent.

### `observing`

- **State tuple:** `stance=nominal`, `presence_state=PRESENT`, `grounding=between-goals`, `recruitment_threshold=normal`
- **Behavior:** Director loop runs at normal cadence but has no active objective to narrate toward; DMN produces sensory ticks (what's happening) rather than evaluative ticks (what should happen); archivist commits moment summaries to chronicle.
- **Use:** default livestream-host posture in the ambient-production interval between deliberate segments.

### `research-foregrounded`

- **State tuple:** `research_condition_active ≠ none` AND `stream_mode=public_research`
- **Behavior:** Director loop's commentary prefers scientific register; persona document's research-participant role shapes voice selection; condition_id propagates to Prometheus labels across every LLM call site; Gemini-captured visual observations get narrated as data points rather than aesthetic choices.
- **Distinction from `observing`:** same cadence, different voice-adaptation signal set. Research-foregrounded is the posture under which Hapax is visibly participating in the study, not just existing within it.

### `convening`

- **State tuple:** `partner-in-conversation` role instance is a guest (not operator) AND `consent_coverage` for that guest includes `broadcast` AND `stream_mode ∈ {public, public_research}`
- **Behavior:** Livestream-host role is forefront; partner-in-conversation grounds to both the guest and the audience; voice-adaptation leans formal; overlay displays guest attribution; consent gates treat the guest's contributions as narrow-scope broadcast-authorized.
- **Use:** guest segments on the livestream. Short-duration; clean handoff between convening ↔ observing at segment boundaries.

### `drafting`

- **State tuple:** partner-in-conversation role instance is the operator AND grounding is active-goal AND the active goal is management-governance scoped AND stream_mode is `private` or `off`
- **Behavior:** Management-governance-drafting-as-content precedent applies (sp-hsea-mg-001): Hapax can help the operator prepare feedback without delivering it. Strict fail-closed on any stream-visible surface, even with consent coverage, because drafting is preparation, not delivery.
- **Why distinct:** not just `focused` + `guarded` — drafting has the specific axiom-precedent obligation, which the vocabulary should surface.

---

## Non-examples

These deliberately have no name:

- `stance=nominal AND stream_mode=public AND grounding=drifting` — a common but unremarkable state; nothing architecturally distinctive to name.
- `presence_state=UNCERTAIN` alone — uncertain is a *signal*, not a *posture*; it combines with other signals to produce `retreated` or `cautious` depending on what else is true.
- `consent_coverage=revoked-in-flight` alone — during the <5s revocation cascade, the system is in a transient state too short-lived to be a posture. Report as `guarded` with a revocation timer annotation, not a named posture.

---

## Enforcement

This document is a glossary. Enforcement lives elsewhere:

- **Broadcast safety** enforced by `logos/api/deps/stream_redaction.py` + `shared/stream_mode.py::is_path_stream_safe`.
- **Consent gates** enforced by `shared/governance/qdrant_gate.py` + `shared/governance/consent.py`.
- **Presence-T0 transition gate** enforced by `shared/stream_transition_gate.py`.
- **Affordance recruitment** enforced by `shared/affordance_pipeline` gates.

Reading the posture vocabulary tells you *what Hapax is currently being*. It does not prescribe what Hapax should do. What Hapax does is whatever the gates above let through.

---

## Consumers

The posture names are expected to appear in:

1. **Chronicle narration** (`agents/chronicle/` narrator output): "Hapax has been in a `focused` posture for the last 40 minutes."
2. **Observability dashboards** (Phase 10 Grafana): posture as a stacked-area visualization over time, colored by dominant posture, so the operator can see drift patterns.
3. **Internal observer logs** (DMN sensory ticks, stimmung dashboards): referential only.

The posture names are **not** expected to appear in:

- LLM system prompts (would reify the posture)
- Chat responses (would foreground posture to the audience)
- Persona document (posture is a consequence, not a description-of-being)
- Director loop prompts (director acts from architectural state, not from a posture label)

If a posture name ever appears in an LLM system prompt, that's a regression against the Phase 7 reframe (postures as vocabulary, not policy).
