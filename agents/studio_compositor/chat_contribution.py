"""chat_contribution.py — Viewer chat contribution ledger for the token pole.

Task #146. The token pole (Vitruvian man) visualises Hapax's token
spend budget. Viewers who contribute chat signal deserve a visible
reward — when cumulative contribution over a rolling 60s window
crosses a threshold, the pole fires an emoji-spew cascade and a brief
BitchX-grammar contributor marker.

Design constraints (task #147 governance qualifier):

* **Subtle, not manipulative.** Threshold + brief 6-second cascade;
  per-author diminishing returns make spam unrewarding.
* **Privacy-first.** Author identity is hashed via SHA-256 with a
  per-session salt (``HAPAX_CHAT_HASH_SALT``). The raw name is never
  retained, logged, or written to disk. The ledger stores only
  ``(author_hash, score, ts)`` tuples.
* **Rising-edge threshold.** Crossing is only signalled once per
  cascade — the ledger remembers the high-water mark so a sustained
  high contribution doesn't re-trigger on every read.

The ledger is tick-idempotent and thread-safe under the GIL for the
expected arrival rates (~O(10) events/sec on a busy stream). Callers
push events via :meth:`record_chat` and poll for cascades via
:meth:`cross_reward_threshold`.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import NamedTuple

__all__ = [
    "ChatContributionLedger",
    "ContributionSnapshot",
    "resolve_salt",
    "hash_author",
]

log = logging.getLogger(__name__)

# Rolling window for the contribution total (seconds).
DEFAULT_WINDOW_SECONDS = 60.0

# Threshold at which the reward cascade fires.
DEFAULT_REWARD_THRESHOLD = 50.0

# Base contribution score per message.
_BASE_SCORE = 1.0

# Bonus caps out at +5 for messages >=200 chars.
_LENGTH_BONUS_CAP = 5.0
_LENGTH_BONUS_THRESHOLD = 200.0

# Per-author diminishing returns: the Nth message from the same author
# (within the window) multiplies its score by this factor. Anything
# beyond index len(_DIMINISHING)-1 reuses the last entry.
_DIMINISHING: tuple[float, ...] = (
    1.0,  # 1st message
    1.0,  # 2nd
    1.0,  # 3rd
    1.0,  # 4th
    0.5,  # 5th
    0.5,  # 6th
    0.5,  # 7th
    0.5,  # 8th
    0.5,  # 9th
    0.1,  # 10th+
)


class ContributionSnapshot(NamedTuple):
    """Immutable snapshot of a reward event.

    Emitted by :meth:`ChatContributionLedger.cross_reward_threshold` on
    the rising edge. The snapshot carries only counts — never names,
    never message bodies.
    """

    explosion_number: int
    total_score: float
    unique_contributor_count: int
    window_seconds: float


# Generated once per process; callers can override via env before the
# first import.
_PROCESS_SALT: bytes = secrets.token_bytes(32)


def resolve_salt() -> bytes:
    """Return the salt to mix into author hashes.

    Precedence:
    1. ``HAPAX_CHAT_HASH_SALT`` env var (bytes, utf-8 decoded).
    2. A per-process random salt generated at module import time.

    The per-process fallback means two independent runs never produce
    the same hash for the same author — any correlation attempt across
    stream sessions also requires knowing that run's salt.
    """
    env = os.environ.get("HAPAX_CHAT_HASH_SALT")
    if env:
        return env.encode("utf-8")
    return _PROCESS_SALT


def hash_author(author_name: str) -> str:
    """SHA-256(salt || author_name) → 16 hex chars.

    Truncation to 16 hex chars (64 bits) is more than sufficient for
    within-window disambiguation: collisions at 2^32 events are <=1e-10.
    """
    salt = resolve_salt()
    digest = hashlib.sha256(salt + author_name.encode("utf-8")).hexdigest()
    return digest[:16]


@dataclass
class _Event:
    """Internal event row — never exposed to callers."""

    author_hash: str
    score: float
    ts: float


@dataclass
class ChatContributionLedger:
    """Rolling-window ledger of chat contribution scores.

    The ledger is intentionally narrow: only what the token-pole reward
    mechanic needs. It does NOT replace chat queues, classifiers, or
    signal aggregators — those serve other consumers.
    """

    window_seconds: float = DEFAULT_WINDOW_SECONDS
    reward_threshold: float = DEFAULT_REWARD_THRESHOLD
    _events: deque[_Event] = field(default_factory=deque)
    _explosion_count: int = 0
    # Was the prior total above threshold? Used to detect rising edges.
    _was_above_threshold: bool = False

    def record_chat(
        self,
        author_name: str,
        message_length: int,
        ts: float,
    ) -> float:
        """Record a chat event and return the assigned score.

        ``author_name`` is hashed immediately and discarded. The raw
        string never leaves this method — not even to debug logs.
        """
        author_hash = hash_author(author_name)
        self._prune(now=ts)

        # Count prior messages from this author in the current window.
        prior = sum(1 for e in self._events if e.author_hash == author_hash)
        dim_factor = _DIMINISHING[prior] if prior < len(_DIMINISHING) else _DIMINISHING[-1]

        length_bonus = min(
            _LENGTH_BONUS_CAP,
            _LENGTH_BONUS_CAP * (max(0, message_length) / _LENGTH_BONUS_THRESHOLD),
        )
        raw_score = _BASE_SCORE + length_bonus
        final_score = raw_score * dim_factor

        self._events.append(_Event(author_hash=author_hash, score=final_score, ts=ts))
        # Debug log is hash-only by construction. Do not reintroduce the
        # name here — the caplog regression test will fail if you do.
        log.debug(
            "chat-contribution: hash=%s score=%.3f len=%d",
            author_hash,
            final_score,
            message_length,
        )
        return final_score

    def _prune(self, *, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._events and self._events[0].ts < cutoff:
            self._events.popleft()

    def get_contribution_total(self, *, now: float | None = None) -> float:
        """Sum of scores in the current rolling window."""
        if now is not None:
            self._prune(now=now)
        return sum(e.score for e in self._events)

    def unique_contributor_count(self, *, now: float | None = None) -> int:
        """Distinct author hashes in the current window."""
        if now is not None:
            self._prune(now=now)
        return len({e.author_hash for e in self._events})

    def cross_reward_threshold(
        self,
        *,
        now: float,
    ) -> ContributionSnapshot | None:
        """Return a snapshot iff the window total just crossed threshold.

        Rising-edge semantics: if the total was already above threshold
        on the prior call and is still above, returns ``None``. Only
        returns a snapshot when the total transitions from below → at/
        above the threshold.

        Once a snapshot is emitted, ``_explosion_count`` increments and
        the ``_was_above_threshold`` latch flips true. The latch clears
        when the total drops below the threshold again — so the next
        rising crossing re-arms the reward.
        """
        self._prune(now=now)
        total = sum(e.score for e in self._events)

        if total >= self.reward_threshold:
            if self._was_above_threshold:
                return None
            self._was_above_threshold = True
            self._explosion_count += 1
            unique = len({e.author_hash for e in self._events})
            return ContributionSnapshot(
                explosion_number=self._explosion_count,
                total_score=total,
                unique_contributor_count=unique,
                window_seconds=self.window_seconds,
            )

        # Below threshold — clear the latch so the next rising edge arms.
        self._was_above_threshold = False
        return None

    def explosion_count(self) -> int:
        """Total number of cascades fired since the ledger was created."""
        return self._explosion_count

    # ------------------------------------------------------------------
    # Testing / introspection helpers. No names ever exposed.
    # ------------------------------------------------------------------

    def _author_message_counts(self) -> dict[str, int]:
        """Map author_hash -> message count in window. Hash-only."""
        out: dict[str, int] = defaultdict(int)
        for e in self._events:
            out[e.author_hash] += 1
        return dict(out)
