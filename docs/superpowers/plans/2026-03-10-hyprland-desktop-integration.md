# Hyprland Desktop Integration Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace AT-SPI2 polling with Hyprland's native IPC, create a shared desktop abstraction layer, enrich the perception engine with desktop topology, add desktop action tools to the voice daemon, and optimize the workspace monitor to reduce unnecessary LLM calls.

**Architecture:** A thin `shared/hyprland.py` wrapper provides typed query/dispatch/event methods over Hyprland's Unix socket IPC. The voice daemon's `ChangeDetector` is replaced by a `HyprlandEventListener` that subscribes to Socket2 for real-time focus/window events. `EnvironmentState` gains desktop topology fields. New voice tools expose window management and app launching. The workspace monitor uses hyprctl data to skip LLM calls when deterministic answers suffice.

**Tech Stack:** Hyprland IPC (hyprctl CLI + Unix sockets), Python asyncio, pydantic-ai, Pipecat function calling

**Reference Specs:**
- Brainstorm: review findings presented in conversation (2026-03-10)
- Aesthetic design: `docs/superpowers/specs/2026-03-10-hyprland-aesthetic-design.md`
- Migration plan: `docs/superpowers/plans/2026-03-10-hyprland-migration-plan.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `shared/hyprland.py` | Create | Thin IPC wrapper: query, dispatch, batch, event listener |
| `tests/test_hyprland.py` | Create | Unit tests for IPC wrapper (mocked subprocess/sockets) |
| `agents/hapax_voice/hyprland_listener.py` | Create | Async Socket2 event listener replacing AT-SPI2 ChangeDetector |
| `tests/hapax_voice/test_hyprland_listener.py` | Create | Unit tests for event listener |
| `agents/hapax_voice/perception.py` | Modify | Add desktop topology fields to EnvironmentState |
| `tests/hapax_voice/test_perception_desktop.py` | Create | Tests for enriched EnvironmentState |
| `agents/hapax_voice/workspace_monitor.py` | Modify | Replace ChangeDetector with HyprlandEventListener, add hyprctl optimization |
| `tests/hapax_voice/test_workspace_monitor.py` | Modify | Update for new listener interface |
| `agents/hapax_voice/desktop_tools.py` | Create | Voice LLM tools: focus_window, switch_workspace, open_app, get_desktop_state |
| `tests/hapax_voice/test_desktop_tools.py` | Create | Tests for desktop tools |
| `agents/hapax_voice/tools.py` | Modify | Register desktop tools alongside existing tools |
| `agents/hapax_voice/__main__.py` | Modify | Wire HyprlandEventListener + desktop tools |
| `agents/hapax_voice/screen_change_detector.py` | Delete | Replaced by hyprland_listener.py |

---

## Chunk 1: Shared Hyprland IPC Wrapper

### Task 1: Create `shared/hyprland.py`

**Files:**
- Create: `shared/hyprland.py`
- Create: `tests/test_hyprland.py`

- [ ] **Step 1: Write failing tests for hyprctl query functions**

```python
# tests/test_hyprland.py
import json
from unittest.mock import patch, MagicMock

from shared.hyprland import (
    HyprlandIPC,
    WindowInfo,
    WorkspaceInfo,
)


class TestHyprlandQuery:
    def test_get_active_window_parses_json(self):
        fake_json = json.dumps({
            "address": "0x1234",
            "class": "foot",
            "title": "~/projects",
            "workspace": {"id": 1, "name": "1"},
            "pid": 42,
            "at": [0, 0],
            "size": [800, 600],
            "floating": False,
            "fullscreen": False,
            "mapped": True,
        })
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=fake_json, returncode=0
            )
            ipc = HyprlandIPC()
            win = ipc.get_active_window()

        assert win is not None
        assert win.app_class == "foot"
        assert win.title == "~/projects"
        assert win.workspace_id == 1
        assert win.pid == 42
        mock_run.assert_called_once_with(
            ["hyprctl", "-j", "activewindow"],
            capture_output=True, text=True, timeout=5,
        )

    def test_get_active_window_returns_none_on_error(self):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            ipc = HyprlandIPC()
            assert ipc.get_active_window() is None

    def test_get_clients_returns_list(self):
        fake_json = json.dumps([
            {
                "address": "0x1", "class": "foot", "title": "term",
                "workspace": {"id": 1, "name": "1"}, "pid": 10,
                "at": [0, 0], "size": [800, 600],
                "floating": False, "fullscreen": False, "mapped": True,
            },
            {
                "address": "0x2", "class": "google-chrome", "title": "Tab",
                "workspace": {"id": 3, "name": "3"}, "pid": 20,
                "at": [0, 0], "size": [1920, 1080],
                "floating": False, "fullscreen": False, "mapped": True,
            },
        ])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=fake_json, returncode=0
            )
            ipc = HyprlandIPC()
            clients = ipc.get_clients()

        assert len(clients) == 2
        assert clients[0].app_class == "foot"
        assert clients[1].workspace_id == 3

    def test_get_workspaces_returns_list(self):
        fake_json = json.dumps([
            {"id": 1, "name": "1", "windows": 3,
             "lastwindowtitle": "foot", "monitor": "DP-1"},
            {"id": 3, "name": "3", "windows": 1,
             "lastwindowtitle": "Chrome", "monitor": "DP-1"},
        ])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=fake_json, returncode=0
            )
            ipc = HyprlandIPC()
            workspaces = ipc.get_workspaces()

        assert len(workspaces) == 2
        assert workspaces[0].window_count == 3


