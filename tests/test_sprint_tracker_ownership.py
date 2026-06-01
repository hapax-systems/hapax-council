"""OQ-9 vault-ownership enforcement at the sprint_tracker write boundary.

CASE-SDLC-REFORM-001 Phase 8. sprint_tracker is the daemon writer for
``measure`` and ``gate`` coordination notes. Before OQ-9 it preserved
operator-authored fields only *incidentally* — it round-tripped the whole
frontmatter dict it had loaded, so a concurrent operator edit between load and
write was silently clobbered. These tests pin the contractual guarantee: the
daemon write re-reads the note and refuses to overwrite an operator-owned field
that diverges on disk, while still applying its own coordination fields.
"""

from __future__ import annotations

from pathlib import Path

import agents.sprint_tracker as st


def test_write_frontmatter_refuses_divergent_operator_field(tmp_path: Path) -> None:
    note = tmp_path / "7.1.md"
    # What the operator has on disk *now* (e.g. edited after the daemon loaded it).
    note.write_text(
        "---\nid: '7.1'\ntitle: Operator edited title\nstatus: pending\n---\nBody.\n",
        encoding="utf-8",
    )
    # The daemon's in-memory copy carries a STALE operator title plus a real
    # coordination change it wants to persist.
    fm = {
        "id": "7.1",
        "title": "STALE daemon copy",
        "status": "completed",
        "completed_at": "2026-05-31T00:00:00Z",
    }

    st._write_frontmatter(note, fm, "Body.\n", note_type="measure")

    on_disk, _body = st._parse_note(note)
    # daemon-owned coordination fields applied
    assert on_disk["status"] == "completed"
    assert on_disk["completed_at"] == "2026-05-31T00:00:00Z"
    # operator-owned field preserved — the divergent daemon value is refused
    assert on_disk["title"] == "Operator edited title"


def test_write_frontmatter_applies_gate_coordination_fields(tmp_path: Path) -> None:
    note = tmp_path / "G1.md"
    note.write_text(
        "---\nid: G1\ntitle: Operator gate title\nstatus: pending\n---\nRationale.\n",
        encoding="utf-8",
    )
    fm = {
        "id": "G1",
        "title": "daemon clobber",
        "status": "failed",
        "evaluated_at": "2026-05-31T01:00:00Z",
        "result_value": 0.42,
    }

    st._write_frontmatter(note, fm, "Rationale.\n", note_type="gate")

    on_disk, body = st._parse_note(note)
    assert on_disk["status"] == "failed"
    assert on_disk["evaluated_at"] == "2026-05-31T01:00:00Z"
    assert on_disk["result_value"] == 0.42
    assert on_disk["title"] == "Operator gate title"
    assert "Rationale." in body
