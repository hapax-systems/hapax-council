"""Regression pins for the content programme run store/event surface contract."""

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
    / "2026-04-29-content-programme-run-store-event-surface-design.md"
)
SCHEMA = REPO_ROOT / "schemas" / "content-programme-run-store-event-surface.schema.json"

REQUIRED_EVENT_TYPES = {
    "selected",
    "started",
    "transitioned",
    "blocked",
    "evidence_attached",
    "gate_evaluated",
    "boundary_emitted",
    "claim_recorded",
    "outcome_recorded",
    "refusal_issued",
    "correction_made",
    "artifact_candidate",
    "conversion_held",
    "public_event_linked",
    "completed",
    "aborted",
}
FIXTURE_CASES = {
    "private_run",
    "dry_run",
    "public_archive_run",
    "public_live_blocked_run",
    "monetization_blocked_run",
    "refusal_run",
    "correction_run",
    "conversion_held_run",
    "dry_run_tier_list",
    "public_safe_evidence_audit",
    "rights_blocked_react_commentary",
    "world_surface_blocked_run",
}


def _body() -> str:
    return SPEC.read_text(encoding="utf-8")


def _schema() -> dict[str, object]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def test_spec_covers_required_contract_sections() -> None:
    body = _body()

    for heading in (
        "## Run Envelope",
        "## Append-Only Run Store Event",
        "## Opportunity And Format Refs",
        "## WCS Binding",
        "## Boundary Event Refs",
        "## Execution Versus Witnessed Outcomes",
        "## Public Conversion Path",
        "## Rights Privacy Public Modes",
        "## Evaluator Scores And Engagement Separation",
        "## Fixture Catalog",
        "## Adapter Exposure",
        "## Operator Doctrine",
    ):
        assert heading in body


def test_schema_top_level_fields_match_run_envelope_contract() -> None:
    schema = _schema()
    required = set(schema["required"])
    properties = schema["properties"]

    for field in (
        "run_id",
        "programme_id",
        "opportunity_decision_id",
        "format_id",
        "broadcast_refs",
        "archive_refs",
        "condition_id",
        "selected_input_refs",
        "substrate_refs",
        "semantic_capability_refs",
        "director_plan",
        "rights_privacy_public_mode",
        "gate_refs",
        "events",
        "claims",
        "uncertainties",
        "refusals",
        "corrections",
        "scores",
        "conversion_candidates",
        "final_status",
    ):
        assert field in required
        assert field in properties


def test_run_store_event_stream_is_append_only_and_names_all_event_types() -> None:
    schema = _schema()
    event_def = schema["$defs"]["content_programme_run_store_event"]

    assert set(schema["$defs"]["run_store_event_type"]["enum"]) == REQUIRED_EVENT_TYPES
    assert event_def["properties"]["append_only"]["const"] is True
    assert (
        event_def["properties"]["mutation_policy"]["const"]
        == "append_new_event_never_update_existing"
    )
    assert "ContentProgrammeRunStoreEvent" in _body()


def test_public_private_modes_and_selected_refs_are_pinned() -> None:
    schema = _schema()

    assert set(schema["$defs"]["public_private_mode"]["enum"]) == {
        "private",
        "dry_run",
        "public_live",
        "public_archive",
        "public_monetizable",
    }
    selected_opportunity = schema["$defs"]["selected_opportunity_ref"]["properties"]
    assert selected_opportunity["rescore_hidden_copy_allowed"]["const"] is False

    body = _body()
    for phrase in (
        "`selected_opportunity.decision_id`",
        "`selected_opportunity.rescore_hidden_copy_allowed = false`",
        "`selected_format.registry_ref`",
        "must not silently re-score a hidden copy",
    ):
        assert phrase in body


def test_wcs_binding_has_required_surface_evidence_and_health_fields() -> None:
    schema = _schema()
    required = set(schema["$defs"]["wcs_binding"]["required"])

    assert required == {
        "semantic_substrate_refs",
        "grounding_contract_refs",
        "evidence_envelope_refs",
        "witness_requirements",
        "capability_outcome_refs",
        "health_state",
        "unavailable_reasons",
        "public_private_posture",
    }

    reasons = set(schema["$defs"]["unavailable_reason"]["enum"])
    for reason in (
        "missing_evidence_ref",
        "research_vehicle_public_event_missing",
        "third_party_media_blocked",
        "owned_cleared_av_missing",
        "monetization_readiness_missing",
        "world_surface_blocked",
        "witness_missing",
    ):
        assert reason in reasons


