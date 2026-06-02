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

from shared.recovery_governor import converge_action_cap
from shared.sdlc_pressure_gate import admission_state

log = logging.getLogger(__name__)


def pressure_dispatch_budget(
    state: str, idle_count: int, base_cooldown: float
) -> tuple[int, float]:
    """Translate the SDLC pressure admission state into a per-tick dispatch budget.

    'closed' dispatches nothing this tick (offered tasks stay on disk — queued,
    not dropped); 'paced' caps to one dispatch and stretches the cooldown so the
    fleet drains slowly; 'open' runs at full throughput. Slows the controller,
    never abandons work.
    """
    if state == "closed":
        return (0, base_cooldown)
    if state == "paced":
        return (1, base_cooldown * 2.0)
    return (idle_count, base_cooldown)


TASKS_DIR = Path.home() / "Documents/Personal/20-projects/hapax-cc-tasks/active"
RELAY_DIR = Path.home() / ".cache/hapax/relay"
PID_DIR = Path(f"/run/user/{os.getuid()}/hapax-claude")
SHM_DIR = Path("/dev/shm/hapax-coordinator")
SHM_FILE = SHM_DIR / "state.json"

FALLBACK_LANE_ROLES = ("alpha", "beta", "gamma", "delta", "epsilon", "zeta")
LANE_ROLES = FALLBACK_LANE_ROLES
SESSION_PREFIXES = (
    ("hapax-claude-", "claude"),
    ("hapax-codex-", "codex"),
    ("hapax-gemini-", "gemini"),
)
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
class LaneDescriptor:
    """A live tmux lane and its dispatch platform."""

    role: str
    session: str
    platform: str


