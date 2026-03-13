"""Actuation layer: Executor Protocol, ScheduleQueue, ExecutorRegistry.

Bridges governance output (Command/Schedule) to physical actuation.
Executor mirrors the PerceptionBackend pattern — Protocol-based, registry
with conflict detection, availability-gated registration.
"""

from __future__ import annotations

import bisect
import logging
import time
from typing import Protocol, runtime_checkable

from agents.hapax_voice.actuation_event import ActuationEvent
from agents.hapax_voice.commands import Command, Schedule
from agents.hapax_voice.primitives import Event

log = logging.getLogger(__name__)


@runtime_checkable
class Executor(Protocol):
    """Actuator that handles Commands. Mirrors PerceptionBackend pattern."""

    @property
    def name(self) -> str:
        """Unique executor identifier."""
        ...

    @property
    def handles(self) -> frozenset[str]:
        """Action names this executor accepts."""
        ...

    def execute(self, command: Command) -> None:
        """Execute a command. Must not block the caller."""
        ...

    def available(self) -> bool:
        """Return True if the executor's dependencies are met at runtime."""
        ...

    def close(self) -> None:
        """Release resources."""
        ...


class ScheduleQueue:
    """Priority queue drained by wall-clock time.

    Enqueue Schedules; drain returns items whose wall_time <= now,
    discarding expired items (past tolerance window).
    """

    __slots__ = ("_items",)

    def __init__(self) -> None:
        self._items: list[Schedule] = []

    def enqueue(self, schedule: Schedule) -> None:
        """Insert a schedule, maintaining wall_time sort order."""
        bisect.insort(self._items, schedule, key=lambda s: s.wall_time)

    def drain(self, now: float) -> list[Schedule]:
        """Return ready items (wall_time <= now), discard expired.

        An item is expired if now > wall_time + tolerance_ms/1000.
        Ready items have wall_time <= now and are within tolerance.
        Items with wall_time > now remain in the queue.
        """
        ready: list[Schedule] = []
        remaining: list[Schedule] = []

        for s in self._items:
            if s.wall_time > now:
                remaining.append(s)
                continue
            deadline = s.wall_time + s.tolerance_ms / 1000.0
            if now <= deadline:
                ready.append(s)
            else:
                log.debug(
                    "Schedule expired: action=%s wall_time=%.3f now=%.3f",
                    s.command.action,
                    s.wall_time,
                    now,
                )

        self._items = remaining
        return ready

    @property
    def pending_count(self) -> int:
        return len(self._items)


class ExecutorRegistry:
    """Maps action names to Executors. Dispatch routes to correct executor.

    Emits ActuationEvent on successful dispatch via the actuation_event Event.
    """

    __slots__ = ("_executors", "_action_map", "actuation_event")

    def __init__(self) -> None:
        self._executors: dict[str, Executor] = {}
        self._action_map: dict[str, Executor] = {}
        self.actuation_event: Event[ActuationEvent] = Event()

    def register(self, executor: Executor) -> None:
        """Register an executor. Rejects duplicate names or handle conflicts."""
        if executor.name in self._executors:
            raise ValueError(f"Executor already registered: {executor.name}")
        conflicts = executor.handles & frozenset(self._action_map)
        if conflicts:
            owners = {a: self._action_map[a].name for a in conflicts}
            raise ValueError(f"Action handle conflicts: {owners}")
        if not executor.available():
            log.warning("Executor %s not available, skipping registration", executor.name)
            return
        self._executors[executor.name] = executor
        for action in executor.handles:
            self._action_map[action] = executor
        log.info("Registered executor: %s (handles: %s)", executor.name, executor.handles)

    def dispatch(self, command: Command, schedule: Schedule | None = None) -> bool:
        """Route a command to the correct executor. Returns True if handled.

        On success, emits an ActuationEvent with latency tracking.
        If schedule is provided, latency is computed from schedule.wall_time.
        """
        if not command.governance_result.allowed:
            log.info(
                "Command blocked by governance: action=%s denied_by=%s axioms=%s",
                command.action,
                command.governance_result.denied_by,
                command.governance_result.axiom_ids,
            )
            return False
        executor = self._action_map.get(command.action)
        if executor is None:
            log.debug("No executor for action: %s", command.action)
            return False
        try:
            executor.execute(command)
            now = time.monotonic()
            target = schedule.wall_time if schedule is not None else now
            latency_ms = (now - target) * 1000.0
            event = ActuationEvent(
                action=command.action,
                chain=command.trigger_source,
                wall_time=now,
                target_time=target,
                latency_ms=latency_ms,
                params=dict(command.params),
            )
            self.actuation_event.emit(now, event)
            return True
        except Exception:
            log.exception("Executor %s failed on action %s", executor.name, command.action)
            return False

    def close_all(self) -> None:
        """Close all registered executors."""
        for executor in self._executors.values():
            try:
                executor.close()
            except Exception:
                log.exception("Error closing executor %s", executor.name)
        self._executors.clear()
        self._action_map.clear()

    @property
    def registered_actions(self) -> frozenset[str]:
        return frozenset(self._action_map)
