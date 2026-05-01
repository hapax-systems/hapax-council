"""Operator-unblockers report: structured JSON of present + missing creds.

Reads the current snapshot, intersects with the expected-entry registry,
emits a report at ``~/.cache/hapax/cred-watch-state.json``. Also appends
arrival/departure events to ``~/.cache/hapax/cred-arrival-log.jsonl``.

The report is the canonical operator-unblockers surface: dashboards,
nudges, and the SessionStart preamble all read this single file.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .monitor import Delta, Snapshot
from .registry import (
    EXPECTED_ENTRIES,
    CategoryView,
    ExpectedEntry,
    categorize,
    expected_entry_names,
    lookup,
    services_unblocked_by,
)

log = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "hapax"
STATE_FILENAME = "cred-watch-state.json"
ARRIVAL_LOG_FILENAME = "cred-arrival-log.jsonl"


@dataclass(frozen=True)
class MissingCredItem:
    """One actionable unblocker entry for the operator dashboard.

    Entry-NAME-only payload; no values, ever. ``remediation`` is the
    canonical ``pass insert <name>`` command — never a sample value.
    """

    entry_name: str
    category: str
    unblocks: tuple[str, ...]
    remediation: str
    notes: str = ""


@dataclass(frozen=True)
class UnblockerReport:
    """Snapshot of credential state + actionable unblocker list.

    The report is value-free: every field is either an entry NAME, a
    service identifier, a count, a timestamp, or a remediation command.
    """

    captured_at: str
    store_path: str
    expected_count: int
    present_entries: tuple[str, ...]
    missing_entries: tuple[str, ...]
    unexpected_entries: tuple[str, ...]
    services_unblocked: tuple[str, ...]
    missing_unblockers: tuple[MissingCredItem, ...]
    by_category: tuple[CategoryView, ...]

    def to_json(self) -> str:
        payload = {
            "captured_at": self.captured_at,
            "store_path": self.store_path,
            "expected_count": self.expected_count,
            "present_count": len(self.present_entries),
            "missing_count": len(self.missing_entries),
            "present_entries": list(self.present_entries),
            "missing_entries": list(self.missing_entries),
            "unexpected_entries": list(self.unexpected_entries),
            "services_unblocked": list(self.services_unblocked),
            "missing_unblockers": [asdict(item) for item in self.missing_unblockers],
            "by_category": [asdict(view) for view in self.by_category],
        }
        return json.dumps(payload, indent=2, sort_keys=True)


def build_report(snapshot: Snapshot) -> UnblockerReport:
    """Construct an UnblockerReport from a Snapshot + the canonical registry.

    Does not touch the file system.
    """
    expected = expected_entry_names()
    actual = snapshot.as_set()
    present = expected & actual
    missing = expected - actual
    unexpected = actual - expected  # entries in pass store but not in registry

    missing_items = tuple(
        sorted(
            (
                MissingCredItem(
                    entry_name=entry.name,
                    category=entry.category,
                    unblocks=entry.unblocks,
                    remediation=entry.remediation,
                    notes=entry.notes,
                )
                for entry in EXPECTED_ENTRIES
                if entry.name in missing
            ),
            key=lambda i: i.entry_name,
        )
    )

    return UnblockerReport(
        captured_at=snapshot.captured_at,
        store_path=snapshot.store_path,
        expected_count=len(expected),
        present_entries=tuple(sorted(present)),
        missing_entries=tuple(sorted(missing)),
        unexpected_entries=tuple(sorted(unexpected)),
        services_unblocked=tuple(sorted(services_unblocked_by(frozenset(present)))),
        missing_unblockers=missing_items,
        by_category=categorize(frozenset(present), frozenset(missing)),
    )


def write_report(report: UnblockerReport, cache_dir: Path = DEFAULT_CACHE_DIR) -> Path:
    """Atomically write the unblocker report JSON. Returns the final path."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / STATE_FILENAME
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(report.to_json() + "\n", encoding="utf-8")
    os.replace(tmp, target)
    log.info(
        "wrote cred-watch state: %d present / %d missing → %s",
        len(report.present_entries),
        len(report.missing_entries),
        target,
    )
    return target


def append_delta_log(
    delta: Delta,
    captured_at: str,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> Path | None:
    """Append a delta event to the arrival log, if any change occurred.

    Returns the log path on append, ``None`` if delta was empty (no I/O).
    """
    if not delta.is_change():
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / ARRIVAL_LOG_FILENAME
    arrived_services = tuple(sorted(services_unblocked_by(delta.arrived)))
    departed_services = tuple(sorted(services_unblocked_by(delta.departed)))
    payload = {
        "captured_at": captured_at,
        "arrived_entries": sorted(delta.arrived),
        "departed_entries": sorted(delta.departed),
        "arrived_services": list(arrived_services),
        "departed_services": list(departed_services),
    }
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, sort_keys=True) + "\n")
    log.info(
        "delta: arrived=%d departed=%d → %s",
        len(delta.arrived),
        len(delta.departed),
        target,
    )
    return target


def load_prior_snapshot(cache_dir: Path = DEFAULT_CACHE_DIR) -> Snapshot | None:
    """Reconstruct the prior snapshot from the on-disk state file.

    Returns ``None`` if no state file exists yet (first-run case).
    """
    target = cache_dir / STATE_FILENAME
    if not target.is_file():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("cred-watch state file is malformed; treating as first run")
        return None
    return Snapshot(
        entries=tuple(payload.get("present_entries", [])),
        captured_at=payload.get("captured_at", ""),
        store_path=payload.get("store_path", ""),
    )


# Re-export for callers building reports without importing registry directly.
__all__ = [
    "MissingCredItem",
    "UnblockerReport",
    "build_report",
    "write_report",
    "append_delta_log",
    "load_prior_snapshot",
    "ExpectedEntry",
    "lookup",
]
