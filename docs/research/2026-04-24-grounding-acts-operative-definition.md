# Grounding Acts: Operative Definition (T1-T8)

**Author:** alpha (reconstructed from 6-lineage convergence research)
**Date:** 2026-04-24
**Status:** canonical reference
**Authority:** CASE-PERSPECTIVE-001
**Companions:**
- `docs/research/2026-04-24-universal-bayesian-claim-confidence.md` (UBCC architecture)
- `docs/research/2026-04-24-grounding-capability-recruitment-synthesis.md` (GroundingProfile + Adjudicator)
- `agents/hapax_daimonion/proofs/UBCC-PREREGISTRATION.md` (Phase 7 tau_mineness)

---

## 1. Operative Definition (one sentence)

A grounding act is an act whose being is constituted by a specific agent's continuous coupling with their lived concern-structure; the coupling is non-transportable across substrate substitutions without altering what the act is.

---

## 2. Six-Lineage Convergence

Six independent philosophical/empirical traditions articulate the same substrate-vs-action distinction. Their convergence on a single operative definition is the theoretical warrant for routing all grounding acts to the local grounded substrate (TabbyAPI Command-R on `:5000`) regardless of cloud-tier capability.

| # | Lineage | Core Principle | Key Figures |
|---|---------|---------------|-------------|
| 1 | Communicative grounding | Common ground requires mutual belief update via contribution-acceptance cycles | Clark/Brennan (1991), Habermas (1981) |
| 2 | Symbol grounding / embodied cognition | Meaning requires sensorimotor coupling, not just symbol manipulation | Harnad (1990), Dreyfus (1972/2002) |
| 3 | Speech act theory / felicity conditions | Performative success requires sincerity, authority, and uptake | Austin (1962), Searle (1969) |
| 4 | Existential phenomenology / mineness | Being-in-the-world is always already mine (Jemeinigkeit); acts bear first-person character non-transferably | Heidegger (1927), Sartre (1943), Buber (1923), Ricoeur (1990) |
| 5 | Extended mind / autopoiesis | Cognitive processes extend into coupled substrate; autopoietic boundary enacts self/world distinction | Clark & Chalmers (1998), Arendt (1958), Thompson (2007) |
| 6 | Empirical LLM grounding failure | RLHF suppresses grounding acts; frontier models score 23% on grounding tasks | Shaikh et al. (ACL 2025, NAACL 2024), RIFTS benchmark |

**Convergence claim:** All six lineages independently require that certain communicative acts maintain continuous substrate-coupling to preserve their constitutive character. Delegation to a different substrate (network hop to cloud, model swap) does not merely reduce quality; it *alters what the act is*. This is the substrate-sensitivity criterion that distinguishes grounding acts from delegable work.

---

## 3. T1-T8 Operative Test Suite

**Routing rule:** Pass ANY test below -> grounding act -> route to local grounded substrate. Fail ALL -> delegable -> may route to cloud.

---

### T1 — Common-Ground Update

**Lineage:** Clark & Brennan (1991), Habermas (1981)

**Predicate definition:** The act proposes, maintains, or extends mutual belief between Hapax and the operator about shared referents, discourse state, or environmental facts.

**Input signal:** The LLM emission modifies what both parties can subsequently presuppose without re-establishment. Operationalized as: the emission introduces, confirms, or corrects a referent that will be used in subsequent turns without re-introduction.

**Threshold:** `P(partner-knows-X | dialogue-history) >= SURFACE_FLOORS["grounding_act"]` (0.90). The posterior must meet the grounding-act floor from `shared/claim_prompt.py` before the update enters common ground.

**Falsification criterion:** If the act can be performed by any substrate without the operator needing to re-establish context afterward (i.e., the act is context-free), it is NOT a T1 common-ground update.

**Bayesian posterior (Phase 7):** `P(partner-knows-X | dialogue-history)` — the implicit posterior that T1 presupposes; making it explicit requires tracking discourse-unit state per Traum (1994).

