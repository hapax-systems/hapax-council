"""Core coordinator logic — task queue, lane health, dispatch routing."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

TASKS_DIR = Path.home() / "Documents/Personal/20-projects/hapax-cc-tasks/active"
RELAY_DIR = Path.home() / ".cache/hapax/relay"
PID_DIR = Path(f"/run/user/{os.getuid()}/hapax-claude")
SHM_DIR = Path("/dev/shm/hapax-coordinator")
SHM_FILE = SHM_DIR / "state.json"

LANE_ROLES = ("beta", "gamma", "delta", "epsilon", "zeta")
DISPATCH_COOLDOWN_S = 120.0


@dataclass(frozen=True)
class Task:
    """A cc-task parsed from YAML frontmatter."""

    task_id: str
    title: str
    status: str
    assigned_to: str
    wsjf: float
    effort_class: str
    platform_suitability: tuple[str, ...]
    quality_floor: str
    path: Path


@dataclass
class LaneState:
    """Health snapshot of a single work lane."""

    role: str
    alive: bool = False
    pid: int | None = None
    relay_age_s: float = float("inf")
    claimed_task: str | None = None
    idle: bool = True


@dataclass
class CoordinatorState:
    """Full coordinator snapshot written to SHM each tick."""

    timestamp: float = 0.0
    offered_tasks: int = 0
    claimed_tasks: int = 0
    lanes_alive: int = 0
    lanes_idle: int = 0
    lanes_total: int = len(LANE_ROLES)
    dispatches_this_tick: int = 0
    lanes: dict[str, dict] = field(default_factory=dict)


class Coordinator:
    """Main coordinator — scans tasks, checks lanes, dispatches work."""

    def __init__(self) -> None:
        self._last_dispatch: dict[str, float] = {}

    def tick(self) -> None:
        tasks = self._scan_tasks()
        lanes = self._check_lanes()
        offered = [t for t in tasks if t.status == "offered"]
        state = CoordinatorState(
            timestamp=time.time(),
            offered_tasks=len(offered),
            claimed_tasks=sum(1 for t in tasks if t.status in ("claimed", "in_progress")),
            lanes_alive=sum(1 for l in lanes.values() if l.alive),
            lanes_idle=sum(1 for l in lanes.values() if l.idle and l.alive),
            lanes_total=len(LANE_ROLES),
        )

        dispatches = 0
        idle_lanes = [l for l in lanes.values() if l.alive and l.idle and l.claimed_task is None]
        offered_sorted = sorted(offered, key=lambda t: t.wsjf, reverse=True)

        for task in offered_sorted:
            if not idle_lanes:
                break
            lane = self._pick_lane(task, idle_lanes)
            if lane is None:
                continue
            now = time.monotonic()
            last = self._last_dispatch.get(lane.role, 0.0)
            if now - last < DISPATCH_COOLDOWN_S:
                continue
            if self._dispatch(task, lane):
                self._last_dispatch[lane.role] = now
                idle_lanes.remove(lane)
                dispatches += 1

        state.dispatches_this_tick = dispatches
        state.lanes = {role: _lane_to_dict(l) for role, l in lanes.items()}
        self._write_state(state)

        log.info(
            "tick: offered=%d idle_lanes=%d dispatched=%d alive=%d/%d",
            len(offered),
            state.lanes_idle,
            dispatches,
            state.lanes_alive,
            state.lanes_total,
        )

    def _scan_tasks(self) -> list[Task]:
        if not TASKS_DIR.is_dir():
            return []
        tasks: list[Task] = []
        for path in sorted(TASKS_DIR.glob("*.md")):
            task = _parse_task(path)
            if task is not None:
                tasks.append(task)
        return tasks

    def _check_lanes(self) -> dict[str, LaneState]:
        lanes: dict[str, LaneState] = {}
        for role in LANE_ROLES:
            lanes[role] = _check_lane(role)
        return lanes

    def _pick_lane(self, task: Task, idle_lanes: list[LaneState]) -> LaneState | None:
        platforms = task.platform_suitability
        for lane in idle_lanes:
            if "any" in platforms or "claude" in platforms:
                return lane
        return None

    def _dispatch(self, task: Task, lane: LaneState) -> bool:
        msg = (
            f"You are {lane.role}. Read ~/projects/hapax-council/CLAUDE.md. "
            f"Claim and work cc-task {task.task_id}. "
            f"Task file: {task.path}. "
            f"{task.title}. PR when done."
        )
        headless = Path.home() / ".local/bin/hapax-claude-send"
        if not headless.exists():
            log.warning("hapax-claude-send not found, cannot dispatch to %s", lane.role)
            return False
        try:
            subprocess.run(
                [str(headless), "--session", lane.role, "--", msg],
                timeout=10,
                capture_output=True,
            )
            log.info("Dispatched task %s to lane %s", task.task_id, lane.role)
            return True
        except (subprocess.TimeoutExpired, OSError) as exc:
            log.warning("Dispatch to %s failed: %s", lane.role, exc)
            return False

    def _write_state(self, state: CoordinatorState) -> None:
        SHM_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": state.timestamp,
            "offered_tasks": state.offered_tasks,
            "claimed_tasks": state.claimed_tasks,
            "lanes_alive": state.lanes_alive,
            "lanes_idle": state.lanes_idle,
            "lanes_total": state.lanes_total,
            "dispatches_this_tick": state.dispatches_this_tick,
            "lanes": state.lanes,
        }
        tmp = SHM_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.rename(SHM_FILE)


def _parse_task(path: Path) -> Task | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        meta = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None
    if not isinstance(meta, dict):
        return None
    status = meta.get("status", "")
    if status not in ("offered", "claimed", "in_progress"):
        return None
    platforms = meta.get("platform_suitability", ["any"])
    if isinstance(platforms, str):
        platforms = [platforms]
    return Task(
        task_id=path.stem,
        title=meta.get("title", path.stem),
        status=status,
        assigned_to=meta.get("assigned_to", "unassigned"),
        wsjf=float(meta.get("wsjf", 0.0)),
        effort_class=meta.get("effort_class", "standard"),
        platform_suitability=tuple(platforms),
        quality_floor=meta.get("quality_floor", "deterministic_ok"),
        path=path,
    )


def _check_lane(role: str) -> LaneState:
    state = LaneState(role=role)

    pidfile = PID_DIR / f"{role}.pid"
    if pidfile.exists():
        try:
            pid = int(pidfile.read_text().strip())
            os.kill(pid, 0)
            state.alive = True
            state.pid = pid
        except (ValueError, OSError):
            pass

    relay_file = RELAY_DIR / f"{role}.yaml"
    if relay_file.exists():
        try:
            state.relay_age_s = time.time() - relay_file.stat().st_mtime
        except OSError:
            pass

    active_task_file = Path.home() / f".cache/hapax/cc-active-task-{role}"
    if active_task_file.exists():
        try:
            task_id = active_task_file.read_text().strip()
            if task_id:
                state.claimed_task = task_id
                state.idle = False
        except OSError:
            pass

    return state


def _lane_to_dict(lane: LaneState) -> dict:
    return {
        "role": lane.role,
        "alive": lane.alive,
        "pid": lane.pid,
        "relay_age_s": round(lane.relay_age_s, 1) if lane.relay_age_s != float("inf") else None,
        "claimed_task": lane.claimed_task,
        "idle": lane.idle,
    }
