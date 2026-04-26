"""Dashboard renderer (PR5 surface B).

Rewrites a generated section of
``~/Documents/Personal/20-projects/hapax-cc-tasks/_dashboard/cc-active.md``
between sentinel comments::

    <!-- HYGIENE-AUTO-START -->
    ...generated content...
    <!-- HYGIENE-AUTO-END -->

The block is **additive**: any non-sentinel content (existing Dataview
tables, operator hand-edits) is preserved verbatim. If sentinels are
absent, the block is appended once.

Three sections are emitted, all native markdown (no Dataview-only
constructs — must render on Obsidian iOS):

* ``## Live Sessions`` — 4-row table, alpha/beta/delta/epsilon, with
  current_claim, branch, PR, severity dot, last-pulse timestamp.
* ``## Recent Hygiene Events (last 20)`` — tail of the markdown event log.
* ``## Counters`` — quick metrics (offered/claimed/in_progress/pr_open
  counts, ghost-claim count, WIP per session).

Sources:

* ``HygieneState`` (sweeper output).
* ``cc-hygiene-events.md`` tail (last 20 events).
* The vault ``active/`` dir for status counters (read-only scan).
"""

from __future__ import annotations

import logging
import os
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .checks import KNOWN_ROLES, parse_task_note
from .events import DEFAULT_EVENT_LOG_PATH
from .models import HygieneState, SessionState

LOG = logging.getLogger("cc-hygiene-dashboard")

DEFAULT_DASHBOARD_PATH = (
    Path.home()
    / "Documents"
    / "Personal"
    / "20-projects"
    / "hapax-cc-tasks"
    / "_dashboard"
    / "cc-active.md"
)
"""Operator-facing dashboard path."""

DEFAULT_VAULT_ACTIVE = (
    Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"
)
"""Active cc-task notes (used for counters)."""

SENTINEL_START = "<!-- HYGIENE-AUTO-START -->"
SENTINEL_END = "<!-- HYGIENE-AUTO-END -->"

KILLSWITCH_ENV = "HAPAX_CC_HYGIENE_OFF"

EVENT_TAIL_LIMIT = 20
"""Number of most-recent hygiene events to surface."""


# ---------------------------------------------------------------------------
# event-log tail parser
# ---------------------------------------------------------------------------


def _read_event_log_tail(path: Path, *, limit: int = EVENT_TAIL_LIMIT) -> list[dict[str, Any]]:
    """Return up to ``limit`` most-recent events from the markdown event log.

    The log format is documented in ``events.append_events``: alternating
    ``## sweep <iso>`` headings + fenced YAML blocks containing
    ``{sweep_timestamp, killswitch_active, events: [...]}``.

    Tolerant of missing/malformed log: returns ``[]`` rather than raise.
    """
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []

    events: list[dict[str, Any]] = []
    in_block = False
    block_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("```yaml"):
            in_block = True
            block_lines = []
            continue
        if line.startswith("```") and in_block:
            in_block = False
            try:
                block = yaml.safe_load("\n".join(block_lines)) or {}
            except yaml.YAMLError:
                block_lines = []
                continue
            block_lines = []
            for evt in block.get("events", []) or []:
                if isinstance(evt, dict):
                    events.append(evt)
            continue
        if in_block:
            block_lines.append(line)

    # Most-recent first
    events.reverse()
    return events[:limit]


# ---------------------------------------------------------------------------
# active-vault status counters
# ---------------------------------------------------------------------------


def _vault_status_counters(active_root: Path) -> Counter[str]:
    """Return ``{status: count}`` for all parsed cc-task notes under ``active/``."""
    counter: Counter[str] = Counter()
    if not active_root.is_dir():
        return counter
    for path in active_root.glob("*.md"):
        note = parse_task_note(path)
        if note is None:
            continue
        counter[note.status] += 1
    return counter


# ---------------------------------------------------------------------------
# severity dot (compact glyph for mobile)
# ---------------------------------------------------------------------------


