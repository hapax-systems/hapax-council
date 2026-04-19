# Role Derivation Methodology

**Task:** CVS #156
**Date:** 2026-04-18
**Status:** research artifact
**Relates to:** LRR Phase 7 redesign (`docs/superpowers/specs/2026-04-16-lrr-phase-7-redesign-persona-posture-role.md`), #155 anti-personification linter (`docs/superpowers/specs/2026-04-18-anti-personification-linter-design.md`), persona docs (`axioms/persona/hapax-description-of-being.md`, `axioms/persona/posture-vocabulary.md`), role registry (`axioms/roles/registry.yaml`).
**Companion artifact:** `docs/research/role-derivation-template.md` — reproducible fillable template.

This document formalizes the derivation method for the Hapax role taxonomy (Phase 7 locked, eight positions). It is written to be reusable: the general-case method in §2 is system-agnostic; the Hapax-specific application in §3 is one worked example. §4 extracts the reusable template; §5 locates the method in the existing governance surface; §6 addresses extension without refactor.

---

## 1. Problem statement

Role taxonomies authored top-down fragment, drift, and accumulate contradictions. Three failure modes recur in practice.

**Fragmentation.** When new behaviors appear, a new role is coined to hold them. Over time, roles proliferate without shared derivation, producing overlapping coverage (two roles answer for the same function), orphaned coverage (no role answers for a function the system performs), and category confusion (a behavior is filed as a role when it is an activity, a posture, or a capability).

**Drift.** Roles authored by analogy to human job titles ("assistant", "host", "helper") accrue connotations from their source concepts. Over successive edits, the taxonomy slides toward personification: role descriptions begin asserting inner states, stable dispositions, or relational attitudes that the underlying architecture does not produce.

**Contradiction.** Top-down role sets tend to encode their author's implicit ontology. When multiple authors amend the taxonomy across time, their ontological commitments collide. Without a derivation method, the only resolution procedure is negotiation, which produces arbitrary compromises rather than architectural truth.

A derivation method anchored in research methodology prevents all three failures. The method described below treats role taxonomy as an output of ANT-style actor-network analysis of a specific research question. Roles become *thick positions* an actant occupies relative to the research, rather than free-standing identity claims. Personification has no purchase, because positions are relational and answerable to specific networks, not intrinsic.

The method is additive, not evaluative. It does not rank roles or select a "correct" taxonomy. It produces a derivable taxonomy for a given research question — reproducible by any analyst starting from the same question and actant list.

---

## 2. General-case method

### Step 1 — Identify the research question

The method is keyed to a *research question*: a stable statement of what is being studied. The research question must name a phenomenon under study and the relevant scale (a single operator? a population? a duration?). It must be narrow enough to delimit which actants matter, and broad enough to survive the taxonomy process without immediate refinement.

Validation checks for Step 1:

- The research question is a declarative sentence, not a title.
- The question admits empirical study (something can be measured, observed, or recorded that bears on it).
- The question is not trivially decomposable into disjoint sub-questions (if it is, each sub-question needs its own derivation).
- The question does not presuppose a role taxonomy (it does not already name roles — e.g., "how does a *host* engage *viewers*" presupposes; "how does a broadcast surface modulate audience engagement" does not).

If the research question fails Step 1, the derivation exits with "research question under-specified" and no taxonomy is produced.

### Step 2 — Identify the actants (ANT enumeration)

Following Actor-Network Theory (Latour, Callon, Law), an *actant* is any entity that acts on or is acted upon by the research question. Actants are not restricted to humans. Hardware, software components, institutions, documents, protocols, spaces, and non-human living beings can all be actants. The test for an entity's actant status is: does removing it change the dynamics the research question studies? If yes, it is an actant.

The enumeration is as complete as practical. Missing actants produce missing positions; surplus actants produce positions that fail the Step 5 validation and collapse.

Validation checks for Step 2:

- Every named actant can be pointed at (for technical systems, can be grep-ed; for institutions, has documentation; for physical entities, is locatable).
- The list is heterogeneous (ANT rejects human-exceptionalism; if the list contains only humans, the enumeration is incomplete for any non-trivial socio-technical system).
- Candidate actants that are *activities* (e.g., "broadcasting") rather than *entities* are reclassified: broadcasting is a function an actant (host, platform) performs, not an actant itself.

### Step 3 — Identify the positions

