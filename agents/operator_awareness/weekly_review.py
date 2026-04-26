"""Weekly review aggregator — daily-note Awareness + Refused rollup.

Reads the past 7 days of vault daily notes (written by
``agents.vault_context_writer.write_awareness_section`` and
``write_refused_section``), extracts the ``## Awareness`` and
``## Refused`` sections, and produces a weekly-review note at
``~/Documents/Personal/40-calendar/weekly/{YYYY-WW}.md``.

Constitutional invariants:

* **Refused rollup is count + raw list, never verdict.** Per
  ``feedback_full_automation_or_no_engagement`` and the
  ``awareness-vault-weekly-review-aggregator`` spec out-of-scope
  clause: refusals never get summary judgment. The renderer emits
  per-axiom + per-surface counts plus a truncated raw entry list
  (with archive-link pointer) — no "best week / worst week" framing,
  no aggregate severity, no recommended-action prose.
* **No HITL annotations.** Operator never edits; the aggregator
  rewrites the weekly note idempotently each tick.
* **Pure-function rendering.** All file I/O lives in
  :func:`write_weekly_review`; the renderers/parsers below are
  testable without touching the vault.
"""

from __future__ import annotations

import logging
import os
import re
from collections import Counter as _Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_DAILY_NOTE_DIR = Path(
    os.environ.get(
        "HAPAX_VAULT_DAILY_NOTE_DIR",
        str(Path.home() / "Documents" / "Personal" / "40-calendar" / "daily"),
    )
)
DEFAULT_WEEKLY_NOTE_DIR = Path(
    os.environ.get(
        "HAPAX_VAULT_WEEKLY_NOTE_DIR",
        str(Path.home() / "Documents" / "Personal" / "40-calendar" / "weekly"),
    )
)

# Refused entries cap in the weekly note. The full archive lives in
# ~/hapax-state/refusals/{date}.jsonl.gz (per agents/refusal_brief/
# rotator.py) — the cap keeps the weekly note readable while a link
# to the archive preserves provenance for any operator who wants to
# inspect the raw stream.
REFUSED_CAP = 100

# Per-category integer fields the aggregator rolls up. Each entry
# is a (label, regex-extractor) tuple matching the daily-note
# format produced by render_awareness_section in
# agents/vault_context_writer.py — keep these in sync if the
# renderer changes.
_AWARENESS_FIELDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("stream_events_5min", re.compile(r"Stream:.*?(\d+) events/5min")),
    ("health_failed_units", re.compile(r"failed=(\d+)")),
    ("disk_pct", re.compile(r"disk (\d+)%")),
    ("gpu_pct", re.compile(r"GPU (\d+)%")),
    ("publishing_inbox", re.compile(r"Publishing: inbox=(\d+)")),
    ("publishing_in_flight", re.compile(r"in-flight=(\d+)")),
    ("research_in_flight", re.compile(r"Research: in-flight=(\d+)")),
    ("marketing_pending", re.compile(r"Marketing: pending=(\d+)")),
    ("sprint_completed", re.compile(r"completed=(\d+)")),
    ("sprint_blocked", re.compile(r"blocked=(\d+)")),
    ("governance_contracts", re.compile(r"Governance: contracts=(\d+)")),
    ("fleet_pi_online", re.compile(r"Fleet: pi (\d+)/")),
)

# ## Refused row format from vault_context_writer.render_refused_section:
# - {HH:MM} · axiom={tag} · surface={name} · reason={short}
_REFUSED_ROW = re.compile(
    r"-\s+(?P<ts>\d{2}:\d{2}|\S+)\s+·\s+axiom=(?P<axiom>\S+)\s+·\s+surface=(?P<surface>\S+)\s+·\s+reason=(?P<reason>.*)"
)


