"""Structural chat-message analysis (Phase 9 §3.1).

Four metrics, all structural (no sentiment, no judgment):

* ``participant_diversity`` — unique authors / total messages, in [0, 1].
* ``novelty_rate`` — fraction of bigrams unseen earlier in the window,
  in [0, 1].
* ``thread_count`` — number of embedding-similarity clusters in the
  window (proxy for parallel conversation threads).
* ``semantic_coherence`` — mean pairwise cosine similarity across
  message embeddings in the window, in [0, 1].

The embedding-based metrics (``thread_count``, ``semantic_coherence``)
are gated on an injected ``embedder`` callable. When none is given the
analyzer returns zero for those two rather than pulling in the nomic
embed stack — tests stay hermetic, and prod wires a real embedder at
call time.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass

log = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[A-Za-z0-9]+")


@dataclass(frozen=True)
class ChatMessage:
    """Minimal message shape consumed by the analyzer."""

    author_id: str
    text: str
    ts: float  # epoch seconds


@dataclass(frozen=True)
class StructuralSignals:
    """The 4-number structural snapshot."""

    participant_diversity: float
    novelty_rate: float
    thread_count: int
    semantic_coherence: float
    window_size: int  # number of messages that produced these numbers

    def asdict(self) -> dict[str, float | int]:
        return asdict(self)


Embedder = Callable[[Sequence[str]], list[list[float]]]


# ── Non-embedding metrics ───────────────────────────────────────────────────


def _participant_diversity(messages: Sequence[ChatMessage]) -> float:
    if not messages:
        return 0.0
    unique_authors = len({m.author_id for m in messages if m.author_id})
    return unique_authors / len(messages)


def _bigrams(text: str) -> list[tuple[str, str]]:
    tokens = [t.lower() for t in _WORD_RE.findall(text)]
    if len(tokens) < 2:
        return []
    return list(zip(tokens, tokens[1:], strict=False))


def _novelty_rate(messages: Sequence[ChatMessage]) -> float:
    if not messages:
        return 0.0
    seen: set[tuple[str, str]] = set()
    total = 0
    novel = 0
    for m in messages:
        for bg in _bigrams(m.text):
            total += 1
            if bg not in seen:
                novel += 1
                seen.add(bg)
    if total == 0:
        return 0.0
    return novel / total


# ── Embedding-based metrics ─────────────────────────────────────────────────


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _thread_count(embeddings: list[list[float]], *, similarity_threshold: float = 0.6) -> int:
    """Greedy agglomerative clustering by cosine similarity.

    Each message joins the first existing cluster whose centroid-similarity
    is above ``similarity_threshold``; otherwise starts a new cluster.
    Returns the number of clusters.
    """
    clusters: list[list[list[float]]] = []
    for vec in embeddings:
        joined = False
        for cluster in clusters:
            centroid = [sum(col) / len(cluster) for col in zip(*cluster, strict=False)]
            if _cosine(vec, centroid) >= similarity_threshold:
                cluster.append(vec)
                joined = True
                break
        if not joined:
            clusters.append([vec])
    return len(clusters)


def _semantic_coherence(embeddings: list[list[float]]) -> float:
    """Mean pairwise cosine similarity across all embeddings in the window."""
    n = len(embeddings)
    if n < 2:
        return 0.0
    total = 0.0
    pairs = 0
    for i in range(n):
        for j in range(i + 1, n):
            total += _cosine(embeddings[i], embeddings[j])
            pairs += 1
    return total / pairs if pairs else 0.0


# ── Top-level analyzer ──────────────────────────────────────────────────────


def analyze(
    messages: Sequence[ChatMessage],
    *,
    embedder: Embedder | None = None,
    similarity_threshold: float = 0.6,
) -> StructuralSignals:
    """Compute the four structural metrics for a message window.

    Returns zeros when the window is empty so downstream callers can
    always expect a ``StructuralSignals`` shape. Embedding-dependent
    metrics return zero when no ``embedder`` is provided — the
    structural caller wires one in; tests can pass a pure-python stub.
    """
    if not messages:
        return StructuralSignals(
            participant_diversity=0.0,
            novelty_rate=0.0,
            thread_count=0,
            semantic_coherence=0.0,
            window_size=0,
        )

    pd = _participant_diversity(messages)
    nr = _novelty_rate(messages)

    if embedder is None:
        return StructuralSignals(
            participant_diversity=pd,
            novelty_rate=nr,
            thread_count=0,
            semantic_coherence=0.0,
            window_size=len(messages),
        )

    try:
        embeddings = embedder([m.text for m in messages])
    except Exception:
        log.exception("chat embedder failed — structural embedding metrics set to zero")
        return StructuralSignals(
            participant_diversity=pd,
            novelty_rate=nr,
            thread_count=0,
            semantic_coherence=0.0,
            window_size=len(messages),
        )

    return StructuralSignals(
        participant_diversity=pd,
        novelty_rate=nr,
        thread_count=_thread_count(embeddings, similarity_threshold=similarity_threshold),
        semantic_coherence=_semantic_coherence(embeddings),
        window_size=len(messages),
    )
