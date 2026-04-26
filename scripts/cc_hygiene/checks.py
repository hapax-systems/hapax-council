"""The 8 hygiene checks, per research §2.

All checks are read-only pure functions: they consume parsed vault notes
and relay yamls and emit ``HygieneEvent`` lists. Auto-actions are PR2
territory and live in a separate module.

Each check has a docstring that names the trigger condition, threshold,
and severity choice. Tunable thresholds are module-level constants so
operator can patch via env or future config without rewriting code.
"""

from __future__ import annotations

import re
import subprocess
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from .models import HygieneEvent, Role, TaskNote

# ----- thresholds (research §2 starting points) -----

STALE_IN_PROGRESS_HOURS = 24
"""§2.1 hard threshold: 24h with no commit/PR activity → stale."""

DUPLICATE_CLAIM_WINDOW_MIN = 5
"""§2.3: same task_id in 2+ relay yamls within this window."""

ORPHAN_PR_AGE_HOURS = 1
"""§2.4: open PR older than this with no vault link."""

RELAY_STALE_MIN = 30
"""§2.5: relay yaml `updated` older than this is stale."""

WIP_LIMIT = 3
"""§2.6: max in_progress per session before warning."""

OFFERED_STALE_DAYS = 14
"""§2.7: offered task older than this with no claim is stale-on-arrival."""

REFUSAL_DORMANCY_DAYS = 7
"""§2.8: zero `status: refused` in this window is a dormancy signal."""

KNOWN_ROLES: tuple[Role, ...] = ("alpha", "beta", "delta", "epsilon")


# ----- helpers -----


def _now() -> datetime:
    return datetime.now(UTC)


def _ensure_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _git_log_count_since(repo_root: Path, branch: str, since_hours: int) -> int:
    """Count commits on ``branch`` in the last ``since_hours``.

    Returns 0 on any error — read-only sweeper must never crash on a
    missing branch or shell hiccup.
    """
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "log",
                f"--since={since_hours}h",
                "--oneline",
                branch,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError):
        return 0
    if result.returncode != 0:
        return 0
    return sum(1 for line in result.stdout.splitlines() if line.strip())


def _gh_pr_list(repo_root: Path) -> list[dict[str, Any]]:
    """Return open PRs as a list of dicts (number, headRefName, createdAt, updatedAt).

    Returns ``[]`` on any error (gh missing, unauthenticated, network).
    """
    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--state",
                "open",
                "--json",
                "number,headRefName,createdAt,updatedAt",
                "--limit",
                "100",
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(repo_root),
            timeout=15,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    if result.returncode != 0:
        return []
    import json

    try:
        return json.loads(result.stdout) or []
    except json.JSONDecodeError:
        return []


