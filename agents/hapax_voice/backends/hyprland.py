"""Hyprland perception backend — desktop state via hyprctl.

Wraps the existing PerceptionEngine.update_desktop_state() into a
PerceptionBackend that can be registered and contribute Behaviors.
"""

from __future__ import annotations

import json
import logging
import subprocess

from agents.hapax_voice.perception import PerceptionTier
from agents.hapax_voice.primitives import Behavior

log = logging.getLogger(__name__)


class HyprlandBackend:
    """PerceptionBackend that reads desktop state from Hyprland.

    Provides:
      - active_window_title: str
      - active_window_class: str
      - workspace_id: int
      - desktop_window_count: int
    """

    def __init__(self) -> None:
        self._b_title: Behavior[str] = Behavior("")
        self._b_class: Behavior[str] = Behavior("")
        self._b_workspace: Behavior[int] = Behavior(0)
        self._b_window_count: Behavior[int] = Behavior(0)

    @property
    def name(self) -> str:
        return "hyprland"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset({
            "active_window_title",
            "active_window_class",
            "workspace_id",
            "desktop_window_count",
        })

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
        """Poll Hyprland state and update behaviors."""
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

            clients_result = subprocess.run(
                ["hyprctl", "clients", "-j"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            clients = (
                json.loads(clients_result.stdout) if clients_result.returncode == 0 else []
            )

            ws_result = subprocess.run(
                ["hyprctl", "activeworkspace", "-j"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            ws_data = json.loads(ws_result.stdout) if ws_result.returncode == 0 else {}

            self._b_title.update(win_data.get("title", ""), now)
            self._b_class.update(win_data.get("class", ""), now)
            self._b_workspace.update(ws_data.get("id", 0), now)
            self._b_window_count.update(len(clients), now)

        except Exception as exc:
            log.debug("Failed to poll Hyprland: %s", exc)

        behaviors["active_window_title"] = self._b_title
        behaviors["active_window_class"] = self._b_class
        behaviors["workspace_id"] = self._b_workspace
        behaviors["desktop_window_count"] = self._b_window_count

    def start(self) -> None:
        log.info("Hyprland backend started")

    def stop(self) -> None:
        log.info("Hyprland backend stopped")
