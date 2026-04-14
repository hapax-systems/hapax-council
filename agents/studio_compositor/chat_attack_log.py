"""LRR Phase 9 item 4 — T0/T1 attack log writer.

Append-only JSONL log of chat messages that the classifier flagged
as T0 (suspicious_injection) or T1 (harassment). The log lives at
``/dev/shm/hapax-chat-attack-log.jsonl`` so operator telemetry can tail
it live without touching disk.

Constitutional constraints:
- **Ephemeral author handles only.** The caller passes the handle as
  opaque bytes; the log stores it for the lifetime of the current
  process but never writes it to persistent storage. Compliant with
  ``it-broadcast-007`` per Bundle 9 §3.
- **No per-author state beyond the in-process rate-limit counter.**
  The counter is reset on process restart. No database, no on-disk
  serialization, no cross-restart persistence.
- **O_APPEND semantics.** Writes use append mode so multiple writers
  never clobber each other's log lines. SHM files do not need fsync
  (backed by tmpfs).

This module ships the writer library; wiring from the classifier
dispatcher into the writer happens in a Phase 9 follow-up once the
live chat feed integration lands.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

from agents.studio_compositor.chat_classifier import ChatTier, Classification

__all__ = [
    "AttackLogEntry",
    "AttackLogWriter",
    "DEFAULT_ATTACK_LOG_PATH",
]

DEFAULT_ATTACK_LOG_PATH: Final = Path("/dev/shm/hapax-chat-attack-log.jsonl")
"""Bundle 9 §2.3 — canonical attack log path. SHM/tmpfs only."""


@dataclass(frozen=True)
class AttackLogEntry:
    """Single JSONL log line.

    ``author_hash`` is a SHA-256 of the author handle truncated to 16
    hex chars. The hash is deterministic for the life of the process
    but carries no upstream identity beyond the chat platform's opaque
    handle string. This gives the operator enough signal to spot
    repeated attackers without persisting the handle.
    """

    ts: float
    tier: int
    tier_label: str
    reason: str
    author_hash: str
    message_length: int
    message_preview: str


class AttackLogWriter:
    """Append-only writer + in-process rate-limit counter.

    Constitutional note: the rate-limit counter is a plain dict keyed on
    the author hash. It is **not** persisted across restarts. That's
    intentional — persistence would constitute per-author state.
    """

    def __init__(
        self,
        log_path: Path | None = None,
        *,
        preview_chars: int = 120,
        rate_limit_window_seconds: float = 300.0,
        rate_limit_threshold: int = 3,
    ) -> None:
        self._log_path = log_path or DEFAULT_ATTACK_LOG_PATH
        self._preview_chars = preview_chars
        self._rate_limit_window = rate_limit_window_seconds
        self._rate_limit_threshold = rate_limit_threshold
        # author_hash -> list of timestamps within the current window.
        self._rate_tracker: dict[str, list[float]] = defaultdict(list)

    @property
    def log_path(self) -> Path:
        return self._log_path

    def record(
        self,
        *,
        classification: Classification,
        message_text: str,
        author_handle: str,
        timestamp: float | None = None,
    ) -> AttackLogEntry | None:
        """Log the attack and return the entry.

        Returns None if the classification is not a T0/T1 drop. Non-attack
        tiers are silently ignored so callers can route all classifications
        through this writer without branching.
        """
        if classification.tier not in (
            ChatTier.T0_SUSPICIOUS_INJECTION,
            ChatTier.T1_HARASSMENT,
        ):
            return None

        ts = timestamp if timestamp is not None else time.time()
        author_hash = _hash_handle(author_handle)

        entry = AttackLogEntry(
            ts=ts,
            tier=int(classification.tier),
            tier_label=classification.tier.label,
            reason=classification.reason,
            author_hash=author_hash,
            message_length=len(message_text),
            message_preview=message_text[: self._preview_chars],
        )

        self._append(entry)
        self._update_rate_tracker(author_hash, ts)
        return entry

    def is_rate_limited(self, author_handle: str, *, now: float | None = None) -> bool:
        """Return True if the author exceeded ``rate_limit_threshold`` within the window."""
        author_hash = _hash_handle(author_handle)
        now_ts = now if now is not None else time.time()
        self._prune_stale(author_hash, now_ts)
        return len(self._rate_tracker[author_hash]) >= self._rate_limit_threshold

    def rate_count(self, author_handle: str, *, now: float | None = None) -> int:
        """Return the current attack count within the rate-limit window."""
        author_hash = _hash_handle(author_handle)
        now_ts = now if now is not None else time.time()
        self._prune_stale(author_hash, now_ts)
        return len(self._rate_tracker[author_hash])

    def _append(self, entry: AttackLogEntry) -> None:
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry)) + "\n")

    def _update_rate_tracker(self, author_hash: str, ts: float) -> None:
        self._prune_stale(author_hash, ts)
        self._rate_tracker[author_hash].append(ts)

    def _prune_stale(self, author_hash: str, now: float) -> None:
        cutoff = now - self._rate_limit_window
        self._rate_tracker[author_hash] = [
            t for t in self._rate_tracker[author_hash] if t >= cutoff
        ]


def _hash_handle(handle: str) -> str:
    """16-char hex SHA-256 of the author handle. Per Bundle 9 §3 privacy note."""
    return hashlib.sha256(handle.encode("utf-8")).hexdigest()[:16]
