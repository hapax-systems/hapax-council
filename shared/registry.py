"""Generic typed Registry[Record, Key] — the KIND-0 substrate (derivation-substrate MOVE 2).

~50 stores (worktree_registry, team_registry, pr_registry, platform_capability_receipts, coord_event_log,
evidence_ledger, …) each hand-roll atomic-write + ABSENT-vs-CORRUPT reads + freshness + (sometimes) a
reaper. This is the ONE framework they parameterize instead — so boutique becomes UNAVAILABLE, not
merely discouraged.

The MANDATORY (classify, is_reapable) pair is enforced by construction: they are abstract, so a Registry
subclass CANNOT be instantiated without them. A persisted concept therefore ships with its lifecycle
terminator (a reaper) or not at all — Work-Unit Totality by construction.

Stdlib-only at import (the reaper path runs under bare system python3 with no project venv): the record
is (de)serialized by a codec the subclass supplies (to_json/from_json), so a pydantic OR a plain
dataclass record both work WITHOUT this module importing pydantic — mirroring worktree_registry's
deliberate dataclass choice.
"""

from __future__ import annotations

import os
import sys
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path


class Registry[R, K](ABC):
    """A durable per-object store keyed by ``K`` over records of type ``R`` (a pydantic model, a plain
    dataclass, … — opaque to the framework; the subclass's codec handles it).

    A subclass supplies the record CODEC + KEY (``to_json``/``from_json``/``key_of``/``slug``) and the
    MANDATORY reaper pair (``classify``/``is_reapable``). It gets atomic writes, fail-closed corruption
    isolation, and listing for free. See ``shared.worktree_registry`` for the exemplar this generalizes.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    # ── codec + key contract (record-type + key) ────────────────────────────────
    @abstractmethod
    def to_json(self, record: R) -> str:
        """Serialize a record to the exact text persisted on disk."""

    @abstractmethod
    def from_json(self, raw: str) -> R:
        """Parse persisted text back into a record. MUST raise on malformed input (so corruption is
        detectable) — never return a partial/default record."""

    @abstractmethod
    def key_of(self, record: R) -> K:
        """The record's identity key (the registry is keyed by it)."""

    @abstractmethod
    def slug(self, key: K) -> str:
        """A filesystem-safe single token for ``key`` (it lands verbatim in the record filename)."""

    # ── the MANDATORY lifecycle pair — Work-Unit Totality by construction ────────
    @abstractmethod
    def classify(self, record: R, **signals: object) -> str:
        """Derive the record's explicit lifecycle status from live ``signals``. Deriving status (not
        scraping/asserting it) is the KIND-2 cure; every store must answer 'what state is this in?'."""

    @abstractmethod
    def is_reapable(self, status: str, **signals: object) -> bool:
        """Whether a record in ``status`` may be terminated. Reap by EXPLICIT status only, never by
        inference. Its mere existence is the point: a store cannot be defined without a reaper."""

    # ── store mechanics (atomic write · fail-closed read · corruption isolation) ─
    def path_for(self, key: K) -> Path:
        slug = self.slug(key)
        if not slug or "/" in slug or os.sep in slug or slug in (".", ".."):
            raise ValueError(
                f"unsafe slug {slug!r} for key {key!r} — would escape the registry dir"
            )
        return self._root / f"{slug}.json"

    def read(self, key: K) -> tuple[R | None, bool]:
        """``(record, corrupt)``. ABSENT = ``(None, False)`` (no file); CORRUPT = ``(None, True)`` (file
        present but unparseable). Conflating the two is the fail-OPEN hole. Warns on corruption."""
        path = self.path_for(key)
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None, False
        try:
            return self.from_json(raw), False
        except Exception as exc:  # noqa: BLE001 — any parse failure is corruption; fail closed
            print(
                f"hapax-registry[{type(self).__name__}]: WARN unparseable record {path}: {exc} — "
                f"fail-closed (protected from overwrite/reaping until repaired)",
                file=sys.stderr,
            )
            return None, True

    def load(self, key: K) -> R | None:
        """Best-effort read: the record, or ``None`` if ABSENT or CORRUPT (corruption is warned).
        Callers that must NOT clobber a corrupt record (a safe upsert) use ``read`` to tell them apart."""
        return self.read(key)[0]

    def save(self, record: R) -> None:
        """Atomic per-object write: a temp file in the SAME dir + ``os.replace`` (never a torn read)."""
        path = self.path_for(self.key_of(record))
        data = self.to_json(record)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".reg-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(data)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def deregister(self, key: K) -> None:
        try:
            self.path_for(key).unlink()
        except FileNotFoundError:
            pass

    def list_records(self) -> list[R]:
        """All PARSEABLE records. Corrupt files are skipped with a per-file warning AND an aggregate
        count (never silently), so a single malformed record can never collapse the whole store into
        emptiness/None (the C2 crash class). Callers that must ACT on corruption use ``read`` per key."""
        out: list[R] = []
        corrupt = 0
        for fp in sorted(self._root.glob("*.json")):
            try:
                out.append(self.from_json(fp.read_text(encoding="utf-8")))
            except Exception as exc:  # noqa: BLE001 — isolate the bad record, never crash the store
                corrupt += 1
                print(
                    f"hapax-registry[{type(self).__name__}]: WARN skipping corrupt record {fp}: {exc}",
                    file=sys.stderr,
                )
        if corrupt:
            print(
                f"hapax-registry[{type(self).__name__}]: WARN list_records skipped {corrupt} corrupt "
                f"record(s) (fail-closed: they stay protected; repair with rm + re-register)",
                file=sys.stderr,
            )
        return out
