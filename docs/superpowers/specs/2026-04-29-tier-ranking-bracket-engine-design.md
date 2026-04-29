# Tier Ranking Bracket Engine - Design Spec

**Status:** schema seed for `tier-ranking-bracket-engine`
**Task:** `/home/hapax/Documents/Personal/20-projects/hapax-cc-tasks/active/tier-ranking-bracket-engine.md`
**Date:** 2026-04-29
**Depends on:** autonomous content programming format registry, format grounding evaluator, and content programme run-store event surface.
**Scope:** object model for candidate sets, criteria, pairwise comparisons, ranks, tiers, tie-breaks, evidence, uncertainty, reversals, inconsistencies, final decisions, deterministic boundaries, and run-store/evaluator refs.
**Non-scope:** scheduler implementation, runner implementation, public adapter writes, YouTube writes, Shorts generation, feedback-ledger persistence, or expert verdict generation.

## Purpose

The tier/ranking/bracket engine structures familiar ranking formats as bounded
grounding attempts.

It answers only this kind of question: given a declared candidate set, criteria,
evidence window, WCS refs, and uncertainty policy, what ordering or bracket
decision can be recorded as attempt evidence? It does not certify domain truth,
decide expertise, or infer public eligibility from a good-looking ordering.

The machine-readable schema lives at:

- `schemas/tier-ranking-bracket-engine.schema.json`

Typed helper models live at:

- `shared/tier_ranking_bracket_engine.py`

## Decision Object Model

`TierRankingBracketDecision` is the canonical final decision projection. It
contains refs to the content programme run store and evaluator outputs without
rewriting those upstream records.

Required object families:

| Object | Meaning |
|---|---|
| `candidate_set` | Bounded candidates, scope limit, criteria, evidence refs, and WCS refs. |
| `criteria` | Weighted criteria with direction, scope limit, evidence refs, and WCS refs. |
| `comparisons` | Pairwise comparison records for left/right/tie/incomparable/refused outcomes. |
| `ranks` | Candidate ranks with criterion ids, comparison refs, evidence, uncertainty, and optional tie-break refs. |
| `tiers` | Named tier buckets that point back to ranks and preserve uncertainty. |
| `tie_breaks` | Explicit tie-break decisions by criterion priority, freshness, uncertainty, stable id, refusal, or no tie-break. |
| `bracket` | Optional bracket rounds and matches for tournament-style pairwise decisions. |
| `reversals` | Corrections to prior comparisons, ranks, tiers, or final decisions. |
| `inconsistencies` | Cycles, criterion conflicts, evidence conflicts, tie-break conflicts, reversals required, and missing evidence. |
| `no_expert_verdict_policy` | Machine-readable policy that all outputs are criteria-bounded and evidence-labelled. |

Every comparison, rank, tie-break, reversal, inconsistency, and final decision
preserves `evidence_refs` and `wcs_refs`. Comparisons, ranks, reversals, and
the final decision also preserve `evidence_envelope_refs` so downstream systems
can feed the format grounding evaluator and run store without inventing public
eligibility.

## Evidence WCS And No Verdict Policy

The engine may structure and score an attempt. It may not act as a hidden expert system.

Required no-verdict constants:

- `criteria_bounded_outputs_only = true`
- `evidence_label_required = true`
- `authoritative_verdict_allowed = false`
- `domain_truth_adjudication_allowed = false`
- `engagement_metric_source_allowed = false`
- `public_claim_requires_effective_public_mode = true`

Public-facing language must be about the declared run: candidate set, criteria,
evidence window, uncertainty, and refusals. It must not claim universal best,
certified truth, expert recommendation, diagnosis, proof, or guarantee.

## Pairwise Comparisons

Pairwise comparisons are the atomic evidence units for rankings and brackets.

Each `PairwiseComparisonRecord` stores:

- `left_candidate_id`
- `right_candidate_id`
- `criterion_ids`
- `outcome`
- `rationale`
- `evidence_refs`
- `evidence_envelope_refs`
- `wcs_refs`
- `uncertainty_ref`
- `state`
- `criteria_bounded = true`
- `expert_verdict_allowed = false`

Missing evidence is not a neutral loss. It is an inconsistency, refusal, or
blocked comparison. A comparison with missing evidence cannot feed public claim
promotion. A comparison with missing evidence cannot feed public claim promotion.

## Ranking Tiers And Tie Breaks

Ranks are evidence-labelled positions inside a declared candidate set. A rank
must point to at least one comparison and at least one criterion. A tier must
point back to ranks, not duplicate hidden ranking semantics.

Tie-break records are explicit. A tie may be resolved only by a named method:

- `criterion_priority`
- `evidence_freshness`
- `uncertainty_lower_bound`
- `stable_id_order`
- `refusal_boundary`
- `no_tiebreak`

Tie-breaks are not authority shortcuts. They are visible decision records with
evidence, WCS refs, uncertainty, and no-expert-verdict policy.

