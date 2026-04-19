"""KDEConnect phone-push bridge runtime.

Polls KDEConnect for inbound text messages, parses them via
``grammar.parse``, throttles, dispatches ``command`` results to the
Tauri command-relay WebSocket, appends ``sidechat`` results to the
compositor side-channel JSONL, and ACKs back to the phone.

The module is deliberately structured so all external surfaces
(``kdeconnect-cli`` invocation, WS connect, sidechat filesystem path,
clock) are injection seams with safe defaults — tests drive the
pipeline synchronously without touching the network or filesystem.
"""

from __future__ import annotations

import asyncio
import collections
import json
import logging
import shutil
import subprocess
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared.operator_sidechat import (
    SIDECHAT_PATH,
)
from shared.operator_sidechat import (
    append_sidechat as _append_operator_sidechat,
)

from .grammar import Parsed, parse

log = logging.getLogger(__name__)

DEFAULT_RELAY_URL = "ws://127.0.0.1:8052/ws/commands"
DEFAULT_SIDECHAT_PATH = SIDECHAT_PATH
DEFAULT_WINDOW_S = 0.250
DEFAULT_BURST = 4

CommandDispatcher = Callable[[str, dict[str, Any]], Awaitable[None]]
AckSender = Callable[[str], None]
Clock = Callable[[], float]
MessageSource = Callable[[], Iterable[str]]


@dataclass(frozen=True)
class DispatchResult:
    """Outcome of handling a single phone-push message.

    Primarily used by tests to make assertions about the bridge's
    behavior without threading a mock recorder through every seam.
    """

    parsed: Parsed
    dispatched: bool
    reason: str = ""


class BurstThrottle:
    """Sliding-window burst throttle for phone-push messages.

    Accepts ``burst`` messages per ``window`` seconds; anything beyond
    is reported to the caller so it can ACK back with a throttle
    notice rather than silently dropping. This is operator self-
    protection (fat-fingered repeats), not anti-abuse — the axiom
    governance explicitly forbids abuse-prevention scaffolding.
    """

    def __init__(
        self,
        *,
        burst: int = DEFAULT_BURST,
        window: float = DEFAULT_WINDOW_S,
        clock: Clock | None = None,
    ) -> None:
        self._burst = burst
        self._window = window
        self._clock = clock or time.monotonic
        self._events: collections.deque[float] = collections.deque()

    def allow(self) -> bool:
        now = self._clock()
        cutoff = now - self._window
        while self._events and self._events[0] < cutoff:
            self._events.popleft()
        if len(self._events) >= self._burst:
            return False
        self._events.append(now)
        return True


def append_sidechat(
    text: str, *, path: Path = DEFAULT_SIDECHAT_PATH, clock: Clock | None = None
) -> None:
    """Append a single sidechat record via ``shared.operator_sidechat``.

    Delegates to the canonical task-#132 producer (O_APPEND, Pydantic-
    validated record, 2000-char cap) so phone-pushed messages land in
    the same JSONL daimonion already consumes. ``clock`` is honored for
    tests that need deterministic timestamps.
    """
    ts = (clock or time.time)()
    _append_operator_sidechat(text, ts=ts, role="operator", path=path)


async def websocket_dispatcher(
    command: str,
    args: dict[str, Any],
    *,
    url: str = DEFAULT_RELAY_URL,
    connect: Callable[[str], Any] | None = None,
) -> None:
    """Post a single ``execute`` message to the Tauri command-relay WS.

    Parallels ``agents.streamdeck_adapter.adapter.websocket_dispatcher``
    — one-shot connect-send-close per press. The relay owns auth and
    retries; the bridge stays crash-simple.
    """
    if connect is None:
        import websockets  # lazy import so tests do not need the dep

        connect = websockets.connect  # type: ignore[assignment]

    payload = json.dumps({"type": "execute", "command": command, "args": args})
    async with await connect(url) as ws:
        await ws.send(payload)


def kdeconnect_available() -> bool:
    """Return True if ``kdeconnect-cli`` is on PATH."""
    return shutil.which("kdeconnect-cli") is not None


