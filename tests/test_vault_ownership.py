"""Tests for the per-field vault write-ownership policy (OQ-9).

CASE-SDLC-REFORM-001 Phase 8. The load-bearing acceptance criterion: an
operator-owned frontmatter field survives a daemon write pass.
"""

from __future__ import annotations

from pathlib import Path

from shared.frontmatter import parse_frontmatter
from shared.vault_ownership import (
    Ownership,
    daemon_owned_keys,
    filter_daemon_frontmatter,
    frontmatter_preserved,
    governed_note_write,
    is_daemon_writable,
    merge_daemon_frontmatter,
    ownership,
    partition_frontmatter,
    resolve_by_ledger_order,
)

# ── Classification ──────────────────────────────────────────────────────────


def test_daemon_generated_note_owns_every_key() -> None:
    assert daemon_owned_keys("briefing") is None
    assert is_daemon_writable("briefing", "anything")
    assert is_daemon_writable("nudges", "updated")
    assert ownership("digest", "whatever") is Ownership.DAEMON


def test_operator_note_owns_unlisted_keys() -> None:
    # measure notes: status is daemon-owned, title/effort_hours are operator-owned
    assert is_daemon_writable("measure", "status")
    assert is_daemon_writable("measure", "completed_at")
    assert not is_daemon_writable("measure", "title")
    assert not is_daemon_writable("measure", "effort_hours")
    assert ownership("measure", "title") is Ownership.OPERATOR


def test_pure_operator_notes_have_no_daemon_keys() -> None:
    assert daemon_owned_keys("daily") == frozenset()
    assert daemon_owned_keys("person") == frozenset()
    assert not is_daemon_writable("daily", "tags")
    assert not is_daemon_writable("person", "last_meeting")


def test_unknown_note_type_is_operator_owned_by_default() -> None:
    assert daemon_owned_keys("some-new-type") == frozenset()
    assert daemon_owned_keys(None) == frozenset()
    assert not is_daemon_writable("some-new-type", "field")
    assert ownership(None, "field") is Ownership.OPERATOR


# ── Partition / filter ──────────────────────────────────────────────────────


def test_partition_splits_by_ownership() -> None:
    part = partition_frontmatter(
        "measure", {"status": "completed", "title": "hacked", "result_summary": "ok"}
    )
    assert part.allowed == {"status": "completed", "result_summary": "ok"}
    assert part.refused == {"title": "hacked"}


def test_filter_drops_operator_keys() -> None:
    filtered = filter_daemon_frontmatter(
        "goal", {"progress": 0.5, "priority": "P0", "title": "owned"}, warn=False
    )
    assert filtered == {"progress": 0.5}


def test_filter_passes_everything_for_daemon_note() -> None:
    raw = {"type": "rag_note", "platform": "obsidian", "tags": ["a"]}
    assert filter_daemon_frontmatter("rag_note", raw, warn=False) == raw


# ── Ledger-order conflict resolution ────────────────────────────────────────


def test_resolve_by_ledger_order_last_wins() -> None:
    resolved = resolve_by_ledger_order(
        [("status", "pending"), ("status", "in_progress"), ("status", "completed")]
    )
    assert resolved == {"status": "completed"}


def test_merge_prefers_ledger_value_for_coordination_field() -> None:
    existing = {"id": "10.1", "status": "pending", "title": "Operator title"}
    proposed = {"status": "in_progress"}
    result = merge_daemon_frontmatter(
        existing, proposed, "measure", ledger_resolved={"status": "completed"}
    )
    # ledger order wins over the proposed value for the coordination field
    assert result.merged["status"] == "completed"
    assert "status" in result.applied


# ── The load-bearing invariant: operator fields survive ─────────────────────


def test_operator_field_survives_daemon_merge() -> None:
    existing = {
        "id": "10.1",
        "title": "Operator-authored title",
        "effort_hours": 4.0,
        "status": "pending",
        "operator_note": "do not clobber me",
    }
    # A daemon write that *tries* to change operator-owned fields too.
    proposed = {
        "status": "completed",
        "completed_at": "2026-05-31T00:00:00Z",
        "title": "DAEMON OVERWRITE",
        "effort_hours": 999.0,
    }
    result = merge_daemon_frontmatter(existing, proposed, "measure")

    # daemon-owned fields applied
    assert result.merged["status"] == "completed"
    assert result.merged["completed_at"] == "2026-05-31T00:00:00Z"
    # operator-owned fields preserved verbatim, the attempted changes refused
    assert result.merged["title"] == "Operator-authored title"
    assert result.merged["effort_hours"] == 4.0
    assert result.merged["operator_note"] == "do not clobber me"
    assert result.refused == {"title": "DAEMON OVERWRITE", "effort_hours": 999.0}


def test_daemon_cannot_add_new_operator_key() -> None:
    existing = {"id": "G1", "status": "pending"}
    proposed = {"status": "passed", "operator_secret": "injected"}
    result = merge_daemon_frontmatter(existing, proposed, "gate")
    assert "operator_secret" not in result.merged
    assert result.refused == {"operator_secret": "injected"}


# ── Governed on-disk write ──────────────────────────────────────────────────


def test_governed_note_write_preserves_operator_fields(tmp_path: Path) -> None:
    note = tmp_path / "10.1-measure.md"
    note.write_text(
        "---\n"
        "id: '10.1'\n"
        "title: Operator title\n"
        "effort_hours: 4.0\n"
        "status: pending\n"
        "---\n"
        "Body the operator wrote.\n",
        encoding="utf-8",
    )

    result = governed_note_write(
        note,
        frontmatter={"status": "completed", "title": "clobber", "completed_at": "2026-05-31"},
        note_type="measure",
    )

    fm, body = parse_frontmatter(note)
    assert fm["status"] == "completed"
    assert fm["completed_at"] == "2026-05-31"
    assert fm["title"] == "Operator title"  # operator field survived the daemon write
    assert fm["effort_hours"] == 4.0
    assert body.strip() == "Body the operator wrote."
    assert result.refused == {"title": "clobber"}


def test_governed_note_write_preserves_body_when_none(tmp_path: Path) -> None:
    note = tmp_path / "g.md"
    note.write_text("---\nid: G1\nstatus: pending\n---\nGate rationale.\n", encoding="utf-8")
    governed_note_write(note, frontmatter={"status": "passed"}, note_type="gate", body=None)
    _, body = parse_frontmatter(note)
    assert "Gate rationale." in body


# ── Frontmatter-preservation guard (daily-note body writes) ─────────────────


def test_frontmatter_preserved_detects_body_only_change() -> None:
    before = "---\ntype: daily\ntags: [x]\n---\n## Log\n- old\n"
    after = "---\ntype: daily\ntags: [x]\n---\n## Log\n- old\n- new\n"
    assert frontmatter_preserved(before, after)


def test_frontmatter_preserved_detects_frontmatter_change() -> None:
    before = "---\ntype: daily\ntags: [x]\n---\n## Log\n- old\n"
    after = "---\ntype: daily\ntags: [x, INJECTED]\n---\n## Log\n- old\n"
    assert not frontmatter_preserved(before, after)