## Brackets

Brackets reuse pairwise comparisons. A bracket match points to a comparison ref
and records round/match indices, outcome, and optional winner. Non-winning
outcomes such as `tie`, `incomparable`, and `refused` cannot set a winner.

Bracket records preserve:

- `bracket_id`
- `candidate_set_id`
- `rounds`
- `matches`
- `champion_candidate_id`
- `evidence_refs`
- `wcs_refs`
- `inconsistency_refs`

A bracket champion is a criteria-bounded result of the declared matches, not a
domain verdict.

## Reversals And Inconsistency Tracking

Reversals and inconsistencies are first-class records. The engine must not hide
or overwrite unstable ranking state.

Initial inconsistency kinds:

- `cycle`
- `criterion_conflict`
- `evidence_conflict`
- `tie_break_conflict`
- `reversal_required`
- `missing_evidence`

Initial resolution states:

- `open`
- `refused`
- `resolved_by_tiebreak`
- `resolved_by_reversal`

Public claims are blocked while open inconsistencies remain. Reversals require
a boundary and a public correction when the earlier decision crossed a public or
archive surface. Reversals require a boundary and a public correction.

## Grounding Evaluator And Run Store Integration

The engine integrates with the format grounding evaluator as attempt quality
evidence. It never emits an expert verdict. It emits attempt quality evidence.

The helper function `can_feed_grounding_evaluator()` returns true only when the
decision is evidence-bound, WCS-bound, no-verdict, and free of unresolved
missing-evidence inconsistencies.

The helper function `build_run_store_events()` projects decisions into
append-only `ContentProgrammeRunStoreEvent` records by reference only. Initial
event projections are:

- `evidence_attached`
- `boundary_emitted`
- `claim_recorded`
- `correction_made`
- `conversion_held`
- `completed`
- `blocked`

The run-store projection does not duplicate claim text, boundary semantics, or
public adapter payloads.

## Deterministic Boundaries

The engine emits deterministic boundaries for the surfaces downstream adapters
expect:

- `chapter`
- `shorts`
- `replay_card`
- `dataset`
- `zine`

Boundary ids, sequence numbers, duplicate keys, cuepoint/chapter distinction,
mapping state, and unavailable reasons are deterministic from the final
decision and supplied public-event mapping refs. The deterministic surface set
is chapters, Shorts, replay cards, datasets, and zines.

Public conversion still follows the established path:

`ContentProgrammeRunEnvelope` -> `ProgrammeBoundaryEvent` ->
`ResearchVehiclePublicEvent` -> surface adapter

Direct publication from a ranking decision is not allowed.

## Private Dry Run And Blocked Public Modes

Tier/ranking/bracket decisions remain useful in private and dry-run modes.

Private and dry-run decisions may preserve candidate sets, criteria,
comparisons, ranks, tiers, reversals, inconsistencies, boundaries, and run-store
events. They may not set `public_claim_allowed = true`.

Blocked public, Shorts, replay, monetization, or rights gates do not erase the
decision. They hold conversion, emit unavailable reasons, and keep all evidence
refs available for later correction, replay cards, datasets, zines, or feedback
ledger consumers.

## Example Decision

