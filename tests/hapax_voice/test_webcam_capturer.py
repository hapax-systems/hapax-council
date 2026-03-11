"""Tests for WebcamCapturer."""

import base64
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.hapax_voice.screen_models import CameraConfig
from agents.hapax_voice.webcam_capturer import WebcamCapturer


def test_capturer_init_with_cameras():
    cameras = [
        CameraConfig(device="/dev/video0", role="operator"),
        CameraConfig(device="/dev/video4", role="hardware"),
    ]
    cap = WebcamCapturer(cameras=cameras)
    assert cap.has_camera("operator")
    assert cap.has_camera("hardware")
    assert not cap.has_camera("ir")


def test_capturer_returns_none_for_missing_role():
    cap = WebcamCapturer(cameras=[])
    assert cap.capture("operator") is None


def test_capturer_respects_cooldown():
    cameras = [CameraConfig(device="/dev/video0", role="operator")]
    cap = WebcamCapturer(cameras=cameras, cooldown_s=60.0)
    # Simulate a recent capture
    cap._last_capture_time["operator"] = time.monotonic()
    assert cap.capture("operator") is None


def test_capturer_returns_base64_on_success(tmp_path):
    cameras = [CameraConfig(device="/dev/video0", role="operator")]
    cap = WebcamCapturer(cameras=cameras, cooldown_s=0)

    fake_jpg = b"\xff\xd8\xff\xe0fake-jpeg-data"
    fake_file = tmp_path / "frame.jpg"
    fake_file.write_bytes(fake_jpg)

    with (
        patch("agents.hapax_voice.webcam_capturer.subprocess.run") as mock_run,
        patch("agents.hapax_voice.webcam_capturer.tempfile.mkdtemp", return_value=str(tmp_path)),
        patch.object(Path, "exists", return_value=True),
    ):
        mock_run.return_value = MagicMock(returncode=0)
        result = cap.capture("operator")

    assert result is not None
    decoded = base64.b64decode(result)
    assert decoded == fake_jpg


def test_capturer_returns_none_on_ffmpeg_failure():
    cameras = [CameraConfig(device="/dev/video0", role="operator")]
    cap = WebcamCapturer(cameras=cameras, cooldown_s=0)

    with (
        patch("agents.hapax_voice.webcam_capturer.subprocess.run") as mock_run,
        patch.object(Path, "exists", return_value=True),
    ):
        mock_run.return_value = MagicMock(returncode=1)
        result = cap.capture("operator")

    assert result is None


def test_capturer_returns_none_on_missing_device():
    cameras = [CameraConfig(device="/dev/video_nonexistent", role="operator")]
    cap = WebcamCapturer(cameras=cameras, cooldown_s=0)
    result = cap.capture("operator")
    assert result is None


def test_capturer_reset_cooldown():
    cameras = [CameraConfig(device="/dev/video0", role="operator")]
    cap = WebcamCapturer(cameras=cameras, cooldown_s=60.0)
    cap._last_capture_time["operator"] = time.monotonic()
    cap.reset_cooldown("operator")
    assert cap._last_capture_time["operator"] == 0.0


# --- Failure-mode tests ---


def test_capturer_handles_ffmpeg_timeout():
    """subprocess.TimeoutExpired from ffmpeg returns None."""
    cameras = [CameraConfig(device="/dev/video0", role="operator")]
    cap = WebcamCapturer(cameras=cameras, cooldown_s=0)

    with (
        patch(
            "agents.hapax_voice.webcam_capturer.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=10),
        ),
        patch.object(Path, "exists", return_value=True),
        patch(
            "agents.hapax_voice.webcam_capturer.tempfile.mkdtemp", return_value="/tmp/fake-webcam"
        ),
    ):
        result = cap.capture("operator")

    assert result is None


def test_capturer_handles_ffmpeg_not_found():
    """FileNotFoundError when ffmpeg is not installed returns None."""
    cameras = [CameraConfig(device="/dev/video0", role="operator")]
    cap = WebcamCapturer(cameras=cameras, cooldown_s=0)

    with (
        patch(
            "agents.hapax_voice.webcam_capturer.subprocess.run",
            side_effect=FileNotFoundError("ffmpeg not found"),
        ),
        patch.object(Path, "exists", return_value=True),
        patch(
            "agents.hapax_voice.webcam_capturer.tempfile.mkdtemp", return_value="/tmp/fake-webcam"
        ),
    ):
        result = cap.capture("operator")

    assert result is None


