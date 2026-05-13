---
type: research-note
title: "Carrier Dynamics Formalization Track"
date: 2026-05-12
status: support_non_authoritative
authority_level: support_non_authoritative
quality_floor: frontier_review_required
parent_request: REQ-20260512-epistemic-audit-realignment
parent_task: epistemic-carrier-dynamics-formalization-track
implementation_refs:
  - packages/agentgov/src/agentgov/carrier.py
  - shared/governance/carrier.py
  - agents/contradiction_detector.py
review_requirement:
  support_artifact_allowed: true
  independent_review_required: true
  authoritative_acceptor_profile: frontier
---

# Carrier Dynamics Formalization Track

This note promotes Carrier Dynamics as a formal research track without treating
the current implementation as a proof. It is a support artifact for independent
frontier review, not an authoritative paper draft.

## Formal Objects

A carrier fact is a bounded, consent-labeled observation:

```text
c = (value, source_domain, consent_label, provenance, observation_count, first_seen, last_seen)
```

The current primitive is `CarrierFact` in `packages/agentgov/src/agentgov/carrier.py`.
The registry state for principal `i` is:

```text
S_i = {c_1 ... c_k}, where |S_i| <= capacity_i
```

A variable node is an agent or principal with local domain state `K_i` plus
carrier slots `S_i`. A check node is a contact, rule, or detector that evaluates
one or more carrier facts against local state:

```text
check_j(K_i, c_1 ... c_n) -> consistent | contradiction | unknown
```

A contradiction is not "two strings differ." It is a typed check failure where
the receiving domain has standing to evaluate the carried fact and can produce a
specific inconsistent pair:

```text
(source_domain, carried_value) contradicts (local_domain, local_assertion)
```

The current concrete check surface is `epistemic_contradiction_veto()` and the
rule-based examples in `agents/contradiction_detector.py`.

## Correction And Displacement

Correction behavior is deliberately conservative:

- A contradiction opens an evidence issue or routes to an authoritative domain.
- Carrier Dynamics does not rewrite the source record automatically.
- Consent revocation purges facts by provenance before further use.
- Facts carry observations, not interpretations.

Displacement behavior is already prototyped in `CarrierRegistry.offer()`:

- duplicate fact: update observation count;
- open slot: insert;
- full slot: displace the least-observed fact only when the new fact exceeds the
  configured frequency threshold;
- otherwise reject.

This is a research heuristic, not yet an optimal policy. The prototype should log
all four outcomes so later evaluation can compare frequency-threshold
displacement against FIFO, random replacement, recency, and diversity-preserving
policies.

## Minimal Prototype

The smallest prototype should stay on existing `agentgov` primitives:

1. Use `CarrierRegistry` for bounded slots and displacement.
2. Use `CarrierFact.labeled` for DLM/LIO consent labels and provenance.
3. Use `RevocationPropagator.register_carrier_registry()` for purge checks.
4. Feed synthetic or recorded facts through `epistemic_contradiction_veto()`.
5. Emit an event log: offer outcome, displaced fact, check outcome, detection
   latency, provenance, and consent label.

No new ontology is needed for phase 0. A small harness can treat each synthetic
domain as a variable node and each detector as a check node, then measure whether
bounded carrier slots reveal injected cross-domain contradictions.

## Claim Boundaries

### Factor Graphs