```json
{
  "schema_version": 1,
  "decision_id": "trb_20260429t130000z_model_routes_a",
  "run_id": "run_20260429t130000z_model_routes_a",
  "programme_id": "programme_model_route_grounding",
  "format_id": "tier_list",
  "selected_at": "2026-04-29T13:00:00Z",
  "candidate_set": {
    "candidate_set_id": "candidate_set_model_routes_a",
    "title": "Model routes for current grounding tasks",
    "scope_limit": "Only routes named in the 2026-04-29 grounding scout evidence window.",
    "candidates": [
      {
        "candidate_id": "route_command_r",
        "label": "Command-R local route",
        "source_refs": ["source:model-routing-scout"],
        "evidence_refs": ["evidence:command-r-route"],
        "evidence_envelope_refs": ["ee:command-r-route"],
        "wcs_refs": ["wcs:command-r-route"],
        "rights_refs": ["rights:operator-owned-config"]
      },
      {
        "candidate_id": "route_gemini",
        "label": "Gemini sidecar route",
        "source_refs": ["source:gemini-sidecar-policy"],
        "evidence_refs": ["evidence:gemini-sidecar"],
        "evidence_envelope_refs": ["ee:gemini-sidecar"],
        "wcs_refs": ["wcs:gemini-sidecar"],
        "rights_refs": ["rights:official-docs-ref"]
      }
    ],
    "criteria": [
      {
        "criterion_id": "criterion_supplied_evidence",
        "label": "Supplied evidence fit",
        "description": "How well the route supports supplied evidence without claiming direct world access.",
        "direction": "higher_better",
        "weight": 0.7,
        "scope_limit": "Current route evidence only.",
        "evidence_refs": ["evidence:route-policy"],
        "wcs_refs": ["wcs:route-policy"]
      }
    ],
    "evidence_refs": ["evidence:route-policy"],
    "wcs_refs": ["wcs:route-policy"]
  },
  "comparisons": [
    {
      "comparison_id": "comparison_command_r_vs_gemini",
      "left_candidate_id": "route_command_r",
      "right_candidate_id": "route_gemini",
      "criterion_ids": ["criterion_supplied_evidence"],
      "outcome": "tie",
      "rationale": "Both routes require supplied evidence constraints under this criterion.",
      "evidence_refs": ["evidence:route-policy"],
      "evidence_envelope_refs": ["ee:route-policy"],
      "wcs_refs": ["wcs:route-policy"],
      "uncertainty_ref": "uncertainty:route-policy",
      "state": "accepted",
      "criteria_bounded": true,
      "expert_verdict_allowed": false
    }
  ],
  "ranks": [
    {
      "rank_id": "rank_route_command_r",
      "candidate_id": "route_command_r",
      "ordinal": 1,
      "tier_id": "tier_a",
      "comparison_refs": ["comparison_command_r_vs_gemini"],
      "criterion_ids": ["criterion_supplied_evidence"],
      "evidence_refs": ["evidence:command-r-route"],
      "evidence_envelope_refs": ["ee:command-r-route"],
      "wcs_refs": ["wcs:command-r-route"],
      "uncertainty_ref": "uncertainty:route-policy",
      "tie_break_ref": "tie_policy_no_break",
      "score": 0.74,
      "scope_limit": "Current route evidence only.",
      "public_claim_allowed": false,
      "criteria_bounded": true,
      "expert_verdict_allowed": false
    },
    {
      "rank_id": "rank_route_gemini",
      "candidate_id": "route_gemini",
      "ordinal": 1,
      "tier_id": "tier_a",
      "comparison_refs": ["comparison_command_r_vs_gemini"],
      "criterion_ids": ["criterion_supplied_evidence"],
      "evidence_refs": ["evidence:gemini-sidecar"],
      "evidence_envelope_refs": ["ee:gemini-sidecar"],
      "wcs_refs": ["wcs:gemini-sidecar"],
      "uncertainty_ref": "uncertainty:route-policy",
      "tie_break_ref": "tie_policy_no_break",
      "score": 0.74,
      "scope_limit": "Current route evidence only.",
      "public_claim_allowed": false,
      "criteria_bounded": true,
      "expert_verdict_allowed": false
    }
  ],
  "tiers": [
    {
      "tier_id": "tier_a",
      "label": "A: usable under supplied evidence constraints",
      "ordinal": 1,
      "rank_refs": ["rank_route_command_r", "rank_route_gemini"],
      "criteria_summary": "Both candidates satisfy supplied-evidence fit for the declared scope.",
      "evidence_refs": ["evidence:route-policy"],
      "wcs_refs": ["wcs:route-policy"],
      "uncertainty_ref": "uncertainty:route-policy"
    }
  ],
  "tie_breaks": [
    {
      "tie_break_id": "tie_policy_no_break",
      "applies_to_rank_ids": ["rank_route_command_r", "rank_route_gemini"],
      "method": "no_tiebreak",
      "criterion_priority": [],
      "rationale": "The declared evidence does not support breaking this tie.",
      "evidence_refs": [],
      "evidence_envelope_refs": [],
      "wcs_refs": [],
      "uncertainty_ref": "uncertainty:route-policy",
      "state": "accepted",
      "expert_verdict_allowed": false
    }
  ],
  "bracket": null,
  "reversals": [],
  "inconsistencies": [],
  "evaluator_refs": ["format-grounding-evaluation:fge_20260429t130000z_route_tier"],
  "run_store_refs": ["run-store:run_20260429t130000z_model_routes_a"],
  "evidence_refs": ["evidence:route-policy"],
  "evidence_envelope_refs": ["ee:route-policy"],
  "wcs_refs": ["wcs:route-policy"],
  "uncertainty_ref": "uncertainty:route-policy",
  "requested_public_private_mode": "dry_run",
  "public_private_mode": "dry_run",
  "output_eligibility": "dry_run",
  "public_claim_allowed": false,
  "no_expert_verdict_policy": {
    "criteria_bounded_outputs_only": true,
    "evidence_label_required": true,
    "authoritative_verdict_allowed": false,
    "domain_truth_adjudication_allowed": false,
    "engagement_metric_source_allowed": false,
    "public_claim_requires_effective_public_mode": true
  }
}
```

## Test Contract

Regression tests pin that:

- schema fields cover all object families in this spec,
- pairwise comparisons, ranks, reversals, and final decisions require evidence,
  evidence envelopes, and WCS refs,
- public claims are blocked in private or dry-run mode,
- open inconsistencies block public claims,
- deterministic boundaries cover chapters, Shorts, replay cards, datasets, and
  zines,
- run-store events are append-only refs,
- evaluator integration is attempt-quality only, never expert verdict output.