def _severity_dot(role: str, events: Iterable[dict[str, Any]]) -> str:
    """Return a compact glyph for a session's hygiene status.

    Walks the recent events for any matching ``session`` and picks the
    highest-severity dot. Mobile-readable plain markdown (no SVG, no css).
    """
    worst = "ok"
    for evt in events:
        if evt.get("session") != role:
            continue
        sev = str(evt.get("severity", ""))
        if sev == "violation" and worst != "violation":
            worst = "violation"
        elif sev == "warning" and worst not in ("violation",):
            worst = "warning"
        elif sev == "info" and worst not in ("violation", "warning"):
            worst = "info"
    return {
        "ok": "green",
        "info": "info",
        "warning": "amber",
        "violation": "red",
    }[worst]


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def _fmt_ts(ts: datetime | str | None) -> str:
    """Compact UTC ISO-8601 string, or ``-`` if absent."""
    if ts is None:
        return "-"
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return ts
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _render_live_sessions(state: HygieneState, recent_events: list[dict[str, Any]]) -> str:
    rows: list[str] = [
        "| Role | Current claim | Branch | PR | Severity | Last pulse |",
        "|------|---------------|--------|----|----------|------------|",
    ]
    by_role: dict[str, SessionState] = {s.role: s for s in state.sessions}
    for role in KNOWN_ROLES:
        s = by_role.get(role)
        current = s.current_claim if s and s.current_claim else "-"
        # branch + PR live in the cc-task note, not relay yaml; keep blank
        # in this surface (Logos panel in PR4 fetches them).
        branch = "-"
        pr = "-"
        last_pulse = _fmt_ts(s.relay_updated) if s else "-"
        sev = _severity_dot(role, recent_events) if recent_events else "green"
        rows.append(f"| {role} | {current} | {branch} | {pr} | {sev} | {last_pulse} |")
    return "## Live Sessions\n\n" + "\n".join(rows) + "\n"


def _render_recent_events(recent_events: list[dict[str, Any]]) -> str:
    if not recent_events:
        return (
            "## Recent Hygiene Events (last 20)\n\n"
            "_No events recorded yet — sweeper has not detected anything._\n"
        )
    rows: list[str] = [
        "| Timestamp | Check | Severity | Task | Session | Message |",
        "|-----------|-------|----------|------|---------|---------|",
    ]
    for evt in recent_events:
        ts = _fmt_ts(evt.get("timestamp"))
        check = str(evt.get("check_id", "-"))
        sev = str(evt.get("severity", "-"))
        task = str(evt.get("task_id") or "-")
        session = str(evt.get("session") or "-")
        # Pipe characters in the message would break markdown tables;
        # escape them defensively.
        msg = str(evt.get("message", "")).replace("|", "\\|")
        rows.append(f"| {ts} | {check} | {sev} | {task} | {session} | {msg} |")
    return "## Recent Hygiene Events (last 20)\n\n" + "\n".join(rows) + "\n"


def _render_counters(state: HygieneState, status_counts: Counter[str]) -> str:
    """Status counters + ghost-claim count + per-session WIP."""
    summary_by_check = {cs.check_id: cs.fired for cs in state.check_summaries}
    ghost = summary_by_check.get("ghost_claimed", 0)
    counters_md = [
        "## Counters",
        "",
        "**Status counts (active/):**",
        "",
        "| offered | claimed | in_progress | pr_open | done | other |",
        "|---------|---------|-------------|---------|------|-------|",
        (
            f"| {status_counts.get('offered', 0)} "
            f"| {status_counts.get('claimed', 0)} "
            f"| {status_counts.get('in_progress', 0)} "
            f"| {status_counts.get('pr_open', 0)} "
            f"| {status_counts.get('done', 0)} "
            f"| {sum(status_counts.values()) - sum(status_counts.get(k, 0) for k in ('offered', 'claimed', 'in_progress', 'pr_open', 'done'))} |"
        ),
        "",
        f"**Ghost-claimed (this sweep):** {ghost}",
        "",
        "**WIP per session:**",
        "",
        "| Role | In-progress |",
        "|------|-------------|",
    ]
    by_role = {s.role: s.in_progress_count for s in state.sessions}
    for role in KNOWN_ROLES:
        counters_md.append(f"| {role} | {by_role.get(role, 0)} |")
    return "\n".join(counters_md) + "\n"


