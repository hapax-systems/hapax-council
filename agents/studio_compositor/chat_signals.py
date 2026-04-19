"""LRR Phase 9 item 3 — structural aggregation writer.

Consumes the :class:`StructuralSignalQueue` (T4 messages, rolling 60s
window) and writes the aggregate ``audience_engagement`` components to
``/dev/shm/hapax-chat-signals.json`` every ~30s. The closed-loop
stimmung consumer reads this file to update the ``audience_engagement``
dimension per Bundle 9 §2.5.

All signals are **structural** — counts, rates, distributions,
diversity. Sentiment is deliberately excluded per Bundle 9 §2.6 and
token pole 7 principle 7. The aggregator computes:

- ``message_count_60s`` — raw count over the window
- ``message_rate_per_min`` — smoothed rate
- ``unique_authors_60s`` — distinct ephemeral author handle hashes
- ``chat_entropy`` — Shannon entropy of message embeddings (0 if no
  embeddings available)
- ``chat_novelty`` — fraction of messages whose cosine distance to
  the rolling centroid is > 0.5
- ``audience_engagement`` — scalar in [0, 1] per the §2.5 formula

Writes go through :func:`shared.stream_archive.atomic_write_json` so
concurrent readers never see partial JSON.

Constitutional constraints:
- Author handles enter the aggregator ONLY as hashes — the caller is
  responsible for hashing at classification time, per
  ``interpersonal_transparency`` axiom.
- No sentiment scoring, ever. See the module-level comment for the
  rationale.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

from agents.studio_compositor.chat_classifier import ChatTier
from agents.studio_compositor.chat_queues import ChatMessage, StructuralSignalQueue

__all__ = [
    "ChatSignals",
    "ChatSignalsAggregator",
    "DEFAULT_CHAT_SIGNALS_PATH",
    "compute_audience_engagement",
]

DEFAULT_CHAT_SIGNALS_PATH: Final = Path("/dev/shm/hapax-chat-signals.json")
"""Bundle 9 §2.5 canonical SHM path for stimmung consumer."""


@dataclass(frozen=True)
class ChatSignals:
    """Structural aggregate signals emitted per window tick.

    Task #123 (Chat Ambient Ward, 2026-04-18) extends this with four
    tier-disaggregated fields — ``t4_plus_rate_per_min``,
    ``unique_t4_plus_authors_60s``, ``t5_rate_per_min``,
    ``t6_rate_per_min``. All four are **pure aggregates** derived from
    the classifier tier labels already on ``ChatMessage.classification``
    (no new per-author state, no message-body storage). They feed the
    BitchX-grammar chat-ambient ward in the compositor chrome band.
    """

    window_seconds: float
    window_end_ts: float
    message_count_60s: int
    message_rate_per_min: float
    unique_authors_60s: int
    chat_entropy: float
    chat_novelty: float
    high_value_queue_depth: int
    audience_engagement: float
    # Task #123 — ChatAmbientWard inputs (aggregate only, no identity leak).
    t4_plus_rate_per_min: float = 0.0
    unique_t4_plus_authors_60s: int = 0
    t5_rate_per_min: float = 0.0
    t6_rate_per_min: float = 0.0


def _sigmoid(x: float) -> float:
    """Numerically stable logistic sigmoid."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    exp_x = math.exp(x)
    return exp_x / (1.0 + exp_x)


def compute_audience_engagement(
    *,
    message_rate_per_min: float,
    chat_entropy: float,
    chat_novelty: float,
    unique_authors_60s: int,
    high_value_queue_depth: int,
) -> float:
    """Bundle 9 §2.5 ``audience_engagement`` formula — pure function.

    Each component is clamped via sigmoid or min() into [0, 1]; the
    weighted sum is therefore already in [0, 1] without additional
    normalization.
    """
    rate_component = _sigmoid((message_rate_per_min - 5.0) / 10.0)
    entropy_component = min(chat_entropy / 3.0, 1.0)
    novelty_component = max(0.0, min(chat_novelty, 1.0))
    authors_component = _sigmoid((unique_authors_60s - 3.0) / 5.0)
    hv_component = 1.0 if high_value_queue_depth > 0 else 0.0
    return (
        0.30 * rate_component
        + 0.20 * entropy_component
        + 0.20 * novelty_component
        + 0.15 * authors_component
        + 0.15 * hv_component
    )


