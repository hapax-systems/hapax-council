"""Context restoration — proactive cognitive state recovery after interruption.

Implements the executive_function axiom (weight 95): the system compensates
for working memory gaps during task-switching. When the operator returns
after an interruption, this agent surfaces:

1. What they were doing (last queries, files, branches)
2. What's next (open PRs, upcoming meetings, pending nudges)
3. What accumulated while away (new alerts, drift, system events)

No LLM calls for data collection. Optional LLM synthesis for narrative.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

CC_HISTORY = Path.home() / ".claude" / "history.jsonl"
PROFILES_DIR = Path.home() / "projects" / "hapax-council" / "profiles"
BRIEFING_PATH = PROFILES_DIR / "briefing.md"
DRIFT_REPORT = PROFILES_DIR / "drift-report.json"


@dataclass
class ContextSnapshot:
    """Everything the operator needs to re-orient after an interruption."""

    # What were you doing?
    last_queries: list[dict] = field(default_factory=list)  # {query, project, timestamp}
    current_branch: str = ""
    last_commit: str = ""
    unstaged_files: list[str] = field(default_factory=list)
    active_worktrees: list[dict] = field(default_factory=list)  # {path, branch}

    # What's next?
    open_prs: list[dict] = field(default_factory=list)  # {number, title, branch}
    next_meetings: list[dict] = field(default_factory=list)  # {time, summary, attendees}
    pending_nudges: list[str] = field(default_factory=list)

    # What accumulated?
    system_status: str = ""
    drift_count: int = 0
    high_priority_actions: list[str] = field(default_factory=list)
    time_since_last_session: str = ""

    # Meta
    collected_at: str = ""


def collect_last_queries(project_path: str, n: int = 3) -> list[dict]:
    """Extract the last N Claude Code queries for this project."""
    if not CC_HISTORY.exists():
        return []

    queries = []
    try:
        lines = CC_HISTORY.read_text().splitlines()
        for line in reversed(lines):
            if len(queries) >= n:
                break
            try:
                entry = json.loads(line)
                proj = entry.get("project", "")
                if project_path in proj:
                    ts = entry.get("timestamp", 0)
                    if isinstance(ts, (int, float)) and ts > 1e12:
                        ts = ts / 1000  # ms → s
                    queries.append(
                        {
                            "query": entry.get("display", "")[:200],
                            "project": proj,
                            "timestamp": datetime.fromtimestamp(ts, tz=UTC).isoformat()
                            if ts
                            else "",
                        }
                    )
            except (json.JSONDecodeError, ValueError):
                continue
    except Exception:
        log.debug("Failed to read Claude Code history", exc_info=True)

    return queries


def collect_git_state() -> dict:
    """Get current git branch, last commit, unstaged files, worktrees."""
    result = {"branch": "", "last_commit": "", "unstaged": [], "worktrees": []}

    try:
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        result["branch"] = branch.stdout.strip()
    except Exception:
        pass

    try:
        commit = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        result["last_commit"] = commit.stdout.strip()
    except Exception:
        pass

    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        files = [line[3:].strip() for line in status.stdout.splitlines() if line.strip()]
        result["unstaged"] = files[:10]  # Cap at 10
    except Exception:
        pass

    try:
        wt = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        worktrees = []
        current_wt: dict = {}
        for line in wt.stdout.splitlines():
            if line.startswith("worktree "):
                if current_wt:
                    worktrees.append(current_wt)
                current_wt = {"path": line[9:]}
            elif line.startswith("branch "):
                current_wt["branch"] = line[7:].split("/")[-1]
        if current_wt:
            worktrees.append(current_wt)
        if len(worktrees) > 1:
            result["worktrees"] = worktrees
    except Exception:
        pass

    return result


def collect_open_prs() -> list[dict]:
    """Get open PRs from GitHub."""
    try:
        result = subprocess.run(
            ["gh", "pr", "list", "--state", "open", "--json", "number,title,headRefName"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            prs = json.loads(result.stdout)
            return [
                {"number": pr["number"], "title": pr["title"], "branch": pr["headRefName"]}
                for pr in prs[:5]
            ]
    except Exception:
        pass
    return []


def collect_next_meetings(hours: int = 12) -> list[dict]:
    """Get upcoming meetings from calendar context."""
    try:
        from shared.calendar_context import CalendarContext

        ctx = CalendarContext()
        meetings = ctx.meetings_in_range(days=1)
        result = []
        for m in meetings[:5]:
            try:
                dt = datetime.fromisoformat(m.start.replace("Z", "+00:00"))
                time_str = dt.strftime("%H:%M")
            except (ValueError, TypeError):
                time_str = m.start
            result.append(
                {
                    "time": time_str,
                    "summary": m.summary,
                    "duration_min": m.duration_minutes,
                    "attendees": m.attendees[:3] if m.attendees else [],
                }
            )
        return result
    except Exception:
        return []


def collect_system_status() -> dict:
    """Get system health, drift, and high-priority actions."""
    status = {"health": "", "drift_count": 0, "actions": []}

    # From briefing
    if BRIEFING_PATH.exists():
        try:
            content = BRIEFING_PATH.read_text()
            # Extract headline
            for line in content.splitlines():
                if line.startswith("## ") and not line.startswith("## Action"):
                    status["health"] = line[3:].strip()
                    break
            # Extract action items
            in_actions = False
            for line in content.splitlines():
                if "Action Items" in line:
                    in_actions = True
                    continue
                if in_actions and line.startswith("- [ ]"):
                    # Extract priority marker
                    if "⏫" in line:
                        action = line.split("]")[1].strip().split("⏫")[0].strip()
                        status["actions"].append(action)
        except Exception:
            pass

    # From drift report
    if DRIFT_REPORT.exists():
        try:
            drift = json.loads(DRIFT_REPORT.read_text())
            items = drift.get("drift_items", [])
            status["drift_count"] = len(items)
        except Exception:
            pass

    return status


def collect_time_since_last_session(project_path: str) -> str:
    """Estimate how long since the operator's last interaction."""
    if not CC_HISTORY.exists():
        return ""

    try:
        lines = CC_HISTORY.read_text().splitlines()
        for line in reversed(lines):
            try:
                entry = json.loads(line)
                if project_path in entry.get("project", ""):
                    ts = entry.get("timestamp", 0)
                    if isinstance(ts, (int, float)) and ts > 1e12:
                        ts = ts / 1000
                    last = datetime.fromtimestamp(ts, tz=UTC)
                    delta = datetime.now(UTC) - last
                    if delta.total_seconds() < 300:
                        return "just now"
                    elif delta.total_seconds() < 3600:
                        return f"{int(delta.total_seconds() / 60)} minutes ago"
                    elif delta.total_seconds() < 86400:
                        return f"{int(delta.total_seconds() / 3600)} hours ago"
                    else:
                        return f"{delta.days} days ago"
            except (json.JSONDecodeError, ValueError):
                continue
    except Exception:
        pass
    return ""