@dataclass
class LaneState:
    """Health snapshot of a single work lane."""

    role: str
    session: str = ""
    platform: str = "claude"
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
            lanes_total=len(lanes),
        )

        dispatches = 0
        idle_lanes = [l for l in lanes.values() if l.alive and l.idle and l.claimed_task is None]
        offered_sorted = sorted(offered, key=lambda t: t.wsjf, reverse=True)

        # L3: pace the dispatch loop under CPU pressure. 'closed' dispatches
        # nothing this tick (tasks stay offered — queued, not dropped); 'paced'
        # caps throughput and stretches the cooldown so the fleet drains slowly.
        admission = admission_state()
        _, cooldown_s = pressure_dispatch_budget(
            admission.state, len(idle_lanes), DISPATCH_COOLDOWN_S
        )
        # bb-control-stability: the RecoveryGovernor's per-tick converge ceiling
        # ({open:6, paced:2, closed:0}) bounds how many dispatches the controller
        # may inject per tick — it cannot become the storm it governs.
        max_dispatches = min(len(idle_lanes), converge_action_cap(admission.state))
        if admission.state != "open":
            log.info(
                "sdlc-pressure %s: dispatch budget=%d cooldown=%.0fs",
                admission.state,
                max_dispatches,
                cooldown_s,
            )

        for task in offered_sorted:
            if not idle_lanes or dispatches >= max_dispatches:
                break
            lane = self._pick_lane(task, idle_lanes)
            if lane is None:
                continue
            now = time.monotonic()
            last = self._last_dispatch.get(lane.role, 0.0)
            if now - last < cooldown_s:
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
        descriptors = _discover_lanes()
        if not descriptors:
            descriptors = [
                LaneDescriptor(role=role, session="", platform="claude")
                for role in FALLBACK_LANE_ROLES
            ]
        for descriptor in descriptors:
            lanes[descriptor.role] = _check_lane(descriptor)
        return lanes

    def _pick_lane(self, task: Task, idle_lanes: list[LaneState]) -> LaneState | None:
        platforms = {platform.lower() for platform in task.platform_suitability}
        for lane in idle_lanes:
            if "any" in platforms or lane.platform in platforms:
                return lane
        return None

    def _dispatch(self, task: Task, lane: LaneState) -> bool:
        dispatcher = Path.home() / "projects/hapax-council/scripts/hapax-methodology-dispatch"
        if not dispatcher.exists():
            log.warning("hapax-methodology-dispatch not found, cannot dispatch to %s", lane.role)
            return False

        try:
            result = subprocess.run(
                [
                    str(dispatcher),
                    "--task",
                    task.task_id,
                    "--lane",
                    lane.role,
                    "--platform",
                    lane.platform,
                    "--mode",
                    "headless",
                    "--launch",
                ],
                timeout=10,
                capture_output=True,
                text=True,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            log.warning("Dispatch to %s failed: %s", lane.role, exc)
            return False

        if result.returncode != 0:
            log.warning(
                "Dispatch to %s failed via methodology dispatcher: %s",
                lane.role,
                result.stderr.strip(),
            )
            return False

        log.info("Dispatched task %s to lane %s", task.task_id, lane.role)
        return True

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


def _lane_from_tmux_session(session: str) -> LaneDescriptor | None:
    for prefix, platform in SESSION_PREFIXES:
        if session.startswith(prefix):
            return LaneDescriptor(
                role=session.removeprefix(prefix),
                session=session,
                platform=platform,
            )
    return None


def _discover_lanes() -> list[LaneDescriptor]:
    try:
        proc = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            timeout=5,
            capture_output=True,
            text=True,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if proc.returncode != 0:
        return []

    lanes: list[LaneDescriptor] = []
    seen: set[str] = set()
    for line in proc.stdout.splitlines():
        descriptor = _lane_from_tmux_session(line.strip())
        if descriptor is None or descriptor.role in seen:
            continue
        seen.add(descriptor.role)
        lanes.append(descriptor)
    return sorted(lanes, key=lambda lane: lane.role)


def _relay_candidates(role: str, session: str = "") -> list[Path]:
    candidates = [
        RELAY_DIR / f"{role}.yaml",
        RELAY_DIR / f"peer-status-{role}.yaml",
    ]
    if session:
        candidates.append(RELAY_DIR / f"peer-status-{session}.yaml")
    return list(dict.fromkeys(candidates))


def _load_freshest_relay(role: str, session: str = "") -> tuple[dict, float | None]:
    fresh_path: Path | None = None
    fresh_mtime = -1.0
    for path in _relay_candidates(role, session):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime > fresh_mtime:
            fresh_path = path
            fresh_mtime = mtime

    if fresh_path is None:
        return {}, None
    try:
        relay = yaml.safe_load(fresh_path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return {}, fresh_mtime
    return relay if isinstance(relay, dict) else {}, fresh_mtime


def _stringify_task(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("task_id", "surface", "id", "name"):
            nested = value.get(key)
            if nested:
                return str(nested)
        return None
    text = str(value).strip()
    return text or None


def _claim_from_relay(relay: dict) -> str | None:
    return _stringify_task(
        relay.get("current_claim")
        or relay.get("current_task")
        or relay.get("task_id")
        or relay.get("currently_working_on")
    )


def _relay_status_is_idle(value: object) -> bool | None:
    if not isinstance(value, str) or not value:
        return None
    status = value.strip().lower().replace(" ", "-").replace("_", "-")
    if status in {"queue-dry", "equilibrium", "idle"} or status.startswith("idle-"):
        return True
    if status in {"active", "executing", "claimed", "in-progress", "working", "retiring"}:
        return False
    return None


def _active_task_candidates(role: str, session: str = "") -> list[Path]:
    candidates = [
        Path.home() / f".cache/hapax/cc-active-task-{role}",
    ]
    if session:
        candidates.append(Path.home() / f".cache/hapax/cc-active-task-{session}")
    return list(dict.fromkeys(candidates))


def _check_lane(lane: str | LaneDescriptor) -> LaneState:
    descriptor = (
        lane
        if isinstance(lane, LaneDescriptor)
        else LaneDescriptor(role=lane, session="", platform="claude")
    )
    state = LaneState(
        role=descriptor.role,
        session=descriptor.session,
        platform=descriptor.platform,
        alive=bool(descriptor.session),
    )

    pidfile = PID_DIR / f"{descriptor.role}.pid"
    if pidfile.exists():
        try:
            pid = int(pidfile.read_text().strip())
            os.kill(pid, 0)
            state.alive = True
            state.pid = pid
        except (ValueError, OSError):
            pass

    relay, relay_mtime = _load_freshest_relay(descriptor.role, descriptor.session)
    if relay_mtime is not None:
        state.relay_age_s = time.time() - relay_mtime

    if relay:
        relay_claim = _claim_from_relay(relay)
        if relay_claim:
            state.claimed_task = relay_claim
            state.idle = False
        relay_idle = _relay_status_is_idle(relay.get("status") or relay.get("session_status"))
        if relay_idle is not None and not state.claimed_task:
            state.idle = relay_idle

    for active_task_file in _active_task_candidates(descriptor.role, descriptor.session):
        try:
            task_id = active_task_file.read_text().strip()
        except OSError:
            continue
        if task_id:
            if not state.claimed_task:
                state.claimed_task = task_id
            state.idle = False
            break

    return state


def _lane_to_dict(lane: LaneState) -> dict:
    return {
        "role": lane.role,
        "session": lane.session,
        "platform": lane.platform,
        "alive": lane.alive,
        "pid": lane.pid,
        "relay_age_s": round(lane.relay_age_s, 1) if lane.relay_age_s != float("inf") else None,
        "claimed_task": lane.claimed_task,
        "idle": lane.idle,
    }
