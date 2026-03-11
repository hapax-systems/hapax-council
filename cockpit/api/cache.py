"""Background data cache for the cockpit API.

Refreshes data collectors on timers matching the original TUI cadence:
- Fast (30s): health, GPU, containers, timers
- Slow (5min): briefing, scout, drift, cost, goals, readiness, nudges
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("cockpit.api")


@dataclass
class DataCache:
    """In-memory cache for all data collector results."""

    # Fast refresh (30s)
    health: Any = None
    gpu: Any = None
    containers: list = field(default_factory=list)
    timers: list = field(default_factory=list)

    # Slow refresh (5min)
    briefing: Any = None
    scout: Any = None
    drift: Any = None
    cost: Any = None
    goals: Any = None
    readiness: Any = None
    nudges: list = field(default_factory=list)
    agents: list = field(default_factory=list)
    accommodations: Any = None

    # Refresh timestamps (monotonic seconds)
    _fast_refreshed_at: float = 0.0
    _slow_refreshed_at: float = 0.0

    async def refresh_fast(self) -> None:
        """Refresh fast-cadence data (health, GPU, infra)."""
        from cockpit.data.gpu import collect_vram
        from cockpit.data.health import collect_live_health
        from cockpit.data.infrastructure import collect_docker, collect_timers

        try:
            health, containers, vram, timers = await asyncio.gather(
                collect_live_health(),
                collect_docker(),
                collect_vram(),
                collect_timers(),
                return_exceptions=True,
            )
            if not isinstance(health, BaseException):
                self.health = health
            if not isinstance(containers, BaseException):
                self.containers = containers
            if not isinstance(vram, BaseException):
                self.gpu = vram
            if not isinstance(timers, BaseException):
                self.timers = timers
        except Exception as e:
            log.warning("Fast refresh failed: %s", e)
        self._fast_refreshed_at = time.monotonic()

    async def refresh_slow(self) -> None:
        """Refresh slow-cadence data (briefing, scout, nudges, etc.)."""
        await asyncio.to_thread(self._refresh_slow_sync)
        self._slow_refreshed_at = time.monotonic()

    def fast_cache_age(self) -> int:
        """Seconds since last fast refresh."""
        if self._fast_refreshed_at == 0.0:
            return -1
        return int(time.monotonic() - self._fast_refreshed_at)

    def slow_cache_age(self) -> int:
        """Seconds since last slow refresh."""
        if self._slow_refreshed_at == 0.0:
            return -1
        return int(time.monotonic() - self._slow_refreshed_at)

    def _refresh_slow_sync(self) -> None:
        """Synchronous slow-cadence data collection (runs in thread pool)."""
        from cockpit.data.agents import get_agent_registry
        from cockpit.data.briefing import collect_briefing
        from cockpit.data.cost import collect_cost
        from cockpit.data.drift import collect_drift
        from cockpit.data.goals import collect_goals
        from cockpit.data.nudges import collect_nudges
        from cockpit.data.readiness import collect_readiness
        from cockpit.data.scout import collect_scout

        for name, fn in [
            ("briefing", collect_briefing),
            ("scout", collect_scout),
            ("drift", collect_drift),
            ("cost", collect_cost),
            ("goals", collect_goals),
            ("readiness", collect_readiness),
            ("agents", get_agent_registry),
        ]:
            try:
                setattr(self, name, fn())
            except Exception as e:
                log.warning("Slow refresh %s failed: %s", name, e)

        try:
            from cockpit.data.briefing import BriefingData
            briefing = self.briefing if isinstance(self.briefing, BriefingData) else None
            self.nudges = collect_nudges(briefing=briefing)
        except Exception as e:
            log.warning("Nudge collection error: %s", e)

        try:
            from cockpit.accommodations import load_accommodations
            self.accommodations = load_accommodations()
        except Exception as e:
            log.warning("Accommodation load error: %s", e)


# Singleton cache instance
cache = DataCache()

from shared.cycle_mode import get_cycle_mode, CycleMode


def _fast_interval() -> int:
    return 15 if get_cycle_mode() == CycleMode.DEV else 30


def _slow_interval() -> int:
    return 120 if get_cycle_mode() == CycleMode.DEV else 300


FAST_INTERVAL = 30   # backward-compat
SLOW_INTERVAL = 300  # backward-compat

_background_tasks: set[asyncio.Task] = set()


async def start_refresh_loop() -> None:
    """Start background refresh tasks. Called from FastAPI lifespan."""
    # Initial load
    await cache.refresh_fast()
    await cache.refresh_slow()

    async def _fast_loop():
        while True:
            await asyncio.sleep(_fast_interval())
            await cache.refresh_fast()

    async def _slow_loop():
        while True:
            await asyncio.sleep(_slow_interval())
            await cache.refresh_slow()

    task1 = asyncio.create_task(_fast_loop())
    task2 = asyncio.create_task(_slow_loop())
    _background_tasks.add(task1)
    _background_tasks.add(task2)
    task1.add_done_callback(_background_tasks.discard)
    task2.add_done_callback(_background_tasks.discard)
