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
