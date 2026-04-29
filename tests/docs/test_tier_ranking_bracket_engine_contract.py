"""Regression pins for the tier/ranking/bracket engine contract."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = (
    REPO_ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-04-29-tier-ranking-bracket-engine-design.md"
)
SCHEMA = REPO_ROOT / "schemas" / "tier-ranking-bracket-engine.schema.json"

REQUIRED_OBJECTS = {
    "candidate_set",
    "comparisons",
    "ranks",
    "tiers",
    "tie_breaks",
    "reversals",
    "inconsistencies",
    "evaluator_refs",
    "run_store_refs",
}
BOUNDARY_SURFACES = {"chapter", "shorts", "replay_card", "dataset", "zine"}


def _body() -> str:
    return SPEC.read_text(encoding="utf-8")


def _schema() -> dict[str, object]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def test_spec_covers_required_contract_sections() -> None:
    body = _body()

    for heading in (
        "## Decision Object Model",
        "## Evidence WCS And No Verdict Policy",
        "## Pairwise Comparisons",
        "## Ranking Tiers And Tie Breaks",
        "## Brackets",
        "## Reversals And Inconsistency Tracking",
        "## Grounding Evaluator And Run Store Integration",
        "## Deterministic Boundaries",
        "## Private Dry Run And Blocked Public Modes",
    ):
        assert heading in body


def test_schema_top_level_fields_cover_decision_object_model() -> None:
    schema = _schema()
    required = set(schema["required"])
    properties = schema["properties"]

    for field in REQUIRED_OBJECTS | {
        "decision_id",
        "run_id",
        "programme_id",
        "format_id",
        "evidence_refs",
        "evidence_envelope_refs",
        "wcs_refs",
        "uncertainty_ref",
        "public_private_mode",
        "output_eligibility",
        "public_claim_allowed",
        "no_expert_verdict_policy",
    }:
        assert field in required
        assert field in properties


def test_candidate_set_criteria_and_pairwise_comparisons_preserve_evidence_refs() -> None:
    schema = _schema()
    candidate_set = schema["$defs"]["candidate_set"]["properties"]
    criterion = schema["$defs"]["criterion"]["properties"]
    comparison = schema["$defs"]["pairwise_comparison"]["properties"]
    nonempty_refs = schema["$defs"]["nonempty_ref_list"]

    assert candidate_set["candidates"]["minItems"] == 2
    assert candidate_set["criteria"]["minItems"] == 1
    assert nonempty_refs["minItems"] == 1
    assert criterion["evidence_refs"]["$ref"] == "#/$defs/nonempty_ref_list"
    assert criterion["wcs_refs"]["$ref"] == "#/$defs/nonempty_ref_list"
    assert comparison["evidence_refs"]["$ref"] == "#/$defs/nonempty_ref_list"
    assert comparison["evidence_envelope_refs"]["$ref"] == "#/$defs/nonempty_ref_list"
    assert comparison["wcs_refs"]["$ref"] == "#/$defs/nonempty_ref_list"
    assert comparison["criteria_bounded"]["const"] is True
    assert comparison["expert_verdict_allowed"]["const"] is False

    body = _body()
    for phrase in (
        "Pairwise comparisons are the atomic evidence units",
        "Missing evidence is not a neutral loss",
        "A comparison with missing evidence cannot feed public claim promotion",
    ):
        assert phrase in body


def test_ranks_tiers_tie_breaks_and_brackets_are_explicit_records() -> None:
    schema = _schema()
    rank = schema["$defs"]["rank_record"]["properties"]
    tier = schema["$defs"]["tier_record"]["properties"]
    tie_break_methods = set(schema["$defs"]["tie_break_method"]["enum"])
    bracket = schema["$defs"]["bracket_record"]["properties"]

    assert rank["comparison_refs"]["$ref"] == "#/$defs/nonempty_ref_list"
    assert rank["criterion_ids"]["$ref"] == "#/$defs/nonempty_ref_list"
    assert rank["criteria_bounded"]["const"] is True
    assert rank["expert_verdict_allowed"]["const"] is False
    assert tier["rank_refs"]["$ref"] == "#/$defs/nonempty_ref_list"
    assert tie_break_methods == {
        "criterion_priority",
        "evidence_freshness",
        "uncertainty_lower_bound",
        "stable_id_order",
        "refusal_boundary",
        "no_tiebreak",
    }
    assert bracket["rounds"]["minItems"] == 1
    assert bracket["matches"]["minItems"] == 1

    body = _body()
    for phrase in (
        "Ranks are evidence-labelled positions",
        "Tie-break records are explicit",
        "Brackets reuse pairwise comparisons",
    ):
        assert phrase in body


def test_reversals_inconsistencies_and_public_claim_blocks_are_pinned() -> None:
    schema = _schema()
    reversal = schema["$defs"]["reversal_record"]["properties"]
    inconsistency_kinds = set(schema["$defs"]["inconsistency_kind"]["enum"])
    resolution_states = set(schema["$defs"]["inconsistency_resolution_state"]["enum"])

    assert reversal["boundary_required"]["const"] is True
    assert reversal["public_correction_required"]["const"] is True
    assert reversal["expert_verdict_allowed"]["const"] is False
    assert inconsistency_kinds == {
        "cycle",
        "criterion_conflict",
        "evidence_conflict",
        "tie_break_conflict",
        "reversal_required",
        "missing_evidence",
    }
    assert resolution_states == {
        "open",
        "refused",
        "resolved_by_tiebreak",
        "resolved_by_reversal",
    }

    body = _body()
    assert "Public claims are blocked while open inconsistencies remain" in body
    assert "Reversals require a boundary and a public correction" in body


def test_no_expert_policy_and_evaluator_integration_are_machine_readable() -> None:
    schema = _schema()
    policy = schema["$defs"]["no_expert_verdict_policy"]["properties"]
    evaluator = schema["x-grounding_evaluator_integration"]

    assert policy["criteria_bounded_outputs_only"]["const"] is True
    assert policy["evidence_label_required"]["const"] is True
    assert policy["authoritative_verdict_allowed"]["const"] is False
    assert policy["domain_truth_adjudication_allowed"]["const"] is False
    assert policy["engagement_metric_source_allowed"]["const"] is False
    assert evaluator["score_as_attempt_quality_only"] is True
    assert evaluator["expert_verdict_allowed"] is False
    assert evaluator["engagement_metric_source_allowed"] is False

    body = _body()
    for phrase in (
        "It does not certify domain truth",
        "It may not act as a hidden expert system",
        "attempt quality evidence",
    ):
        assert phrase in body


def test_boundaries_and_run_store_projection_cover_downstream_surfaces() -> None:
    schema = _schema()

    assert set(schema["x-boundary_surfaces"]) == BOUNDARY_SURFACES
    assert set(schema["$defs"]["boundary_surface"]["enum"]) == BOUNDARY_SURFACES
    assert schema["x-run_store_event_projection"] == [
        "evidence_attached",
        "boundary_emitted",
        "claim_recorded",
        "correction_made",
        "conversion_held",
        "completed",
        "blocked",
    ]

    body = _body()
    for phrase in (
        "`ContentProgrammeRunEnvelope` -> `ProgrammeBoundaryEvent` ->",
        "Direct publication from a ranking decision is not allowed",
        "chapters, Shorts, replay cards, datasets, and zines",
    ):
        assert phrase in body


def test_example_decision_is_parseable_conservative_and_dry_run_safe() -> None:
    body = _body()
    schema = _schema()
    match = re.search(r"```json\n(?P<payload>.*?)\n```", body, re.DOTALL)
    assert match, "example TierRankingBracketDecision JSON block missing"

    decision = json.loads(match.group("payload"))

    assert decision["schema_version"] == 1
    assert decision["format_id"] in schema["$defs"]["ranking_format"]["enum"]
    assert decision["public_private_mode"] == "dry_run"
    assert decision["output_eligibility"] == "dry_run"
    assert decision["public_claim_allowed"] is False
    assert decision["comparisons"][0]["criteria_bounded"] is True
    assert decision["comparisons"][0]["expert_verdict_allowed"] is False
    assert decision["ranks"][0]["evidence_envelope_refs"]
    assert decision["no_expert_verdict_policy"]["authoritative_verdict_allowed"] is False
