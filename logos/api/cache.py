"""Background data cache for the logos API.

Refreshes data collectors on timers matching the original TUI cadence:
- Fast (30s): health, GPU, containers, timers
- Slow (5min): briefing, scout, drift, cost, goals, readiness, nudges
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logos.accommodations import AccommodationSet
    from logos.data.briefing import BriefingData
    from logos.data.cost import CostSnapshot
    from logos.data.drift import DriftSummary
    from logos.data.goals import GoalSnapshot
    from logos.data.gpu import VramSnapshot
    from logos.data.health import HealthSnapshot
    from logos.data.orientation import OrientationState
    from logos.data.readiness import ReadinessSnapshot
    from logos.data.scout import ScoutData
    from logos.data.studio import StudioSnapshot

log = logging.getLogger("logos.api")


@dataclass
class DataCache:
    """In-memory cache for all data collector results."""

    # Fast refresh (30s)
    health: HealthSnapshot | None = None
    gpu: VramSnapshot | None = None
    containers: list = field(default_factory=list)
    timers: list = field(default_factory=list)

    # Slow refresh (5min)
    briefing: BriefingData | None = None
    scout: ScoutData | None = None
    drift: DriftSummary | None = None
    cost: CostSnapshot | None = None
    goals: GoalSnapshot | None = None
    readiness: ReadinessSnapshot | None = None
    nudges: list = field(default_factory=list)
    agents: list = field(default_factory=list)
    accommodations: AccommodationSet | None = None
    studio: StudioSnapshot | None = None
    orientation: OrientationState | None = None

    # Refresh timestamps (monotonic seconds)
    _fast_refreshed_at: float = 0.0
    _slow_refreshed_at: float = 0.0
    _slow_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def refresh_fast(self) -> None:
        """Refresh fast-cadence data (health, GPU, infra)."""
        from logos.data.gpu import collect_vram
        from logos.data.health import collect_live_health
        from logos.data.infrastructure import collect_docker, collect_timers

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
        if self._slow_lock.locked():
            log.debug("Slow refresh already in progress, skipping")
            return
        async with self._slow_lock:
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
        from logos.data.agents import get_agent_registry
        from logos.data.briefing import collect_briefing
        from logos.data.cost import collect_cost
        from logos.data.drift import collect_drift
        from logos.data.goals import collect_goals
        from logos.data.nudges import collect_nudges
        from logos.data.readiness import collect_readiness
        from logos.data.scout import collect_scout
        from logos.data.studio import collect_studio

        for name, fn in [
            ("briefing", collect_briefing),
            ("scout", collect_scout),
            ("drift", collect_drift),
            ("cost", collect_cost),
            ("goals", collect_goals),
            ("readiness", collect_readiness),
            ("agents", get_agent_registry),
            ("studio", collect_studio),
        ]:
            try:
                setattr(self, name, fn())
            except Exception as e:
                log.warning("Slow refresh %s failed: %s", name, e)

        try:
            from logos.data.briefing import BriefingData

            briefing = self.briefing if isinstance(self.briefing, BriefingData) else None
            self.nudges = collect_nudges(briefing=briefing)
        except Exception as e:
            log.warning("Nudge collection error: %s", e)

        try:
            from logos.accommodations import load_accommodations

            self.accommodations = load_accommodations()
        except Exception as e:
            log.warning("Accommodation load error: %s", e)

        try:
            from logos.data.orientation import collect_orientation

            self.orientation = collect_orientation()
        except Exception as e:
            log.warning("Orientation refresh failed: %s", e)


# Singleton cache instance
cache = DataCache()


def _fast_interval() -> int:
    return 15


def _slow_interval() -> int:
    return 120


FAST_INTERVAL = 30  # backward-compat
SLOW_INTERVAL = 300  # backward-compat

_background_tasks: set[asyncio.Task] = set()


async def start_refresh_loop() -> None:
    """Start background refresh tasks. Called from FastAPI lifespan.

    Initial cache load runs in the background so the API starts serving
    immediately — endpoints return empty/stale data until the first
    refresh completes (typically <10s).
    """

    async def _fast_loop():
        await cache.refresh_fast()
        while True:
            await asyncio.sleep(_fast_interval())
            await cache.refresh_fast()

    async def _slow_loop():
        await cache.refresh_slow()
        while True:
            await asyncio.sleep(_slow_interval())
            await cache.refresh_slow()

    task1 = asyncio.create_task(_fast_loop())
    task2 = asyncio.create_task(_slow_loop())
    _background_tasks.add(task1)
    _background_tasks.add(task2)
    task1.add_done_callback(_background_tasks.discard)
    task2.add_done_callback(_background_tasks.discard)
