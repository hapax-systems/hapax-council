"""Context restoration — proactive cognitive state recovery after interruption.

Implements the executive_function axiom (weight 95): the system compensates
for working memory gaps during task-switching. When the operator returns
after an interruption, this agent surfaces:

1. What they were doing (last queries, files, branches)
2. What's next (open PRs, upcoming meetings, pending nudges)
3. What accumulated while away (new alerts, drift, system events)
4. One actionable next step (reduces activation energy for task re-entry)

Adapts presentation based on active accommodations:
- soft_framing: observational tone, not imperative
- energy_aware: suppress non-critical items during low-energy hours
- smallest_step: always end with one concrete action
- time_anchor: show elapsed time prominently

No LLM calls. Pure data extraction from local sources.
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
FLOW_STATE_PATH = Path.home() / ".local" / "share" / "hapax-daimonion" / "flow_state.json"
WORKSPACE_STATE_PATH = Path.home() / ".local" / "share" / "hapax-daimonion" / "workspace_state.json"
VOICE_EVENTS_DIR = Path.home() / ".local" / "share" / "hapax-daimonion"
WEATHER_DIR = Path.home() / "documents" / "rag-sources" / "weather"


@dataclass
class Accommodations:
    """Active accommodations affecting restoration format."""

    soft_framing: bool = False
    energy_aware: bool = False
    smallest_step: bool = False
    time_anchor: bool = False
    is_low_energy: bool = False
    is_peak_energy: bool = False


@dataclass
class ContextSnapshot:
    """Everything the operator needs to re-orient after an interruption."""

    # What were you doing?
    last_queries: list[dict] = field(default_factory=list)
    current_branch: str = ""
    last_commit: str = ""
    unstaged_files: list[str] = field(default_factory=list)
    active_worktrees: list[dict] = field(default_factory=list)
    was_in_flow: bool = False
    flow_state: str = ""

    # What's next?
    open_prs: list[dict] = field(default_factory=list)
    next_meetings: list[dict] = field(default_factory=list)
    pending_nudges: list[dict] = field(default_factory=list)
    deep_work_window_hours: float = 0.0

    # What accumulated?
    system_status: str = ""
    drift_count: int = 0
    high_priority_actions: list[str] = field(default_factory=list)
    time_since_last_session: str = ""

    # Environment
    operator_present: bool = True
    weather: str = ""  # e.g. "28°F heavy snow"
    presence_transitions: int = 0  # how many times came/went today
    governance_heartbeat: str = ""  # "green (0.92)" or "yellow (0.65)"

    # Derived
    start_here: str = ""
    accommodations: Accommodations = field(default_factory=Accommodations)

    # Meta
    collected_at: str = ""


# ── Data collectors ──────────────────────────────────────────────────


def collect_last_queries(project_path: str, n: int = 3) -> list[dict]:
    """Extract the last N Claude Code queries for this project."""
    if not CC_HISTORY.exists():
        return []

    queries: list[dict] = []
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
                        ts = ts / 1000
                    queries.append(
                        {
                            "query": entry.get("display", "")[:200],
                            "project": proj,
                            "timestamp": (
                                datetime.fromtimestamp(ts, tz=UTC).isoformat() if ts else ""
                            ),
                        }
                    )
            except (json.JSONDecodeError, ValueError):
                continue
    except Exception:
        log.debug("Failed to read Claude Code history", exc_info=True)

    return queries


def collect_git_state() -> dict:
    """Get current git branch, last commit, unstaged files, worktrees."""
    result: dict = {"branch": "", "last_commit": "", "unstaged": [], "worktrees": []}

    for cmd, key, post in [
        (["git", "branch", "--show-current"], "branch", str.strip),
        (["git", "log", "--oneline", "-1"], "last_commit", str.strip),
    ]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            result[key] = post(r.stdout)
        except Exception:
            pass

    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, timeout=5
        )
        result["unstaged"] = [line[3:].strip() for line in r.stdout.splitlines() if line.strip()][
            :10
        ]
    except Exception:
        pass

    try:
        r = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        worktrees: list[dict] = []
        current_wt: dict = {}
        for line in r.stdout.splitlines():
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
        r = subprocess.run(
            ["gh", "pr", "list", "--state", "open", "--json", "number,title,headRefName"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if r.returncode == 0:
            return [
                {"number": pr["number"], "title": pr["title"], "branch": pr["headRefName"]}
                for pr in json.loads(r.stdout)[:5]
            ]
    except Exception:
        pass
    return []


def collect_next_meetings() -> list[dict]:
    """Get upcoming meetings from calendar context."""
    try:
        from shared.calendar_context import CalendarContext

        ctx = CalendarContext()
        result = []
        for m in ctx.meetings_in_range(days=1)[:5]:
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
    status: dict = {"health": "", "drift_count": 0, "actions": []}

    if BRIEFING_PATH.exists():
        try:
            content = BRIEFING_PATH.read_text()
            for line in content.splitlines():
                if line.startswith("## ") and not line.startswith("## Action"):
                    status["health"] = line[3:].strip()
                    break
            in_actions = False
            for line in content.splitlines():
                if "Action Items" in line:
                    in_actions = True
                    continue
                if in_actions and line.startswith("- [ ]") and "⏫" in line:
                    action = line.split("]")[1].strip().split("⏫")[0].strip()
                    status["actions"].append(action)
        except Exception:
            pass

    if DRIFT_REPORT.exists():
        try:
            drift = json.loads(DRIFT_REPORT.read_text())
            status["drift_count"] = len(drift.get("drift_items", []))
        except Exception:
            pass

    return status


def collect_time_since_last_session(project_path: str) -> str:
    """Estimate how long since the operator's last interaction."""
    if not CC_HISTORY.exists():
        return ""

    try:
        for line in reversed(CC_HISTORY.read_text().splitlines()):
            try:
                entry = json.loads(line)
                if project_path in entry.get("project", ""):
                    ts = entry.get("timestamp", 0)
                    if isinstance(ts, (int, float)) and ts > 1e12:
                        ts = ts / 1000
                    delta = datetime.now(UTC) - datetime.fromtimestamp(ts, tz=UTC)
                    secs = delta.total_seconds()
                    if secs < 300:
                        return "just now"
                    if secs < 3600:
                        return f"{int(secs / 60)} minutes ago"
                    if secs < 86400:
                        return f"{int(secs / 3600)} hours ago"
                    return f"{delta.days} days ago"
            except (json.JSONDecodeError, ValueError):
                continue
    except Exception:
        pass
    return ""