Factor graph language is valid as a structural model: agents are variable nodes,
detectors or contact points are check nodes, and carrier offers are messages.
The canonical reference is Kschischang, Frey, and Loeliger's factor graph and
sum-product account in IEEE Transactions on Information Theory
([DOI 10.1109/18.910572](https://doi.org/10.1109/18.910572);
[PDF mirror](https://web.stanford.edu/~montanar/TEACHING/Stat375/papers/sumprod.pdf)).

Current claim limit: Hapax has a sparse bipartite consistency-checking design.
It does not yet implement sum-product inference, belief propagation, or a
probabilistic graphical model with calibrated marginals.

### LDPC Codes

LDPC language is valid only for sparse-check inspiration. Gallager's LDPC codes
are defined over parity-check matrices and channel/noise assumptions
([1962 article metadata](https://jglobal.jst.go.jp/en/detail?JGLOBAL_ID=201602016942732431);
[Gallager PDF](https://web.mit.edu/gallager/www/pages/ldpc.pdf)).

Current claim limit: Carrier Dynamics borrows the idea that sparse checks can
detect distributed errors. It must not claim near-Shannon-limit, near-optimal, or
LDPC-equivalent behavior until the work defines a code, channel, noise model,
decoder, and proof or simulation.

### Mirroring Hypothesis And Conway's Law

Conway's law motivates the epistemic problem: communication structure shapes
system structure. The mirroring hypothesis literature refines this into a claim
that organizational ties tend to correspond to technical dependencies; Colfer
and Baldwin also emphasize exceptions and ways to "break the mirror"
([Harvard record](https://dash.harvard.edu/entities/publication/73120379-10f0-6bd4-e053-0100007fdf3b);
[PDF](https://www.hbs.edu/ris/Publication%20Files/Colfer%20Baldwin%20Mirroring%20Hypothesis%20Ind%20Corp%20Change-2016_8aa320ff-6aa6-42ef-b259-d139012faaf6.pdf)).

Current claim limit: Carrier Dynamics is a candidate mechanism for deliberately
adding sparse cross-boundary epistemic ties. It is not evidence that Conway's law
is false, and it is not proof that all mirrored organizations can be repaired by
carrier slots.

### Agent Trace, Provenance, And Process-Mining Work

Existing work already analyzes agent traces and workflows. Relevant prior art
includes TRAIL for trace reasoning and issue localization
([arXiv:2505.08638](https://arxiv.org/abs/2505.08638)), COMPASS for applying
process mining to LLM-agent behavior
([CEUR PDF](https://ceur-ws.org/Vol-3996/paper-5.pdf)), and PROV-AGENT for
agent-workflow provenance
([arXiv:2508.02866](https://arxiv.org/abs/2508.02866)).

Current claim limit: Carrier Dynamics is not novel because it traces agents.
The candidate novelty is the consent-labeled, bounded, cross-domain fact-carrying
mechanism that turns selected trace or filesystem facts into sparse consistency
checks.

## Falsifiers

Carrier Dynamics should be demoted or abandoned if:

- bounded carrier slots do not improve contradiction detection over no-carrier
  and random-gossip baselines;
- useful detection requires near-full broadcast or high-capacity slots;
- false positives dominate true contradictions under realistic domain checks;
- displacement policy erases rare but important facts before contact;
- carrier propagation homogenizes domain state rather than preserving local
  expertise;
- consent labels or provenance are lost during carrying, checking, or purge;
- measured detection latency is worse than simpler centralized audit jobs.

## Measurable Outcomes

Phase-0 evaluation should report:

- contradiction detection rate at capacity `k in {0, 1, 3, 5, 10}`;
- false-positive and false-negative rate by detector type;
- time-to-detection measured in contacts or events;
- marginal detection gain per added carrier slot;
- displacement regret against FIFO, random, recency, and diversity baselines;
- homogenization index: overlap of carried fact sets across domains;
- consent purge latency and residual facts after revocation;
- operator review load per true contradiction found.

## Separation From Token Capital

Carrier Dynamics is an epistemic consistency mechanism. It says nothing about
economic value, token reuse, depreciation curves, Shapley values, or marginal
contribution of generated text. Token Capital remains a separate hypothesis
program until the RAG and measurement repairs define its game, utility function,
and evidence pipeline.

Safe phrasing:

> Carrier Dynamics is a bounded cross-domain contradiction-detection mechanism
> over consent-labeled carrier facts.

Unsafe phrasing:

> Carrier Dynamics proves Token Capital or shows near-optimal error correction.
