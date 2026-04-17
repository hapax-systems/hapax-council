"""Stream Deck adapter — turn a key press into a command-registry dispatch.

The design keeps the adapter stateless at the Python layer: every press
resolves to a ``(command, args)`` pair from the YAML key-map and is sent
verbatim to the command dispatcher. The adapter holds no studio /
compositor state of its own.

Two injection seams keep the module testable and let the systemd unit
sit idle when the hardware is absent:

* ``device_opener`` — returns a device-like object exposing
  ``set_key_callback(fn)`` and ``run()`` (real devices from the
  ``streamdeck`` library satisfy this; tests pass a fake).
* ``command_dispatcher`` — ``async def (command, args) -> None``. The
  default implementation posts a JSON message over the Tauri relay
  WebSocket; tests pass a recording stub.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .key_map import KeyBinding, KeyMap, KeyMapError, load_key_map

log = logging.getLogger(__name__)

DEFAULT_RELAY_URL = "ws://127.0.0.1:8052/ws/commands"


class _Device(Protocol):
    def set_key_callback(self, callback: Callable[[int, bool], None]) -> None: ...
    def run(self) -> None: ...


CommandDispatcher = Callable[[str, dict[str, Any]], Awaitable[None]]
DeviceOpener = Callable[[], _Device | None]


@dataclass(frozen=True)
class DispatchEvent:
    """Record of a key → command dispatch, emitted for tests and logs."""

    key: int
    command: str
    args: dict[str, Any] = field(default_factory=dict)
    label: str = ""


class StreamDeckAdapter:
    """Own the key-map and route press events to the command dispatcher."""

    def __init__(
        self,
        key_map: KeyMap,
        dispatcher: CommandDispatcher,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self._key_map = key_map
        self._dispatcher = dispatcher
        self._loop = loop
        self._events: list[DispatchEvent] = []

    @property
    def events(self) -> list[DispatchEvent]:
        """Return a copy of emitted dispatch events (primarily for tests)."""
        return list(self._events)

    def handle_key_press(self, key_index: int, pressed: bool) -> None:
        """Synchronous hook the device library calls on each transition.

        We only act on the down-edge (``pressed=True``); releases are
        ignored. When no binding is registered for the key we log and
        drop silently so the operator can grow the key-map incrementally
        without error spam.
        """
        if not pressed:
            return

        binding = self._key_map.for_key(key_index)
        if binding is None:
            log.debug("streamdeck key %d pressed with no binding", key_index)
            return

        log.info(
            "streamdeck key %d → %s args=%s",
            key_index,
            binding.command,
            binding.args,
        )
        self._events.append(
            DispatchEvent(
                key=binding.key,
                command=binding.command,
                args=dict(binding.args),
                label=binding.label,
            )
        )
        self._schedule_dispatch(binding)

    def _schedule_dispatch(self, binding: KeyBinding) -> None:
        """Fire-and-forget schedule the async dispatcher from a sync callback."""
        loop = self._loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # No running loop — run the coroutine to completion synchronously.
                asyncio.run(self._dispatcher(binding.command, dict(binding.args)))
                return
        asyncio.run_coroutine_threadsafe(
            self._dispatcher(binding.command, dict(binding.args)),
            loop,
        )


async def websocket_dispatcher(
    command: str,
    args: dict[str, Any],
    *,
    url: str = DEFAULT_RELAY_URL,
    connect: Callable[[str], Awaitable[Any]] | None = None,
) -> None:
    """Send a single ``execute`` message over the Tauri command-relay WS.

    The relay owns reconnection + auth; the adapter opens a one-shot
    connection per press, sends, and closes. Simple and crash-safe.
    """
    if connect is None:
        import websockets  # lazy import so the module can be imported in tests

        connect = websockets.connect  # type: ignore[assignment]

    payload = json.dumps({"type": "execute", "command": command, "args": args})
    async with await connect(url) as ws:
        await ws.send(payload)


def make_null_device() -> _Device:
    """Return a device that blocks forever without producing events.

    Used when hardware is absent so the systemd unit does not
    crash-loop. ``run()`` sleeps so the process stays alive for log
    observability.
    """

    class _NullDevice:
        def set_key_callback(self, callback: Callable[[int, bool], None]) -> None:
            self._callback = callback  # noqa: F841 — intentionally unused

        def run(self) -> None:
            import time

            while True:
                time.sleep(3600)

    return _NullDevice()


def run_adapter(
    key_map_path: Path,
    *,
    device_opener: DeviceOpener | None = None,
    command_dispatcher: CommandDispatcher | None = None,
) -> None:
    """Service-entrypoint loop.

    Degrades to a null device (sleep forever) when the key-map is
    unreadable or the hardware is absent; the systemd unit stays up
    so the operator can fix the config or plug in the device without
    restarting.
    """
    try:
        key_map = load_key_map(key_map_path)
    except KeyMapError:
        log.exception("streamdeck key-map unreadable at %s — running idle", key_map_path)
        key_map = KeyMap(bindings=())

    device_opener = device_opener or make_null_device
    device = device_opener()
    if device is None:
        log.warning("no streamdeck device present — running idle")
        device = make_null_device()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _default_dispatcher(command: str, args: dict[str, Any]) -> None:
        await websocket_dispatcher(command, args)

    dispatcher = command_dispatcher or _default_dispatcher
    adapter = StreamDeckAdapter(key_map, dispatcher, loop=loop)
    device.set_key_callback(adapter.handle_key_press)

    try:
        device.run()
    finally:
        loop.close()