def test_capturer_cooldown_not_updated_on_failure():
    """After failed capture, cooldown NOT updated (allows retry)."""
    cameras = [CameraConfig(device="/dev/video0", role="operator")]
    cap = WebcamCapturer(cameras=cameras, cooldown_s=10)

    with (
        patch("agents.hapax_voice.webcam_capturer.subprocess.run") as mock_run,
        patch.object(Path, "exists", return_value=True),
        patch(
            "agents.hapax_voice.webcam_capturer.tempfile.mkdtemp", return_value="/tmp/fake-webcam"
        ),
    ):
        mock_run.return_value = MagicMock(returncode=1)
        result = cap.capture("operator")

    assert result is None
    # Cooldown should NOT have been updated because _do_capture returned None
    assert cap._last_capture_time["operator"] == 0.0


def test_capturer_tmpdir_cleaned_on_ffmpeg_exception():
    """shutil.rmtree called even when ffmpeg raises."""
    cameras = [CameraConfig(device="/dev/video0", role="operator")]
    cap = WebcamCapturer(cameras=cameras, cooldown_s=0)

    with (
        patch(
            "agents.hapax_voice.webcam_capturer.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=10),
        ),
        patch.object(Path, "exists", return_value=True),
        patch(
            "agents.hapax_voice.webcam_capturer.tempfile.mkdtemp", return_value="/tmp/fake-webcam"
        ),
        patch("shutil.rmtree") as mock_rmtree,
    ):
        result = cap.capture("operator")

    assert result is None
    mock_rmtree.assert_called_once_with("/tmp/fake-webcam", ignore_errors=True)


def test_capturer_handles_empty_output_file(tmp_path):
    """frame.jpg exists but 0 bytes — returns empty base64 string."""
    cameras = [CameraConfig(device="/dev/video0", role="operator")]
    cap = WebcamCapturer(cameras=cameras, cooldown_s=0)

    empty_file = tmp_path / "frame.jpg"
    empty_file.write_bytes(b"")

    with (
        patch("agents.hapax_voice.webcam_capturer.subprocess.run") as mock_run,
        patch("agents.hapax_voice.webcam_capturer.tempfile.mkdtemp", return_value=str(tmp_path)),
        patch.object(Path, "exists", return_value=True),
    ):
        mock_run.return_value = MagicMock(returncode=0)
        result = cap.capture("operator")

    assert result is not None
    assert result == ""  # base64 of empty bytes
    assert base64.b64decode(result) == b""


def test_capturer_device_check_before_subprocess():
    """If device doesn't exist, ffmpeg is never called."""
    cameras = [CameraConfig(device="/dev/video_nonexistent", role="operator")]
    cap = WebcamCapturer(cameras=cameras, cooldown_s=0)

    with patch("agents.hapax_voice.webcam_capturer.subprocess.run") as mock_run:
        # Device path doesn't exist on disk — no need to mock Path.exists
        result = cap.capture("operator")

    assert result is None
    mock_run.assert_not_called()


def test_capturer_pixel_format_optional():
    """CameraConfig without pixel_format — ffmpeg command doesn't include -pix_fmt."""
    cameras = [CameraConfig(device="/dev/video0", role="operator", pixel_format=None)]
    cap = WebcamCapturer(cameras=cameras, cooldown_s=0)

    with (
        patch("agents.hapax_voice.webcam_capturer.subprocess.run") as mock_run,
        patch.object(Path, "exists", return_value=True),
        patch(
            "agents.hapax_voice.webcam_capturer.tempfile.mkdtemp", return_value="/tmp/fake-webcam"
        ),
    ):
        mock_run.return_value = MagicMock(returncode=1)
        cap.capture("operator")

    assert mock_run.called
    cmd_args = mock_run.call_args[0][0]
    assert "-pix_fmt" not in cmd_args


def test_capturer_independent_cooldowns():
    """Verify operator and hardware cameras have independent cooldowns."""
    cameras = [
        CameraConfig(device="/dev/video0", role="operator"),
        CameraConfig(device="/dev/video4", role="hardware"),
    ]
    cap = WebcamCapturer(cameras=cameras, cooldown_s=60.0)

    # Simulate recent capture for operator only
    cap._last_capture_time["operator"] = time.monotonic()

    # operator should be on cooldown
    assert cap.capture("operator") is None

    # hardware should NOT be on cooldown (just needs device to exist)
    with (
        patch("agents.hapax_voice.webcam_capturer.subprocess.run") as mock_run,
        patch.object(Path, "exists", return_value=True),
        patch(
            "agents.hapax_voice.webcam_capturer.tempfile.mkdtemp", return_value="/tmp/fake-webcam"
        ),
    ):
        mock_run.return_value = MagicMock(returncode=1)
        # Should attempt capture (not blocked by cooldown)
        cap.capture("hardware")
        mock_run.assert_called_once()
