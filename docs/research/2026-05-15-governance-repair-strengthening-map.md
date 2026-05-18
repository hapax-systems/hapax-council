# Governance Repair Strengthening Map - 2026-05-15

Source prompt: `/data/downloads/council_synthesis.md`

This note records the post-synthesis repair framing. The aim is to strengthen
the Hapax governance approach where it is sound, not retreat from algebraic
governance, LLM-assisted review, or single-operator design.

## Thesis

The council synthesis is directionally right: Hapax has partially escaped plain
Expert Systems Redux because some authority is compressed into reusable
algebraic primitives (`VetoChain`, labels, provenance, principal attribution,
consent wrappers) rather than only expanding lists of rules.

The repair target is therefore not "delete rules" or "remove LLMs." The repair
target is authority boundary drift:

- the axiom core is comparatively stable;
- the perimeter around it is growing faster than the core;
- some review surfaces give broader assurance than their actual coverage;
- at least one degraded path bypasses the intended gate chain;
- policy text and source registries can disagree while both look locally valid.

The strengthening move is to make every governance surface either algebraic,
coverage-accounted, or explicitly advisory.

## Confirmed Repair Surfaces

### 1. SDLC axiom judge

The LLM judge is useful, but weaker than its surrounding claims. It samples a
subset of implications, truncates diffs, and uses a loader path that can miss
standalone implication files. Repair should add deterministic coverage
accounting, parity tests, semantic golden cases, and fail-closed JSON handling.
The goal is to cage stochastic judgment, not remove it.

### 2. AffordancePipeline gate chain

`shared/affordance_pipeline.py` is a valid unified recruitment surface, but it
mixes retrieval, gate enforcement, scoring, learning, telemetry, and side
effects. The immediate defect is narrower than a full refactor: degraded
embedding fallback can return candidates before the normal consent,
monetization, and content-risk gates run. Repair starts by sharing the gate
chain across normal and fallback paths, then extracting interfaces under tests.

### 3. Patreon/refusal source of truth

The current Patreon implementation appears intentionally receive-only: no SDK,
no outbound calls, no CRM/perks surface, and no PII persistence. The refusal
brief, however, says no Patreon webhook receivers. This is not merely a doc
typo; it is a policy/source-of-truth contradiction. Repair must decide whether
`patreon-receiver` is an allowed receive-only telemetry exception or a literal
refusal violation, then encode that distinction in registries and tests.

### 4. Governance perimeter accretion

The strongest Expert Systems Redux risk is not the current implication count.
It is the pattern where every new surface adds a brief, hook, registry entry,
publisher class, refused publisher, test, dashboard row, and doc. Repair should
introduce a measured perimeter budget and force consolidation/retirement when
new governance artifacts are added.

### 5. agentgov proof and parity

`packages/agentgov` is the core positive result. It should be strengthened as
the portable artifact: package-local property tests for advertised laws,
explicit docs that distinguish algebra from normative rulebase, and parity or
migration for vendored governance copies.

### 6. systemd and agent topology

Raw systemd unit count is a poor proxy for Expert Systems Redux. Most timers
are T3 scheduled work, not IF-THEN rulebase expansion. Still, source docs are
stale and the operational topology is too hard to reason about. Repair should
inventory unit categories separately from governance rules.

## Request Set

The repair program has been split into active request-intake notes:

- `REQ-20260515-governance-repair-strengthening-program`
- `REQ-20260515-axiom-gate-coverage-and-property-hardening`
- `REQ-20260515-affordance-pipeline-gate-chain-hardening`
- `REQ-20260515-payment-rail-refusal-source-of-truth-reconciliation`
- `REQ-20260515-governance-perimeter-budget-and-inventory`
- `REQ-20260515-agentgov-proof-and-vendored-parity-hardening`
- `REQ-20260515-systemd-agent-topology-inventory`

## Non-Retreat Constraints

- Do not remove the LLM judge merely because it is stochastic; bind it with
  deterministic coverage accounting and negative examples.
- Do not split `AffordancePipeline` into cosmetic files before proving degraded
  paths run the same safety gates as normal paths.
- Do not resolve Patreon by silently weakening refusal doctrine; either encode
  the receive-only exception or remove the rail.
- Do not cap implication count mechanically while allowing unchecked expansion
  of hooks, registries, briefs, and publisher variants.
- Do not claim `agentgov` proves the whole Hapax system; make it prove the
  reusable enforcement algebra it actually owns.

## First Repair Order

1. AffordancePipeline degraded-path gate hardening.
2. Patreon/refusal source-of-truth reconciliation.
3. SDLC axiom judge coverage and property hardening.
4. Governance perimeter budget and inventory.
5. agentgov proof/parity hardening.
6. systemd and agent topology inventory.