def _shannon_entropy(vectors: list[tuple[float, ...]]) -> float:
    """Shannon entropy of a clustering of embedding vectors.

    Without a real embedder we approximate via hash-bucket clustering:
    each vector is hashed into one of 8 buckets, then entropy is
    computed over the bucket distribution. This gives a rough
    "diversity" measure for test determinism and downstream monitoring.
    """
    if not vectors:
        return 0.0
    buckets: dict[int, int] = {}
    for vec in vectors:
        idx = hash(tuple(round(v, 4) for v in vec)) % 8
        buckets[idx] = buckets.get(idx, 0) + 1
    total = sum(buckets.values())
    if total == 0:
        return 0.0
    entropy = 0.0
    for count in buckets.values():
        if count == 0:
            continue
        p = count / total
        entropy -= p * math.log2(p)
    return entropy


def _novelty_fraction(vectors: list[tuple[float, ...]], threshold: float = 0.5) -> float:
    """Fraction of vectors whose cosine distance to the centroid exceeds ``threshold``.

    Cosine distance = 1 - cosine similarity. The centroid is the
    arithmetic mean of the window vectors.
    """
    if not vectors:
        return 0.0
    dim = len(vectors[0])
    centroid = [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]
    centroid_norm = math.sqrt(sum(c * c for c in centroid))
    if centroid_norm == 0:
        return 0.0
    novel_count = 0
    for vec in vectors:
        vec_norm = math.sqrt(sum(v * v for v in vec))
        if vec_norm == 0:
            continue
        dot = sum(c * v for c, v in zip(centroid, vec, strict=False))
        similarity = dot / (centroid_norm * vec_norm)
        distance = 1.0 - similarity
        if distance > threshold:
            novel_count += 1
    return novel_count / len(vectors)


