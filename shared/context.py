# shared/context.py
"""Shared context enrichment for all Hapax subsystems.

EnrichmentContext is assembled from canonical sources and consumed by both
daimonion (voice) and Reverie (visual). Both systems see identical context
at the same moment.

Phase 2 of capability parity (queue #018).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

_DEFAULT_STIMMUNG = Path("/dev/shm/hapax-stimmung/state.json")
_DEFAULT_DMN_BUFFER = Path("/dev/shm/hapax-dmn/buffer.txt")
_DEFAULT_IMAGINATION = Path("/dev/shm/hapax-imagination/current.json")


@dataclass(frozen=True)
class EnrichmentContext:
    """Snapshot of all context sources, consumed by voice and visual systems."""

    timestamp: float
    stimmung_stance: str = "nominal"
    stimmung_raw: dict = field(default_factory=dict)
    active_goals: list[dict] = field(default_factory=list)
    health_summary: dict = field(default_factory=dict)
    pending_nudges: list[dict] = field(default_factory=list)
    dmn_observations: list[str] = field(default_factory=list)
    imagination_fragments: list[dict] = field(default_factory=list)
    perception_snapshot: dict = field(default_factory=dict)


class ContextAssembler:
    """Gathers context from canonical sources with snapshot isolation and caching."""

    def __init__(
        self,
        stimmung_path: Path = _DEFAULT_STIMMUNG,
        dmn_buffer_path: Path = _DEFAULT_DMN_BUFFER,
        imagination_path: Path = _DEFAULT_IMAGINATION,
        goals_fn=None,
        health_fn=None,
        nudges_fn=None,
        perception_fn=None,
        goals_ttl: float = 60.0,
        health_ttl: float = 30.0,
        nudges_ttl: float = 30.0,
    ) -> None:
        self._stimmung_path = stimmung_path
        self._dmn_buffer_path = dmn_buffer_path
        self._imagination_path = imagination_path
        self._goals_fn = goals_fn or (lambda: [])
        self._health_fn = health_fn or (lambda: {})
        self._nudges_fn = nudges_fn or (lambda: [])
        self._perception_fn = perception_fn or (lambda: {})
        self._cache: EnrichmentContext | None = None
        self._cache_time: float = 0.0
        self._cache_ttl: float = 2.0
        # Per-fragment TTL cache: key -> (result, timestamp)
        import threading

        self._fragment_cache: dict[str, tuple[object, float]] = {}
        self._fragment_lock = threading.Lock()
        self._ttls: dict[str, float] = {
            "goals": goals_ttl,
            "health": health_ttl,
            "nudges": nudges_ttl,
        }

    def _cached_call(self, key: str, fn) -> object:
        """Return cached result if within TTL, otherwise call fn and cache.

        Thread-safe: multiple agents may call snapshot() concurrently.
        """
        with self._fragment_lock:
            now = time.time()
            ttl = self._ttls.get(key, 30.0)
            if key in self._fragment_cache:
                result, ts = self._fragment_cache[key]
                if (now - ts) < ttl:
                    return result
        # Call fn outside lock (may be slow — Qdrant queries, collectors)
        result = fn()
        with self._fragment_lock:
            self._fragment_cache[key] = (result, now)
        return result

    def flush(self) -> None:
        """Clear all cached fragments."""
        with self._fragment_lock:
            self._fragment_cache.clear()

    def snapshot(self) -> EnrichmentContext:
        """Assemble context using per-fragment TTL caches.

        Shm reads (stimmung, dmn, imagination) are always fresh.
        Callback sources (goals, health, nudges) are cached per their TTLs.
        """
        stimmung_raw = self._read_stimmung_raw()
        return EnrichmentContext(
            timestamp=time.time(),
            stimmung_stance=stimmung_raw.get("overall_stance", "nominal"),
            stimmung_raw=stimmung_raw,
            active_goals=self._safe_call(  # type: ignore[arg-type]
                lambda: self._cached_call("goals", self._goals_fn), []
            ),
            health_summary=self._safe_call(  # type: ignore[arg-type]
                lambda: self._cached_call("health", self._health_fn), {}
            ),
            pending_nudges=self._safe_call(  # type: ignore[arg-type]
                lambda: self._cached_call("nudges", self._nudges_fn), []
            ),
            dmn_observations=self._read_dmn_buffer(),
            imagination_fragments=self._read_imagination(),
            perception_snapshot=self._safe_call(self._perception_fn, {}),
        )

    def assemble(self) -> EnrichmentContext:
        """Assemble context from all sources. Cached for _cache_ttl seconds."""
        now = time.monotonic()
        if self._cache is not None and (now - self._cache_time) < self._cache_ttl:
            return self._cache

        stimmung_raw = self._read_stimmung_raw()
        ctx = EnrichmentContext(
            timestamp=time.time(),
            stimmung_stance=stimmung_raw.get("overall_stance", "nominal"),
            stimmung_raw=stimmung_raw,
            active_goals=self._safe_call(self._goals_fn, []),
            health_summary=self._safe_call(self._health_fn, {}),
            pending_nudges=self._safe_call(self._nudges_fn, []),
            dmn_observations=self._read_dmn_buffer(),
            imagination_fragments=self._read_imagination(),
            perception_snapshot=self._safe_call(self._perception_fn, {}),
        )
        self._cache = ctx
        self._cache_time = now
        return ctx

    def invalidate(self) -> None:
        """Force next assemble() to re-read all sources."""
        self._cache = None

    def _read_stimmung_raw(self) -> dict:
        try:
            return json.loads(self._stimmung_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _read_dmn_buffer(self) -> list[str]:
        try:
            text = self._dmn_buffer_path.read_text(encoding="utf-8").strip()
            return [text] if text else []
        except (FileNotFoundError, OSError):
            return []

    def _read_imagination(self) -> list[dict]:
        try:
            raw = json.loads(self._imagination_path.read_text(encoding="utf-8"))
            return [raw] if raw else []
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []

    @staticmethod
    def _safe_call(fn, default):
        try:
            return fn()
        except Exception:
            log.debug("Context source failed (non-fatal)", exc_info=True)
            return default
