"""Flagged-payload store — partitioned per-date / per-capability JSONL.

Plan §Phase 10. Path layout::

    ~/hapax-state/monetization-flagged/
        2026-04-25/
            knowledge.web_search.jsonl
            chronicle.synthesize.jsonl
        2026-04-26/
            ...

Writer fires when ``MonetizationRiskGate`` emits ``allowed=False``.
Reader walks the directory in newest-first order so the operator sees
recent blocks first. 7-day pruning is documented per spec; pruning is
a side helper invoked by the CLI's ``--prune`` flag rather than a
timer (operator-driven).

Records are append-only, one JSON object per line::

    {
      "ts": 1713588000.0,
      "capability_name": "knowledge.web_search",
      "surface": "tts",
      "rendered_payload": "<text or stringified dict>",
      "risk": "medium",
      "reason": "ring2 escalated to medium (politically charged)",
      "programme_id": "showcase-001"
    }
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, Final

log = logging.getLogger(__name__)

DEFAULT_FLAGGED_DIR: Final[Path] = Path.home() / "hapax-state" / "monetization-flagged"
DEFAULT_RETENTION_DAYS: Final[int] = 7


@dataclass(frozen=True)
class FlaggedRecord:
    """One block decision the operator can review."""

    ts: float
    capability_name: str
    surface: str | None
    rendered_payload: str
    risk: str
    reason: str
    programme_id: str | None
    source_path: Path

    @property
    def date_str(self) -> str:
        return datetime.fromtimestamp(self.ts, tz=UTC).strftime("%Y-%m-%d")


class FlaggedStore:
    """Read + write the partitioned flagged-payload directory.

    Thread-safe writes via per-instance lock; reads are unlocked
    (filesystem snapshots — multiple concurrent readers fine).
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = root if root is not None else DEFAULT_FLAGGED_DIR
        self._lock = Lock()

    def record_block(
        self,
        *,
        capability_name: str,
        surface: str | None,
        rendered_payload: Any,
        risk: str,
        reason: str,
        programme_id: str | None = None,
        now: float | None = None,
    ) -> Path:
        """Append one block decision. Returns the file written to.

        ``rendered_payload`` is coerced to ``str`` for storage —
        callers that want the original object should pass it directly
        and accept the JSON-string round-trip.
        """
        ts = now if now is not None else time.time()
        date = datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d")
        date_dir = self.root / date
        target = date_dir / f"{capability_name}.jsonl"
        line = {
            "ts": ts,
            "capability_name": capability_name,
            "surface": surface,
            "rendered_payload": rendered_payload
            if isinstance(rendered_payload, str)
            else str(rendered_payload),
            "risk": risk,
            "reason": reason,
            "programme_id": programme_id,
        }
        payload = json.dumps(line, sort_keys=False, separators=(",", ":"))
        with self._lock:
            date_dir.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as f:
                f.write(payload + "\n")
        return target

    def iter_records(self) -> list[FlaggedRecord]:
        """Walk the directory, newest-first, returning all flagged records.

        Ordering: date desc → file mtime desc → record order within file
        (file is append-only so file order is chronological).
        """
        if not self.root.exists():
            return []
        out: list[FlaggedRecord] = []
        date_dirs = sorted(
            (d for d in self.root.iterdir() if d.is_dir() and _looks_like_date(d.name)),
            key=lambda d: d.name,
            reverse=True,
        )
        for date_dir in date_dirs:
            files = sorted(
                (f for f in date_dir.iterdir() if f.is_file() and f.suffix == ".jsonl"),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )
            for f in files:
                out.extend(_read_records(f))
        return out

    def prune(
        self,
        *,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        now: float | None = None,
    ) -> list[Path]:
        """Delete date directories older than ``retention_days``.

        Returns the list of removed directories. Skips non-date entries
        so operator-dropped scratch files in ``self.root`` survive.
        """
        if not self.root.exists():
            return []
        ts = now if now is not None else time.time()
        cutoff = ts - (retention_days * 86400.0)
        removed: list[Path] = []
        for entry in self.root.iterdir():
            if not entry.is_dir() or not _looks_like_date(entry.name):
                continue
            try:
                entry_ts = datetime.strptime(entry.name, "%Y-%m-%d").replace(tzinfo=UTC).timestamp()
            except ValueError:
                continue
            if entry_ts >= cutoff:
                continue
            for child in entry.iterdir():
                child.unlink()
            entry.rmdir()
            removed.append(entry)
        return removed


def _looks_like_date(name: str) -> bool:
    return len(name) == 10 and name[4] == "-" and name[7] == "-"


def _read_records(path: Path) -> list[FlaggedRecord]:
    out: list[FlaggedRecord] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        log.warning("flagged_store: failed to read %s", path, exc_info=True)
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        out.append(
            FlaggedRecord(
                ts=float(obj.get("ts", 0.0)),
                capability_name=str(obj.get("capability_name", "")),
                surface=obj.get("surface"),
                rendered_payload=str(obj.get("rendered_payload", "")),
                risk=str(obj.get("risk", "")),
                reason=str(obj.get("reason", "")),
                programme_id=obj.get("programme_id"),
                source_path=path,
            )
        )
    return out


__all__ = [
    "DEFAULT_FLAGGED_DIR",
    "DEFAULT_RETENTION_DAYS",
    "FlaggedRecord",
    "FlaggedStore",
]