def render_block(
    state: HygieneState,
    *,
    event_log_path: Path = DEFAULT_EVENT_LOG_PATH,
    vault_active: Path = DEFAULT_VAULT_ACTIVE,
    now: datetime | None = None,
) -> str:
    """Build the entire sentinel-bracketed hygiene block (string)."""
    now = now or datetime.now(UTC)
    recent_events = _read_event_log_tail(event_log_path)
    status_counts = _vault_status_counters(vault_active)

    parts: list[str] = [
        SENTINEL_START,
        "",
        f"_Generated by `cc-hygiene-sweeper` at {_fmt_ts(now)}. Do not hand-edit between sentinels._",
        "",
        _render_live_sessions(state, recent_events),
        _render_recent_events(recent_events),
        _render_counters(state, status_counts),
        SENTINEL_END,
    ]
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# additive write — preserves user content outside sentinels
# ---------------------------------------------------------------------------


def update_dashboard(
    state: HygieneState,
    *,
    dashboard_path: Path = DEFAULT_DASHBOARD_PATH,
    event_log_path: Path = DEFAULT_EVENT_LOG_PATH,
    vault_active: Path = DEFAULT_VAULT_ACTIVE,
    now: datetime | None = None,
) -> Path:
    """Rewrite (only) the sentinel-bracketed block in the dashboard.

    * If sentinels exist → replace contents between them, preserve outside.
    * If sentinels do not exist → append the block to the file.
    * Honors the killswitch env var: no-op when set.
    * Atomic write (tmp + rename).
    """
    if os.environ.get(KILLSWITCH_ENV) == "1":
        LOG.info("dashboard: killswitch active, skipping render")
        return dashboard_path

    block = render_block(
        state,
        event_log_path=event_log_path,
        vault_active=vault_active,
        now=now,
    )

    dashboard_path.parent.mkdir(parents=True, exist_ok=True)
    if not dashboard_path.exists():
        new_content = block
    else:
        try:
            existing = dashboard_path.read_text(encoding="utf-8")
        except OSError as exc:
            LOG.warning("dashboard read failed: %s", exc)
            return dashboard_path
        new_content = _replace_sentinel_block(existing, block)

    tmp = dashboard_path.with_suffix(dashboard_path.suffix + ".tmp")
    tmp.write_text(new_content, encoding="utf-8")
    tmp.replace(dashboard_path)
    return dashboard_path


def _replace_sentinel_block(existing: str, block: str) -> str:
    """Inject ``block`` (starts with sentinel, ends with sentinel + newline) into ``existing``.

    Strategy:

    * If both sentinels are present → replace everything between them (and
      the sentinels themselves), keeping outside content verbatim.
    * If neither sentinel is present → append block after a blank line.
    * Mismatched sentinels (e.g. only START or only END present) → bail
      out and append, refusing to corrupt operator content.
    """
    has_start = SENTINEL_START in existing
    has_end = SENTINEL_END in existing
    if has_start and has_end:
        start_idx = existing.index(SENTINEL_START)
        end_idx = existing.index(SENTINEL_END) + len(SENTINEL_END)
        # consume optional trailing newline so we do not stack blanks
        if end_idx < len(existing) and existing[end_idx] == "\n":
            end_idx += 1
        prefix = existing[:start_idx]
        suffix = existing[end_idx:]
        # ensure a blank line between prefix and block when prefix is non-empty
        if prefix and not prefix.endswith("\n\n"):
            if not prefix.endswith("\n"):
                prefix = prefix + "\n"
        return prefix + block + suffix

    # Mismatched / absent sentinels → append.
    sep = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    return existing + sep + block


__all__ = [
    "DEFAULT_DASHBOARD_PATH",
    "DEFAULT_VAULT_ACTIVE",
    "EVENT_TAIL_LIMIT",
    "KILLSWITCH_ENV",
    "SENTINEL_END",
    "SENTINEL_START",
    "render_block",
    "update_dashboard",
]
