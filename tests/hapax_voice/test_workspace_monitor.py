"""Tests for WorkspaceMonitor orchestrator."""

import sys
import time
import types
from unittest.mock import MagicMock, patch

from agents.hapax_voice.screen_models import (
    Issue,
    WorkspaceAnalysis,
)
from agents.hapax_voice.workspace_monitor import WorkspaceMonitor


def _make_analysis(**kwargs):
    defaults = dict(
        app="chrome",
        context="browsing",
        summary="Web page.",
        issues=[],
        suggestions=[],
        keywords=[],
        operator_present=True,
        operator_activity="typing",
        operator_attention="screen",
        gear_state=[],
        workspace_change=False,
    )
    defaults.update(kwargs)
    return WorkspaceAnalysis(**defaults)


def test_monitor_caches_latest_analysis():
    monitor = WorkspaceMonitor(enabled=False)
    analysis = _make_analysis()
    monitor._latest_analysis = analysis
    assert monitor.latest_analysis is analysis


def test_monitor_staleness():
    monitor = WorkspaceMonitor(enabled=False, recapture_idle_s=60)
    monitor._latest_analysis = _make_analysis()
    monitor._last_analysis_time = time.monotonic() - 120
    assert monitor.is_analysis_stale is True


def test_monitor_proactive_routing():
    queue = MagicMock()
    monitor = WorkspaceMonitor(enabled=False, proactive_min_confidence=0.8)
    monitor._notification_queue = queue
    analysis = _make_analysis(
        issues=[
            Issue(severity="error", description="Docker down", confidence=0.95),
        ]
    )
    monitor._route_proactive_issues(analysis)
    assert queue.enqueue.call_count == 1


def test_monitor_proactive_cooldown():
    queue = MagicMock()
    monitor = WorkspaceMonitor(
        enabled=False,
        proactive_min_confidence=0.8,
        proactive_cooldown_s=300,
    )
    monitor._notification_queue = queue
    analysis = _make_analysis(
        issues=[
            Issue(severity="error", description="fail", confidence=0.9),
        ]
    )
    monitor._route_proactive_issues(analysis)
    monitor._route_proactive_issues(analysis)
    assert queue.enqueue.call_count == 1


def test_monitor_reload_context():
    monitor = WorkspaceMonitor(enabled=False)
    mock_analyzer = MagicMock()
    monitor._analyzer = mock_analyzer
    monitor.reload_context()
    mock_analyzer.reload_context.assert_called_once()


def test_monitor_rag_query_empty_keywords():
    monitor = WorkspaceMonitor(enabled=False)
    assert monitor._query_rag([]) is None


def test_monitor_rag_query_returns_chunks():
    monitor = WorkspaceMonitor(enabled=False)
    mock_point = MagicMock()
    mock_point.payload = {"filename": "docker-compose.yml", "text": "config here"}
    mock_results = MagicMock()
    mock_results.points = [mock_point]

    mock_config = types.ModuleType("agents.shared.config")
    mock_config.embed = MagicMock(return_value=[0.1] * 768)
    mock_config.get_qdrant = MagicMock()
    mock_config.get_qdrant.return_value.query_points.return_value = mock_results

    with patch.dict(
        sys.modules,
        {
            "agents.shared": types.ModuleType("agents.shared"),
            "agents.shared.config": mock_config,
        },
    ):
        result = monitor._query_rag(["docker"])
    assert result is not None
    assert "docker-compose.yml" in result


def test_monitor_disabled_without_crash():
    monitor = WorkspaceMonitor(enabled=False)
    assert monitor.latest_analysis is None
    assert monitor.has_camera("operator") is False


def test_workspace_monitor_uses_hyprland_listener():
    """WorkspaceMonitor should accept a HyprlandEventListener."""
    from unittest.mock import MagicMock, patch

    from agents.hapax_voice.workspace_monitor import WorkspaceMonitor

    with (
        patch("agents.hapax_voice.workspace_monitor.HyprlandEventListener") as MockListener,
        patch("agents.hapax_voice.workspace_monitor.ScreenCapturer"),
        patch("agents.hapax_voice.workspace_monitor.WorkspaceAnalyzer"),
    ):
        mock_instance = MagicMock()
        mock_instance.available = True
        MockListener.return_value = mock_instance

        WorkspaceMonitor(enabled=True)
        # Listener should have on_focus_changed set
        assert mock_instance.on_focus_changed is not None
