"""Core coordinator logic — task queue, lane health, dispatch routing.

No-spin law (failure class #9 remediation): the dispatch refusal ledger tracks
(task_id, lane, reason) triples and enters exponential-backoff cooldown after K
identical deterministic refusals.  A single ntfy escalation fires at the K
threshold.  Fleet-wide starvation (offered>0, dispatched=0 for 1h) also triggers
one escalation.  See agents/coordinator/refusal_ledger.py.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml

from agents.coordinator.refusal_ledger import DispatchRefusalLedger
from shared.dispatch_service_time import (
    AGE_NORM_S,
    QueueLane,
    QueueTask,
    parse_ts,
    plan_dispatches,
    wsjf_effective,
)
from shared.jsonl_append import append_jsonl
from shared.notify import send_notification
from shared.recovery_governor import converge_action_cap
from shared.sdlc_lifecycle import TASK_TERMINAL_STATUSES
from shared.sdlc_pressure_gate import admission_state

log = logging.getLogger(__name__)


def _ntfy_escalate(title: str, body: str) -> None:
    """Send an ntfy escalation for the no-spin law.  Best-effort; never raises."""
    try:
        send_notification(title, body, priority="high", tags=["sdlc", "no-spin"])
    except Exception:  # noqa: BLE001 — ntfy is best-effort; never block the tick.
        log.exception("no-spin ntfy escalation failed (continuing)")


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


def _queue_task_routable(task: QueueTask, lane: QueueLane) -> bool:
    platforms = {platform.lower() for platform in task.platform_suitability}
    return "any" in platforms or lane.platform.lower() in platforms


TASKS_DIR = Path.home() / "Documents/Personal/20-projects/hapax-cc-tasks/active"
CACHE_DIR = Path.home() / ".cache/hapax"
RELAY_DIR = CACHE_DIR / "relay"
PID_DIR = Path(f"/run/user/{os.getuid()}/hapax-claude")
SHM_DIR = Path("/dev/shm/hapax-coordinator")
SHM_FILE = SHM_DIR / "state.json"

# The same authority-case ledger cc-stage-advance writes — one SSOT for transitions.
# Honor the same env override so both producers target the same inode.
REOFFER_LEDGER = Path(
    os.environ.get("HAPAX_AUTHORITY_CASE_LEDGER", str(CACHE_DIR / "authority-case-ledger.jsonl"))
).expanduser()

FALLBACK_LANE_ROLES = ("alpha", "beta", "gamma", "delta", "epsilon", "zeta")
LANE_ROLES = FALLBACK_LANE_ROLES
SESSION_PREFIXES = (
    ("hapax-claude-", "claude"),
    ("hapax-codex-", "codex"),
    ("hapax-gemini-", "gemini"),
)
DISPATCH_COOLDOWN_S = 120.0

# A lane that owns a non-terminal task but has emitted no progress signal for this
# long (or whose supervising launcher PID is gone) is projected `stalled` and its
# held task reoffered. 15 min of zero progress on a held task is a real stall, not
# normal think-time (lanes ship in minutes-to-an-hour per velocity calibration).
STALL_OUTPUT_GRACE_S = 900.0
MAX_REOFFERS_PER_TICK = 1  # bound the controller per tick; never thrash the queue
MAX_REOFFERS_PER_TASK = 3  # per-lifetime cap: after N, escalate (block + ntfy), don't loop

# bb-dispatch-scheduler: the measured per-lineage service-time cache the reaper and
# idle-watchdog also read. When present, it replaces the THREE divergent fixed stall
# timeouts (this 900s, the reaper's 1800s, the idle-watchdog's 600s) with one measured
# tau(lineage); when absent the in-process reoffer falls back to STALL_OUTPUT_GRACE_S
# (reoffer is non-destructive, so an aggressive blind grace is safe — unlike the reaper,
# which KILLS and therefore falls back to the conservative ceiling).
DISPATCH_SERVICE_TIME_CACHE_NAME = "dispatch-service-time.json"
# Revert env: restore the exact prior fixed-T, raw-WSJF greedy-global behavior.
SCHEDULER_LEGACY_ENV = "HAPAX_DISPATCH_SCHEDULER_LEGACY"


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
    created_at: float | None = None  # epoch; drives WSJF aging (None -> no aging)


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
    output_age_s: float = float("inf")  # age of the freshest progress signal
    stalled: bool = False  # ground-truth projection, re-derived each tick


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
    lanes_stalled: int = 0
    reoffers_this_tick: int = 0
    lanes: dict[str, dict] = field(default_factory=dict)


class Coordinator:
    """Main coordinator — scans tasks, checks lanes, dispatches work."""

    def __init__(self) -> None:
        self._last_dispatch: dict[str, float] = {}
        # per-task-lifetime reoffer counter (process-local); caps the
        # offered→claim→stall→offered loop and escalates to `blocked` past the cap.
        self._reoffer_counts: dict[str, int] = {}
        # No-spin law: refusal ledger tracks (task, lane, reason) triples and
        # enters cooldown after K identical deterministic refusals.
        self._refusal_ledger = DispatchRefusalLedger(
            _escalate_fn=_ntfy_escalate,
        )

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

        # bb-dispatch-scheduler: load the measured per-lineage service-time cache once.
        # `legacy` restores the prior fixed-T / raw-WSJF behavior exactly (revert env).
        legacy = os.environ.get(SCHEDULER_LEGACY_ENV) == "1"
        cache = None if legacy else _load_dispatch_cache()

        # Project ground-truth `stalled` for every lane, then reoffer held tasks off
        # stalled lanes — bounded, and gated on the SAME #3850 admission read. 'closed'
        # reoffers nothing (the held task stays offered — queued, never dropped). Runs
        # before the dispatch loop so a just-freed lane re-enters the pool next tick.
        # The stall grace is now the MEASURED tau(lineage) when the cache is present
        # (one timeout, not three divergent fixed numbers); 900s fallback when blind.
        non_terminal_ids = frozenset(
            t.task_id for t in tasks if t.status not in TASK_TERMINAL_STATUSES
        )
        for lane in lanes.values():
            lane.stalled = project_stalled(
                lane,
                non_terminal_task_ids=non_terminal_ids,
                output_grace_s=_stall_grace_for(lane.role, cache),
            )
        state.lanes_stalled = sum(1 for lane in lanes.values() if lane.stalled)

        reoffer_budget = 0 if admission.state == "closed" else MAX_REOFFERS_PER_TICK
        reoffered = 0
        for lane in lanes.values():
            if reoffered >= reoffer_budget:
                break
            if lane.stalled and lane.claimed_task and self._reoffer_stalled(lane):
                reoffered += 1
        state.reoffers_this_tick = reoffered

        # bb-dispatch-scheduler: per-lineage virtual queues + WSJF aging. Iterate idle
        # lanes (lane-outer) so a busy/cooled lineage can never head-of-line-block a
        # routable task from a free lane, and let a starved low-WSJF task overtake fresh
        # high-WSJF arrivals (bounded). `legacy` reverts to the prior raw-WSJF task-outer
        # loop. The converge ceiling (max_dispatches) and cooldown are unchanged.
        now_mono = time.monotonic()
        age_norm_s = _age_norm_s(cache)
        queue_tasks = [
            QueueTask(
                task_id=t.task_id,
                wsjf=t.wsjf,
                platform_suitability=t.platform_suitability,
                age_s=max(0.0, state.timestamp - t.created_at) if t.created_at else 0.0,
            )
            for t in offered
        ]
        queue_lanes = [
            QueueLane(
                role=l.role,
                platform=l.platform,
                cooldown_remaining_s=cooldown_s - (now_mono - self._last_dispatch.get(l.role, 0.0)),
            )
            for l in idle_lanes
        ]
        skipped_cooldown = 0
        if legacy:
            plan = plan_dispatches(
                queue_tasks,
                queue_lanes,
                max_dispatches=max_dispatches,
                age_norm_s=age_norm_s,
                legacy=True,
            )
        else:
            plan = []
            remaining = list(queue_tasks)
            for qlane in [lane for lane in queue_lanes if lane.cooldown_remaining_s <= 0]:
                if len(plan) >= max_dispatches:
                    break
                routable = [task for task in remaining if _queue_task_routable(task, qlane)]
                eligible = [
                    task
                    for task in routable
                    if not self._refusal_ledger.any_cooldown_for_pair(
                        task.task_id, qlane.role, now=now_mono
                    )
                ]
                if routable and not eligible:
                    skipped_cooldown += len(routable)
                    continue
                if not eligible:
                    continue
                best = max(
                    eligible,
                    key=lambda task: wsjf_effective(task.wsjf, task.age_s, age_norm_s),
                )
                plan.append((best.task_id, qlane.role))
                remaining.remove(best)
        task_by_id = {t.task_id: t for t in offered}
        lane_by_role = {l.role: l for l in idle_lanes}
        for task_id, role in plan:
            task = task_by_id.get(task_id)
            lane = lane_by_role.get(role)
            if task is None or lane is None:
                continue
            # No-spin law: skip if ANY (task, lane, *) triple is in cooldown.
            if self._refusal_ledger.any_cooldown_for_pair(task_id, role, now=now_mono):
                skipped_cooldown += 1
                log.debug(
                    "no-spin: skipping dispatch %s → %s (in cooldown)",
                    task_id,
                    role,
                )
                continue
            success, refusal_reason = self._dispatch(task, lane)
            if success:
                self._last_dispatch[role] = now_mono
                dispatches += 1
                # Success clears refusal state for this task (the external issue resolved).
                self._refusal_ledger.clear(task_id)
            else:
                # Every failed dispatch is recorded — no silent retries.
                self._refusal_ledger.record_refusal(task_id, role, refusal_reason, now=now_mono)

        state.dispatches_this_tick = dispatches
        state.lanes = {role: _lane_to_dict(l) for role, l in lanes.items()}

        # No-spin law: starvation detector (offered>0, dispatched=0 for 1h →
        # escalate). A no-spin cooldown skip is an intentional circuit-breaker
        # hold, not a fresh starvation condition; reset starvation tracking while
        # the refusal ledger is actively preventing repeat dispatch attempts.
        starvation_offered = 0 if skipped_cooldown > 0 else len(offered)
        self._refusal_ledger.tick_starvation(starvation_offered, dispatches, now=now_mono)

        # Surface refusal stats in SHM.
        refusal_stats = self._refusal_ledger.stats()
        self._write_state(state, refusal_stats=refusal_stats)

        log.info(
            "tick: offered=%d idle_lanes=%d dispatched=%d alive=%d/%d cooled=%d skipped=%d",
            len(offered),
            state.lanes_idle,
            dispatches,
            state.lanes_alive,
            state.lanes_total,
            refusal_stats.get("cooled_down", 0),
            skipped_cooldown,
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

    def _dispatch(self, task: Task, lane: LaneState) -> tuple[bool, str]:
        """Attempt to dispatch a task to a lane.

        Returns (success, refusal_reason).  On success refusal_reason is empty.
        On failure refusal_reason is the stderr text (for the refusal ledger).
        """
        dispatcher = Path.home() / "projects/hapax-council/scripts/hapax-methodology-dispatch"
        if not dispatcher.exists():
            log.warning("hapax-methodology-dispatch not found, cannot dispatch to %s", lane.role)
            return False, "dispatcher_not_found"

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
        except subprocess.TimeoutExpired as exc:
            log.warning("Dispatch to %s timed out: %s", lane.role, exc)
            return False, f"TimeoutExpired: {exc}"
        except OSError as exc:
            log.warning("Dispatch to %s failed: %s", lane.role, exc)
            return False, f"OSError: {exc}"

        if result.returncode != 0:
            reason = result.stderr.strip()
            if not reason:
                reason = f"dispatch_exit_{result.returncode}"
            log.warning(
                "Dispatch to %s failed via methodology dispatcher: %s",
                lane.role,
                reason,
            )
            return False, reason

        log.info("Dispatched task %s to lane %s", task.task_id, lane.role)
        return True, ""

    def _reoffer_stalled(self, lane: LaneState) -> bool:
        """Release a stalled lane's held task back to `offered`/`unassigned`, clear the
        stale claim signal, and emit a ground-truth ledger record. Idempotent: once the
        note is already `offered` a second call is a no-op. Past the per-task reoffer cap
        it escalates to `blocked` (+ntfy) instead of looping. NEVER kills a process."""
        claim = lane.claimed_task
        if not claim:
            return False
        path, match_count = _resolve_task_note(claim)
        if path is None:
            if match_count > 1:
                # ambiguous prefix collision — refuse to guess; emit a visible record
                self._emit_reoffer_ledger(
                    lane, claim, kind="lane_stalled_reoffer_ambiguous", to_stage="error"
                )
                log.error(
                    "reoffer: %d notes match claim %s (prefix collision) — aborting",
                    match_count,
                    claim,
                )
            return False
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return False

        if self._reoffer_counts.get(claim, 0) >= MAX_REOFFERS_PER_TASK:
            return self._escalate_stalled(lane, claim, path, text)

        new = re.sub(
            r"^status: (?:claimed|in_progress)\b", "status: offered", text, count=1, flags=re.M
        )
        new = re.sub(r"^assigned_to: .*$", "assigned_to: unassigned", new, count=1, flags=re.M)
        if new == text:
            return False  # already offered / nothing to release — idempotent no-op
        _atomic_write(path, new)
        self._clear_claim_signal(lane)
        self._reoffer_counts[claim] = self._reoffer_counts.get(claim, 0) + 1
        self._emit_reoffer_ledger(lane, claim, kind="lane_stalled_reoffer", to_stage="offered")
        log.warning(
            "reoffer: lane %s stalled on %s -> offered (output_age=%.0fs, reoffer #%d)",
            lane.role,
            claim,
            lane.output_age_s,
            self._reoffer_counts[claim],
        )
        return True

    def _escalate_stalled(self, lane: LaneState, claim: str, path: Path, text: str) -> bool:
        """Past the per-task reoffer cap: block the task and ntfy the operator instead of
        looping offered→claim→stall→offered forever. Bounded escalation, never a kill."""
        new = re.sub(
            r"^status: (?:claimed|in_progress|offered)\b",
            "status: blocked",
            text,
            count=1,
            flags=re.M,
        )
        new = re.sub(r"^assigned_to: .*$", "assigned_to: unassigned", new, count=1, flags=re.M)
        if new != text:
            _atomic_write(path, new)
        self._clear_claim_signal(lane)
        self._emit_reoffer_ledger(lane, claim, kind="lane_stalled_escalated", to_stage="blocked")
        reoffers = self._reoffer_counts.get(claim, 0)
        log.error(
            "reoffer cap exceeded: %s reoffered %dx without progress -> blocked (lane %s)",
            claim,
            reoffers,
            lane.role,
        )
        try:
            send_notification(
                "SDLC: task stuck, blocked",
                f"{claim} stalled and was reoffered {reoffers}x without progress; set to blocked.",
                priority="high",
                tags=["sdlc", "stalled"],
            )
        except Exception:  # noqa: BLE001 — ntfy is best-effort; never block the tick.
            log.exception("stall-escalation ntfy failed (continuing)")
        return True

    def _clear_claim_signal(self, lane: LaneState) -> None:
        """Remove the per-lane cc-active-task signal so the next tick sees the lane idle."""
        for signal in _active_task_candidates(lane.role, lane.session):
            try:
                signal.unlink()
            except OSError:
                pass

    def _emit_reoffer_ledger(
        self, lane: LaneState, task_id: str, *, kind: str, to_stage: str
    ) -> None:
        """Append a `ts`-keyed record to the SAME ledger cc-stage-advance writes, so the
        real stuck case is finally visible to INV-2. `ts` is an ISO-8601 STRING matching the
        producer byte-for-byte — a float epoch would `fromisoformat`-fail to ~56yr-stale and
        self-generate the exact false 'stuck' finding this projection exists to cure."""
        append_jsonl(
            REOFFER_LEDGER,
            {
                "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "kind": kind,
                "tool": "coordinator",
                "role": lane.role,
                "task_id": task_id,
                "to_stage": to_stage,
                "reason": "launcher_pid_gone"
                if not _launcher_pid_present(lane.role)
                else "output_stale",
                "output_age_s": round(lane.output_age_s, 1)
                if lane.output_age_s != float("inf")
                else None,
            },
            sort_keys=True,
        )

    def _write_state(self, state: CoordinatorState, *, refusal_stats: dict | None = None) -> None:
        SHM_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": state.timestamp,
            "offered_tasks": state.offered_tasks,
            "claimed_tasks": state.claimed_tasks,
            "lanes_alive": state.lanes_alive,
            "lanes_idle": state.lanes_idle,
            "lanes_total": state.lanes_total,
            "dispatches_this_tick": state.dispatches_this_tick,
            "lanes_stalled": state.lanes_stalled,
            "reoffers_this_tick": state.reoffers_this_tick,
            "lanes": state.lanes,
        }
        if refusal_stats:
            payload["refusal_ledger"] = refusal_stats
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
        created_at=_created_at_epoch(meta.get("created_at") or meta.get("updated_at")),
    )


def _created_at_epoch(value: object) -> float | None:
    """Frontmatter ``created_at`` -> epoch. YAML may parse an ISO timestamp into a
    ``datetime`` OR leave it a string; both fold to epoch (None on anything else)."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.timestamp()
    if isinstance(value, str):
        return parse_ts(value)
    return None


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
        CACHE_DIR / f"cc-active-task-{role}",
    ]
    if session:
        candidates.append(CACHE_DIR / f"cc-active-task-{session}")
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

    # freshest progress signal: cc-active-task mtime ∪ relay mtime (relay alone is
    # unreliable per grounding — its mtime can run tens of minutes stale on a live lane).
    progress_mtimes: list[float] = []
    if relay_mtime is not None:
        progress_mtimes.append(relay_mtime)
    for active_task_file in _active_task_candidates(descriptor.role, descriptor.session):
        try:
            progress_mtimes.append(active_task_file.stat().st_mtime)
        except OSError:
            continue
    if progress_mtimes:
        state.output_age_s = time.time() - max(progress_mtimes)

    return state


