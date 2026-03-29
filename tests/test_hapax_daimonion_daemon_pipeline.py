"""Tests for VoiceDaemon pipeline lifecycle management."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_daimonion.config import DaimonionConfig


def _make_daemon(backend: str = "local") -> VoiceDaemon:
    """Create a VoiceDaemon with mocked subsystems for testing."""
    from agents.hapax_daimonion.__main__ import VoiceDaemon

    cfg = DaimonionConfig(
        backend=backend,
        silence_timeout_s=10,
        hotkey_socket="/tmp/test-hapax-daimonion.sock",
    )

    with (
        patch("agents.hapax_daimonion.__main__.PresenceDetector"),
        patch("agents.hapax_daimonion.__main__.ContextGate"),
        patch("agents.hapax_daimonion.__main__.HotkeyServer"),
        patch("agents.hapax_daimonion.__main__.WakeWordDetector"),
        patch("agents.hapax_daimonion.__main__.TTSManager"),
    ):
        daemon = VoiceDaemon(cfg=cfg)

    return daemon


class TestDaemonInit:
    def test_pipeline_state_initially_none(self) -> None:
        daemon = _make_daemon()
        assert daemon._pipeline_task is None
        assert daemon._gemini_session is None

    def test_backend_from_config(self) -> None:
        daemon = _make_daemon(backend="gemini")
        assert daemon.cfg.backend == "gemini"


class TestStartPipeline:
    @pytest.mark.asyncio
    async def test_local_pipeline_starts(self) -> None:
        daemon = _make_daemon(backend="local")

        mock_task = MagicMock()
        mock_transport = MagicMock()

        with (
            patch(
                "agents.hapax_daimonion.pipeline.build_pipeline_task",
                return_value=(mock_task, mock_transport),
            ) as mock_build,
            patch("pipecat.pipeline.runner.PipelineRunner") as mock_runner_cls,
        ):
            mock_runner = AsyncMock()
            mock_runner_cls.return_value = mock_runner

            await daemon._start_local_pipeline()

            mock_build.assert_called_once()
            assert daemon._pipeline_task is not None

    @pytest.mark.asyncio
    async def test_gemini_pipeline_starts(self) -> None:
        daemon = _make_daemon(backend="gemini")

        with patch("agents.hapax_daimonion.gemini_live.GeminiLiveSession") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session.is_connected = True
            mock_session_cls.return_value = mock_session

            await daemon._start_gemini_session()

            mock_session.connect.assert_called_once()
            assert daemon._gemini_session is mock_session

    @pytest.mark.asyncio
    async def test_duplicate_start_skipped(self) -> None:
        daemon = _make_daemon(backend="local")
        daemon._pipeline_task = MagicMock()  # Pretend already running

        # _start_pipeline checks _pipeline_task and returns early
        await daemon._start_pipeline()
        # If it didn't skip, it would have tried to import and build, which would fail


class TestStopPipeline:
    @pytest.mark.asyncio
    async def test_stop_local_pipeline(self) -> None:
        daemon = _make_daemon()

        # Create a real task that we can cancel
        async def _noop():
            await asyncio.sleep(999)

        real_task = asyncio.create_task(_noop())
        daemon._pipeline_task = real_task
        daemon._pipecat_task = MagicMock()
        daemon._pipecat_transport = MagicMock()

        await daemon._stop_pipeline()

        assert real_task.cancelled()
        assert daemon._pipeline_task is None
        assert daemon._pipecat_task is None

    @pytest.mark.asyncio
    async def test_stop_gemini_session(self) -> None:
        daemon = _make_daemon(backend="gemini")

        mock_session = AsyncMock()
        daemon._gemini_session = mock_session

        await daemon._stop_pipeline()

        mock_session.disconnect.assert_called_once()
        assert daemon._gemini_session is None

    @pytest.mark.asyncio
    async def test_stop_when_nothing_running(self) -> None:
        daemon = _make_daemon()
        # Should not raise
        await daemon._stop_pipeline()


class TestCloseSession:
    @pytest.mark.asyncio
    async def test_close_stops_pipeline_and_session(self) -> None:
        daemon = _make_daemon()
        daemon.session.open(trigger="test")
        assert daemon.session.is_active

        daemon._stop_pipeline = AsyncMock()

        await daemon._close_session(reason="test")

        daemon._stop_pipeline.assert_called_once()
        assert not daemon.session.is_active


class TestHotkeyIntegration:
    @pytest.mark.asyncio
    async def test_hotkey_open_starts_pipeline(self) -> None:
        daemon = _make_daemon()
        daemon._start_pipeline = AsyncMock()

        await daemon._handle_hotkey("open")

        assert daemon.session.is_active
        daemon._start_pipeline.assert_called_once()

    @pytest.mark.asyncio
    async def test_hotkey_close_stops_pipeline(self) -> None:
        daemon = _make_daemon()
        daemon.session.open(trigger="test")
        daemon._stop_pipeline = AsyncMock()

        await daemon._handle_hotkey("close")

        daemon._stop_pipeline.assert_called_once()
        assert not daemon.session.is_active

    @pytest.mark.asyncio
    async def test_hotkey_toggle_open(self) -> None:
        daemon = _make_daemon()
        daemon._start_pipeline = AsyncMock()

        await daemon._handle_hotkey("toggle")

        assert daemon.session.is_active
        daemon._start_pipeline.assert_called_once()

    @pytest.mark.asyncio
    async def test_hotkey_toggle_close(self) -> None:
        daemon = _make_daemon()
        daemon.session.open(trigger="test")
        daemon._stop_pipeline = AsyncMock()

        await daemon._handle_hotkey("toggle")

        daemon._stop_pipeline.assert_called_once()
        assert not daemon.session.is_active


class TestConfigBackendField:
    def test_default_is_local(self) -> None:
        cfg = DaimonionConfig()
        assert cfg.backend == "local"

    def test_gemini_backend(self) -> None:
        cfg = DaimonionConfig(backend="gemini")
        assert cfg.backend == "gemini"

    def test_llm_model_default(self) -> None:
        cfg = DaimonionConfig()
        assert cfg.llm_model == "claude-sonnet"


def test_daemon_creates_perception_engine():
    """VoiceDaemon initializes a PerceptionEngine."""
    from unittest.mock import MagicMock, patch

    from agents.hapax_daimonion.__main__ import VoiceDaemon
    from agents.hapax_daimonion.config import DaimonionConfig

    with (
        patch("agents.hapax_daimonion.__main__.AudioInputStream"),
        patch("agents.hapax_daimonion.__main__.WorkspaceMonitor") as MockWM,
        patch("agents.hapax_daimonion.__main__.TTSManager"),
        patch("agents.hapax_daimonion.__main__.ChimePlayer"),
        patch("agents.hapax_daimonion.__main__.EventLog"),
    ):
        MockWM.return_value.set_notification_queue = MagicMock()
        MockWM.return_value.set_presence = MagicMock()
        MockWM.return_value.set_event_log = MagicMock()
        daemon = VoiceDaemon(cfg=DaimonionConfig())
        assert hasattr(daemon, "perception")
        assert hasattr(daemon, "governor")
        assert hasattr(daemon, "_frame_gate")
