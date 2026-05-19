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
import subprocess
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
    check_spec_staleness,
    check_stale_in_progress,
    check_wip_limit,
    parse_task_note,
)
from cc_hygiene.dashboard import (
    DEFAULT_DASHBOARD_PATH,
    DEFAULT_VAULT_ACTIVE,
    update_dashboard,
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
from cc_hygiene.ntfy import DEFAULT_THROTTLE_PATH, dispatch_alerts
from cc_hygiene.state import DEFAULT_STATE_PATH, write_state

LOG = logging.getLogger("cc-hygiene-sweeper")

DEFAULT_VAULT_ROOT = Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
DEFAULT_RELAY_ROOT = Path.home() / ".cache" / "hapax" / "relay"
DEFAULT_REPO_ROOT = Path.home() / "projects" / "hapax-council"

KILLSWITCH_ENV = "HAPAX_CC_HYGIENE_OFF"


def _relay_payload_is_retired(payload: dict[str, Any]) -> bool:
    """Return true for relays that explicitly mark a retired/superseded lane."""
    values: list[str] = []
    for key in ("status", "state", "relay_status", "session_state", "role", "session_status"):
        raw = payload.get(key)
        if raw:
            values.append(str(raw))
    for value in values:
        normalized = value.strip().strip("\"'").upper()
        if normalized.startswith(("RETIR", "SUPERSEDED", "CLOSED", "ANTIGRAVITY")):
            return True
    return False


_AGENT_PGREP_PATTERN = (
    r"claude-code/bin/claude|/\.local/bin/claude|/\.npm-global/bin/codex|(^|/)codex( |$)"
    r"|(^|/)claude( |$)"
)

_WORKTREE_ROOT = Path.home() / "projects"


def _lane_has_live_process(role: str) -> bool:
    """Check if any claude/codex process is running for this lane role.

    Detection strategy (ordered by reliability):
    1. Process env vars (CLAUDE_ROLE, HAPAX_AGENT_ROLE, CODEX_ROLE) match role
    2. Process cwd is inside the role's canonical worktree
    3. For alpha only: process cwd is the workspace root (bare sessions)
    Fails open: if pgrep fails or /proc is unreadable, assume alive.
    """
    try:
        result = subprocess.run(
            ["pgrep", "-af", _AGENT_PGREP_PATTERN],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return True
    if result.returncode != 0:
        return False

    alpha_worktree = str(_WORKTREE_ROOT / "hapax-council")
    role_worktrees = {
        str(_WORKTREE_ROOT / f"hapax-council--{role}"),
        str(_WORKTREE_ROOT / f"hapax-council--{role}-omg"),
    }
    if role == "alpha":
        role_worktrees.add(alpha_worktree)

    role_env_vars = (b"CLAUDE_ROLE=", b"HAPAX_AGENT_NAME=", b"HAPAX_AGENT_ROLE=", b"CODEX_ROLE=")

    for line in result.stdout.strip().splitlines():
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        pid = parts[0]

        try:
            env_bytes = Path(f"/proc/{pid}/environ").read_bytes()
        except OSError:
            env_bytes = b""

        for var in role_env_vars:
            idx = env_bytes.find(var)
            if idx >= 0:
                val_start = idx + len(var)
                try:
                    val_end = env_bytes.index(b"\x00", val_start)
                except ValueError:
                    val_end = len(env_bytes)
                if env_bytes[val_start:val_end].decode(errors="replace") == role:
                    return True

        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            continue
        if cwd in role_worktrees:
            return True
        if role == "alpha" and cwd == str(_WORKTREE_ROOT):
            return True

    return False


def reap_dead_lanes(relay_root: Path) -> list[str]:
    """Retire relay YAMLs for lanes with no running process.

    Returns list of roles that were reaped.
    """
    from cc_hygiene.checks import _read_relay_yaml

    reaped: list[str] = []
    retire_script = Path.home() / "projects" / "hapax-council" / "scripts" / "hapax-relay-retire"

    for role in KNOWN_ROLES:
        for suffix in (f"{role}-status.yaml", f"{role}.yaml"):
            yaml_path = relay_root / suffix
            if not yaml_path.exists():
                continue
            payload = _read_relay_yaml(yaml_path)
            if payload is None or _relay_payload_is_retired(payload):
                continue
            if _lane_has_live_process(role):
                continue
            LOG.info("Reaping dead lane '%s' — no running process found", role)
            try:
                subprocess.run(
                    [
                        str(retire_script),
                        role,
                        "--reason",
                        "reaped by hygiene sweeper (no running process)",
                    ],
                    timeout=5,
                    check=False,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                LOG.warning("Failed to retire relay YAML for '%s'", role)
                continue
            reaped.append(role)
            break  # only one file per role

    for path in sorted(relay_root.glob("cx-*.yaml")):
        session = path.stem
        payload = _read_relay_yaml(path)
        if payload is None or _relay_payload_is_retired(payload):
            continue
        if payload.get("session") != session:
            continue
        if _lane_has_live_process(session):
            continue
        LOG.info("Reaping dead cx lane '%s' — no running process found", session)
        try:
            subprocess.run(
                [
                    str(retire_script),
                    session,
                    "--reason",
                    "reaped by hygiene sweeper (no running process)",
                ],
                timeout=5,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            LOG.warning("Failed to retire relay YAML for '%s'", session)
        else:
            reaped.append(session)

    return reaped


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
    """Load known role relay yaml plus Codex `cx-*.yaml` files."""
    from cc_hygiene.checks import _read_relay_yaml  # local helper

    payloads: dict[str, dict[str, Any]] = {}
    if not relay_root.is_dir():
        return payloads
    for role in KNOWN_ROLES:
        payload = _read_relay_yaml(relay_root / f"{role}.yaml")
        if payload is not None:
            if _relay_payload_is_retired(payload):
                continue
            payloads[role] = payload
    for path in sorted(relay_root.glob("cx-*.yaml")):
        role = path.stem
        payload = _read_relay_yaml(path)
        if payload is not None:
            # `cx-*.yaml` also includes read-only audit sidecars such as
            # `cx-amber-wsjf-007-velocity-audit.yaml`. Only the canonical
            # live relay file is named exactly after its `session`.
            if payload.get("session") != role:
                continue
            if _relay_payload_is_retired(payload):
                continue
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
    roles = list(KNOWN_ROLES)
    for role in sorted(relay_payloads):
        if role not in roles:
            roles.append(role)
    for role in sorted(in_progress_by_session):
        if role not in roles:
            roles.append(role)

    for role in roles:
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

    reaped = reap_dead_lanes(relay_root)
    if reaped:
        LOG.info("Reaped %d dead lane(s): %s", len(reaped), ", ".join(reaped))

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
    events.extend(check_spec_staleness(notes, now=now))

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
    parser.add_argument("--dashboard-path", type=Path, default=DEFAULT_DASHBOARD_PATH)
    parser.add_argument("--vault-active", type=Path, default=DEFAULT_VAULT_ACTIVE)
    parser.add_argument("--throttle-path", type=Path, default=DEFAULT_THROTTLE_PATH)
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Run the sweep but do not write event log or state JSON (diagnostic mode).",
    )
    parser.add_argument(
        "--no-ntfy",
        action="store_true",
        help="Skip the PR5 ntfy dispatch (dashboard renderer still runs).",
    )
    parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Skip the PR5 dashboard renderer (ntfy still runs).",
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
        # PR5 surface A — high-severity ntfy alerts (gated + throttled)
        if not args.no_ntfy:
            try:
                dispatch_alerts(
                    state.events,
                    now=state.sweep_timestamp,
                    throttle_path=args.throttle_path,
                )
            except Exception:  # noqa: BLE001
                LOG.exception("ntfy dispatch raised; continuing")
        # PR5 surface B — vault dashboard sentinel-block rewrite
        if not args.no_dashboard:
            try:
                update_dashboard(
                    state,
                    dashboard_path=args.dashboard_path,
                    event_log_path=args.event_log_path,
                    vault_active=args.vault_active,
                    now=state.sweep_timestamp,
                )
            except Exception:  # noqa: BLE001
                LOG.exception("dashboard render raised; continuing")
    if args.verbose:
        for event in state.events:
            LOG.debug("%s: %s", event.check_id, event.message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
