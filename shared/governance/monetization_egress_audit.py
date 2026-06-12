"""Monetization egress audit writer — demonet Phase 6.

Every ``RiskAssessment`` emitted by ``MonetizationRiskGate`` lands in
a JSONL trail so post-stream analysis can answer:

- Which capabilities were blocked? By which reason class?
- Which Programme opt-ins were actually exercised vs declared but
  never hit?
- How often did a high-risk capability even _attempt_ recruitment
  (governance stress-test)?

Storage: ``~/hapax-state/demonet-egress-audit.jsonl`` (configurable
per-writer). Appended-to line-by-line; rotation helper cuts the file
into dated archives so a Grafana dashboard can tail the live file
without re-reading 30 days of history.

Scope (Phase 6):

- Append-only writer with thread-safe open+write.
- Rotation helper — splits the live file into
  ``demonet-egress-audit.YYYY-MM-DD.jsonl`` archives.
- 30-day retention pruner.
- No Grafana dashboard, no systemd timer (operator ships those).
- No JSON schema validation — the record shape is Pydantic's
  ``RiskAssessment.model_dump_json()`` + timestamp + capability name.
  Downstream consumers parse with their own Pydantic reader.

Reference:
    - docs/superpowers/plans/2026-04-20-demonetization-safety-plan.md §6
    - docs/governance/monetization-risk-classification.md
    - shared/governance/monetization_safety.py — Phase 1 gate
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, Final

from shared.governance.monetization_safety import RiskAssessment, SurfaceKind

log = logging.getLogger(__name__)

DEFAULT_AUDIT_PATH: Final[Path] = Path.home() / "hapax-state" / "demonet-egress-audit.jsonl"

# Default retention — 30 days of archive files matches the operator's
# sprint-review cadence. Tunable per-call of prune_old_archives.
DEFAULT_RETENTION_DAYS: Final[int] = 30


class MonetizationEgressAudit:
    """Append-only JSONL writer for RiskAssessment decisions.

    Instantiate with a path (tests override) or rely on module-level
    ``default_writer()`` for production. Thread-safe via a per-instance
    lock — multiple agents (director, cpal, affordance pipeline) can
    write concurrently without garbling lines.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else DEFAULT_AUDIT_PATH
        self._lock = Lock()

    def record(
        self,
        capability_name: str,
        assessment: RiskAssessment,
        *,
        surface: SurfaceKind | None = None,
        programme_id: str | None = None,
        now: float | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Append one line describing the assessment.

        Record shape:

            {
              "ts": 1713588000.0,
              "capability_name": "knowledge.web_search",
              "surface": "tts" | null,
              "programme_id": "showcase-001" | null,
              "allowed": true|false,
              "risk": "none"|"low"|"medium"|"high",
              "reason": "...",
              "extra": {...}   # caller-supplied, e.g. impingement id
            }

        Caller passes ``surface`` + ``programme_id`` if known; neither
        is required at the gate's call site, but governance wants both
        when they exist for the audit trail.
        """
        ts = now if now is not None else time.time()
        line = {
            "ts": ts,
            "capability_name": capability_name,
            "surface": surface.value if surface is not None else None,
            "programme_id": programme_id,
            "allowed": assessment.allowed,
            "risk": assessment.risk,
            "reason": assessment.reason,
        }
        if extra:
            line["extra"] = extra
        payload = json.dumps(line, sort_keys=False, separators=(",", ":"))
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # jsonl-rotation: exempt(domain rotation; rotate() archives by UTC day)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(payload + "\n")

    def rotate(self, *, now: float | None = None) -> Path | None:
        """Move the current live file to a dated archive.

        Archive name: ``<stem>.YYYY-MM-DD<suffix>`` — e.g.
        ``demonet-egress-audit.2026-04-20.jsonl``. Uses UTC for date
        consistency across sessions crossing local midnight.

        Returns the archive path if rotation happened, None if there
        was nothing to rotate (live file missing / empty).

        Idempotent — calling twice in the same day with no new records
        between is a no-op after the first call creates the archive.
        """
        with self._lock:
            if not self.path.exists() or self.path.stat().st_size == 0:
                return None
            ts = now if now is not None else time.time()
            date = datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d")
            archive = self.path.with_suffix(f".{date}{self.path.suffix}")
            if archive.exists():
                # Same-day rotation already happened — append remaining
                # live lines to the archive, then truncate the live
                # file. Preserves continuity when multiple rotate()
                # calls land the same UTC day.
                with archive.open("a", encoding="utf-8") as out:
                    with self.path.open("r", encoding="utf-8") as live:
                        out.write(live.read())
                self.path.write_text("")
            else:
                os.rename(self.path, archive)
            return archive

    def prune_old_archives(
        self,
        *,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        now: float | None = None,
    ) -> list[Path]:
        """Delete archive files older than ``retention_days``.

        Safe by design: NEVER deletes the live ``self.path`` file.
        Only matches archives whose name contains ``.YYYY-MM-DD.``
        between the stem and suffix — anything else the operator
        dropped in the directory stays untouched.

        Returns the list of pruned paths.
        """
        if not self.path.parent.exists():
            return []
        ts = now if now is not None else time.time()
        cutoff = ts - (retention_days * 86400.0)
        stem = self.path.stem  # "demonet-egress-audit"
        suffix = self.path.suffix  # ".jsonl"
        pruned: list[Path] = []
        # Log boundaries so a crash mid-loop is visible in the journal.
        # Without this, an incomplete prune manifests only as inconsistent
        # archive state next cycle — hard to attribute.
        log.info(
            "prune_old_archives: start (retention=%d days, dir=%s)",
            retention_days,
            self.path.parent,
        )
        for candidate in self.path.parent.iterdir():
            if candidate == self.path:
                continue  # never prune live file
            if not candidate.is_file():
                continue
            name = candidate.name
            if not (name.startswith(f"{stem}.") and name.endswith(suffix)):
                continue
            # Extract the date between stem+dot and suffix.
            date_part = name[len(stem) + 1 : -len(suffix)]
            try:
                archive_ts = (
                    datetime.strptime(date_part, "%Y-%m-%d").replace(tzinfo=UTC).timestamp()
                )
            except ValueError:
                continue
            if archive_ts < cutoff:
                candidate.unlink()
                pruned.append(candidate)
        log.info("prune_old_archives: end (pruned=%d)", len(pruned))
        return pruned


_DEFAULT_WRITER: MonetizationEgressAudit | None = None
_DEFAULT_WRITER_LOCK = Lock()


def default_writer() -> MonetizationEgressAudit:
    """Module-level singleton writer — the shared audit at DEFAULT_AUDIT_PATH.

    Lazily constructed so tests that never call this don't touch
    ``~/hapax-state``. Production callers use this; tests instantiate
    their own ``MonetizationEgressAudit(path=tmp_path)``.

    Thread-safe: the TOCTOU window between ``is None`` check and
    assignment is guarded so concurrent first-callers don't construct
    two writer instances (which would bypass each other's file locks
    when they happen to land on the same path).
    """
    global _DEFAULT_WRITER
    if _DEFAULT_WRITER is None:
        with _DEFAULT_WRITER_LOCK:
            if _DEFAULT_WRITER is None:  # double-checked — re-read inside lock
                _DEFAULT_WRITER = MonetizationEgressAudit()
    return _DEFAULT_WRITER