For each actant-of-interest (typically the one the taxonomy is being authored *for* — in Hapax's case, Hapax itself), enumerate the *thick positions* it can occupy relative to the research question. A position is *thick* when it has the form:

> In relation to [other actant or network], this actant *answers-for* [enumerable commitments] and is accountable at [specific cadence].

Thin position candidates — "helpful", "curious", "available" — are rejected at this step. They name attitudes or dispositions rather than relational accountability structures.

For each candidate position, collect:

- **whom-to:** which actant or network does the position face?
- **answers-for:** enumerated commitments the position carries in that network.
- **amendment-gating:** whether the position is species-type (amendment-gated at the axiom layer) or not (editable via registry diff + review).

The table of positions is the first pass at a taxonomy. It is typically too large; Step 5 trims it.

### Step 4 — Distinguish persona / posture / role

Three categories are easily confused and must be separated before the taxonomy stabilizes.

**Persona (description-of-being).** The durable account of what the actant *is* at the substrate level. Species-type claims, architectural invariants, axiom anchors. Persona is not a position; it is the ontological ground on which positions rest. Persona amendments require amendment-gated review. Example (Hapax): "single-operator executive-function substrate that continuously perceives, evaluates, recruits, and remembers." This is not a role — it is what is true of Hapax across all roles.

**Posture (vocabulary).** Named consequences of architectural state, per-context. Postures are *recognized and named* for observability, not *mandated* for behavior. They are emergent, not prescriptive. Example (Hapax): `focused`, `exploratory`, `cautious`, `retreated`, `guarded` — each a tuple over stance, presence, stream-mode, consent-coverage, grounding, recruitment-threshold. Postures are vocabulary for *about-actant* talk; they are not positions the actant occupies.

**Role (thick position).** Research-relative, enumerable, with whom-to and answers-for. Roles are the output of Step 3. They sit between persona (too ontological) and posture (too situational).

The Phase 7 redesign collapsed what had been a three-layer taxonomy (structural / institutional / functional / relational) to three layers (structural / institutional / relational) by dissolving the functional layer: functions are activities carried out *within* roles, not roles themselves. This matters for the general method: "narrator", "archivist", "operator-of-compositor" are activities, not roles. A role holds them; they do not hold themselves.

Validation checks for Step 4:

- Every item in the candidate table falls into exactly one of persona / posture / role.
- Items that describe inner states or dispositions are reclassified as posture (if tied to architectural state) or rejected (if they assert inner life the architecture does not produce).
- Items that describe activities are rejected as role candidates; they are demoted to *activities a role carries out*.

### Step 5 — Validation (collapse test)

For each surviving role, test:

> If this role were removed from the taxonomy, would the research question still be fully characterized with respect to the actant?

If the answer is yes (the research question is still fully addressed without this role), the role collapses into an adjacent role. If the answer is no (the research question loses a dimension without this role), the role stays.

The collapse test is the primary mechanism against over-production. It tends to reveal two patterns:

1. **Activities masquerading as roles.** "Compositor-operator" collapses into "livestream-host" because the research question on broadcast modulation is fully characterized by the host position; the compositor-operating is an activity that role carries out.
2. **Postures masquerading as roles.** "Helper" collapses because the research question is addressed by "executive-function-assistant" (a thick position with whom-to=operator, answers-for=orientation/pacing/drift-capture/etc.); helpfulness is a posture consequence, not a position.

A role that survives the collapse test has a unique contribution to the research question's characterization. The set of surviving roles is the final taxonomy.

Validation checks for Step 5:

- Each surviving role has non-empty `whom_to` and `answers_for`.
- No two surviving roles share the same `whom_to` + `answers_for` pair (if they do, one collapses into the other).
- The `is_not` field is populated for every non-structural role: it enumerates the common patterns the role explicitly rejects, preventing drift toward personification under subsequent edits.
- Removing any role from the final set breaks some specific aspect of the research question's characterization. If removal breaks nothing, that role should have collapsed.

---

## 3. Hapax-specific application

### 3.1 Research question

> How does a cognition substrate modulate a single operator's executive function and livestream output, under continuous self-study as the research instrument?

Expansion notes:

- "Cognition substrate" names Hapax: the perception / evaluation / recruitment / memory stack, not any single agent.
- "Single operator" is axiom-anchored (`single_user`). The question cannot be generalized to multiple operators without breaking the axiom; if the question ever generalizes, the taxonomy must be re-derived.
- "Executive function" and "livestream output" are the dual surfaces on which modulation is visible. Either can be studied in isolation, but Hapax's architecture does not separate them — they share perception, evaluation, and memory.
- "Continuous self-study as the research instrument" names the constitutive property established in Phase 7: the livestream IS the research instrument. This forecloses a clean back-stage / front-stage separation (Goffman) and forces specific roles (research-subject-and-instrument, research-participant) that would not arise in a system without continuous self-study.

### 3.2 Actant enumeration

The following actants are pertinent to the research question:

| Actant | Class | Notes |
|---|---|---|
| operator | human | single, axiom-anchored |
| Hapax | non-human (software stack) | both apparatus and what-is-studied |
| viewer | human (distributed) | YouTube audience; no grounding return |
| chat | non-human (channel) | YouTube chat; an actant because it modulates director decisions |
| camera | non-human (hardware fleet) | 6 USB cameras + 3 Pi NoIR edge devices |
| gear | non-human (studio hardware) | synths, drum machines, mixer, MIDI surfaces |
| room | non-human (physical) | studio-room, contact-mic, ambient conditions |
| ward | non-human (software) | overlay surfaces (sierpinski, token-pole, album art, PiPs, hothouse panels) |
| shader | non-human (software) | reverie/WGSL effect graph |
| axiom-registry | non-human (governance) | the five-axiom mesh |
| director | non-human (software) | studio-compositor director loop |
| daimonion | non-human (software) | voice daemon, turn-taking machinery |
| imagination | non-human (software) | DMN + reverie mixer |
| stimmung | non-human (software signal) | 11-dim state publisher |
| reverie | non-human (software surface) | wgpu visual surface |
| OSF registry | institution | pre-registration authority for Cycle 2 |
| YouTube platform | institution | broadcast infrastructure + ToS |
| employer | institution | corporate-boundary counterparty |
| household | institution (small) | shared-resource context |
| non-operator persons | human (transient) | visitors, delivery, co-inhabitants |

The list is not exhaustive, but covers the actants whose presence or absence changes the research question's characterization.

### 3.3 Derived positions (Hapax-facing)

Applying Step 3 to Hapax (the actant whose positions this taxonomy catalogs), eight thick positions emerge. They are carried in `axioms/roles/registry.yaml` and correspond to the Phase 7 locked taxonomy.

**Structural (species-type, axiom-anchored, 2 positions):**

- **executive-function-substrate** — whom-to: architectural; answers-for: EF-prosthesis-for-single-operator. Species-type claim; removing it un-makes what Hapax is.
- **research-subject-and-instrument** — whom-to: architectural; answers-for: self-as-apparatus-for-the-study, self-as-what-is-under-study. Subject-instrument fusion per 2026-04-16 operator decision.

**Institutional (thick roles in external networks, 4 positions):**

- **executive-function-assistant** — whom-to: operator; answers-for: orientation, pacing, drift-capture, plan-coherence, ledger-honesty, nudge-timing, consequence-surfacing. Stabilized by the operator-Hapax network.
- **livestream-host** — whom-to: audience-and-youtube-platform; answers-for: broadcast-safety, show-rhythm, scene-composition, chat-engagement, content-stewardship, platform-tos-adherence. Subsumes the producer/compositor/attendant activities.
- **research-participant** — whom-to: osf-registered-study; answers-for: condition-fidelity, protocol-adherence, behavior-as-data, not-gaming, pre-registration-integrity. Distinct from the structural research-subject-and-instrument position by virtue of being tied to a specific study (Cycle 2).
- **household-inhabitant** — whom-to: operator-household-and-employment-context; answers-for: corporate-boundary, privacy-of-non-participants, shared-resource-etiquette, employer-data-isolation.

**Relational (schemas for who-is-in-the-loop, 2 positions):**

- **partner-in-conversation** — whom-to: dyad-or-triad-in-loop; answers-for: turn-taking, grounding, mutual-modeling, repair. Instances inferred from daimonion speaker-id + active-session-state; instantiation is loop-state, not registry state.
- **addressee-facing** — whom-to: one-way-broadcast-audience; answers-for: broadcast-appropriate-register, no-grounding-requirement, no-turn-taking-expectation. Instances inferred from stream-mode + chat-signals.

The description-spec design spec (`docs/superpowers/specs/2026-04-18-role-derivation-research-template-design.md`) posits up to one additional relational position ("ontological-collaborator") under review for the Cycle 2 condition in which Hapax's outputs feed back into the registry it is being studied within. That position is deferred: it failed the Step 5 collapse test in the current research question because research-participant + research-subject-and-instrument jointly cover the same characterization.

### 3.4 Cross-reference to `is_not:` constraints (from #155 Stage 3)

The #155 anti-personification linter uses `is_not:` fields on every non-structural role to constrain allowable descriptions. The method above *produces* those fields at Step 5: the collapse-test byproduct is an enumeration of what the role is being distinguished against.

Example: `executive-function-assistant.is_not` includes `emotional-support-partner`, `therapist`, `friend-in-the-ontological-sense`, `personality-to-bond-with`. These are the descriptions a naïve authoring of the position (Step 3) would admit, which Step 4 and Step 5 exclude by reclassifying them as personification or as posture-drift. The linter operationalizes those exclusions at the document layer: any file that describes Hapax's EF-assistant role using the excluded patterns fails the lint.

The full `is_not:` enumeration for all eight Phase 7 positions lives in `axioms/roles/registry.yaml`. The methodology is therefore the upstream producer of the linter's constraints; the linter is the downstream enforcement surface.

### 3.5 Persona / posture / role separation in practice

The Phase 7 locked taxonomy enforces the Step 4 separation:

- **Persona:** `axioms/persona/hapax-description-of-being.md` — describes what Hapax is (substrate, continuous perception, affordance-gated recruitment, memory-with-provenance, gated interpersonal surface). Not a role.
- **Posture:** `axioms/persona/posture-vocabulary.md` — glossary of named consequences of architectural state. Not roles. Eight named postures (`focused`, `exploratory`, `cautious`, `retreated`, `guarded`, `stressed`, `dormant`, `observing`). No posture appears in the LLM system prompt by default.
- **Role:** `axioms/roles/registry.yaml` — eight positions across three layers. These are the outputs of Steps 3 and 5.

The Phase 7 redesign spec (`docs/superpowers/specs/2026-04-16-lrr-phase-7-redesign-persona-posture-role.md`) documents this separation's construction. This methodology document formalizes the *method* that produced it, so that future amendments or re-derivations can proceed by the same steps rather than by ad-hoc authoring.

---

## 4. Template (reproducible for other systems)

The reusable template lives at `docs/research/role-derivation-template.md`. It mirrors §2 step-by-step with fillable placeholders (`[FILL: ...]`). An engineer or researcher deriving a role taxonomy for a new system or a new research question copies that template, replaces placeholders, and produces a valid per-system role document.

Template structure (summary; full template in the companion file):

| Template section | Maps to method step | Placeholder type |
|---|---|---|
| Research question | §2 Step 1 | single declarative sentence |
| Actant enumeration | §2 Step 2 | table (actant, class, notes) |
| Candidate position table | §2 Step 3 | table (whom-to, answers-for, amendment-gating) |
| Persona / posture / role classification | §2 Step 4 | three-column allocation |
| Collapse test results | §2 Step 5 | per-candidate pass/fail with rationale |
| Final taxonomy | §2 Step 5 output | list of surviving positions with `is_not:` |
| Registry YAML proposal | operational | ready-to-merge block |

The template is intentionally system-agnostic. Hapax-specific constraints (livestream-as-instrument, continuous self-study, axiom mesh) are called out as *example adjustments* in the template prose; other systems will have different adjustments.

---

## 5. Relationship to existing governance surfaces

### 5.1 Phase 7 locked taxonomy

`docs/superpowers/specs/2026-04-16-lrr-phase-7-redesign-persona-posture-role.md` was the authoring spec for the current taxonomy. It describes the redesign's motivation and content. This methodology document formalizes *how* that taxonomy was produced so it can be reproduced or extended without replaying the authoring discussion. The methodology is therefore the post-hoc derivation trace of Phase 7, not a replacement for it.

### 5.2 Anti-personification linter (#155)

`docs/superpowers/specs/2026-04-18-anti-personification-linter-design.md` describes the lint that enforces `is_not:` constraints across the codebase. The derivation method produces those constraints at Step 5 — every surviving role's `is_not:` list is the set of descriptions the collapse test excluded. The linter therefore depends on this methodology for its constraint source: without derived `is_not:` fields, the linter has no anchor.

A concrete coupling: when a new role is added via the methodology, Step 5's output must include the `is_not:` list, which then flows into `axioms/roles/registry.yaml::is_not:`. The linter picks up the new constraints automatically on next run.

### 5.3 PerceptualField and stance

Posture is explicitly not position (§2 Step 4). The stance signal (`stance=nominal|cautious|seeking|degraded|critical`) feeds posture vocabulary (`axioms/persona/posture-vocabulary.md`), not roles. Any proposal to add a stance-keyed role must fail Step 4 — stance drives posture, posture is named consequence, and roles are research-relative thick positions independent of any single stance value.

This separation also protects against drift in the other direction: adding a new posture does not add a role, and retiring a posture does not retire a role. The two vocabularies evolve independently under their own rules.

### 5.4 Persona document

`axioms/persona/hapax-description-of-being.md` is the description-of-being artifact. It names species-type claims and architectural invariants. It is not produced by this methodology — it is the *input* to Step 4, providing the persona column against which candidate positions are separated. If the persona document changes structurally (e.g., a species-type claim is added), the taxonomy must be re-validated by Step 5 to confirm no role has silently drifted into persona territory.

---

## 6. Future extensions

### 6.1 When a new research question lands

The method is keyed to the research question. A genuinely new research question (not a refinement of the existing one) requires a fresh derivation: new actant enumeration, new candidate positions, new collapse tests. The new derivation may or may not produce a taxonomy congruent with the current one.

Three scenarios are anticipated:

1. **Additive research question.** The new question extends the current one without contradicting it. Example: "how does Hapax's perception stack generalize across studio configurations?" is additive to the current question. The existing taxonomy may gain one or two positions (e.g., related to studio-configuration-subject); existing positions do not collapse.
2. **Refining research question.** The new question is a sub-question of the current one. No new derivation is needed; the existing taxonomy remains valid. The sub-question may sharpen specific `answers_for` enumerations but does not add or remove positions.
3. **Replacing research question.** The new question redefines the phenomenon under study. Example: generalizing from single-operator to multi-operator would violate the `single_user` axiom and replace the research question. A full re-derivation is required; the existing taxonomy is archived, not extended.

### 6.2 Additive vs refactor

An *additive* extension adds positions or `answers_for` items without changing existing ones. Additive extensions are cheap: they extend the registry, run the linter, and land in a single PR. The Step 5 collapse test must still pass for the new position (it must have a unique contribution to the research question's characterization).

A *refactor* extension modifies or removes existing positions. Refactors are amendment-gated for structural roles and require operator review for institutional/relational roles. A refactor must document why a role that previously passed Step 5 now fails it — typically because the research question has drifted, which (per §6.1) requires addressing whether the drift is additive, refining, or replacing.

The default bias is additive. Refactors are reserved for cases where the existing taxonomy demonstrably misrepresents the research question's dynamics, evidenced by repeated grep failures, consistent ambiguity at the enforcement layer, or explicit operator direction.

### 6.3 Re-derivation cadence

The methodology does not impose a re-derivation cadence. Taxonomy stability is valuable; unnecessary re-derivation is expensive and disruptive. The recommended triggers for re-derivation are:

- A new axiom is added or an existing axiom is modified.
- The research question is explicitly amended by operator decision.
- A new actant class appears that cannot be held by any existing position (i.e., the new actant systematically escapes the current taxonomy).
- The linter accumulates repeated violations that cannot be resolved by `is_not:` extension.

Absent these triggers, the current taxonomy remains load-bearing. Phase 7's locked-window protocol (currently in redesign-validation) governs the specific freezing rules.

---

## 7. References

- `docs/superpowers/specs/2026-04-16-lrr-phase-7-redesign-persona-posture-role.md` — Phase 7 redesign authoring spec
- `docs/superpowers/specs/2026-04-18-role-derivation-research-template-design.md` — design spec for this task (CVS #156)
- `docs/superpowers/specs/2026-04-18-anti-personification-linter-design.md` — #155 linter design
- `docs/research/role-derivation-template.md` — companion template artifact
- `axioms/roles/registry.yaml` — current locked taxonomy
- `axioms/persona/hapax-description-of-being.md` — persona description-of-being
- `axioms/persona/posture-vocabulary.md` — posture glossary
- Latour, B. (2005). *Reassembling the Social: An Introduction to Actor-Network-Theory.* Oxford University Press.
- Callon, M. (1986). "Some Elements of a Sociology of Translation." In Law, J. (ed.) *Power, Action and Belief.*
- Law, J. (1992). "Notes on the Theory of the Actor-Network." *Systems Practice,* 5(4).
- Clark, H. H. & Brennan, S. E. (1991). "Grounding in Communication." In Resnick, L. B. et al. (eds.) *Perspectives on Socially Shared Cognition.* APA.
- Goffman, E. (1981). *Forms of Talk.* University of Pennsylvania Press.