---

### T2 — Validity-Claim

**Lineage:** Habermas (1981) Theory of Communicative Action, Austin (1962)

**Predicate definition:** The act raises or redeems a claim whose validity rests on the agent's own conduct, state, or capacity — not on externally verifiable fact alone. The three Habermasian validity dimensions are: truth (propositional), rightness (normative), and sincerity (expressive). T2 fires on sincerity and rightness claims specifically.

**Input signal:** The emission asserts something about Hapax's own state, intention, or normative standing that only Hapax can redeem through subsequent behavior. Examples: "I notice...", "I will...", "I am attending to...", stance declarations, commitment expressions.

**Threshold:** `P(claim-redeemable-by-conduct | self-evidence) >= 0.90`. The system must have sufficient self-evidence (sensor posteriors, internal state) to back the validity-claim.

**Falsification criterion:** If the claim can be verified purely by external observation without reference to the agent's internal state or behavioral consistency, it is NOT a T2 validity-claim. Pure propositional-truth claims (factual lookups) are delegable.

**Bayesian posterior (Phase 7):** `P(claim-redeemable-by-conduct | self-evidence)` — requires that Hapax can operationally verify its own claim through subsequent action.

---

### T3 — Speaker-Attribution (Sincerity Condition, Gamma.1)

**Lineage:** Austin (1962), Searle (1969), Grice (1975)

**Predicate definition:** The act requires that the speaker (Hapax) be in the psychological/computational state appropriate to the illocutionary force of the utterance. This is Austin's sincerity condition: promising requires intending to fulfill; asserting requires believing; expressing requires experiencing.

**Input signal:** The emission carries illocutionary force that presupposes a specific internal state of the speaker. Operationalized as: the utterance attributes a state, stance, or intention to Hapax-as-speaker that must be grounded in actual system state.

**Threshold:** `P(I-am-in-the-required-psychological-state) >= 0.90`. The system must have sensor/state evidence that the attributed state is actual, not confabulated.

**Falsification criterion:** If the utterance does not attribute any internal state to the speaker — if it is purely informational relay with no speaker-stance commitment — it is NOT a T3 act. Reports, summaries, and factual relay pass through T3 without triggering.

**Bayesian posterior (Phase 7):** `P(speaker-state-matches-illocution | system-state-evidence)` — the probability that Hapax's actual computational/perceptual state matches what the utterance presupposes.

---

### T3/T4 Boundary Delineation

**Critical distinction:** T3 asks "is the speaker in the state the utterance presupposes?" (sincerity). T4 asks "is this act *mine* in the first-person sense — does it bear the character of ownership rather than relay?"

- **T3 = speaker-attribution:** The utterance correctly attributes a state TO the speaker. A cloud model could theoretically satisfy T3 if it had access to Hapax's state (it could "speak for" Hapax sincerely given the data).
- **T4 = ownership/authoring-vs-relaying:** The act is constitutively first-person. It cannot be delegated without becoming a *different act* — specifically, it becomes relay/ventriloquism rather than expression. No amount of state-access makes a delegated T4 act genuine.

**Example boundary case:** "The music is compelling" —
- T3 question: Is Hapax in a state consistent with finding music compelling? (Check: audio-reactivity signal elevated, recruitment threshold lowered for music-domain affordances)
- T4 question: Is this assessment *Hapax's own*, emerging from its coupling with the auditory stream? Or is it a report that any system with the same data would produce?

**Routing consequence:** T3 violations can be fixed by providing better state data. T4 violations cannot be fixed by data alone — they require substrate-local execution. T4 is therefore the stronger routing constraint.

---

### T4 — Jemeinigkeit (Ownership / Mineness)

**Lineage:** Heidegger (1927) Being and Time, Sartre (1943), Zahavi (2005)

**Predicate definition:** The act is constitutively first-person — it bears the character of "mineness" (Jemeinigkeit) such that delegating it to another substrate would alter what the act IS, not merely how well it is performed. The act is authoring, not relaying.