def collect_context(project_path: str | None = None) -> ContextSnapshot:
    """Collect all context restoration data. No LLM calls."""
    import os

    proj = project_path or os.getcwd()

    git = collect_git_state()
    sys_status = collect_system_status()

    return ContextSnapshot(
        last_queries=collect_last_queries(proj),
        current_branch=git["branch"],
        last_commit=git["last_commit"],
        unstaged_files=git["unstaged"],
        active_worktrees=git["worktrees"],
        open_prs=collect_open_prs(),
        next_meetings=collect_next_meetings(),
        pending_nudges=[],  # TODO: query cockpit API
        system_status=sys_status["health"],
        drift_count=sys_status["drift_count"],
        high_priority_actions=sys_status["actions"],
        time_since_last_session=collect_time_since_last_session(proj),
        collected_at=datetime.now(UTC).isoformat(),
    )


def format_context(ctx: ContextSnapshot) -> str:
    """Format context snapshot as concise markdown for the operator."""
    lines = []

    # What were you doing?
    if ctx.last_queries:
        q = ctx.last_queries[0]
        lines.append(f"**Last task:** {q['query']}")
        if ctx.time_since_last_session:
            lines.append(f"**Last active:** {ctx.time_since_last_session}")

    if ctx.current_branch and ctx.last_commit:
        lines.append(f"**Branch:** {ctx.current_branch} | {ctx.last_commit}")

    if ctx.unstaged_files:
        lines.append(f"**Uncommitted:** {len(ctx.unstaged_files)} files")

    if ctx.active_worktrees:
        wt_str = ", ".join(
            f"{w.get('branch', '?')}"
            for w in ctx.active_worktrees[1:]  # skip primary
        )
        if wt_str:
            lines.append(f"**Worktrees:** {wt_str}")

    # What's next?
    if ctx.open_prs:
        pr_str = "; ".join(f"#{p['number']} {p['title']}" for p in ctx.open_prs[:3])
        lines.append(f"**Open PRs:** {pr_str}")

    if ctx.next_meetings:
        m = ctx.next_meetings[0]
        att = f" ({', '.join(m['attendees'])})" if m.get("attendees") else ""
        lines.append(f"**Next meeting:** {m['time']} {m['summary']}{att}")

    # What accumulated?
    if ctx.system_status:
        lines.append(f"**System:** {ctx.system_status}")

    if ctx.drift_count > 0:
        lines.append(f"**Drift:** {ctx.drift_count} items")

    if ctx.high_priority_actions:
        lines.append("**Actions:**")
        for a in ctx.high_priority_actions[:3]:
            lines.append(f"  - {a}")

    return "\n".join(lines)


if __name__ == "__main__":
    ctx = collect_context()
    print(format_context(ctx))
