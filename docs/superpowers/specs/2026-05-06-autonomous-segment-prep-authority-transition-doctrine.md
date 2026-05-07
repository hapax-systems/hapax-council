# Autonomous Segment Prep Authority-Transition Doctrine

**Status:** design doctrine, implementation paused pending operator review
**Checked at:** 2026-05-06
**Scope:** content/segment prep, source recruitment, segment form, script/actionability/layout contracts, review gates, and non-anthropomorphic personage.

## Decision

Segment prep should be freed by moving constraints from form to authority
transition.

Hapax should be able to choose topic, source class, form, structure, action
plan, layout need, source follow-up depth, and submission timing through its own
operational determinations: opportunity priors, source pressure, affordance
recruitment, novelty, uncertainty, risk, budget, and runtime responsibility.

Hard gates should answer only authority questions:

- may this artifact claim;
- may it publish;
- may it load;
- may it command runtime;
- may it recruit external sources;
- may it spend additional budget;
- may it enter selected release;
- must it refuse, narrow, quarantine, or record a no-candidate dossier.

The rule is:

> Forms are generated; authority is gated.

## Constraint Classes

### Hard Invariants

These constraints may fail closed. They preserve authority, privacy, safety,
provenance, and public accountability. They are not artificial choreography.

- Resident Command-R only for prep; no fallback model and no unload/reload
  prep workflow.
- Artifact authority remains `prior_only`.
- Provenance hashes bind model, prompt, seed, source packets, contracts, and
  review receipts.
- Claims require evidence, uncertainty, scope limits, freshness where relevant,
  rights/privacy posture, and correction path.
- Source guidance can shape priors and criteria; it does not transfer
  authority.
- Prepared layout remains proposal-only; runtime readback must witness layout
  success.
- Static/default layout is fallback or non-responsible context, not responsible
  success.
- Validators may reject, quarantine, narrow, or request recruitment; they must
  not silently author the artifact.
- `manifest.json` is eligibility only. `selected-release-manifest.json` is the
  runtime pool boundary.
- Non-anthropomorphic register is mandatory: operational agency is allowed;
  fake human feeling, empathy, rapport, private taste, concern, or human-host
  imitation is not.
- Budget, quota, and egress ceilings are resource limits, not content
  templates.

### Soft Priors

These constraints bias attention without eliminating valid candidates except
through an explicit hard invariant.

- programmes;
- operator-local context;
- temporality bands;
- current source pressure;
- role/form exemplars;
- professional standards, examples, counterexamples, and quality ranges;
- novelty, boredom, curiosity, learning progress, and coherence pressure;
- cost, reversibility, source availability, and runtime capability likelihood.

Soft priors should remain scored, traceable, and revisable. They should not
become fixed role membership, fixed beat anatomy, exact phrase requirements, or
deterministic fallback content.

### Inquiry Budgets

Inquiry budgets limit time, calls, risk, egress, and cost. They should not
predefine the micro-structure of research.

Within budget and hard invariants, Hapax should be able to follow leads
freely: search again, branch, abandon a lead, consult standards, compare
counterexamples, recruit a source, or decide that no loadable segment is
justified.

Budget exhaustion should produce a no-release or no-candidate dossier with
remaining gaps, not a forced low-quality segment.

## Artificial Constraint Pattern

A constraint is artificial or expert-system-like when it prescribes shape
instead of guarding authority.

Current suspicious residues include:

- fixed segmented-role eligibility instead of a form/capability contract;
- universal opening/body/closing anatomy;
- minimum beat counts and fixed 30-60 minute assumptions;
- raw character-count floors as quality proxies;
- exact trigger phrases used as release authority for actionability;
- deterministic canary fallback as automatic content;
- source-readiness as shape validation rather than active inquiry;
- fixed review-team choreography as a universal release pattern;
- validator-generated contract backfill masquerading as model-authored
  source/action reasoning.

Some of these may remain temporarily as fixtures, scaffolds, or diagnostics, but
they must be marked as such and not treated as the design ideal.

## Target Architecture

Segment prep should split into two layers.

### 1. Freedom Layer

The freedom layer is an autonomous inquiry workspace. It owns:

- topic/source opportunity formation;
- source recruitment and follow-up;
- form generation or form selection;
- segment structure;
- script drafting;
- actionability proposal;
- layout-need proposal;
- self-critique;
- decision to submit, continue, abandon, or emit a no-candidate dossier.

It should operate as a blackboard/impingement process, not a fixed pipeline:
specialized capabilities observe the current inquiry state, propose work, add
receipts, surface gaps, and compete for budget. Termination is by quiescence,
submission, refusal, or budget exhaustion.

Quiescence means no unresolved lead, source gap, quality gap, authority gap, or
runtime responsibility gap remains above the current risk/budget threshold.

