"""Snapshot the FileStore secret-name set and compute arrival/departure deltas.

Lists the store's ``<name>.bin`` blob names through ``shared.secrets.list_secret_names``,
yielding NAMES only (the mapped form ``hapax-secret --list`` prints, e.g. ``api-anthropic``).
Never opens or decrypts a blob, never resolves a value, never touches pass. Never
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

from shared.secrets import list_secret_names, secret_store_root

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Snapshot:
    """Point-in-time view of the FileStore secret-name set.

    Attributes:
        entries: Sorted tuple of secret names (no values, no .bin suffix).
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


def walk_secret_store(root: Path | None = None) -> Snapshot:
    """List the FileStore and return a Snapshot of secret names.

    Reads only the store directory's blob filenames. Never opens or decrypts a blob. ``root``
    names an explicit store directory (tests, a replica); otherwise the host's FileStore, or
    ``hapax-secret --list`` where the module is absent. A missing store yields an empty
    snapshot (the absence is itself the signal — no names means no services unblocked).
    """
    captured_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    target = root if root is not None else secret_store_root()
    if target is not None and not target.is_dir():
        log.warning("secret store missing at %s", target)
        return Snapshot(entries=(), captured_at=captured_at, store_path=str(target))
    names = list_secret_names(target)
    return Snapshot(
        entries=tuple(sorted(names)),
        captured_at=captured_at,
        store_path=str(target) if target is not None else "hapax-secret --list",
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
