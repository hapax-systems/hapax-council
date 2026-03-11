"""Tests for system readiness gate."""

from unittest.mock import AsyncMock, MagicMock, patch

from agents.demo_pipeline.readiness import ReadinessResult, check_readiness


def _make_report(healthy: int = 75, total: int = 75, failed: int = 0, degraded: int = 0):
    """Create a mock HealthReport matching the real interface."""
    report = MagicMock()
    report.healthy_count = healthy
    report.total_checks = total
    report.failed_count = failed
    report.degraded_count = degraded
    report.overall_status = "healthy" if failed == 0 else "failed"
    report.groups = []
    report.summary = f"{healthy}/{total} healthy"
    return report


class TestReadiness:
    def test_readiness_all_healthy(self):
        """All checks pass -> ready=True."""
        mock_report = _make_report()

        with (
            patch(
                "agents.health_monitor.run_checks", new_callable=AsyncMock, return_value=mock_report
            ) as mock_run,
            patch("agents.health_monitor.run_fixes", new_callable=AsyncMock, return_value=0),
            patch("urllib.request.urlopen"),
        ):
            result = check_readiness()
            assert result.ready is True
            assert result.health_score == "75/75"
            mock_run.assert_called_once()

    def test_readiness_health_failures(self):
        """Health failures -> ready=True (warnings, not blockers)."""
        mock_report = _make_report(healthy=70, total=75, failed=5)

        with (
            patch(
                "agents.health_monitor.run_checks", new_callable=AsyncMock, return_value=mock_report
            ),
            patch("agents.health_monitor.run_fixes", new_callable=AsyncMock, return_value=2),
            patch("urllib.request.urlopen"),
        ):
            result = check_readiness()
            assert result.ready is True
            assert any("failed" in w.lower() for w in result.warnings)

    def test_readiness_health_failures_no_autofix(self):
        """Health failures with auto_fix=False -> no run_fixes call."""
        mock_report = _make_report(healthy=70, total=75, failed=5)

        with (
            patch(
                "agents.health_monitor.run_checks", new_callable=AsyncMock, return_value=mock_report
            ),
            patch("agents.health_monitor.run_fixes", new_callable=AsyncMock) as mock_fixes,
            patch("urllib.request.urlopen"),
        ):
            result = check_readiness(auto_fix=False)
            assert result.ready is True
            assert any("failed" in w.lower() for w in result.warnings)
            mock_fixes.assert_not_called()

    def test_readiness_cockpit_api_down(self):
        """Cockpit API down -> ready=False."""
        mock_report = _make_report()

        def urlopen_side_effect(url, **kwargs):
            if "8051" in url:
                raise ConnectionError("Connection refused")
            return MagicMock()

        with (
            patch(
                "agents.health_monitor.run_checks", new_callable=AsyncMock, return_value=mock_report
            ),
            patch("agents.health_monitor.run_fixes", new_callable=AsyncMock, return_value=0),
            patch("urllib.request.urlopen", side_effect=urlopen_side_effect),
        ):
            result = check_readiness()
            assert result.ready is False
            assert any("8051" in i for i in result.issues)

    def test_readiness_cockpit_web_down(self):
        """Cockpit web down -> ready=False."""
        mock_report = _make_report()

        def urlopen_side_effect(url, **kwargs):
            if "5173" in url:
                raise ConnectionError("Connection refused")
            return MagicMock()

        with (
            patch(
                "agents.health_monitor.run_checks", new_callable=AsyncMock, return_value=mock_report
            ),
            patch("agents.health_monitor.run_fixes", new_callable=AsyncMock, return_value=0),
            patch("urllib.request.urlopen", side_effect=urlopen_side_effect),
        ):
            result = check_readiness()
            assert result.ready is False
            assert any("5173" in i for i in result.issues)

    def test_readiness_tts_not_required(self):
        """TTS down but not required -> still ready."""
        mock_report = _make_report()

        with (
            patch(
                "agents.health_monitor.run_checks", new_callable=AsyncMock, return_value=mock_report
            ),
            patch("agents.health_monitor.run_fixes", new_callable=AsyncMock, return_value=0),
            patch("urllib.request.urlopen"),
        ):
            result = check_readiness(require_tts=False)
            assert result.ready is True

    def test_readiness_tts_required_but_down(self):
        """TTS required but down -> ready=False."""
        mock_report = _make_report()

        def urlopen_side_effect(url, **kwargs):
            if "4123" in url:
                raise ConnectionError("Connection refused")
            return MagicMock()

        with (
            patch(
                "agents.health_monitor.run_checks", new_callable=AsyncMock, return_value=mock_report
            ),
            patch("agents.health_monitor.run_fixes", new_callable=AsyncMock, return_value=0),
            patch("urllib.request.urlopen", side_effect=urlopen_side_effect),
            patch("pathlib.Path.exists", return_value=True),
        ):
            result = check_readiness(require_tts=True)
            assert result.ready is False
            assert any("4123" in i for i in result.issues)

    def test_readiness_voice_sample_missing(self):
        """Voice sample missing -> ready=False."""
        mock_report = _make_report()

        with (
            patch(
                "agents.health_monitor.run_checks", new_callable=AsyncMock, return_value=mock_report
            ),
            patch("agents.health_monitor.run_fixes", new_callable=AsyncMock, return_value=0),
            patch("urllib.request.urlopen"),
            patch("pathlib.Path.exists", return_value=False),
        ):
            result = check_readiness(require_tts=True)
            assert result.ready is False
            assert any("voice" in i.lower() for i in result.issues)

    def test_readiness_health_monitor_unavailable(self):
        """Health monitor import failure -> warning, not issue."""
        with (
            patch(
                "agents.health_monitor.run_checks",
                new_callable=AsyncMock,
                side_effect=ImportError("no module"),
            ),
            patch("urllib.request.urlopen"),
        ):
            result = check_readiness()
            assert result.ready is True
            assert any("unavailable" in w.lower() for w in result.warnings)

    def test_readiness_on_progress_callback(self):
        """on_progress callback is invoked."""
        mock_report = _make_report()
        progress_msgs: list[str] = []

        with (
            patch(
                "agents.health_monitor.run_checks", new_callable=AsyncMock, return_value=mock_report
            ),
            patch("agents.health_monitor.run_fixes", new_callable=AsyncMock, return_value=0),
            patch("urllib.request.urlopen"),
        ):
            check_readiness(on_progress=progress_msgs.append)
            assert len(progress_msgs) > 0
            assert any("health" in m.lower() for m in progress_msgs)

    def test_readiness_result_dataclass(self):
        """ReadinessResult defaults work correctly."""
        result = ReadinessResult(ready=True)
        assert result.ready is True
        assert result.issues == []
        assert result.warnings == []
        assert result.health_report is None
        assert result.health_score == ""
        assert result.briefing_summary == ""
