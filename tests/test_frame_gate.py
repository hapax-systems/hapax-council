"""Tests for FrameGate Pipecat processor."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_voice.frame_gate import FrameGate


@pytest.mark.asyncio
async def test_passes_audio_on_process():
    """Audio frames pass through when directive is 'process'."""
    from pipecat.frames.frames import AudioRawFrame
    from pipecat.processors.frame_processor import FrameDirection

    gate = FrameGate()
    gate.set_directive("process")
    gate.push_frame = AsyncMock()

    frame = AudioRawFrame(audio=b"\x00" * 960, sample_rate=16000, num_channels=1)
    await gate.process_frame(frame, FrameDirection.DOWNSTREAM)

    gate.push_frame.assert_called_once_with(frame, FrameDirection.DOWNSTREAM)


@pytest.mark.asyncio
async def test_drops_audio_on_pause():
    """Audio frames are dropped when directive is 'pause'."""
    from pipecat.frames.frames import AudioRawFrame
    from pipecat.processors.frame_processor import FrameDirection

    gate = FrameGate()
    gate.set_directive("pause")
    gate.push_frame = AsyncMock()

    frame = AudioRawFrame(audio=b"\x00" * 960, sample_rate=16000, num_channels=1)
    await gate.process_frame(frame, FrameDirection.DOWNSTREAM)

    gate.push_frame.assert_not_called()


@pytest.mark.asyncio
async def test_passes_control_frames_on_pause():
    """Non-audio frames (control frames) pass through even on pause."""
    from pipecat.frames.frames import Frame, StartFrame
    from pipecat.processors.frame_processor import FrameDirection

    gate = FrameGate()
    gate.set_directive("pause")
    gate.push_frame = AsyncMock()

    frame = StartFrame()
    await gate.process_frame(frame, FrameDirection.DOWNSTREAM)

    gate.push_frame.assert_called_once()


@pytest.mark.asyncio
async def test_counts_dropped_frames():
    """Gate tracks how many frames it has dropped."""
    from pipecat.frames.frames import AudioRawFrame
    from pipecat.processors.frame_processor import FrameDirection

    gate = FrameGate()
    gate.set_directive("pause")
    gate.push_frame = AsyncMock()

    frame = AudioRawFrame(audio=b"\x00" * 960, sample_rate=16000, num_channels=1)
    await gate.process_frame(frame, FrameDirection.DOWNSTREAM)
    await gate.process_frame(frame, FrameDirection.DOWNSTREAM)

    assert gate.dropped_count == 2


def test_directive_default_is_process():
    gate = FrameGate()
    assert gate.directive == "process"
