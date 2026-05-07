# Systems/Control Map for Segment Prep and Runtime

**Status:** current_authority
**Checked at:** 2026-05-06T19:05:39-05:00
**Scope:** segment prep, release gates, programme runtime, responsible layout, interview prep, temporal bands, impingement/recruitment, and documentation discipline.

## Decision

Systems and control theory are operationally applicable to Hapax only where there is a real or declared loop boundary:

- plant or process boundary;
- controlled variable;
- reference signal;
- observation/sensor;
- actuator or release action;
- sample rate or review cadence;
- latency/staleness budget;
- fallback/saturation behavior;
- authority boundary;
- readback or receipt.

If these are absent, control language must be marked as feedforward planning, supervisory gating, design hypothesis, or analogy. It must not be used as a master ontology for Hapax personhood, operator behavior, audience response, scientific validity, market value, consciousness, empathy, taste, or human-like concern.

Implementation anchor: `shared.loop_card.ControlLoopCard`. Prepared segment artifacts may emit `feedforward_plan` loop cards. Runtime components may emit `closed_loop` or `supervisory_gate` loop cards only when they own the sensors, actuators, timing, fallback, and readback. Analogy-only uses must state their limits.

## Primary Mapping

| Surface | Mapping strength | Control-theory reading | Required limit |
|---|---|---|---|
| Daily segment prep | Strong as feedforward/MPC-like planning | Command-R generates priors, source/action contracts, layout needs, readback obligations, and loop cards for future runtime closure. | Prep cannot claim runtime success or command layout. |
| Candidate selection and release | Strong as supervisory control | Eligibility gates, excellence receipts, selected-release manifests, and Qdrant exposure are release actuators. | Hard gates do not prove excellence; they only prevent unsafe release. |
| Programme loop | Strong as multi-rate content controller | 1 Hz manager activates, completes, aborts, recycles, and writes active-segment state. | Predicate policies must fail closed when observations are missing. |
| Responsible layout | Strong as runtime assurance | Layout controller takes bounded needs, observes rendered readback, applies hysteresis/TTL, and emits receipts. | Static/default layout is fallback or non-responsible context, not success. |
| Interview segment | Strong once wrapped in FSM/contracts | Topic consent, question ladder, answer-source policy, turn receipts, release scope, and layout readback form the loop. | The operator is not the plant; the live exchange/segment process is. |
| Knowledge recruitment | Strong as uncertainty-triggered evidence acquisition | KnowledgeGapSignal is an error/uncertainty signal; recruitment acquires evaluated priors. | Sources guide judgment; they do not become runtime authority. |
| Temporality bands | Strong as multi-rate freshness constraints | Freshness bands define which evidence can support current, rolling, evergreen, operator-local, or constitutional claims. | A stable template cannot authorize a current claim. |
| Non-anthropomorphic register | Moderate as interface constraint | Control vocabulary gives useful nonhuman operational language. | Do not smuggle inner life through cybernetic terms. |
| Prediction ledger | Strong as calibration loop | Expected effects, metrics, observations, and posterior updates form the learning/calibration surface. | Ledger entries are not victory claims. |

## Rejected Overreach

- Treating Hapax as a human-like host with control-theory vocabulary pasted over it.
- Treating the operator, audience, public reception, scientific validity, or market value as controlled plants.
- Collapsing privacy, quality, growth, health, and convenience into one scalar objective.
- Calling logs observability when they lack units, TTL, readback refs, and action refs.
- Calling a prompt, schema, or review rubric a control law without a sensor-actuator loop.
- Using VSM, autopoiesis, active inference, allostasis, or cybernetics as personhood frames.
- Letting engagement, publication, refusal, citation, or novelty metrics validate the truth or quality of the claims that produced them.

## Immediate Implementation Consequences

1. Prepared artifacts must include loop cards in the source/action/readback contract. These cards are `feedforward_plan` by default.
2. Runtime loop claims must require sensor, actuator, timing, latency, readback, and fallback fields.
3. Validators remain supervisors. They accept, reject, narrow, quarantine, or request recruitment; they should not silently rewrite narration or command runtime actions.
4. Selected-release review remains separate from eligibility. `manifest.json` is a candidate floor; `selected-release-manifest.json` is the runtime pool boundary.
5. Interview artifacts remain blocked from public release unless topic consent, answer authority, release scope, turn receipts, and layout readback receipts exist.
6. Documentation using "control loop", "cybernetic", "allostatic", or "active inference" should either carry a loop card, cite an existing loop card, or explicitly mark the phrase as analogy/historical context.
7. The prediction ledger must record expected effects, confidence, observation windows, and result updates for each control-theory-derived change.

