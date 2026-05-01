"""Overlay-zones producer orchestrator.

The producer holds a list of :class:`ContentSource` instances; each
source returns zero or more :class:`shared.text_repo.TextEntry`
candidates per tick. The producer dedups against existing entries in
the repo (by ``id``), applies a default TTL when sources don't supply
one, and writes the new entries through ``TextRepo.add_entry``.

The compositor's ``OverlayZoneManager`` already filters expired
entries during selection, so this producer just needs to keep fresh
entries flowing — when the producer crashes or stalls, existing
entries decay naturally and the zone reverts to the
``stream-overlays/`` folder fallback.

Pure-logic apart from ``TextRepo`` writes. The daemon loop wrapper
(``agents.overlay_producer.daemon``, separate slice) calls
:meth:`OverlayProducer.tick` on a 60s cadence.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Final, Protocol

from shared.text_repo import TextEntry, TextRepo

log = logging.getLogger(__name__)

#: Default TTL applied to entries whose source did not stamp ``expires_ts``.
#: Five minutes matches the recency-penalty window in
#: ``shared.text_repo.select_for_context``, so an entry has roughly the
#: lifetime of one rotation through the zone.
DEFAULT_ENTRY_TTL_S: Final[float] = 300.0


class ContentSource(Protocol):
    """Each content source emits zero or more `TextEntry` candidates."""

    def collect(self, now: float) -> list[TextEntry]:
        """Return entries to upsert at time ``now``.

        Sources are expected to be cheap to call (no heavy network or
        LLM work on the hot path). Sources that need expensive
        gathering should cache internally and return cached results.
        Failures should be logged and an empty list returned — one
        bad source must not break the producer tick.
        """
        ...


@dataclass(frozen=True)
class ProducerTickResult:
    """Per-tick summary returned by :meth:`OverlayProducer.tick`.

    ``added`` counts entries newly written this tick. ``skipped_existing``
    is entries whose id was already in the repo. ``source_failures``
    counts how many ``ContentSource.collect`` calls raised, so daemon
    health monitors can log when the producer is degraded.
    """

    added: int
    skipped_existing: int
    source_failures: int


class OverlayProducer:
    """Drives a list of content sources into the shared text repo.

    Construct once per daemon process. Pass a pre-loaded
    :class:`TextRepo` (the daemon owner is responsible for the
    ``load()`` call before the first tick).
    """

    def __init__(
        self,
        *,
        repo: TextRepo,
        sources: list[ContentSource],
        default_ttl_s: float = DEFAULT_ENTRY_TTL_S,
    ) -> None:
        if default_ttl_s <= 0:
            raise ValueError(f"default_ttl_s must be > 0, got {default_ttl_s}")
        self._repo = repo
        self._sources = list(sources)
        self._default_ttl_s = default_ttl_s

    def tick(self, now: float | None = None) -> ProducerTickResult:
        """Run one collection pass across all sources.

        Returns a :class:`ProducerTickResult` so callers / tests /
        observability can act on the counters. Source exceptions are
        caught and counted; the tick continues with remaining sources.
        """
        ts_now = now if now is not None else time.time()
        added = 0
        skipped = 0
        failures = 0

        # Snapshot existing IDs so dedup is O(1) per candidate.
        existing_ids: set[str] = {e.id for e in self._repo.all_entries()}

        for source in self._sources:
            try:
                candidates = source.collect(ts_now)
            except Exception:
                log.exception(
                    "overlay-producer source %s.collect raised; skipping",
                    type(source).__name__,
                )
                failures += 1
                continue
            for candidate in candidates:
                if candidate.id in existing_ids:
                    skipped += 1
                    continue
                expires_ts = candidate.expires_ts
                if expires_ts is None:
                    expires_ts = ts_now + self._default_ttl_s
                self._repo.add_entry(
                    body=candidate.body,
                    tags=candidate.tags,
                    priority=candidate.priority,
                    expires_ts=expires_ts,
                    context_keys=candidate.context_keys,
                    entry_id=candidate.id,
                )
                existing_ids.add(candidate.id)
                added += 1

        return ProducerTickResult(
            added=added,
            skipped_existing=skipped,
            source_failures=failures,
        )
