"""LRR Phase 9 item 2 — tiered chat queues.

Three queue types, each with a distinct sampling + eviction policy,
per Bundle 9 §2.3:

- ``HighValueQueue`` (T6 high_value): capacity 5, FIFO eviction,
  top-3 read per director tick. Reaches Hapax's prompt directly.
- ``ResearchRelevantQueue`` (T5 research_relevant): capacity 30,
  embedding-importance eviction, top-5 read per tick. Reaches the
  prompt as a digest.
- ``StructuralSignalQueue`` (T4 structural_signal): unbounded within
  a rolling 60s window, time-based eviction. NOT sampled directly;
  aggregated into stimmung ``audience_engagement`` by
  ``chat_signals.py``.

The embedding function for ``ResearchRelevantQueue`` is pluggable —
this module ships a deterministic fake embedder used in tests; the
production integration with ``nomic-embed-text`` is a Phase 9 v2 task
when the small-model classifier path is wired.

Constitutional constraints (same as chat_classifier):

- No per-author state. The queues store the message text + opaque
  author handle for display-only purposes; the handle is never
  cross-referenced or persisted. Compliant with
  ``interpersonal_transparency``.
- No sentiment ranking. Importance is structural (cosine similarity
  to current research focus) not affective.
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from agents.studio_compositor.chat_classifier import ChatTier, Classification

__all__ = [
    "ChatMessage",
    "HighValueQueue",
    "ResearchRelevantQueue",
    "StructuralSignalQueue",
    "EmbeddingFn",
    "fake_embedder",
]


# Pluggable embedding function type. Returns a fixed-length list of floats.
EmbeddingFn = Callable[[str], list[float]]


@dataclass(frozen=True)
class ChatMessage:
    """A classified chat message, ready for queue routing.

    ``embedding`` is None until the queue (or a caller) invokes the
    embedding function. The fake embedder used in tests is deterministic
    so queue eviction tests are stable.
    """

    text: str
    author_handle: str
    ts: float
    classification: Classification
    embedding: tuple[float, ...] | None = None


def fake_embedder(text: str) -> list[float]:
    """Deterministic 8-dimensional hash-based embedding.

    NOT for production — just enough structure that embedding-importance
    tests are reproducible. Real integration uses ``nomic-embed-text``
    via the existing Ollama CPU pipeline (Phase 9 v2 task).
    """
    vec = [0.0] * 8
    for i, ch in enumerate(text.encode("utf-8")):
        vec[i % 8] += (ch - 64) / 32.0
    # Normalize
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cosine(a: Iterable[float], b: Iterable[float]) -> float:
    a_list = list(a)
    b_list = list(b)
    if len(a_list) != len(b_list):
        return 0.0
    dot = sum(x * y for x, y in zip(a_list, b_list, strict=False))
    na = math.sqrt(sum(x * x for x in a_list))
    nb = math.sqrt(sum(y * y for y in b_list))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


# ---------------------------------------------------------------------------
# Queue A — HighValueQueue (T6)
# ---------------------------------------------------------------------------


@dataclass
class HighValueQueue:
    """FIFO queue for T6 messages, capacity 5, top-3 per tick.

    These are the rare, high-signal chat messages: explicit citations,
    corrections, novel observations. They reach Hapax's prompt directly
    with minimal transformation.
    """

    capacity: int = 5
    _items: deque[ChatMessage] = field(default_factory=deque)

    def push(self, message: ChatMessage) -> None:
        if message.classification.tier != ChatTier.T6_HIGH_VALUE:
            raise ValueError(
                f"HighValueQueue only accepts T6 messages, got {message.classification.tier}"
            )
        self._items.append(message)
        while len(self._items) > self.capacity:
            self._items.popleft()

    def sample(self, top_k: int = 3) -> list[ChatMessage]:
        """Return up to ``top_k`` oldest messages (FIFO order)."""
        return list(self._items)[:top_k]

    def __len__(self) -> int:
        return len(self._items)

    def clear(self) -> None:
        self._items.clear()


# ---------------------------------------------------------------------------
# Queue B — ResearchRelevantQueue (T5) with embedding-importance eviction
# ---------------------------------------------------------------------------


@dataclass
class ResearchRelevantQueue:
    """Bounded queue with embedding-importance eviction (Bundle 9 §2.4).

    When the queue is full and a new message arrives:
    1. Compute an importance score for every queued message (and the new
       one) as ``cosine_similarity(message.embedding, focus_vector) +
       recency_bonus(age_seconds)``.
    2. Drop the lowest-scoring message.
    3. Top-K sampling returns the highest-scoring messages in score order.

    The focus vector is set by the caller via ``update_focus_vector`` and
    is recomputed every 30s in the production closed loop. The recency
    bonus is ``0.2 * exp(-age_seconds / 60)`` per Bundle 9 §2.4.
    """

    capacity: int = 30
    embedder: EmbeddingFn = field(default=fake_embedder)
    _items: list[ChatMessage] = field(default_factory=list)
    _focus_vector: tuple[float, ...] | None = None

    def update_focus_vector(self, focus_vector: Iterable[float] | None) -> None:
        """Set the current research focus embedding. None disables similarity."""
        self._focus_vector = tuple(focus_vector) if focus_vector is not None else None

    def push(self, message: ChatMessage, *, now: float | None = None) -> None:
        if message.classification.tier != ChatTier.T5_RESEARCH_RELEVANT:
            raise ValueError(
                f"ResearchRelevantQueue only accepts T5 messages, got {message.classification.tier}"
            )
        if message.embedding is None:
            embedding = tuple(self.embedder(message.text))
            message = ChatMessage(
                text=message.text,
                author_handle=message.author_handle,
                ts=message.ts,
                classification=message.classification,
                embedding=embedding,
            )
        self._items.append(message)
        if len(self._items) > self.capacity:
            self._evict_lowest(now=now or time.time())

    def sample(self, *, top_k: int = 5, now: float | None = None) -> list[ChatMessage]:
        """Return the top-K highest-importance messages."""
        now_ts = now or time.time()
        scored = [(self._score(m, now_ts), m) for m in self._items]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [m for _, m in scored[:top_k]]

    def __len__(self) -> int:
        return len(self._items)

    def clear(self) -> None:
        self._items.clear()

    def _score(self, message: ChatMessage, now: float) -> float:
        similarity = 0.0
        if self._focus_vector is not None and message.embedding is not None:
            similarity = _cosine(message.embedding, self._focus_vector)
        age = max(0.0, now - message.ts)
        recency_bonus = 0.2 * math.exp(-age / 60.0)
        return similarity + recency_bonus

    def _evict_lowest(self, *, now: float) -> None:
        if not self._items:
            return
        worst_idx = min(range(len(self._items)), key=lambda i: self._score(self._items[i], now))
        del self._items[worst_idx]


# ---------------------------------------------------------------------------
# Queue C — StructuralSignalQueue (T4) with time-window eviction
# ---------------------------------------------------------------------------


@dataclass
class StructuralSignalQueue:
    """Rolling 60s window queue for T4 messages.

    Not sampled directly — the caller is ``chat_signals.py`` which
    computes aggregate features (count, rate, unique authors count,
    entropy, novelty, topic distribution) from the current window.

    Eviction is purely time-based: messages older than
    ``window_seconds`` are dropped whenever ``prune`` is called or a
    new message arrives.
    """

    window_seconds: float = 60.0
    _items: list[ChatMessage] = field(default_factory=list)

    def push(self, message: ChatMessage) -> None:
        if message.classification.tier != ChatTier.T4_STRUCTURAL_SIGNAL:
            raise ValueError(
                f"StructuralSignalQueue only accepts T4 messages, got {message.classification.tier}"
            )
        self.prune(now=message.ts)
        self._items.append(message)

    def prune(self, *, now: float) -> None:
        cutoff = now - self.window_seconds
        self._items = [m for m in self._items if m.ts >= cutoff]

    def window_items(self, *, now: float | None = None) -> list[ChatMessage]:
        self.prune(now=now or time.time())
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def clear(self) -> None:
        self._items.clear()
