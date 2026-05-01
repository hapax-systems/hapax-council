"""Awareness-digest watcher loop.

The companion to ``agents.hapax_daimonion.awareness_digest`` (which is
pure-logic, no async, no I/O). This module owns the polling loop that
subscribes the digest's trigger logic to the live working-mode and
stimmung event streams.

Runtime ownership
-----------------

The loop runs as a single async coroutine alongside the other
``run_loops_aux`` consumers (impingement, sidechat, proactive delivery).
It does NOT touch the CPAL hot path. It does NOT itself synthesize TTS
or call the LLM — it dispatches typed ``WatcherEvent`` records to a
caller-supplied handler, which is responsible for invoking the
condense + speak side-effects out of band.

This split lets the watcher stay pure-async (testable with a single
``tick_once`` helper) and keeps the daemon's voice path under separate
review. The daemon wiring lands in a follow-up that supplies
``get_mode`` / ``get_stimmung`` from ``shared.working_mode`` and
``perception_loop`` respectively.

Observability
-------------

Each dispatched event carries an ISO-8601 timestamp string in
``WatcherEvent.observed_at`` (UTC, second-precision). Handlers can
log, persist, or forward at their discretion. The watcher itself
never writes to disk — that is also the handler's responsibility.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from agents.hapax_daimonion.awareness_digest import (
    FORTRESS_MODE,
    AwarenessDigestState,
    is_entering_fortress,
    is_exiting_fortress,
    is_mode_shift,
    is_stimmung_threshold_cross,
    is_within_fortress,
    stimmung_bucket,
)

log = logging.getLogger("hapax_daimonion.awareness_digest_watcher")


WatcherEventKind = Literal[
    "mode_shift",
    "fortress_enter",
    "fortress_exit",
    "stimmung_cross",
    "suppressed_within_fortress",
]


@dataclass(frozen=True)
class WatcherEvent:
    """Typed event dispatched on each detected boundary.

    ``kind`` identifies which trigger fired:

    - ``mode_shift`` — non-fortress transition (research↔rnd).
    - ``fortress_enter`` — entering fortress mode (pre-stream digest).
    - ``fortress_exit`` — leaving fortress mode (post-stream digest).
    - ``stimmung_cross`` — stimmung bucket crossed; outside fortress.
    - ``suppressed_within_fortress`` — stimmung crossed but within
      fortress; emitted as an audit signal (handler should NOT speak).

    ``mode`` is set on every mode-related event. ``stimmung_value`` and
    ``stimmung_bucket`` are set on every stimmung-related event.
    """

    kind: WatcherEventKind
    observed_at: str
    mode: str | None = None
    stimmung_value: float | None = None
    stimmung_bucket_value: str | None = None


WatcherEventHandler = Callable[[WatcherEvent], None | Awaitable[None]]


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _emit_mode_event(state: AwarenessDigestState, new_mode: str) -> WatcherEvent | None:
    """Classify a mode change against ``state`` and return an event.

    Mutates ``state.last_mode`` ONLY if a transition fires. ``None`` is
    returned for no-op observations (same mode as last).
    """
    if not is_mode_shift(state, new_mode):
        return None

    entering = is_entering_fortress(state, new_mode)
    exiting = is_exiting_fortress(state, new_mode)
    state.last_mode = new_mode

    if entering:
        kind: WatcherEventKind = "fortress_enter"
    elif exiting:
        kind = "fortress_exit"
    else:
        kind = "mode_shift"

    return WatcherEvent(kind=kind, observed_at=_now_iso(), mode=new_mode)


def _emit_stimmung_event(state: AwarenessDigestState, new_value: float) -> WatcherEvent | None:
    """Classify a stimmung observation against ``state`` and return an event.

    Mutates ``state.last_stimmung_bucket`` ONLY if a bucket crossing
    fires. ``None`` is returned for same-bucket observations.

    Within fortress, a crossing is reported as
    ``suppressed_within_fortress`` so the handler can audit the
    suppression without speaking. The state is still advanced — the
    suppression applies to handler dispatch, not to bucket tracking.
    """
    if not is_stimmung_threshold_cross(state, new_value):
        return None

    bucket = stimmung_bucket(new_value)
    state.last_stimmung_bucket = bucket
    kind: WatcherEventKind = (
        "suppressed_within_fortress" if is_within_fortress(state) else "stimmung_cross"
    )
    return WatcherEvent(
        kind=kind,
        observed_at=_now_iso(),
        stimmung_value=new_value,
        stimmung_bucket_value=bucket,
    )


async def tick_once(
    state: AwarenessDigestState,
    *,
    get_mode: Callable[[], str | None],
    get_stimmung: Callable[[], float | None],
    handler: WatcherEventHandler,
) -> list[WatcherEvent]:
    """Run a single watcher iteration; return the events that fired.

    Reads both getters, classifies each, advances ``state``, and
    dispatches each fired event to ``handler``. Mode is processed first
    so within-fortress suppression of stimmung is consistent on the
    same tick that fortress was entered. Either getter may return
    ``None`` (signal absent) — that observation is silently skipped,
    not treated as a transition.

    Handler exceptions are caught and logged; one bad handler call
    does not break the watcher.
    """
    fired: list[WatcherEvent] = []

    mode = get_mode()
    if mode is not None:
        event = _emit_mode_event(state, mode)
        if event is not None:
            fired.append(event)

    stimmung_value = get_stimmung()
    if stimmung_value is not None:
        event = _emit_stimmung_event(state, stimmung_value)
        if event is not None:
            fired.append(event)

    for event in fired:
        try:
            result = handler(event)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            log.exception("awareness-digest watcher handler raised on %s", event.kind)

    return fired


async def awareness_digest_watcher_loop(
    is_running: Callable[[], bool],
    *,
    get_mode: Callable[[], str | None],
    get_stimmung: Callable[[], float | None],
    handler: WatcherEventHandler,
    poll_interval_s: float = 5.0,
    state: AwarenessDigestState | None = None,
) -> None:
    """Polling loop: read getters every ``poll_interval_s`` and dispatch.

    Runs while ``is_running()`` returns truthy. Each iteration is a
    :func:`tick_once` call. The first tick after start always produces
    events for whatever mode/stimmung the getters return (initial state
    has ``last_mode is None``), which matches the digest's documented
    "first event always triggers" behavior.

    ``CancelledError`` exits cleanly. Other exceptions are logged but
    do not break the loop — the watcher must survive transient getter
    failures (file-not-yet-written, parser hiccups).
    """
    log.info(
        "awareness-digest watcher loop started (poll=%.1fs, fortress=%r)",
        poll_interval_s,
        FORTRESS_MODE,
    )
    if state is None:
        state = AwarenessDigestState()

    while is_running():
        try:
            await tick_once(
                state,
                get_mode=get_mode,
                get_stimmung=get_stimmung,
                handler=handler,
            )
            await asyncio.sleep(poll_interval_s)
        except asyncio.CancelledError:
            log.info("awareness-digest watcher loop cancelled")
            break
        except Exception:
            log.exception("awareness-digest watcher loop iteration failed")
            await asyncio.sleep(poll_interval_s)
