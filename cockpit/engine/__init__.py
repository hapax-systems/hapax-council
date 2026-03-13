"""cockpit/engine — Reactive engine orchestrator.

Watches filesystem for changes, evaluates rules, executes actions in phases.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from cockpit.engine.executor import PhasedExecutor
from cockpit.engine.models import ActionPlan as ActionPlan
from cockpit.engine.models import ChangeEvent
from cockpit.engine.rules import RuleRegistry, evaluate_rules
from cockpit.engine.watcher import DirectoryWatcher
from shared.config import AI_AGENTS_DIR, PROFILES_DIR, RAG_SOURCES_DIR
from shared.cycle_mode import CycleMode, get_cycle_mode

_log = logging.getLogger(__name__)


def _env_int(key: str, default: int) -> int:
    val = os.environ.get(key)
    if val is not None:
        try:
            return int(val)
        except ValueError:
            pass
    return default


def _env_float(key: str, default: float) -> float:
    val = os.environ.get(key)
    if val is not None:
        try:
            return float(val)
        except ValueError:
            pass
    return default


@dataclass
class _HistoryEntry:
    """Record of a processed event for status queries."""

    timestamp: datetime
    event_path: str
    doc_type: str | None
    rules_matched: list[str]
    actions: list[str]
    errors: list[str]


class ReactiveEngine:
    """Orchestrator wiring watcher, rules, executor, and delivery."""

    def __init__(
        self,
        data_dir: Path | None = None,
        watch_paths: list[Path] | None = None,
        debounce_ms: int | None = None,
        gpu_concurrency: int | None = None,
        cloud_concurrency: int | None = None,
        action_timeout_s: float | None = None,
        quiet_window_s: float | None = None,
        cooldown_default_s: float | None = None,
    ) -> None:
        cycle = get_cycle_mode()
        default_debounce = 1000 if cycle == CycleMode.DEV else 500

        self._data_dir = data_dir or PROFILES_DIR
        self._debounce_ms = debounce_ms or _env_int("ENGINE_DEBOUNCE_MS", default_debounce)
        self._gpu_concurrency = gpu_concurrency or _env_int("ENGINE_GPU_CONCURRENCY", 1)
        self._cloud_concurrency = cloud_concurrency or _env_int("ENGINE_CLOUD_CONCURRENCY", 2)
        self._action_timeout_s = action_timeout_s or _env_float("ENGINE_ACTION_TIMEOUT_S", 120)
        self._quiet_window_s = quiet_window_s or _env_float("ENGINE_QUIET_WINDOW_S", 180)
        self._cooldown_default_s = cooldown_default_s or _env_float("ENGINE_COOLDOWN_S", 600)

        self._watch_paths = watch_paths or [
            PROFILES_DIR,
            RAG_SOURCES_DIR,
            AI_AGENTS_DIR / "axioms",
        ]

        self._registry = RuleRegistry()
        self._executor = PhasedExecutor(
            gpu_concurrency=self._gpu_concurrency,
            cloud_concurrency=self._cloud_concurrency,
            action_timeout_s=self._action_timeout_s,
        )
        self._watcher: DirectoryWatcher | None = None
        self._paused = False
        self._running = False
        self._start_time: float | None = None

        # Counters
        self._events_processed = 0
        self._rules_evaluated = 0
        self._actions_executed = 0
        self._error_count = 0

        # History ring buffer
        self._history: deque[_HistoryEntry] = deque(maxlen=100)

    @property
    def registry(self) -> RuleRegistry:
        """Expose rule registry for external registration."""
        return self._registry

    @property
    def status(self) -> dict[str, Any]:
        """Current engine status."""
        uptime = time.monotonic() - self._start_time if self._start_time else 0
        return {
            "running": self._running,
            "paused": self._paused,
            "uptime_s": round(uptime, 1),
            "events_processed": self._events_processed,
            "rules_evaluated": self._rules_evaluated,
            "actions_executed": self._actions_executed,
            "errors": self._error_count,
        }

    @property
    def history(self) -> list[_HistoryEntry]:
        """Recent event history (newest first)."""
        return list(reversed(self._history))

    async def start(self) -> None:
        """Start the watcher and begin processing events."""
        if self._running:
            _log.warning("Engine already running")
            return

        loop = asyncio.get_running_loop()
        self._watcher = DirectoryWatcher(
            watch_paths=self._watch_paths,
            callback=self._handle_change,
            debounce_ms=self._debounce_ms,
            loop=loop,
            data_dir=self._data_dir,
        )
        await self._watcher.start()
        self._running = True
        self._start_time = time.monotonic()
        _log.info(
            "Reactive engine started (debounce=%dms, gpu=%d, cloud=%d)",
            self._debounce_ms,
            self._gpu_concurrency,
            self._cloud_concurrency,
        )

    async def stop(self) -> None:
        """Stop the watcher and clean up."""
        if not self._running:
            return

        if self._watcher is not None:
            await self._watcher.stop()
            self._watcher = None

        self._running = False
        _log.info("Reactive engine stopped")

    def pause(self) -> None:
        """Pause rule evaluation (events still debounced but not processed)."""
        self._paused = True
        _log.info("Engine paused")

    def resume(self) -> None:
        """Resume rule evaluation."""
        self._paused = False
        _log.info("Engine resumed")

    def ignore_fn(self, path: Path) -> None:
        """Register a path as own-write (passthrough to watcher)."""
        if self._watcher is not None:
            self._watcher.ignore_fn(path)

    async def _handle_change(self, event: ChangeEvent) -> None:
        """Core event handler: evaluate rules → execute plan → log results."""
        if self._paused:
            _log.debug("Paused, ignoring event: %s", event.path)
            return

        self._events_processed += 1

        _log.info(
            "Event: %s %s (doc_type=%s)",
            event.event_type,
            event.path,
            event.doc_type,
        )

        # Evaluate rules
        plan = evaluate_rules(event, self._registry)
        self._rules_evaluated += len(self._registry)

        if not plan.actions:
            _log.debug("No rules matched for %s", event.path)
            return

        _log.info(
            "Matched %d action(s): %s",
            len(plan.actions),
            [a.name for a in plan.actions],
        )

        # Execute
        await self._executor.execute(plan)
        self._actions_executed += len(plan.results)
        self._error_count += len(plan.errors)

        if plan.errors:
            _log.warning("Action errors: %s", plan.errors)

        # Record history
        self._history.append(
            _HistoryEntry(
                timestamp=event.timestamp,
                event_path=str(event.path),
                doc_type=event.doc_type,
                rules_matched=[a.name for a in plan.actions],
                actions=list(plan.results.keys()),
                errors=list(plan.errors.keys()),
            )
        )
