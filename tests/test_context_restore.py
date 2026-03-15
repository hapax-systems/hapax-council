"""Tests for context restoration agent — cognitive state recovery.

Self-contained, asyncio_mode="auto", unittest.mock only.
"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.context_restore import (
    Accommodations,
    ContextSnapshot,
    collect_last_queries,
    collect_system_status,
    collect_time_since_last_session,
    determine_start_here,
    format_context,
)


class TestCollectLastQueries(unittest.TestCase):
    def test_extracts_matching_project(self):
        now_ms = int(time.time() * 1000)
        history = "\n".join(
            [
                json.dumps(
                    {
                        "display": "fix the bug",
                        "project": "/home/operator/projects/hapax-council",
                        "timestamp": now_ms - 60000,
                        "sessionId": "s1",
                    }
                ),
                json.dumps(
                    {
                        "display": "unrelated work",
                        "project": "/home/operator/projects/other",
                        "timestamp": now_ms,
                        "sessionId": "s2",
                    }
                ),
            ]
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(history)
            path = Path(f.name)

        try:
            with patch("agents.context_restore.CC_HISTORY", path):
                queries = collect_last_queries("/home/operator/projects/hapax-council", n=3)
                assert len(queries) == 1
                assert queries[0]["query"] == "fix the bug"
        finally:
            path.unlink()

    def test_limits_to_n(self):
        now_ms = int(time.time() * 1000)
        entries = [
            json.dumps(
                {
                    "display": f"query {i}",
                    "project": "/proj",
                    "timestamp": now_ms - i * 1000,
                    "sessionId": f"s{i}",
                }
            )
            for i in range(10)
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("\n".join(entries))
            path = Path(f.name)

        try:
            with patch("agents.context_restore.CC_HISTORY", path):
                queries = collect_last_queries("/proj", n=3)
                assert len(queries) == 3
        finally:
            path.unlink()

    def test_missing_history_returns_empty(self):
        with patch("agents.context_restore.CC_HISTORY", Path("/nonexistent")):
            assert collect_last_queries("/proj") == []

    def test_truncates_long_queries(self):
        now_ms = int(time.time() * 1000)
        entry = json.dumps(
            {
                "display": "x" * 300,
                "project": "/proj",
                "timestamp": now_ms,
                "sessionId": "s1",
            }
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(entry)
            path = Path(f.name)

        try:
            with patch("agents.context_restore.CC_HISTORY", path):
                queries = collect_last_queries("/proj", n=1)
                assert len(queries[0]["query"]) <= 200
        finally:
            path.unlink()


class TestCollectSystemStatus(unittest.TestCase):
    def test_extracts_from_briefing(self):
        briefing = (
            "# System Briefing\n"
            "## Stack DEGRADED, 20 drift items\n\n"
            "Summary text.\n\n"
            "## Action Items\n"
            "- [ ] Fix audio-recorder.service \u23eb\n"
            "- [ ] Clear rag-retry queue \u23eb\n"
            "- [ ] Low priority thing \U0001f53c\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(briefing)
            path = Path(f.name)

        try:
            with patch("agents.context_restore.BRIEFING_PATH", path):
                with patch("agents.context_restore.DRIFT_REPORT", Path("/nonexistent")):
                    status = collect_system_status()
                    assert "DEGRADED" in status["health"]
                    assert len(status["actions"]) == 2
        finally:
            path.unlink()

    def test_missing_briefing_returns_empty(self):
        with patch("agents.context_restore.BRIEFING_PATH", Path("/nonexistent")):
            with patch("agents.context_restore.DRIFT_REPORT", Path("/nonexistent")):
                status = collect_system_status()
                assert status["health"] == ""
                assert status["actions"] == []


class TestCollectTimeSinceLastSession(unittest.TestCase):
    def test_recent_session(self):
        now_ms = int(time.time() * 1000) - 30000
        entry = json.dumps(
            {"display": "q", "project": "/proj", "timestamp": now_ms, "sessionId": "s1"}
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(entry)
            path = Path(f.name)

        try:
            with patch("agents.context_restore.CC_HISTORY", path):
                result = collect_time_since_last_session("/proj")
                assert result == "just now"
        finally:
            path.unlink()

    def test_hours_ago(self):
        ts = int((time.time() - 7200) * 1000)
        entry = json.dumps({"display": "q", "project": "/proj", "timestamp": ts, "sessionId": "s1"})
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(entry)
            path = Path(f.name)

        try:
            with patch("agents.context_restore.CC_HISTORY", path):
                result = collect_time_since_last_session("/proj")
                assert "hours ago" in result
        finally:
            path.unlink()


class TestDetermineStartHere(unittest.TestCase):
    def test_uncommitted_on_feature_branch(self):
        ctx = ContextSnapshot(
            unstaged_files=["a.py", "b.py"],
            current_branch="feat/something",
        )
        result = determine_start_here(ctx)
        assert "Commit 2 files" in result
        assert "feat/something" in result

    def test_uncommitted_on_main_skipped(self):
        ctx = ContextSnapshot(unstaged_files=["a.py"], current_branch="main")
        assert determine_start_here(ctx) == ""

    def test_open_pr_when_no_uncommitted(self):
        ctx = ContextSnapshot(
            open_prs=[{"number": 78, "title": "consent gate", "branch": "fix/consent"}],
        )
        assert "#78" in determine_start_here(ctx)

    def test_meeting_prep(self):
        ctx = ContextSnapshot(
            next_meetings=[
                {"time": "14:00", "summary": "1:1 with Alice", "attendees": ["alice"]},
            ],
        )
        assert "14:00" in determine_start_here(ctx)

    def test_top_nudge(self):
        ctx = ContextSnapshot(
            pending_nudges=[
                {
                    "title": "Fix health check",
                    "priority_label": "critical",
                    "suggested_action": "Run health monitor fix",
                    "category": "health",
                },
            ],
        )
        assert "health monitor" in determine_start_here(ctx).lower()

    def test_empty_context_returns_empty(self):
        assert determine_start_here(ContextSnapshot()) == ""


class TestFormatContext(unittest.TestCase):
    def test_formats_complete_context(self):
        ctx = ContextSnapshot(
            last_queries=[{"query": "implement feature", "project": "/p", "timestamp": ""}],
            current_branch="feat/ctx",
            last_commit="abc feat: ctx",
            unstaged_files=["a.py", "b.py"],
            open_prs=[{"number": 90, "title": "benchmarks", "branch": "feat/b"}],
            next_meetings=[{"time": "14:00", "summary": "1:1 Alice", "attendees": ["alice"]}],
            system_status="Stack DEGRADED",
            drift_count=20,
            high_priority_actions=["Fix audio-recorder"],
            time_since_last_session="3 hours ago",
            start_here="Commit 2 files on feat/ctx",
        )
        text = format_context(ctx)
        assert "implement feature" in text
        assert "#90" in text
        assert "Start here" in text
        assert "Commit 2 files" in text

    def test_formats_minimal_context(self):
        assert format_context(ContextSnapshot()) == ""

    def test_soft_framing(self):
        ctx = ContextSnapshot(
            last_queries=[{"query": "work", "project": "/p", "timestamp": ""}],
            start_here="Do thing",
            accommodations=Accommodations(soft_framing=True),
        )
        text = format_context(ctx)
        assert "A good place to start:" in text
        assert "**Start here:**" not in text

    def test_low_energy_suppresses_drift(self):
        ctx = ContextSnapshot(
            drift_count=20,
            system_status="Stack healthy",
            accommodations=Accommodations(energy_aware=True, is_low_energy=True),
        )
        text = format_context(ctx)
        assert "Drift" not in text

    def test_low_energy_shows_degraded(self):
        ctx = ContextSnapshot(
            system_status="Stack DEGRADED",
            accommodations=Accommodations(energy_aware=True, is_low_energy=True),
        )
        text = format_context(ctx)
        assert "DEGRADED" in text

    def test_flow_interrupted(self):
        ctx = ContextSnapshot(was_in_flow=True)
        text = format_context(ctx)
        assert "Flow interrupted" in text

    def test_flow_soft_framing(self):
        ctx = ContextSnapshot(was_in_flow=True, accommodations=Accommodations(soft_framing=True))
        text = format_context(ctx)
        assert "deep focus" in text

    def test_nudges_shown(self):
        ctx = ContextSnapshot(
            pending_nudges=[
                {
                    "title": "2 health checks failing",
                    "category": "health",
                    "priority_label": "high",
                    "suggested_action": "fix",
                },
            ],
        )
        text = format_context(ctx)
        assert "health checks failing" in text

    def test_nudges_capped_low_energy(self):
        ctx = ContextSnapshot(
            pending_nudges=[
                {
                    "title": f"nudge {i}",
                    "category": "x",
                    "priority_label": "medium",
                    "suggested_action": "",
                }
                for i in range(5)
            ],
            accommodations=Accommodations(energy_aware=True, is_low_energy=True),
        )
        text = format_context(ctx)
        assert "nudge 0" in text
        assert "nudge 1" not in text

    def test_deep_work_window(self):
        ctx = ContextSnapshot(deep_work_window_hours=3.5)
        text = format_context(ctx)
        assert "uninterrupted" in text