def make_kdeconnect_ack() -> AckSender:
    """Return an ACK sender that pings back via ``kdeconnect-cli``.

    Falls back to a no-op (with a log line) when the binary is missing
    so tests and degraded hosts do not crash.
    """

    def _ack(message: str) -> None:
        if not kdeconnect_available():
            log.debug("kdeconnect-cli absent - skipping ACK %r", message)
            return
        try:
            subprocess.run(
                ["kdeconnect-cli", "--send-ping", "--ping-msg", message],
                check=False,
                capture_output=True,
                timeout=2.0,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            log.warning("kdeconnect-cli ACK failed: %s", exc)

    return _ack


class Bridge:
    """Bridge core used by tests and ``__main__``.

    Holds the throttle and pre-wired seams. A single call to
    ``handle`` parses a message, applies the throttle, and fires the
    correct side effect (WS dispatch, sidechat write, or ACK-only for
    unknown commands).
    """

    def __init__(
        self,
        *,
        dispatcher: CommandDispatcher,
        ack: AckSender | None = None,
        sidechat_path: Path = DEFAULT_SIDECHAT_PATH,
        throttle: BurstThrottle | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._ack = ack or (lambda _msg: None)
        self._sidechat_path = sidechat_path
        self._throttle = throttle or BurstThrottle(clock=clock)
        self._clock = clock or time.time

    async def handle(self, message: str) -> DispatchResult:
        parsed = parse(message)

        if parsed.kind == "unknown":
            self._ack(f"ERR: {parsed.error}")
            return DispatchResult(parsed=parsed, dispatched=False, reason=parsed.error)

        if not self._throttle.allow():
            self._ack("ERR: throttled")
            return DispatchResult(parsed=parsed, dispatched=False, reason="throttled")

        if parsed.kind == "sidechat":
            append_sidechat(parsed.sidechat_text, path=self._sidechat_path, clock=self._clock)
            self._ack(f"OK: sidechat ({len(parsed.sidechat_text)} chars)")
            return DispatchResult(parsed=parsed, dispatched=True)

        # parsed.kind == "command"
        try:
            await self._dispatcher(parsed.command, dict(parsed.args))
        except Exception as exc:  # noqa: BLE001 - surface every dispatch failure uniformly
            log.exception("dispatch failed for %s", parsed.command)
            self._ack(f"ERR: dispatch failed ({exc})")
            return DispatchResult(parsed=parsed, dispatched=False, reason=f"dispatch:{exc}")

        self._ack(f"OK: {parsed.command}")
        return DispatchResult(parsed=parsed, dispatched=True)


def _poll_kdeconnect_cli() -> Iterable[str]:
    """Default message source - wrap ``kdeconnect-cli`` output.

    KDEConnect does not expose a clean "stream inbound text" CLI; the
    production deployment reads the DBus notification interface. To
    avoid a hard runtime dep on ``pydbus`` this helper shells out to
    ``kdeconnect-cli --list-notifications`` on each poll and yields
    new notification bodies. Absent the binary, yield nothing and let
    the caller exit cleanly.
    """
    if not kdeconnect_available():
        return
    try:
        result = subprocess.run(
            ["kdeconnect-cli", "--list-notifications"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log.warning("kdeconnect-cli poll failed: %s", exc)
        return
    for line in result.stdout.splitlines():
        line = line.strip()
        if line:
            yield line


async def run_bridge(
    *,
    source: MessageSource | None = None,
    dispatcher: CommandDispatcher | None = None,
    ack: AckSender | None = None,
    poll_interval: float = 0.5,
    sidechat_path: Path = DEFAULT_SIDECHAT_PATH,
) -> None:
    """Long-running service loop.

    Degrades gracefully: if ``kdeconnect-cli`` is absent and the caller
    did not supply a custom source, log a single warning and return -
    systemd will treat the exit as a success and not restart-flap.
    """
    if dispatcher is None:

        async def _default_dispatcher(command: str, args: dict[str, Any]) -> None:
            await websocket_dispatcher(command, args)

        dispatcher = _default_dispatcher

    if source is None:
        if not kdeconnect_available():
            log.warning("kdeconnect-cli absent - bridge exiting in degraded mode")
            return
        source = _poll_kdeconnect_cli

    bridge = Bridge(
        dispatcher=dispatcher,
        ack=ack or make_kdeconnect_ack(),
        sidechat_path=sidechat_path,
    )

    seen: set[str] = set()
    while True:
        for msg in source():
            if msg in seen:
                continue
            seen.add(msg)
            await bridge.handle(msg)
        await asyncio.sleep(poll_interval)
