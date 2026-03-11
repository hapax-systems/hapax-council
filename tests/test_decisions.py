"""Tests for Stage 6: Decision Capture.

Covers: record_decision, collect_decisions, read_decisions_log reader,
and profiler source discovery integration.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from agents.profiler_sources import (
    DiscoveredSources,
    discover_sources,
    list_source_ids,
    read_decisions_log,
)
from cockpit.data.decisions import Decision, _rotate_decisions, collect_decisions, record_decision

# ── record_decision tests ─────────────────────────────────────────────────


def test_record_decision_creates_file(tmp_path):
    """record_decision creates the JSONL file and writes an entry."""
    path = tmp_path / "decisions.jsonl"
    with patch("cockpit.data.decisions._DECISIONS_PATH", path):
        record_decision(
            Decision(
                timestamp="2026-03-01T10:00:00+00:00",
                nudge_title="Run health check",
                nudge_category="health",
                action="executed",
                context="uv run python -m agents.health_monitor",
            )
        )
    assert path.exists()
    data = json.loads(path.read_text().strip())
    assert data["nudge_title"] == "Run health check"
    assert data["action"] == "executed"


def test_record_decision_appends(tmp_path):
    """Multiple decisions are appended to the same file."""
    path = tmp_path / "decisions.jsonl"
    with patch("cockpit.data.decisions._DECISIONS_PATH", path):
        record_decision(
            Decision(
                timestamp="2026-03-01T10:00:00+00:00",
                nudge_title="First",
                nudge_category="health",
                action="executed",
            )
        )
        record_decision(
            Decision(
                timestamp="2026-03-01T10:05:00+00:00",
                nudge_title="Second",
                nudge_category="goal",
                action="dismissed",
            )
        )
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["nudge_title"] == "First"
    assert json.loads(lines[1])["nudge_title"] == "Second"


# ── collect_decisions tests ───────────────────────────────────────────────


def test_collect_decisions_basic(tmp_path):
    """Collects all decisions within the lookback window."""
    path = tmp_path / "decisions.jsonl"
    now = datetime.now(UTC)
    entries = [
        {
            "timestamp": now.isoformat(),
            "nudge_title": "Recent",
            "nudge_category": "health",
            "action": "executed",
        },
        {
            "timestamp": (now - timedelta(hours=200)).isoformat(),
            "nudge_title": "Old",
            "nudge_category": "goal",
            "action": "expired",
        },
    ]
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    with patch("cockpit.data.decisions._DECISIONS_PATH", path):
        decisions = collect_decisions(hours=168)  # 7 days
    # Only the recent one should be included
    assert len(decisions) == 1
    assert decisions[0].nudge_title == "Recent"


def test_collect_decisions_empty_file(tmp_path):
    """Empty file returns empty list."""
    path = tmp_path / "decisions.jsonl"
    path.write_text("")
    with patch("cockpit.data.decisions._DECISIONS_PATH", path):
        decisions = collect_decisions()
    assert decisions == []


def test_collect_decisions_no_file(tmp_path):
    """Missing file returns empty list."""
    path = tmp_path / "nonexistent.jsonl"
    with patch("cockpit.data.decisions._DECISIONS_PATH", path):
        decisions = collect_decisions()
    assert decisions == []


def test_collect_decisions_corrupt_lines(tmp_path):
    """Corrupt lines are skipped."""
    path = tmp_path / "decisions.jsonl"
    now = datetime.now(UTC)
    path.write_text(
        "not json\n"
        + json.dumps(
            {
                "timestamp": now.isoformat(),
                "nudge_title": "Valid",
                "nudge_category": "health",
                "action": "executed",
            }
        )
        + "\n"
    )
    with patch("cockpit.data.decisions._DECISIONS_PATH", path):
        decisions = collect_decisions()
    assert len(decisions) == 1
    assert decisions[0].nudge_title == "Valid"


# ── read_decisions_log tests ──────────────────────────────────────────────


def test_read_decisions_log_basic(tmp_path):
    """Valid JSONL produces a SourceChunk."""
    path = tmp_path / "decisions.jsonl"
    entries = [
        {
            "timestamp": "2026-03-01T10:00:00+00:00",
            "nudge_title": "Run health check",
            "nudge_category": "health",
            "action": "executed",
        },
        {
            "timestamp": "2026-03-01T10:05:00+00:00",
            "nudge_title": "Check stale goal",
            "nudge_category": "goal",
            "action": "dismissed",
        },
    ]
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    chunks = read_decisions_log(path)
    assert len(chunks) == 1
    assert chunks[0].source_type == "decisions"
    assert "executed" in chunks[0].text
    assert "dismissed" in chunks[0].text
    assert "health check" in chunks[0].text


def test_read_decisions_log_empty(tmp_path):
    """Empty file returns no chunks."""
    path = tmp_path / "decisions.jsonl"
    path.write_text("")
    assert read_decisions_log(path) == []


def test_read_decisions_log_missing(tmp_path):
    """Missing file returns no chunks."""
    path = tmp_path / "nonexistent.jsonl"
    assert read_decisions_log(path) == []


def test_read_decisions_log_all_corrupt(tmp_path):
    """All corrupt lines returns no chunks."""
    path = tmp_path / "decisions.jsonl"
    path.write_text("bad\nworse\n")
    assert read_decisions_log(path) == []


# ── profiler_sources integration ──────────────────────────────────────────


def test_list_source_ids_with_decisions(tmp_path):
    """decisions_log appears in source ID list."""
    path = tmp_path / "decisions.jsonl"
    sources = DiscoveredSources(decisions_log=path)
    ids = list_source_ids(sources)
    assert any("decisions:" in sid for sid in ids)


def test_list_source_ids_without_decisions():
    """No decisions_log → no decisions source ID."""
    sources = DiscoveredSources()
    ids = list_source_ids(sources)
    assert not any("decisions:" in sid for sid in ids)


def test_discover_finds_decisions(tmp_path):
    """discover_sources detects decisions.jsonl when it exists."""
    decisions_path = tmp_path / ".cache" / "cockpit" / "decisions.jsonl"
    decisions_path.parent.mkdir(parents=True)
    decisions_path.write_text('{"action": "test"}\n')
    with patch("agents.profiler_sources.HOME", tmp_path):
        with patch("agents.profiler_sources.CLAUDE_DIR", tmp_path / ".claude"):
            with patch("agents.profiler_sources.PROJECTS_DIR", tmp_path / ".claude" / "projects"):
                with patch("agents.profiler_sources._check_langfuse_available", return_value=False):
                    sources = discover_sources()
    assert sources.decisions_log is not None
    assert sources.decisions_log.name == "decisions.jsonl"


def test_discover_no_decisions(tmp_path):
    """discover_sources leaves decisions_log=None when file is absent."""
    with patch("agents.profiler_sources.HOME", tmp_path):
        with patch("agents.profiler_sources.CLAUDE_DIR", tmp_path / ".claude"):
            with patch("agents.profiler_sources.PROJECTS_DIR", tmp_path / ".claude" / "projects"):
                with patch("agents.profiler_sources._check_langfuse_available", return_value=False):
                    sources = discover_sources()
    assert sources.decisions_log is None


# ── F-0.1: rotation uses os module correctly ─────────────────────────────


def test_rotate_decisions_over_500(tmp_path):
    """Rotation keeps last 500 lines when file exceeds max_lines."""
    path = tmp_path / "decisions.jsonl"
    now = datetime.now(UTC)
    lines = []
    for i in range(520):
        entry = {
            "timestamp": now.isoformat(),
            "nudge_title": f"Entry-{i}",
            "nudge_category": "test",
            "action": "executed",
            "context": "",
            "active_accommodations": [],
        }
        lines.append(json.dumps(entry))
    path.write_text("\n".join(lines) + "\n")
    assert len(path.read_text().strip().splitlines()) == 520

    with patch("cockpit.data.decisions._DECISIONS_PATH", path):
        _rotate_decisions(max_lines=500)

    result_lines = path.read_text().strip().splitlines()
    assert len(result_lines) == 500
    # Last entry should be Entry-519
    assert json.loads(result_lines[-1])["nudge_title"] == "Entry-519"
    # First entry should be Entry-20 (520 - 500)
    assert json.loads(result_lines[0])["nudge_title"] == "Entry-20"


def test_rotate_decisions_under_limit(tmp_path):
    """Rotation is a no-op when under the limit."""
    path = tmp_path / "decisions.jsonl"
    now = datetime.now(UTC)
    lines = []
    for i in range(10):
        entry = {
            "timestamp": now.isoformat(),
            "nudge_title": f"Entry-{i}",
            "nudge_category": "test",
            "action": "executed",
            "context": "",
            "active_accommodations": [],
        }
        lines.append(json.dumps(entry))
    path.write_text("\n".join(lines) + "\n")

    with patch("cockpit.data.decisions._DECISIONS_PATH", path):
        _rotate_decisions(max_lines=500)

    assert len(path.read_text().strip().splitlines()) == 10


# ── F-0.2: active_accommodations uses a.id correctly ────────────────────


def test_record_decision_populates_active_accommodations(tmp_path):
    """Active accommodations are populated using Accommodation.id attribute."""
    from cockpit.accommodations import Accommodation

    path = tmp_path / "decisions.jsonl"
    mock_accommodations = [
        Accommodation(
            id="time_anchor",
            pattern_category="time",
            description="Show elapsed time",
            active=True,
            proposed_at="2026-01-01T00:00:00+00:00",
        ),
        Accommodation(
            id="soft_framing",
            pattern_category="framing",
            description="Use soft framing",
            active=True,
            proposed_at="2026-01-01T00:00:00+00:00",
        ),
        Accommodation(
            id="energy_aware",
            pattern_category="energy",
            description="Energy awareness",
            active=False,
            proposed_at="2026-01-01T00:00:00+00:00",
        ),
    ]

    with (
        patch("cockpit.data.decisions._DECISIONS_PATH", path),
        patch("cockpit.accommodations.load_accommodations", return_value=mock_accommodations),
    ):
        record_decision(
            Decision(
                timestamp="2026-03-01T10:00:00+00:00",
                nudge_title="Test nudge",
                nudge_category="health",
                action="executed",
            )
        )

    data = json.loads(path.read_text().strip())
    # Only active accommodations should be recorded, using .id
    assert data["active_accommodations"] == ["time_anchor", "soft_framing"]
