"""Tests for voice context enrichment functions."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.hapax_daimonion.context_enrichment import (
    render_dmn,
    render_goals,
    render_health,
    render_nudges,
)


class TestRenderGoals:
    def test_empty_goals(self):
        with patch("logos.data.goals.collect_goals") as mock:
            mock_snapshot = MagicMock()
            mock_snapshot.goals = []
            mock.return_value = mock_snapshot
            assert render_goals() == ""

    def test_active_goals(self):
        with patch("logos.data.goals.collect_goals") as mock:
            goal = MagicMock()
            goal.status = "active"
            goal.category = "primary"
            goal.name = "Ship v2"
            goal.stale = False
            mock_snapshot = MagicMock()
            mock_snapshot.goals = [goal]
            mock.return_value = mock_snapshot
            result = render_goals()
            assert "Operator Goals" in result
            assert "Ship v2" in result

    def test_stale_goal_marked(self):
        with patch("logos.data.goals.collect_goals") as mock:
            goal = MagicMock()
            goal.status = "active"
            goal.category = "secondary"
            goal.name = "Fix tests"
            goal.stale = True
            mock_snapshot = MagicMock()
            mock_snapshot.goals = [goal]
            mock.return_value = mock_snapshot
            result = render_goals()
            assert "\u26a0" in result

    def test_exception_returns_empty(self):
        with patch("logos.data.goals.collect_goals", side_effect=Exception):
            assert render_goals() == ""


class TestRenderHealth:
    def test_healthy_returns_empty(self, tmp_path):
        health_file = tmp_path / "health-history.jsonl"
        from datetime import UTC, datetime

        health_file.write_text(
            json.dumps(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "status": "healthy",
                    "healthy": 100,
                    "degraded": 0,
                    "failed": 0,
                    "failed_checks": [],
                }
            )
        )
        with patch("agents._config.PROFILES_DIR", tmp_path):
            result = render_health()
            assert result == ""

    def test_degraded_returns_status(self, tmp_path):
        health_file = tmp_path / "health-history.jsonl"
        from datetime import UTC, datetime

        health_file.write_text(
            json.dumps(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "status": "degraded",
                    "healthy": 97,
                    "degraded": 3,
                    "failed": 1,
                    "failed_checks": ["docker.redis"],
                }
            )
        )
        with patch("agents._config.PROFILES_DIR", tmp_path):
            result = render_health()
            assert "degraded" in result
            assert "redis" in result

    def test_missing_file_returns_empty(self):
        with patch("agents._config.PROFILES_DIR", Path("/nonexistent")):
            assert render_health() == ""


class TestRenderNudges:
    def test_no_nudges(self):
        import agents.hapax_daimonion.context_enrichment as mod

        mod._nudge_cache = None
        with patch("logos.data.nudges.collect_nudges", return_value=[]):
            assert render_nudges() == ""

    def test_with_nudges(self):
        import agents.hapax_daimonion.context_enrichment as mod

        mod._nudge_cache = None
        nudge = MagicMock()
        nudge.priority_label = "high"
        nudge.title = "Profile stale"
        with patch("logos.data.nudges.collect_nudges", return_value=[nudge]):
            result = render_nudges()
            assert "Open Loops" in result
            assert "Profile stale" in result

    def test_cache_reused(self):
        import agents.hapax_daimonion.context_enrichment as mod

        nudge = MagicMock()
        nudge.priority_label = "low"
        nudge.title = "Cached"
        mod._nudge_cache = [nudge]
        mod._nudge_cache_time = time.monotonic()
        # Should NOT call collect_nudges (uses cache)
        with patch("logos.data.nudges.collect_nudges") as mock:
            result = render_nudges()
            mock.assert_not_called()
            assert "Cached" in result

    def test_exception_returns_empty(self):
        import agents.hapax_daimonion.context_enrichment as mod

        mod._nudge_cache = None
        with patch("logos.data.nudges.collect_nudges", side_effect=Exception):
            assert render_nudges() == ""


class TestRenderDmn:
    def _make_buffer(self, tmp_path: Path, content: str) -> Path:
        buf = tmp_path / "buffer.txt"
        buf.write_text(content, encoding="utf-8")
        return buf

    def test_stable_buffer_compressed(self, tmp_path: Path):
        lines = "\n".join(
            f'<dmn_observation tick="{43169 + i}" age="{141 - i}s">stable</dmn_observation>'
            for i in range(18)
        )
        content = lines + "\n"
        buf = self._make_buffer(tmp_path, content)
        with patch("agents.hapax_daimonion.context_enrichment._DMN_BUFFER_PATH", buf):
            result = render_dmn()
        assert result != ""
        assert "stable" in result
        assert "18" in result
        assert "<dmn_observation" not in result
        assert len(result) < 120

    def test_changing_trajectory_shows_transitions(self, tmp_path: Path):
        obs_stable = "\n".join(
            f'<dmn_observation tick="{43169 + i}" age="{141 - i}s">stable</dmn_observation>'
            for i in range(12)
        )
        obs_elevated = "\n".join(
            f'<dmn_observation tick="{43181 + i}" age="{80 - i}s">elevated</dmn_observation>'
            for i in range(3)
        )
        obs_cautious = "\n".join(
            f'<dmn_observation tick="{43184 + i}" age="{50 - i}s">cautious</dmn_observation>'
            for i in range(2)
        )
        eval_line = (
            '<dmn_evaluation tick="43186" age="44s">'
            " Trajectory: declining. Concerns: resource_pressure </dmn_evaluation>"
        )
        content = "\n".join([obs_stable, obs_elevated, obs_cautious, eval_line]) + "\n"
        buf = self._make_buffer(tmp_path, content)
        with patch("agents.hapax_daimonion.context_enrichment._DMN_BUFFER_PATH", buf):
            result = render_dmn()
        assert "stable" in result
        assert "elevated" in result
        assert "cautious" in result
        assert "resource_pressure" in result

    def test_empty_buffer_returns_empty(self, tmp_path: Path):
        buf = self._make_buffer(tmp_path, "")
        with patch("agents.hapax_daimonion.context_enrichment._DMN_BUFFER_PATH", buf):
            result = render_dmn()
        assert result == ""

    def test_stale_buffer_returns_empty(self, tmp_path: Path):
        buf = self._make_buffer(
            tmp_path, "<dmn_observation tick='1' age='1s'>stable</dmn_observation>"
        )
        stale_time = time.time() - 120
        os.utime(buf, (stale_time, stale_time))
        with patch("agents.hapax_daimonion.context_enrichment._DMN_BUFFER_PATH", buf):
            result = render_dmn()
        assert result == ""
