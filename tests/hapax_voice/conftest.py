"""Shared fixtures and markers for hapax_voice tests."""
import subprocess
import pytest
from pathlib import Path


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
            if "screen" in item.name and not (_has_command("grim") and _has_display()):
                item.add_marker(skip_hw)
            elif "webcam" in item.name and not (_has_v4l2_device() and _has_command("ffmpeg")):
                item.add_marker(skip_hw)
            elif "face" in item.name and not _has_v4l2_device():
                item.add_marker(skip_hw)
            elif "atspi" in item.name and not _has_display():
                item.add_marker(skip_hw)
