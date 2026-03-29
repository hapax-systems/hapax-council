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


# Auto-skip hardware tests when hardware isn't available
def pytest_collection_modifyitems(config, items):
    """Auto-skip hardware tests when requirements aren't met."""
    skip_hw = pytest.mark.skip(reason="Hardware not available")
    for item in items:
        if "hardware" in item.keywords:
            # Check which hardware is needed based on test name
            if (
                "screen" in item.name
                and not (_has_command("grim") and _has_display())
                or "webcam" in item.name
                and not (_has_v4l2_device() and _has_command("ffmpeg"))
                or "face" in item.name
                and not _has_v4l2_device()
                or "atspi" in item.name
                and not _has_display()
            ):
                item.add_marker(skip_hw)