@dataclass
class WeeklyRollup:
    """Computed weekly aggregate, rendered downstream."""

    week_start: date
    week_end: date
    iso_year: int
    iso_week: int
    awareness_totals: dict[str, int] = field(default_factory=dict)
    refused_total: int = 0
    refused_by_axiom: dict[str, int] = field(default_factory=dict)
    refused_by_surface: dict[str, int] = field(default_factory=dict)
    refused_entries: list[dict[str, str]] = field(default_factory=list)
    days_observed: int = 0


def _iso_week_for(d: date) -> tuple[int, int]:
    iso = d.isocalendar()
    return iso.year, iso.week


def _week_bounds(week_end: date) -> tuple[date, date]:
    """Return ``(monday, sunday)`` for the ISO week containing
    ``week_end``. Sunday-evening run cadence: pass ``date.today()``."""
    iso_year, iso_week, weekday = week_end.isocalendar()
    monday = week_end - timedelta(days=weekday - 1)
    sunday = monday + timedelta(days=6)
    return monday, sunday


def _extract_section(text: str, heading: str) -> str | None:
    """Return everything between ``heading`` (a `## ` line) and the
    next `## ` heading or EOF. Returns None if heading absent."""
    lines = text.split("\n")
    start = None
    for i, line in enumerate(lines):
        if line.strip() == heading.strip():
            start = i + 1
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return "\n".join(lines[start:end])


def parse_awareness_section(text: str) -> dict[str, int]:
    """Extract integer-valued fields from a ``## Awareness`` body."""
    out: dict[str, int] = {}
    for label, pattern in _AWARENESS_FIELDS:
        match = pattern.search(text)
        if match is not None:
            try:
                out[label] = int(match.group(1))
            except ValueError:
                pass
    return out


def parse_refused_section(text: str) -> list[dict[str, str]]:
    """Extract refused-row dicts from a ``## Refused`` body."""
    rows: list[dict[str, str]] = []
    for raw in text.split("\n"):
        m = _REFUSED_ROW.match(raw.strip())
        if m is None:
            continue
        rows.append(
            {
                "ts": m.group("ts"),
                "axiom": m.group("axiom"),
                "surface": m.group("surface"),
                "reason": m.group("reason").strip(),
            }
        )
    return rows


def collect_week(
    *,
    week_end: date,
    daily_dir: Path = DEFAULT_DAILY_NOTE_DIR,
) -> WeeklyRollup:
    """Walk the past 7 days from ``week_end`` and accumulate.

    Missing daily notes are silently skipped — operators take days
    off and the daemon shouldn't fabricate empty observations on
    those days.
    """
    monday, sunday = _week_bounds(week_end)
    iso_year, iso_week = _iso_week_for(monday)
    rollup = WeeklyRollup(
        week_start=monday,
        week_end=sunday,
        iso_year=iso_year,
        iso_week=iso_week,
    )
    awareness_sums: _Counter[str] = _Counter()
    refused_axioms: _Counter[str] = _Counter()
    refused_surfaces: _Counter[str] = _Counter()
    refused_entries: list[dict[str, str]] = []

    cur = monday
    while cur <= sunday:
        path = daily_dir / f"{cur.isoformat()}.md"
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                cur += timedelta(days=1)
                continue
            rollup.days_observed += 1
            awareness = _extract_section(text, "## Awareness")
            if awareness:
                for k, v in parse_awareness_section(awareness).items():
                    awareness_sums[k] += v
            refused = _extract_section(text, "## Refused")
            if refused:
                rows = parse_refused_section(refused)
                for r in rows:
                    refused_axioms[r["axiom"]] += 1
                    refused_surfaces[r["surface"]] += 1
                    refused_entries.append({**r, "date": cur.isoformat()})
        cur += timedelta(days=1)

    rollup.awareness_totals = dict(awareness_sums)
    rollup.refused_total = len(refused_entries)
    rollup.refused_by_axiom = dict(refused_axioms)
    rollup.refused_by_surface = dict(refused_surfaces)
    rollup.refused_entries = refused_entries
    return rollup


