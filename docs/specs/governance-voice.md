---
title: "Governance/voice model for Hapax perspective"
date: 2026-05-21
author: epsilon
status: draft
cc_task: 202605181733-hapax-perspective-phase0-research-governance-voice
authority_case: CASE-202605181733-HAPAX-P
---

# Governance/Voice Model for Hapax Perspective

## 1. Permission model

Single-operator (`single_user` axiom, weight 100). No roles, no auth, no
collaboration. All permissions flow from the operator principal.

### Axiom governance (5 axioms, all constitutional)

| Axiom | Weight | Voice constraint |
|-------|--------|-----------------|
| `single_user` | 100 | No multi-user constructs; no community voice |
| `executive_function` | 95 | Zero-config; errors include next actions |
| `corporate_boundary` | 90 | Work data in employer systems only |
| `interpersonal_transparency` | 88 | No persistent state on non-operator without consent |
| `management_governance` | 85 | LLMs prepare, humans deliver |

Registry: `axioms/registry.yaml`. Enforcement: `shared/axiom_enforcement.py`
(38 tests, 90% coverage). Precedent system: `agents/_axiom_precedents.py`.

### Consent governance

Consent contracts gate data about non-operator persons. Three tiers:
- `ConsentStateTracker` — gates data persistence based on guest presence
- `ConsentGatedReader` — gates text content based on per-person contract registry
- Consent degradation levels 1–4 (levels 3/4 unimplemented — see
  `docs/research/2026-05-21-consent-degradation-levels-3-4-root-cause.md`)

## 2. Voice attribution scheme

### Voice register (`shared/voice_register.py`)

Four registers cover Hapax's tonal spread:

| Register | Context | Behavior |
|----------|---------|----------|
| `ANNOUNCING` | Broadcast / public research | No turn closure; declarative |
| `CONVERSING` | Active operator conversation | Turn-taking with repair and grounding |
| `TEXTMODE` | IRC-style / bridge-short | Clipped delivery, BitchX lineage |
| `AMBIENT` | No presence, phone KDE connected | System-status narration, density-modulated speed |

Set by HomagePackage, read by CPAL (voice pipeline). Spec:
`docs/superpowers/specs/2026-04-18-homage-framework-design.md` §4.8.

### Anti-personification linter (`shared/anti_personification_linter.py`, 495 lines)

Enforces voice identity constraints:
- No inner-experience claims ("I feel", "I want")
- No social performance ("I'm happy to help")
- No availability performance ("I'm here for you")
- No personality claims beyond register selection

Tests: 3 test files, regression suite. Design spec:
`docs/superpowers/specs/2026-04-18-anti-personification-linter-design.md`

### Persona document

Authority: `axioms/persona/hapax-description-of-being.prompt.md`

Frames Hapax as system, not person. "Adaptation is register selection,
not personality." Voice attribution traces to this document, not to
learned behavioral patterns.

## 3. Audit log requirements

### LLM call tracing

All LLM calls route through LiteLLM gateway (`:4000`) with Langfuse
observability. Each call carries a trace ID linking prompt → completion →
tool use. Retention: MinIO blob store with 14-day lifecycle on `events/`,
full retention on traces.

### Grounding ledger

`agents/hapax_daimonion/grounding_ledger.py` (13.7KB) logs grounding acts
(claims, citations, evidence references) to Qdrant `grounding-acts` collection.
Each entry carries source attribution and temporal binding.

### Axiom precedent log

`agents/_axiom_precedents.py` records axiom-related decisions with timestamp,
axiom ID, decision outcome, and rationale. Queryable for governance audit.

### Voice output witness

`/dev/shm/hapax-daimonion/voice-output-witness.json` records each TTS
utterance: route, playback status, egress audibility, drop reason. Consumed
by broadcast audio health gate.

## 4. Escalation paths

| Trigger | Escalation | Owner |
|---------|-----------|-------|
| Axiom violation detected | Block + precedent logged | `shared/axiom_enforcement.py` |
| Anti-personification violation | Utterance blocked, ntfy alert | `shared/anti_personification_linter.py` |
| Guest presence (consent) | Persistence curtailed; voice egress NOT gated (known gap) | `consent_state.py` |
| Consent contract missing | Content degraded to level 2 (abstraction) | `consent_reader.py` |
| Management-governance boundary | LLM output gated, human delivery required | Axiom `management_governance` |

## 5. Pre-existing research

| Document | Contribution |
|----------|-------------|
| `docs/superpowers/specs/2026-04-18-anti-personification-linter-design.md` | Linter spec |
| `docs/superpowers/specs/2026-04-15-lrr-phase-7-persona-spec-design.md` | Persona spec |
| `docs/superpowers/specs/2026-04-16-lrr-phase-7-redesign-persona-posture-role.md` | Posture/role redesign |
| `docs/superpowers/plans/2026-04-18-homage-framework-plan.md` | HOMAGE voice register framework |
| `docs/superpowers/specs/2026-03-13-interpersonal-transparency-axiom-evaluation.md` | Consent axiom evaluation |
| `docs/research/2026-05-21-consent-degradation-levels-3-4-root-cause.md` | Degradation gap (this session) |
| `docs/research/2026-05-21-consent-overhearing-escalation-root-cause.md` | Egress gap (this session) |