def test_boundary_events_are_refs_without_duplicated_semantics() -> None:
    schema = _schema()
    boundary_props = schema["$defs"]["programme_boundary_event_ref"]["properties"]

    for field in (
        "boundary_id",
        "sequence",
        "duplicate_key",
        "cuepoint_chapter_distinction",
        "public_event_mapping_ref",
        "mapping_state",
        "unavailable_reasons",
    ):
        assert field in boundary_props

    for duplicated_boundary_payload in (
        "summary",
        "evidence_refs",
        "no_expert_system_gate",
        "claim_shape",
        "public_event_mapping",
        "cuepoint_chapter_policy",
    ):
        assert duplicated_boundary_payload not in boundary_props

    body = _body()
    assert "The envelope does not duplicate boundary summaries" in body
    assert "cuepoint/chapter distinction" in body


def test_command_execution_and_witnessed_outcomes_are_separate() -> None:
    schema = _schema()
    command = schema["$defs"]["command_execution_record"]["properties"]
    trace = schema["$defs"]["command_execution_trace"]["properties"]
    separation = schema["$defs"]["separation_policy"]["properties"]

    assert command["posterior_update_allowed"]["const"] is False
    assert "commanded_states" in trace
    assert "executed_states" in trace
    assert "witnessed_outcomes" in trace
    assert separation["selected_commanded_executed_are_not_witnessed"]["const"] is True
    assert separation["witnessed_outcomes_only_update_posteriors"]["const"] is True

    body = _body()
    assert "Selected, commanded, and executed records always have" in body
    assert "Only witnessed outcomes with `witness_state = witness_verified`" in body


def test_conversion_and_separation_policies_fail_closed() -> None:
    schema = _schema()
    conversion = schema["$defs"]["conversion_candidate"]["properties"]
    separation = schema["$defs"]["separation_policy"]["properties"]

    assert "research_vehicle_public_event_ref" in conversion
    assert "owned_cleared_av_ref" in conversion
    assert "monetization_readiness_ref" in conversion
    assert schema["x-public_conversion_path"] == [
        "ContentProgrammeRunEnvelope",
        "ProgrammeBoundaryEvent",
        "ResearchVehiclePublicEvent",
        "surface_adapter",
    ]
    assert separation["evaluator_outputs_are_evidence_outcomes"]["const"] is True
    assert separation["engagement_can_override_grounding"]["const"] is False
    assert separation["revenue_can_override_grounding"]["const"] is False
    assert separation["support_data_public_state_aggregate_only"]["const"] is True
    assert separation["public_payer_identity_allowed"]["const"] is False


def test_fixture_catalog_and_single_operator_policy_are_pinned() -> None:
    schema = _schema()
    operator = schema["$defs"]["operator_labor_policy"]["properties"]

    assert set(schema["x-fixture_cases"]) == FIXTURE_CASES
    assert operator["single_operator_only"]["const"] is True
    assert operator["request_queue_allowed"]["const"] is False
    assert operator["manual_content_calendar_allowed"]["const"] is False
    assert operator["supporter_controlled_programming_allowed"]["const"] is False
    assert operator["personalized_supporter_treatment_allowed"]["const"] is False


def test_example_envelope_is_parseable_and_demonstrates_public_safe_archive() -> None:
    body = _body()
    match = re.search(r"```json\n(?P<payload>.*?)\n```", body, re.DOTALL)
    assert match, "example ContentProgrammeRunEnvelope JSON block missing"

    envelope = json.loads(match.group("payload"))

    assert envelope["schema_version"] == 1
    assert envelope["public_private_mode"] == "public_archive"
    assert envelope["selected_opportunity"]["rescore_hidden_copy_allowed"] is False
    assert envelope["boundary_event_refs"][0]["mapping_state"] == "research_vehicle_linked"
    assert envelope["conversion_candidates"][0]["research_vehicle_public_event_ref"]
    assert envelope["command_execution"]["selected"]["posterior_update_allowed"] is False
    assert envelope["witnessed_outcomes"][0]["posterior_update_allowed"] is True
    assert envelope["separation_policy"]["revenue_can_override_grounding"] is False