def collect_pending_nudges(max_nudges: int = 5) -> list[dict]:
    """Collect top pending nudges from the 12-source aggregator."""
    try:
        from logos.data.nudges import collect_nudges

        accom = _load_accommodations_raw()
        nudges = collect_nudges(max_nudges=max_nudges, accommodations=accom)
        return [
            {
                "title": n.title,
                "category": n.category,
                "priority_label": n.priority_label,
                "suggested_action": n.suggested_action,
            }
            for n in nudges
        ]
    except Exception:
        log.debug("Failed to collect nudges", exc_info=True)
        return []


def collect_flow_state() -> dict:
    """Check if the operator was in flow when interrupted."""
    result: dict = {"was_in_flow": False, "state": ""}

    # Try persisted flow state (written by voice daemon on transitions)
    if FLOW_STATE_PATH.exists():
        try:
            data = json.loads(FLOW_STATE_PATH.read_text())
            age = datetime.now(UTC).timestamp() - data.get("updated_at", 0)
            if age < 300:  # Fresh within 5 min
                state = data.get("current_state", "")
                result["state"] = state
                result["was_in_flow"] = state in ("flow", "active")
                return result
        except Exception:
            pass

    # Fallback: workspace state
    if WORKSPACE_STATE_PATH.exists():
        try:
            data = json.loads(WORKSPACE_STATE_PATH.read_text())
            age = datetime.now(UTC).timestamp() - data.get("timestamp", 0)
            if age < 300:
                activity = data.get("operator_activity", "")
                present = data.get("operator_present", False)
                if present and activity not in ("", "unknown", "idle"):
                    result["state"] = "likely_active"
        except Exception:
            pass

    return result


def _load_accommodations_raw():
    """Load AccommodationSet from disk for nudge priority adjustment."""
    try:
        from logos.accommodations import load_accommodations

        return load_accommodations()
    except Exception:
        return None


