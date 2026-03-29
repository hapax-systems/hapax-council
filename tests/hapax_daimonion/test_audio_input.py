"""Tests for AudioInputStream — PyAudio wrapper with PipeWire source routing."""

from __future__ import annotations

import queue
from unittest.mock import MagicMock, patch

import pytest

from agents.hapax_daimonion.audio_input import AudioInputStream


def _make_stream(**kwargs):
    """Create AudioInputStream with PyAudio and subprocess mocked."""
    mock_pa = MagicMock()
    mock_pa.get_device_count.return_value = 0
    pactl_rc = kwargs.pop("pactl_rc", 0)
    pactl_stderr = kwargs.pop("pactl_stderr", b"")
    mock_result = MagicMock(returncode=pactl_rc, stderr=pactl_stderr)
    with (
        patch("agents.hapax_daimonion.audio_input.pyaudio.PyAudio", return_value=mock_pa),
        patch(
            "agents.hapax_daimonion.audio_input.subprocess.run", return_value=mock_result
        ) as mock_run,
    ):
        stream = AudioInputStream(**kwargs)
    return stream, mock_pa, mock_run


# --- PipeWire source routing ---


class TestPipeWireRouting:
    """AudioInputStream sets PipeWire default source via pactl."""

    def test_sets_default_source_on_init(self):
        """Calls pactl set-default-source with the requested source name."""
        _, _, mock_run = _make_stream(source_name="echo_cancel_capture")
        mock_run.assert_called_once_with(
            ["pactl", "set-default-source", "echo_cancel_capture"],
            capture_output=True,
            timeout=5,
        )

    def test_device_index_is_none_on_success(self):
        """Uses PyAudio default device (None) after setting PipeWire source."""
        stream, _, _ = _make_stream(source_name="echo_cancel_capture")
        assert stream._device_index is None

    def test_device_index_is_none_on_pactl_failure(self):
        """Falls back to None (system default) when pactl fails."""
        stream, _, _ = _make_stream(
            source_name="echo_cancel_capture",
            pactl_rc=1,
            pactl_stderr=b"No such entity",
        )
        assert stream._device_index is None

    def test_device_index_none_when_pactl_missing(self):
        """Falls back to None when pactl is not installed."""
        mock_pa = MagicMock()
        mock_pa.get_device_count.return_value = 0
        with (
            patch("agents.hapax_daimonion.audio_input.pyaudio.PyAudio", return_value=mock_pa),
            patch(
                "agents.hapax_daimonion.audio_input.subprocess.run",
                side_effect=FileNotFoundError("pactl"),
            ),
        ):
            stream = AudioInputStream(source_name="echo_cancel_capture")
        assert stream._device_index is None


# --- Frame queue ---


class TestFrameQueue:
    """Callback writes frames to queue, get_frame() retrieves them."""

    def test_callback_enqueues_frame(self):
        """PyAudio callback writes audio data to internal queue."""
        stream, _, _ = _make_stream()
        audio_data = b"\x00" * 960
        result = stream._pyaudio_callback(audio_data, 480, {}, 0)
        assert result[1] == 0  # pyaudio.paContinue = 0
        assert stream._queue.get_nowait() == audio_data

    def test_callback_drops_frame_when_queue_full(self):
        """Callback drops frames when queue is full instead of blocking."""
        stream, _, _ = _make_stream()
        stream._queue = queue.Queue(maxsize=2)
        stream._queue.put(b"a")
        stream._queue.put(b"b")
        result = stream._pyaudio_callback(b"c", 480, {}, 0)
        assert result[1] == 0
        assert stream._queue.qsize() == 2

    @pytest.mark.asyncio
    async def test_get_frame_returns_bytes(self):
        """get_frame() returns bytes from the queue."""
        stream, _, _ = _make_stream()
        stream._queue.put(b"\x01" * 960)
        frame = await stream.get_frame(timeout=0.1)
        assert frame == b"\x01" * 960

    @pytest.mark.asyncio
    async def test_get_frame_returns_none_on_timeout(self):
        """get_frame() returns None when queue is empty after timeout."""
        stream, _, _ = _make_stream()
        frame = await stream.get_frame(timeout=0.01)
        assert frame is None


# --- Lifecycle ---


