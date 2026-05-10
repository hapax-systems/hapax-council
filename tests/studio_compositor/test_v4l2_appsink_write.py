"""Tests for v4l2 appsink+os.write output pipeline.

Covers fd management, write error recovery, and frame flow tracking
without requiring GStreamer or a v4l2loopback device.
"""

from __future__ import annotations

import errno
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agents.studio_compositor.v4l2_output_pipeline import (
    _RECOVERABLE_ERRNOS,
    V4l2OutputPipeline,
)


def _make_pipeline(**kwargs) -> V4l2OutputPipeline:
    gst = MagicMock()
    gst.PadProbeReturn.OK = 0
    gst.FlowReturn.OK = 0
    gst.MapFlags.READ = 1
    gst.State.PLAYING = 4
    gst.State.NULL = 1
    gst.StateChangeReturn.FAILURE = 0
    gst.StateChangeReturn.SUCCESS = 1
    gst.SECOND = 1_000_000_000
    defaults = {
        "gst": gst,
        "device": "/dev/video42",
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "proof_snapshot_interval_s": 0.0,
    }
    defaults.update(kwargs)
    return V4l2OutputPipeline(**defaults)


class TestFdManagement:
    def test_open_fd_succeeds(self, tmp_path: Path) -> None:
        dev = tmp_path / "fake_device"
        dev.write_bytes(b"")
        p = _make_pipeline(device=str(dev))
        assert p._open_fd()
        assert p._fd >= 0
        p._close_fd()
        assert p._fd == -1

    def test_open_fd_fails_gracefully(self) -> None:
        p = _make_pipeline(device="/dev/nonexistent_v4l2_device_xyz")
        assert not p._open_fd()
        assert p._fd == -1

    def test_close_fd_idempotent(self) -> None:
        p = _make_pipeline()
        p._fd = -1
        p._close_fd()
        assert p._fd == -1

    def test_reopen_increments_counter(self, tmp_path: Path) -> None:
        dev = tmp_path / "fake_device"
        dev.write_bytes(b"")
        p = _make_pipeline(device=str(dev))
        with patch("agents.studio_compositor.v4l2_output_pipeline._FD_REOPEN_DELAY_S", 0):
            with patch("agents.studio_compositor.v4l2_output_pipeline.time.sleep"):
                assert p._reopen_fd()
        assert p.fd_reopen_count == 1
        p._close_fd()


class TestWriteFrame:
    def test_write_succeeds(self, tmp_path: Path) -> None:
        dev = tmp_path / "fake_device"
        dev.write_bytes(b"")
        p = _make_pipeline(device=str(dev))
        p._open_fd()
        assert p._write_frame(b"\x00" * 100)
        p._close_fd()

    def test_write_fails_without_fd(self) -> None:
        p = _make_pipeline()
        assert not p._write_frame(b"\x00" * 100)

    def test_write_error_increments_counter(self) -> None:
        p = _make_pipeline()
        p._fd = 999
        with patch("os.write", side_effect=OSError(errno.EAGAIN, "Resource busy")):
            assert not p._write_frame(b"\x00" * 100)
        assert p.fd_write_error_count == 1

    def test_recoverable_errno_set(self) -> None:
        assert errno.EAGAIN in _RECOVERABLE_ERRNOS
        assert errno.EIO in _RECOVERABLE_ERRNOS
        assert errno.ENODEV in _RECOVERABLE_ERRNOS
        assert errno.ENXIO in _RECOVERABLE_ERRNOS


class TestFrameTracking:
    def test_initial_age_is_infinite(self) -> None:
        p = _make_pipeline()
        assert p.last_frame_age_seconds == float("inf")

    def test_is_alive_false_initially(self) -> None:
        p = _make_pipeline()
        assert not p.is_alive()

    def test_frame_updates_timestamp(self) -> None:
        p = _make_pipeline()
        p._last_frame_monotonic = time.monotonic()
        assert p.last_frame_age_seconds < 1.0
        assert p.is_alive()


