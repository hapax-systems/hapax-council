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

from shared.sdlc_owner_identity import parse_task_owner

from .models import HygieneEvent, Role, TaskNote


def _session_role(owner: str | None) -> str | None:
    if owner is None:
        return None
    try:
        identity = parse_task_owner(owner)
    except ValueError:
        return owner
    return identity.role if identity is not None else None


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

GHOST_CLAIM_GRACE_MINUTES = 10
"""§2.2 grace window: ghost-claimed notes modified within this window are
skipped — a mid-claim partial stamp must not be reverted out from under a
freshly launched lane (2026-07-01 eta/ndcvb-phase1 incident)."""

REFUSAL_DORMANCY_DAYS = 7
"""§2.8: zero canonical refusal notes in this window is a dormancy signal."""

SPEC_STALENESS_DAYS = 7
"""Hard threshold: active requests older than 7d with no cc-tasks."""

KNOWN_ROLES: tuple[Role, ...] = ("alpha", "beta", "delta", "epsilon")
"""Permanent Claude worktree slots. Codex cx-* relay files are discovered dynamically."""

# Status values that mean the session is no longer ticking and should not
# be staleness-checked. A retired/wound-down lane is correctly silent;
# flagging it as stale is noise. Matched case-insensitively.
#
# Empirical note (2026-05-01): the post-codex cx-* lanes carry several
# spelling variants — `idle_wound_down`, `wind_down_idle`, `wind_down`,
# and `wound_down`. We accept all four. The retirement contract is
# semantic ("this lane has stopped ticking"), not strict-spelling, so
# the recognizer is permissive on word order + form.
RETIRED_STATUS_VALUES: frozenset[str] = frozenset(
    {
        "retired",
        "superseded",
        "closed",
        "idle_wound_down",
        "wind_down_idle",
        "wound_down",
        "wind_down",
        "winding_down",
        "antigravity_takeover",
    }
)


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
    """Return open PRs as a list of dicts (number, headRefName, createdAt, updatedAt, author).

    ``author`` is included so the orphan-PR predicate can exclude bot-authored
    PRs (Dependabot/Renovate), which live outside the cc-task workflow.

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
                "number,headRefName,createdAt,updatedAt,author",
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
    for key in ("updated", "updated_at", "last_updated", "timestamp"):
        raw = payload.get(key)
        if raw:
            return _parse_dt(raw)
    status = payload.get("session_status")
    if isinstance(status, dict):
        for key in ("updated", "updated_at", "timestamp", "last_updated"):
            raw = status.get(key)
            if raw:
                return _parse_dt(raw)
    return None


def _is_retired_session(payload: dict[str, Any]) -> bool:
    """Detect a retired / wound-down session whose silence is correct.

    Walks the same shape as ``_extract_relay_updated`` looking for a
    status / state field whose value is in ``RETIRED_STATUS_VALUES``.
    Tolerant of either a flat ``status`` key or a nested
    ``session_status.status`` / ``session_status.state``.
    """
    candidates: list[Any] = []
    for key in ("status", "state", "relay_status", "session_state"):
        candidates.append(payload.get(key))
    nested = payload.get("session_status")
    if isinstance(nested, dict):
        for key in ("status", "state"):
            candidates.append(nested.get(key))
    elif isinstance(nested, str):
        candidates.append(nested)
    for raw in candidates:
        if not isinstance(raw, str):
            continue
        normalized = raw.strip().strip("\"'").lower()
        # session_status: "RETIRED foo bar" — match on the leading word
        # so multi-line scalars or annotations don't defeat the check.
        first_word = normalized.split()[0] if normalized.split() else ""
        if first_word in RETIRED_STATUS_VALUES:
            return True
        if normalized in RETIRED_STATUS_VALUES:
            return True
    return False


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
                session=_session_role(note.assigned_to),
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

    Grace window: a ghost whose note file changed within
    ``GHOST_CLAIM_GRACE_MINUTES`` is skipped. A partially stamped claim
    (target keys absent when cc-claim's substitutions ran) looks ghost for
    the moments between the stamp and the sweep, and the H1 revert then
    kills the freshly launched lane via the launcher's terminal check
    (2026-07-01 eta/ndcvb-phase1 incident). A real ghost goes quiet and is
    flagged on the first sweep after the window.

    Known limitation: the window is anchored to file mtime, so a writer that
    touches a genuinely ghost note more often than the window (vault sync,
    hook appends) defers detection while it keeps writing. Accepted: those
    writers are themselves sweep-visible, and anchoring to frontmatter
    timestamps is impossible here — the ghost predicate is precisely that
    claimed_at is missing.
    """
    now = now or _now()
    events: list[HygieneEvent] = []
    for note in notes:
        if note.status != "claimed":
            continue
        ghost = note.assigned_to in (None, "unassigned") or note.claimed_at is None
        if not ghost:
            continue
        try:
            mtime = datetime.fromtimestamp(Path(note.path).stat().st_mtime, tz=UTC)
        except OSError:
            mtime = None
        if mtime is not None and now - mtime < timedelta(minutes=GHOST_CLAIM_GRACE_MINUTES):
            continue
        events.append(
            HygieneEvent(
                timestamp=now,
                check_id="ghost_claimed",
                severity="violation",
                task_id=note.task_id,
                session=_session_role(note.assigned_to),
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

    Severity: violation. Fires one event per *cluster* of claimants whose
    sorted claim times are each within the window of their neighbor. A
    chain (a→b→c with sub-window gaps) is one event even if its total span
    exceeds the window; disjoint bursts hours apart are separate events.
    """
    now = now or _now()
    events: list[HygieneEvent] = []
    by_task: defaultdict[str, list[tuple[str, datetime | None]]] = defaultdict(list)
    for role, payload in relay_payloads.items():
        task_id, claimed_at = _extract_current_claim(payload)
        if task_id:
            # A bare-string `current_claim` carries no `claimed_at`; fall back
            # to the relay's own `updated` stamp so the window has a real time
            # to compare. Never substitute `now` — that collapses every unknown
            # timestamp to the same instant, defeating the window and firing a
            # false "claimed simultaneously within 5min" on every sweep for a
            # stale collision (the duplicate_claim P0 storm: two relays 91min
            # apart stormed 52 pages because both timestamps read as `now`).
            ts = claimed_at or _extract_relay_updated(payload)
            by_task[task_id].append((role, ts))
    window = timedelta(minutes=DUPLICATE_CLAIM_WINDOW_MIN)
    for task_id, claimers in by_task.items():
        if len(claimers) < 2:
            continue
        # Only claimants with a known timestamp can establish that the claims
        # fall within the window. If fewer than two are datable, we cannot
        # distinguish a genuine near-simultaneous double-claim from a stale
        # leftover, so we stay silent (a stale relay is `relay_yaml_stale`'s
        # job, not a false duplicate_claim).
        datable = [(role, ts) for role, ts in claimers if ts is not None]
        if len(datable) < 2:
            continue
        datable.sort(key=lambda pair: pair[1])
        # Cluster on adjacent within-window gaps, not on the total
        # oldest→newest span: a span check lets one stale claimant mask a
        # genuine near-simultaneous pair among the others (three claimants,
        # one hours old + two minutes apart, must still fire for the fresh
        # pair). Sorted order guarantees the closest pair is adjacent. Each
        # cluster alerts separately so one event never lumps together
        # claimants that are hours apart.
        clusters: list[list[str]] = []
        cluster_roles = [datable[0][0]]
        cluster_end = datable[0][1]
        for role, ts in datable[1:]:
            if ts - cluster_end <= window:
                cluster_roles.append(role)
            else:
                clusters.append(cluster_roles)
                cluster_roles = [role]
            cluster_end = ts
        clusters.append(cluster_roles)
        for roles in clusters:
            if len(roles) < 2:
                continue
            events.append(
                HygieneEvent(
                    timestamp=now,
                    check_id="duplicate_claim",
                    severity="violation",
                    task_id=task_id,
                    session=None,
                    message=(
                        f"task '{task_id}' claimed by sessions {roles} with "
                        f"claim times chained within "
                        f"{DUPLICATE_CLAIM_WINDOW_MIN}min of a neighbor"
                    ),
                    metadata={
                        "sessions": ",".join(roles),
                        "window_minutes": str(DUPLICATE_CLAIM_WINDOW_MIN),
                    },
                )
            )
    return events


def _pr_author_is_bot(pr: dict[str, Any]) -> bool:
    """True if the PR was opened by a bot (Dependabot, Renovate, github-actions).

    Bot-authored PRs are automated dependency/maintenance updates that live
    outside the cc-task workflow by design: they will never carry a vault
    cc-task ``pr`` link, so the orphan-PR predicate must not treat them as
    hygiene violations (that produced a false-positive P0, incident
    ``cc_hygiene_violation:orphan_pr:4408`` — Dependabot bumped hapax-logos npm
    deps and the never-linkable PR aged past the 6h ntfy threshold).

    Robust to two independent GitHub signals so a single API-shape change
    cannot silently reopen the false positive:

    * the ``author.is_bot`` boolean (primary, from ``gh pr list --json author``),
      and
    * the login conventions ``<name>[bot]`` / ``app/<name>`` used for GitHub
      App / bot accounts (fallback when ``is_bot`` is absent).
    """
    author = pr.get("author")
    if not isinstance(author, dict):
        return False
    if author.get("is_bot") is True:
        return True
    login = str(author.get("login", ""))
    return login.endswith("[bot]") or login.startswith("app/")


def check_orphan_pr(
    notes: Iterable[TaskNote],
    repo_root: Path,
    *,
    closed_notes: Iterable[TaskNote] = (),
    now: datetime | None = None,
) -> list[HygieneEvent]:
    """§2.4 — open PR > 1h old with no vault cc-task linking it.

    Severity: warning. Auto-link is refused (false-positive risk).

    A PR counts as linked when ANY task note — active OR closed — carries its
    number in ``pr``. Tasks are routinely closed (moved to ``closed/``) the
    moment their PR opens, well before the PR merges; consulting only active
    notes mislabels every such PR as an orphan and fires a recurring 5-min
    notification storm for the PR's whole open lifetime (P0 incident
    ``orphan_pr:4111``, count 215). ``closed_notes`` defaults to empty so
    callers that only have active notes keep the prior behavior.

    Bot-authored PRs (Dependabot/Renovate) are excluded via
    ``_pr_author_is_bot``: they are never cc-task-tracked, so flagging them as
    orphans is a false positive (P0 incident ``orphan_pr:4408``).
    """
    now = now or _now()
    events: list[HygieneEvent] = []
    linked: set[int] = set()
    for note in (*notes, *closed_notes):
        if note.pr:
            linked.add(note.pr)
        linked.update(note.linked_prs)
    cutoff = now - timedelta(hours=ORPHAN_PR_AGE_HOURS)
    for pr in _gh_pr_list(repo_root):
        number = pr.get("number")
        if not isinstance(number, int) or number in linked:
            continue
        if _pr_author_is_bot(pr):
            continue  # Dependabot/Renovate — outside the cc-task workflow
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
        # Retired / wound-down sessions are correctly silent; their
        # staleness is the expected steady state, not a hygiene event.
        if _is_retired_session(payload):
            continue
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
            session = _session_role(note.assigned_to)
            if session is not None:
                by_session[session] += 1
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
    """§2.8 — zero canonical refusal notes in last 7 days.

    Severity: info. Surfaces *absence* of an expected signal; not a
    violation per se. Reads from the closed/ archive plus active/ notes.

    Canonical refusal representation is ``automation_status: REFUSED``.
    Legacy ``status: refused`` notes still count so older vault exports do not
    create a false dormancy signal.
    """
    now = now or _now()
    cutoff = now - timedelta(days=REFUSAL_DORMANCY_DAYS)
    refused_recent = 0
    for note in closed_notes:
        is_refused = note.automation_status == "REFUSED" or note.status == "refused"
        if not is_refused:
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
                f"zero canonical refusal notes in last {REFUSAL_DORMANCY_DAYS}d "
                f"(refusal pipeline may be unwired)"
            ),
            metadata={"window_days": str(REFUSAL_DORMANCY_DAYS)},
        )
    ]


# ----- frontmatter parsing (used by sweeper main) -----

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


def _parse_pr_number(raw: Any) -> int | None:
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        try:
            return int(raw)
        except ValueError:
            return None
    return None


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
    pr = _parse_pr_number(fm.get("pr"))
    linked_prs: list[int] = []
    for key, value in fm.items():
        if key != "pr" and str(key).startswith("pr_"):
            parsed = _parse_pr_number(value)
            if parsed is not None:
                linked_prs.append(parsed)
    if pr is not None:
        linked_prs.insert(0, pr)
    linked_prs = list(dict.fromkeys(linked_prs))
    tags_raw = fm.get("tags")
    if isinstance(tags_raw, list):
        tags = [str(tag) for tag in tags_raw if tag is not None]
    elif isinstance(tags_raw, str):
        tags = [tags_raw]
    else:
        tags = []
    wsjf_raw = fm.get("wsjf")
    try:
        wsjf = float(wsjf_raw) if wsjf_raw is not None else None
    except (TypeError, ValueError):
        wsjf = None
    return TaskNote(
        path=str(path),
        task_id=str(task_id),
        title=str(fm["title"]) if fm.get("title") is not None else None,
        status=str(status),
        automation_status=(
            str(fm["automation_status"]) if fm.get("automation_status") is not None else None
        ),
        priority=str(fm["priority"]) if fm.get("priority") is not None else None,
        wsjf=wsjf,
        assigned_to=fm.get("assigned_to"),
        claimed_at=_parse_dt(fm.get("claimed_at")),
        branch=fm.get("branch"),
        pr=pr,
        linked_prs=tuple(linked_prs),
        parent_request=(
            str(fm["parent_request"]) if fm.get("parent_request") is not None else None
        ),
        parent_plan=str(fm["parent_plan"]) if fm.get("parent_plan") is not None else None,
        parent_spec=str(fm["parent_spec"]) if fm.get("parent_spec") is not None else None,
        tags=tags,
        created_at=_parse_dt(fm.get("created_at")),
        updated_at=_parse_dt(fm.get("updated_at")),
    )


def check_spec_staleness(
    notes: Iterable[TaskNote], requests_root: Path | None = None, *, now: datetime | None = None
) -> list[HygieneEvent]:
    """Scans active requests older than 7 days with no downstream cc-tasks.

    Severity: warning.
    """
    now = now or _now()
    events: list[HygieneEvent] = []
    if requests_root is None:
        requests_root = Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-requests"
    active_req_dir = requests_root / "active"
    if not active_req_dir.is_dir():
        return events

    downstream_specs = set()
    for note in notes:
        if note.parent_spec:
            downstream_specs.add(note.parent_spec)

    cutoff = now - timedelta(days=SPEC_STALENESS_DAYS)
    for path in active_req_dir.glob("*.md"):
        req_id = path.stem
        if req_id in downstream_specs:
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue

        m = _FRONTMATTER_RE.match(text)
        created = None
        if m:
            try:
                fm = yaml.safe_load(m.group(1)) or {}
                if isinstance(fm, dict):
                    created = _parse_dt(fm.get("created_at"))
            except yaml.YAMLError:
                pass

        if not created:
            try:
                created = _ensure_aware(datetime.fromtimestamp(path.stat().st_ctime, UTC))
            except OSError:
                continue

        if created and created < cutoff:
            age_days = int((now - created).total_seconds() // 86400)
            events.append(
                HygieneEvent(
                    timestamp=now,
                    check_id="spec_staleness",
                    severity="warning",
                    task_id=None,
                    session=None,
                    message=f"active request '{req_id}' is {age_days}d old with no downstream cc-tasks",
                    metadata={
                        "request_id": req_id,
                        "age_days": str(age_days),
                        "threshold_days": str(SPEC_STALENESS_DAYS),
                    },
                )
            )
    return events


# ----- vault-link-integrity (Phase-0 housekeeping #3) -----

_LINK_NULLISH = frozenset({"", "null", "none", "~"})
"""Link values that carry no real pointer and are skipped."""

# Note dirs (relative to vault_root / repo_root) where a bare-id or
# basename-only link may resolve. Real notes name parent_request as a bare id
# OR an id+`.md` OR any of these dirs' paths; parent_spec/parent_plan point at
# specs/plans/requests across both the Obsidian vault and the repo. Resolution
# is basename-against-known-dirs so the same id resolves regardless of which
# spelling a note used — keeping the false-positive rate near zero (measured
# 161 -> 3 dangling on the live vault, where the 3 are genuinely broken).
_VAULT_NOTE_DIRS = (
    "20-projects/hapax-requests/active",
    "20-projects/hapax-requests/closed",
    "20-projects/hapax-cc-tasks/active",
    "20-projects/hapax-cc-tasks/closed",
    "20-projects/hapax-research/specs",
    "20-projects/hapax-research/plans",
    "30-areas/hapax",
)
_REPO_NOTE_DIRS = (
    "docs/superpowers/specs",
    "docs/superpowers/plans",
    "docs/research",
)


def _default_vault_root() -> Path:
    return Path.home() / "Documents" / "Personal"


def _default_repo_root() -> Path:
    return Path.home() / "projects" / "hapax-council"


def _link_is_nullish(value: str | None) -> bool:
    """True when a parent_* value is absent or a YAML null sentinel."""
    if value is None:
        return True
    return value.strip().strip("\"'").lower() in _LINK_NULLISH


def _link_resolves(target: str, vault_root: Path, repo_root: Path) -> bool:
    """True if a ``parent_*`` link target exists, in any of its real-world forms.

    Pure existence probe (never opens the file). A target resolves if ANY of:

    * it is an absolute / ``~``-expanded path that exists;
    * it is a path resolved relative to the vault root or the repo root;
    * its basename (with an implied ``.md``) exists in any known note dir under
      the vault or the repo — this absorbs bare ids, ``id.md``, vault-relative
      and repo-relative spellings of the same underlying note.

    No prefix/fuzzy matching: a truncated id that is only a *prefix* of a real
    filename is intentionally treated as dangling so it gets repaired.
    """
    raw = target.strip().strip("\"'")
    expanded = Path(raw).expanduser()

    if expanded.is_absolute():
        if expanded.exists():
            return True
    else:
        for root in (vault_root, repo_root, Path.home()):
            if (root / raw).exists():
                return True

    stem = Path(raw).name
    filename = stem if stem.endswith(".md") else f"{stem}.md"
    for root, dirs in ((vault_root, _VAULT_NOTE_DIRS), (repo_root, _REPO_NOTE_DIRS)):
        for note_dir in dirs:
            if (root / note_dir / filename).exists():
                return True
    return False


def check_vault_link_integrity(
    notes: Iterable[TaskNote],
    vault_root: Path | None = None,
    *,
    repo_root: Path | None = None,
    now: datetime | None = None,
) -> list[HygieneEvent]:
    """Flag cc-task notes whose ``parent_*`` pointers dangle.

    Resolves ``parent_request`` / ``parent_spec`` / ``parent_plan`` for each
    note via :func:`_link_resolves`, which accepts every form these fields take
    in the live vault (bare id, ``id.md``, vault-/repo-relative path,
    ``~``-path, absolute path). ``null`` / ``None`` / empty values carry no link
    and are skipped. One ``warning`` event is emitted per dangling field.

    Read-only — only probes existence, never opens targets. Recurrence guard for
    the five sbcl-clog specs that shipped with dangling ``parent_request`` refs.
    """
    now = now or _now()
    if vault_root is None:
        vault_root = _default_vault_root()
    if repo_root is None:
        repo_root = _default_repo_root()
    events: list[HygieneEvent] = []
    for note in notes:
        link_fields = (
            ("parent_request", note.parent_request),
            ("parent_spec", note.parent_spec),
            ("parent_plan", note.parent_plan),
        )
        for field, value in link_fields:
            if _link_is_nullish(value):
                continue
            target = value.strip().strip("\"'")  # type: ignore[union-attr]  # narrowed above
            if _link_resolves(target, vault_root, repo_root):
                continue
            events.append(
                HygieneEvent(
                    timestamp=now,
                    check_id="vault_link_integrity",
                    severity="warning",
                    task_id=note.task_id,
                    session=_session_role(note.assigned_to),
                    message=(
                        f"task '{note.task_id}' has dangling {field} -> "
                        f"{target!r} (target not found on disk)"
                    ),
                    metadata={"field": field, "target": target},
                )
            )
    return events
