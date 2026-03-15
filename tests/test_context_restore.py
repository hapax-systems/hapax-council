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
    ContextSnapshot,
    collect_last_queries,
    collect_system_status,
    collect_time_since_last_session,
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
                        "project": "/home/hapax/projects/hapax-council",
                        "timestamp": now_ms - 60000,
                        "sessionId": "s1",
                    }
                ),
                json.dumps(
                    {
                        "display": "unrelated work",
                        "project": "/home/hapax/projects/other",
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
                queries = collect_last_queries("/home/hapax/projects/hapax-council", n=3)
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
        briefing = """# System Briefing
## Stack DEGRADED, 20 drift items

Summary text.

## Action Items
- [ ] Fix audio-recorder.service ⏫
- [ ] Clear rag-retry queue ⏫
- [ ] Low priority thing 🔼
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(briefing)
            path = Path(f.name)

        try:
            with patch("agents.context_restore.BRIEFING_PATH", path):
                with patch("agents.context_restore.DRIFT_REPORT", Path("/nonexistent")):
                    status = collect_system_status()
                    assert "DEGRADED" in status["health"]
                    assert len(status["actions"]) == 2
                    assert "Fix audio-recorder.service" in status["actions"][0]
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
        now_ms = int(time.time() * 1000) - 30000  # 30s ago
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
        ts = int((time.time() - 7200) * 1000)  # 2h ago
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


class TestFormatContext(unittest.TestCase):
    def test_formats_complete_context(self):
        ctx = ContextSnapshot(
            last_queries=[{"query": "implement the feature", "project": "/proj", "timestamp": ""}],
            current_branch="feat/context-restoration",
            last_commit="abc1234 feat: add context restore",
            unstaged_files=["a.py", "b.py"],
            open_prs=[{"number": 90, "title": "governance benchmarks", "branch": "feat/bench"}],
            next_meetings=[{"time": "14:00", "summary": "1:1 with Alice", "attendees": ["alice"]}],
            system_status="Stack DEGRADED, 20 drift items",
            drift_count=20,
            high_priority_actions=["Fix audio-recorder.service"],
            time_since_last_session="3 hours ago",
        )
        text = format_context(ctx)
        assert "implement the feature" in text
        assert "feat/context-restoration" in text
        assert "2 files" in text
        assert "#90" in text
        assert "14:00" in text
        assert "DEGRADED" in text
        assert "audio-recorder" in text

    def test_formats_minimal_context(self):
        ctx = ContextSnapshot()
        text = format_context(ctx)
        assert text == ""  # Empty context produces no output

    def test_truncates_pr_list(self):
        ctx = ContextSnapshot(
            open_prs=[{"number": i, "title": f"PR {i}", "branch": f"b{i}"} for i in range(10)],
        )
        text = format_context(ctx)
        assert "#0" in text
        assert "#3" not in text  # Capped at 3