class TestHyprlandDispatch:
    def test_dispatch_calls_hyprctl(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            ipc = HyprlandIPC()
            ipc.dispatch("workspace", "3")

        mock_run.assert_called_once_with(
            ["hyprctl", "dispatch", "workspace", "3"],
            capture_output=True, text=True, timeout=5,
        )

    def test_batch_sends_semicolon_joined(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            ipc = HyprlandIPC()
            ipc.batch([
                "dispatch workspace 3",
                "dispatch exec foot",
            ])

        mock_run.assert_called_once_with(
            ["hyprctl", "--batch", "dispatch workspace 3 ; dispatch exec foot"],
            capture_output=True, text=True, timeout=5,
        )

    def test_dispatch_returns_false_on_missing_hyprctl(self):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            ipc = HyprlandIPC()
            assert ipc.dispatch("workspace", "3") is False
```

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hyprland.py -v`
Expected: FAIL — `shared.hyprland` does not exist

- [ ] **Step 2: Implement `shared/hyprland.py`**

```python
# shared/hyprland.py
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
```

- [ ] **Step 3: Run tests**

Run: `cd ~/projects/ai-agents && uv run pytest tests/test_hyprland.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add shared/hyprland.py tests/test_hyprland.py
git commit -m "feat: add shared/hyprland.py IPC wrapper for desktop state and actions"
```

---

## Chunk 2: Hyprland Event Listener (Replace AT-SPI2)

### Task 2: Create `HyprlandEventListener`

**Files:**
- Create: `agents/hapax_voice/hyprland_listener.py`
- Create: `tests/hapax_voice/test_hyprland_listener.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/hapax_voice/test_hyprland_listener.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_voice.hyprland_listener import (
    HyprlandEventListener,
    FocusEvent,
)


def test_focus_event_creation():
    ev = FocusEvent(app_class="foot", title="~/projects", workspace_id=1, address="0x1")
    assert ev.app_class == "foot"


class TestEventParsing:
    def test_parse_activewindowv2(self):
        listener = HyprlandEventListener()
        ev = listener._parse_line("activewindowv2>>0x55a1c2e3f0a0")
        assert ev is not None
        assert ev[0] == "activewindowv2"
        assert ev[1] == "0x55a1c2e3f0a0"

    def test_parse_openwindow(self):
        listener = HyprlandEventListener()
        ev = listener._parse_line("openwindow>>0x1234,1,foot,~/projects")
        assert ev is not None
        assert ev[0] == "openwindow"

    def test_parse_workspace(self):
        listener = HyprlandEventListener()
        ev = listener._parse_line("workspacev2>>3,3")
        assert ev is not None
        assert ev[0] == "workspacev2"

    def test_parse_ignores_unknown(self):
        listener = HyprlandEventListener()
        ev = listener._parse_line("configreloaded>>")
        # Parsed but not an error
        assert ev is not None

    def test_parse_handles_malformed(self):
        listener = HyprlandEventListener()
        ev = listener._parse_line("garbage")
        assert ev is None


class TestDebounce:
    def test_same_focus_suppressed(self):
        listener = HyprlandEventListener(debounce_s=1.0)
        callback = MagicMock()
        listener.on_focus_changed = callback

        # Simulate two identical focus events
        listener._handle_focus_event("foot", "term", 1, "0x1")
        listener._handle_focus_event("foot", "term", 1, "0x1")
        assert callback.call_count == 1

    def test_different_focus_fires(self):
        listener = HyprlandEventListener(debounce_s=0.0)
        callback = MagicMock()
        listener.on_focus_changed = callback

        listener._handle_focus_event("foot", "term", 1, "0x1")
        listener._handle_focus_event("chrome", "tab", 3, "0x2")
        assert callback.call_count == 2

    def test_debounced_event_fires_via_pending_confirmation(self):
        """Events within debounce window are stored as pending and
        fire after debounce elapses (via _confirm_pending)."""
        listener = HyprlandEventListener(debounce_s=1.0)
        callback = MagicMock()
        listener.on_focus_changed = callback

        # First event fires immediately
        listener._handle_focus_event("foot", "term", 1, "0x1")
        assert callback.call_count == 1

        # Second event within debounce — stored as pending
        listener._handle_focus_event("chrome", "tab", 3, "0x2")
        # In sync mode (no event loop), _confirm_pending fires immediately
        # because _schedule_pending_confirmation falls through to sync path
        assert callback.call_count == 2
        last_event = callback.call_args[0][0]
        assert last_event.app_class == "chrome"


class TestProcessEvent:
    @pytest.mark.asyncio
    async def test_activewindowv2_queries_ipc(self):
        from shared.hyprland import WindowInfo

        listener = HyprlandEventListener(debounce_s=0.0)
        callback = MagicMock()
        listener.on_focus_changed = callback

        mock_win = WindowInfo(
            "0x1234", "foot", "term", 1, 42, 0, 0, 800, 600, False, False,
        )
        with patch.object(listener._ipc, "get_active_window", return_value=mock_win):
            await listener._process_event("activewindowv2", "0x1234")

        assert callback.call_count == 1
        assert callback.call_args[0][0].app_class == "foot"

    @pytest.mark.asyncio
    async def test_openwindow_calls_handler(self):
        listener = HyprlandEventListener()
        handler = MagicMock()
        listener.on_window_opened = handler

        await listener._process_event("openwindow", "0x1234,1,foot,~/projects")
        handler.assert_called_once_with("foot", "~/projects", "0x1234")

    @pytest.mark.asyncio
    async def test_closewindow_calls_handler(self):
        listener = HyprlandEventListener()
        handler = MagicMock()
        listener.on_window_closed = handler

        await listener._process_event("closewindow", "0x1234")
        handler.assert_called_once_with("0x1234")


class TestFallback:
    def test_available_false_when_no_socket(self):
        with patch.dict("os.environ", {"HYPRLAND_INSTANCE_SIGNATURE": "", "XDG_RUNTIME_DIR": ""}):
            listener = HyprlandEventListener()
            assert listener.available is False
```

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_hyprland_listener.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 2: Implement `hyprland_listener.py`**

```python
# agents/hapax_voice/hyprland_listener.py
"""Real-time Hyprland event listener replacing AT-SPI2 polling.

Connects to Hyprland Socket2 for instant window focus, open/close,
and workspace change events. Fail-open: if the socket is unavailable,
becomes a no-op (identical degradation to the old AT-SPI2 detector).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Callable

from shared.hyprland import HyprlandIPC, WindowInfo

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FocusEvent:
    """A focus change event from Hyprland."""
    app_class: str
    title: str
    workspace_id: int
    address: str


class HyprlandEventListener:
    """Async listener for Hyprland Socket2 events.

    Replaces the AT-SPI2 ChangeDetector with real-time, reliable
    event delivery. Includes debounce for rapid alt-tab bouncing.

    Fail-open: if HYPRLAND_INSTANCE_SIGNATURE is not set or the
    socket is unreachable, `available` is False and `run()` returns
    immediately.
    """

    def __init__(self, debounce_s: float = 1.0) -> None:
        self.debounce_s = debounce_s
        self.on_focus_changed: Callable[[FocusEvent], None] | None = None
        self.on_window_opened: Callable[[str, str, str], None] | None = None
        self.on_window_closed: Callable[[str], None] | None = None

        self._ipc = HyprlandIPC()
        self._current_address: str | None = None
        self._last_focus_time: float = 0.0
        self._pending_event: FocusEvent | None = None
        self._pending_timer: asyncio.TimerHandle | None = None
        self._socket_path: str | None = None

        sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        if sig and runtime:
            self._socket_path = f"{runtime}/hypr/{sig}/.socket2.sock"

    @property
    def available(self) -> bool:
        return self._socket_path is not None

    def _parse_line(self, line: str) -> tuple[str, str] | None:
        """Parse a Socket2 event line into (event_name, data)."""
        if ">>" not in line:
            return None
        event, _, data = line.partition(">>")
        return (event, data)

    def _handle_focus_event(
        self, app_class: str, title: str, workspace_id: int, address: str,
    ) -> None:
        """Process a focus change with debounce.

        Uses a pending-confirmation pattern: when events arrive within the
        debounce window, they are stored as pending. A timer fires after the
        debounce period to deliver the most recent pending event. This prevents
        event loss during rapid alt-tab bouncing while ensuring the final
        destination always fires.
        """
        if address == self._current_address:
            return  # Same window, suppress

        pending = FocusEvent(
            app_class=app_class,
            title=title,
            workspace_id=workspace_id,
            address=address,
        )

        now = time.monotonic()
        if (now - self._last_focus_time) < self.debounce_s and self._current_address is not None:
            # Within debounce window — store as pending, schedule confirmation
            self._pending_event = pending
            self._current_address = address
            self._last_focus_time = now
            self._schedule_pending_confirmation()
            return

        self._current_address = address
        self._last_focus_time = now
        self._pending_event = None
        self._fire_focus_event(pending)

    def _fire_focus_event(self, event: FocusEvent) -> None:
        """Deliver a focus event to the callback."""
        if self.on_focus_changed is not None:
            self.on_focus_changed(event)

    def _schedule_pending_confirmation(self) -> None:
        """Schedule delivery of the pending event after debounce elapses."""
        if self._pending_timer is not None:
            self._pending_timer.cancel()
        try:
            loop = asyncio.get_running_loop()
            self._pending_timer = loop.call_later(
                self.debounce_s, self._confirm_pending,
            )
        except RuntimeError:
            # No event loop (e.g. synchronous tests) — fire immediately
            self._confirm_pending()

    def _confirm_pending(self) -> None:
        """Fire the pending event if it hasn't been superseded."""
        self._pending_timer = None
        if self._pending_event is not None:
            event = self._pending_event
            self._pending_event = None
            self._last_focus_time = time.monotonic()
            self._fire_focus_event(event)

    async def _process_event(self, event_name: str, data: str) -> None:
        """Route parsed events to handlers."""
        if event_name == "activewindowv2":
            # data is just the address — query hyprctl for full info
            address = data.strip()
            win = self._ipc.get_active_window()
            if win is not None:
                self._handle_focus_event(
                    win.app_class, win.title, win.workspace_id, address,
                )
        elif event_name == "openwindow":
            # data: address,workspace_name,class,title
            parts = data.strip().split(",", 3)
            if len(parts) >= 4 and self.on_window_opened:
                self.on_window_opened(parts[2], parts[3], parts[0])
        elif event_name == "closewindow":
            address = data.strip()
            if self.on_window_closed:
                self.on_window_closed(address)

    async def run(self) -> None:
        """Connect to Socket2 and process events indefinitely.

        Reconnects on disconnection with exponential backoff.
        Returns immediately if Hyprland is not detected.
        """
        if not self.available:
            log.warning("Hyprland not detected — event listener disabled")
            # Block forever so asyncio.gather doesn't exit
            await asyncio.Event().wait()
            return

        backoff = 1.0
        while True:
            try:
                reader, _ = await asyncio.open_unix_connection(self._socket_path)
                log.info("Connected to Hyprland event socket")
                backoff = 1.0  # Reset on successful connect

                while True:
                    line = await reader.readline()
                    if not line:
                        break  # Disconnected
                    parsed = self._parse_line(line.decode().strip())
                    if parsed is not None:
                        await self._process_event(*parsed)

            except (ConnectionRefusedError, FileNotFoundError, OSError) as exc:
                log.warning("Hyprland socket error: %s — retrying in %.0fs", exc, backoff)
            except asyncio.CancelledError:
                return

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
```

- [ ] **Step 3: Run tests**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_hyprland_listener.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add agents/hapax_voice/hyprland_listener.py tests/hapax_voice/test_hyprland_listener.py
git commit -m "feat: add HyprlandEventListener replacing AT-SPI2 polling"
```

---

## Chunk 3: Enrich EnvironmentState with Desktop Topology

### Task 3: Add desktop fields to `EnvironmentState`

**Files:**
- Modify: `agents/hapax_voice/perception.py`
- Create: `tests/hapax_voice/test_perception_desktop.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/hapax_voice/test_perception_desktop.py
import time
from unittest.mock import MagicMock

from agents.hapax_voice.perception import EnvironmentState, PerceptionEngine
from shared.hyprland import WindowInfo


def test_environment_state_has_desktop_fields():
    state = EnvironmentState(timestamp=time.monotonic())
    assert state.active_window is None
    assert state.window_count == 0
    assert state.active_workspace_id == 0


def test_environment_state_with_active_window():
    win = WindowInfo(
        address="0x1", app_class="foot", title="~/projects",
        workspace_id=1, pid=42, x=0, y=0, width=800, height=600,
        floating=False, fullscreen=False,
    )
    state = EnvironmentState(
        timestamp=time.monotonic(),
        active_window=win,
        window_count=3,
        active_workspace_id=1,
    )
    assert state.active_window.app_class == "foot"
    assert state.window_count == 3


def test_perception_engine_tick_includes_desktop():
    presence = MagicMock()
    presence.latest_vad_confidence = 0.0
    presence.face_detected = False
    presence.face_count = 0

    ws_monitor = MagicMock()

    engine = PerceptionEngine(
        presence=presence,
        workspace_monitor=ws_monitor,
    )

    # Simulate hyprland data
    win = WindowInfo(
        address="0x1", app_class="foot", title="term",
        workspace_id=1, pid=1, x=0, y=0, width=800, height=600,
        floating=False, fullscreen=False,
    )
    engine.update_desktop_state(active_window=win, window_count=4, active_workspace_id=1)

    state = engine.tick()
    assert state.active_window is not None
    assert state.active_window.app_class == "foot"
    assert state.window_count == 4
```

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_perception_desktop.py -v`
Expected: FAIL — fields don't exist

- [ ] **Step 2: Add desktop fields to EnvironmentState**

In `agents/hapax_voice/perception.py`, add to `EnvironmentState`:

```python
    # Desktop topology (updated by HyprlandEventListener)
    active_window: "WindowInfo | None" = None
    window_count: int = 0
    active_workspace_id: int = 0
```

Add the import at the top (TYPE_CHECKING only):

```python
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from shared.hyprland import WindowInfo
```

Add to `PerceptionEngine`:

```python
    # Desktop state (updated by HyprlandEventListener)
    self._desktop_active_window: WindowInfo | None = None
    self._desktop_window_count: int = 0
    self._desktop_active_workspace_id: int = 0

def update_desktop_state(
    self,
    active_window: WindowInfo | None = None,
    window_count: int = 0,
    active_workspace_id: int = 0,
) -> None:
    """Update desktop topology from HyprlandEventListener."""
    self._desktop_active_window = active_window
    self._desktop_window_count = window_count
    self._desktop_active_workspace_id = active_workspace_id
```

Add these fields to the `EnvironmentState(...)` construction in `tick()`:

```python
    active_window=self._desktop_active_window,
    window_count=self._desktop_window_count,
    active_workspace_id=self._desktop_active_workspace_id,
```

- [ ] **Step 3: Run tests**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_perception_desktop.py -v`
Expected: All PASS

- [ ] **Step 4: Run existing perception-related tests for regressions**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/ -k "perception or governor or frame_gate" -v`
Expected: All PASS (new fields have defaults, existing code unchanged)

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_voice/perception.py tests/hapax_voice/test_perception_desktop.py
git commit -m "feat: add desktop topology fields to EnvironmentState"
```

---

## Chunk 4: Wire Listener into WorkspaceMonitor and Daemon

### Task 4: Replace ChangeDetector with HyprlandEventListener

**Files:**
- Modify: `agents/hapax_voice/workspace_monitor.py`
- Modify: `tests/hapax_voice/test_workspace_monitor.py`

- [ ] **Step 1: Write failing test for new listener integration**

```python
# Add to tests/hapax_voice/test_workspace_monitor.py

def test_workspace_monitor_uses_hyprland_listener():
    """WorkspaceMonitor should accept a HyprlandEventListener."""
    from unittest.mock import MagicMock, patch
    from agents.hapax_voice.workspace_monitor import WorkspaceMonitor

    with patch("agents.hapax_voice.workspace_monitor.HyprlandEventListener") as MockListener, \
         patch("agents.hapax_voice.workspace_monitor.ScreenCapturer"), \
         patch("agents.hapax_voice.workspace_monitor.WorkspaceAnalyzer"):
        mock_instance = MagicMock()
        mock_instance.available = True
        MockListener.return_value = mock_instance

        monitor = WorkspaceMonitor(enabled=True)
        # Listener should have on_focus_changed set
        assert mock_instance.on_focus_changed is not None
```

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_workspace_monitor.py::test_workspace_monitor_uses_hyprland_listener -v`
Expected: FAIL — HyprlandEventListener not imported

- [ ] **Step 2: Update WorkspaceMonitor imports and constructor**

In `agents/hapax_voice/workspace_monitor.py`:

Replace:
```python
from agents.hapax_voice.screen_change_detector import ChangeDetector, FocusState
```
With:
```python
from agents.hapax_voice.hyprland_listener import HyprlandEventListener, FocusEvent
```

Replace the `ChangeDetector` creation in `__init__`:
```python
        self._listener = HyprlandEventListener(debounce_s=1.0) if enabled else None
```

Add a public property for the listener (used by daemon wiring):
```python
    @property
    def listener(self) -> HyprlandEventListener | None:
        """Public access to the event listener for daemon-level wiring."""
        return self._listener
```

Replace the callback wiring:
```python
        if self._listener is not None:
            self._listener.on_focus_changed = self._on_focus_changed
```

Replace `_on_context_changed` with:
```python
    def _on_focus_changed(self, event: FocusEvent) -> None:
        log.info("Focus changed: %s — %s (ws:%d)", event.app_class, event.title, event.workspace_id)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._capture_and_analyze())
        except RuntimeError:
            log.debug("No event loop available for workspace capture")
```

In `run()`, replace `self._detector.poll_loop()` with `self._listener.run()`:
```python
        tasks = [
            self._listener.run(),
            _staleness_loop(),
        ]
```

In `_staleness_loop()`, replace `self._detector.poll_interval_s` with `self.recapture_idle_s`:
```python
        # Old: await asyncio.sleep(self._detector.poll_interval_s)
        await asyncio.sleep(self.recapture_idle_s)
```

And update the guard:
```python
        if not self._enabled or self._listener is None:
```

- [ ] **Step 3: Run workspace monitor tests**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_workspace_monitor.py -v`
Expected: All PASS

- [ ] **Step 4: Run full voice daemon test suite for regressions**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/ -v --timeout=60`
Expected: All pass except known pre-existing failures (tool_registration, wake_word_augmentation)

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_voice/workspace_monitor.py tests/hapax_voice/test_workspace_monitor.py
git commit -m "refactor: replace AT-SPI2 ChangeDetector with HyprlandEventListener"
```

### Task 5: Wire listener into daemon and perception engine

**Files:**
- Modify: `agents/hapax_voice/__main__.py`

- [ ] **Step 1: Update daemon to feed desktop state to perception**

In `__main__.py`, add to `VoiceDaemon.__init__()` after the perception engine creation:

```python
        # Wire Hyprland desktop state into perception
        listener = self.workspace_monitor.listener
        if listener is not None:
            ipc = listener._ipc  # Reuse the listener's IPC instance
            orig_cb = listener.on_focus_changed

            def _focus_with_perception(event):
                # Update perception with desktop state
                clients = ipc.get_clients()
                self.perception.update_desktop_state(
                    active_window=ipc.get_active_window(),
                    window_count=len(clients),
                    active_workspace_id=event.workspace_id,
                )
                # Chain to workspace monitor's capture trigger
                if orig_cb is not None:
                    orig_cb(event)

            listener.on_focus_changed = _focus_with_perception
```

- [ ] **Step 2: Run full voice daemon tests**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/ -v --timeout=60`
Expected: No new failures

- [ ] **Step 3: Commit**

```bash
git add agents/hapax_voice/__main__.py
git commit -m "feat: wire Hyprland desktop state into perception engine"
```

### Task 6: Delete AT-SPI2 change detector

**Files:**
- Delete: `agents/hapax_voice/screen_change_detector.py`
- Modify: `tests/hapax_voice/test_screen_change_detector.py` (rename/repurpose)
- Modify: `tests/hapax_voice/test_hardware_integration.py` (remove ChangeDetector ref)

- [ ] **Step 1: Check remaining imports of screen_change_detector**

Run: `grep -r "screen_change_detector\|ChangeDetector\|FocusState" agents/ tests/ --include="*.py" -l`

Expected: Only `screen_change_detector.py`, `screen_monitor.py` (legacy), `test_screen_change_detector.py`, `test_hardware_integration.py`

- [ ] **Step 2: Remove ChangeDetector from screen_monitor.py (legacy)**

`screen_monitor.py` is unused (replaced by `workspace_monitor.py`) but still imports `ChangeDetector`. Update its import to use `HyprlandEventListener` or delete the file if unused.

Check if anything imports `screen_monitor.py`:
```bash
grep -r "screen_monitor" agents/ tests/ --include="*.py" -l
```

If only tests reference it, consider deleting both `screen_monitor.py` and `test_screen_monitor.py` as dead code.

- [ ] **Step 3: Remove test_screen_change_detector.py**

The debounce behavior is now tested in `test_hyprland_listener.py`. Delete the old test file.

- [ ] **Step 4: Update test_hardware_integration.py**

Remove any `ChangeDetector` import or assertion. Replace with `HyprlandEventListener` check if needed.

- [ ] **Step 5: Delete screen_change_detector.py**

```bash
git rm agents/hapax_voice/screen_change_detector.py
git rm tests/hapax_voice/test_screen_change_detector.py
```

- [ ] **Step 6: Run full test suite**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/ -v --timeout=60`
Expected: No new failures

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: remove AT-SPI2 screen_change_detector (replaced by Hyprland IPC)"
```

---

## Chunk 5: Desktop Action Tools for Voice Daemon

### Task 7: Create `desktop_tools.py`

**Files:**
- Create: `agents/hapax_voice/desktop_tools.py`
- Create: `tests/hapax_voice/test_desktop_tools.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/hapax_voice/test_desktop_tools.py
import json
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from agents.hapax_voice.desktop_tools import (
    DESKTOP_TOOL_SCHEMAS,
    handle_focus_window,
    handle_switch_workspace,
    handle_open_app,
    handle_confirm_open_app,
    handle_get_desktop_state,
)


class TestToolSchemas:
    def test_five_desktop_tools_defined(self):
        assert len(DESKTOP_TOOL_SCHEMAS) == 5

    def test_schema_names(self):
        names = {s.name for s in DESKTOP_TOOL_SCHEMAS}
        assert names == {"focus_window", "switch_workspace", "open_app", "confirm_open_app", "get_desktop_state"}


class TestFocusWindow:
    @pytest.mark.asyncio
    async def test_focus_by_class(self):
        params = MagicMock()
        params.arguments = {"target": "google-chrome"}
        params.result_callback = AsyncMock()

        with patch("agents.hapax_voice.desktop_tools._ipc") as mock_ipc:
            mock_ipc.dispatch.return_value = True
            await handle_focus_window(params)

        mock_ipc.dispatch.assert_called_once_with("focuswindow", "class:google-chrome")
        params.result_callback.assert_awaited_once()
        result = params.result_callback.call_args[0][0]
        assert result["status"] == "focused"


class TestSwitchWorkspace:
    @pytest.mark.asyncio
    async def test_switch_to_number(self):
        params = MagicMock()
        params.arguments = {"workspace": 3}
        params.result_callback = AsyncMock()

        with patch("agents.hapax_voice.desktop_tools._ipc") as mock_ipc:
            mock_ipc.dispatch.return_value = True
            await handle_switch_workspace(params)

        mock_ipc.dispatch.assert_called_once_with("workspace", "3")


class TestOpenApp:
    @pytest.mark.asyncio
    async def test_open_returns_pending_confirmation(self):
        import agents.hapax_voice.desktop_tools as dt
        dt._pending_open = None  # Reset state

        params = MagicMock()
        params.arguments = {"command": "foot", "workspace": 2}
        params.result_callback = AsyncMock()

        await handle_open_app(params)

        result = params.result_callback.call_args[0][0]
        assert result["status"] == "pending_confirmation"
        assert dt._pending_open is not None

    @pytest.mark.asyncio
    async def test_confirm_launches_pending(self):
        import agents.hapax_voice.desktop_tools as dt
        dt._pending_open = {"command": "foot", "workspace": 2}

        params = MagicMock()
        params.arguments = {}
        params.result_callback = AsyncMock()

        with patch("agents.hapax_voice.desktop_tools._ipc") as mock_ipc:
            mock_ipc.dispatch.return_value = True
            await handle_confirm_open_app(params)

        mock_ipc.dispatch.assert_called_once_with(
            "exec", "[workspace 2 silent] foot"
        )
        assert dt._pending_open is None


class TestGetDesktopState:
    @pytest.mark.asyncio
    async def test_returns_window_list(self):
        from shared.hyprland import WindowInfo, WorkspaceInfo

        params = MagicMock()
        params.arguments = {}
        params.result_callback = AsyncMock()

        mock_clients = [
            WindowInfo("0x1", "foot", "term", 1, 10, 0, 0, 800, 600, False, False),
            WindowInfo("0x2", "chrome", "tab", 3, 20, 0, 0, 1920, 1080, False, False),
        ]
        mock_workspaces = [
            WorkspaceInfo(1, "1", 1, "foot", "DP-1"),
            WorkspaceInfo(3, "3", 1, "chrome", "DP-1"),
        ]

        with patch("agents.hapax_voice.desktop_tools._ipc") as mock_ipc:
            mock_ipc.get_clients.return_value = mock_clients
            mock_ipc.get_workspaces.return_value = mock_workspaces
            mock_ipc.get_active_window.return_value = mock_clients[0]
            await handle_get_desktop_state(params)

        result = params.result_callback.call_args[0][0]
        assert result["active_window"]["class"] == "foot"
        assert len(result["windows"]) == 2
        assert len(result["workspaces"]) == 2
```

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_desktop_tools.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 2: Implement `desktop_tools.py`**

```python
# agents/hapax_voice/desktop_tools.py
"""Desktop management tools for the voice assistant.

Exposes Hyprland window management as LLM function-calling tools:
focus_window, switch_workspace, open_app, get_desktop_state.
"""
from __future__ import annotations

import logging

from pipecat.adapters.schemas.function_schema import FunctionSchema

from shared.hyprland import HyprlandIPC

log = logging.getLogger(__name__)

_ipc = HyprlandIPC()

# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

_focus_window = FunctionSchema(
    name="focus_window",
    description=(
        "Bring a window to focus by its application name. "
        "Examples: 'google-chrome', 'foot', 'obsidian', 'code'."
    ),
    properties={
        "target": {
            "type": "string",
            "description": "Application class name to focus",
        },
    },
    required=["target"],
)

_switch_workspace = FunctionSchema(
    name="switch_workspace",
    description="Switch to a workspace by number (1-10).",
    properties={
        "workspace": {
            "type": "integer",
            "description": "Workspace number to switch to",
        },
    },
    required=["workspace"],
)

_open_app = FunctionSchema(
    name="open_app",
    description=(
        "Launch an application. Optionally place it on a specific workspace. "
        "Examples: 'foot' (terminal), 'google-chrome-stable https://example.com', "
        "'flatpak run md.obsidian.Obsidian'."
    ),
    properties={
        "command": {
            "type": "string",
            "description": "Shell command to launch the application",
        },
        "workspace": {
            "type": "integer",
            "description": "Optional workspace number to place the window on",
        },
    },
    required=["command"],
)

_confirm_open_app = FunctionSchema(
    name="confirm_open_app",
    description="Confirm a pending app launch. Call after open_app returns pending_confirmation.",
    properties={},
    required=[],
)

_get_desktop_state = FunctionSchema(
    name="get_desktop_state",
    description=(
        "Get the current desktop state: all open windows, their workspaces, "
        "and which window is focused. Use this to understand the desktop layout."
    ),
    properties={},
    required=[],
)

DESKTOP_TOOL_SCHEMAS = [_focus_window, _switch_workspace, _open_app, _confirm_open_app, _get_desktop_state]


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


async def handle_focus_window(params) -> None:
    target = params.arguments["target"]
    ok = _ipc.dispatch("focuswindow", f"class:{target}")
    status = "focused" if ok else "failed"
    await params.result_callback({"status": status, "target": target})


async def handle_switch_workspace(params) -> None:
    ws = params.arguments["workspace"]
    ok = _ipc.dispatch("workspace", str(ws))
    status = "switched" if ok else "failed"
    await params.result_callback({"status": status, "workspace": ws})


# Pending open_app commands awaiting confirmation
_pending_open: dict[str, dict] | None = None


async def handle_open_app(params) -> None:
    global _pending_open
    command = params.arguments["command"]
    workspace = params.arguments.get("workspace")

    _pending_open = {"command": command, "workspace": workspace}
    await params.result_callback({
        "status": "pending_confirmation",
        "message": f"Ready to launch: {command}. Say 'confirm' to proceed.",
    })


async def handle_confirm_open_app(params) -> None:
    global _pending_open
    if _pending_open is None:
        await params.result_callback({"status": "error", "message": "No pending app launch."})
        return

    command = _pending_open["command"]
    workspace = _pending_open["workspace"]
    _pending_open = None

    if workspace:
        ok = _ipc.dispatch("exec", f"[workspace {workspace} silent] {command}")
    else:
        ok = _ipc.dispatch("exec", command)

    status = "launched" if ok else "failed"
    await params.result_callback({"status": status, "command": command})


async def handle_get_desktop_state(params) -> None:
    active = _ipc.get_active_window()
    clients = _ipc.get_clients()
    workspaces = _ipc.get_workspaces()

    def _win_dict(w):
        return {"class": w.app_class, "title": w.title, "workspace": w.workspace_id}

    result = {
        "active_window": _win_dict(active) if active else None,
        "windows": [_win_dict(c) for c in clients],
        "workspaces": [
            {"id": ws.id, "name": ws.name, "windows": ws.window_count}
            for ws in workspaces
        ],
    }
    await params.result_callback(result)
```

- [ ] **Step 3: Run tests**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_desktop_tools.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add agents/hapax_voice/desktop_tools.py tests/hapax_voice/test_desktop_tools.py
git commit -m "feat: add desktop management tools for voice assistant"
```

### Task 8: Register desktop tools in tools.py

**Files:**
- Modify: `agents/hapax_voice/tools.py:753-786`

- [ ] **Step 1: Add imports and registration**

At the top of `tools.py`, add:
```python
from agents.hapax_voice.desktop_tools import (
    DESKTOP_TOOL_SCHEMAS,
    handle_focus_window,
    handle_switch_workspace,
    handle_open_app,
    handle_confirm_open_app,
    handle_get_desktop_state,
)
```

In `register_tool_handlers()`, after the existing 9 registrations, add:

```python
    llm.register_function("focus_window", handle_focus_window)
    llm.register_function("switch_workspace", handle_switch_workspace)
    llm.register_function("open_app", handle_open_app)
    llm.register_function("confirm_open_app", handle_confirm_open_app)
    llm.register_function("get_desktop_state", handle_get_desktop_state)

    log.info("Registered %d voice tools", 14)
```

- [ ] **Step 2: Update `get_tool_schemas()` in tools.py**

In `get_tool_schemas()` (around line 224 of `tools.py`), append the desktop schemas so the LLM can see and call them:

```python
def get_tool_schemas(guest_mode: bool = False) -> list | None:
    if guest_mode:
        return None
    return TOOL_SCHEMAS + DESKTOP_TOOL_SCHEMAS
```

This ensures `pipeline.py` passes all 13 tool schemas to `OpenAILLMContext(tools=tools)`.

- [ ] **Step 3: Run tool-related tests**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/ -k "tool" -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add agents/hapax_voice/tools.py
git commit -m "feat: register desktop tools in voice assistant tool registry"
```

---

## Chunk 6: Optimize WorkspaceMonitor with Deterministic Data

### Task 9: Add hyprctl pre-check to workspace analysis

**Files:**
- Modify: `agents/hapax_voice/workspace_monitor.py`
- Create: `tests/hapax_voice/test_workspace_monitor_optimization.py`

- [ ] **Step 1: Write failing test**

```python
# tests/hapax_voice/test_workspace_monitor_optimization.py
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from agents.hapax_voice.workspace_monitor import WorkspaceMonitor


class TestDeterministicContext:
    @pytest.mark.asyncio
    async def test_builds_window_context_from_hyprctl(self):
        """Workspace monitor should query hyprctl for window list
        and include it in the analyzer prompt."""
        from shared.hyprland import WindowInfo

        mock_clients = [
            WindowInfo("0x1", "foot", "~/projects/ai-agents", 1, 10, 0, 0, 800, 600, False, False),
            WindowInfo("0x2", "google-chrome", "cockpit-web", 3, 20, 0, 0, 1920, 1080, False, False),
        ]

        with patch("agents.hapax_voice.workspace_monitor.HyprlandIPC") as MockIPC:
            mock_ipc = MagicMock()
            mock_ipc.get_clients.return_value = mock_clients
            MockIPC.return_value = mock_ipc

            monitor = WorkspaceMonitor(enabled=True)
            context = monitor._build_deterministic_context()

        assert "foot" in context
        assert "google-chrome" in context
        assert "ai-agents" in context
```

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_workspace_monitor_optimization.py -v`
Expected: FAIL — method doesn't exist

- [ ] **Step 2: Add `_build_deterministic_context()` method**

In `workspace_monitor.py`, add:

```python
from shared.hyprland import HyprlandIPC

# In __init__:
self._hypr_ipc = HyprlandIPC() if enabled else None
```

```python
    def _build_deterministic_context(self) -> str:
        """Build workspace context string from Hyprland IPC (no LLM needed).

        This gives the LLM analyzer exact window/workspace data so it can
        focus on visual analysis (errors, code content) rather than
        identifying which apps are running.
        """
        if self._hypr_ipc is None:
            return ""
        clients = self._hypr_ipc.get_clients()
        if not clients:
            return ""
        lines = ["Open windows:"]
        for c in clients:
            lines.append(f"  - [{c.app_class}] \"{c.title}\" on workspace {c.workspace_id}")
        return "\n".join(lines)
```

- [ ] **Step 3: Pass deterministic context to analyzer**

In `_capture_and_analyze()`, before calling `self._analyzer.analyze()`, add:

```python
        # Add deterministic desktop context from Hyprland IPC
        desktop_context = self._build_deterministic_context()
        combined_context = "\n\n".join(filter(None, [desktop_context, rag_context]))
```

Then pass `combined_context` instead of `rag_context` to `extra_context=`.

- [ ] **Step 4: Run tests**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_workspace_monitor_optimization.py tests/hapax_voice/test_workspace_monitor.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_voice/workspace_monitor.py tests/hapax_voice/test_workspace_monitor_optimization.py
git commit -m "feat: inject deterministic hyprctl context into workspace analysis"
```

---

## Holistic Evaluation

### Cross-Cutting Concerns

**1. Fail-open consistency.** Every component follows the same pattern: if Hyprland is unavailable (container, test, different compositor), it degrades gracefully. `HyprlandIPC` returns `None`/`[]`/`False`. `HyprlandEventListener.available` is `False` and `run()` blocks silently. `_build_deterministic_context()` returns `""`. Desktop tools return `{"status": "failed"}`. This means:
- Tests run without Hyprland (all subprocess calls are mocked)
- The cockpit-api container (no compositor) is unaffected
- A future compositor switch only requires replacing `shared/hyprland.py`

**2. Import chain safety.** `shared/hyprland.py` has zero project imports (only stdlib). `hyprland_listener.py` imports from `shared/hyprland.py`. `desktop_tools.py` imports from `shared/hyprland.py`. `workspace_monitor.py` imports from `hyprland_listener.py`. No circular dependencies. The `EnvironmentState.active_window` field uses `TYPE_CHECKING` for the `WindowInfo` import to avoid runtime coupling.

**3. Debounce behavior preserved with pending confirmation.** The old `ChangeDetector` had a debounce mechanism with `confirm_pending()` for alt-tab bounce. `HyprlandEventListener` preserves this with a pending-confirmation pattern: events within the debounce window are stored as pending, and a timer fires after the debounce period to deliver the most recent one. This prevents event loss while still suppressing alt-tab noise. Tests cover both immediate fire and pending confirmation paths.

**4. FocusState → FocusEvent rename.** The old `FocusState` dataclass (app_name, window_title) is replaced by `FocusEvent` (app_class, title, workspace_id, address). This is richer — workspace ID and address are new. The `workspace_monitor.py` callback signature changes from `_on_context_changed(FocusState)` to `_on_focus_changed(FocusEvent)`.

**5. screen_monitor.py (legacy).** This dead file imports `ChangeDetector`. Task 6 handles its deletion or update. Check for any test that imports it.

**6. Perception engine backwards compatibility.** New fields on `EnvironmentState` all have defaults (`None`, `0`, `""`). The `governor.py` state machine doesn't reference them — it only uses `speech_detected`, `operator_present`, `conversation_detected`, and `activity_mode`. No regression risk.

**7. Tool count increase.** Voice tools go from 9 → 14. The LLM's system prompt in `persona.py` includes tool descriptions automatically via Pipecat's `ToolsSchema`. `get_tool_schemas()` is explicitly updated (Task 8 Step 2) to append `DESKTOP_TOOL_SCHEMAS`. More tools means more tokens in the system prompt — monitor for context window pressure if the LLM model has tight limits.

**8. Security: `open_app` confirmation flow.** The `open_app` tool uses a two-step confirmation pattern (like `send_sms`): the LLM calls `open_app` which stores the command as pending and returns `pending_confirmation`, then the LLM must call `confirm_open_app` to execute. This guards against STT hallucination or misinterpretation of voice commands, even though the single-operator axiom makes malicious injection unlikely.

**9. Hotkey observability gap.** Not addressed in this plan — it's low priority and orthogonal. The 4/5 hotkey scripts calling Claude directly could be addressed in a follow-up by switching `aichat` to use `litellm:` model prefix, but this is a separate concern.

**10. Event listener reconnection.** The `HyprlandEventListener.run()` method reconnects with exponential backoff on disconnection. This handles Hyprland restarts (e.g., `hyprctl reload` causes a brief socket reset). Max backoff is 30 seconds.

### Potential Issues Not Visible in Isolation

**A. `activewindowv2` fires before window properties update.** When Hyprland emits `activewindowv2>>0xADDR`, the subsequent `hyprctl -j activewindow` call might see stale data if called too quickly. Mitigation: the debounce window (default 1s) provides a natural delay. If this is insufficient, add a 50ms `await asyncio.sleep(0.05)` before the query in `_process_event`.

**B. Socket2 buffer overflow under high event rates.** Rapid workspace switching could flood the event stream. The event listener processes events sequentially. If `_process_event` (which calls `hyprctl -j activewindow`) takes too long, events queue up in the socket buffer. Mitigation: the debounce suppresses rapid re-focus, and the `hyprctl` call is fast (<5ms typical). Not a realistic concern at human interaction speeds.

**C. `_build_deterministic_context()` called on every analysis.** This adds one `hyprctl -j clients` call per analysis cycle. The call takes <5ms. The analysis cycle already takes 1-3 seconds (LLM call). Negligible overhead.

**D. ToolsSchema registration order.** Pipecat registers tools by name. `get_tool_schemas()` is updated in Task 8 Step 2 to return `TOOL_SCHEMAS + DESKTOP_TOOL_SCHEMAS`, ensuring `pipeline.py` passes all 14 schemas to the LLM context. The handler registration in `register_tool_handlers()` must still match these schemas — implementer should verify the ordering.

**E. `_staleness_loop` reference to removed `poll_interval_s`.** Task 4 Step 2 replaces `self._detector.poll_interval_s` with `self.recapture_idle_s` in the staleness loop sleep, since `HyprlandEventListener` has no polling interval.
