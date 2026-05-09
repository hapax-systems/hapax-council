#!/usr/bin/env python3
"""cc-pr-merge-watcher — auto-close cc-tasks on linked-PR merge (PR3 / H9).

Scans `gh pr list --state merged` since the last cursor timestamp, finds
vault cc-task notes linked to those PRs (`pr: N` frontmatter), and
invokes `scripts/cc-close <task_id> --pr N` for each.

Cursor advances only on success; a failure on one PR does not block
others, and does not lose them on the next run.

Killswitch: ``HAPAX_CC_HYGIENE_OFF=1`` skips entirely (shared with
PR1 sweeper + H8 hook).

Usage::

    uv run python scripts/cc-pr-merge-watcher.py
    uv run python scripts/cc-pr-merge-watcher.py --dry-run
    HAPAX_CC_HYGIENE_OFF=1 uv run python scripts/cc-pr-merge-watcher.py

The systemd timer ``hapax-cc-pr-merge-watcher.timer`` runs this every
5 minutes.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

LOG = logging.getLogger("cc-pr-merge-watcher")

DEFAULT_VAULT_ROOT = Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
DEFAULT_CURSOR_PATH = Path.home() / ".cache" / "hapax" / "cc-pr-merge-watcher-cursor.txt"
KILLSWITCH_ENV = "HAPAX_CC_HYGIENE_OFF"

# RFC3339 / ISO-8601 timestamp shape gh emits on `mergedAt`.
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


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
    """One merged PR, parsed from `gh pr list --state merged --json ...`."""

    number: int
    merged_at: datetime
    head_branch: str


@dataclass
class LinkedTask:
    """A vault cc-task note linked to a specific PR."""

    task_id: str
    note_path: Path
    pr_number: int


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
    limit: int = 50,
    runner: callable[..., subprocess.CompletedProcess] | None = None,
) -> list[MergedPR]:
    """Run ``gh pr list --state merged`` and parse the result.

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
    cmd = [
        "gh",
        "pr",
        "list",
        "--state",
        "merged",
        "--json",
        "number,mergedAt,headRefName",
        "--limit",
        str(limit),
        "--search",
        f"merged:>={cursor_str}",
    ]
    LOG.debug("running: %s", " ".join(cmd))
    proc = runner(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if proc.returncode != 0:
        LOG.error("gh pr list failed (rc=%d): %s", proc.returncode, proc.stderr.strip())
        return []
    try:
        items = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as e:
        LOG.error("gh pr list emitted non-JSON: %s", e)
        return []

    out: list[MergedPR] = []
    for item in items:
        try:
            number = int(item["number"])
            merged_at_raw = str(item["mergedAt"])
            head = str(item.get("headRefName") or "")
        except (KeyError, TypeError, ValueError) as e:
            LOG.warning("skipping malformed PR record %r: %s", item, e)
            continue
        if not _ISO_RE.match(merged_at_raw):
            LOG.warning("skipping PR #%d with bad mergedAt %r", number, merged_at_raw)
            continue
        try:
            merged_at = datetime.fromisoformat(merged_at_raw.replace("Z", "+00:00"))
        except ValueError as e:
            LOG.warning(
                "skipping PR #%d with unparseable mergedAt %r: %s", number, merged_at_raw, e
            )
            continue
        out.append(MergedPR(number=number, merged_at=merged_at, head_branch=head))
    return out


def find_linked_task(pr_number: int, *, vault_root: Path = DEFAULT_VAULT_ROOT) -> LinkedTask | None:
    """Locate the vault cc-task note (in ``active/``) whose ``pr: N`` matches."""
    active = vault_root / "active"
    if not active.is_dir():
        return None
    pr_pattern = re.compile(rf"^pr:\s*{pr_number}\s*$", flags=re.MULTILINE)
    task_id_pattern = re.compile(r"^task_id:\s*(.+?)\s*$", flags=re.MULTILINE)
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
        return LinkedTask(task_id=m.group(1).strip(), note_path=note, pr_number=pr_number)
    return None


def close_linked_task(
    task: LinkedTask,
    *,
    repo_root: Path | None = None,
    runner: callable[..., subprocess.CompletedProcess] | None = None,
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
    cmd = [str(cc_close), task.task_id, "--pr", str(task.pr_number)]
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


def run_watcher(
    *,
    cursor_path: Path = DEFAULT_CURSOR_PATH,
    vault_root: Path = DEFAULT_VAULT_ROOT,
    repo_root: Path | None = None,
    dry_run: bool = False,
    runner: callable[..., subprocess.CompletedProcess] | None = None,
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
    newest_seen = cursor  # start where we were; bump on each successful close
    for pr in sorted(merged, key=lambda p: p.merged_at):
        task = find_linked_task(pr.number, vault_root=vault_root)
        if task is None:
            LOG.info("PR #%d (%s) has no linked cc-task; skipping", pr.number, pr.head_branch)
            # Still advance cursor — no work to lose.
            if pr.merged_at > newest_seen:
                newest_seen = pr.merged_at
            continue
        linked += 1
        if dry_run:
            LOG.info(
                "[dry-run] would cc-close task %s for PR #%d (merged %s)",
                task.task_id,
                pr.number,
                pr.merged_at.isoformat(),
            )
            closed += 1
            if pr.merged_at > newest_seen:
                newest_seen = pr.merged_at
            continue
        ok = close_linked_task(task, repo_root=repo_root, runner=runner)
        if ok:
            closed += 1
            if pr.merged_at > newest_seen:
                newest_seen = pr.merged_at
        else:
            failed += 1
            # Do NOT advance cursor past a failed close — retry next cycle.

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
    return 0


if __name__ == "__main__":
    sys.exit(main())
