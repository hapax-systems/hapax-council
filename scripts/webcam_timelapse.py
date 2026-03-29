"""Periodic webcam timelapse capture."""

from __future__ import annotations

import argparse
import subprocess
import time
from datetime import datetime
from pathlib import Path

CAMERAS = {
    "operator": "/dev/v4l/by-id/usb-046d_Logitech_BRIO_5342C819-video-index0",
    "hardware": "/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_2657DFCF-video-index0",
}
DEFAULT_PATH = Path.home() / ".local" / "share" / "hapax-daimonion" / "timelapse"


def capture_frame(device: str, role: str, output_dir: Path) -> None:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    outfile = output_dir / f"{role}-{ts}.jpg"
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "v4l2",
        "-input_format",
        "mjpeg",
        "-video_size",
        "1280x720",
        "-i",
        device,
        "-frames:v",
        "1",
        "-update",
        "1",
        "-q:v",
        "5",
        str(outfile),
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=10)
    except Exception:
        pass  # fail-open


def cleanup_old(output_dir: Path, retention_days: int) -> None:
    cutoff = time.time() - (retention_days * 86400)
    for f in output_dir.glob("*.jpg"):
        if f.stat().st_mtime < cutoff:
            f.unlink()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=str, default=str(DEFAULT_PATH))
    parser.add_argument("--retention-days", type=int, default=7)
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    for role, device in CAMERAS.items():
        if Path(device).exists():
            capture_frame(device, role, output_dir)

    cleanup_old(output_dir, args.retention_days)


if __name__ == "__main__":
    main()
