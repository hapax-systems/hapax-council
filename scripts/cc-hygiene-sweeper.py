#!/usr/bin/env python3
"""cc-hygiene-sweeper — read-only diagnostic daemon for vault cc-tasks.

PR1 of the task-list-hygiene plan
(`docs/research/2026-04-26-task-list-hygiene-operator-visibility.md`).
Implements the 8 checks described in §2 and emits:

* an append-only markdown event log under
  ``~/.cache/hapax/cc-hygiene-events.md`` (size-capped via whole-file rotation
  into an ``archive/`` sibling; see ``cc_hygiene.events``)
* a machine-readable JSON snapshot at
  ``~/.cache/hapax/cc-hygiene-state.json``

The 8 checks are read-only; the only mutation is the ghost-claimed self-heal
(``cc_hygiene.actions``, scoped to ``ghost_claimed``): a ``status: claimed`` note
with no claimer/``claimed_at`` is a definitional violation ``cc-claim`` cannot
produce, so it is reverted to ``offered`` (reversible, re-validated on disk) to
stop the violation re-firing every sweep. Disable with ``--no-actions``. The
other auto-actions (H2 stale-in-progress, H7 offered-stale) remain unwired.

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
from typing import Any, NamedTuple

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
    check_stale_claim_marker,
    check_stale_in_progress,
    check_vault_link_integrity,
    check_wip_limit,
    parse_task_note,
    read_claim_markers,
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

#: Point the live<->declared join at the real marker directory on a host whose
#: cache layout differs from the default derivation. Deliberately a CORRECTION and
#: not a mute: the check whose job is noticing that live state disagrees with
#: declared state is the last one that should be individually silenceable, and
#: "the derivation is wrong here" is answered by naming the right directory.
CLAIM_MARKER_DIR_ENV = "HAPAX_CC_HYGIENE_CLAIM_MARKER_DIR"


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


class VaultScan(NamedTuple):
    """One read of one task directory: what parsed, what did not, what failed.

    ONE scan, not three. The first repair kept three functions — a note loader, a
    rejected-path scan, a closed loader — each enumerating the directory again. That
    is not a view of the vault; it is three views, and a directory that failed on
    the first read and succeeded on the second produced a notes snapshot missing
    that directory beside an error list saying nothing went wrong. Measured in
    review round 13: an injected PermissionError on the first active/ enumeration,
    followed by a successful rescan, recorded no errors and produced
    retire-orphan-marker advice for a live in_progress task.

    A later successful rescan cannot repair an earlier snapshot, because nothing
    joins them. So the notes, the rejects and the errors are produced together, by
    the same read, and travel together to the decision.

    A NamedTuple rather than a dataclass: this module is extensionless and is loaded
    in tests through `spec_from_file_location`, where `@dataclass` raises
    `AttributeError: 'NoneType' object has no attribute '__dict__'` unless the
    loader registers the module in `sys.modules` before executing it. Requiring a
    loader to do that is a trap for the next loader; NamedTuple needs nothing.
    """

    notes: list[TaskNote]
    rejected: list[str]
    errors: list[str]


def _scan_task_notes(directory: Path) -> VaultScan:
    """Read one task directory once.

    `os.listdir`, not `Path.glob`: glob swallows a directory-level PermissionError
    inside its own scandir walk and returns an empty iterator, which is
    indistinguishable from an empty directory. An unreadable active/ therefore read
    as "no live tasks", and the live↔declared join recommended retiring a live
    claim's marker from a view it could not read.

    An ABSENT directory is not an error: a vault with no closed/ yet is normal. An
    unreadable one is.
    """
    if not directory.is_dir():
        return VaultScan(notes=[], rejected=[], errors=[])
    try:
        names = sorted(os.listdir(directory))
    except OSError as exc:
        return VaultScan(
            notes=[], rejected=[], errors=[f"{directory}: {type(exc).__name__}: {exc}"]
        )
    notes: list[TaskNote] = []
    rejected: list[str] = []
    for name in names:
        if not name.endswith(".md"):
            continue
        path = directory / name
        note = parse_task_note(path)
        if note is None:
            # `parse_task_note` returns None for anything without `type: cc-task` or
            # a readable task_id/status, and callers used to drop those silently.
            # That is fine for a check that only reports and unsafe for one that
            # recommends deleting runtime state: a rejected active note is precisely
            # a task the sweep cannot see, and it may own the marker being retired.
            rejected.append(str(path))
        else:
            notes.append(note)
    return VaultScan(notes=notes, rejected=rejected, errors=[])


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
        "spec_staleness",
        "vault_link_integrity",
        "stale_claim_marker",
    )
    return [CheckSummary(check_id=cid, fired=counter.get(cid, 0)) for cid in all_ids]


def run_sweep(
    *,
    vault_root: Path = DEFAULT_VAULT_ROOT,
    relay_root: Path = DEFAULT_RELAY_ROOT,
    repo_root: Path = DEFAULT_REPO_ROOT,
    claim_marker_dir: Path | None = None,
    reap: bool = True,
    now: datetime | None = None,
) -> HygieneState:
    """Perform one sweep and return the snapshot.

    The docstring used to say "Does NOT write to disk", and that was false in the
    one way that matters: `reap_dead_lanes` runs `hapax-relay-retire` against every
    lane with no live process, so a sweep MUTATES relay state before it computes a
    single event. `--no-write --no-actions` did not stop it, and the gate0b runbook
    recommended exactly that pair as a diagnostic — measured 2026-09-14T10:46:26Z:
    running it to verify the runbook retired `alpha`.

    So `reap` is a parameter, off in diagnostic mode. Events are still computed;
    only the action is withheld, which is what "observational" has to mean for a
    tool whose whole job is reporting on state it can also change.
    """
    now = now or datetime.now(UTC)
    started = time.monotonic()
    # Derived from relay_root, not from $HOME: cc-claim writes the markers beside
    # the relay dir, and every other root here is configurable. A marker source
    # anchored on the real home would make a sweep of some OTHER vault report on
    # THIS host's live lanes — which is both wrong in production and untestable.
    #
    # The coupling is IMPLICIT and worth stating: cc-claim writes to
    # $HOME/.cache/hapax while the default relay root is $HOME/.cache/hapax/relay,
    # so `relay_root.parent` coincides with the marker dir only because of that
    # layout. Relocate relay_root without relocating the cache and this join
    # silently points at a directory holding no markers — the absent-dir branch
    # catches a MISSING one, but a relocated-and-existing one reports clean while
    # checking nothing. Pass claim_marker_dir explicitly rather than relying on the
    # coincidence whenever the two are not siblings.
    # Two options were on the table for the relocation hazard: resolve from the
    # same source cc-claim uses ($HOME/.cache/hapax), or emit an event when the
    # derivation finds nothing. The first was TRIED and reverted — reading the real
    # $HOME makes a sweep of some other vault report on this host's live lanes,
    # which is the isolation defect this default was introduced to fix. So the
    # derivation stays, and the fail-open is closed below by an event instead.
    derived_marker_dir = claim_marker_dir is None
    if claim_marker_dir is None:
        claim_marker_dir = relay_root.parent
    # Carried onto EVERY event this check emits. The remaining hole the derivation
    # leaves is a directory that exists and is wrong — no guard here can see that,
    # because "wrong" is a fact about another process's configuration. What a reader
    # CAN be given is how the location was chosen, so a clean result is never
    # mistaken for a verified one.
    marker_dir_provenance = (
        f"derived from relay_root {relay_root} (cc-claim writes markers beside it)"
        if derived_marker_dir
        else "passed explicitly by the caller"
    )

    if reap:
        reaped = reap_dead_lanes(relay_root)
        if reaped:
            LOG.info("Reaped %d dead lane(s): %s", len(reaped), ", ".join(reaped))
    else:
        LOG.info("Reaping skipped (observational mode) — no relay was retired")

    # ONE read of each directory, here, for the whole sweep. Every consumer below
    # — including the live↔declared join, which recommends deleting runtime state —
    # gets notes, rejected paths and enumeration errors that describe the SAME read.
    active_scan = _scan_task_notes(vault_root / "active")
    closed_scan = _scan_task_notes(vault_root / "closed")
    notes = active_scan.notes
    closed_notes = closed_scan.notes
    vault_rejected = [*active_scan.rejected, *closed_scan.rejected]
    vault_errors = [*active_scan.errors, *closed_scan.errors]
    relay_payloads = _load_relay_payloads(relay_root)

    events: list[HygieneEvent] = []
    events.extend(check_stale_in_progress(notes, repo_root, now=now))
    events.extend(check_ghost_claimed(notes, now=now))
    events.extend(check_duplicate_claim(relay_payloads, now=now))
    events.extend(check_orphan_pr(notes, repo_root, closed_notes=closed_notes, now=now))
    events.extend(check_relay_yaml_staleness(relay_payloads, now=now))
    events.extend(check_wip_limit(notes, now=now))
    events.extend(check_offered_staleness(notes, now=now))
    events.extend(check_refusal_pipeline_dormancy(closed_notes, now=now))
    events.extend(check_spec_staleness(notes, now=now))
    # Resolve parent_* links against the whole vault + repo, not just the
    # cc-tasks dir: cc-tasks lives at <personal>/20-projects/hapax-cc-tasks,
    # so its grandparent is the Obsidian vault root the links resolve against.
    events.extend(
        check_vault_link_integrity(notes, vault_root.parent.parent, repo_root=repo_root, now=now)
    )
    # The live<->declared join: every other check reads the vault and asks whether
    # the DECLARED state is self-consistent. This one reads the runtime markers the
    # gate actually keys on and asks whether they still agree with it.
    # An absent marker dir makes this check inert, and read_claim_markers returns
    # {} for both "no drift" and "I could not read anything" — so a reconciliation
    # check would report clean while checking nothing. Say so instead.
    if not claim_marker_dir.is_dir():
        events.append(
            HygieneEvent(
                timestamp=now,
                check_id="stale_claim_marker",
                # VIOLATION, not warning. ntfy alerts gate on `violation`
                # (cc_hygiene/models.py), so a warning lands in the dashboard and
                # pages nobody — practically the same outcome as the silence this
                # event exists to replace, just with a record. A reconciliation that
                # checked nothing is exactly the case someone has to notice.
                severity="violation",
                task_id=None,
                session=None,
                message=(
                    f"claim marker directory {claim_marker_dir} does not exist — the "
                    "live↔declared join checked nothing this sweep"
                ),
                metadata={
                    "marker_dir": str(claim_marker_dir),
                    "marker_dir_provenance": marker_dir_provenance,
                    "next_action": "operator-adjudication",
                    "reason": "marker_dir_absent",
                },
            )
        )
    else:
        scan = read_claim_markers(claim_marker_dir)
        # A DERIVED marker dir that exists but holds nothing is the relocation
        # hazard the comment above names: the absent-dir branch catches a missing
        # directory, not a relocated-and-empty one, so without this the join
        # reports clean while reconciling nothing. An empty cache is legitimate on
        # an idle host, so this is a warning that names where it looked — not a
        # violation — and it is raised only when the dir was derived rather than
        # passed, since an explicit dir is the caller's assertion about where to look.
        if derived_marker_dir and not scan.markers and scan.enumeration_error is None:
            # WARNING, not violation — and the reason matters, because escalating
            # here was TRIED and is unsound. "The vault records held tasks, so the
            # cache must hold markers" looks compelling and is false twice over: a
            # ghost claim is precisely a claimed note with no marker (cc-hygiene has
            # a separate check for exactly that), and a task held by a lane on
            # another host has no marker here either. Escalating on that inference
            # pages falsely on both. This records where the join looked and what it
            # found; escalation belongs to the checks that can tell those apart.
            held = [n for n in notes if (n.status or "").strip() in {"claimed", "in_progress"}]
            events.append(
                HygieneEvent(
                    timestamp=now,
                    check_id="stale_claim_marker",
                    severity="warning",
                    message=(
                        f"claim marker directory {claim_marker_dir} (derived from "
                        f"relay_root {relay_root}) holds no cc-active-task-* markers "
                        f"while the vault records {len(held)} claimed/in_progress "
                        "task(s) — the join reconciled nothing. Expected on an idle "
                        "host, or where those tasks are held elsewhere or are ghost "
                        "claims; otherwise the derivation points at the wrong directory"
                    ),
                    metadata={
                        "marker_dir": str(claim_marker_dir),
                        "marker_dir_provenance": marker_dir_provenance,
                        "relay_root": str(relay_root),
                        "held_task_count": str(len(held)),
                        "next_action": "operator-adjudication",
                        "reason": "marker_dir_empty",
                    },
                )
            )
        events.extend(
            check_stale_claim_marker(
                scan,
                notes,
                closed_notes,
                cache_dir=claim_marker_dir,
                unparsed_notes=vault_rejected,
                enumeration_errors=vault_errors,
                marker_dir_provenance=marker_dir_provenance,
                now=now,
            )
        )

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
    parser.add_argument(
        "--no-actions",
        action="store_true",
        help="Skip the ghost-claimed self-heal auto-action (observational mode).",
    )
    parser.add_argument(
        "--claim-marker-dir",
        type=Path,
        default=None,
        help=(
            "Where cc-claim writes cc-active-task-* markers. Defaults to the parent "
            "of --relay-root, which coincides with cc-claim's cache by layout. Pass "
            "it (or set HAPAX_CC_HYGIENE_CLAIM_MARKER_DIR) on a host whose cache "
            "layout differs, so the live<->declared join is CORRECTED rather than "
            "silenced."
        ),
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

    # An explicit marker dir CORRECTS a wrong derivation rather than muting the
    # check. Review round 14 asked for an emergency bypass for stale_claim_marker,
    # naming "a host whose cache layout differs" as the misfire — and a per-check
    # mute is the wrong answer to that: it leaves the drift in place and removes
    # the only thing reporting it. The sweeper-wide killswitch above still exists
    # for a genuinely misbehaving sweeper. This is the narrower control, and it is
    # the one that fits the named cause.
    claim_marker_dir = args.claim_marker_dir
    if claim_marker_dir is None:
        env_dir = (os.environ.get(CLAIM_MARKER_DIR_ENV) or "").strip()
        if env_dir:
            claim_marker_dir = Path(env_dir)
    state = run_sweep(
        vault_root=args.vault_root,
        relay_root=args.relay_root,
        repo_root=args.repo_root,
        claim_marker_dir=claim_marker_dir,
        # Retiring a relay is an ACTION, so --no-actions withholds it. --no-write
        # counts too: a flag pair a runbook offers as "writes no state" must not
        # leave one mutation outside both of them, which is how a diagnostic run
        # retired a live lane.
        reap=not (args.no_actions or args.no_write),
    )
    LOG.info(
        "sweep complete: %d events in %d ms",
        len(state.events),
        state.sweep_duration_ms,
    )
    if not args.no_write:
        append_events(state.events, state.sweep_timestamp, path=args.event_log_path)
        write_state(state, path=args.state_path)
        # Effect-based self-heal: a ghost-claimed note (status: claimed with no
        # claimer/claimed_at) is a definitional violation cc-claim cannot produce
        # (freehand frontmatter edits bypass the atomic claimer). Left alone it
        # re-fires every sweep -> a notification storm (P0 incident 2026-06-13, 39x).
        # Reverting it to `offered` (reversible, idempotent, re-validated on disk)
        # makes the violation stop recurring at source — independent of which
        # producer created it. Scoped to ghost_claimed only; H2/H7 stay unwired.
        healed_ghost_ids: set[str] = set()
        if not args.no_actions:
            ghost_events = [e for e in state.events if e.check_id == "ghost_claimed"]
            if ghost_events:
                from cc_hygiene.actions import apply_actions

                notes = _scan_task_notes(args.vault_root / "active").notes
                for result in apply_actions(
                    ghost_events,
                    notes,
                    vault_root=args.vault_root,
                    now=state.sweep_timestamp,
                ):
                    LOG.info("ghost-claim self-heal %s: %s", result.task_id, result.message)
                    if result.success and result.action_id == "ghost_claimed_revert":
                        healed_ghost_ids.add(result.task_id)
        # PR5 surface A — high-severity ntfy alerts (gated + throttled).
        #
        # A ghost_claimed event self-healed in THIS sweep is already remediated,
        # so it must not page the operator — and, downstream, must not mint a
        # fresh P0 incident task. That was the recurrence #4140 left open: the
        # heal stopped the *re-fire* (storm), but the *first* detection still
        # dispatched a `violation` ntfy every time, so each transient ghost minted
        # one duplicate P0 task (one per task_id; 2026-06-15/16 ledger storm).
        # Suppress ONLY events whose heal succeeded this sweep; an un-healed ghost
        # (race/skip/write-fail, or --no-actions observational mode) still pages —
        # that is the genuinely actionable case. append_events() already recorded
        # the full detection above and the dashboard receives the unfiltered
        # state, so this routes by severity, it does not avoid detection.
        if not args.no_ntfy:
            alert_events = [
                e
                for e in state.events
                if not (e.check_id == "ghost_claimed" and e.task_id in healed_ghost_ids)
            ]
            try:
                dispatch_alerts(
                    alert_events,
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
            # Metadata too, not just check_id and message. The runbook tells an
            # operator to verify `marker_dir` and `marker_dir_provenance` from a
            # `--no-write --no-actions -v` run — and verbose printed neither, while
            # --no-write meant nothing was recorded to read them from afterwards. A
            # documented verification that cannot display the field it verifies is
            # not a recheck (review round 19).
            detail = (
                " ".join(f"{k}={v}" for k, v in sorted(event.metadata.items()))
                if event.metadata
                else ""
            )
            LOG.debug("%s: %s%s", event.check_id, event.message, f" [{detail}]" if detail else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
