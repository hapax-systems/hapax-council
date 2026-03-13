"""cockpit/engine/reactive_rules.py — Reactive engine rules.

Phase 0 (deterministic):
- collector-refresh: refresh cockpit cache tier on profiles/ changes
- config-changed: log axiom registry reload on axioms/registry.yaml change
- sdlc-event-logged: notify + cache refresh on SDLC event append

Phase 1 (local GPU):
- rag-source-landed: ingest new RAG source files via Ollama embeddings

Phase 2 (cloud LLM):
- knowledge-maintenance: run maintenance after profiles/ changes settle (quiet window)
"""

from __future__ import annotations

import asyncio
import logging
import time

from cockpit.engine.models import Action, ChangeEvent
from cockpit.engine.rules import Rule

_log = logging.getLogger(__name__)

# ── File-to-cache-tier mapping ───────────────────────────────────────────────

_FAST_REFRESH_FILES = {"health-history.jsonl"}
_SLOW_REFRESH_FILES = {"drift-report.json", "scout-report.json", "operator-profile.json"}


# ── Handlers (lazy imports to avoid circular deps) ──────────────────────────


async def _handle_collector_refresh(*, tier: str) -> str:
    """Refresh the appropriate cockpit cache tier."""
    from cockpit.api.cache import cache

    if tier == "fast":
        await cache.refresh_fast()
    else:
        await cache.refresh_slow()
    _log.info("Cache %s refresh triggered by file change", tier)
    return f"cache.refresh_{tier}"


async def _handle_config_changed(*, path: str) -> str:
    """Log axiom registry change. No explicit reload needed — loaders read fresh."""
    _log.info("Axiom config changed: %s (loaders will pick up on next call)", path)
    return "config-reloaded"


async def _handle_sdlc_event(*, path: str) -> str:
    """Send notification and refresh slow cache for SDLC events."""
    from cockpit.api.cache import cache
    from shared.notify import send_notification

    await asyncio.to_thread(
        send_notification,
        "SDLC Pipeline Event",
        "New event logged to sdlc-events.jsonl",
        priority="default",
        tags=["gear"],
    )
    await cache.refresh_slow()
    _log.info("SDLC event notification sent + slow cache refreshed")
    return "sdlc-notified"


# ── Rule definitions ────────────────────────────────────────────────────────


def _collector_refresh_filter(event: ChangeEvent) -> bool:
    """Match profiles/ file changes that need cache refresh."""
    return event.path.name in _FAST_REFRESH_FILES | _SLOW_REFRESH_FILES


def _collector_refresh_produce(event: ChangeEvent) -> list[Action]:
    """Produce cache refresh action for the correct tier."""
    filename = event.path.name
    if filename in _FAST_REFRESH_FILES:
        tier = "fast"
    else:
        tier = "slow"
    return [
        Action(
            name=f"collector-refresh-{tier}",
            handler=_handle_collector_refresh,
            args={"tier": tier},
            phase=0,
            priority=10,
        )
    ]


def _config_changed_filter(event: ChangeEvent) -> bool:
    """Match axioms/registry.yaml modifications."""
    return event.path.name == "registry.yaml" and "axioms" in event.path.parts


def _config_changed_produce(event: ChangeEvent) -> list[Action]:
    return [
        Action(
            name="config-changed",
            handler=_handle_config_changed,
            args={"path": str(event.path)},
            phase=0,
            priority=5,
        )
    ]


def _sdlc_event_filter(event: ChangeEvent) -> bool:
    """Match sdlc-events.jsonl modifications."""
    return event.path.name == "sdlc-events.jsonl"


def _sdlc_event_produce(event: ChangeEvent) -> list[Action]:
    return [
        Action(
            name="sdlc-event-logged",
            handler=_handle_sdlc_event,
            args={"path": str(event.path)},
            phase=0,
            priority=20,
        )
    ]


# ── Phase 1: Sync rules (local GPU) ─────────────────────────────────────


async def _handle_rag_ingest(*, path: str) -> str:
    """Ingest a new RAG source file. Runs in thread (sync function)."""
    from pathlib import Path

    from agents.ingest import ingest_file

    file_path = Path(path)
    success, error = await asyncio.to_thread(ingest_file, file_path)
    if success:
        _log.info("Ingested RAG source: %s", file_path.name)
        return f"ingested:{file_path.name}"
    else:
        _log.warning("Ingest failed for %s: %s", file_path.name, error)
        raise RuntimeError(f"Ingest failed: {error}")


def _rag_source_filter(event: ChangeEvent) -> bool:
    """Match new files in RAG_SOURCES_DIR."""
    if event.event_type != "created":
        return False
    return event.source_service is not None