def collect_accommodations() -> Accommodations:
    """Load active accommodations and determine current energy state."""
    acc = Accommodations()
    try:
        from logos.accommodations import load_accommodations

        acc_set = load_accommodations()
        acc.soft_framing = getattr(acc_set, "soft_framing", False)
        acc.energy_aware = getattr(acc_set, "energy_aware", False)
        acc.time_anchor = getattr(acc_set, "time_anchor_enabled", False)
        for a in getattr(acc_set, "accommodations", []):
            if getattr(a, "id", "") == "smallest_step" and getattr(a, "active", False):
                acc.smallest_step = True

        if acc.energy_aware:
            hour = datetime.now().hour
            acc.is_low_energy = hour in getattr(acc_set, "low_hours", [])
            acc.is_peak_energy = hour in getattr(acc_set, "peak_hours", [])
    except Exception:
        log.debug("Failed to load accommodations", exc_info=True)

    return acc


# ── Start-here logic ─────────────────────────────────────────────────


def collect_voice_events_summary() -> dict:
    """Summarize today's voice daemon events (presence transitions)."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    events_file = VOICE_EVENTS_DIR / f"events-{today}.jsonl"
    result: dict = {"transitions": 0, "present": True}

    if not events_file.exists():
        return result

    try:
        transitions = 0
        last_presence = "likely_present"
        for line in events_file.read_text().splitlines():
            try:
                event = json.loads(line)
                if event.get("type") == "presence_transition":
                    transitions += 1
                    last_presence = event.get("to", last_presence)
            except json.JSONDecodeError:
                continue
        result["transitions"] = transitions
        result["present"] = last_presence == "likely_present"
    except Exception:
        pass

    return result


def collect_weather() -> str:
    """Get the latest weather observation."""
    if not WEATHER_DIR.exists():
        return ""

    try:
        files = sorted(WEATHER_DIR.glob("weather-*.md"), reverse=True)
        if not files:
            return ""

        # Parse frontmatter from most recent file
        content = files[0].read_text()
        for line in content.splitlines():
            if line.startswith("**Conditions:**"):
                # Extract from the body lines
                pass

        # Simpler: read frontmatter fields
        import yaml

        parts = content.split("---")
        if len(parts) >= 3:
            fm = yaml.safe_load(parts[1])
            if fm:
                temp = fm.get("temperature_f", "?")
                desc = fm.get("description", "")
                return f"{temp}°F {desc}"
    except Exception:
        pass

    return ""


def determine_start_here(ctx: ContextSnapshot) -> str:
    """Determine the single most actionable next step.

    Priority: uncommitted feature work > open PR > meeting prep > top nudge > briefing action.
    """
    if ctx.unstaged_files and ctx.current_branch not in ("main", "master", ""):
        n = len(ctx.unstaged_files)
        return f"Commit {n} file{'s' if n > 1 else ''} on {ctx.current_branch}"

    if ctx.open_prs:
        pr = ctx.open_prs[0]
        return f"Review/merge PR #{pr['number']}: {pr['title']}"

    if ctx.next_meetings:
        m = ctx.next_meetings[0]
        if m.get("attendees"):
            return f"Prep for {m['time']} {m['summary']}"

    if ctx.pending_nudges:
        top = ctx.pending_nudges[0]
        if top.get("priority_label") in ("critical", "high"):
            return (top.get("suggested_action") or top.get("title", ""))[:120]

    if ctx.high_priority_actions:
        return ctx.high_priority_actions[0]

    return ""


# ── Formatter ────────────────────────────────────────────────────────


def format_context(ctx: ContextSnapshot) -> str:
    """Format context snapshot as concise markdown.

    Adapts tone and density based on active accommodations:
    - soft_framing: observational ("Here's where things stand")
    - energy_aware + low hours: fewer items, critical only
    - smallest_step: always end with one concrete action
    """
    acc = ctx.accommodations
    lines: list[str] = []

    # Flow state acknowledgment
    if ctx.was_in_flow:
        if acc.soft_framing:
            lines.append("*You were in deep focus when you left.*")
        else:
            lines.append("**Flow interrupted.** Focused re-entry below.")
        lines.append("")

    # What were you doing?
    if ctx.last_queries:
        q = ctx.last_queries[0]
        label = "Last task:" if acc.soft_framing else "**Last task:**"
        lines.append(f"{label} {q['query']}")
        if ctx.time_since_last_session:
            lines.append(f"**Last active:** {ctx.time_since_last_session}")

    if ctx.current_branch and ctx.last_commit:
        lines.append(f"**Branch:** {ctx.current_branch} | {ctx.last_commit}")

    if ctx.unstaged_files:
        lines.append(f"**Uncommitted:** {len(ctx.unstaged_files)} files")

    if ctx.active_worktrees:
        wt_str = ", ".join(w.get("branch", "?") for w in ctx.active_worktrees[1:])
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

    if ctx.deep_work_window_hours > 0:
        lines.append(f"**Focus window:** ~{ctx.deep_work_window_hours:.0f}h uninterrupted")

    # Nudges (cap density based on energy)
    if ctx.pending_nudges:
        max_shown = 1 if acc.is_low_energy else 3
        shown = ctx.pending_nudges[:max_shown]
        if len(shown) == 1:
            lines.append(f"**Nudge:** {shown[0]['title']}")
        else:
            lines.append("**Nudges:**")
            for n in shown:
                lines.append(f"  - {n['title']}")

    # System status (skip non-critical during low energy)
    if ctx.system_status:
        if not acc.is_low_energy or "DEGRADED" in ctx.system_status.upper():
            lines.append(f"**System:** {ctx.system_status}")

    if ctx.drift_count > 0 and not acc.is_low_energy:
        lines.append(f"**Drift:** {ctx.drift_count} items")

    if ctx.high_priority_actions and not acc.is_low_energy:
        lines.append("**Actions:**")
        for a in ctx.high_priority_actions[:3]:
            lines.append(f"  - {a}")

    # Environment
    if ctx.weather:
        lines.append(f"**Weather:** {ctx.weather}")

    if ctx.governance_heartbeat:
        lines.append(f"**Governance:** {ctx.governance_heartbeat}")

    # Start here — always last, always present
    if ctx.start_here:
        lines.append("")
        if acc.soft_framing:
            lines.append(f"A good place to start: {ctx.start_here}")
        else:
            lines.append(f"**Start here:** {ctx.start_here}")

    return "\n".join(lines)


# ── Main collector ───────────────────────────────────────────────────


def collect_context(project_path: str | None = None) -> ContextSnapshot:
    """Collect all context restoration data. No LLM calls."""
    import os

    proj = project_path or os.getcwd()

    git = collect_git_state()
    sys_status = collect_system_status()
    flow = collect_flow_state()
    accom = collect_accommodations()
    nudges = collect_pending_nudges(max_nudges=7)
    meetings = collect_next_meetings()
    voice = collect_voice_events_summary()
    weather = collect_weather()

    # Governance heartbeat
    gov_heartbeat = ""
    try:
        from logos.data.governance import collect_governance_heartbeat

        hb = collect_governance_heartbeat()
        gov_heartbeat = f"{hb.label} ({hb.score})"
    except Exception:
        pass

    # Compute deep work window from calendar
    deep_work_h = 0.0
    if meetings:
        try:
            next_time = meetings[0].get("time", "")
            if next_time:
                now = datetime.now()
                h, m = int(next_time.split(":")[0]), int(next_time.split(":")[1])
                meeting_dt = now.replace(hour=h, minute=m, second=0)
                if meeting_dt > now:
                    deep_work_h = (meeting_dt - now).total_seconds() / 3600
        except Exception:
            pass

    ctx = ContextSnapshot(
        last_queries=collect_last_queries(proj),
        current_branch=git["branch"],
        last_commit=git["last_commit"],
        unstaged_files=git["unstaged"],
        active_worktrees=git["worktrees"],
        was_in_flow=flow["was_in_flow"],
        flow_state=flow["state"],
        open_prs=collect_open_prs(),
        next_meetings=meetings,
        pending_nudges=nudges,
        deep_work_window_hours=deep_work_h,
        system_status=sys_status["health"],
        drift_count=sys_status["drift_count"],
        high_priority_actions=sys_status["actions"],
        time_since_last_session=collect_time_since_last_session(proj),
        operator_present=voice["present"],
        weather=weather,
        presence_transitions=voice["transitions"],
        governance_heartbeat=gov_heartbeat,
        accommodations=accom,
        collected_at=datetime.now(UTC).isoformat(),
    )

    ctx.start_here = determine_start_here(ctx)
    return ctx


if __name__ == "__main__":
    ctx = collect_context()
    print(format_context(ctx))
