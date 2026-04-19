"""shared/text_repo.py — Hapax-managed Pango overlay content repository (task #126).

Curated text entries the operator has chosen to surface on the livestream
Pango overlay zones, with context-aware selection so Hapax can rotate what
appears based on activity / stance / scene rather than cycling every file
in a folder alphabetically.

Replaces the filesystem-folder-scan content source previously used by the
overlay zone manager. The Obsidian note folder scan remains as a fallback
and seed path — ``scripts/seed-text-repo.py`` walks the folder once to
convert existing notes into :class:`TextEntry` records.

Persistence: newline-delimited JSON (JSONL) at
``~/hapax-state/text-repo/entries.jsonl``. Writes use ``O_APPEND | O_CREAT``
so concurrent writers from multiple processes produce well-formed lines
(POSIX atomic append for writes under PIPE_BUF; our entries sit well under).

**Single-operator invariant (axiom: single_user).** The repo carries no
user_id, no per-user state, no multi-user code. One operator; one
workstation.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "DEFAULT_REPO_PATH",
    "TEXT_ENTRY_MAX_BODY_LEN",
    "TextEntry",
    "TextRepo",
]

log = logging.getLogger(__name__)

DEFAULT_REPO_PATH: Path = Path.home() / "hapax-state" / "text-repo" / "entries.jsonl"

# Per-entry body size cap. Pango layouts for overlay zones stay legible at
# a few hundred chars; this cap is defense-in-depth against someone pasting
# an entire markdown file into a sidechat ``add-text`` command.
TEXT_ENTRY_MAX_BODY_LEN: int = 4096

# Entries shown within this many seconds are down-weighted during selection
# so the overlay doesn't re-cycle the same entry back-to-back.
_RECENT_SHOW_WINDOW_S: float = 300.0
_RECENT_SHOW_PENALTY: float = 0.6


class TextEntry(BaseModel):
    """One Pango overlay text entry.

    ``context_keys`` are soft filters: an entry with ``context_keys=["study"]``
    scores higher when the current activity/stance/scene matches ``"study"``
    but is still eligible (at a reduced score) when nothing matches. An
    entry with no ``context_keys`` is always-on (acts like the old
    folder-scan default).

    Validation fails closed: body must be non-empty and under
    :data:`TEXT_ENTRY_MAX_BODY_LEN`, priority clamped to [0, 10], expiry if
    present must be a valid unix timestamp (accepted as-is; the selection
    path discards expired entries).
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        default_factory=lambda: uuid.uuid4().hex[:12],
        description="Opaque id used for dedup / mark-shown cursor.",
    )
    body: str = Field(description="Pango-markup or plain text body.")
    tags: list[str] = Field(
        default_factory=list,
        description="Free-form tags (persona/theme). Normalized to lowercase.",
    )
    priority: int = Field(
        default=5,
        ge=0,
        le=10,
        description="Selection priority 0..10. Higher wins ties.",
    )
    expires_ts: float | None = Field(
        default=None,
        description="Unix ts past which the entry is excluded. None = never expires.",
    )
    context_keys: list[str] = Field(
        default_factory=list,
        description=(
            "Soft context filters: activity, stance, scene, package. "
            "Lowercase-normalized. Empty list = always-on."
        ),
    )
    last_shown_ts: float | None = Field(
        default=None,
        description="Unix ts the entry was most recently rendered on-screen.",
    )
    show_count: int = Field(
        default=0,
        ge=0,
        description="How many times ``mark_shown`` has been invoked for this entry.",
    )

    @field_validator("body")
    @classmethod
    def _validate_body(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("text entry body must be non-empty")
        if len(v) > TEXT_ENTRY_MAX_BODY_LEN:
            raise ValueError(
                f"text entry body exceeds {TEXT_ENTRY_MAX_BODY_LEN} chars (got {len(v)})"
            )
        return v

    @field_validator("tags", "context_keys")
    @classmethod
    def _normalize_string_list(cls, v: list[str]) -> list[str]:
        seen: dict[str, None] = {}
        for t in v:
            key = t.strip().lower()
            if key:
                seen.setdefault(key, None)
        return list(seen)

    def is_expired(self, now: float | None = None) -> bool:
        """True when ``expires_ts`` is set and past."""
        if self.expires_ts is None:
            return False
        ts_now = now if now is not None else time.time()
        return ts_now >= self.expires_ts


class TextRepo:
    """In-memory pool of :class:`TextEntry` records with JSONL persistence.

    The repo is append-first: :meth:`add_entry` writes a new line atomically
    via ``O_APPEND``. :meth:`mark_shown` updates in-memory state and
    periodically rewrites the JSONL (tmp + rename) to persist ``last_shown_ts``
    / ``show_count`` without risking torn writes.

    Loading is idempotent; later lines with the same ``id`` replace
    earlier ones (so rewriting on mark_shown compacts the log naturally).
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path: Path = path if path is not None else DEFAULT_REPO_PATH
        self._by_id: dict[str, TextEntry] = {}

    # ── persistence ──────────────────────────────────────────────────

    def load(self) -> int:
        """Load the repo from JSONL. Returns number of records loaded.

        Later records with the same id replace earlier ones — so the
        JSONL can be used as an append-only log and the in-memory state
        still reflects the latest show counts.
        """
        self._by_id.clear()
        if not self.path.exists():
            return 0
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            log.debug("Failed to read text repo %s", self.path, exc_info=True)
            return 0
        for raw in text.splitlines():
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
                entry = TextEntry.model_validate(obj)
                self._by_id[entry.id] = entry
            except Exception:
                log.debug("Skipping malformed text-repo line: %s", stripped[:80])
        return len(self._by_id)

    def save(self) -> None:
        """Rewrite the JSONL atomically (tmp + rename).

        Used to compact the append-only log after mark_shown updates,
        and by tests that want a clean starting state.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        lines = [e.model_dump_json() for e in self._by_id.values()]
        tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        tmp.replace(self.path)

    def _append_line(self, entry: TextEntry) -> None:
        """Append one entry to the JSONL via ``O_APPEND``."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = (entry.model_dump_json() + "\n").encode("utf-8")
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)

    # ── mutation ─────────────────────────────────────────────────────

    def add_entry(
        self,
        body: str,
        *,
        tags: Iterable[str] | None = None,
        priority: int = 5,
        expires_ts: float | None = None,
        context_keys: Iterable[str] | None = None,
        entry_id: str | None = None,
    ) -> TextEntry:
        """Create and persist a new :class:`TextEntry`.

        Returns the record as written. Raises ``pydantic.ValidationError``
        when the body fails validation — callers should surface that to
        the operator (sidechat reply, ntfy).
        """
        kwargs: dict[str, Any] = {
            "body": body,
            "tags": list(tags) if tags is not None else [],
            "priority": priority,
            "expires_ts": expires_ts,
            "context_keys": list(context_keys) if context_keys is not None else [],
        }
        if entry_id is not None:
            kwargs["id"] = entry_id
        entry = TextEntry(**kwargs)
        self._by_id[entry.id] = entry
        self._append_line(entry)
        return entry

    def upsert(self, entry: TextEntry) -> None:
        """Insert or replace an entry by id (in-memory; callers save)."""
        self._by_id[entry.id] = entry

    def remove(self, entry_id: str) -> bool:
        """Drop an entry by id. Returns True if present."""
        return self._by_id.pop(entry_id, None) is not None

    def all_entries(self) -> list[TextEntry]:
        """Return a list copy of every entry currently in the repo."""
        return list(self._by_id.values())

    # ── selection ────────────────────────────────────────────────────

    def select_for_context(
        self,
        activity: str = "",
        stance: str = "",
        scene: str = "",
        *,
        now: float | None = None,
    ) -> TextEntry | None:
        """Pick the best entry for the supplied context, or ``None`` if empty.

        Scoring (all contributions additive):

        * Priority: ``entry.priority / 10.0`` (0..1).
        * Context match: ``+0.5`` per ``context_keys`` hit against the
          lowercase ``activity`` / ``stance`` / ``scene`` tokens. Empty
          ``context_keys`` contributes 0 — the always-on entries still
          score via priority and are never excluded on context grounds.
        * Recency penalty: entries shown within the last
          :data:`_RECENT_SHOW_WINDOW_S` seconds get
          ``score *= _RECENT_SHOW_PENALTY``.

        Expired entries (``is_expired(now)``) are filtered out entirely.
        Ties broken by lower ``show_count`` (less-seen entries float up).
        """
        ts_now = now if now is not None else time.time()
        ctx = {c.strip().lower() for c in (activity, stance, scene) if c}

        best: tuple[float, int, str, TextEntry] | None = None
        for entry in self._by_id.values():
            if entry.is_expired(ts_now):
                continue
            score = entry.priority / 10.0
            if entry.context_keys and ctx:
                hits = sum(1 for k in entry.context_keys if k in ctx)
                score += 0.5 * hits
            if (
                entry.last_shown_ts is not None
                and ts_now - entry.last_shown_ts < _RECENT_SHOW_WINDOW_S
            ):
                score *= _RECENT_SHOW_PENALTY
            # Ranking: higher score wins; on ties prefer fewer shows, then
            # id lexicographically for determinism. The entry itself sits
            # at position 3 and is never compared (earlier fields always
            # break the tie).
            key = (score, -entry.show_count, entry.id, entry)
            if best is None or key > best:
                best = key
        return best[3] if best is not None else None

    def mark_shown(self, entry_id: str, *, when: float | None = None) -> TextEntry | None:
        """Record that ``entry_id`` was rendered on-screen.

        Returns the updated entry, or ``None`` if the id is unknown.
        Compacts the JSONL (tmp + rename) so the persisted file mirrors
        the latest ``last_shown_ts`` / ``show_count`` without leaving a
        growing tail of stale updates.
        """
        prior = self._by_id.get(entry_id)
        if prior is None:
            return None
        ts = when if when is not None else time.time()
        updated = prior.model_copy(
            update={
                "last_shown_ts": ts,
                "show_count": prior.show_count + 1,
            }
        )
        self._by_id[entry_id] = updated
        try:
            self.save()
        except OSError:
            log.debug("Failed to persist text-repo mark-shown for %s", entry_id, exc_info=True)
        return updated

    # ── iteration helpers ────────────────────────────────────────────

    def __iter__(self) -> Iterator[TextEntry]:
        return iter(self._by_id.values())

    def __len__(self) -> int:
        return len(self._by_id)

    def __contains__(self, entry_id: object) -> bool:
        return isinstance(entry_id, str) and entry_id in self._by_id
