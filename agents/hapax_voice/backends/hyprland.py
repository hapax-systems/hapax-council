"""Hyprland perception backend — active window class via hyprctl.

Only provides `active_window_class`, consumed by context_gate for
fullscreen app detection. Desktop topology (title, workspace, window
count) is handled by the event-driven update_desktop_state() path.
"""

from __future__ import annotations

import json
import logging
import subprocess

from agents.hapax_voice.perception import PerceptionTier
from agents.hapax_voice.primitives import Behavior

log = logging.getLogger(__name__)


class HyprlandBackend:
    """PerceptionBackend that reads active window class from Hyprland.

    Provides:
      - active_window_class: str
    """

    def __init__(self) -> None:
        self._b_class: Behavior[str] = Behavior("")

    @property
    def name(self) -> str:
        return "hyprland"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset({"active_window_class"})

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
        """Poll active window class from Hyprland."""
        import time

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
        except Exception as exc:
            log.debug("Failed to poll Hyprland: %s", exc)

        behaviors["active_window_class"] = self._b_class

    def start(self) -> None:
        log.info("Hyprland backend started")

    def stop(self) -> None:
        log.info("Hyprland backend stopped")