class TestFinalEgressProofSnapshot:
    def test_writes_jpeg_from_nv12_frame(self, tmp_path: Path) -> None:
        pytest.importorskip("cv2")
        pytest.importorskip("numpy")

        target = tmp_path / "fx-snapshot.jpg"
        p = _make_pipeline(
            width=2,
            height=2,
            proof_snapshot_path=target,
            proof_snapshot_interval_s=1.0,
        )

        # 2x2 NV12 = 4 Y bytes + 2 interleaved UV bytes.
        p._write_proof_snapshot_jpeg(bytes([82, 82, 82, 82, 128, 128]))

        assert target.exists()
        assert target.read_bytes().startswith(b"\xff\xd8")

    def test_proof_snapshot_disabled_when_interval_zero(self) -> None:
        p = _make_pipeline(proof_snapshot_interval_s=0.0)
        with patch.object(p, "_write_proof_snapshot_jpeg") as writer:
            p._maybe_write_proof_snapshot(b"\x00" * 100)
        writer.assert_not_called()

    def test_successful_sample_schedules_proof_snapshot(self, tmp_path: Path) -> None:
        dev = tmp_path / "fake_device"
        dev.write_bytes(b"")
        p = _make_pipeline(device=str(dev), proof_snapshot_interval_s=1.0)
        p._open_fd()

        mock_appsink = MagicMock()
        mock_sample = MagicMock()
        mock_buf = MagicMock()
        mock_map_info = MagicMock()
        mock_map_info.data = b"\x00" * 100

        mock_appsink.emit.return_value = mock_sample
        mock_sample.get_buffer.return_value = mock_buf
        mock_buf.map.return_value = (True, mock_map_info)

        with patch.object(p, "_maybe_write_proof_snapshot") as proof:
            p._on_new_sample(mock_appsink)

        proof.assert_called_once_with(b"\x00" * 100)
        p._close_fd()

    def test_failed_v4l2_write_does_not_publish_proof_snapshot(self) -> None:
        p = _make_pipeline(proof_snapshot_interval_s=1.0)

        mock_appsink = MagicMock()
        mock_sample = MagicMock()
        mock_buf = MagicMock()
        mock_map_info = MagicMock()
        mock_map_info.data = b"\x00" * 100

        mock_appsink.emit.return_value = mock_sample
        mock_sample.get_buffer.return_value = mock_buf
        mock_buf.map.return_value = (True, mock_map_info)

        with patch.object(p, "_write_frame", return_value=False):
            with patch.object(p, "_maybe_write_proof_snapshot") as proof:
                p._on_new_sample(mock_appsink)

        proof.assert_not_called()


class TestOnNewSample:
    def test_successful_sample_updates_frame_time(self, tmp_path: Path) -> None:
        dev = tmp_path / "fake_device"
        dev.write_bytes(b"")
        frame_callback = MagicMock()
        p = _make_pipeline(device=str(dev), on_frame=frame_callback)
        p._open_fd()

        gst = p._Gst
        mock_appsink = MagicMock()
        mock_sample = MagicMock()
        mock_buf = MagicMock()
        mock_map_info = MagicMock()
        mock_map_info.data = b"\x00" * 100

        mock_appsink.emit.return_value = mock_sample
        mock_sample.get_buffer.return_value = mock_buf
        mock_buf.map.return_value = (True, mock_map_info)

        result = p._on_new_sample(mock_appsink)
        assert result == gst.FlowReturn.OK
        assert p.last_frame_age_seconds < 1.0
        frame_callback.assert_called_once()
        mock_buf.unmap.assert_called_once_with(mock_map_info)
        p._close_fd()

    def test_null_sample_returns_ok(self) -> None:
        p = _make_pipeline()
        mock_appsink = MagicMock()
        mock_appsink.emit.return_value = None
        result = p._on_new_sample(mock_appsink)
        assert result == p._Gst.FlowReturn.OK


class TestRebuild:
    def test_rebuild_property_access(self) -> None:
        p = _make_pipeline()
        assert p.fd_reopen_count == 0
        assert p.fd_write_error_count == 0
