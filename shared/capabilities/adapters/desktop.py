"""Hyprland desktop adapter — proof-of-pattern for DesktopCapability."""

from __future__ import annotations

import json
import logging
import subprocess

from shared.capabilities.protocols import DesktopResult, HealthStatus

log = logging.getLogger(__name__)


class HyprlandDesktopAdapter:
    """DesktopCapability adapter backed by Hyprland's hyprctl CLI.

    Implements the DesktopCapability Protocol. Queries Hyprland
    compositor state via hyprctl JSON output.
    """

    @property
    def name(self) -> str:
        return "hyprland-desktop"

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

    def health(self) -> HealthStatus:
        """Check Hyprland compositor health."""
        try:
            import time

            start = time.monotonic()
            result = subprocess.run(
                ["hyprctl", "activewindow", "-j"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            latency = (time.monotonic() - start) * 1000
            if result.returncode != 0:
                return HealthStatus(
                    healthy=False,
                    message=f"hyprctl failed: {result.stderr.strip()}",
                    latency_ms=latency,
                )
            return HealthStatus(healthy=True, message="ok", latency_ms=latency)
        except Exception as e:
            return HealthStatus(healthy=False, message=str(e))

    def snapshot(self) -> DesktopResult:
        """Get current desktop state from Hyprland."""
        try:
            # Get active window
            win_result = subprocess.run(
                ["hyprctl", "activewindow", "-j"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            win_data = json.loads(win_result.stdout) if win_result.returncode == 0 else {}

            # Get window count
            clients_result = subprocess.run(
                ["hyprctl", "clients", "-j"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            clients = json.loads(clients_result.stdout) if clients_result.returncode == 0 else []

            # Get active workspace
            ws_result = subprocess.run(
                ["hyprctl", "activeworkspace", "-j"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            ws_data = json.loads(ws_result.stdout) if ws_result.returncode == 0 else {}

            return DesktopResult(
                active_window_title=win_data.get("title", ""),
                active_window_class=win_data.get("class", ""),
                workspace_id=ws_data.get("id", 0),
                window_count=len(clients),
            )
        except Exception as e:
            log.warning("Failed to snapshot desktop state: %s", e)
            return DesktopResult()
