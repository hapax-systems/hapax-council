"""agents/coordination_tui/data.py — Data loading for the coordination TUI."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml

from shared.frontmatter import parse_frontmatter

RELAY_DIR = Path.home() / ".cache/hapax/relay"
TASK_ROOT = Path.home() / "Documents/Personal/20-projects/hapax-cc-tasks/active"
PRESSURE_PATH = Path("/dev/shm/hapax-quota/pressure.json")
TRIAGE_STATE_PATH = Path("/dev/shm/hapax-triage/officer-state.json")
IDLE_STATE_DIR = Path("/tmp/hapax-lane-idle-state")
CLAUDE_SEND = Path.home() / "projects/hapax-council/scripts/hapax-claude-send"
CODEX_SEND = Path.home() / "projects/hapax-council/scripts/hapax-codex-send"

Platform = Literal["claude", "codex", "gemini"]

SESSION_PREFIXES: tuple[tuple[str, Platform], ...] = (
    ("hapax-claude-", "claude"),
    ("hapax-codex-", "codex"),
    ("hapax-gemini-", "gemini"),
)


@dataclass(frozen=True)
class LaneInfo:
    name: str
    session: str
    platform: Platform
    status: str
    idle_seconds: int
    current_task: str
    current_pr: str


@dataclass(frozen=True)
class TaskInfo:
    task_id: str
    title: str
    wsjf: float
    status: str
    effort_class: str
    assigned_to: str
    platform_suitability: list[str]
    quality_floor: str


@dataclass(frozen=True)
class PRInfo:
    number: int
    title: str
    branch: str
    ci_status: str
    author: str


@dataclass(frozen=True)
class QuotaState:
    pressure: float
    throttle_level: str
    window_24h_cost: float
    budget: float
    governance_healthy: bool


@dataclass
class DashboardState:
    lanes: list[LaneInfo] = field(default_factory=list)
    tasks: list[TaskInfo] = field(default_factory=list)
    prs: list[PRInfo] = field(default_factory=list)
    quota: QuotaState | None = None
    task_counts: dict[str, int] = field(default_factory=dict)
    refreshed_at: datetime | None = None


async def _run(cmd: list[str], timeout: float = 10.0) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return stdout.decode(errors="replace").strip()
    except (TimeoutError, FileNotFoundError, OSError):
        return ""


def _lane_from_tmux_session(session: str) -> tuple[str, Platform] | None:
    for prefix, platform in SESSION_PREFIXES:
        if session.startswith(prefix):
            return session.removeprefix(prefix), platform
    return None


def _relay_candidates(lane: str, session: str) -> list[Path]:
    candidates = [
        RELAY_DIR / f"{lane}.yaml",
        RELAY_DIR / f"peer-status-{lane}.yaml",
        RELAY_DIR / f"peer-status-{session}.yaml",
    ]
    return list(dict.fromkeys(candidates))


def _load_freshest_relay(lane: str, session: str) -> dict:
    fresh_path: Path | None = None
    fresh_mtime = -1.0
    for path in _relay_candidates(lane, session):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime > fresh_mtime:
            fresh_path = path
            fresh_mtime = mtime

    if fresh_path is None:
        return {}

    try:
        relay = yaml.safe_load(fresh_path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return {}
    return relay if isinstance(relay, dict) else {}


def _stringify_task(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("task_id", "surface", "id", "name"):
            nested = value.get(key)
            if nested:
                return str(nested)
        return ""
    return str(value)


def _normalize_relay_status(value: object) -> str:
    if not isinstance(value, str) or not value:
        return ""
    status = value.strip().lower().replace(" ", "-").replace("_", "-")
    if status in {"queue-dry", "equilibrium"} or status.startswith("idle-"):
        return "idle"
    if status == "active":
        return "active"
    if status == "retiring":
        return "retiring"
    return status.split("-", 1)[0]


def _active_task_candidates(lane: str, session: str) -> list[Path]:
    candidates = [
        Path.home() / f".cache/hapax/cc-active-task-{lane}",
        Path.home() / f".cache/hapax/cc-active-task-{session}",
    ]
    return list(dict.fromkeys(candidates))


def _active_claim(lane: str, session: str) -> str:
    for path in _active_task_candidates(lane, session):
        try:
            task_id = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if task_id:
            return task_id
    return ""


async def load_lanes() -> list[LaneInfo]:
    raw = await _run(["tmux", "list-sessions", "-F", "#{session_name}"])
    if not raw:
        return []

    now = datetime.now(UTC).timestamp()
    lanes: list[LaneInfo] = []

    for session in sorted(raw.splitlines()):
        parsed = _lane_from_tmux_session(session)
        if parsed is None:
            continue
        lane, platform = parsed

        status = "active"
        idle_seconds = 0
        idle_file = IDLE_STATE_DIR / f"{session}.idle_since"
        if idle_file.exists():
            try:
                idle_since = float(idle_file.read_text().strip())
                idle_seconds = int(now - idle_since)
                if idle_seconds > 600:
                    status = "idle"
            except (ValueError, OSError):
                pass

        current_task = ""
        current_pr = ""
        relay = _load_freshest_relay(lane, session)
        if relay:
            current_task = _stringify_task(
                relay.get("current_claim")
                or relay.get("current_task")
                or relay.get("task_id")
                or relay.get("currently_working_on")
            )
            current_pr = str(relay.get("current_pr") or relay.get("pr") or "")
            relay_idle_seconds = relay.get("idle_seconds")
            if isinstance(relay_idle_seconds, (int, float)):
                idle_seconds = max(0, int(relay_idle_seconds))
            relay_status = _normalize_relay_status(
                relay.get("status") or relay.get("session_status")
            )
            if relay_status:
                status = relay_status

        claim = _active_claim(lane, session)
        if claim:
            current_task = claim
            status = "active"
            idle_seconds = 0

        lanes.append(
            LaneInfo(
                name=lane,
                session=session,
                platform=platform,
                status=status[:12],
                idle_seconds=idle_seconds,
                current_task=current_task[:40],
                current_pr=current_pr[:20],
            )
        )

    return lanes


def load_tasks() -> list[TaskInfo]:
    if not TASK_ROOT.is_dir():
        return []

    tasks: list[TaskInfo] = []
    for path in TASK_ROOT.glob("*.md"):
        meta, _ = parse_frontmatter(path)
        if not meta:
            continue
        status = meta.get("status", "")
        if status not in ("offered", "claimed", "in_progress", "ready"):
            continue
        wsjf_raw = meta.get("wsjf", 0)
        try:
            wsjf = float(wsjf_raw)
        except (ValueError, TypeError):
            wsjf = 0.0

        plat = meta.get("platform_suitability", [])
        if isinstance(plat, str):
            plat = [plat]

        tasks.append(
            TaskInfo(
                task_id=path.stem,
                title=str(meta.get("title", path.stem))[:60],
                wsjf=wsjf,
                status=status,
                effort_class=str(meta.get("effort_class", "standard")),
                assigned_to=str(meta.get("assigned_to", "unassigned")),
                platform_suitability=plat if isinstance(plat, list) else ["any"],
                quality_floor=str(meta.get("quality_floor", "")),
            )
        )

    tasks.sort(key=lambda t: (-t.wsjf, t.task_id))
    return tasks


async def load_prs() -> list[PRInfo]:
    raw = await _run(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "open",
            "--limit",
            "30",
            "--json",
            "number,title,headRefName,statusCheckRollup,author",
        ],
        timeout=15.0,
    )
    if not raw:
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []

    prs: list[PRInfo] = []
    for pr in data:
        checks = pr.get("statusCheckRollup") or []
        if not checks:
            ci = "none"
        else:
            states = {c.get("conclusion") or c.get("status", "") for c in checks}
            if "FAILURE" in states or "ERROR" in states:
                ci = "fail"
            elif "PENDING" in states or "IN_PROGRESS" in states or "QUEUED" in states:
                ci = "pending"
            elif "SUCCESS" in states:
                ci = "pass"
            else:
                ci = "unknown"

        author = ""
        author_raw = pr.get("author")
        if isinstance(author_raw, dict):
            author = author_raw.get("login", "")
        elif isinstance(author_raw, str):
            author = author_raw

        prs.append(
            PRInfo(
                number=pr["number"],
                title=str(pr.get("title", ""))[:50],
                branch=str(pr.get("headRefName", ""))[:30],
                ci_status=ci,
                author=author[:15],
            )
        )

    return prs


def load_quota() -> QuotaState | None:
    if PRESSURE_PATH.exists():
        try:
            data = json.loads(PRESSURE_PATH.read_text())
            return QuotaState(
                pressure=float(data.get("pressure", 0)),
                throttle_level=data.get("throttle_level", "unknown"),
                window_24h_cost=float(data.get("window_24h_cost", 0)),
                budget=50.0,
                governance_healthy=data.get("governance_healthy", True),
            )
        except (json.JSONDecodeError, OSError, KeyError):
            pass

    try:
        from shared.quota_partition import quota_pressure

        qp = quota_pressure()
        return QuotaState(
            pressure=qp.pressure,
            throttle_level=qp.throttle_level,
            window_24h_cost=qp.window_24h_cost,
            budget=50.0,
            governance_healthy=qp.governance_healthy,
        )
    except Exception:
        return None


def load_task_counts() -> dict[str, int]:
    if not TASK_ROOT.is_dir():
        return {}
    counts: dict[str, int] = {}
    for path in TASK_ROOT.glob("*.md"):
        meta, _ = parse_frontmatter(path)
        status = meta.get("status", "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


async def load_all() -> DashboardState:
    lanes_coro = load_lanes()
    prs_coro = load_prs()
    lanes, prs = await asyncio.gather(lanes_coro, prs_coro)
    tasks = load_tasks()
    quota = load_quota()
    counts = load_task_counts()
    return DashboardState(
        lanes=lanes,
        tasks=tasks,
        prs=prs,
        quota=quota,
        task_counts=counts,
        refreshed_at=datetime.now(UTC),
    )


async def dispatch_to_lane(lane: LaneInfo, message: str) -> bool:
    if lane.platform == "gemini":
        await _run(
            ["tmux", "send-keys", "-t", lane.session, message, "Enter"],
            timeout=5.0,
        )
        return True

    send = str(CODEX_SEND) if lane.platform == "codex" else str(CLAUDE_SEND)
    await _run([send, "--session", lane.name, "--", message], timeout=10.0)
    return True