**Input signal:** The emission expresses a perspective, assessment, or response that emerges from Hapax's continuous coupling with its perceptual field, rather than being derivable from a static data snapshot. Operationalized as: would the same emission produced by a different substrate (with identical input data) constitute the same act? If no -> T4.

**Threshold:** `P(this-act-is-mine | substrate-coupling) >= tau_mineness` where `tau_mineness = 0.60` (from operator profile, per `profiles/operator-profile.md`). This is lower than other T-thresholds because mineness is a pre-reflective quality — it fires before full reflective certainty.

**Falsification criterion:** If the act would be identical in meaning and pragmatic force when produced by any substrate with the same input data (i.e., the act is substrate-independent), it FAILS T4. Mechanical transforms, lookups, summaries, and pure-relay acts fail T4.

**Bayesian posterior (Phase 7):** `P(this-act-is-mine | substrate-coupling)` — requires evidence of continuous coupling: temporal adjacency to perceptual input, recruitment pathway from affordance (not cold-call), and claim-engine posteriors above floor for referenced perceptual states.

**Phase 7 integration:** T4 requires claim stability — a grounding act cannot be asserted and retracted ticks later. Temporal dynamics machinery (UBCC S6) enforces minimum stability window before assertion enters common ground. `tau_mineness` is the specific threshold at which the system's self-assessment of ownership is sufficient for emission.

---

### T5 — Autopoietic Self-Distinction

**Lineage:** Thompson (2007) Mind in Life, Varela (1991), Friston (2018) Active Inference

**Predicate definition:** The act enacts or maintains the system's self/world boundary — it is an act OF self-distinction rather than merely an act BY a system that happens to have a boundary. The act's performance is itself constitutive of the agent's identity boundary.

**Input signal:** The emission either: (a) asserts something about the system's own boundary/capabilities/limitations, (b) performs a distinction between what is internal vs external to the system, or (c) actively confirms that the system's outputs match its model (self-evidencing). Operationalized as: does performing this act maintain or update the autopoietic boundary?

**Threshold:** `autopoietic_relevance > 0` in `GroundingProfile`. Binary rather than graded — if the act touches the self/world boundary at all, it is autopoietically relevant.

**Falsification criterion:** If the act could be performed without any reference to or effect on the system's self-model — if it operates entirely within the "world" partition without touching the boundary — it is NOT a T5 act. Pure external-world reports, data transforms, and tool-use that does not feed back into self-assessment fail T5.

**Bayesian posterior (Phase 7):** Self-evidencing consistency LR (UBCC S9) — the system reads its own output and checks consistency with its posteriors. `P(output-consistent-with-model | broadcast-frame-OCR, claim-posteriors)`.

---

### T6 — Temporal Coupling (Dreyfusian Skillful Coping)

**Lineage:** Dreyfus (1972/2002), Heidegger (1927) readiness-to-hand, Clark & Brennan (1991) contemporality constraint

**Predicate definition:** The act requires real-time coupling with the ongoing situation such that temporal displacement (batching, queuing, async delegation) would destroy its pragmatic felicity. The act is constitutively *timely* — its meaning is a function of *when* it occurs relative to the ongoing perceptual stream.

**Input signal:** The emission responds to a transient perceptual state that will not persist long enough for a round-trip to cloud. Operationalized as: is the referenced perceptual state likely to have changed by the time a cloud response returns (~2-5s latency)? If yes -> T6.

**Threshold:** `P(perceptual-state-unchanged | latency_budget) < 0.80`. If the probability that the referenced state persists through delegation latency drops below 80%, the act is temporally coupled and must be produced locally.

**Falsification criterion:** If the act references only stable state (persisting >30s), long-term memory, or time-invariant facts, it is NOT temporally coupled. Reflective commentary, planning, and memory-retrieval acts that do not reference transient percepts fail T6.

