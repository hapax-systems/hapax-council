"""Regression pins for the programme boundary event surface contract."""

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
    / "2026-04-29-programme-boundary-event-surface-design.md"
)
SCHEMA = REPO_ROOT / "schemas" / "programme-boundary-event-surface.schema.json"
PUBLIC_EVENT_SCHEMA = REPO_ROOT / "schemas" / "research-vehicle-public-event.schema.json"


def _body() -> str:
    return SPEC.read_text(encoding="utf-8")


def _schema() -> dict[str, object]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def _public_event_schema() -> dict[str, object]:
    return json.loads(PUBLIC_EVENT_SCHEMA.read_text(encoding="utf-8"))


def test_spec_covers_required_contract_sections() -> None:
    body = _body()

    for heading in (
        "## Boundary Event Types",
        "## `ProgrammeBoundaryEvent` Schema Seed",
        "## ResearchVehiclePublicEvent Mapping",
        "## Public/Private And Gate Propagation",
        "## Cuepoint And Chapter Policy",
        "## Dry-Run And Unavailable Reasons",
    ):
        assert heading in body


def test_schema_has_required_boundary_fields() -> None:
    schema = _schema()
    required = set(schema["required"])
    properties = schema["properties"]

    for field in (
        "boundary_id",
        "emitted_at",
        "programme_id",
        "run_id",
        "format_id",
        "sequence",
        "boundary_type",
        "public_private_mode",
        "grounding_question",
        "summary",
        "evidence_refs",
        "no_expert_system_gate",
        "claim_shape",
        "public_event_mapping",
        "cuepoint_chapter_policy",
        "dry_run_unavailable_reasons",
        "duplicate_key",
    ):
        assert field in required
        assert field in properties


def test_schema_names_all_required_boundary_types() -> None:
    schema = _schema()
    boundary_types = set(schema["$defs"]["boundary_type"]["enum"])

    assert boundary_types >= {
        "programme.started",
        "criterion.declared",
        "evidence.observed",
        "claim.made",
        "rank.assigned",
        "comparison.resolved",
        "uncertainty.marked",
        "refusal.issued",
        "correction.made",
        "clip.candidate",
        "live_cuepoint.candidate",
        "chapter.boundary",
        "artifact.candidate",
    }

    body = _body()
    for boundary_type in boundary_types:
        assert f"`{boundary_type}`" in body


def test_public_event_mapping_stays_inside_research_vehicle_event_vocabulary() -> None:
    schema = _schema()
    public_schema = _public_event_schema()

    mapped_events = {
        value
        for value in schema["properties"]["public_event_mapping"]["properties"][
            "research_vehicle_event_type"
        ]["enum"]
        if value is not None
    }
    public_events = set(public_schema["properties"]["event_type"]["enum"])

    assert mapped_events <= public_events

    mapped_state_kinds = {
        value
        for value in schema["properties"]["public_event_mapping"]["properties"]["state_kind"][
            "enum"
        ]
        if value is not None
    }
    public_state_kinds = set(public_schema["properties"]["state_kind"]["enum"])

    assert mapped_state_kinds <= public_state_kinds


def test_gate_result_and_public_private_mode_are_preserved_on_every_boundary() -> None:
    schema = _schema()
    gate_required = set(schema["properties"]["no_expert_system_gate"]["required"])

    for field in (
        "gate_ref",
        "gate_state",
        "claim_allowed",
        "public_claim_allowed",
        "infractions",
    ):
        assert field in gate_required

    assert set(schema["$defs"]["public_private_mode"]["enum"]) == {
        "private",
        "dry_run",
        "public_live",
        "public_archive",
        "public_monetizable",
    }

    body = _body()
    for phrase in (
        "`public_private_mode`",
        "`no_expert_system_gate.gate_ref`",
        "`no_expert_system_gate.gate_state`",
        "`no_expert_system_gate.public_claim_allowed`",
        "Adapters must consume these values directly",
    ):
        assert phrase in body


def test_cuepoint_and_chapter_policy_keeps_live_ads_distinct_from_vod_chapters() -> None:
    schema = _schema()
    cue_policy = schema["properties"]["cuepoint_chapter_policy"]["properties"]

    assert cue_policy["live_cuepoint_distinct_from_vod_chapter"]["const"] is True

    body = _body()
    for phrase in (
        "Live ad cuepoints and VOD chapters are distinct",
        "`live_cuepoint.candidate`",
        "`cuepoint.candidate`",
        "It never implies a VOD chapter exists",
        "It never implies a live ad cuepoint was sent or accepted",
        "`chapter_only`",
    ):
        assert phrase in body


def test_example_boundary_is_parseable_and_dry_run_safe() -> None:
    body = _body()
    schema = _schema()
    match = re.search(r"```json\n(?P<payload>.*?)\n```", body, re.DOTALL)
    assert match, "example ProgrammeBoundaryEvent JSON block missing"

    event = json.loads(match.group("payload"))

    assert event["schema_version"] == 1
    assert re.match(schema["properties"]["boundary_id"]["pattern"], event["boundary_id"])
    assert event["boundary_type"] == "rank.assigned"
    assert event["public_private_mode"] == "dry_run"
    assert event["no_expert_system_gate"]["gate_state"] == "dry_run"
    assert event["no_expert_system_gate"]["public_claim_allowed"] is False
    assert event["public_event_mapping"]["research_vehicle_event_type"] == "programme.boundary"
    assert event["public_event_mapping"]["fallback_action"] == "chapter_only"
    assert event["cuepoint_chapter_policy"]["live_ad_cuepoint_allowed"] is False
    assert event["cuepoint_chapter_policy"]["vod_chapter_allowed"] is True
    assert event["cuepoint_chapter_policy"]["live_cuepoint_distinct_from_vod_chapter"] is True
    assert "dry_run_mode" in event["dry_run_unavailable_reasons"]


def test_unavailable_reasons_are_machine_readable_and_named_in_spec() -> None:
    schema = _schema()
    reasons = set(schema["$defs"]["unavailable_reason"]["enum"])
    body = _body()

    for reason in (
        "private_mode",
        "dry_run_mode",
        "missing_grounding_gate",
        "grounding_gate_failed",
        "unsupported_claim",
        "source_stale",
        "rights_blocked",
        "privacy_blocked",
        "egress_blocked",
        "audio_blocked",
        "archive_missing",
        "video_id_missing",
        "cuepoint_smoke_missing",
        "cuepoint_api_rejected",
        "rate_limited",
        "monetization_blocked",
        "operator_review_required",
    ):
        assert reason in reasons
        assert f"`{reason}`" in body
