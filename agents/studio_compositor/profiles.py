"""Camera profile evaluation and application."""

from __future__ import annotations

import logging
import subprocess
from datetime import UTC, datetime

import yaml

from .config import PROFILES_CONFIG_PATH
from .models import CameraProfile, OverlayData

log = logging.getLogger(__name__)


def _time_in_range(start_str: str, end_str: str) -> bool:
    """Check if current time is within start-end range (HH:MM format)."""
    now = datetime.now(tz=UTC).astimezone()
    current = now.hour * 60 + now.minute
    sh, sm = (int(x) for x in start_str.split(":"))
    eh, em = (int(x) for x in end_str.split(":"))
    start = sh * 60 + sm
    end = eh * 60 + em
    if start <= end:
        return start <= current < end
    return current >= start or current < end


def _schedule_matches(schedule: str | None) -> bool:
    """Evaluate a schedule string."""
    if not schedule:
        return True
    if "-" in schedule and ":" in schedule:
        parts = schedule.split("-", 1)
        return _time_in_range(parts[0].strip(), parts[1].strip())
    if schedule == "night":
        return _time_in_range("20:00", "06:00")
    if schedule == "day":
        return _time_in_range("06:00", "20:00")
    return True


def _condition_matches(condition: str | None, overlay_data: OverlayData) -> bool:
    """Evaluate a condition string against current overlay/perception state."""
    if not condition:
        return True
    if "=" in condition:
        key, value = condition.split("=", 1)
        key = key.strip()
        value = value.strip()
        actual = getattr(overlay_data, key, None)
        if actual is None:
            return False
        return str(actual) == value
    return True


def evaluate_active_profile(
    profiles: list[CameraProfile], overlay_data: OverlayData
) -> CameraProfile | None:
    """Return the highest-priority matching profile, or None."""
    candidates = []
    for p in profiles:
        if _schedule_matches(p.schedule) and _condition_matches(p.condition, overlay_data):
            candidates.append(p)
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.priority, reverse=True)
    return candidates[0]


def apply_camera_profile(profile: CameraProfile) -> None:
    """Apply V4L2 controls from a camera profile via v4l2-ctl."""
    for device_role, controls in profile.cameras.items():
        ctrl_args: list[str] = []
        for field_name, value in controls.model_dump(exclude_none=True).items():
            ctrl_args.append(f"{field_name}={value}")
        if not ctrl_args:
            continue
        ctrl_str = ",".join(ctrl_args)
        cmd = ["v4l2-ctl", "-d", device_role, "--set-ctrl", ctrl_str]
        try:
            subprocess.run(cmd, capture_output=True, timeout=5, check=False)
            log.debug("Applied profile controls to %s: %s", device_role, ctrl_str)
        except Exception as exc:
            log.warning("Failed to apply v4l2 controls to %s: %s", device_role, exc)


def load_camera_profiles(config_profiles: list[CameraProfile]) -> list[CameraProfile]:
    """Load camera profiles from config or standalone file."""
    if config_profiles:
        return config_profiles
    if PROFILES_CONFIG_PATH.exists():
        try:
            data = yaml.safe_load(PROFILES_CONFIG_PATH.read_text()) or {}
            profiles_raw = data.get("profiles", [])
            return [CameraProfile(**p) for p in profiles_raw]
        except Exception as exc:
            log.warning("Failed to load camera profiles: %s", exc)
    return []
