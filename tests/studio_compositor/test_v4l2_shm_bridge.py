from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.studio_compositor.v4l2_shm_bridge import BridgeConfig, ShmToV4l2Bridge


def _bridge(tmp_path: Path) -> ShmToV4l2Bridge:
    gst = MagicMock()
    glib = MagicMock()
    config = BridgeConfig(
        device=str(tmp_path / "video42"),
        socket_path=str(tmp_path / "bridge.sock"),
        width=1280,
        height=720,
        fps=30,
        wait_seconds=1,
        metrics_path=tmp_path / "bridge.prom",
    )
    return ShmToV4l2Bridge(config, gst, glib)


def test_bridge_config_declares_nv12_caps(tmp_path: Path) -> None:
    config = BridgeConfig(
        device=str(tmp_path / "video42"),
        socket_path=str(tmp_path / "bridge.sock"),
        width=1280,
        height=720,
        fps=30,
        wait_seconds=1,
        metrics_path=tmp_path / "bridge.prom",
    )

    assert config.caps == "video/x-raw,format=NV12,width=1280,height=720,framerate=30/1"


def test_write_frame_uses_existing_fd_without_copy(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    bridge._fd = 999
    payload = memoryview(bytearray(b"\x01" * 64))

    with patch("os.write", return_value=64) as write:
        assert bridge._write_frame(payload)

    write.assert_called_once()
    assert write.call_args.args[0] == 999
    assert write.call_args.args[1] is payload


def test_write_metrics_reports_heartbeat_age(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    bridge.counters.frames = 2
    bridge.counters.bytes = 128
    bridge.counters.last_frame_monotonic = 10.0

    with patch("agents.studio_compositor.v4l2_shm_bridge.time.monotonic", return_value=10.5):
        bridge._write_metrics()

    text = (tmp_path / "bridge.prom").read_text(encoding="utf-8")
    assert "hapax_v4l2_bridge_write_frames_total 2" in text
    assert "hapax_v4l2_bridge_write_bytes_total 128" in text
    assert "hapax_v4l2_bridge_heartbeat_seconds_ago 0.500000" in text


def test_open_fd_enforces_format_before_open(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    with patch(
        "agents.studio_compositor.v4l2_shm_bridge._enforce_v4l2_output_format",
        return_value=True,
    ) as guard:
        with patch("os.open", return_value=123) as open_fd:
            with patch("os.close"):
                assert bridge._open_fd()
                bridge._close_fd()

    guard.assert_called_once()
    open_fd.assert_called_once_with(str(tmp_path / "video42"), os.O_WRONLY | os.O_NONBLOCK)
