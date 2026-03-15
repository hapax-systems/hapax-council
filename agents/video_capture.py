"""video_capture.py — Multi-camera video capture service.

Captures video from USB cameras using ffmpeg, producing 5-minute MKV
segments. Each camera role has a configured resolution:
  - BRIO (operator cam): 1080p
  - C920 (hardware cam): 720p

Designed to run as a systemd template unit (hapax-video-cam@.service)
where the instance name is the camera role.

Tier 3 agent: no LLM calls. Pure capture service.

Usage:
    uv run python -m agents.video_capture --camera brio --device /dev/video0
    uv run python -m agents.video_capture --camera c920 --device /dev/video2
    uv run python -m agents.video_capture --list   # List available cameras
"""

from __future__ import annotations

import argparse
import logging
import signal
import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel

from shared.config import HAPAX_HOME

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

VIDEO_DIR = HAPAX_HOME / "video-recording"
SEGMENT_SECONDS = 300  # 5 minutes

# Camera role → resolution mapping
CAMERA_PROFILES: dict[str, dict] = {
    "brio": {
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "description": "Logitech BRIO — operator camera (1080p)",
    },
    "c920": {
        "width": 1280,
        "height": 720,
        "fps": 30,
        "description": "Logitech C920 — hardware camera (720p)",
    },
}


# ── Models ───────────────────────────────────────────────────────────────────


class CaptureConfig(BaseModel):
    """Configuration for a camera capture instance."""

    camera_role: str
    device_path: str
    width: int = 1920
    height: int = 1080
    fps: int = 30
    segment_seconds: int = SEGMENT_SECONDS
    output_dir: Path = VIDEO_DIR


# ── Core functions ───────────────────────────────────────────────────────────


def list_cameras() -> list[dict[str, str]]:
    """List available V4L2 camera devices."""
    cameras = []
    try:
        result = subprocess.run(
            ["v4l2-ctl", "--list-devices"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        current_name = ""
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if not stripped.startswith("/dev"):
                current_name = stripped.rstrip(":")
            else:
                cameras.append({"name": current_name, "device": stripped})
    except (FileNotFoundError, subprocess.TimeoutExpired):
        log.warning("v4l2-ctl not found, cannot list cameras")
    return cameras


def build_ffmpeg_cmd(config: CaptureConfig) -> list[str]:
    """Build the ffmpeg command for segmented capture.

    Uses V4L2 input, MJPEG preferred, segmented MKV output with
    strftime-based filenames.
    """
    output_dir = config.output_dir / config.camera_role
    output_dir.mkdir(parents=True, exist_ok=True)

    output_pattern = str(output_dir / f"cap-{config.camera_role}-%Y%m%d-%H%M%S.mkv")

    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        # Input
        "-f",
        "v4l2",
        "-input_format",
        "mjpeg",
        "-video_size",
        f"{config.width}x{config.height}",
        "-framerate",
        str(config.fps),
        "-i",
        config.device_path,
        # Encoding
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "23",
        # Segmentation
        "-f",
        "segment",
        "-segment_time",
        str(config.segment_seconds),
        "-segment_format",
        "matroska",
        "-strftime",
        "1",
        "-reset_timestamps",
        "1",
        output_pattern,
    ]


def run_capture(config: CaptureConfig) -> None:
    """Run ffmpeg capture in a subprocess, handling graceful shutdown."""
    cmd = build_ffmpeg_cmd(config)
    log.info(
        "Starting capture: %s (%dx%d@%dfps)",
        config.camera_role,
        config.width,
        config.height,
        config.fps,
    )
    log.debug("Command: %s", " ".join(cmd))

    proc = subprocess.Popen(cmd)
    _running = True

    def _signal_handler(signum, frame):
        nonlocal _running
        _running = False
        log.info("Received signal %d, stopping capture", signum)
        proc.terminate()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait(timeout=10)

    log.info("Capture stopped for %s (exit code: %d)", config.camera_role, proc.returncode)


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-camera video capture service")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--camera",
        choices=list(CAMERA_PROFILES.keys()),
        help="Camera role to capture",
    )
    group.add_argument("--list", action="store_true", help="List available cameras")
    parser.add_argument("--device", type=str, help="V4L2 device path (e.g. /dev/video0)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    from shared.log_setup import configure_logging

    configure_logging(agent="video-capture", level="DEBUG" if args.verbose else None)

    if args.list:
        cameras = list_cameras()
        if not cameras:
            print("No cameras found")
            return
        for cam in cameras:
            print(f"  {cam['device']}  {cam['name']}")
        return

    if not args.device:
        print("Error: --device is required when using --camera")
        sys.exit(1)

    profile = CAMERA_PROFILES[args.camera]
    config = CaptureConfig(
        camera_role=args.camera,
        device_path=args.device,
        width=profile["width"],
        height=profile["height"],
        fps=profile["fps"],
    )

    run_capture(config)


if __name__ == "__main__":
    main()
