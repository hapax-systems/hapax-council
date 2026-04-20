"""AttributionSource Protocol — Phase 1 of YouTube broadcast bundle (#144).

Per `docs/superpowers/specs/2026-04-18-youtube-broadcast-bundle-design.md`
§2.4 + plan `docs/superpowers/plans/2026-04-20-youtube-broadcast-bundle-plan.md`
Phase 1.

Operator's framing (spec §2.4):

    > think carefully about this last part, because it could be a
    > powerful reusable strategy.

The strategy: every linkable artifact produced during a stream backflows
into the YouTube livestream description as a citation. Define one
contract that maps every kind of attribution-bearing producer →
description text:

    AttributionSource (Protocol)
        ↓
    AttributionEntry (typed)
        ↓
    AttributionFileWriter (per-kind JSONL under vault)
        ↓
    youtube_description_syncer (existing) reads + dedups + PUTs

Producers that should implement this Protocol:

- chat-monitor URL extractor (Phase 2 of plan)
- vinyl now-playing → operator-vinyl attribution
- knowledge-tool web-search results
- daimonion citations from research/RAG
- album-art lookup → cover-source attribution

This module ships the Protocol + the AttributionEntry shape + the
file-per-kind ring buffer + the per-kind file writer. Concrete
producers wire in subsequent phases.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

log = logging.getLogger(__name__)

AttributionKind = Literal[
    "citation",
    "album-ref",
    "doi",
    "tweet",
    "youtube",
    "github",
    "wikipedia",
    "operator-vinyl",
    "soundcloud-licensed",
    "hapax-pool",
    "youtube-react",
    "other",
]

DEFAULT_VAULT_ATTRIBUTION_ROOT: Path = (
    Path.home() / "Documents" / "Personal" / "30-areas" / "legomena-live"
)


@dataclass(frozen=True)
class AttributionEntry:
    """One linkable artifact with provenance metadata."""

    kind: AttributionKind
    url: str
    title: str | None = None
    source: str = ""  # producer identifier; chat-author IDs MUST be hashed before this point
    emitted_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.url.strip():
            raise ValueError("AttributionEntry.url cannot be empty")
        if self.kind not in AttributionKind.__args__:  # type: ignore[attr-defined]
            raise ValueError(
                f"AttributionEntry.kind={self.kind!r} not in {AttributionKind.__args__}"
            )

    @property
    def dedup_key(self) -> str:
        """Stable hash for de-duplication.

        Two entries with the same kind + url collide regardless of
        source/title/metadata — the description should not get the same
        URL twice across producers.
        """
        return hashlib.md5(  # noqa: S324 — non-security identifier hash
            f"{self.kind}|{self.url}".encode(), usedforsecurity=False
        ).hexdigest()

    def to_jsonl_line(self) -> str:
        """Serialize as one JSONL line (newline appended by writer)."""
        return json.dumps(
            {
                "kind": self.kind,
                "url": self.url,
                "title": self.title,
                "source": self.source,
                "emitted_at": self.emitted_at.isoformat(),
                "metadata": self.metadata,
            },
            sort_keys=False,
            separators=(",", ":"),
        )


class AttributionSource(Protocol):
    """One contract per attribution-bearing producer.

    Producers implement this Protocol; consumers (description syncer,
    operator dashboard, audit log) iterate over entries via
    ``emit_entries()``.
    """

    def emit_entries(self, since: datetime | None = None) -> Iterator[AttributionEntry]:
        """Yield entries newer than ``since`` (or all if None).

        Producers MUST yield only entries they have authority over; do
        not invent or forward entries from other producers (that's the
        consumer's job to aggregate).
        """
        ...


class AttributionRingBuffer:
    """Per-kind in-memory FIFO with TTL + size cap.

    Used by producers that observe a fast event stream (chat URLs) and
    need to bound memory. Older entries fall off; consumers pull via
    ``snapshot()`` to get a list at a point in time.

    Thread-safe via internal lock — chat-monitor and the description
    syncer can read concurrently.
    """

    def __init__(
        self,
        *,
        max_per_kind: int = 100,
        ttl_seconds: float = 86400.0,  # 24h default per spec §2.4
    ) -> None:
        self._max_per_kind = max_per_kind
        self._ttl_seconds = ttl_seconds
        # One deque per kind; lazy-created on first use.
        self._buffers: dict[AttributionKind, deque[AttributionEntry]] = {}
        self._lock = threading.Lock()

    def add(self, entry: AttributionEntry) -> None:
        """Append an entry, evicting oldest if over cap."""
        with self._lock:
            buf = self._buffers.setdefault(entry.kind, deque(maxlen=self._max_per_kind))
            buf.append(entry)

    def snapshot(
        self, kind: AttributionKind | None = None, *, now: datetime | None = None
    ) -> list[AttributionEntry]:
        """Return all currently-live entries for one kind, or all kinds.

        TTL applied at snapshot time so stale entries never leak to
        consumers without paying the eviction cost on the producer
        path.
        """
        cutoff = now or datetime.now(UTC)
        with self._lock:
            if kind is not None:
                source_buffers = [self._buffers.get(kind, deque())]
            else:
                source_buffers = list(self._buffers.values())
        result: list[AttributionEntry] = []
        for buf in source_buffers:
            for entry in buf:
                age = (cutoff - entry.emitted_at).total_seconds()
                if 0 <= age <= self._ttl_seconds:
                    result.append(entry)
        return result

    def __len__(self) -> int:
        with self._lock:
            return sum(len(b) for b in self._buffers.values())


class AttributionFileWriter:
    """Append-only JSONL per-kind under the vault attribution root.

    Path: ``<root>/<kind>.jsonl``. Atomic via tmp+rename per file (D-20
    pattern; one writer at a time per kind).

    Operator can browse + curate the JSONL files manually in Obsidian.
    """

    def __init__(self, root: Path = DEFAULT_VAULT_ATTRIBUTION_ROOT) -> None:
        self.root = root
        self._lock = threading.Lock()

    def append(self, entry: AttributionEntry) -> None:
        """Append one entry to ``<root>/<entry.kind>.jsonl``."""
        path = self.root / f"{entry.kind}.jsonl"
        line = entry.to_jsonl_line() + "\n"
        with self._lock:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                # Sub-PIPE_BUF append; threads in the same process are
                # serialized by the lock above, multi-process writers
                # would need fcntl.flock.
                with path.open("a", encoding="utf-8") as f:
                    f.write(line)
            except OSError:
                log.warning(
                    "AttributionFileWriter append failed for %s",
                    path,
                    exc_info=True,
                )

    def read_all(self, kind: AttributionKind) -> list[AttributionEntry]:
        """Read every entry of one kind from the JSONL file (for tests
        + the description syncer's enumeration step)."""
        path = self.root / f"{kind}.jsonl"
        if not path.exists():
            return []
        entries: list[AttributionEntry] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                entries.append(
                    AttributionEntry(
                        kind=data["kind"],
                        url=data["url"],
                        title=data.get("title"),
                        source=data.get("source", ""),
                        emitted_at=datetime.fromisoformat(data["emitted_at"]),
                        metadata=data.get("metadata", {}),
                    )
                )
            except (json.JSONDecodeError, KeyError, ValueError):
                log.warning("malformed attribution entry in %s: %r", path, line)
        return entries


__all__ = [
    "AttributionEntry",
    "AttributionFileWriter",
    "AttributionKind",
    "AttributionRingBuffer",
    "AttributionSource",
    "DEFAULT_VAULT_ATTRIBUTION_ROOT",
]