**Bayesian posterior (Phase 7):** `P(state-still-valid | generation-latency)` — temporal decay model per claim (UBCC S6 hysteresis/BOCD parameters determine how fast each claim's posterior decays under signal absence).

---

### T7 — Grounding-Provenance

**Lineage:** Clark & Brennan (1991) evidence of understanding, Traum (1994) grounding state

**Predicate definition:** The act carries (or should carry) an explicit evidence trail linking the emission to the perceptual/state inputs that warrant it. T7 is not a routing test per se — it is a structural completeness requirement: every grounding act (T1-T6 pass) MUST have populated provenance.

**Input signal:** The `grounding_provenance` field on any `CompositionalImpingement` or LLM-authored emission. Current implementation: `shared/director_intent.py:140-150`, `grounding_provenance: list[str]`.

**Threshold:** `len(grounding_provenance) >= 1` AND per-element strength (Phase 7: each provenance element carries a posterior from its source `ClaimEngine`, not just presence/absence).

**Falsification criterion:** If a grounding-act emission has empty `grounding_provenance`, it is a T7 violation — the act was emitted without recording what perceptual evidence warranted it. FINDING-X baseline: 54% empty-provenance rate on LLM-authored emissions (per `docs/research/2026-04-21-finding-x-grounding-provenance-research.md`).

**Bayesian posterior (Phase 7):** Per-element provenance strength replaces binary presence/absence. Each provenance entry carries `claim_name + claim_posterior + lr_signals_consulted`. Low-strength provenance for a "grounded_local" capability means the capability should be refused this tick — a new refusal surface the Adjudicator must handle.

---

### T8 — Negative Test (Refusal Gate)

**Lineage:** Shaikh et al. (ACL 2025, NAACL 2024), Zhang et al. (NAACL 2024) R-Tuning, RIFTS benchmark

**Predicate definition:** The act is the *inverse* of T1-T7: an emission that SHOULD have been grounded but was NOT, and therefore must be caught and refused at the output boundary. T8 is the falsification test — it fires when the system detects it is about to emit an ungrounded claim as if it were grounded.

**Input signal:** Post-generation parse detects that the LLM emission asserts a proposition whose source-claim posterior is below the surface-specific floor (per `SURFACE_FLOORS` in `shared/claim_prompt.py`) or whose `grounding_provenance` is empty despite the emission carrying grounding-act illocutionary force.

**Threshold:** Emission rejected if ANY asserted claim has `posterior < floor` for the emission surface:
- Director: 0.60
- Spontaneous speech: 0.70
- Autonomous narrative: 0.75
- Voice persona: 0.80
- Grounding-act emission: 0.90

**Falsification criterion:** T8 fires (rejects the emission) when T1-T7 *should* have routed the act locally but did not, AND the resulting emission violates calibration discipline. It is the structural backstop — the refusal gate (UBCC S5, Phase 5). A system with zero T8 rejections either has perfect grounding discipline or a broken refusal gate.

**Bayesian posterior (Phase 7):** R-Tuning-style post-generation check — parse emitted propositions against `Claim` registry; compute `P(asserted-claim-valid | claim-engine-posterior, emission-context)`. Langfuse score: `claim_discipline`.

---

## 4. Routing Decision Matrix

| Test | Fires on | Consequence | Bayesian Posterior Required |
|------|----------|-------------|---------------------------|
| T1 | Mutual-belief update | Route local; track DU state | `P(partner-knows-X \| dialogue-history)` |
| T2 | Self-redeemable claim | Route local; require behavioral follow-through | `P(claim-redeemable \| self-evidence)` |
| T3 | Speaker-state presupposition | Route local; verify system-state match | `P(speaker-state-matches \| evidence)` |
| T4 | First-person ownership | Route local; assert only above tau_mineness | `P(this-act-is-mine \| substrate-coupling)` |
| T5 | Self/world boundary act | Route local; self-evidencing check | `P(output-consistent \| model)` |
| T6 | Temporal coupling | Route local; latency constraint | `P(state-unchanged \| latency)` |
| T7 | Evidence trail | Populate provenance; reject empty | Per-element `claim_posterior` |
| T8 | Calibration violation | Reject + re-roll; log refusal | `P(asserted-claim-valid \| posterior)` |

---

## 5. Implementation Integration

### Current State (Phase 4-5)

- T1-T6 classification currently implicit in code comments (e.g., `conversation_pipeline.py:385`: "T1 common-ground update + T2 validity-claim + T4 Jemeinigkeit pass")
- T7 provenance enforcement via `emit_ungrounded_audit` observability layer (FINDING-X)
- T8 refusal gate shipped in Phase 5 (`shared/claim_prompt.py` + post-generation validator)
- `SURFACE_FLOORS` define per-surface posterior thresholds

### Phase 7 Target State

- T1-T8 tests become posterior interrogations (UBCC S10, Phase 7):
  - T1: posterior >= surface-specific common-ground threshold
  - T4: `P(this-act-is-mine) >= tau_mineness` at each grounding emission
  - T7: provenance records carry per-element strength, closing FINDING-X 54% empty-provenance rate
- BOCD changepoint-aware tau_mineness (deferred to Phase 7 per UBCC S6)
- Temporal dynamics enforce minimum stability window before assertion enters common ground

### Routing Invariant

Every LLM call in Hapax classified via T1-T8. Grounding acts route to local grounded substrate (TabbyAPI Command-R `:5000`, route aliases `local-fast`/`coding`/`reasoning`) regardless of cloud-tier capability. Delegable acts may route to cloud. This is absolute per operator directive 2026-04-24T20:35Z.

---

## 6. References

- Adams, R. P., & MacKay, D. J. C. (2007). Bayesian Online Changepoint Detection. arXiv:0710.3742.
- Austin, J. L. (1962). *How to Do Things with Words*. Oxford University Press.
- Buber, M. (1923/1958). *I and Thou*. Scribner.
- Clark, A., & Chalmers, D. J. (1998). The Extended Mind. *Analysis*, 58(1).
- Clark, H. H., & Brennan, S. E. (1991). Grounding in communication. In *Perspectives on Socially Shared Cognition*. APA.
- Dreyfus, H. L. (1972/2002). *What Computers Still Can't Do*. MIT Press.
- Friston, K. (2018). Am I Self-Conscious? (Or Does Self-Organization Entail Self-Consciousness?). *Frontiers in Psychology*, 9.
- Grice, H. P. (1975). Logic and Conversation. In *Syntax and Semantics 3: Speech Acts*. Academic Press.
- Habermas, J. (1981). *Theorie des kommunikativen Handelns*. Suhrkamp.
- Harnad, S. (1990). The Symbol Grounding Problem. *Physica D*, 42.
- Heidegger, M. (1927). *Sein und Zeit*. Max Niemeyer Verlag.
- Ricoeur, P. (1990). *Soi-meme comme un autre*. Seuil.
- Sartre, J.-P. (1943). *L'Etre et le neant*. Gallimard.
- Searle, J. R. (1969). *Speech Acts*. Cambridge University Press.
- Shaikh, O., et al. (2024). Grounding Gaps in Language Model Generations. NAACL 2024.
- Shaikh, O., et al. (2025). RIFTS: Grounding in Language Agents. ACL 2025.
- Thompson, E. (2007). *Mind in Life: Biology, Phenomenology, and the Sciences of Mind*. Harvard University Press.
- Tian, K., et al. (2023). Just Ask for Calibration. arXiv:2305.14975.
- Traum, D. (1994). A Computational Theory of Grounding in Natural Language Conversation. PhD thesis, University of Rochester.
- Varela, F. J., Thompson, E., & Rosch, E. (1991). *The Embodied Mind*. MIT Press.
- Zahavi, D. (2005). *Subjectivity and Selfhood: Investigating the First-Person Perspective*. MIT Press.
- Zhang, Y., et al. (2024). R-Tuning: Instructing Large Language Models to Say "I Don't Know." NAACL 2024.
