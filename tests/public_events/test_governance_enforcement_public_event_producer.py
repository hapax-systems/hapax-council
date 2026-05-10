"""Governance enforcement ResearchVehiclePublicEvent producer tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agents.governance_enforcement_public_event_producer import (
    GovernanceEnforcementPublicEventProducer,
    build_governance_enforcement_event,
    governance_enforcement_event_id,
)


def _enforcement_record(**overrides: Any) -> dict[str, Any]:
    record = {
        "event_type": "axiom_blocked",
        "timestamp": "2026-05-10T14:30:00Z",
        "hook": "axiom-scan",
        "domain": "single_user",
        "pattern": "blocked-pattern-xyz",
        "matched": "xyz_blocked_construct()",
        "file_path": "shared/example.py",
        "description": "Blocked by axiom governance.",
        "recovery": "Remove the prohibited construct.",
        "tool": "Edit",
    }
    record.update(overrides)
    return record


def _write_enforcement(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _read_public_events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_enforcement_event_maps_axiom_block() -> None:
    event = build_governance_enforcement_event(
        _enforcement_record(),
        evidence_ref="/dev/shm/hapax-governance/enforcement.jsonl#byte=0",
    )

    assert event.event_type == "governance.enforcement"
    assert event.state_kind == "governance_state"
    assert event.source.substrate_id == "governance_axiom"
    assert event.source.task_anchor == "governance-enforcement-public-event-producer"
    assert event.rights_class == "operator_original"
    assert event.privacy_class == "public_safe"
    assert event.salience == 0.85
    assert event.surface_policy.claim_live is False
    assert event.surface_policy.claim_archive is True
    assert "health" in event.surface_policy.allowed_surfaces
    assert "archive" in event.surface_policy.allowed_surfaces
    assert "youtube_description" in event.surface_policy.denied_surfaces
    assert event.surface_policy.fallback_action == "archive_only"
    assert event.surface_policy.dry_run_reason is None


def test_enforcement_event_provenance_captures_hook_details() -> None:
    event = build_governance_enforcement_event(
        _enforcement_record(),
        evidence_ref="enforcement.jsonl#byte=0",
    )

    assert event.provenance.token is not None
    assert event.provenance.token.startswith("governance_enforcement:")
    assert "hook:axiom-scan" in event.provenance.evidence_refs
    assert "domain:single_user" in event.provenance.evidence_refs
    assert "tool:Edit" in event.provenance.evidence_refs
    assert "file:shared/example.py" in event.provenance.evidence_refs


def test_event_id_is_stable_and_schema_safe() -> None:
    first = governance_enforcement_event_id(_enforcement_record())
    second = governance_enforcement_event_id(_enforcement_record())

    assert first == second
    assert first.startswith("rvpe:governance_enforcement:")
    assert "-" not in first


def test_event_id_differs_for_different_matches() -> None:
    id_a = governance_enforcement_event_id(_enforcement_record(matched="construct_alpha"))
    id_b = governance_enforcement_event_id(_enforcement_record(matched="construct_beta"))

    assert id_a != id_b


def test_commit_scan_enforcement_maps_correctly() -> None:
    event = build_governance_enforcement_event(
        _enforcement_record(
            hook="axiom-commit-scan",
            tool="git-commit",
            file_path="staged-diff",
            domain="management_governance",
            matched="blocked_mgmt_construct()",
        ),
        evidence_ref="enforcement.jsonl#byte=100",
    )

    assert event.event_type == "governance.enforcement"
    assert "hook:axiom-commit-scan" in event.provenance.evidence_refs
    assert "domain:management_governance" in event.provenance.evidence_refs
    assert "tool:git-commit" in event.provenance.evidence_refs


def test_producer_writes_public_event_and_advances_cursor(tmp_path: Path) -> None:
    enforcement = tmp_path / "enforcement.jsonl"
    public = tmp_path / "public.jsonl"
    cursor = tmp_path / "cursor.txt"
    _write_enforcement(enforcement, _enforcement_record())
    producer = GovernanceEnforcementPublicEventProducer(
        enforcement_path=enforcement,
        public_event_path=public,
        cursor_path=cursor,
    )

    assert producer.run_once() == 1
    events = _read_public_events(public)
    assert len(events) == 1
    assert events[0]["event_type"] == "governance.enforcement"
    assert events[0]["state_kind"] == "governance_state"
    assert int(cursor.read_text(encoding="utf-8")) == enforcement.stat().st_size


def test_producer_skips_non_axiom_events(tmp_path: Path) -> None:
    enforcement = tmp_path / "enforcement.jsonl"
    public = tmp_path / "public.jsonl"
    cursor = tmp_path / "cursor.txt"
    _write_enforcement(
        enforcement, {"event_type": "other_event", "timestamp": "2026-05-10T14:30:00Z"}
    )
    _write_enforcement(enforcement, _enforcement_record())
    producer = GovernanceEnforcementPublicEventProducer(
        enforcement_path=enforcement,
        public_event_path=public,
        cursor_path=cursor,
    )

    assert producer.run_once() == 1
    events = _read_public_events(public)
    assert len(events) == 1


def test_producer_skips_duplicate_event_ids(tmp_path: Path) -> None:
    enforcement = tmp_path / "enforcement.jsonl"
    public = tmp_path / "public.jsonl"
    cursor = tmp_path / "cursor.txt"
    record = _enforcement_record()
    _write_enforcement(enforcement, record)
    producer = GovernanceEnforcementPublicEventProducer(
        enforcement_path=enforcement,
        public_event_path=public,
        cursor_path=cursor,
    )

    assert producer.run_once() == 1
    cursor.unlink()
    assert producer.run_once() == 0
    assert len(_read_public_events(public)) == 1


def test_producer_handles_missing_enforcement_file(tmp_path: Path) -> None:
    enforcement = tmp_path / "enforcement.jsonl"
    public = tmp_path / "public.jsonl"
    cursor = tmp_path / "cursor.txt"
    producer = GovernanceEnforcementPublicEventProducer(
        enforcement_path=enforcement,
        public_event_path=public,
        cursor_path=cursor,
    )

    assert producer.run_once() == 0


def test_producer_resets_cursor_on_file_shrink(tmp_path: Path) -> None:
    enforcement = tmp_path / "enforcement.jsonl"
    public = tmp_path / "public.jsonl"
    cursor = tmp_path / "cursor.txt"
    _write_enforcement(enforcement, _enforcement_record())
    producer = GovernanceEnforcementPublicEventProducer(
        enforcement_path=enforcement,
        public_event_path=public,
        cursor_path=cursor,
    )
    assert producer.run_once() == 1

    short_record = {
        "event_type": "axiom_blocked",
        "timestamp": "2026-05-10T15:00:00Z",
        "hook": "axiom-scan",
        "domain": "single_user",
        "matched": "x",
    }
    enforcement.write_text(json.dumps(short_record) + "\n", encoding="utf-8")
    producer = GovernanceEnforcementPublicEventProducer(
        enforcement_path=enforcement,
        public_event_path=public,
        cursor_path=cursor,
    )
    assert producer.run_once() == 1
    events = _read_public_events(public)
    assert len(events) == 2


def test_producer_processes_multiple_records(tmp_path: Path) -> None:
    enforcement = tmp_path / "enforcement.jsonl"
    public = tmp_path / "public.jsonl"
    cursor = tmp_path / "cursor.txt"
    _write_enforcement(enforcement, _enforcement_record(timestamp="2026-05-10T14:00:00Z"))
    _write_enforcement(
        enforcement,
        _enforcement_record(
            timestamp="2026-05-10T14:01:00Z",
            matched="another_blocked_construct()",
        ),
    )
    producer = GovernanceEnforcementPublicEventProducer(
        enforcement_path=enforcement,
        public_event_path=public,
        cursor_path=cursor,
    )

    assert producer.run_once() == 2
    events = _read_public_events(public)
    assert len(events) == 2
    assert all(e["event_type"] == "governance.enforcement" for e in events)
