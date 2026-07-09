#!/usr/bin/env python3
"""cc-pr-merge-watcher — auto-close cc-tasks on linked-PR merge (PR3 / H9).

Searches merged pull requests via GitHub REST since the last cursor timestamp, finds
vault cc-task notes linked to those PRs (`pr: N` frontmatter), and
invokes `scripts/cc-close <task_id> --pr N` for each.

Cursor advances only on success; a failure on one PR does not block
others, and does not lose them on the next run.

Multi-PR lanes opt out per note: a task whose frontmatter carries
``close_on_pr_merge: false`` is never auto-closed by this watcher — neither by
the merged-PR cursor loop nor by the stale-state reconciler — because a lane
spanning several PRs shares one task note, and auto-closing on the first
merged PR has killed such lanes mid-flight. The lane owner closes explicitly
via ``cc-close``. Three-way semantics: an explicit true-ish value (or the
field's absence) keeps the auto-close default; a false-ish value (false/no/off,
optionally quoted, optional trailing comment) opts out; any OTHER value on the
field is an attempted opt-out the watcher cannot read, so it fails closed
toward NOT closing and warns.

Killswitch: ``HAPAX_CC_HYGIENE_OFF=1`` skips entirely (shared with
PR1 sweeper + H8 hook).

Usage::

    uv run python scripts/cc-pr-merge-watcher.py
    uv run python scripts/cc-pr-merge-watcher.py --dry-run
    HAPAX_CC_HYGIENE_OFF=1 uv run python scripts/cc-pr-merge-watcher.py

The systemd timer ``hapax-cc-pr-merge-watcher.timer`` runs this on the
staggered cadence declared in ``systemd/units/hapax-cc-pr-merge-watcher.timer``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from github_pr_status import (  # noqa: E402
    GRAPHQL_BACKOFF_RC,
    get_pull_rest,
    list_open_pr_statuses_rest,
    list_pulls_for_branch_rest,
    list_pulls_rest,
    rest_pull_state,
    run_graphql_rate_aware,
)

from shared.frontmatter import parse_frontmatter_with_diagnostics  # noqa: E402

LOG = logging.getLogger("cc-pr-merge-watcher")

DEFAULT_VAULT_ROOT = Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
DEFAULT_CURSOR_PATH = Path.home() / ".cache" / "hapax" / "cc-pr-merge-watcher-cursor.txt"
KILLSWITCH_ENV = "HAPAX_CC_HYGIENE_OFF"

# Reform ENGINE auto-advance (CASE-SDLC-REFORM-001): after a close, nudge the
# RTE manifest-drain dispatcher so a freshly-unblocked unit gets picked up
# without waiting for the next 270s poll. Set to "0" to disable the nudge.
REFORM_AUTO_DISPATCH_ENV = "HAPAX_REFORM_AUTO_DISPATCH"

# RFC3339 / ISO-8601 timestamp shape gh emits on `mergedAt`.
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

# G5 stuck-PR alerter. The owning repo for the merge-queue graphql probe; the
# autoqueue likewise hardcodes the council repo. Overridable for tests/forks.
DEFAULT_REPO = os.environ.get("HAPAX_CC_PR_REPO", "hapax-systems/hapax-council")
# Branch-protection required contexts (mirrors cc-pr-autoqueue DEFAULT_REQUIRED_CHECKS).
REQUIRED_QUEUE_CHECKS = ("lint", "test", "typecheck", "web-build", "vscode-build")


def default_repo_root() -> Path:
    """Resolve cc-task tooling from activated source unless explicitly overridden."""
    raw = (
        os.environ.get("HAPAX_CC_TASK_TOOL_REPO_ROOT")
        or os.environ.get("HAPAX_SOURCE_ACTIVATE_WORKTREE")
        or str(Path.home() / ".cache" / "hapax" / "source-activation" / "worktree")
    )
    return Path(raw).expanduser()


@dataclass
class MergedPR:
    """One merged PR, parsed from GitHub REST pull data."""

    number: int
    merged_at: datetime
    head_branch: str


def _run_gh_api_json(
    path: str,
    *,
    repo_root: Path,
    runner: Callable[..., subprocess.CompletedProcess],
    fields: dict[str, str] | None = None,
    timeout: int = 60,
) -> Any | None:
    cmd = [
        "gh",
        "api",
        "--method",
        "GET",
        "-H",
        "Accept: application/vnd.github+json",
        path,
    ]
    for key, value in (fields or {}).items():
        cmd.extend(["-f", f"{key}={value}"])
    proc = runner(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout or "null")
    except json.JSONDecodeError:
        return None


def _merged_pr_from_rest_item(item: dict[str, Any], *, cursor: datetime) -> MergedPR | None:
    try:
        number = int(item["number"])
        merged_at_raw = str(item.get("mergedAt") or item.get("merged_at") or "")
        head_payload = item.get("head") if isinstance(item.get("head"), dict) else {}
        head = str(item.get("headRefName") or head_payload.get("ref") or "")
    except (KeyError, TypeError, ValueError) as e:
        LOG.warning("skipping malformed PR record %r: %s", item, e)
        return None
    if not _ISO_RE.match(merged_at_raw):
        LOG.warning("skipping PR #%d with bad mergedAt %r", number, merged_at_raw)
        return None
    try:
        merged_at = datetime.fromisoformat(merged_at_raw.replace("Z", "+00:00"))
    except ValueError as e:
        LOG.warning("skipping PR #%d with unparseable mergedAt %r: %s", number, merged_at_raw, e)
        return None
    if merged_at <= cursor:
        return None
    return MergedPR(number=number, merged_at=merged_at, head_branch=head)


def _search_merged_pull_details_rest(
    cursor: datetime,
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path,
    runner: Callable[..., subprocess.CompletedProcess],
    limit: int,
) -> list[dict[str, Any]] | None:
    query = f"repo:{repo} is:pr is:merged merged:>={cursor.astimezone(UTC):%Y-%m-%d}"
    out: list[dict[str, Any]] = []
    page = 1
    while len(out) < limit:
        per_page = min(100, limit - len(out))
        payload = _run_gh_api_json(
            "search/issues",
            repo_root=repo_root,
            runner=runner,
            fields={
                "q": query,
                "sort": "updated",
                "order": "desc",
                "per_page": str(per_page),
                "page": str(page),
            },
        )
        if not isinstance(payload, dict):
            return None
        items = payload.get("items")
        if not isinstance(items, list):
            return None
        if not items:
            break
        for search_item in items:
            if not isinstance(search_item, dict):
                continue
            number = search_item.get("number")
            if number is None:
                continue
            detail = get_pull_rest(number, repo=repo, repo_root=repo_root, runner=runner)
            if isinstance(detail, dict):
                out.append(detail)
                if len(out) >= limit:
                    break
        if len(items) < per_page:
            break
        page += 1
    return out


@dataclass
class LinkedTask:
    """A vault cc-task note linked to a specific PR."""

    task_id: str
    note_path: Path
    pr_number: int


# Multi-PR lane opt-out: `close_on_pr_merge: false` in the note frontmatter
# means the lane owner closes explicitly; the watcher must never auto-close.
# Three-way semantics, fail-closed toward NOT closing: an explicit true-ish value (or
# the field's absence) keeps the auto-close default; a false-ish value opts out; any
# OTHER value on the field — malformed quoting, typos, unexpected spellings — is an
# attempted opt-out we cannot read, so the watcher declines to close and warns rather
# than proceeding to cc-close (auto-closing on a malformed opt-out is exactly the
# lane-killing failure this gate exists to stop).
_FALSEISH_STRINGS = frozenset({"false", "no", "off"})
_TRUEISH_STRINGS = frozenset({"true", "yes", "on"})


def declines_close_on_pr_merge(text: str) -> bool:
    """True when the note FRONTMATTER opts out of merge-triggered auto-close.

    Parsed with the repo-canonical frontmatter parser (shared/frontmatter.py) so
    YAML semantics — quoted spellings, no/off booleans, inline comments, duplicate
    keys, CRLF, multi-line values containing ``---`` — resolve the way every other
    consumer resolves them. Scoping to the leading block comes with the parser: a
    body or session-log line quoting ``close_on_pr_merge: false`` never opts out.

    Failure direction is uniformly SAFE toward not closing: when the note carries
    the field with an unreadable value, or the frontmatter fails to parse while the
    raw text mentions the field at all, the watcher treats it as an ATTEMPTED
    opt-out, declines to close, and warns — auto-closing on a malformed opt-out is
    exactly the lane-killing failure this gate exists to stop. A cleanly parsed
    note without the field (or with an explicit true-ish value) keeps the
    auto-close default.
    """
    stripped = text.lstrip("﻿\n\r")  # a BOM/leading blank line must not hide the block
    result = parse_frontmatter_with_diagnostics(stripped)
    frontmatter = result.frontmatter if result.ok else None
    if isinstance(frontmatter, dict):
        if "close_on_pr_merge" not in frontmatter:
            return False
        value = frontmatter["close_on_pr_merge"]
        if value is False:
            return True
        if value is True:
            return False
        if isinstance(value, str):
            token = value.strip().lower()
            if token in _FALSEISH_STRINGS:
                return True
            if token in _TRUEISH_STRINGS:
                return False
        LOG.warning(
            "close_on_pr_merge has unreadable value %r — treating as opt-out (fail "
            "closed: not auto-closing); fix the note frontmatter to a plain true/false",
            value,
        )
        return True
    # Frontmatter failed to parse. If the note mentions the field at all, this is an
    # attempted opt-out we cannot read — fail closed toward not closing.
    if "close_on_pr_merge" in stripped:
        LOG.warning(
            "note frontmatter failed to parse and mentions close_on_pr_merge — "
            "treating as opt-out (fail closed: not auto-closing); repair the note"
        )
        return True
    return False


def read_cursor(cursor_path: Path) -> datetime:
    """Read last-scan timestamp; default to 24h ago when missing."""
    if not cursor_path.is_file():
        return datetime.now(UTC) - timedelta(hours=24)
    raw = cursor_path.read_text(encoding="utf-8").strip()
    if not raw:
        return datetime.now(UTC) - timedelta(hours=24)
    try:
        # Allow trailing `Z`.
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        LOG.warning("cursor %s is malformed (%r); resetting to 24h ago", cursor_path, raw)
        return datetime.now(UTC) - timedelta(hours=24)


def write_cursor(cursor_path: Path, when: datetime) -> None:
    """Atomically write the cursor."""
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cursor_path.with_suffix(cursor_path.suffix + ".tmp")
    tmp.write_text(when.astimezone(UTC).isoformat().replace("+00:00", "Z"), encoding="utf-8")
    tmp.replace(cursor_path)


def fetch_merged_prs(
    cursor: datetime,
    *,
    repo_root: Path | None = None,
    limit: int = 300,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> list[MergedPR]:
    """List recently merged PRs through REST/core and parse the result.

    Parameters
    ----------
    cursor
        Lower bound on `mergedAt`. Items newer than this are returned.
    repo_root
        cwd for the ``gh`` invocation. Must be inside a council clone.
    limit
        ``--limit`` pass-through.
    runner
        Injection point for tests; defaults to ``subprocess.run``.
    """
    runner = runner or subprocess.run
    repo_root = repo_root or default_repo_root()
    cursor_str = cursor.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    LOG.debug("fetching merged PRs newer than %s via REST search", cursor_str)
    items = _search_merged_pull_details_rest(
        cursor,
        repo=DEFAULT_REPO,
        repo_root=repo_root,
        runner=runner,
        limit=limit,
    )
    if items is None:
        LOG.warning("REST merged-PR search failed; falling back to closed pulls scan")
        items = list_pulls_rest(
            repo=DEFAULT_REPO,
            repo_root=repo_root,
            runner=runner,
            state="closed",
            sort="updated",
            direction="desc",
            limit=limit,
        )

    out: list[MergedPR] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        merged = _merged_pr_from_rest_item(item, cursor=cursor)
        if merged is not None:
            out.append(merged)
    return out


def find_linked_tasks(pr_number: int, *, vault_root: Path = DEFAULT_VAULT_ROOT) -> list[LinkedTask]:
    """Locate vault cc-task notes (in ``active/``) whose ``pr: N`` matches.

    Notes declaring ``close_on_pr_merge: false`` are excluded (multi-PR lane
    opt-out): the lane owner closes them explicitly, never this watcher.
    """
    active = vault_root / "active"
    if not active.is_dir():
        return []
    pr_pattern = re.compile(rf"^pr:\s*{pr_number}\s*$", flags=re.MULTILINE)
    task_id_pattern = re.compile(r"^task_id:\s*(.+?)\s*$", flags=re.MULTILINE)
    tasks: list[LinkedTask] = []
    for note in sorted(active.glob("*.md")):
        try:
            text = note.read_text(encoding="utf-8")
        except OSError:
            continue
        if not pr_pattern.search(text):
            continue
        m = task_id_pattern.search(text)
        if not m:
            continue
        task_id = m.group(1).strip()
        if declines_close_on_pr_merge(text):
            LOG.info(
                "task %s declares close_on_pr_merge: false — lane owner closes explicitly",
                task_id,
            )
            continue
        tasks.append(LinkedTask(task_id=task_id, note_path=note, pr_number=pr_number))
    return tasks


def find_linked_task(pr_number: int, *, vault_root: Path = DEFAULT_VAULT_ROOT) -> LinkedTask | None:
    """Locate the first vault cc-task note linked to ``pr_number``.

    Kept for older callers/tests; the watcher itself closes every linked active task.
    """
    tasks = find_linked_tasks(pr_number, vault_root=vault_root)
    return tasks[0] if tasks else None


_LEGACY_API_ENTRYPOINTS = (find_linked_task,)


def close_linked_task(
    task: LinkedTask,
    *,
    repo_root: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
    role: str = "watcher",
) -> bool:
    """Invoke ``scripts/cc-close`` on the matched task. Returns True on success."""
    runner = runner or subprocess.run
    repo_root = repo_root or default_repo_root()
    cc_close = repo_root / "scripts" / "cc-close"
    if not cc_close.is_file():
        LOG.error("cc-close script missing at %s", cc_close)
        return False
    env = os.environ.copy()
    # cc-close uses CLAUDE_ROLE only for the log line (not gating); the
    # watcher is not a session, so a synthetic value is fine.
    env.setdefault("CLAUDE_ROLE", role)
    # The watcher only closes tasks whose PR is MERGED; cc-close still runs the
    # PR-merge evidence gate to verify that. The pre-merge AC-checkbox and
    # acceptance-receipt gates belong to the pre-merge review/admission pipeline
    # and are redundant post-merge, so a legitimately-merged PR's task must drain
    # regardless of pre-merge bookkeeping (otherwise the watcher loops forever).
    env["HAPAX_CC_TASK_CLOSURE_GATE_OFF"] = "1"
    env["HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF"] = "1"
    cmd = [str(cc_close), task.task_id, "--pr", str(task.pr_number), "--retroactive"]
    LOG.info("closing task %s for PR #%d", task.task_id, task.pr_number)
    try:
        proc = runner(
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            env=env,
        )
    except (FileNotFoundError, OSError) as e:
        LOG.error("cc-close failed to launch: %s", e)
        return False
    if proc.returncode != 0:
        LOG.error(
            "cc-close failed for task %s PR #%d (rc=%d): %s",
            task.task_id,
            task.pr_number,
            proc.returncode,
            (proc.stderr or proc.stdout).strip(),
        )
        return False
    LOG.info(
        "cc-close OK for task %s PR #%d: %s", task.task_id, task.pr_number, proc.stdout.strip()
    )
    return True


def trigger_reform_dispatch(
    *,
    repo_root: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> bool:
    """Nudge the RTE manifest-drain dispatcher (event complement to the 270s poll).

    Fail-open: any error (disabled env, missing script, launch failure) returns
    False without raising — a close must never be undone by a dispatch hiccup,
    and the next RTE poll covers a missed nudge.
    """
    if os.environ.get(REFORM_AUTO_DISPATCH_ENV) == "0":
        return False
    runner = runner or subprocess.run
    repo_root = repo_root or default_repo_root()
    script = Path(repo_root) / "scripts" / "hapax-rte-state"
    try:
        proc = runner(
            [str(script), "--dispatch"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return getattr(proc, "returncode", 1) == 0


def run_watcher(
    *,
    cursor_path: Path = DEFAULT_CURSOR_PATH,
    vault_root: Path = DEFAULT_VAULT_ROOT,
    repo_root: Path | None = None,
    dry_run: bool = False,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> dict[str, int]:
    """Run one watcher cycle.

    Returns a dict of counters: ``{merged: int, linked: int, closed: int, failed: int}``.
    """
    if os.environ.get(KILLSWITCH_ENV) == "1":
        LOG.info("killswitch %s=1; skipping watcher cycle", KILLSWITCH_ENV)
        return {"merged": 0, "linked": 0, "closed": 0, "failed": 0, "skipped": 1}

    repo_root = repo_root or default_repo_root()
    cursor = read_cursor(cursor_path)
    LOG.info("scanning merged PRs since %s", cursor.isoformat())

    merged = fetch_merged_prs(cursor, repo_root=repo_root, runner=runner)
    LOG.info("found %d merged PRs since cursor", len(merged))

    linked = 0
    closed = 0
    failed = 0
    newest_seen = cursor  # start where we were; bump only across a failure-free prefix
    first_failure_at: datetime | None = None
    for pr in sorted(merged, key=lambda p: p.merged_at):
        tasks = find_linked_tasks(pr.number, vault_root=vault_root)
        if not tasks:
            LOG.info("PR #%d (%s) has no linked cc-task; skipping", pr.number, pr.head_branch)
            # Still advance cursor for the success prefix — no work to lose.
            if first_failure_at is None and pr.merged_at > newest_seen:
                newest_seen = pr.merged_at
            continue
        linked += len(tasks)
        if dry_run:
            for task in tasks:
                LOG.info(
                    "[dry-run] would cc-close task %s for PR #%d (merged %s)",
                    task.task_id,
                    pr.number,
                    pr.merged_at.isoformat(),
                )
            closed += len(tasks)
            if first_failure_at is None and pr.merged_at > newest_seen:
                newest_seen = pr.merged_at
            continue
        pr_failed = False
        for task in tasks:
            ok = close_linked_task(task, repo_root=repo_root, runner=runner)
            if ok:
                closed += 1
            else:
                pr_failed = True
        if pr_failed:
            failed += 1
            if first_failure_at is None:
                first_failure_at = pr.merged_at
            # Do NOT advance cursor past a failed close — retry next cycle.
        elif first_failure_at is None and pr.merged_at > newest_seen:
            newest_seen = pr.merged_at

    if newest_seen > cursor and not dry_run:
        write_cursor(cursor_path, newest_seen)
        LOG.info("advanced cursor to %s", newest_seen.isoformat())
    elif dry_run:
        LOG.info("[dry-run] would advance cursor to %s", newest_seen.isoformat())

    return {
        "merged": len(merged),
        "linked": linked,
        "closed": closed,
        "failed": failed,
        "skipped": 0,
    }


_STATUS_OPEN_PATTERN = re.compile(r"^status:\s*(pr_open|merge_queue)\s*$", flags=re.MULTILINE)
_PR_NUM_PATTERN = re.compile(r"^pr:\s*(\d+)\s*$", flags=re.MULTILINE)
_PR_NULL_NULLISH = frozenset({"", "null", "none", "~"})


def _task_id_from_note(note: Path, text: str) -> str:
    m = re.search(r"^task_id:\s*(.+?)\s*$", text, flags=re.MULTILINE)
    return m.group(1).strip() if m else note.stem


def _query_pr_state(
    pr_num: str,
    *,
    repo_root: Path,
    runner: Callable[..., subprocess.CompletedProcess],
) -> str | None:
    """Return the PR's current state (MERGED|CLOSED|OPEN) or None on lookup failure."""
    try:
        payload = get_pull_rest(pr_num, repo=DEFAULT_REPO, repo_root=repo_root, runner=runner)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return rest_pull_state(payload)


