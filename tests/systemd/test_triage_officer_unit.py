from __future__ import annotations

from pathlib import Path

UNIT = Path(__file__).resolve().parents[2] / "systemd/units/hapax-frontier-triage-officer.service"


def test_triage_officer_unit_runs_frontier_annotator() -> None:
    text = UNIT.read_text(encoding="utf-8")

    assert "HAPAX_AGENT_NAME=triage-officer" in text
    assert "uv run python -m agents.triage_officer" in text
    assert "--write" in text
    assert "--limit" in text
    assert "HAPAX_TRIAGE_LIMIT" in text
    assert ".cache/hapax/source-activation/worktree" in text
    assert "projects/hapax-council" in text
