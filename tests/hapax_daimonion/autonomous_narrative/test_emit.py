"""Unit tests for autonomous_narrative.emit."""

from __future__ import annotations

import json
from pathlib import Path

from agents.hapax_daimonion.autonomous_narrative import emit


def _read_records(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def test_emit_writes_impingement_and_chronicle(tmp_path: Path) -> None:
    p = tmp_path / "impingements.jsonl"
    ok = emit.emit_narrative(
        "Vinyl side B started.",
        programme_id="prog-1",
        operator_referent="Oudepode",
        impingement_path=p,
        now=1234.0,
    )
    assert ok is True
    records = _read_records(p)
    assert len(records) == 2
    impingement, chronicle = records
    assert impingement["source"] == "autonomous_narrative"
    assert impingement["intent_family"] == "narrative.autonomous_speech"
    assert impingement["content"]["narrative"] == "Vinyl side B started."
    assert impingement["content"]["programme_id"] == "prog-1"
    assert impingement["content"]["operator_referent"] == "Oudepode"
    assert chronicle["source"] == "self_authored_narrative"
    assert chronicle["event_type"] == "narrative.emitted"
    assert chronicle["payload"]["narrative"] == "Vinyl side B started."


def test_emit_appends_not_overwrites(tmp_path: Path) -> None:
    p = tmp_path / "impingements.jsonl"
    emit.emit_narrative("first", impingement_path=p, now=1.0)
    emit.emit_narrative("second", impingement_path=p, now=2.0)
    records = _read_records(p)
    # Two emissions × 2 records each = 4 lines
    assert len(records) == 4
    narratives = [
        r.get("content", {}).get("narrative") or r.get("payload", {}).get("narrative")
        for r in records
    ]
    assert "first" in narratives
    assert "second" in narratives


def test_emit_creates_parent_directory(tmp_path: Path) -> None:
    p = tmp_path / "subdir" / "impingements.jsonl"
    assert not p.parent.exists()
    ok = emit.emit_narrative("test", impingement_path=p)
    assert ok is True
    assert p.exists()


def test_emit_chronicle_event_filtered_by_state_readers(tmp_path: Path) -> None:
    """The chronicle event we WRITE must use a source the reader FILTERS.

    Closes the feedback loop: composer can't read its own output back.
    """
    from agents.hapax_daimonion.autonomous_narrative import state_readers

    p = tmp_path / "impingements.jsonl"
    emit.emit_narrative("self-test", impingement_path=p, now=1000.0)
    # The reader, given the same chronicle, must filter both records.
    out = state_readers.read_chronicle_window(now=1000.0, window_s=600.0, path=p)
    assert out == [], "self-authored narrative MUST be filtered"


def test_emit_handles_missing_optional_args(tmp_path: Path) -> None:
    """programme_id and operator_referent are optional; emit still works."""
    p = tmp_path / "impingements.jsonl"
    ok = emit.emit_narrative("minimal", impingement_path=p)
    assert ok is True
    records = _read_records(p)
    impingement = records[0]
    assert impingement["content"]["narrative"] == "minimal"
    assert impingement["content"]["programme_id"] is None
    assert impingement["content"]["operator_referent"] is None