def _list_prs_for_branch(
    branch: str,
    *,
    repo_root: Path,
    runner: Callable[..., subprocess.CompletedProcess],
) -> list[dict[str, Any]]:
    """Re-derive PRs for a branch via REST ``pulls?head=`` (newest first)."""
    try:
        rows = list_pulls_for_branch_rest(
            branch,
            repo=DEFAULT_REPO,
            repo_root=repo_root,
            runner=runner,
            state="all",
            limit=1,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append({"number": row.get("number"), "state": rest_pull_state(row)})
    return out


def _block_stale_note(note: Path, text: str, *, reason: str, dry_run: bool) -> bool:
    """Transition a pr_open/merge_queue note to blocked with a reason. True if blocked."""
    if dry_run:
        LOG.info("[dry-run] would block task %s (%s)", note.stem, reason)
        return True
    new = _STATUS_OPEN_PATTERN.sub("status: blocked", text, count=1)
    if re.search(r"^blocked_reason:", new, flags=re.MULTILINE):
        new = re.sub(
            r"^blocked_reason:.*$",
            f"blocked_reason: {reason}",
            new,
            count=1,
            flags=re.MULTILINE,
        )
    else:
        new = re.sub(
            r"^(status: blocked)",
            f"\\1\nblocked_reason: {reason}",
            new,
            count=1,
            flags=re.MULTILINE,
        )
    note.write_text(new, encoding="utf-8")
    LOG.info("stale PR drain: %s -> blocked (%s)", note.stem, reason)
    return True


def _close_merged_note(
    note: Path,
    text: str,
    pr_num: str,
    *,
    repo_root: Path,
    dry_run: bool,
    runner: Callable[..., subprocess.CompletedProcess],
) -> bool:
    """cc-close a task whose PR is merged (the cursor loop missed it). True on close."""
    task_id = _task_id_from_note(note, text)
    if declines_close_on_pr_merge(text):
        LOG.info(
            "task %s declares close_on_pr_merge: false — lane owner closes explicitly",
            task_id,
        )
        return False
    if dry_run:
        LOG.info("[dry-run] would cc-close task %s (PR #%s merged)", task_id, pr_num)
        return True
    ok = close_linked_task(
        LinkedTask(task_id=task_id, note_path=note, pr_number=int(pr_num)),
        repo_root=repo_root,
        runner=runner,
    )
    if ok:
        LOG.info("stale PR drain: %s -> closed (PR #%s merged)", note.stem, pr_num)
    return ok


def _apply_pr_state(
    note: Path,
    text: str,
    pr_num: str,
    pr_state: str,
    *,
    repo_root: Path,
    dry_run: bool,
    runner: Callable[..., subprocess.CompletedProcess],
    counts: dict[str, int],
) -> None:
    """Reconcile one note against its PR's current state."""
    if pr_state == "MERGED":
        if _close_merged_note(
            note, text, pr_num, repo_root=repo_root, dry_run=dry_run, runner=runner
        ):
            counts["closed"] += 1
    elif pr_state == "CLOSED":
        if _block_stale_note(
            note, text, reason=f"PR #{pr_num} closed without merge", dry_run=dry_run
        ):
            counts["stale"] += 1
    # OPEN (or any other state): the PR is still in flight; leave the task alone.


def _repair_pr_null_note(
    note: Path,
    text: str,
    *,
    repo_root: Path,
    dry_run: bool,
    runner: Callable[..., subprocess.CompletedProcess],
    counts: dict[str, int],
) -> None:
    """pr:null + pr_open/merge_queue: re-derive the PR from the task branch.

    A ``pr: null`` note matches no PR lookup, so it would otherwise stay
    pr_open forever. Re-derive via REST ``pulls?head=<owner>:<branch>``; on success
    write the number back and reconcile its state, otherwise block with a
    reason so the stuck task surfaces instead of silently lingering.
    """
    branch_m = re.search(r"^branch:\s*(\S+)\s*$", text, flags=re.MULTILINE)
    branch = (branch_m.group(1).strip() if branch_m else "").strip("\"'")
    if branch.lower() in _PR_NULL_NULLISH:
        if _block_stale_note(
            note, text, reason="pr_open but pr:null and no branch to re-derive", dry_run=dry_run
        ):
            counts["stale"] += 1
        return
    rows = _list_prs_for_branch(branch, repo_root=repo_root, runner=runner)
    if not rows:
        if _block_stale_note(
            note,
            text,
            reason=f"pr_open but pr:null; no PR found for branch {branch}",
            dry_run=dry_run,
        ):
            counts["stale"] += 1
        return
    pr_number = str(rows[0].get("number"))
    pr_state = str(rows[0].get("state", "")).upper()
    counts["repaired"] += 1
    if dry_run:
        LOG.info(
            "[dry-run] would re-derive PR #%s for %s (branch %s)", pr_number, note.stem, branch
        )
        if pr_state == "MERGED":
            counts["closed"] += 1
        return
    new_text = re.sub(r"^pr:\s*null\s*$", f"pr: {pr_number}", text, count=1, flags=re.MULTILINE)
    note.write_text(new_text, encoding="utf-8")
    LOG.info("stale PR drain: %s -> re-derived PR #%s from branch %s", note.stem, pr_number, branch)
    _apply_pr_state(
        note,
        new_text,
        pr_number,
        pr_state,
        repo_root=repo_root,
        dry_run=dry_run,
        runner=runner,
        counts=counts,
    )


def reconcile_stale_pr_states(
    *,
    vault_root: Path = DEFAULT_VAULT_ROOT,
    repo_root: Path | None = None,
    dry_run: bool = False,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> dict[str, int]:
    """Reconcile active pr_open/merge_queue tasks against live PR state.

    Cursor-window independent: scans EVERY active pr_open/merge_queue note and
    reconciles it against the PR's *current* state, so a task self-heals even
    when its PR merged outside the ``run_watcher`` cursor window (the bug that
    stranded ``soundcloud`` #3740 and ``meeting-in-screwm`` #3751 for days):

    - PR MERGED -> cc-close the task (the cursor loop missed it).
    - PR CLOSED -> transition to blocked with a reason.
    - PR OPEN   -> leave it (still in flight).
    - pr: null  -> repair: re-derive the PR from the task branch via
      REST ``pulls?head=<owner>:<branch>``; write it back and act on its state, or block.
    """
    runner = runner or subprocess.run
    repo_root = repo_root or default_repo_root()
    active = vault_root / "active"
    counts = {"scanned": 0, "stale": 0, "closed": 0, "repaired": 0}
    if not active.is_dir():
        return counts

    for note in sorted(active.glob("*.md")):
        try:
            text = note.read_text(encoding="utf-8")
        except OSError:
            continue
        if not _STATUS_OPEN_PATTERN.search(text):
            continue
        pr_m = _PR_NUM_PATTERN.search(text)
        if not pr_m:
            _repair_pr_null_note(
                note,
                text,
                repo_root=repo_root,
                dry_run=dry_run,
                runner=runner,
                counts=counts,
            )
            continue
        counts["scanned"] += 1
        pr_state = _query_pr_state(pr_m.group(1), repo_root=repo_root, runner=runner)
        if pr_state is None:
            continue
        _apply_pr_state(
            note,
            text,
            pr_m.group(1),
            pr_state,
            repo_root=repo_root,
            dry_run=dry_run,
            runner=runner,
            counts=counts,
        )

    return counts


# --- G5: stuck-PR alerter ---------------------------------------------------


@dataclass(frozen=True)
class StuckPR:
    number: int
    head_branch: str
    reason: str


def _stuck_gh_json(
    args: list[str],
    *,
    repo_root: Path,
    runner: Callable[..., subprocess.CompletedProcess],
) -> Any:
    try:
        proc = runner(
            args, cwd=str(repo_root), capture_output=True, text=True, check=False, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if getattr(proc, "returncode", 1) != 0:
        return None
    try:
        return json.loads(proc.stdout or "null")
    except (json.JSONDecodeError, TypeError):
        return None


def _json_loads_or_none(raw: str) -> Any:
    try:
        return json.loads(raw or "null")
    except (json.JSONDecodeError, TypeError):
        return None


def fetch_merge_queue_numbers(
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> set[int] | None:
    """PR numbers currently in the native merge queue (graphql)."""
    owner, _, name = repo.partition("/")
    query = (
        "query($o:String!,$n:String!){repository(owner:$o,name:$n)"
        "{mergeQueue{entries(first:50){nodes{pullRequest{number}}}}}}"
    )
    proc = run_graphql_rate_aware(
        ["-f", f"query={query}", "-F", f"o={owner}", "-F", f"n={name}"],
        repo_root=repo_root,
        runner=runner,
    )
    if proc.returncode != 0:
        level = logging.WARNING if proc.returncode == GRAPHQL_BACKOFF_RC else logging.ERROR
        LOG.log(
            level,
            "merge-queue snapshot indeterminate (rc=%d): %s",
            proc.returncode,
            proc.stderr.strip(),
        )
        return None
    data = _json_loads_or_none(proc.stdout)
    if not isinstance(data, dict):
        return None
    queue = (((data.get("data") or {}).get("repository") or {}).get("mergeQueue")) or {}
    nodes = (queue.get("entries") or {}).get("nodes") or []
    numbers: set[int] = set()
    for node in nodes:
        pr = (node or {}).get("pullRequest") or {}
        if isinstance(pr.get("number"), int):
            numbers.add(pr["number"])
    return numbers


def _required_checks_green(rollup: list[dict[str, Any]], required: tuple[str, ...]) -> bool:
    observed: dict[str, str] = {}
    for item in rollup or []:
        name = item.get("name") or item.get("context")
        if name:
            observed[name] = (item.get("conclusion") or item.get("state") or "").upper()
    return all(observed.get(check) == "SUCCESS" for check in required)


def detect_stuck_prs(
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    required_checks: tuple[str, ...] = REQUIRED_QUEUE_CHECKS,
) -> list[StuckPR]:
    """Armed (auto-merge enabled) + all required checks green, yet NOT in the
    merge queue: an ejected-while-green PR that strands silently — the exact
    failure mode this task addresses (G5). A single snapshot suffices because
    GitHub enqueues an armed+green PR within seconds, so absence from the queue
    is a real ejection rather than a transient."""
    prs = list_open_pr_statuses_rest(repo=repo, repo_root=repo_root, runner=runner, limit=100)
    if not isinstance(prs, list):
        return []
    queued = fetch_merge_queue_numbers(repo=repo, repo_root=repo_root, runner=runner)
    if queued is None:
        LOG.warning("stuck-PR detection skipped: merge-queue snapshot indeterminate")
        return []
    stuck: list[StuckPR] = []
    for pr in prs:
        if not isinstance(pr, dict) or pr.get("isDraft"):
            continue
        if pr.get("autoMergeRequest") is None:
            continue  # not armed
        if not _required_checks_green(pr.get("statusCheckRollup") or [], required_checks):
            continue  # required checks not all green (still running or failed)
        number = pr.get("number")
        if not isinstance(number, int) or number in queued:
            continue  # actually enqueued → fine
        stuck.append(StuckPR(number, pr.get("headRefName") or "", "armed+green but not enqueued"))
    return stuck


def alert_stuck_prs(
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    dry_run: bool = False,
) -> int:
    """Detect ejected-while-green PRs and ntfy the operator; returns the count.
    Fail-open: a probe or ntfy error never breaks the watcher cycle."""
    try:
        stuck = detect_stuck_prs(repo=repo, repo_root=repo_root, runner=runner)
    except Exception as exc:  # noqa: BLE001 — a probe failure must not wedge the cycle
        LOG.warning("stuck-PR detection failed: %s", exc)
        return 0
    if not stuck:
        return 0
    detail = "\n".join(f"#{item.number} {item.head_branch}: {item.reason}" for item in stuck)
    message = (
        f"{len(stuck)} armed+green PR(s) not draining via the native merge queue "
        f"(ejected-while-green):\n{detail}"
    )
    LOG.warning("stuck-PR alert:\n%s", message)
    if not dry_run:
        try:
            from shared.notify import send_notification

            send_notification(
                title="Merge queue: stuck PR(s)",
                message=message,
                priority="high",
                tags=["rotating_light"],
            )
        except Exception as exc:  # noqa: BLE001 — ntfy is best-effort
            LOG.warning("stuck-PR ntfy failed: %s", exc)
    return len(stuck)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print intended cc-close calls without invoking them or advancing the cursor.",
    )
    parser.add_argument(
        "--cursor-path",
        type=Path,
        default=DEFAULT_CURSOR_PATH,
        help="Cursor file path (default: %(default)s).",
    )
    parser.add_argument(
        "--vault-root",
        type=Path,
        default=DEFAULT_VAULT_ROOT,
        help="Vault root containing active/ + closed/ (default: %(default)s).",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=default_repo_root(),
        help="hapax-council repo root for cc-close (default: activated source worktree).",
    )
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args(argv)

    level = logging.WARNING
    if args.verbose == 1:
        level = logging.INFO
    elif args.verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    counters = run_watcher(
        cursor_path=args.cursor_path,
        vault_root=args.vault_root,
        repo_root=args.repo_root,
        dry_run=args.dry_run,
    )
    LOG.info("watcher cycle done: %s", counters)

    # Event-driven complement to the RTE 270s poll: a close may have flipped a
    # reform dep to MERGED, so nudge the manifest-drain dispatcher to pick up the
    # next ready unit without waiting for the next poll. Fail-open.
    if not args.dry_run and counters.get("closed", 0) > 0:
        if trigger_reform_dispatch(repo_root=args.repo_root):
            LOG.info("nudged reform auto-advance dispatcher after %d close(s)", counters["closed"])

    stale_counters = reconcile_stale_pr_states(
        vault_root=args.vault_root,
        repo_root=args.repo_root,
        dry_run=args.dry_run,
    )
    if stale_counters["stale"]:
        LOG.info("stale PR drain: %s", stale_counters)

    # G5: alert the operator about armed+green PRs that the native queue ejected
    # without merging (the exact stranding this task fixes). Runs every watcher
    # cycle; send_notification dedups repeats. Fail-open.
    stuck_count = alert_stuck_prs(repo_root=args.repo_root, dry_run=args.dry_run)
    if stuck_count:
        LOG.warning("stuck-PR alert fired for %d PR(s)", stuck_count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