### 2. Authority Layer

The authority layer is deterministic and conservative. It decides what the
artifact is allowed to do:

- private scratch only;
- eligible candidate;
- selected release;
- runtime pool load;
- public live;
- public archive;
- monetizable;
- needs source recruitment;
- needs operator consent;
- needs runtime readback;
- must refuse, narrow, quarantine, or correct.

The authority layer must not author the segment. It emits impingements,
blockers, receipts, and authority transitions.

## Artifact Contract

A segment candidate should declare:

- source pressure: why this is worth doing now;
- grounding question;
- permitted claim shape and authority ceiling;
- evidence packet and source consequence;
- unresolved gaps and why they are acceptable or blocking;
- form chosen or generated, with rationale;
- live-event object, if any;
- audience job or refusal/no-candidate reason;
- action/readback/layout affordance proposal;
- runtime responsibility boundary;
- non-anthropomorphic register posture;
- budget spent and budget remaining;
- release request class.

It should not be required to fit a universal segment anatomy. A valid candidate
might be a short refusal, a source audit, a visual comparison, an interview
state machine, a long ranking bit, a recruitment interlude, a silent evidence
surface, or a no-release diagnostic.

## Operational Consequences

1. Replace role eligibility with a form/capability contract. Existing roles
   become exemplars, not the closed ontology.
2. Replace fixed beat and length rules with sufficiency receipts tied to source
   density, temporal coupling, action obligations, pacing budget, and runtime
   readback needs.
3. Replace regex phrase authority with authored structured action intents:
   object, operation, evidence, expected visible effect, fallback, and receipt.
4. Replace one-shot compose/refine with an inquiry loop that can recruit more
   evidence, consult standards, branch, abandon, or submit.
5. Replace automatic deterministic canary fallback with a no-candidate/source
   recruitment receipt. Keep deterministic canaries only as explicit fixtures.
6. Keep validation gates, but make them authority-transition gates rather than
   content-shaping authors.
7. Make source follow-up self-directed inside budget and egress limits.
8. Require every "good segment" claim to name the evidence and operational
   criteria that make it good; do not let craft standards become hidden expert
   verdicts.
9. Treat no-release as a successful outcome when the system cannot justify a
   segment under current evidence, authority, or runtime responsibility.

## Predictive Expectations

Expected effects if this doctrine is implemented thoroughly:

| Problem cluster | Expected effect | Confidence | Rationale |
|---|---:|---|---|
| Topic anchoring and repeated example collapse | Large improvement | High | Automatic deterministic fallback and closed role prompts are direct anchoring sources. |
| Premise weakness | Medium-large improvement | Medium | Source pressure and self-directed inquiry should improve premises, but quality depends on available standards and candidate review. |
| Specificity/source fidelity | Large improvement | High | Free source follow-up plus source consequence receipts targets this failure directly. |
| Actionability slop | Large improvement | Medium-high | Structured action intents replace phrase-trigger theater. Runtime capability availability remains a limiting factor. |
| Layout responsibility | Medium improvement | Medium | Proposal/readback split is already right; improvement comes from making layout needs generated from real segment objects, not templates. |
| Non-anthropomorphic personage | Medium improvement | Medium | Authority-language and operational agency help, but adjacent craft guidance remains anthropocentric and needs continued lint/review. |
| Prep latency/resource use | Increase | High | Free inquiry consumes more time/calls. This is acceptable under the one-hour quality budget. |
| Chaos/overproduction risk | Medium risk | Medium | Mitigated by hard authority gates, budgets, quiescence criteria, and no-release dossiers. |

## Research Basis

This doctrine is consistent with the current local research stack:

- standards as calibration surfaces, not scripts;
- grounding attempts, not expert verdicts;
- source/action/live-event contracts with scripts attached;
- prep as feedforward planning and runtime as witnessed control loop;
- blackboard-style impingement and recruitment;
- requisite variety: the regulator must preserve enough internal variety to
  handle environmental variety;
- runtime assurance: autonomy operates inside an accountable envelope;
- active learning and curiosity: inquiry should follow expected information
  gain and learning progress, not fixed pass counts;
- mixed initiative: initiative shifts according to uncertainty, risk, cost, and
  context;
- anti-personification: public explanation names signals, models, traces, and
  authority outcomes rather than imaginary humanlike motives.

## Non-Goals

- Do not remove consent, privacy, provenance, rights, freshness, or release
  gates.
- Do not let freedom mean unsupported public claims.
- Do not let prep command runtime layout.
- Do not replace fixed expert rules with an unobservable model vibe.
- Do not require a segment to be produced when no segment is justified.
- Do not use anthropomorphic desire, feeling, empathy, taste, or human-host
  rapport to explain Hapax decisions.