def _launcher_pid_present(role: str) -> bool:
    """True iff the supervising launcher PID for this lane is alive. Uses os.kill(pid, 0) —
    a liveness probe only (signal 0 delivers nothing); NEVER os.killpg or a real signal."""
    try:
        pid = int((PID_DIR / f"{role}.launcher.pid").read_text().strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _load_dispatch_cache() -> dict | None:
    """The measured service-time cache (`dispatch_service_time --recompute`). None when
    absent/corrupt — callers fall back to the fixed defaults. Path resolves through
    CACHE_DIR at call-time so tests that patch CACHE_DIR stay isolated."""
    try:
        data = json.loads(
            (CACHE_DIR / DISPATCH_SERVICE_TIME_CACHE_NAME).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _stall_grace_for(role: str, cache: dict | None) -> float:
    """Per-lineage stall grace = measured tau(role) when the cache is present, else the
    fixed STALL_OUTPUT_GRACE_S. Reoffer is non-destructive, so the blind fallback stays
    aggressive (unlike the reaper's conservative ceiling fallback when it cannot measure)."""
    if not cache:
        return STALL_OUTPUT_GRACE_S
    per_lineage = cache.get("per_lineage")
    if isinstance(per_lineage, dict):
        entry = per_lineage.get(role)
        if isinstance(entry, dict) and isinstance(entry.get("tau_s"), int | float):
            return float(entry["tau_s"])
    glob = cache.get("global")
    if isinstance(glob, dict) and isinstance(glob.get("tau_s"), int | float):
        return float(glob["tau_s"])
    return STALL_OUTPUT_GRACE_S


def _age_norm_s(cache: dict | None) -> float:
    """One service-epoch for WSJF aging — the measured p90 service span when known."""
    if cache:
        value = cache.get("age_norm_s")
        if isinstance(value, int | float) and value > 0:
            return float(value)
    return AGE_NORM_S


def project_stalled(
    lane: LaneState,
    *,
    non_terminal_task_ids: frozenset[str],
    output_grace_s: float = STALL_OUTPUT_GRACE_S,
) -> bool:
    """PURE projection, re-derived every tick from ground truth (never a persisted edge).

    A lane is stalled iff it owns a non-terminal task AND it has stopped: either its
    supervising launcher PID is gone, or its progress signal is stale past `output_grace_s`.
    """
    claim = lane.claimed_task
    if not claim or claim not in non_terminal_task_ids:
        return False  # idle, or the claim is already terminal → not stalled
    if not _launcher_pid_present(lane.role):
        return True  # owner process gone, task still non-terminal
    return lane.output_age_s > output_grace_s


def _resolve_task_note(task_id: str) -> tuple[Path | None, int]:
    """Locate the single cc-task note for `task_id`, mirroring cc-stage-advance `_find_note`:
    exact `{id}.md` wins, else `{id}-*.md`. Returns (path, match_count). A match_count > 1 is
    a prefix collision the caller MUST refuse to act on — never silently take matches[0]."""
    exact = TASKS_DIR / f"{task_id}.md"
    if exact.exists():
        return exact, 1
    matches = sorted(TASKS_DIR.glob(f"{task_id}-*.md"))
    if len(matches) == 1:
        return matches[0], 1
    return None, len(matches)


def _atomic_write(path: Path, text: str) -> None:
    """Write via temp file + atomic replace — same discipline as _write_state, so a
    concurrent reader never sees a half-written note."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


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
        "stalled": lane.stalled,
        "output_age_s": round(lane.output_age_s, 1) if lane.output_age_s != float("inf") else None,
    }