def render_weekly_review(rollup: WeeklyRollup) -> str:
    """Render the weekly note Markdown.

    The format is fixed; surfaces consuming the weekly note (operator
    morning scan, omg.lol future-fanout, downstream archive) all see
    the same shape regardless of week.
    """
    week_label = f"{rollup.iso_year}-W{rollup.iso_week:02d}"
    title = f"# Weekly Review · {week_label}"
    range_line = (
        f"_{rollup.week_start.isoformat()} → {rollup.week_end.isoformat()} · "
        f"{rollup.days_observed}/7 days observed_"
    )

    awareness_lines: list[str] = ["## Awareness Rollup", ""]
    if rollup.awareness_totals:
        for key, total in sorted(rollup.awareness_totals.items()):
            awareness_lines.append(f"- {key}: {total}")
    else:
        awareness_lines.append("- _no daily-note awareness sections in window_")

    refused_lines: list[str] = ["## Refused Rollup", ""]
    refused_lines.append(f"- total refusals: {rollup.refused_total}")
    if rollup.refused_by_axiom:
        refused_lines.append("")
        refused_lines.append("### By axiom")
        refused_lines.append("")
        for axiom, count in sorted(rollup.refused_by_axiom.items(), key=lambda kv: (-kv[1], kv[0])):
            refused_lines.append(f"- {axiom}: {count}")
    if rollup.refused_by_surface:
        refused_lines.append("")
        refused_lines.append("### By surface")
        refused_lines.append("")
        for surface, count in sorted(
            rollup.refused_by_surface.items(), key=lambda kv: (-kv[1], kv[0])
        ):
            refused_lines.append(f"- {surface}: {count}")

    if rollup.refused_entries:
        refused_lines.append("")
        refused_lines.append(f"### Raw entries ({len(rollup.refused_entries)} total)")
        refused_lines.append("")
        capped = rollup.refused_entries[:REFUSED_CAP]
        for entry in capped:
            refused_lines.append(
                f"- {entry['date']} {entry['ts']} · axiom={entry['axiom']} · "
                f"surface={entry['surface']} · reason={entry['reason']}"
            )
        if len(rollup.refused_entries) > REFUSED_CAP:
            omitted = len(rollup.refused_entries) - REFUSED_CAP
            refused_lines.append("")
            refused_lines.append(
                f"_(+{omitted} more entries; full archive: "
                f"`~/hapax-state/refusals/YYYY-MM-DD.jsonl.gz`)_"
            )

    parts = [
        title,
        "",
        range_line,
        "",
        *awareness_lines,
        "",
        *refused_lines,
        "",
    ]
    return "\n".join(parts)


def write_weekly_review(
    *,
    week_end: date | None = None,
    daily_dir: Path = DEFAULT_DAILY_NOTE_DIR,
    weekly_dir: Path = DEFAULT_WEEKLY_NOTE_DIR,
) -> Path:
    """Compute + write the weekly note. Idempotent on retry — same
    inputs produce the same file content, so two consecutive runs in
    the same week converge."""
    week_end = week_end or datetime.now(UTC).date()
    rollup = collect_week(week_end=week_end, daily_dir=daily_dir)
    text = render_weekly_review(rollup)
    week_label = f"{rollup.iso_year}-W{rollup.iso_week:02d}"
    weekly_dir.mkdir(parents=True, exist_ok=True)
    path = weekly_dir / f"weekly-{week_label}.md"
    path.write_text(text, encoding="utf-8")
    return path


__all__ = [
    "DEFAULT_DAILY_NOTE_DIR",
    "DEFAULT_WEEKLY_NOTE_DIR",
    "REFUSED_CAP",
    "WeeklyRollup",
    "collect_week",
    "parse_awareness_section",
    "parse_refused_section",
    "render_weekly_review",
    "write_weekly_review",
]
