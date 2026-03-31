"""Phase 2 reactive rules — cloud LLM processing.

Includes: knowledge maintenance (quiet window), pattern consolidation,
correction synthesis.
"""

from __future__ import annotations

import asyncio
import logging
import time

from logos.engine.models import Action, ChangeEvent
from logos.engine.rules import Rule

_log = logging.getLogger(__name__)


# ── QuietWindowScheduler ────────────────────────────────────────────────────


class QuietWindowScheduler:
    """Accumulates events and fires a callback after a quiet period.

    Each new event resets the timer. The callback fires only after
    quiet_window_s seconds pass with no new events.
    """

    def __init__(self, quiet_window_s: float = 180) -> None:
        self._quiet_window_s = quiet_window_s
        self._dirty_paths: set[str] = set()
        self._last_event: float = 0.0
        self._scheduled_handle: asyncio.TimerHandle | None = None
        self._callback: asyncio.Future | None = None
        self._running = False

    @property
    def dirty(self) -> bool:
        return len(self._dirty_paths) > 0

    @property
    def dirty_paths(self) -> set[str]:
        return set(self._dirty_paths)

    def record(self, path: str, *, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Record a dirty path and reset the quiet window timer."""
        self._dirty_paths.add(path)
        self._last_event = time.monotonic()

        if self._scheduled_handle is not None:
            self._scheduled_handle.cancel()
            self._scheduled_handle = None

        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
        self._scheduled_handle = loop.call_later(self._quiet_window_s, self._mark_ready)

    def _mark_ready(self) -> None:
        self._scheduled_handle = None
        self._running = True

    def should_fire(self) -> bool:
        return bool(self._running and self._dirty_paths)

    def consume(self) -> set[str]:
        paths = set(self._dirty_paths)
        self._dirty_paths.clear()
        self._running = False
        return paths

    def cancel(self) -> None:
        if self._scheduled_handle is not None:
            self._scheduled_handle.cancel()
            self._scheduled_handle = None
        self._dirty_paths.clear()
        self._running = False


# ── Knowledge maintenance ───────────────────────────────────────────────────

_knowledge_scheduler = QuietWindowScheduler(quiet_window_s=180)


def get_knowledge_scheduler() -> QuietWindowScheduler:
    return _knowledge_scheduler


async def _handle_knowledge_maintenance(*, ignore_fn=None) -> str:
    from agents.knowledge_maint import run_maintenance
    from logos._config import PROFILES_DIR

    if ignore_fn is not None:
        ignore_fn(PROFILES_DIR / "knowledge-maint-report.json")

    # Snapshot dirty paths but don't consume yet — if maintenance fails,
    # paths remain for retry on the next qualifying event.
    paths = _knowledge_scheduler.dirty_paths
    _log.info("Knowledge maintenance triggered by %d dirty paths", len(paths))

    report = await run_maintenance(dry_run=False)
    _knowledge_scheduler.consume()  # consume only after success
    _log.info(
        "Knowledge maintenance complete: pruned=%d merged=%d",
        report.total_pruned,
        report.total_merged,
    )
    return f"maintenance:pruned={report.total_pruned},merged={report.total_merged}"


_KNOWLEDGE_TRIGGER_FILES = {
    "health-history.jsonl",
    "drift-report.json",
    "scout-report.json",
    "operator-profile.json",
    "knowledge-maint-report.json",
}


def _knowledge_maint_filter(event: ChangeEvent) -> bool:
    if "profiles" not in event.path.parts:
        return False
    if event.path.name == "knowledge-maint-report.json":
        return False
    if event.path.name == "knowledge-maint-history.jsonl":
        return False
    _knowledge_scheduler.record(str(event.path))
    return _knowledge_scheduler.should_fire()


def _knowledge_maint_produce(event: ChangeEvent) -> list[Action]:
    return [
        Action(
            name="knowledge-maintenance",
            handler=_handle_knowledge_maintenance,
            args={},
            phase=2,
            priority=80,
        )
    ]


KNOWLEDGE_MAINT_RULE = Rule(
    name="knowledge-maintenance",
    description="Run knowledge maintenance after profiles/ changes settle (180s quiet window)",
    trigger_filter=_knowledge_maint_filter,
    produce=_knowledge_maint_produce,
    phase=2,
    cooldown_s=600,
)


# ── Pattern consolidation (WS3 L3) ──────────────────────────────────────────

_consolidation_scheduler = QuietWindowScheduler(quiet_window_s=300)


async def _handle_pattern_consolidation(*, ignore_fn=None) -> str:
    from agents._correction_memory import CorrectionStore
    from logos._episodic_memory import EpisodeStore
    from logos._pattern_consolidation import PatternStore, run_consolidation

    episode_store = EpisodeStore()
    correction_store = CorrectionStore()
    pattern_store = PatternStore()
    pattern_store.ensure_collection()

    result = await run_consolidation(episode_store, correction_store, pattern_store)
    _consolidation_scheduler.consume()  # consume only after success
    _log.info(
        "Pattern consolidation: %d new patterns, summary: %s",
        len(result.patterns),
        result.summary[:80],
    )
    return f"consolidation:patterns={len(result.patterns)}"


def _consolidation_filter(event: ChangeEvent) -> bool:
    if event.path.name != "perception-state.json":
        return False
    _consolidation_scheduler.record(str(event.path))
    return _consolidation_scheduler.should_fire()


def _consolidation_produce(event: ChangeEvent) -> list[Action]:
    return [
        Action(
            name="pattern-consolidation",
            handler=_handle_pattern_consolidation,
            args={},
            phase=2,
            priority=90,
        )
    ]


PATTERN_CONSOLIDATION_RULE = Rule(
    name="pattern-consolidation",
    description="Run WS3 pattern consolidation after episodes accumulate (daily)",
    trigger_filter=_consolidation_filter,
    produce=_consolidation_produce,
    phase=2,
    cooldown_s=86400,
)


# ── Correction synthesis (WS3 learning loop) ────────────────────────────────

_correction_synthesis_scheduler = QuietWindowScheduler(quiet_window_s=600)


async def _handle_correction_synthesis(*, ignore_fn=None) -> str:
    from logos._correction_synthesis import run_correction_synthesis

    result = await run_correction_synthesis()
    _correction_synthesis_scheduler.consume()  # consume only after success
    _log.info("Correction synthesis: %s", result[:120])
    return f"correction-synthesis:{result[:80]}"


def _correction_synthesis_filter(event: ChangeEvent) -> bool:
    # Sentinel written to PROFILES_DIR by the studio activity-correction endpoint.
    # The original activity-correction.json lives in /dev/shm/ which the engine
    # doesn't watch; this sentinel bridges the gap.
    if event.path.name != "correction-pending.json":
        return False
    _correction_synthesis_scheduler.record(str(event.path))
    return _correction_synthesis_scheduler.should_fire()


def _correction_synthesis_produce(event: ChangeEvent) -> list[Action]:
    return [
        Action(
            name="correction-synthesis",
            handler=_handle_correction_synthesis,
            args={},
            phase=2,
            priority=85,
        )
    ]


CORRECTION_SYNTHESIS_RULE = Rule(
    name="correction-synthesis",
    description="Synthesize operator corrections into profile facts (daily)",
    trigger_filter=_correction_synthesis_filter,
    produce=_correction_synthesis_produce,
    phase=2,
    cooldown_s=86400,
)
