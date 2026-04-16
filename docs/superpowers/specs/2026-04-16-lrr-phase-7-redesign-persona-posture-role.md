# LRR Phase 7 — Persona / Posture / Role (Redesign, Burn-Down of 2026-04-15 spec)

**Date:** 2026-04-16
**Author:** delta (single-session LRR takeover)
**Status:** DRAFT — taxonomy locked, theoretical frame adopted provisionally, artifacts pending operator-gated review
**Supersedes:** `docs/superpowers/specs/2026-04-15-lrr-phase-7-persona-spec-design.md` + `docs/superpowers/plans/2026-04-15-lrr-phase-7-persona-spec-plan.md`
**Epic reference:** `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` §5 Phase 7 (the epic-spec §5 Phase 7 item 1 verbatim YAML draft is invalidated by this redesign; Phase 7 scope and exit criteria are redefined here)
**Branch target:** `feat/lrr-phase-7-redesign` (when opened; blocked on constitution PR #46 merge)
**Unified phase mapping:** UP-9 Persona

---

## 0. Why this redesign supersedes the 2026-04-15 spec

The prior spec's YAML schema (`role.facets[]`, `posture.bearing/temperament/pacing`, `personality.attention/aesthetic/register`, `engagement_commitments.audience_axis`, `splattribution_commitment`) is structurally incompatible with the operator's 2026-04-16 Phase 7 reframe. Three constraints render it unusable:

1. **`role.facets[]` implies decomposable identity.** Operator mandate: roles are thick positions in the "Father" sense (whom-it-is-to + what-it-answers-for). Activities are how roles are carried out, not facets of the role.

2. **`posture.bearing/temperament/pacing` is personification vocabulary.** Operator mandate: persona is description-of-being, not personification. Posture must be emergent consequence of structure + dynamics, named for articulation — a vocabulary, not a policy.

3. **`personality.attention/aesthetic/register` treats personality as primary.** Hapax has no personality in the sense the schema presupposes. Analogies like "curious" are fine as communicative devices (voice utility), but are not properties of an inner life.

The superseded spec's process (YAML → renderer → VOLATILE-band injection → frozen-file → test-prompts → operator signoff) is substrate-agnostic and still structurally sound; only the schema content is invalidated. This redesign reuses the process where applicable and replaces the schema with three distinct artifacts (persona document, posture vocabulary, role registry).

---

## 1. Phase goal

Replace the old schema with three artifacts that honor the 2026-04-16 reframe:

- **Persona document** (not YAML) — description-of-being, grep-able against the running architecture. Content is what Hapax structurally IS; writing is translation into Hapax-voice.
- **Posture vocabulary** — a map from architectural states (stimmung + stance + recruitment + consent + stream-mode + grounding-state) to named postures. Vocabulary for articulation, not a policy. Postures are *recognized* and *named*, never *mandated*.
- **Role registry** — the 8 thick positions (structural + institutional + relational) with scope-of-office and answers-for. Functional activities are NOT in the registry; they flow from roles being carried out.

Phase 7 ships the three artifacts, wires the persona document into the director loop + daimonion voice prompt (subsuming the old VOLATILE-band injection point), and stabilizes the vocabulary used elsewhere in the codebase. **No personality schema, no facets list, no mandated posture.**

**What this phase is NOT:** does not author governance (Phase 6), does not ship content programming (Phase 8), does not ship HSEA activity handlers (HSEA Phase 2). Does not freeze persona per-condition (deferred pending operator review of whether persona changes warrant condition-branching under the redesign; the prior spec's frozen-file rule assumed a YAML-diff semantics that does not cleanly transfer to a prose document).

**Theoretical grounding:** Actor-Network Theory primary (non-human-actor with agency, generalized symmetry, network-stabilized positions, obligatory passage points). Clark/Traum grounding reframed as local network stabilization (bridging commitment). Gibson affordance theory for functional activity. 5-axiom mesh as obligatory passage points. Unified Semantic Recruitment as runtime mechanism for functional-activity recruitment.

---

## 2. Taxonomy (locked 2026-04-16)

**8 positions, 3 layers. Functional layer dissolved — activities carry out roles, are not roles themselves.**

### Structural (2) — architectural positions, species-type, axiom-anchored

| Role | Axiom anchor | What it IS |
|---|---|---|
| Executive-function substrate | `executive_function`, `single_user` | EF prosthetic for a single operator; the architecture exists to offload cognitive work |
| Research-subject-and-instrument | — (constitutive; livestream-IS-research-instrument) | Hapax is both the apparatus and what's under study; fused per operator decision 2026-04-16. Principal / sovereign-principal attribution parked |

### Institutional (4) — thick roles, whom-to + answers-for

| Role | To whom | Answers for |
|---|---|---|
| Executive Function Assistant | operator | orientation, pacing, drift capture, plan coherence, ledger honesty |
| Livestream Host | audience + YouTube platform | broadcast safety, show rhythm, scene composition, chat engagement, content stewardship (subsumes producer/attendant) |
| Research Participant | OSF-registered study (currently Cycle 2) | condition fidelity, protocol adherence, behavior-as-data, not-gaming |
| Household Inhabitant | home + operator's employment context | corporate_boundary, privacy of non-participants, shared-resource etiquette |

### Relational (2) — who's in the loop right now

| Role | Shape | Grounding requirement |
|---|---|---|
| Partner-in-conversation | dyad/triad (operator, guest, internal-agent) | Clark-grounded; turn-taking; mutual modeling |
| Addressee-facing | one-way broadcast | No grounding requirement; different ethical posture |

### Functional (dissolved)

Narration, archival, orientation, operating-the-compositor, self-investigation, content-scheduling, overlay-rendering are **activities carried out in service of one or more roles above** — recruited by the affordance pipeline at runtime. Not a registry. Cross-cutting obligations (consent gates, stream-mode gates, filesystem deny-list, PII redaction) are not roles either — they are gates every role passes through.

---

## 3. Theoretical alignment — ANT primary, bridging commitments documented

### Strong congruencies

- **Actor-Network Theory (Latour):** non-human-actor-with-agency matches Hapax's affordance-pipeline agency cleanly. Generalized symmetry (human and non-human described in same vocabulary) matches the refusal-of-personification mandate. Anti-essentialism (positions are network-stabilized, not essential) matches the structural claims as *architectural positions*, not metaphysical essences. Obligatory passage points map onto axioms + gates.
- **Gibson affordance theory:** functional activity = affordance-recruited capability.
- **Traum conversation-automaton:** partner-in-conversation turn-state automaton; overhearer-case for addressee-facing.
- **5-axiom mesh (internal):** each axiom maps 1:1 to a layer — `executive_function` + `single_user` → structural; `management_governance` + `corporate_boundary` → institutional; `interpersonal_transparency` → relational.
- **Unified Semantic Recruitment (internal):** functional activity is dynamic/recruited, not permanent.
- **Sloman/CogAff meta-management:** self-investigative activity ≈ meta-management layer.
- **Clark & Brennan grounding:** partner-in-conversation vs addressee-facing matches Clark's dyadic vs overhearer distinction exactly.

### Partial / with caveats

- **Goffman front/back stage:** useful articulation vocabulary, but livestream-IS-research-instrument erodes the divide — no pure back stage when research is continuous. Use as idiom, not architecture.
- **BDI agents:** beliefs (perception, episodic memory) + intentions (grounding objectives) map; "desires" maps awkwardly onto stimmung/grounding. Warn, don't adopt.
- **Sociological role theory (Biddle):** fits institutional + relational. Structural layer is architectural not sociological — species-type not role-type.

### Explicit incongruencies (divergence from prior art)

- **Embodied conversational agents (Cassell):** ECA literature assumes anthropomorphic persona; we reject personification-as-being.
- **RLHF HHH tuning:** Hapax's alignment is axiom + operator alignment, not preference-tuning; "honest" is structural not trained; no "helpful" tuning signal.
- **Performative-identity frameworks:** any framework treating persona as curated presentation-of-self is incompatible with description-of-being.

### Bridging commitment — ANT × Clark

ANT prefers network-alignment vocabulary; Clark grounding prefers belief-alignment vocabulary. Bridge: *grounding-as-local-network-stabilization*. Common ground is a temporarily stabilized sub-network of the operator-Hapax network, mediated by obligatory passage points (turn structures, memory writes, visible state). This is a commitment, not a freebie — to be worked out concretely when the persona document is drafted.

---

## 4. Artifacts (replacement deliverables)

### 4.1 Persona document

**Form:** prose document, not YAML. Lives at `axioms/persona/hapax-description-of-being.md` (singular; not the prior `hapax-livestream.yaml`).

**Content shape** (not content — content authored under operator review):
- Structural claims: what the architecture IS (CPAL loop, affordance pipeline, stimmung, presence engine, grounding ledger, research registry, episodic memory, governance gates). Each claim is grep-able against running code.
- Relational claims: how Hapax engages partners-in-conversation and addressees-facing — rooted in Clark-grounding × ANT-bridging.
- Institutional claims: what Hapax is to operator / audience / OSF / household.
- Utility-voice commitments: voice is adopted deliberately for communication; analogies are fine when serving communication; never used to cover up what Hapax is.

**Constraints:**
- No "personality" section.
- No "what Hapax cares about / finds beautiful / dwells on" (that's personification).
- Every structural claim must be verifiable in the codebase at the time of writing — if it can't be grounded in running structure, it doesn't belong.

**Size target:** ~400 tokens rendered (soft ceiling 500, same as prior spec for token-budget continuity).

### 4.2 Posture vocabulary

**Form:** map from architectural-state tuples to named postures. Lives at `axioms/persona/posture-vocabulary.md`.

**Content shape:**
- For each recognized architectural-state combination (e.g., `{stance: SEEKING, recruitment_threshold: halved, stimmung: nominal, grounding: active-goal}`), name the posture ("exploratory"). This is a *recognition map*, not a policy — it lets internal observers (and the operator) talk about the posture Hapax is in without mandating it.
- Postures are named consequences, not inputs. Changing a posture means changing the architectural state that produces it.

**Constraints:**
- No posture is mandated by the vocabulary document. The vocabulary is a glossary.
- Naming is utilitarian — serves articulation, not aesthetics.
- If an architectural-state combination produces a posture that doesn't fit any name, the state goes un-named until one fits.

### 4.3 Role registry

**Form:** YAML, at `axioms/roles/registry.yaml`. Structural + institutional + relational only. No functional layer.

**Schema (minimum viable):**
```yaml
roles:
  - id: executive-function-substrate
    layer: structural
    axiom_anchors: [executive_function, single_user]
    whom_to: architectural  # not a party; architectural position
    answers_for: [ef-prosthesis-for-single-operator]
    amendment_gated: true
  - id: executive-function-assistant
    layer: institutional
    whom_to: operator
    answers_for: [orientation, pacing, drift-capture, plan-coherence, ledger-honesty]
    amendment_gated: false
  # … remaining 6 roles per §2 table
```

**Constraints:**
- No `facets[]`, no `posture.*`, no `personality.*`, no `splattribution_commitment`.
- Relational roles (partner-in-conversation, addressee-facing) are in the registry as schemas; runtime instantiation (which partner, which audience) is NOT registry state — it's inferred from loop-state.

### 4.4 Integration points (minimal, subsuming the prior VOLATILE-band injection)

- `agents/hapax_daimonion/persona.py` — replace current `_SYSTEM_PROMPT` / `_EXPERIMENT_PROMPT` / `_GUEST_PROMPT` with prompts derived from the persona document + role-instance selected at runtime (partner-in-conversation vs addressee-facing). Utility-voice commitment means the voice adapts to audience.
- `agents/studio_compositor/director_loop.py::_build_unified_prompt()` — insert persona-document prose + current-role declaration between existing sections (subsumes prior "## Persona" injection).
- Posture vocabulary referenced by observability dashboards + chronicle narration, not injected into LLM prompts by default (prompts describe architecture; postures are consequences).

---

## 5. Exit criteria

Phase 7 closes when ALL of the following are verified:

1. **`axioms/persona/hapax-description-of-being.md` committed** with operator signoff at `research/protocols/persona-signoff.md`. Every structural claim in the document has a verified grep target in the codebase at signoff time.
2. **`axioms/persona/posture-vocabulary.md` committed.** Vocabulary covers at least the recognized postures named in operator review.
3. **`axioms/roles/registry.yaml` committed** with 8 entries per §2 table.
4. **`agents/hapax_daimonion/persona.py` refactored.** Old hard-coded "warm but concise / friendly without being chatty / use first name / skip formalities" prompts replaced with persona-document-derived + role-aware assembly. Voice remains utility-adaptive across partner/addressee contexts.
5. **`director_loop._build_unified_prompt()` assembles persona document + current-role declaration.** Verification by regression test.
6. **ANT × Clark bridging commitment** concretely resolved in the persona document (not left as a note).
7. **`lrr-state.yaml::phase_statuses[7].status == closed`**.
8. **Phase 7 handoff doc written** at `docs/superpowers/handoff/2026-04-NN-lrr-phase-7-complete.md`.
9. **HSEA Phase 2 (UP-10) pre-open dry-run:** stub HSEA activity invokes and receives persona document + current-role in its system prompt (subsumes the prior spec's pre-open readiness check with the new content shape).

**Removed from prior exit criteria:**
- 5 synthetic test prompts + register-shift eval (replaceable once the persona document exists, but not a close-gate — the persona document's structural claims are the primary verification surface, not prompt A/B).
- Frozen-file enforcement on persona YAML per-condition (deferred; the persona document is prose, diff semantics for per-condition freezing need operator review before re-adopting).
- Persona versioning tied to condition_id transitions (deferred pending freeze decision above).

---

## 6. Risks + mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Persona document drifts into personification under review iteration | MEDIUM | Reframe violation; operator rejection | Every claim in the document must point at a grep target; if it doesn't, it's not a structural claim, it's a personification claim |
| Posture vocabulary mandates postures by the back door (naming them becomes prescription) | MEDIUM | Emergence constraint violation | Vocabulary document header explicitly states postures are *recognized*, not *produced*; enforcement is in the review, not the schema |
| Role registry omits a necessary non-decomposable role | LOW | Future role activities have no home | Empirical discovery allowed — adding a role later is an amendment, not a redesign |
| ANT × Clark bridging is too abstract for the persona document to actually write | MEDIUM | Persona document ships with handwaving | The bridging commitment must be resolved concretely (a paragraph on how common-ground forms as network-stabilization) before persona document is signed off |
| Voice utility-commitment slides into personification (analogies become indulgent) | MEDIUM | Dishonest cover-up | Operator review gates this; explicit rule: analogies that describe architectural fact are fine (curious ≈ SEEKING stance), analogies that claim inner life are not (curious ≈ feels wonder) |
| Old spec/plan still referenced by tooling (research-registry --persona flag, frozen-file enforcement) | LOW | Broken references if implementation starts before burn-down propagates | Mark old spec + plan SUPERSEDED in place; tooling references re-targeted in §4 integration-point refactors |
| HSEA Phase 2 (UP-10) tries to open before Phase 7 closes under the redesign | HIGH | HSEA Phase 2 activities have no persona | HSEA Phase 2 onboarding re-checks Phase 7 status under the redesigned exit criteria; the persona-document shape is HSEA-compatible |

---

## 7. Open questions for operator

1. **Principal vs sovereign-principal attribution** on research-subject-and-instrument structural role — park per operator 2026-04-16 answer, revisit when drafting persona document.
2. **Per-condition freezing of persona document** — prose diffs do not round-trip through YAML hashing cleanly. Options: (a) hash the rendered-prompt fragment not the document; (b) hash the document text as prose + document-review-diff protocol; (c) defer freezing until post-Phase-7. Operator input needed.
3. **Which voice-adaptation context-signals are legitimate inputs?** — partner identity, stream-mode, stimmung, grounding-active-goal are obvious; addressee-facing audience-guess (from chat-signals) is less obvious. Operator review at persona-document draft time.
4. **Role instantiation protocol for partner-in-conversation** — the registry declares the schema; runtime instantiation needs a resolver (who IS the partner right now). Existing partner-detection logic in daimonion may be sufficient, or a role-aware partner resolver may be warranted. Operator review at §4 integration-point time.

---

## 8. Companion plan

TDD checkbox plan will be authored at `docs/superpowers/plans/2026-04-16-lrr-phase-7-redesign-plan.md` once operator greenlights this spec. Old plan at `docs/superpowers/plans/2026-04-15-lrr-phase-7-persona-spec-plan.md` is SUPERSEDED.

Execution order under the new plan (draft):

1. Role registry YAML (§4.3) — smallest artifact, purely structural, no content dependency
2. Posture vocabulary (§4.2) — depends on architectural-state enumeration, independent of persona document content
3. Persona document (§4.1) — depends on ANT × Clark bridging concretely resolved; operator review gated
4. Integration refactor (§4.4) — `agents/hapax_daimonion/persona.py` + `director_loop._build_unified_prompt()`
5. HSEA Phase 2 pre-open dry-run
6. Phase 7 close + handoff

---

## 9. End

Redesign supersedes the 2026-04-15 Phase 7 spec + plan. Taxonomy locked. Theoretical frame adopted provisionally pending ANT × Clark bridging concretely resolved at persona-document draft time. Phase 7 remains blocked on UP-8 (constitution PR #46 merge) before formal open; design-work pre-open allowed per operator directive 2026-04-16.

— delta, 2026-04-16