## Implemented Runtime Corrections

As of 2026-05-06T19:05:39-05:00:

- Layout validation no longer performs an LLM `layout_repair` rewrite. Layout/actionability failures quarantine the candidate and force a new prep iteration rather than laundering a validator-authored artifact into loadability.
- One-segment review rejects artifacts whose LLM provenance contains validator rewrite or repair phases such as `layout_repair`, `validator_rewrite`, or `actionability_repair`.
- `ProgrammeManager` now owns an `AbortEvaluator` supervisory gate. Abort predicates open a pending abort with the five-second veto window; the programme transitions to `ABORTED` only after the pending abort commits against the same active programme id.
- The daimonion impingement loop routes programme-control impingements into `ProgrammeManager.handle_impingement`, allowing `programme.abort.veto` to cancel a pending abort.
- Operator, planned, and time-cap transitions clear pending abort state so a stale abort decision cannot apply to the next programme.
- The programme loop supplies a best-effort perception snapshot for abort predicates. Missing inputs remain non-firing; this is conservative, not evidence of normal state. Predicate-by-predicate missing-data behavior is documented in `docs/superpowers/specs/2026-05-06-programme-abort-supervisory-gate.md`.
- `scripts/review_segment_candidate_set.py` publishes selected-release feedback immediately after writing a valid `selected-release-manifest.json`: selected artifacts are upserted to retrievable Qdrant points through the same selected loader gate, and a compact prior-only digest is written to `~/documents/rag-sources/segment-prep/`.
- Selected-release feedback publication failures are diagnostics on future-prep memory surfaces, not release-boundary failures. The selected manifest plus selected loader gate remain the runtime pool boundary.
- RAG ingest now recognizes `rag-sources/segment-prep` as `source_service: segment-prep`.
- Candidate-set review now ranks all eligible candidates first and requires receipts for the top-N release window. Below-cutoff gaps remain diagnostic; a higher-ranked unreviewed candidate blocks release.

## Runtime Follow-Up Targets

These follow from the team mapping. Completed items stay listed so later sessions can verify they remain true:

- Completed: wire `AbortEvaluator` into production programme runtime and feed a conservative perception snapshot.
- Completed: align predicate callable type annotations with the actual two-argument runtime call.
- Completed: add a post-review path that upserts selected artifacts to Qdrant after `selected-release-manifest.json` is written.
- Completed: write a selected-release feedback digest to RAG sources so future prep can consult selected/canary precedent.
- Completed: make selected-release Qdrant points retrievable by the affordance pipeline while preserving prior-only authority metadata.
- Completed: keep selected-release feedback publication failures diagnostic rather than revoking a valid selected manifest.
- Completed: split candidate-review requirements between top-N eligible artifacts and below-cutoff eligible artifacts so all-candidate review is not required but higher-ranked unreviewed artifacts cannot be skipped.
- Completed: make abort-predicate missing-data behavior externally documented per predicate, especially consent and operator-presence gates.
- Completed: bind pending abort decisions to programme identity and clear stale pending aborts across operator/planned/time-cap transitions.
- Promote the prep-layout to compositor-layout vocabulary shim into a shared enum/contract test.
- Mark legacy layout actuators as outside segment authority unless they route through responsible layout receipts.
- Feed layout receipts, programme outcomes, refusal reasons, and canary critique back into prep selection and planner priors.

## Source Basis

Team research converged on these frameworks as useful:

- contract / assume-guarantee design;
- observability and controllability;
- Ashby requisite variety and good regulator theorem;
- runtime assurance / Simplex;
- MAPE-K;
- model predictive / receding-horizon planning;
- hierarchical and multi-rate control;
- resilience engineering;
- contextual-bandit/adaptive-control patterns for recruitment;
- blackboard-style shared problem state where an explicit control component schedules work.

Each framework is a tool for bounded operational mapping. None is allowed to authorize anthropomorphic personage, consciousness claims, market claims, or public-release truth claims.