def _rag_source_produce(event: ChangeEvent) -> list[Action]:
    return [
        Action(
            name=f"rag-ingest:{event.path}",
            handler=_handle_rag_ingest,
            args={"path": str(event.path)},
            phase=1,
            priority=50,
        )
    ]


RAG_SOURCE_RULE = Rule(
    name="rag-source-landed",
    description="Ingest new RAG source files via local GPU embeddings",
    trigger_filter=_rag_source_filter,
    produce=_rag_source_produce,
    phase=1,
    cooldown_s=0,
)


# ── Phase 2: Knowledge rules (cloud LLM) ───────────────────────────────


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

        # Cancel any pending scheduled fire
        if self._scheduled_handle is not None:
            self._scheduled_handle.cancel()
            self._scheduled_handle = None

        # Schedule fire after quiet window
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # No running loop — can't schedule, stay dirty but don't fire
                return
        self._scheduled_handle = loop.call_later(self._quiet_window_s, self._mark_ready)

    def _mark_ready(self) -> None:
        """Called when quiet window expires."""
        self._scheduled_handle = None
        self._running = True

    def should_fire(self) -> bool:
        """Check if quiet window has elapsed and there's dirty state."""
        return bool(self._running and self._dirty_paths)

    def consume(self) -> set[str]:
        """Consume dirty paths, resetting state. Call after firing."""
        paths = set(self._dirty_paths)
        self._dirty_paths.clear()
        self._running = False
        return paths

    def cancel(self) -> None:
        """Cancel any pending timer."""
        if self._scheduled_handle is not None:
            self._scheduled_handle.cancel()
            self._scheduled_handle = None
        self._dirty_paths.clear()
        self._running = False


# Module-level scheduler instance shared between filter and handler
_knowledge_scheduler = QuietWindowScheduler(quiet_window_s=180)


def get_knowledge_scheduler() -> QuietWindowScheduler:
    """Expose scheduler for testing and engine integration."""
    return _knowledge_scheduler


async def _handle_knowledge_maintenance(*, ignore_fn=None) -> str:
    """Run knowledge maintenance after quiet window expires."""
    from agents.knowledge_maint import run_maintenance
    from shared.config import PROFILES_DIR

    # Self-trigger prevention for output files
    if ignore_fn is not None:
        ignore_fn(PROFILES_DIR / "knowledge-maint-report.json")

    paths = _knowledge_scheduler.consume()
    _log.info("Knowledge maintenance triggered by %d dirty paths", len(paths))

    report = await run_maintenance(dry_run=False)
    _log.info(
        "Knowledge maintenance complete: pruned=%d merged=%d",
        report.total_pruned,
        report.total_merged,
    )
    return f"maintenance:pruned={report.total_pruned},merged={report.total_merged}"


# Files that should trigger knowledge maintenance consideration
_KNOWLEDGE_TRIGGER_FILES = {
    "health-history.jsonl",
    "drift-report.json",
    "scout-report.json",
    "operator-profile.json",
    "knowledge-maint-report.json",  # own output — filtered by scheduler, not trigger
}


def _knowledge_maint_filter(event: ChangeEvent) -> bool:
    """Match profiles/ changes and manage quiet window.

    Always records events. Only returns True when quiet window has elapsed.
    """
    # Only profiles/ directory changes
    if "profiles" not in event.path.parts:
        return False
    # Skip our own output
    if event.path.name == "knowledge-maint-report.json":
        return False
    if event.path.name == "knowledge-maint-history.jsonl":
        return False

    # Record the event in the scheduler
    _knowledge_scheduler.record(str(event.path))

    # Only fire if quiet window has elapsed
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


# ── Registration ────────────────────────────────────────────────────────────

ALL_RULES: list[Rule] = [
    Rule(
        name="collector-refresh",
        description="Refresh cockpit cache tier when profiles/ data changes",
        trigger_filter=_collector_refresh_filter,
        produce=_collector_refresh_produce,
        phase=0,
    ),
    Rule(
        name="config-changed",
        description="Log axiom registry reload on axioms/registry.yaml change",
        trigger_filter=_config_changed_filter,
        produce=_config_changed_produce,
        phase=0,
    ),
    Rule(
        name="sdlc-event-logged",
        description="Notify and refresh cache on SDLC pipeline event",
        trigger_filter=_sdlc_event_filter,
        produce=_sdlc_event_produce,
        phase=0,
        cooldown_s=30,
    ),
    RAG_SOURCE_RULE,
    KNOWLEDGE_MAINT_RULE,
]

# Backwards compat alias
INFRASTRUCTURE_RULES = ALL_RULES


def register_rules(registry) -> None:
    """Register all reactive rules on a RuleRegistry."""
    for rule in ALL_RULES:
        registry.register(rule)
    _log.info("Registered %d reactive rules", len(ALL_RULES))


# Backwards compat alias
register_infrastructure_rules = register_rules
