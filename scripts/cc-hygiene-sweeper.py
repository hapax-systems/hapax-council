#!/usr/bin/env python3
"""cc-hygiene-sweeper — read-only diagnostic daemon for vault cc-tasks.

PR1 of the task-list-hygiene plan
(`docs/research/2026-04-26-task-list-hygiene-operator-visibility.md`).
Implements the 8 checks described in §2 and emits:

* an append-only markdown event log under
  ``~/Documents/Personal/20-projects/hapax-cc-tasks/_dashboard/cc-hygiene-events.md``
* a machine-readable JSON snapshot at
  ``~/.cache/hapax/cc-hygiene-state.json``

Auto-actions are PR2 territory; this script is strictly observational.

Usage::

    uv run python scripts/cc-hygiene-sweeper.py
    HAPAX_CC_HYGIENE_OFF=1 uv run python scripts/cc-hygiene-sweeper.py  # killswitch

The systemd timer ``hapax-cc-hygiene.timer`` runs this every 5 minutes.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# When invoked as a CLI script, the package sits next to us under cc_hygiene/.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from cc_hygiene.checks import (
    KNOWN_ROLES,
    check_duplicate_claim,
    check_ghost_claimed,
    check_offered_staleness,
    check_orphan_pr,
    check_refusal_pipeline_dormancy,
    check_relay_yaml_staleness,
    check_stale_in_progress,
    check_wip_limit,
    parse_task_note,
)
from cc_hygiene.events import DEFAULT_EVENT_LOG_PATH, append_events
from cc_hygiene.models import (
    CheckId,
    CheckSummary,
    HygieneEvent,
    HygieneState,
    SessionState,
    TaskNote,
)
from cc_hygiene.state import DEFAULT_STATE_PATH, write_state

LOG = logging.getLogger("cc-hygiene-sweeper")

DEFAULT_VAULT_ROOT = Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
DEFAULT_RELAY_ROOT = Path.home() / ".cache" / "hapax" / "relay"
DEFAULT_REPO_ROOT = Path.home() / "projects" / "hapax-council"

KILLSWITCH_ENV = "HAPAX_CC_HYGIENE_OFF"


def _load_active_notes(vault_root: Path) -> list[TaskNote]:
    """Parse all `active/*.md` cc-task notes."""
    active = vault_root / "active"
    if not active.is_dir():
        return []
    notes: list[TaskNote] = []
    for path in sorted(active.glob("*.md")):
        note = parse_task_note(path)
        if note is not None:
            notes.append(note)
    return notes


def _load_closed_notes(vault_root: Path) -> list[TaskNote]:
    """Parse closed/*.md notes for refusal-dormancy check (best-effort)."""
    closed = vault_root / "closed"
    if not closed.is_dir():
        return []
    notes: list[TaskNote] = []
    for path in sorted(closed.glob("*.md")):
        note = parse_task_note(path)
        if note is not None:
            notes.append(note)
    return notes


def _load_relay_payloads(relay_root: Path) -> dict[str, dict[str, Any]]:
    """Load `{role}.yaml` for each known role; tolerate missing files."""
    from cc_hygiene.checks import _read_relay_yaml  # local helper

    payloads: dict[str, dict[str, Any]] = {}
    if not relay_root.is_dir():
        return payloads
    for role in KNOWN_ROLES:
        payload = _read_relay_yaml(relay_root / f"{role}.yaml")
        if payload is not None:
            payloads[role] = payload
    return payloads


def _build_session_states(
    relay_payloads: dict[str, dict[str, Any]], notes: list[TaskNote]
) -> list[SessionState]:
    """Construct per-session current-claim summaries."""
    from cc_hygiene.checks import _extract_current_claim, _extract_relay_updated

    sessions: list[SessionState] = []
    in_progress_by_session: Counter[str] = Counter()
    for note in notes:
        if note.status == "in_progress" and note.assigned_to and note.assigned_to != "unassigned":
            in_progress_by_session[note.assigned_to] += 1
    for role in KNOWN_ROLES:
        payload = relay_payloads.get(role, {})
        task_id, _ = _extract_current_claim(payload) if payload else (None, None)
        updated = _extract_relay_updated(payload) if payload else None
        sessions.append(
            SessionState(
                role=role,
                current_claim=task_id,
                relay_updated=updated,
                in_progress_count=in_progress_by_session.get(role, 0),
            )
        )
    return sessions


def _summarize_checks(events: list[HygieneEvent]) -> list[CheckSummary]:
    counter: Counter[CheckId] = Counter()
    for event in events:
        counter[event.check_id] += 1
    all_ids: tuple[CheckId, ...] = (
        "stale_in_progress",
        "ghost_claimed",
        "duplicate_claim",
        "orphan_pr",
        "relay_yaml_stale",
        "wip_limit",
        "offered_stale",
        "refusal_dormancy",
    )
    return [CheckSummary(check_id=cid, fired=counter.get(cid, 0)) for cid in all_ids]


def run_sweep(
    *,
    vault_root: Path = DEFAULT_VAULT_ROOT,
    relay_root: Path = DEFAULT_RELAY_ROOT,
    repo_root: Path = DEFAULT_REPO_ROOT,
    now: datetime | None = None,
) -> HygieneState:
    """Perform one sweep and return the snapshot. Does NOT write to disk."""
    now = now or datetime.now(UTC)
    started = time.monotonic()
    notes = _load_active_notes(vault_root)
    closed_notes = _load_closed_notes(vault_root)
    relay_payloads = _load_relay_payloads(relay_root)

    events: list[HygieneEvent] = []
    events.extend(check_stale_in_progress(notes, repo_root, now=now))
    events.extend(check_ghost_claimed(notes, now=now))
    events.extend(check_duplicate_claim(relay_payloads, now=now))
    events.extend(check_orphan_pr(notes, repo_root, now=now))
    events.extend(check_relay_yaml_staleness(relay_payloads, now=now))
    events.extend(check_wip_limit(notes, now=now))
    events.extend(check_offered_staleness(notes, now=now))
    events.extend(check_refusal_pipeline_dormancy(closed_notes, now=now))

    sessions = _build_session_states(relay_payloads, notes)
    summaries = _summarize_checks(events)
    duration_ms = int((time.monotonic() - started) * 1000)

    return HygieneState(
        sweep_timestamp=now,
        sweep_duration_ms=duration_ms,
        killswitch_active=False,
        sessions=sessions,
        check_summaries=summaries,
        events=events,
    )


def _killswitch_state(*, now: datetime | None = None) -> HygieneState:
    """Return a no-op snapshot when the killswitch is engaged."""
    now = now or datetime.now(UTC)
    return HygieneState(
        sweep_timestamp=now,
        sweep_duration_ms=0,
        killswitch_active=True,
        sessions=[],
        check_summaries=_summarize_checks([]),
        events=[],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-root", type=Path, default=DEFAULT_VAULT_ROOT)
    parser.add_argument("--relay-root", type=Path, default=DEFAULT_RELAY_ROOT)
    parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--event-log-path", type=Path, default=DEFAULT_EVENT_LOG_PATH)
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Run the sweep but do not write event log or state JSON (diagnostic mode).",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if os.environ.get(KILLSWITCH_ENV) == "1":
        LOG.info("killswitch active, no checks run")
        state = _killswitch_state()
        if not args.no_write:
            append_events(
                [],
                state.sweep_timestamp,
                path=args.event_log_path,
                killswitch_active=True,
            )
            write_state(state, path=args.state_path)
        return 0

    state = run_sweep(
        vault_root=args.vault_root,
        relay_root=args.relay_root,
        repo_root=args.repo_root,
    )
    LOG.info(
        "sweep complete: %d events in %d ms",
        len(state.events),
        state.sweep_duration_ms,
    )
    if not args.no_write:
        append_events(state.events, state.sweep_timestamp, path=args.event_log_path)
        write_state(state, path=args.state_path)
    if args.verbose:
        for event in state.events:
            LOG.debug("%s: %s", event.check_id, event.message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
