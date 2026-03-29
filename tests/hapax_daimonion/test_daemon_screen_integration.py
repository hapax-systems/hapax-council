from unittest.mock import patch

from agents.hapax_daimonion.config import DaimonionConfig
from agents.hapax_daimonion.persona import screen_context_block
from agents.hapax_daimonion.screen_models import Issue, ScreenAnalysis


def test_daimonion_config_has_screen_fields():
    config = DaimonionConfig()
    assert config.screen_monitor_enabled is True
    assert config.screen_poll_interval_s == 2
    assert config.screen_capture_cooldown_s == 10
    assert config.screen_proactive_min_confidence == 0.8
    assert config.screen_proactive_cooldown_s == 300
    assert config.screen_recapture_idle_s == 60


def test_daimonion_config_screen_disabled():
    config = DaimonionConfig(screen_monitor_enabled=False)
    assert config.screen_monitor_enabled is False


def test_screen_context_block_none():
    assert screen_context_block(None) == ""


def test_screen_context_block_with_analysis():
    analysis = ScreenAnalysis(
        app="foot",
        context="Running pytest",
        summary="Test output visible.",
        issues=[Issue(severity="error", description="3 tests failed", confidence=0.92)],
        suggestions=[],
        keywords=[],
    )
    result = screen_context_block(analysis)
    assert "foot" in result
    assert "Running pytest" in result
    assert "[error] 3 tests failed" in result
    assert "0.92" in result


def test_screen_context_block_no_issues():
    analysis = ScreenAnalysis(
        app="Chrome",
        context="Browsing",
        summary="Web page.",
        issues=[],
        suggestions=[],
        keywords=[],
    )
    result = screen_context_block(analysis)
    assert "Chrome" in result
    assert "Issues:" not in result


def test_daimonion_config_has_webcam_fields():
    from agents.hapax_daimonion.config import DaimonionConfig

    cfg = DaimonionConfig()
    assert cfg.webcam_enabled is True
    assert "BRIO" in cfg.webcam_brio_device
    assert "C920" in cfg.webcam_c920_device
    assert cfg.webcam_capture_width == 1280
    assert cfg.webcam_capture_height == 720
    assert cfg.presence_face_detection is True
    assert cfg.presence_face_interval_s == 8.0
    assert cfg.workspace_analysis_cadence_s == 45.0
    assert cfg.timelapse_enabled is False


def test_workspace_context_block_with_gear():
    from agents.hapax_daimonion.persona import screen_context_block
    from agents.hapax_daimonion.screen_models import GearObservation, WorkspaceAnalysis

    analysis = WorkspaceAnalysis(
        app="foot",
        context="running build",
        summary="Build in progress.",
        operator_present=True,
        operator_activity="typing",
        operator_attention="screen",
        gear_state=[
            GearObservation(
                device="MPC Live III", powered=True, display_content="Song mode", notes=""
            ),
        ],
    )
    result = screen_context_block(analysis)
    assert "MPC Live III" in result
    assert "typing" in result
    assert "Operator:" in result or "operator" in result.lower()


def test_daemon_creates_workspace_monitor():
    """VoiceDaemon should use WorkspaceMonitor with camera configs."""
    from agents.hapax_daimonion.config import DaimonionConfig

    cfg = DaimonionConfig(screen_monitor_enabled=True, webcam_enabled=True)

    with patch("agents.hapax_daimonion.__main__.WorkspaceMonitor") as mock_wm:
        from agents.hapax_daimonion.__main__ import VoiceDaemon

        VoiceDaemon(cfg=cfg)
        # Should have created a workspace monitor with camera configs
        assert mock_wm.called


def test_daemon_creates_event_log():
    """VoiceDaemon should create EventLog."""
    from unittest.mock import patch

    from agents.hapax_daimonion.config import DaimonionConfig

    cfg = DaimonionConfig(
        screen_monitor_enabled=False,
        webcam_enabled=False,
    )
    with (
        patch("agents.hapax_daimonion.__main__.HotkeyServer"),
        patch("agents.hapax_daimonion.__main__.WakeWordDetector"),
        patch("agents.hapax_daimonion.__main__.TTSManager"),
    ):
        from agents.hapax_daimonion.__main__ import VoiceDaemon

        daemon = VoiceDaemon(cfg=cfg)
        assert hasattr(daemon, "event_log")
        assert daemon.event_log is not None


def test_daemon_wires_event_log_to_subsystems():
    from unittest.mock import patch

    from agents.hapax_daimonion.config import DaimonionConfig

    cfg = DaimonionConfig(
        screen_monitor_enabled=False,
        webcam_enabled=False,
    )
    with (
        patch("agents.hapax_daimonion.__main__.HotkeyServer"),
        patch("agents.hapax_daimonion.__main__.WakeWordDetector"),
        patch("agents.hapax_daimonion.__main__.TTSManager"),
    ):
        from agents.hapax_daimonion.__main__ import VoiceDaemon

        daemon = VoiceDaemon(cfg=cfg)
        assert daemon.presence._event_log is daemon.event_log
        assert daemon.gate._event_log is daemon.event_log
        assert daemon.notifications._event_log is daemon.event_log
        assert daemon.workspace_monitor._event_log is daemon.event_log
        assert daemon.workspace_monitor._tracer is daemon.tracer
