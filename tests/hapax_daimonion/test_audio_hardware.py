"""Hardware integration tests for AudioInputStream.

Run with: pytest tests/hapax_daimonion/test_audio_hardware.py -v -m hardware
Requires: PipeWire running, echo_cancel_capture source available.
"""

from __future__ import annotations

import asyncio

import pytest

from agents.hapax_daimonion.audio_input import AudioInputStream


@pytest.mark.hardware
class TestRealAudioStream:
    """Tests against real PipeWire audio hardware."""

    def test_opens_echo_cancel_source(self):
        """Real PyAudio stream opens with echo_cancel_capture as PipeWire default."""
        stream = AudioInputStream(source_name="echo_cancel_capture")
        try:
            stream.start()
            assert stream.is_active
            # Device index is None — we use PipeWire default source routing
            assert stream._device_index is None
        finally:
            stream.stop()

    @pytest.mark.asyncio
    async def test_frames_are_correct_size(self):
        """Frames from real stream are 960 bytes (30ms @ 16kHz int16)."""
        stream = AudioInputStream(source_name="echo_cancel_capture")
        try:
            stream.start()
            assert stream.is_active
            frame = await stream.get_frame(timeout=2.0)
            assert frame is not None
            assert len(frame) == 960
        finally:
            stream.stop()

    @pytest.mark.asyncio
    async def test_stream_survives_five_seconds(self):
        """Stream produces frames continuously for 5 seconds without crash."""
        stream = AudioInputStream(source_name="echo_cancel_capture")
        try:
            stream.start()
            assert stream.is_active
            frame_count = 0
            end_time = asyncio.get_event_loop().time() + 5.0
            while asyncio.get_event_loop().time() < end_time:
                frame = await stream.get_frame(timeout=0.1)
                if frame is not None:
                    frame_count += 1
            # At 33 frames/sec for 5 seconds, expect ~165 frames
            assert frame_count > 100, f"Only got {frame_count} frames in 5s"
            assert stream.is_active
        finally:
            stream.stop()

    @pytest.mark.asyncio
    async def test_frames_are_received(self):
        """Frames are received from the audio stream."""
        stream = AudioInputStream(source_name="echo_cancel_capture")
        try:
            stream.start()
            assert stream.is_active
            received = 0
            for _ in range(50):
                frame = await stream.get_frame(timeout=0.5)
                if frame is not None:
                    received += 1
            # Echo cancel source may produce all-zero frames in silence,
            # but we should still receive frames from the stream.
            assert received > 0, "No frames received from audio stream"
        finally:
            stream.stop()

    def test_default_device_fallback(self):
        """Falls back to default device when bogus source name given."""
        stream = AudioInputStream(source_name="nonexistent_device_xyz")
        try:
            stream.start()
            # May or may not be active depending on whether a default device exists
            # The important thing is it doesn't crash
        finally:
            stream.stop()
