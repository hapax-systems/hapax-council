"""Shared fixtures and markers for hapax_daimonion tests."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Stub hardware/ML C-extension modules that aren't in the test venv.
# These must be injected before any hapax_daimonion module is imported,
# so that `from agents.hapax_daimonion.__main__ import VoiceDaemon` works
# without pyaudio, pipecat, torch, or openwakeword installed.


class _StubFunctionSchema:
    """Stub for pipecat.adapters.schemas.function_schema.FunctionSchema."""

    def __init__(self, *, name="", description="", properties=None, required=None):
        self.name = name
        self.description = description
        self.properties = properties or {}
        self.required = required or []


class _StubToolsSchema:
    """Stub for pipecat.adapters.schemas.tools_schema.ToolsSchema."""

    def __init__(self, standard_tools=None, **kwargs):
        self.standard_tools = standard_tools or []


class _StubFrame:
    pass


class _StubAudioRawFrame(_StubFrame):
    pass


class _StubFrameDirection:
    DOWNSTREAM = "downstream"
    UPSTREAM = "upstream"


class _StubFrameProcessor:
    def __init__(self, **kwargs):
        pass

    async def push_frame(self, frame, direction):
        pass


def _stub_hardware_modules():
    """Register MagicMock stubs for all hardware/ML modules.

    For pipecat, we register every intermediate submodule path so Python's
    import system can resolve `from pipecat.x.y.z import Foo`. The leaf
    modules for frames and processors use real stub classes so FrameGate
    can inherit from FrameProcessor and be tested normally.
    """
    # All pipecat submodule paths used in agents/hapax_daimonion/
    _pipecat_leaves = [
        "pipecat.adapters.schemas.function_schema",
        "pipecat.adapters.schemas.tools_schema",
        "pipecat.audio.vad.silero",
        "pipecat.frames.frames",
        "pipecat.pipeline.pipeline",
        "pipecat.pipeline.runner",
        "pipecat.pipeline.task",
        "pipecat.processors.aggregators.llm_context",
        "pipecat.processors.aggregators.llm_response_universal",
        "pipecat.processors.frame_processor",
        "pipecat.services.openai.llm",
        "pipecat.services.tts_service",
        "pipecat.services.whisper.stt",
        "pipecat.transports.local.audio",
    ]

    # Build set of all intermediate paths (pipecat, pipecat.frames, etc.)
    all_paths: set[str] = set()
    for leaf in _pipecat_leaves:
        parts = leaf.split(".")
        for i in range(1, len(parts) + 1):
            all_paths.add(".".join(parts[:i]))

    # Register a MagicMock for each path not already loaded
    for path in sorted(all_paths):
        if path not in sys.modules:
            sys.modules[path] = MagicMock()

    # Override specific leaf modules with real stub classes so that
    # FrameGate(FrameProcessor) can be instantiated in tests.
    frames_mod = sys.modules["pipecat.frames.frames"]
    frames_mod.Frame = _StubFrame
    frames_mod.AudioRawFrame = _StubAudioRawFrame

    fp_mod = sys.modules["pipecat.processors.frame_processor"]
    fp_mod.FrameProcessor = _StubFrameProcessor
    fp_mod.FrameDirection = _StubFrameDirection

    fs_mod = sys.modules["pipecat.adapters.schemas.function_schema"]
    fs_mod.FunctionSchema = _StubFunctionSchema

    ts_mod = sys.modules["pipecat.adapters.schemas.tools_schema"]
    ts_mod.ToolsSchema = _StubToolsSchema

    # Other hardware/ML deps — simple MagicMock stubs
    for mod_name in [
        "pyaudio",
        "torch",
        "torchaudio",
        "openwakeword",
        "openwakeword.model",
        "cv2",
        "insightface",
        "insightface.app",
        "insightface.app.common",
        "googleapiclient",
        "googleapiclient.discovery",
    ]:
        if mod_name not in sys.modules:
            sys.modules[mod_name] = MagicMock()


_stub_hardware_modules()


def _has_command(cmd: str) -> bool:
    """Check if a command is available on PATH."""
    try:
        subprocess.run([cmd, "--version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _has_v4l2_device() -> bool:
    """Check if any V4L2 video device exists."""
    return any(Path("/dev").glob("video*"))


def _has_display() -> bool:
    """Check if a display server is accessible."""
    import os

    return bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))


def make_stub_daemon(**overrides):
    """Create a VoiceDaemon with __init__ bypassed and all attributes stubbed.

    This avoids AttributeError from the ever-growing __init__ method.
    Tests can override any attribute via keyword arguments.
    """
    import asyncio

    from agents.hapax_daimonion.__main__ import VoiceDaemon

    daemon = object.__new__(VoiceDaemon)

    # Core state
    daemon._running = False
    daemon._background_tasks = []
    daemon._pipeline_task = None
    daemon._gemini_session = None
    daemon._loop = None

    # Config
    daemon.cfg = MagicMock()
    daemon.cfg.ntfy_topic = ""
    daemon.cfg.backend = "local"
    daemon.cfg.audio_input_source = "echo_cancel_capture"
    daemon.cfg.silence_timeout_s = 30
    daemon.cfg.presence_window_minutes = 5
    daemon.cfg.presence_vad_threshold = 0.5
    daemon.cfg.context_gate_volume_threshold = 0.5
    daemon.cfg.screen_monitor_enabled = False
    daemon.cfg.webcam_enabled = False
    daemon.cfg.chime_enabled = False
    daemon.cfg.mc_enabled = False
    daemon.cfg.obs_enabled = False
    daemon.cfg.salience_enabled = False
    daemon.cfg.aec_enabled = False
    daemon.cfg.voxtral_voice_id = "jessica"
    daemon.cfg.perception_tier = "full"
    daemon.cfg.local_stt_model = "distil-large-v3"

    # Subsystems
    daemon.session = MagicMock()
    daemon.session.is_active = False
    daemon.presence = MagicMock()
    daemon.presence.process_audio_frame.return_value = 0.5
    daemon.presence._latest_vad_confidence = 0.5
    daemon.gate = MagicMock()
    daemon.notifications = MagicMock()
    daemon.notifications.pending_count = 0
    daemon.hotkey = MagicMock()
    daemon.wake_word = MagicMock()
    daemon.wake_word.frame_length = 1280
    daemon.tts = MagicMock()
    daemon.chime_player = MagicMock()
    daemon.workspace_monitor = MagicMock()
    daemon.workspace_monitor.run = MagicMock()
    daemon.workspace_monitor.latest_analysis = None
    daemon.event_log = MagicMock()
    daemon.tracer = MagicMock()
    daemon.perception = MagicMock()
    daemon.governor = MagicMock()

    # Audio
    daemon._audio_input = MagicMock()
    daemon._audio_input.is_active = True
    daemon._echo_canceller = None
    daemon._noise_reference = None
    daemon._audio_preprocessor = None
    daemon._conversation_buffer = MagicMock()
    daemon._conversation_buffer.is_active = False

    # Consent / governance
    daemon.consent_registry = MagicMock()
    daemon._operator_principal = MagicMock()
    daemon._daemon_principal = MagicMock()
    daemon.consent_tracker = MagicMock()
    daemon._consent_session_active = False

    # Pipeline
    daemon._conversation_pipeline = None
    daemon._resident_stt = MagicMock()
    daemon._resident_stt.is_loaded = True
    daemon._bridge_engine = MagicMock()
    daemon._bridges_presynthesized = False
    daemon._cognitive_loop = None
    daemon._precompute_pipeline_deps = MagicMock()
    daemon._frame_gate = MagicMock()
    daemon._perception_tier = "full"
    daemon._wake_word_signal = asyncio.Event()

    # Salience
    daemon._salience_router = None
    daemon._salience_embedder = None
    daemon._salience_concern_graph = None
    daemon._salience_diagnostics = None
    daemon._context_distillation = ""

    # Speaker ID
    daemon._speaker_identifier = None

    # Actuation
    daemon.schedule_queue = MagicMock()
    daemon.executor_registry = MagicMock()
    daemon._shared_pa = None
    daemon.arbiter = MagicMock()
    daemon._mc_tick_event = None
    daemon._obs_tick_event = None
    daemon._midi_output = None

    # Events
    daemon.wake_word_event = MagicMock()
    daemon.focus_event = MagicMock()

    # Perception loop
    daemon._presence_engine = None

    # Apply overrides
    for key, value in overrides.items():
        setattr(daemon, key, value)

    return daemon


# Auto-skip hardware tests when hardware isn't available
def pytest_collection_modifyitems(config, items):
    """Auto-skip hardware tests when requirements aren't met."""
    skip_hw = pytest.mark.skip(reason="Hardware not available")

    def _has_real_pyaudio() -> bool:
        """Check if real (non-mocked) PyAudio is available."""
        try:
            import pyaudio

            return not isinstance(pyaudio, MagicMock) and hasattr(pyaudio, "PyAudio")
        except ImportError:
            return False

    _real_audio = _has_real_pyaudio()

    for item in items:
        if "hardware" in item.keywords:
            # Check which hardware is needed based on test name/module
            if (
                "screen" in item.name
                and not (_has_command("grim") and _has_display())
                or "webcam" in item.name
                and not (_has_v4l2_device() and _has_command("ffmpeg"))
                or "face" in item.name
                and not _has_v4l2_device()
                or "atspi" in item.name
                and not _has_display()
                or "audio" in item.module.__name__
                and not _real_audio
            ):
                item.add_marker(skip_hw)
