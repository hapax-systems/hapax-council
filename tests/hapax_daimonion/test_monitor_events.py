"""Tests for WorkspaceMonitor event emission (face_result, analysis_complete, analysis_failed)."""

from unittest.mock import MagicMock

from agents.hapax_daimonion.screen_models import WorkspaceAnalysis
from agents.hapax_daimonion.workspace_monitor import WorkspaceMonitor


def test_monitor_emits_analysis_complete():
    mon = WorkspaceMonitor(enabled=False)
    mock_log = MagicMock()
    mon.set_event_log(mock_log)

    analysis = WorkspaceAnalysis(
        app="VS Code",
        context="editing",
        summary="Writing code.",
        operator_present=True,
    )
    mon._emit_analysis_event(analysis, latency_ms=1200, images_sent=3)

    mock_log.emit.assert_called_once()
    call = mock_log.emit.call_args
    assert call[0][0] == "analysis_complete"
    assert call[1]["app"] == "VS Code"
    assert call[1]["latency_ms"] == 1200
    assert call[1]["images_sent"] == 3


def test_monitor_emits_analysis_failed():
    mon = WorkspaceMonitor(enabled=False)
    mock_log = MagicMock()
    mon.set_event_log(mock_log)

    mon._emit_analysis_failed("Connection timeout", latency_ms=5000)

    mock_log.emit.assert_called_once()
    call = mock_log.emit.call_args
    assert call[0][0] == "analysis_failed"
    assert call[1]["error"] == "Connection timeout"


def test_monitor_emits_face_result():
    mon = WorkspaceMonitor(enabled=False)
    mock_log = MagicMock()
    mon.set_event_log(mock_log)

    mon._emit_face_event(detected=True, count=1, latency_ms=4)

    mock_log.emit.assert_called_once()
    call = mock_log.emit.call_args
    assert call[0][0] == "face_result"
    assert call[1]["detected"] is True
    assert call[1]["count"] == 1


def test_monitor_no_event_without_log():
    mon = WorkspaceMonitor(enabled=False)
    # No event_log set — should not raise
    mon._emit_analysis_event(
        WorkspaceAnalysis(app="test", context="", summary=""),
        latency_ms=100,
        images_sent=1,
    )
    mon._emit_analysis_failed("err", latency_ms=100)
    mon._emit_face_event(detected=False, count=0, latency_ms=3)


def test_monitor_uses_otel_tracer():
    """WorkspaceMonitor uses module-level OTel tracer (no set_tracer needed)."""
    from agents.hapax_daimonion.workspace_monitor import _tracer

    assert _tracer is not None
    assert hasattr(_tracer, "start_as_current_span")