def _gh_pr_view_updated(repo_root: Path, pr_number: int) -> datetime | None:
    """Return PR `updatedAt` as aware datetime, or None on failure."""
    try:
        result = subprocess.run(
            ["gh", "pr", "view", str(pr_number), "--json", "updatedAt"],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(repo_root),
            timeout=15,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if result.returncode != 0:
        return None
    import json

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    raw = data.get("updatedAt")
    if not raw:
        return None
    try:
        # gh returns ISO-8601 with 'Z' suffix
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


# ----- relay-yaml parsing helpers -----


def _read_relay_yaml(path: Path) -> dict[str, Any] | None:
    """Read a relay yaml; tolerate missing or malformed files."""
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return None


def _extract_relay_updated(payload: dict[str, Any]) -> datetime | None:
    """Best-effort parse of `updated` (or `last_updated`) from a relay yaml.

    Some yamls use `updated`, some use `session_status.timestamp` or
    similar. Walk a few common spellings; missing → None.
    """
    for key in ("updated", "last_updated", "timestamp"):
        raw = payload.get(key)
        if raw:
            return _parse_dt(raw)
    status = payload.get("session_status")
    if isinstance(status, dict):
        for key in ("updated", "timestamp", "last_updated"):
            raw = status.get(key)
            if raw:
                return _parse_dt(raw)
    return None


def _extract_current_claim(payload: dict[str, Any]) -> tuple[str | None, datetime | None]:
    """Return (task_id, claimed_at) from `current_claim`. Tolerant of shape."""
    claim = payload.get("current_claim")
    if not claim:
        return None, None
    if isinstance(claim, str):
        return claim, None
    if isinstance(claim, dict):
        return claim.get("task_id"), _parse_dt(claim.get("claimed_at"))
    return None, None


def _parse_dt(raw: Any) -> datetime | None:
    """Parse a value that might be a string, datetime, or date."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return _ensure_aware(raw)
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            return _ensure_aware(datetime.fromisoformat(s.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


# ----- the 8 checks -----


def check_stale_in_progress(
    notes: Iterable[TaskNote], repo_root: Path, *, now: datetime | None = None
) -> list[HygieneEvent]:
    """§2.1 — `status: in_progress` AND no commit/PR activity in 24h.

    Severity: warning (operator may want to revert; auto-action is PR2).
    """
    now = now or _now()
    events: list[HygieneEvent] = []
    cutoff = now - timedelta(hours=STALE_IN_PROGRESS_HOURS)
    for note in notes:
        if note.status != "in_progress":
            continue
        updated = _ensure_aware(note.updated_at)
        if updated is not None and updated >= cutoff:
            continue
        # secondary signal: branch activity
        if note.branch:
            commit_count = _git_log_count_since(repo_root, note.branch, STALE_IN_PROGRESS_HOURS)
            if commit_count > 0:
                continue
        # tertiary: PR activity
        if note.pr:
            pr_updated = _gh_pr_view_updated(repo_root, note.pr)
            if pr_updated and pr_updated >= cutoff:
                continue
        events.append(
            HygieneEvent(
                timestamp=now,
                check_id="stale_in_progress",
                severity="warning",
                task_id=note.task_id,
                session=note.assigned_to,
                message=(
                    f"task '{note.task_id}' is in_progress with no commit/PR "
                    f"activity in {STALE_IN_PROGRESS_HOURS}h"
                ),
                metadata={
                    "branch": note.branch or "",
                    "pr": str(note.pr) if note.pr else "",
                    "threshold_hours": str(STALE_IN_PROGRESS_HOURS),
                },
            )
        )
    return events


def check_ghost_claimed(
    notes: Iterable[TaskNote], *, now: datetime | None = None
) -> list[HygieneEvent]:
    """§2.2 — `status: claimed` AND (`assigned_to: unassigned` OR `claimed_at: null`).

    Severity: violation (definitional — `cc-claim` cannot produce this).
    """
    now = now or _now()
    events: list[HygieneEvent] = []
    for note in notes:
        if note.status != "claimed":
            continue
        ghost = note.assigned_to in (None, "unassigned") or note.claimed_at is None
        if not ghost:
            continue
        events.append(
            HygieneEvent(
                timestamp=now,
                check_id="ghost_claimed",
                severity="violation",
                task_id=note.task_id,
                session=note.assigned_to if note.assigned_to != "unassigned" else None,
                message=(
                    f"task '{note.task_id}' is claimed but assigned_to="
                    f"{note.assigned_to!r} claimed_at={note.claimed_at!r} "
                    f"(definitional violation)"
                ),
                metadata={
                    "assigned_to": str(note.assigned_to),
                    "claimed_at": str(note.claimed_at),
                },
            )
        )
    return events


def check_duplicate_claim(
    relay_payloads: dict[str, dict[str, Any]], *, now: datetime | None = None
) -> list[HygieneEvent]:
    """§2.3 — same `task_id` in 2+ relay yamls' ``current_claim`` within 5min.

    Severity: violation. Only fires when both relays are within window.
    """
    now = now or _now()
    events: list[HygieneEvent] = []
    by_task: defaultdict[str, list[tuple[str, datetime | None]]] = defaultdict(list)
    for role, payload in relay_payloads.items():
        task_id, claimed_at = _extract_current_claim(payload)
        if task_id:
            by_task[task_id].append((role, claimed_at))
    window = timedelta(minutes=DUPLICATE_CLAIM_WINDOW_MIN)
    for task_id, claimers in by_task.items():
        if len(claimers) < 2:
            continue
        # if any pair is within window (or claimed_at unknown), fire
        sortable = [(role, ts or now) for role, ts in claimers]
        sortable.sort(key=lambda pair: pair[1])
        oldest_ts = sortable[0][1]
        newest_ts = sortable[-1][1]
        if newest_ts - oldest_ts > window:
            continue
        roles = [role for role, _ in sortable]
        events.append(
            HygieneEvent(
                timestamp=now,
                check_id="duplicate_claim",
                severity="violation",
                task_id=task_id,
                session=None,
                message=(
                    f"task '{task_id}' claimed simultaneously by sessions "
                    f"{roles} within {DUPLICATE_CLAIM_WINDOW_MIN}min"
                ),
                metadata={
                    "sessions": ",".join(roles),
                    "window_minutes": str(DUPLICATE_CLAIM_WINDOW_MIN),
                },
            )
        )
    return events


def check_orphan_pr(
    notes: Iterable[TaskNote], repo_root: Path, *, now: datetime | None = None
) -> list[HygieneEvent]:
    """§2.4 — open PR > 1h old with no vault cc-task linking it.

    Severity: warning. Auto-link is refused (false-positive risk).
    """
    now = now or _now()
    events: list[HygieneEvent] = []
    linked = {note.pr for note in notes if note.pr}
    cutoff = now - timedelta(hours=ORPHAN_PR_AGE_HOURS)
    for pr in _gh_pr_list(repo_root):
        number = pr.get("number")
        if not isinstance(number, int) or number in linked:
            continue
        created_raw = pr.get("createdAt")
        created = _parse_dt(created_raw) if created_raw else None
        if created and created > cutoff:
            continue  # too young
        events.append(
            HygieneEvent(
                timestamp=now,
                check_id="orphan_pr",
                severity="warning",
                task_id=None,
                session=None,
                message=(
                    f"PR #{number} ({pr.get('headRefName', '?')}) open with no "
                    f"vault cc-task `pr` field linking it"
                ),
                metadata={
                    "pr": str(number),
                    "branch": str(pr.get("headRefName", "")),
                    "createdAt": str(created_raw or ""),
                    "threshold_hours": str(ORPHAN_PR_AGE_HOURS),
                },
            )
        )
    return events


def check_relay_yaml_staleness(
    relay_payloads: dict[str, dict[str, Any]], *, now: datetime | None = None
) -> list[HygieneEvent]:
    """§2.5 — relay yaml `updated` > 30min ago.

    Severity: warning (`hard` 30min; soft `15min` is informational only;
    the spec maps the soft tier to UI color in PR4, not to a separate
    event).
    """
    now = now or _now()
    events: list[HygieneEvent] = []
    cutoff = now - timedelta(minutes=RELAY_STALE_MIN)
    for role, payload in relay_payloads.items():
        updated = _extract_relay_updated(payload)
        if updated is None:
            events.append(
                HygieneEvent(
                    timestamp=now,
                    check_id="relay_yaml_stale",
                    severity="info",
                    task_id=None,
                    session=role,
                    message=f"relay yaml for '{role}' has no parseable `updated` timestamp",
                    metadata={"role": role},
                )
            )
            continue
        if updated < cutoff:
            age_min = int((now - updated).total_seconds() // 60)
            events.append(
                HygieneEvent(
                    timestamp=now,
                    check_id="relay_yaml_stale",
                    severity="warning",
                    task_id=None,
                    session=role,
                    message=(
                        f"relay yaml for '{role}' is {age_min}min stale "
                        f"(threshold {RELAY_STALE_MIN}min)"
                    ),
                    metadata={
                        "role": role,
                        "age_minutes": str(age_min),
                        "threshold_minutes": str(RELAY_STALE_MIN),
                    },
                )
            )
    return events


def check_wip_limit(
    notes: Iterable[TaskNote], *, now: datetime | None = None
) -> list[HygieneEvent]:
    """§2.6 — single session has > WIP_LIMIT tasks in `status: in_progress`.

    Severity: warning (soft only — hard-block would stall, refused per
    `feedback_never_stall_revert_acceptable`).
    """
    now = now or _now()
    by_session: Counter[str] = Counter()
    for note in notes:
        if note.status == "in_progress" and note.assigned_to:
            if note.assigned_to == "unassigned":
                continue
            by_session[note.assigned_to] += 1
    events: list[HygieneEvent] = []
    for session, count in by_session.items():
        if count <= WIP_LIMIT:
            continue
        events.append(
            HygieneEvent(
                timestamp=now,
                check_id="wip_limit",
                severity="warning",
                task_id=None,
                session=session,
                message=(f"session '{session}' has {count} tasks in_progress (limit {WIP_LIMIT})"),
                metadata={
                    "session": session,
                    "in_progress_count": str(count),
                    "limit": str(WIP_LIMIT),
                },
            )
        )
    return events


def check_offered_staleness(
    notes: Iterable[TaskNote], *, now: datetime | None = None
) -> list[HygieneEvent]:
    """§2.7 — offered AND `created_at` > 14d AND `updated_at` <= `created_at`.

    Severity: info (auto-archive is PR2; this is observational).
    """
    now = now or _now()
    cutoff = now - timedelta(days=OFFERED_STALE_DAYS)
    events: list[HygieneEvent] = []
    for note in notes:
        if note.status != "offered":
            continue
        created = _ensure_aware(note.created_at)
        if created is None or created > cutoff:
            continue
        updated = _ensure_aware(note.updated_at)
        if updated and updated > created:
            continue  # touched after creation → not dead-on-arrival
        age_days = int((now - created).total_seconds() // 86400)
        events.append(
            HygieneEvent(
                timestamp=now,
                check_id="offered_stale",
                severity="info",
                task_id=note.task_id,
                session=None,
                message=(
                    f"task '{note.task_id}' offered for {age_days}d with no "
                    f"updates (threshold {OFFERED_STALE_DAYS}d)"
                ),
                metadata={
                    "age_days": str(age_days),
                    "threshold_days": str(OFFERED_STALE_DAYS),
                    "created_at": str(note.created_at),
                },
            )
        )
    return events


def check_refusal_pipeline_dormancy(
    closed_notes: Iterable[TaskNote], *, now: datetime | None = None
) -> list[HygieneEvent]:
    """§2.8 — zero `status: refused` events in last 7 days.

    Severity: info. Surfaces *absence* of an expected signal; not a
    violation per se. Reads from the closed/ archive plus active/ notes.
    """
    now = now or _now()
    cutoff = now - timedelta(days=REFUSAL_DORMANCY_DAYS)
    refused_recent = 0
    for note in closed_notes:
        if note.status != "refused":
            continue
        ts = _ensure_aware(note.updated_at) or _ensure_aware(note.created_at)
        if ts and ts >= cutoff:
            refused_recent += 1
    if refused_recent > 0:
        return []
    return [
        HygieneEvent(
            timestamp=now,
            check_id="refusal_dormancy",
            severity="info",
            task_id=None,
            session=None,
            message=(
                f"zero `status: refused` notes in last {REFUSAL_DORMANCY_DAYS}d "
                f"(refusal pipeline may be unwired)"
            ),
            metadata={"window_days": str(REFUSAL_DORMANCY_DAYS)},
        )
    ]


# ----- frontmatter parsing (used by sweeper main) -----

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


def parse_task_note(path: Path) -> TaskNote | None:
    """Best-effort parse of a vault cc-task note. Returns None on any failure."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(fm, dict):
        return None
    if fm.get("type") != "cc-task":
        return None
    task_id = fm.get("task_id")
    status = fm.get("status")
    if not task_id or not status:
        return None
    pr = fm.get("pr")
    if isinstance(pr, str):
        try:
            pr = int(pr)
        except ValueError:
            pr = None
    elif not isinstance(pr, int):
        pr = None
    return TaskNote(
        path=str(path),
        task_id=str(task_id),
        status=str(status),
        assigned_to=fm.get("assigned_to"),
        claimed_at=_parse_dt(fm.get("claimed_at")),
        branch=fm.get("branch"),
        pr=pr,
        created_at=_parse_dt(fm.get("created_at")),
        updated_at=_parse_dt(fm.get("updated_at")),
    )
