"""Thin wrapper over Hyprland IPC for desktop state queries and actions.

All methods are fail-open: if hyprctl is unavailable (e.g. running in a
container or on a non-Hyprland system), queries return None/empty and
dispatches return False. No exceptions escape.
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)

_TIMEOUT_S = 5


@dataclass(frozen=True)
class WindowInfo:
    """Snapshot of a single Hyprland window."""
    address: str
    app_class: str
    title: str
    workspace_id: int
    pid: int
    x: int
    y: int
    width: int
    height: int
    floating: bool
    fullscreen: bool

    @classmethod
    def from_json(cls, d: dict) -> WindowInfo:
        ws = d.get("workspace", {})
        at = d.get("at", [0, 0])
        size = d.get("size", [0, 0])
        return cls(
            address=d.get("address", ""),
            app_class=d.get("class", ""),
            title=d.get("title", ""),
            workspace_id=ws.get("id", 0),
            pid=d.get("pid", 0),
            x=at[0] if len(at) > 0 else 0,
            y=at[1] if len(at) > 1 else 0,
            width=size[0] if len(size) > 0 else 0,
            height=size[1] if len(size) > 1 else 0,
            floating=d.get("floating", False),
            fullscreen=d.get("fullscreen", False),
        )


@dataclass(frozen=True)
class WorkspaceInfo:
    """Snapshot of a single Hyprland workspace."""
    id: int
    name: str
    window_count: int
    last_window_title: str
    monitor: str

    @classmethod
    def from_json(cls, d: dict) -> WorkspaceInfo:
        return cls(
            id=d.get("id", 0),
            name=d.get("name", ""),
            window_count=d.get("windows", 0),
            last_window_title=d.get("lastwindowtitle", ""),
            monitor=d.get("monitor", ""),
        )


class HyprlandIPC:
    """Fail-open Hyprland IPC client.

    All methods return sensible defaults (None, [], False) if hyprctl
    is unavailable. Safe to instantiate on any system.
    """

    def _query(self, cmd: str) -> dict | list | None:
        try:
            result = subprocess.run(
                ["hyprctl", "-j", cmd],
                capture_output=True, text=True, timeout=_TIMEOUT_S,
            )
            if result.returncode != 0:
                log.debug("hyprctl query %s returned %d", cmd, result.returncode)
                return None
            return json.loads(result.stdout)
        except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            log.debug("hyprctl query %s failed: %s", cmd, exc)
            return None

    def get_active_window(self) -> WindowInfo | None:
        data = self._query("activewindow")
        if not isinstance(data, dict) or not data.get("mapped"):
            return None
        return WindowInfo.from_json(data)

    def get_clients(self) -> list[WindowInfo]:
        data = self._query("clients")
        if not isinstance(data, list):
            return []
        return [WindowInfo.from_json(d) for d in data if d.get("mapped")]

    def get_workspaces(self) -> list[WorkspaceInfo]:
        data = self._query("workspaces")
        if not isinstance(data, list):
            return []
        return [WorkspaceInfo.from_json(d) for d in data]

    def dispatch(self, dispatcher: str, args: str = "") -> bool:
        try:
            cmd = ["hyprctl", "dispatch", dispatcher]
            if args:
                cmd.append(args)
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT_S)
            if result.returncode != 0:
                log.debug("hyprctl dispatch %s returned %d", dispatcher, result.returncode)
                return False
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            log.debug("hyprctl dispatch %s failed: %s", dispatcher, exc)
            return False

    def batch(self, commands: list[str]) -> bool:
        try:
            joined = " ; ".join(commands)
            result = subprocess.run(
                ["hyprctl", "--batch", joined],
                capture_output=True, text=True, timeout=_TIMEOUT_S,
            )
            if result.returncode != 0:
                log.debug("hyprctl batch returned %d", result.returncode)
                return False
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            log.debug("hyprctl batch failed: %s", exc)
            return False
