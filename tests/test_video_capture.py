"""Tests for video_capture.py — multi-camera video capture service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agents.video_capture import (
    CAMERA_PROFILES,
    CaptureConfig,
    build_ffmpeg_cmd,
    list_cameras,
)


def test_camera_profiles_exist():
    assert "brio" in CAMERA_PROFILES
    assert "c920" in CAMERA_PROFILES


def test_brio_profile():
    p = CAMERA_PROFILES["brio"]
    assert p["width"] == 1920
    assert p["height"] == 1080


def test_c920_profile():
    p = CAMERA_PROFILES["c920"]
    assert p["width"] == 1280
    assert p["height"] == 720


def test_capture_config_defaults():
    config = CaptureConfig(camera_role="brio", device_path="/dev/video0")
    assert config.fps == 30
    assert config.segment_seconds == 300


def test_build_ffmpeg_cmd(tmp_path):
    config = CaptureConfig(
        camera_role="brio",
        device_path="/dev/video0",
        width=1920,
        height=1080,
        fps=30,
        output_dir=tmp_path,
    )
    cmd = build_ffmpeg_cmd(config)

    assert cmd[0] == "ffmpeg"
    assert "-f" in cmd
    assert "v4l2" in cmd
    assert "/dev/video0" in cmd
    assert "1920x1080" in cmd
    assert "segment" in cmd
    assert (tmp_path / "brio").exists()


def test_build_ffmpeg_cmd_creates_output_dir(tmp_path):
    config = CaptureConfig(
        camera_role="c920",
        device_path="/dev/video2",
        output_dir=tmp_path,
    )
    build_ffmpeg_cmd(config)
    assert (tmp_path / "c920").is_dir()


def test_list_cameras_when_v4l2_available():
    mock_result = MagicMock()
    mock_result.stdout = (
        "Logitech BRIO:\n\t/dev/video0\n\t/dev/video1\nLogitech C920:\n\t/dev/video2\n"
    )
    mock_result.returncode = 0

    with patch("agents.video_capture.subprocess.run", return_value=mock_result):
        cameras = list_cameras()

    assert len(cameras) == 3
    assert cameras[0]["name"] == "Logitech BRIO"
    assert cameras[0]["device"] == "/dev/video0"
    assert cameras[2]["name"] == "Logitech C920"


def test_list_cameras_when_not_available():
    with patch("agents.video_capture.subprocess.run", side_effect=FileNotFoundError):
        cameras = list_cameras()
    assert cameras == []


def test_ffmpeg_cmd_contains_segment_time(tmp_path):
    config = CaptureConfig(
        camera_role="brio",
        device_path="/dev/video0",
        segment_seconds=600,
        output_dir=tmp_path,
    )
    cmd = build_ffmpeg_cmd(config)
    idx = cmd.index("-segment_time")
    assert cmd[idx + 1] == "600"