class ChatSignalsAggregator:
    """Tick-driven aggregator — compute + emit ChatSignals.

    Not a daemon in itself. The caller drives ``compute_signals`` on a
    ~30s cadence and optionally invokes ``write_shm`` to publish. Keeping
    the timer external means this module is trivially testable.

    Task #123 (Chat Ambient Ward, 2026-04-18): the aggregator also
    accumulates per-tier timestamped events via
    :meth:`record_classification`. The caller invokes this once per
    classified chat message; the aggregator stores only
    ``(ts, tier, author_hash)`` tuples — no text, no raw author handle —
    and prunes to a rolling window on every read. The resulting
    ``t4_plus_rate_per_min``/``unique_t4_plus_authors_60s``/
    ``t5_rate_per_min``/``t6_rate_per_min`` fields feed the
    :class:`ChatAmbientWard` BitchX-grammar ambient chrome row.
    """

    def __init__(
        self,
        queue: StructuralSignalQueue,
        *,
        output_path: Path | None = None,
        tier_window_seconds: float = 60.0,
    ) -> None:
        self._queue = queue
        self._output_path = output_path or DEFAULT_CHAT_SIGNALS_PATH
        self._tier_window_seconds = tier_window_seconds
        # Each entry: (ts, tier_int, short_author_hash). No text, no raw handle.
        self._tier_events: list[tuple[float, int, str]] = []

    @property
    def output_path(self) -> Path:
        return self._output_path

    def record_classification(
        self,
        *,
        ts: float,
        tier: ChatTier,
        author_handle: str,
    ) -> None:
        """Record a single classification for tier-disaggregated aggregates.

        The aggregator immediately hashes ``author_handle`` (sha256, first
        16 hex chars — same discipline as existing author counting) and
        discards the raw handle. Message text is never accepted.
        """
        digest = hashlib.sha256(author_handle.encode("utf-8")).hexdigest()[:16]
        self._tier_events.append((ts, int(tier), digest))

    def _prune_tier_events(self, *, now: float) -> None:
        cutoff = now - self._tier_window_seconds
        # Small window + small arrival rates → list comprehension is fine.
        self._tier_events = [evt for evt in self._tier_events if evt[0] >= cutoff]

    def _tier_aggregates(self, *, now: float) -> tuple[float, int, float, float]:
        """Return (t4_plus_rate_per_min, unique_t4_plus_authors_60s, t5_rate_per_min, t6_rate_per_min)."""
        self._prune_tier_events(now=now)
        if self._tier_window_seconds <= 0:
            return 0.0, 0, 0.0, 0.0
        t4_plus_count = 0
        t5_count = 0
        t6_count = 0
        t4_plus_hashes: set[str] = set()
        t4_int = int(ChatTier.T4_STRUCTURAL_SIGNAL)
        t5_int = int(ChatTier.T5_RESEARCH_RELEVANT)
        t6_int = int(ChatTier.T6_HIGH_VALUE)
        for _ts, tier_int, author_hash in self._tier_events:
            if tier_int >= t4_int:
                t4_plus_count += 1
                t4_plus_hashes.add(author_hash)
            if tier_int == t5_int:
                t5_count += 1
            elif tier_int == t6_int:
                t6_count += 1
        scale = 60.0 / self._tier_window_seconds
        return (
            t4_plus_count * scale,
            len(t4_plus_hashes),
            t5_count * scale,
            t6_count * scale,
        )

    def compute_signals(
        self,
        *,
        now: float,
        high_value_queue_depth: int = 0,
    ) -> ChatSignals:
        items = self._queue.window_items(now=now)
        count = len(items)
        window_seconds = self._queue.window_seconds
        rate_per_min = (count / window_seconds) * 60.0 if window_seconds > 0 else 0.0
        unique_authors = _count_unique_author_hashes(items)
        vectors = [tuple(m.embedding) for m in items if m.embedding is not None]
        entropy = _shannon_entropy(vectors)
        novelty = _novelty_fraction(vectors)
        engagement = compute_audience_engagement(
            message_rate_per_min=rate_per_min,
            chat_entropy=entropy,
            chat_novelty=novelty,
            unique_authors_60s=unique_authors,
            high_value_queue_depth=high_value_queue_depth,
        )
        t4p_rate, t4p_unique, t5_rate, t6_rate = self._tier_aggregates(now=now)
        return ChatSignals(
            window_seconds=window_seconds,
            window_end_ts=now,
            message_count_60s=count,
            message_rate_per_min=round(rate_per_min, 3),
            unique_authors_60s=unique_authors,
            chat_entropy=round(entropy, 4),
            chat_novelty=round(novelty, 4),
            high_value_queue_depth=high_value_queue_depth,
            audience_engagement=round(engagement, 4),
            t4_plus_rate_per_min=round(t4p_rate, 3),
            unique_t4_plus_authors_60s=t4p_unique,
            t5_rate_per_min=round(t5_rate, 3),
            t6_rate_per_min=round(t6_rate, 3),
        )

    def write_shm(self, signals: ChatSignals) -> None:
        """Atomically write ``signals`` to the configured output path."""
        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(signals), sort_keys=True)
        tmp_fd, tmp_path_s = tempfile.mkstemp(
            prefix=f".{self._output_path.name}.",
            suffix=".tmp",
            dir=str(self._output_path.parent),
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path_s, self._output_path)
        except Exception:
            tmp_path = Path(tmp_path_s)
            if tmp_path.exists():
                tmp_path.unlink()
            raise


def _count_unique_author_hashes(items: list[ChatMessage]) -> int:
    seen: set[str] = set()
    for msg in items:
        seen.add(hashlib.sha256(msg.author_handle.encode("utf-8")).hexdigest()[:16])
    return len(seen)
