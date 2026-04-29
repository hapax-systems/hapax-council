"""Regression pins for the director control move audit-log contract."""

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
    / "2026-04-29-director-control-move-audit-log-design.md"
)
SCHEMA = REPO_ROOT / "schemas" / "director-control-move-audit-log.schema.json"
DIRECTOR_MOVE_SCHEMA = REPO_ROOT / "schemas" / "director-substrate-control-plane.schema.json"


def _body() -> str:
    return SPEC.read_text(encoding="utf-8")


def _schema() -> dict[str, object]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def _director_move_schema() -> dict[str, object]:
    return json.loads(DIRECTOR_MOVE_SCHEMA.read_text(encoding="utf-8"))


def test_spec_covers_required_contract_sections() -> None:
    body = _body()

    for heading in (
        "## Audit Record Schema Seed",
        "## Explicit Result States And Fallback",
        "## Mark Boundary Projection",
        "## Audit Trail Consumers",
        "## Storage And Metrics Policy",
        "## Failure Behavior",
        "## Acceptance Pin",
    ):
        assert heading in body


def test_schema_requires_acceptance_fields() -> None:
    schema = _schema()
    required = set(schema["required"])
    properties = schema["properties"]

    for field in (
        "programme_id",
        "run_id",
        "lane_id",
        "verb",
        "reason",
        "evidence",
        "gate_results",
        "fallback",
        "rendered_evidence",
        "mark_boundary_projection",
        "audit_trail",
        "metrics",
    ):
        assert field in required
        assert field in properties


def test_schema_reuses_all_director_control_verbs() -> None:
    schema = _schema()
    director_schema = _director_move_schema()

    assert set(schema["$defs"]["director_verb"]["enum"]) == set(
        director_schema["$defs"]["director_verb"]["enum"]
    )


def test_noop_dry_run_and_unavailable_states_are_explicit() -> None:
    schema = _schema()
    body = _body()

    result_states = set(schema["properties"]["result_state"]["enum"])
    execution_states = set(schema["properties"]["execution_state"]["enum"])
    fallback_modes = set(schema["$defs"]["fallback_mode"]["enum"])

    for state in ("no_op", "dry_run", "unavailable"):
        assert state in result_states
        assert state in execution_states
        assert state in fallback_modes
        assert f"`{state}`" in body


def test_gate_results_cover_grounding_policy_and_public_conversion_gates() -> None:
    schema = _schema()
    gates = set(schema["properties"]["gate_results"]["required"])

    assert gates == {
        "no_expert_system",
        "public_claim",
        "rights",
        "privacy",
        "egress",
        "audio",
        "monetization",
        "archive",
        "cuepoint_chapter",
    }


def test_mark_boundary_projection_preserves_chapter_and_clip_without_publication() -> None:
    schema = _schema()
    projection = schema["properties"]["mark_boundary_projection"]["properties"]
    body = _body()

    assert projection["force_publication"]["const"] is False
    assert "chapter_candidate" in projection
    assert "clip_candidate" in projection

    for phrase in (
        "`force_publication` is always false",
        "`chapter_candidate` is a replay/navigation candidate",
        "`clip_candidate` is a conversion candidate",
        "Public-event adapters may use the audit row only after",
    ):
        assert phrase in body


def test_audit_trail_names_replay_metrics_scorecard_and_public_event_consumers() -> None:
    schema = _schema()
    consumers = set(schema["$defs"]["audit_consumer"]["enum"])
    sinks = set(schema["$defs"]["audit_sink"]["enum"])
    body = _body()

    assert {"replay", "metrics", "grounding_scorecard", "public_event_adapter"} <= consumers
    assert {
        "jsonl",
        "artifact_payload",
        "prometheus_counter",
        "replay_index",
        "grounding_scorecard",
        "public_event_adapter",
    } <= sinks

    for consumer in ("Replay", "Metrics", "Grounding scorecard", "Public-event adapter"):
        assert consumer in body


def test_example_audit_record_is_parseable_and_dry_run_boundary_safe() -> None:
    body = _body()
    schema = _schema()
    match = re.search(r"```json\n(?P<payload>.*?)\n```", body, re.DOTALL)
    assert match, "example DirectorControlMoveAuditRecord JSON block missing"

    record = json.loads(match.group("payload"))

    assert record["schema_version"] == 1
    assert re.match(schema["properties"]["audit_id"]["pattern"], record["audit_id"])
    assert record["programme_id"] == "programme_tierlist_models_20260429"
    assert record["run_id"] == "run_20260429_models_a"
    assert record["lane_id"] == "programme_cuepoints"
    assert record["verb"] == "mark_boundary"
    assert record["execution_state"] == "dry_run"
    assert record["result_state"] == "dry_run"
    assert record["public_claim_allowed"] is False
    assert record["gate_results"]["public_claim"]["state"] == "dry_run"
    assert record["fallback"]["mode"] == "chapter_only"
    assert record["rendered_evidence"]["replay_ref"].startswith("replay:")
    assert record["mark_boundary_projection"]["chapter_candidate"]["allowed"] is True
    assert record["mark_boundary_projection"]["clip_candidate"]["allowed"] is False
    assert record["mark_boundary_projection"]["force_publication"] is False
