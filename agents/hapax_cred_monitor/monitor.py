"""Snapshot the password-store entry set and compute arrival/departure deltas.

Walks ``~/.password-store/`` for ``.gpg`` files, yielding entry NAMES only.
Never opens, decrypts, or shells out to ``gpg`` / ``pass show``. Never
returns or logs values. The snapshot is a sorted tuple of strings; the
delta is a pair of frozensets (arrived, departed).

The state file at ``~/.cache/hapax/cred-watch-state.json`` is the durable
boundary for delta computation across timer firings; ``compute_delta``
takes prior + current snapshot and returns the diff without consulting
the file system.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_PASS_STORE = Path.home() / ".password-store"


@dataclass(frozen=True)
class Snapshot:
    """Point-in-time view of the password-store entry set.

    Attributes:
        entries: Sorted tuple of entry names (no values, no .gpg suffix).
        captured_at: UTC ISO-8601 timestamp of the walk.
        store_path: The directory walked (recorded for diagnostics).
    """

    entries: tuple[str, ...] = field(default_factory=tuple)
    captured_at: str = ""
    store_path: str = ""

    def as_set(self) -> frozenset[str]:
        return frozenset(self.entries)


@dataclass(frozen=True)
class Delta:
    """Difference between two snapshots.

    ``arrived`` is the set of entry names present in the current
    snapshot but not the prior one. ``departed`` is the inverse.
    """

    arrived: frozenset[str] = field(default_factory=frozenset)
    departed: frozenset[str] = field(default_factory=frozenset)

    def is_change(self) -> bool:
        return bool(self.arrived) or bool(self.departed)


def walk_pass_store(store: Path = DEFAULT_PASS_STORE) -> Snapshot:
    """Walk the pass store and return a Snapshot of entry names.

    Reads only directory structure and ``.gpg`` filenames. Never opens
    or decrypts a file. If the store is missing, returns an empty
    snapshot (the absence is itself the signal — no entries means no
    services unblocked).
    """
    captured_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not store.is_dir():
        log.warning("pass store missing at %s", store)
        return Snapshot(entries=(), captured_at=captured_at, store_path=str(store))

    names: list[str] = []
    for gpg_path in store.rglob("*.gpg"):
        try:
            rel = gpg_path.relative_to(store)
        except ValueError:
            continue
        # Drop the .gpg suffix; preserve the relative path as the entry name.
        name = str(rel.with_suffix(""))
        names.append(name)
    return Snapshot(
        entries=tuple(sorted(names)),
        captured_at=captured_at,
        store_path=str(store),
    )


def compute_delta(prior: Snapshot, current: Snapshot) -> Delta:
    """Return arrival/departure delta between two snapshots.

    Pure function over snapshot data. Does not touch disk.
    """
    prior_set = prior.as_set()
    current_set = current.as_set()
    return Delta(
        arrived=current_set - prior_set,
        departed=prior_set - current_set,
    )
