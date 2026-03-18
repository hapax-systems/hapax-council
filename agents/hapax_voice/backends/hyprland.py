"""Hyprland perception backend — active window class + desktop activity.

Provides `active_window_class` (for context_gate fullscreen detection)
and `desktop_active` (for Bayesian presence — window focus changed recently).
Desktop topology (title, workspace, window count) is handled by the
event-driven update_desktop_state() path.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time

from agents.hapax_voice.perception import PerceptionTier
from agents.hapax_voice.primitives import Behavior

log = logging.getLogger(__name__)

_DESKTOP_ACTIVE_WINDOW_S = 30.0  # consider desktop "active" if focus changed within 30s


class HyprlandBackend:
    """PerceptionBackend that reads active window state from Hyprland.

    Provides:
      - active_window_class: str
      - desktop_active: bool (window focus changed within 30s)
    """

    def __init__(self) -> None:
        self._b_class: Behavior[str] = Behavior("")
        self._b_desktop_active: Behavior[bool] = Behavior(False)
        self._last_window_id: int = -1
        self._last_focus_change: float = 0.0

    @property
    def name(self) -> str:
        return "hyprland"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset({"active_window_class", "desktop_active"})

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.EVENT

    def available(self) -> bool:
        """Check if hyprctl is accessible."""
        try:
            result = subprocess.run(
                ["hyprctl", "version", "-j"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        """Poll active window from Hyprland, detect focus changes."""
        now = time.monotonic()

        try:
            win_result = subprocess.run(
                ["hyprctl", "activewindow", "-j"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            win_data = json.loads(win_result.stdout) if win_result.returncode == 0 else {}
            self._b_class.update(win_data.get("class", ""), now)

            # Track focus changes by window address (unique per window)
            window_id = win_data.get("address", win_data.get("pid", -1))
            if isinstance(window_id, str):
                window_id = hash(window_id)
            if window_id != self._last_window_id and self._last_window_id != -1:
                self._last_focus_change = now
            self._last_window_id = window_id

        except Exception as exc:
            log.debug("Failed to poll Hyprland: %s", exc)

        # Desktop is "active" if window focus changed within the last 30s
        desktop_active = (now - self._last_focus_change) < _DESKTOP_ACTIVE_WINDOW_S
        self._b_desktop_active.update(desktop_active, now)

        behaviors["active_window_class"] = self._b_class
        behaviors["desktop_active"] = self._b_desktop_active

    def start(self) -> None:
        self._last_focus_change = time.monotonic()  # assume active at startup
        log.info("Hyprland backend started")

    def stop(self) -> None:
        log.info("Hyprland backend stopped")