class TestLifecycle:
    """Start/stop manage the PyAudio stream."""

    def test_start_opens_stream(self):
        """start() opens a PyAudio input stream in callback mode."""
        mock_pa = MagicMock()
        mock_pa.get_device_count.return_value = 0
        mock_stream = MagicMock()
        mock_pa.open.return_value = mock_stream
        mock_result = MagicMock(returncode=0)
        with (
            patch("agents.hapax_daimonion.audio_input.pyaudio.PyAudio", return_value=mock_pa),
            patch("agents.hapax_daimonion.audio_input.subprocess.run", return_value=mock_result),
        ):
            stream = AudioInputStream()
            stream.start()
            mock_pa.open.assert_called_once()
            call_kwargs = mock_pa.open.call_args[1]
            assert call_kwargs["input"] is True
            assert call_kwargs["rate"] == 16000
            assert call_kwargs["channels"] == 1
            assert call_kwargs["stream_callback"] == stream._pyaudio_callback
            assert stream.is_active is True

    def test_stop_closes_stream(self):
        """stop() closes the stream and terminates PyAudio."""
        mock_pa = MagicMock()
        mock_pa.get_device_count.return_value = 0
        mock_stream = MagicMock()
        mock_pa.open.return_value = mock_stream
        mock_result = MagicMock(returncode=0)
        with (
            patch("agents.hapax_daimonion.audio_input.pyaudio.PyAudio", return_value=mock_pa),
            patch("agents.hapax_daimonion.audio_input.subprocess.run", return_value=mock_result),
        ):
            stream = AudioInputStream()
            stream.start()
            stream.stop()
            mock_stream.stop_stream.assert_called_once()
            mock_stream.close.assert_called_once()
            mock_pa.terminate.assert_called_once()
            assert stream.is_active is False

    def test_start_idempotent(self):
        """start() called twice does not open a second stream."""
        mock_pa = MagicMock()
        mock_pa.get_device_count.return_value = 0
        mock_stream = MagicMock()
        mock_pa.open.return_value = mock_stream
        mock_result = MagicMock(returncode=0)
        with (
            patch("agents.hapax_daimonion.audio_input.pyaudio.PyAudio", return_value=mock_pa),
            patch("agents.hapax_daimonion.audio_input.subprocess.run", return_value=mock_result),
        ):
            stream = AudioInputStream()
            stream.start()
            stream.start()
            mock_pa.open.assert_called_once()

    def test_restart_after_stop(self):
        """stop() then start() reinitialises PyAudio and opens a new stream."""
        mock_pa_1 = MagicMock()
        mock_pa_1.get_device_count.return_value = 0
        mock_pa_1.open.return_value = MagicMock()
        mock_pa_2 = MagicMock()
        mock_pa_2.get_device_count.return_value = 0
        mock_pa_2.open.return_value = MagicMock()
        mock_result = MagicMock(returncode=0)
        with (
            patch(
                "agents.hapax_daimonion.audio_input.pyaudio.PyAudio",
                side_effect=[mock_pa_1, mock_pa_2],
            ),
            patch("agents.hapax_daimonion.audio_input.subprocess.run", return_value=mock_result),
        ):
            stream = AudioInputStream()
            stream.start()
            assert stream.is_active is True
            stream.stop()
            assert stream.is_active is False
            mock_pa_1.terminate.assert_called_once()
            # Restart — should create a fresh PyAudio instance
            stream.start()
            assert stream.is_active is True
            mock_pa_2.open.assert_called_once()

    def test_stop_idempotent(self):
        """stop() can be called multiple times without error."""
        stream, _, _ = _make_stream()
        stream.stop()
        stream.stop()

    def test_start_failure_sets_inactive(self):
        """If PyAudio.open() raises, is_active remains False."""
        mock_pa = MagicMock()
        mock_pa.get_device_count.return_value = 0
        mock_pa.open.side_effect = OSError("No audio device")
        mock_result = MagicMock(returncode=0)
        with (
            patch("agents.hapax_daimonion.audio_input.pyaudio.PyAudio", return_value=mock_pa),
            patch("agents.hapax_daimonion.audio_input.subprocess.run", return_value=mock_result),
        ):
            stream = AudioInputStream()
            stream.start()
            assert stream.is_active is False


# --- Frame size ---


class TestFrameSize:
    """Verify frame size calculations."""

    def test_frame_size_30ms_16khz(self):
        """30ms at 16kHz mono int16 = 480 samples = 960 bytes."""
        stream, _, _ = _make_stream(sample_rate=16000, frame_ms=30)
        assert stream.frame_samples == 480
        assert stream.frame_bytes == 960
