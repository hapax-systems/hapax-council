"""Core coordinator logic — task queue, lane health, dispatch routing.

No-spin law (failure class #9 remediation): the dispatch refusal ledger tracks
(task_id, lane, reason) triples and enters exponential-backoff cooldown after K
identical deterministic refusals.  A single ntfy escalation fires at the K
threshold.  Fleet-wide starvation (offered>0, dispatched=0 for 1h) also triggers
one escalation.  See agents/coordinator/refusal_ledger.py.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import sqlite3
import subprocess
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from agents.coordinator.refusal_ledger import DispatchRefusalLedger
from shared import sdlc_dispatch_guards as dispatch_guards
from shared.coord_dispatch import (
    CoordDispatchError,
    DispatchLaunchRequest,
    DispatchPreparationBinding,
    dispatch_preparation_binding_from_payload,
    finalize_accepted_dispatch_on_pickup,
    lane_ownership_projection_hashes,
)
from shared.coord_event_log import CoordEventLog, coord_base_dir
from shared.dispatch_service_time import (
    AGE_NORM_S,
    QueueLane,
    QueueTask,
    is_claude_operator_pool_role,
    parse_ts,
    plan_dispatches,
    wsjf_effective,
)
from shared.dispatcher_policy import LOCAL_DEV_TARGET
from shared.gate_event_producer import build_gate_event
from shared.gate_log import append_gate_event
from shared.intake_fit_scorer import composite_rank_key, fit_score
from shared.notify import send_notification
from shared.recovery_governor import converge_action_cap
from shared.relay_lifecycle import (
    parse_relay_document,
    relay_status_values,
    relay_value_is_retired,
    relay_values_are_retired,
)
from shared.relay_mq import (
    COORDINATOR_ACCEPTED_DISPATCH_REASON_PREFIX,
    CoordinatorDispatchPreparation,
    abort_coordinator_prepared_dispatch,
    coordinator_dispatch_recipient_state,
    prepare_coordinator_dispatch,
)
from shared.relay_mq_envelope import Envelope, compute_payload_hash
from shared.route_metadata_schema import (
    RouteMetadataStatus,
    assess_route_metadata,
    route_metadata_payload_from_frontmatter,
)
from shared.sdlc_lifecycle import TASK_TERMINAL_STATUSES
from shared.sdlc_owner_identity import (
    UNASSIGNED_TASK_OWNERS,
    TaskOwnerIdentity,
    owner_matches,
    parse_task_owner,
    task_owner_is_unassigned,
)
from shared.sdlc_pressure_gate import admission_state
from shared.sdlc_task_store import (
    TaskStoreError,
    claim_dispatch_binding_path,
    load_claim_dispatch_binding,
    resolve_task_note,
)
from shared.strict_yaml import strict_safe_load

log = logging.getLogger(__name__)


def _positive_env_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _env_float(name: str, default: float) -> float:
    """Parse a finite float env var with no sign constraint (allows 0 and negatives).

    For knobs like the intake-fit blend where 0.0 is the default-off golden state and a
    negative value is a valid operator dial — ``_positive_env_float`` would clamp both.
    Non-finite values (``nan``/``inf``) fall back to default — a NaN blend would otherwise
    poison the rank-key's ``max()`` sort (``nan == 0.0`` is False, so it would flow through
    ``composite_rank_key`` and return NaN).
    """
    try:
        value = float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


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


def _task_fields_for_gate_event(task: Task) -> dict[str, object]:
    """Project a parsed ``Task`` into the frontmatter-shaped mapping ``build_gate_event``
    reads (task_id / requirement_vector / routing_class / kind / mutation_surface).

    The coordinator holds a parsed ``Task``, not raw frontmatter; this is the faithful
    bridge so the producer's classification + hashing logic is reused, not duplicated.
    """
    return {
        "task_id": task.task_id,
        "requirement_vector": dict(task.requirement_vector) if task.requirement_vector else {},
        "routing_class": task.routing_class or "",
        "kind": task.kind,
        "mutation_surface": task.mutation_surface or "",
    }


TASKS_DIR = Path.home() / "Documents/Personal/20-projects/hapax-cc-tasks/active"
CACHE_DIR = Path.home() / ".cache/hapax"
RELAY_DIR = CACHE_DIR / "relay"
PID_DIR = Path(f"/run/user/{os.getuid()}/hapax-claude")
CODEX_PID_DIR = Path(f"/run/user/{os.getuid()}/hapax-codex")
SHM_DIR = Path("/dev/shm/hapax-coordinator")
SHM_FILE = SHM_DIR / "state.json"
REPO_ROOT = Path(__file__).resolve().parents[2]

FALLBACK_LANE_ROLES = ("alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta")
LANE_ROLES = FALLBACK_LANE_ROLES
SESSION_PREFIXES = (
    ("hapax-claude-", "claude"),
    ("hapax-codex-", "codex"),
    ("hapax-gemini-", "gemini"),
)
DISPATCH_COOLDOWN_S = 120.0
DISPATCH_TIMEOUT_S = _positive_env_float("HAPAX_COORDINATOR_DISPATCH_TIMEOUT_S", 30.0)
DISPATCH_TIMEOUT_LANDING_GRACE_S = _positive_env_float(
    "HAPAX_COORDINATOR_DISPATCH_TIMEOUT_LANDING_GRACE_S", 5.0
)
COORDINATOR_DISPATCH_MODE = "headless"
COORDINATOR_DISPATCH_PROFILE = "full"
SUPPORTED_DISPATCH_PLATFORMS = ("claude", "codex", "gemini", "vibe", "api")

# Dispatch through the running release checkout by default. A hard-coded primary
# clone can drift dirty and make the coordinator follow unactivated source.
METHODOLOGY_DISPATCHER = Path(
    os.environ.get(
        "HAPAX_METHODOLOGY_DISPATCHER",
        str(REPO_ROOT / "scripts" / "hapax-methodology-dispatch"),
    )
).expanduser()

# A lane may be projected `stalled` after this much progress silence. The
# projection is observation only: it cannot authorize task-owner detachment.
STALL_OUTPUT_GRACE_S = 900.0

# bb-dispatch-scheduler: the measured per-lineage service-time cache the reaper and
# idle-watchdog also read. When present, it replaces the THREE divergent fixed stall
# timeouts (this 900s, the reaper's 1800s, the idle-watchdog's 600s) with one measured
# tau(lineage); when absent the projection falls back to STALL_OUTPUT_GRACE_S.
DISPATCH_SERVICE_TIME_CACHE_NAME = "dispatch-service-time.json"
# Revert env: restore the exact prior fixed-T, raw-WSJF greedy-global behavior.
SCHEDULER_LEGACY_ENV = "HAPAX_DISPATCH_SCHEDULER_LEGACY"
# Intake fit-shadow: blend the demand-shape fit_score into the dispatch rank-key.
# Default 0.0 => composite short-circuits to wsjf_effective (byte-identical plan, the
# golden guarantee); a non-zero value (positive OR negative) is the operator's dial.
INTAKE_FIT_BLEND_ENV = "HAPAX_INTAKE_FIT_BLEND"
# Convergence contract: emit one admission GateEvent per planned dispatch to the
# gate-events.jsonl plane reins' :route lens reads (off by default — the shadow-diff
# discipline; flip to 1 to light the feed). Reuses build_gate_event (no parallel logic)
# and stamps the spine's fit_score. Fail-open: a lost measurement must never crash tick.
INTAKE_FIT_OBSERVE_ENV = "HAPAX_INTAKE_FIT_OBSERVE"


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
    claimed_at: float | None = None
    authority_case: str | None = None
    authority_item: str | None = None
    parent_spec: str | None = None
    priority: str = ""
    kind: str = ""
    tags: tuple[str, ...] = ()
    # Demand-shape for intake fit-routing (the (1)<->(2) loop). Written by the
    # decomposer (request_decomposer/writer.py), read by the SdlcRouter shadow
    # scorer. None = absent/unparsed -> honest-DARK (no fit influence).
    requirement_vector: dict[str, int] | None = None
    routing_class: str | None = None
    mutation_surface: str | None = None
    authority_level: str | None = None
    source_sha256: str = ""


@dataclass
class LaneDescriptor:
    """A live tmux lane and its dispatch platform."""

    role: str
    session: str
    platform: str
    generation: str = ""


@dataclass
class LaneState:
    """Health snapshot of a single work lane."""

    role: str
    session: str = ""
    platform: str = "claude"
    generation: str = ""
    alive: bool = False
    pid: int | None = None
    pid_source: str | None = None
    relay_age_s: float = float("inf")
    claimed_task: str | None = None
    idle: bool = True
    dispatchable: bool = True
    output_age_s: float = float("inf")  # age of the freshest progress signal
    stalled: bool = False  # ground-truth projection, re-derived each tick
    dispatch_ready: bool = True
    dispatch_blocked_reason: str | None = None
    task_ssot_claims: tuple[str, ...] = ()


def _lane_dispatchable(lane: LaneState) -> bool:
    if not lane.dispatchable:
        return False
    return not (lane.platform.lower() == "claude" and is_claude_operator_pool_role(lane.role))


_UNASSIGNED_TASK_OWNERS = UNASSIGNED_TASK_OWNERS
_UNMAPPABLE_OWNER_RESERVATION = "__task_owner_unmappable__"


def _normalized_task_owner(owner: str) -> TaskOwnerIdentity | None:
    try:
        return parse_task_owner(owner)
    except ValueError:
        return None


def _owner_matches_lane(owner: TaskOwnerIdentity | None, lane: LaneState) -> bool:
    if owner is None:
        return False
    raw = owner.reservation_key
    return owner_matches(raw, lane.role, lane.platform)


def _reserve_lanes_from_task_ssot(lanes: dict[str, LaneState], tasks: Sequence[Task]) -> None:
    """Fold authoritative task-note ownership into lane admission.

    Relay and claim-cache files are projections. Their absence cannot make a lane
    available while a nonterminal task note still assigns work to that role.
    Multiple assignments are preserved as an explicit conflict and still HOLD.
    """
    reservations = _task_ssot_reservations(tasks)

    invalid = reservations.get(_UNMAPPABLE_OWNER_RESERVATION, ())
    if invalid:
        blocker = "task_ssot_owner_unmappable:" + ",".join(invalid)
        for lane in lanes.values():
            lane.dispatch_ready = False
            lane.dispatch_blocked_reason = blocker
        return

    for lane in lanes.values():
        claims = tuple(
            sorted(
                set(reservations.get(lane.role, ()))
                | set(reservations.get(f"{lane.platform}/{lane.role}", ()))
            )
        )
        if not claims:
            continue
        lane.task_ssot_claims = claims
        if lane.claimed_task is None:
            lane.claimed_task = claims[0]
        lane.idle = False
        lane.dispatch_ready = False
        lane.dispatch_blocked_reason = "lane_reserved_by_task_ssot:" + ",".join(claims)


def _task_ssot_reservations(tasks: Sequence[Task]) -> dict[str, tuple[str, ...]]:
    reservations: dict[str, list[str]] = {}
    for task in tasks:
        owner = task.assigned_to.strip()
        if task_owner_is_unassigned(owner):
            continue
        try:
            normalized_owner = parse_task_owner(owner)
        except ValueError:
            reservations.setdefault(_UNMAPPABLE_OWNER_RESERVATION, []).append(task.task_id)
            continue
        if normalized_owner is None:
            continue
        reservations.setdefault(normalized_owner.reservation_key, []).append(task.task_id)
    return {role: tuple(sorted(set(task_ids))) for role, task_ids in reservations.items()}


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
    task_status_counts: dict[str, int] = field(default_factory=dict)
    task_flow_counts: dict[str, int] = field(default_factory=dict)
    lanes: dict[str, dict] = field(default_factory=dict)
    starvation_pressure_mask: dict[str, object] | None = None
    task_ssot_complete: bool = True


class Coordinator:
    """Main coordinator — scans tasks, checks lanes, dispatches work."""

    def __init__(self) -> None:
        self._last_dispatch: dict[str, float] = {}
        self._task_ssot_complete = True
        # No-spin law: refusal ledger tracks (task, lane, reason) triples and
        # enters cooldown after K identical deterministic refusals.
        self._refusal_ledger = DispatchRefusalLedger(
            _escalate_fn=_ntfy_escalate,
        )

    def tick(self) -> None:
        tasks = self._scan_tasks()
        lanes = self._check_lanes()
        _reserve_lanes_from_task_ssot(lanes, tasks)
        if not self._task_ssot_complete:
            for lane in lanes.values():
                lane.dispatch_ready = False
                lane.dispatch_blocked_reason = "task_ssot_incomplete"
        # Admit on the DISPATCH TARGET's pressure, not the local box: dev/SDLC
        # execution is confined to appendix (LOCAL_DEV_TARGET), so gating on
        # podium's PRODUCTION load wrongly closes appendix-bound dispatch — the
        # documented "raw PSI starved appendix lanes ~4h" incident
        # (sdlc_pressure_gate.py:176/209/414). read_remote_pressure fails OPEN if
        # the target is unreachable, so this can only loosen, never re-starve.
        admission = admission_state(target_host=LOCAL_DEV_TARGET)
        # Claim detachment is an effect-bearing lifecycle transition. The
        # coordinator has no standing authority to perform it; orphan and
        # stalled claims remain visible HOLDs for an explicitly authorized
        # recovery writer.
        orphan_reoffers = 0
        offered = [t for t in tasks if t.status == "offered"]
        state = CoordinatorState(
            timestamp=time.time(),
            offered_tasks=len(offered),
            claimed_tasks=sum(1 for t in tasks if t.status in ("claimed", "in_progress")),
            lanes_alive=sum(1 for l in lanes.values() if l.alive),
            lanes_idle=sum(
                1
                for l in lanes.values()
                if l.idle
                and l.alive
                and l.claimed_task is None
                and l.dispatch_ready
                and _lane_dispatchable(l)
            ),
            lanes_total=len(lanes),
            task_status_counts=_task_status_counts(tasks),
            task_flow_counts=_task_flow_counts(tasks),
            task_ssot_complete=self._task_ssot_complete,
        )

        dispatches = 0
        idle_lanes = [
            l
            for l in lanes.values()
            if l.alive
            and l.idle
            and l.claimed_task is None
            and l.dispatch_ready
            and _lane_dispatchable(l)
        ]

        # L3: pace the dispatch loop under CPU pressure. 'closed' dispatches
        # nothing this tick (tasks stay offered — queued, not dropped); 'paced'
        # caps throughput and stretches the cooldown so the fleet drains slowly.
        _, cooldown_s = pressure_dispatch_budget(
            admission.state, len(idle_lanes), DISPATCH_COOLDOWN_S
        )
        # bb-control-stability: the RecoveryGovernor's per-tick converge ceiling
        # ({open:6, paced:2, closed:0}) bounds how many dispatches the controller
        # may inject per tick — it cannot become the storm it governs.
        pressure_cap = converge_action_cap(admission.state)
        max_dispatches = min(len(idle_lanes), pressure_cap)
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
        # bb-intake-fit-shadow: blend the demand-shape fit_score into the dispatch
        # rank-key. Default 0.0 => byte-identical to pure WSJF (the golden guarantee).
        fit_blend = _env_float(INTAKE_FIT_BLEND_ENV, 0.0)
        # Convergence contract: light the gate-events.jsonl feed reins :route reads.
        observe_fit = os.environ.get(INTAKE_FIT_OBSERVE_ENV) == "1"
        cache = None if legacy else _load_dispatch_cache()

        # Project `stalled` for observability only. A stale signal is not an
        # authority source and never changes task ownership.
        reofferable_claim_ids = frozenset(
            t.task_id for t in tasks if t.status in {"claimed", "in_progress"}
        )
        for lane in lanes.values():
            lane.stalled = project_stalled(
                lane,
                non_terminal_task_ids=reofferable_claim_ids,
                output_grace_s=_stall_grace_for(lane.role, cache),
            )
        state.lanes_stalled = sum(1 for lane in lanes.values() if lane.stalled)

        state.reoffers_this_tick = orphan_reoffers

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
                requirement_vector=t.requirement_vector,
                routing_class=t.routing_class,
            )
            for t in offered
        ]
        queue_lanes = [
            QueueLane(
                role=l.role,
                platform=l.platform,
                cooldown_remaining_s=cooldown_s - (now_mono - self._last_dispatch.get(l.role, 0.0)),
                dispatchable=_lane_dispatchable(l),
            )
            for l in idle_lanes
        ]
        # Delegate ordering/aging/fairness to the tested plan_dispatches (both the
        # default lane-outer VOQ planner and the `legacy` revert path), then run a
        # no-spin repair pass: a (task, lane) pair in refusal cooldown is replanned
        # to the next eligible task for that lane instead of head-of-line-blocking
        # it. The repair applies in BOTH scheduler modes — the legacy path no longer
        # lets a cooled high-WSJF pair freeze a lane other work could use.
        plan = plan_dispatches(
            queue_tasks,
            queue_lanes,
            max_dispatches=max_dispatches,
            age_norm_s=age_norm_s,
            legacy=legacy,
            fit_blend=fit_blend,
        )
        plan, skipped_cooldown = self._repair_cooled_plan(
            plan,
            queue_tasks,
            queue_lanes,
            age_norm_s=age_norm_s,
            now_mono=now_mono,
            fit_blend=fit_blend,
        )
        task_by_id = {t.task_id: t for t in offered}
        lane_by_role = {l.role: l for l in idle_lanes}
        for task_id, role in plan:
            task = task_by_id.get(task_id)
            lane = lane_by_role.get(role)
            if task is None or lane is None:
                continue
            success, refusal_reason = self._dispatch(task, lane)
            if success:
                self._last_dispatch[role] = now_mono
                dispatches += 1
                # Success clears refusal state for this task (the external issue resolved).
                self._refusal_ledger.clear(task_id)
            elif refusal_reason.startswith("dispatch_in_flight:"):
                log.info("Dispatch for task=%s lane=%s remains in flight", task_id, role)
            else:
                # Every failed dispatch is recorded — no silent retries.
                self._refusal_ledger.record_refusal(task_id, role, refusal_reason, now=now_mono)
            # Convergence contract: emit one admission gate-event per planned dispatch
            # to the gate-events.jsonl plane reins' :route lens reads (flag-gated + fail-open).
            if observe_fit:
                self._emit_admission_gate_event(task, lane, accepted=success)

        state.dispatches_this_tick = dispatches
        state.lanes = {role: _lane_to_dict(l) for role, l in lanes.items()}

        # No-spin law: fleet-starvation detector (offered>0, dispatched=0 for 1h →
        # ONE escalation). Count only offered tasks the refusal ledger is NOT
        # already holding: a cooled pair has its own circuit-breaker escalation, so
        # counting it here would double-escalate the same root cause. But zeroing
        # the count whenever ANY single pair is cooled (the prior behavior) let one
        # cooled pair silently mask genuine starvation of the rest of the fleet —
        # a task that is offered, undispatched, and NOT cooled must still drive the
        # starvation horizon. Only when EVERY offered task is cooled does the count
        # reach 0 (the intentional no-double-escalation case).
        # Gate on idle capacity: a fleet with NO idle lanes is saturated (busy
        # working), not starving — counting offered work as starved there would
        # page the operator for a healthy fleet (executive_function noise). The
        # 2026-06-12 incident had idle_lanes=1, dispatched=0: capacity present,
        # dispatch still failing — that is the starvation this detector is for.
        # Discount only tasks held by an ESCALATED cooldown (deterministic refusal
        # past K, already paged); a transient cooldown (timeouts, no escalation)
        # must still drive the horizon, else a task stuck on transient failures is
        # silently dropped — neither escalated nor counted.
        cooled_offered = sum(
            1
            for t in offered
            if self._refusal_ledger.any_cooldown_for_task(
                t.task_id, escalated_only=True, now=now_mono
            )
        )
        # Pressure CLOSED intentionally yields a zero dispatch budget: work remains
        # queued, but the controller is not failing to use available capacity.
        starvation_capacity = bool(idle_lanes) and pressure_cap > 0
        uncooled_offered = max(0, len(offered) - cooled_offered)
        starvation_offered = uncooled_offered if starvation_capacity else 0
        if idle_lanes and uncooled_offered > 0 and pressure_cap == 0:
            state.starvation_pressure_mask = {
                "active": True,
                "reason": "sdlc_pressure_closed",
                "admission_state": admission.state,
                "admission_reasons": list(getattr(admission, "reasons", []) or []),
                "offered_tasks": len(offered),
                "uncooled_offered": uncooled_offered,
                "idle_lanes": len(idle_lanes),
                "pressure_cap": pressure_cap,
                "dispatches_this_tick": dispatches,
            }
            log.warning(
                "starvation masked by closed pressure: offered=%d uncooled=%d idle_lanes=%d",
                len(offered),
                uncooled_offered,
                len(idle_lanes),
            )
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
        tasks, self._task_ssot_complete = self._read_task_snapshot()
        return tasks

    def _read_task_snapshot(self) -> tuple[list[Task], bool]:
        if not TASKS_DIR.is_dir():
            return [], False
        tasks: list[Task] = []
        complete = True
        for path in sorted(TASKS_DIR.glob("*.md")):
            frontmatter, valid, source_sha256 = _load_task_frontmatter(path)
            if not valid or frontmatter is None:
                complete = False
                log.error("task SSOT parse HOLD: unreadable or malformed note %s", path)
                continue
            task = _task_from_frontmatter(path, frontmatter, source_sha256=source_sha256)
            if task is not None:
                tasks.append(task)
        return tasks, complete

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

    def _repair_cooled_plan(
        self,
        plan: list[tuple[str, str]],
        queue_tasks: list[QueueTask],
        queue_lanes: list[QueueLane],
        *,
        age_norm_s: float,
        now_mono: float,
        fit_blend: float = 0.0,
    ) -> tuple[list[tuple[str, str]], int]:
        """No-spin law for the planned dispatches: drop refusal-cooled pairs and
        replan their freed lane to the best eligible non-cooled task.

        ``plan_dispatches`` is cooldown-blind (it only knows the per-lane dispatch
        rate-limit, not the refusal ledger). This pass enforces the no-spin
        invariant on top of whatever plan it produced — in both the default and
        the ``legacy`` scheduler — so a cooled (task, lane) pair never head-of-line-
        blocks a lane that another offered task could use.

        Returns ``(repaired_plan, skipped_cooldown)`` where ``skipped_cooldown``
        counts lanes freed by a cooled pair that had no eligible backfill.
        """

        def cooled(task_id: str, role: str) -> bool:
            return self._refusal_ledger.any_cooldown_for_pair(task_id, role, now=now_mono)

        lane_by_role = {lane.role: lane for lane in queue_lanes}
        planned: set[str] = {task_id for task_id, _ in plan}
        repaired: list[tuple[str, str]] = []
        skipped = 0
        for task_id, role in plan:
            if not cooled(task_id, role):
                repaired.append((task_id, role))
                continue
            # Cooled: free the lane and try to backfill with the best eligible task
            # (routable, not already planned, not itself in cooldown on this lane).
            planned.discard(task_id)
            lane = lane_by_role.get(role)
            candidates = [
                t
                for t in queue_tasks
                if t.task_id not in planned
                and lane is not None
                and _queue_task_routable(t, lane)
                and not cooled(t.task_id, role)
            ]
            if candidates:
                best = max(
                    candidates,
                    key=lambda t: composite_rank_key(
                        wsjf_effective(t.wsjf, t.age_s, age_norm_s),
                        fit_score(t.requirement_vector),
                        blend=fit_blend,
                    ),
                )
                repaired.append((best.task_id, role))
                planned.add(best.task_id)
            else:
                skipped += 1
        return repaired, skipped

    def _emit_admission_gate_event(self, task: Task, lane: LaneState, *, accepted: bool) -> None:
        """Emit one observational admission ``GateEvent`` for a planned dispatch.

        Reuses ``build_gate_event`` (the designated admission assembler — no parallel
        logic) for routing_class resolution + requirement_vector + task_hash, then
        stamps the spine's ``fit_score`` and ``provenance="admission"``. Fail-open: any
        assembly or I/O error is logged and swallowed — a lost measurement must never
        crash the dispatch tick (observation is best-effort, the plan is authoritative).
        Lights the ``gate-events.jsonl`` feed the reins ``:route`` lens reads.
        """
        try:
            event = build_gate_event(
                _task_fields_for_gate_event(task),
                route=lane.platform,
                demand_vector=None,
                gate_result="accept" if accepted else "reject",
            )
            # Stamp the measured score only when the vector was measured-complete: the
            # producer sets event.requirement_vector non-empty iff the explicit 8-dim
            # vector was valid, so a DARK/partial task stamps None (no measured demand),
            # mirroring reins' _measured_reqvec_or_absent honesty (not 0.0-as-measured).
            event.fit_score = (
                fit_score(task.requirement_vector) if event.requirement_vector else None
            )
            event.provenance = "admission"
            append_gate_event(event)
        except Exception:  # noqa: BLE001 - observation is best-effort; never block dispatch.
            log.warning("admission gate-event emit failed for task=%s", task.task_id, exc_info=True)

    def _fresh_dispatch_task(self, task: Task, lane: LaneState) -> tuple[Task | None, str]:
        """Return the current dispatchable task or a fail-closed blocker."""
        lane_blocker = _fresh_lane_ownership_blocker(lane)
        if lane_blocker:
            log.warning("dispatch HOLD for %s: %s", lane.role, lane_blocker)
            return None, lane_blocker
        latest_tasks, task_ssot_complete = self._read_task_snapshot()
        if not task_ssot_complete:
            log.warning("dispatch HOLD for %s: task SSOT snapshot incomplete", lane.role)
            return None, "task_ssot_incomplete"
        fresh_task_matches = [
            candidate for candidate in latest_tasks if candidate.task_id == task.task_id
        ]
        if len(fresh_task_matches) != 1:
            reason = f"task_ssot_identity_ambiguous:matches={len(fresh_task_matches)}"
            log.warning("dispatch HOLD for %s: %s task=%s", lane.role, reason, task.task_id)
            return None, reason
        fresh_task = fresh_task_matches[0]
        if (
            fresh_task.status != "offered"
            or fresh_task.assigned_to.strip().lower() not in _UNASSIGNED_TASK_OWNERS
        ):
            reason = (
                "task_not_dispatchable_from_fresh_ssot:"
                f"status={fresh_task.status}:assigned_to={fresh_task.assigned_to}"
            )
            log.warning("dispatch HOLD for %s: %s task=%s", lane.role, reason, task.task_id)
            return None, reason
        reservations = _task_ssot_reservations(latest_tasks)
        invalid_owners = reservations.get(_UNMAPPABLE_OWNER_RESERVATION, ())
        if invalid_owners:
            reason = "task_ssot_owner_unmappable:" + ",".join(invalid_owners)
            log.warning("dispatch HOLD for %s: %s", lane.role, reason)
            return None, reason
        lane_reservations = tuple(
            sorted(
                set(reservations.get(lane.role, ()))
                | set(reservations.get(f"{lane.platform}/{lane.role}", ()))
            )
        )
        if lane_reservations:
            reason = "lane_reserved_by_task_ssot:" + ",".join(lane_reservations)
            log.warning("dispatch HOLD for %s: %s", lane.role, reason)
            return None, reason
        if not _queue_task_routable(
            QueueTask(
                task_id=fresh_task.task_id,
                wsjf=fresh_task.wsjf,
                platform_suitability=fresh_task.platform_suitability,
                age_s=0.0,
            ),
            QueueLane(role=lane.role, platform=lane.platform, cooldown_remaining_s=0.0),
        ):
            reason = f"task_not_routable_from_fresh_ssot:platform={lane.platform}"
            log.warning("dispatch HOLD for %s: %s task=%s", lane.role, reason, task.task_id)
            return None, reason
        return fresh_task, ""

    def _dispatch(self, task: Task, lane: LaneState) -> tuple[bool, str]:
        """Attempt to dispatch a task to a lane.

        Returns (success, refusal_reason).  On success refusal_reason is empty.
        On failure refusal_reason is the stderr text (for the refusal ledger).
        """
        dispatcher = METHODOLOGY_DISPATCHER
        if not dispatcher.exists():
            log.warning("hapax-methodology-dispatch not found, cannot dispatch to %s", lane.role)
            return False, "dispatcher_not_found"
        task, blocker = self._fresh_dispatch_task(task, lane)
        if task is None:
            return False, blocker
        try:
            message_id = _prepare_dispatch_message(task, lane)
        except _CoordinatorDispatchInFlight as exc:
            message_id = exc.preparation.message_id
            if _dispatch_landed(task, lane, message_id):
                blocker = _finalize_dispatch_pickup(task, lane, message_id)
                if not blocker:
                    return True, ""
                return False, blocker
            return False, f"dispatch_in_flight:{message_id}:pickup_pending"
        except Exception as exc:  # noqa: BLE001 - refusal ledger needs the root cause.
            next_action = (
                "next_action=check HAPAX_RELAY_MQ_DB path, relay DB parent permissions, "
                "and disk pressure; then rerun governed dispatch for the same task/lane"
            )
            log.warning(
                "Dispatch to %s could not mint durable MQ binding: %s; %s",
                lane.role,
                exc,
                next_action,
            )
            return False, f"durable_mq_prepare_failed:{type(exc).__name__}:{exc}; {next_action}"

        refreshed_lane = _refresh_dispatch_lane(lane)
        post_prepare_task, blocker = self._fresh_dispatch_task(task, refreshed_lane)
        if post_prepare_task is None:
            return False, _abort_prepared_dispatch_message(message_id, lane, blocker)
        if post_prepare_task != task:
            log.warning(
                "dispatch HOLD for %s: selected task changed during MQ preparation task=%s",
                lane.role,
                task.task_id,
            )
            blocker = "task_ssot_changed_during_mq_prepare"
            return False, _abort_prepared_dispatch_message(message_id, lane, blocker)
        task = post_prepare_task

        cmd = [
            str(dispatcher),
            "--task",
            task.task_id,
            "--lane",
            lane.role,
            "--platform",
            lane.platform,
            "--mode",
            COORDINATOR_DISPATCH_MODE,
            "--launch",
        ]
        if message_id:
            cmd.extend(["--mq-message-id", message_id])

        try:
            dispatch_env = os.environ.copy()
            # The methodology dispatcher retains a legacy opportunistic claim
            # sweeper, and cc-claim retains lease-expiry removal of session-keyed
            # claims. Coordinator dispatch has no claim-detachment authority.
            dispatch_env["HAPAX_DISPATCH_CLAIM_SWEEP"] = "0"
            dispatch_env["HAPAX_CLAIM_LEASE_TTL_SECS"] = str(2**63 - 1)
            result = subprocess.run(
                cmd,
                timeout=DISPATCH_TIMEOUT_S,
                capture_output=True,
                text=True,
                env=dispatch_env,
            )
        except subprocess.TimeoutExpired as exc:
            step_s = 0.5
            attempts = max(1, math.ceil(DISPATCH_TIMEOUT_LANDING_GRACE_S / step_s) + 1)
            for attempt in range(attempts):
                if _dispatch_landed(task, lane, message_id):
                    finalization_blocker = _finalize_dispatch_pickup(
                        task,
                        lane,
                        message_id,
                    )
                    if finalization_blocker:
                        log.warning(
                            "Dispatch pickup for %s could not be finalized: %s",
                            lane.role,
                            finalization_blocker,
                        )
                        return False, finalization_blocker
                    log.info(
                        "Dispatch to %s exceeded %.0fs but lane pickup evidence is live",
                        lane.role,
                        DISPATCH_TIMEOUT_S,
                    )
                    return True, ""
                if attempt < attempts - 1:
                    time.sleep(min(step_s, DISPATCH_TIMEOUT_LANDING_GRACE_S))
            log.warning("Dispatch to %s timed out: %s", lane.role, exc)
            blocker = f"TimeoutExpired: {exc}"
            return False, _abort_prepared_dispatch_message(message_id, lane, blocker)
        except OSError as exc:
            log.warning("Dispatch to %s failed: %s", lane.role, exc)
            blocker = f"OSError: {exc}"
            return False, _abort_prepared_dispatch_message(message_id, lane, blocker)

        if result.returncode != 0:
            reason = result.stderr.strip()
            if not reason:
                reason = f"dispatch_exit_{result.returncode}"
            log.warning(
                "Dispatch to %s failed via methodology dispatcher: %s",
                lane.role,
                reason,
            )
            return False, _abort_prepared_dispatch_message(message_id, lane, reason)

        log.info("Dispatched task %s to lane %s", task.task_id, lane.role)
        return True, ""

    def _reoffer_stalled(self, lane: LaneState) -> bool:
        """Refuse automatic detachment of a stalled lane's task owner."""
        claim = lane.claimed_task
        if not claim:
            return False
        log.warning(
            "claim detach HOLD: lane=%s task=%s reason=governed_effect_authority_required",
            lane.role,
            claim,
        )
        return False

    def _escalate_stalled(self, lane: LaneState, claim: str, path: Path, text: str) -> bool:
        """Refuse automatic stalled-task escalation for the same authority reason."""
        log.warning(
            "claim escalation HOLD: lane=%s task=%s reason=governed_effect_authority_required",
            lane.role,
            claim,
        )
        return False

    def _reoffer_orphaned_claims(
        self, tasks: Sequence[Task], lanes: dict[str, LaneState], *, now_wall: float
    ) -> int:
        """Refuse automatic orphan-claim detachment.

        Marker or launcher absence is support evidence only. A governed recovery
        writer must bind fresh cross-host evidence, exact preimage, and single-use
        effect authority before changing owner or status.
        """
        return 0

    def _reoffer_orphaned_claim(self, task: Task, lanes: dict[str, LaneState]) -> bool:
        log.warning(
            "orphan claim detach HOLD: task=%s assigned_to=%s "
            "reason=governed_effect_authority_required",
            task.task_id,
            task.assigned_to,
        )
        return False

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
            "claim_detach_policy": "hold_requires_governed_effect_authority",
            "task_ssot_complete": state.task_ssot_complete,
            "task_status_counts": state.task_status_counts,
            "task_flow_counts": state.task_flow_counts,
            "lanes": state.lanes,
        }
        if state.starvation_pressure_mask:
            payload["starvation_pressure_mask"] = state.starvation_pressure_mask
        if refusal_stats:
            payload["refusal_ledger"] = refusal_stats
        tmp = SHM_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.rename(SHM_FILE)


def _load_task_frontmatter(path: Path) -> tuple[dict | None, bool, str]:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None, False, ""
    if not text.startswith("---"):
        return None, False, ""
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None, False, ""
    try:
        meta = strict_safe_load(parts[1])
    except (ValueError, TypeError):
        return None, False, ""
    if not isinstance(meta, dict):
        return None, False, ""
    status = meta.get("status")
    assigned_to = meta.get("assigned_to")
    task_id = meta.get("task_id")
    if not isinstance(status, str) or not status.strip():
        return None, False, ""
    if "assigned_to" not in meta:
        return None, False, ""
    if assigned_to is not None and (not isinstance(assigned_to, str) or not assigned_to.strip()):
        return None, False, ""
    if not isinstance(task_id, str) or not task_id.strip():
        return None, False, ""
    task_id = task_id.strip()
    if path.stem != task_id and not path.stem.startswith(f"{task_id}-"):
        return None, False, ""
    return meta, True, hashlib.sha256(raw).hexdigest()


def _parse_task(path: Path) -> Task | None:
    meta, valid, source_sha256 = _load_task_frontmatter(path)
    if not valid or meta is None:
        return None
    return _task_from_frontmatter(path, meta, source_sha256=source_sha256)


def _task_from_frontmatter(path: Path, meta: dict, *, source_sha256: str = "") -> Task | None:
    status = str(meta.get("status", "")).strip().lower()
    if status in TASK_TERMINAL_STATUSES:
        return None
    platforms = meta.get("platform_suitability", ["any"])
    if isinstance(platforms, str):
        platforms = [platforms]
    platforms = _effective_platform_suitability(platforms, meta)
    return Task(
        task_id=str(meta["task_id"]).strip(),
        title=_frontmatter_text(meta.get("title")) or path.stem,
        status=status,
        assigned_to=_frontmatter_text(meta.get("assigned_to")) or "unassigned",
        wsjf=_frontmatter_float(meta.get("wsjf")),
        effort_class=_frontmatter_text(meta.get("effort_class")) or "standard",
        platform_suitability=tuple(platforms),
        quality_floor=_frontmatter_text(meta.get("quality_floor")) or "deterministic_ok",
        path=path,
        created_at=_created_at_epoch(meta.get("created_at") or meta.get("updated_at")),
        claimed_at=_created_at_epoch(meta.get("claimed_at")),
        authority_case=_frontmatter_text(meta.get("authority_case")),
        authority_item=_frontmatter_text(meta.get("authority_item") or meta.get("slice_id")),
        parent_spec=_frontmatter_text(meta.get("parent_spec")),
        priority=(_frontmatter_text(meta.get("priority")) or "").lower(),
        kind=(_frontmatter_text(meta.get("kind")) or "").lower(),
        tags=_frontmatter_tags(meta.get("tags")),
        requirement_vector=_parse_requirement_vector(meta.get("requirement_vector")),
        routing_class=_frontmatter_text(meta.get("routing_class")),
        mutation_surface=_frontmatter_text(meta.get("mutation_surface")),
        authority_level=_frontmatter_text(meta.get("authority_level")),
        source_sha256=source_sha256,
    )


def _parse_requirement_vector(value: object) -> dict[str, int] | None:
    """Parse the decomposer-written requirement_vector (8-dim, strict int 0..5).

    Returns None when absent/invalid so the fit-scorer treats it as honest-DARK
    (no fit influence). Strict-int validation mirrors SdlcRoutingRequest's own
    validator — a bool or non-int score is rejected (not coerced).
    """
    if not isinstance(value, dict) or not value:
        return None
    parsed: dict[str, int] = {}
    for key, score in value.items():
        if not isinstance(key, str) or isinstance(score, bool) or not isinstance(score, int):
            return None
        parsed[key] = score
    return parsed


def _frontmatter_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return None
    text = str(value).strip().strip("\"'")
    return None if not text or text.lower() in {"null", "none", "~"} else text


def _frontmatter_float(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, str) and not value.strip():
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _frontmatter_tags(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        raw = [value]
    elif isinstance(value, list):
        raw = value
    else:
        return ()
    tags: list[str] = []
    for item in raw:
        tag = str(item).strip().lower()
        if tag:
            tags.append(tag)
    return tuple(tags)


FLOW_STATUS_KEYS = ("offered", "claimed", "in_progress", "blocked", "pr_open")


def _task_status_counts(tasks: Sequence[Task]) -> dict[str, int]:
    counts = Counter(task.status for task in tasks)
    return {status: int(counts.get(status, 0)) for status in FLOW_STATUS_KEYS}


def _is_remediation_task(task: Task) -> bool:
    haystack = " ".join(
        (
            task.task_id,
            task.title,
            task.effort_class,
            task.quality_floor,
            task.kind,
            " ".join(task.tags),
        )
    ).lower()
    return "remediation" in haystack or "admission-blocked" in haystack


def _is_unowned(task: Task) -> bool:
    owner = task.assigned_to.strip().lower()
    return task.status in {"offered", "claimed", "in_progress"} and owner in {
        "",
        "null",
        "none",
        "~",
        "unassigned",
    }


def _task_flow_counts(tasks: Sequence[Task]) -> dict[str, int]:
    return {
        **_task_status_counts(tasks),
        "remediation": sum(1 for task in tasks if _is_remediation_task(task)),
        "no_owner": sum(1 for task in tasks if _is_unowned(task)),
    }


def _platform_tokens(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raw = [value]
    elif isinstance(value, (list, tuple, set, frozenset)):
        raw = [str(item) for item in value]
    else:
        raw = [str(value)]
    out: list[str] = []
    for item in raw:
        token = item.strip().lower().replace("_", "-")
        if token and token not in out:
            out.append(token)
    return tuple(out)


def _effective_platform_suitability(platforms: object, frontmatter: dict) -> tuple[str, ...]:
    base = _platform_tokens(platforms) or ("any",)
    try:
        assessment = assess_route_metadata(frontmatter)
    except Exception:  # noqa: BLE001 - defense-in-depth; assess_route_metadata is fail-safe
        # Defensive only: assess_route_metadata does NOT raise on malformed input (it returns
        # status=MALFORMED, metadata=None — handled below). If it ever did raise, fail closed.
        log.warning(
            "route metadata assessment raised for task %r; failing scope mask closed",
            frontmatter.get("task_id"),
        )
        return ()
    mask_declared = "route_constraints" in route_metadata_payload_from_frontmatter(frontmatter)
    if assessment.status is RouteMetadataStatus.MALFORMED and mask_declared:
        # FAIL CLOSED (scope-mask R5): a scope NEVER/ONLY mask WAS DECLARED but the metadata is
        # unparseable, so the mask cannot be trusted/read. Return () (the "nothing suitable / held"
        # signal), never the unconstrained base — silently dropping a declared-but-unreadable mask
        # to base is the fail-open that voids the scope regime. This keys on STATUS + mask-presence,
        # NOT on an exception (assess never raises on malformed) nor on metadata-is-None. Mask
        # presence is checked via route_metadata_payload_from_frontmatter — the SAME canonical
        # extractor the schema uses — so it catches route_constraints in BOTH the top-level and the
        # nested `route_metadata:` mapping forms (a top-level-key check missed the nested form).
        # Tasks that are MALFORMED only because unrelated fields are missing (e.g. a quality_floor-
        # only note with no mask) have no mask to drop and fall through to base — normal dispatch
        # is unaffected.
        log.warning(
            "malformed route metadata WITH a declared route_constraints mask for task %r (%s); "
            "scope suitability failed closed to ()",
            frontmatter.get("task_id"),
            "; ".join(assessment.validation_errors) or "unparseable",
        )
        return ()
    metadata = assessment.metadata
    if metadata is None:
        # HOLD / no declared route_metadata / MALFORMED-without-a-mask: no readable scope mask is
        # in play (the NEVER/ONLY mask lives in route_constraints, absent or maskless here), so the
        # base suitability stands. A present-but-unparseable mask is handled by the fail-close above.
        return base

    constraints = metadata.route_constraints
    required_mode = _frontmatter_text(constraints.required_mode)
    if required_mode and required_mode.lower() != COORDINATOR_DISPATCH_MODE:
        return ()
    required_profile = _frontmatter_text(constraints.required_profile)
    if required_profile and required_profile.lower() != COORDINATOR_DISPATCH_PROFILE:
        return ()

    allowed = set(_platform_tokens(constraints.allowed_platforms))
    prohibited = set(_platform_tokens(constraints.prohibited_platforms))
    if "any" in base:
        if not allowed and not prohibited:
            return ("any",)
        selected = set(allowed or SUPPORTED_DISPATCH_PLATFORMS)
    else:
        selected = set(base)
        if allowed:
            selected &= allowed
    selected -= prohibited
    return tuple(platform for platform in SUPPORTED_DISPATCH_PLATFORMS if platform in selected)


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


TMUX_DISCOVERY_FORMAT = "#{session_name}\t#{session_id}\t#{session_created}"


def _pid_generation(pid: int) -> str:
    """Bind a PID-backed lane to Linux process start time, not PID alone."""

    try:
        stat_text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        tail = stat_text.rsplit(")", 1)[1].split()
        start_ticks = tail[19]
    except (OSError, IndexError):
        return ""
    return f"pid:{pid}:{start_ticks}"


def _lane_from_tmux_session(session: str, generation: str = "") -> LaneDescriptor | None:
    for prefix, platform in SESSION_PREFIXES:
        if session.startswith(prefix):
            return LaneDescriptor(
                role=session.removeprefix(prefix),
                session=session,
                platform=platform,
                generation=generation,
            )
    return None


def _discover_lanes() -> list[LaneDescriptor]:
    lanes_by_role: dict[str, LaneDescriptor] = {
        role: LaneDescriptor(role=role, session="", platform="claude")
        for role in FALLBACK_LANE_ROLES
    }
    try:
        proc = subprocess.run(
            ["tmux", "list-sessions", "-F", TMUX_DISCOVERY_FORMAT],
            timeout=5,
            capture_output=True,
            text=True,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        proc = None
    if proc is not None and proc.returncode == 0:
        for line in proc.stdout.splitlines():
            fields = line.rstrip().split("\t")
            session = fields[0].strip()
            generation = ":".join(fields[1:3]) if len(fields) >= 3 else ""
            descriptor = _lane_from_tmux_session(session, generation)
            if descriptor is not None:
                lanes_by_role[descriptor.role] = descriptor

    for pid_dir, platform in ((PID_DIR, "claude"), (CODEX_PID_DIR, "codex")):
        try:
            pid_paths = sorted(pid_dir.glob("*.pid"))
        except OSError:
            pid_paths = []
        for path in pid_paths:
            name = path.name
            if name.endswith(".launcher.pid"):
                role = name.removesuffix(".launcher.pid")
            else:
                role = name.removesuffix(".pid")
            if role:
                try:
                    pid_generation = _pid_generation(int(path.read_text().strip()))
                except (OSError, ValueError):
                    pid_generation = ""
                existing = lanes_by_role.get(role)
                if existing is None or (not existing.session and not existing.generation):
                    lanes_by_role[role] = LaneDescriptor(
                        role=role,
                        session="",
                        platform=platform,
                        generation=pid_generation,
                    )

    return sorted(lanes_by_role.values(), key=lambda lane: lane.role)


def _relay_candidates(role: str, session: str = "") -> list[Path]:
    candidates = [
        RELAY_DIR / f"{role}-status.yaml",
        RELAY_DIR / f"{role}.yaml",
        RELAY_DIR / f"status-{role}.yaml",
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
        relay = parse_relay_document(fresh_path.read_text(encoding="utf-8"))
    except OSError:
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
    return None if not text or text.lower() in {"null", "none", "~"} else text


def _normalized_status(value: object) -> str:
    if not isinstance(value, str) or not value:
        return ""
    return value.strip().lower().replace(" ", "-").replace("_", "-")


def _relay_reports_claim_ownership_block(relay: dict) -> bool:
    status = _normalized_status(relay.get("status") or relay.get("session_status"))
    return status == "blocked-claim-ownership"


def _relay_status_has_no_active_claim(relay: dict) -> bool:
    status = _normalized_status(relay.get("status") or relay.get("session_status"))
    if _relay_is_retired(relay):
        return True
    if not status:
        return False
    if (
        status in {"queue-dry", "equilibrium", "idle"}
        or _relay_status_is_retired(status)
        or status.startswith("idle-")
    ):
        return True
    return (
        status.startswith("resolved-")
        or "no-active-claim" in status
        or "no-task" in status
        or status == "blocked-claim-ownership"
    )


def _relay_status_supports_task_id_claim(relay: dict) -> bool:
    status = _normalized_status(relay.get("status") or relay.get("session_status"))
    if not status:
        return False
    return status in {"active", "executing", "claimed", "in-progress", "working"} or any(
        token in status for token in ("active-claim", "in-progress", "working")
    )


def _diagnostic_claim_text(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip().lower()
    return text.startswith("other session active:") or (
        " assigned_to=" in text and " session=" in text
    )


def _claim_from_relay(relay: dict) -> str | None:
    if _relay_reports_claim_ownership_block(relay) or _relay_status_has_no_active_claim(relay):
        return None
    for key in ("current_claim", "current_task", "currently_working_on"):
        value = relay.get(key)
        if _diagnostic_claim_text(value):
            continue
        claim = _stringify_task(value)
        if claim:
            return claim
    if _relay_status_supports_task_id_claim(relay):
        return _stringify_task(relay.get("task_id"))
    return None


def _relay_status_is_retired(value: object) -> bool:
    # Delegate to the single-source predicate (shared.relay_lifecycle) so the
    # coordinator's capacity projection agrees with the dispatch gate and the
    # launcher. Closes the SUPERSEDED/CLOSED/ANTIGRAVITY_TAKEOVER vocabulary gap
    # the coordinator previously missed (it routed them -> launcher refused ->
    # rc=6) and unifies the canonicalization. See shared/relay_lifecycle +
    # design-of-record non-boutique-codex-auth-and-lane-liveness-design-2026-07-03.md.
    return relay_value_is_retired(value)


def _relay_is_retired(relay: dict) -> bool:
    return relay_values_are_retired(relay_status_values(relay))


def _relay_status_is_idle(value: object) -> bool | None:
    status = _normalized_status(value)
    if not status:
        return None
    if (
        status in {"queue-dry", "equilibrium", "idle"}
        or _relay_status_is_retired(status)
        or status.startswith("idle-")
    ):
        return True
    if status == "blocked-claim-ownership":
        return True
    if status.startswith("resolved-") or "no-active-claim" in status or "no-task" in status:
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
    try:
        candidates.extend(
            sorted(
                CACHE_DIR.glob(f"cc-active-task-{role}-*"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        )
    except OSError:
        pass
    return list(dict.fromkeys(candidates))


def _active_task_claims_task(role: str, session: str, aliases: set[str]) -> bool:
    for active_task_file in _active_task_candidates(role, session):
        try:
            task_id = active_task_file.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if task_id in aliases:
            return True
    return False


def _lane_claim_cache_ids(role: str, session: str = "") -> tuple[str, ...]:
    claims: set[str] = set()
    for active_task_file in _active_task_candidates(role, session):
        try:
            task_id = active_task_file.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if task_id:
            claims.add(task_id)
    return tuple(sorted(claims))


def _fresh_lane_ownership_blocker(lane: LaneState) -> str:
    """Re-read mutable ownership surfaces at the dispatch mutation moment."""
    if not lane.alive:
        return "lane_projection_changed:alive=false"
    if not lane.dispatchable:
        return "lane_projection_changed:dispatchable=false"
    if not lane.dispatch_ready:
        return "lane_projection_changed:dispatch_ready=false"
    if not lane.idle or lane.claimed_task is not None:
        return f"lane_projection_changed:claimed_task={lane.claimed_task or 'none'}"

    cached_claims = _lane_claim_cache_ids(lane.role, lane.session)
    if cached_claims:
        return "lane_claim_cache_present:" + ",".join(cached_claims)

    relay, _relay_mtime = _load_freshest_relay(lane.role, lane.session)
    relay_claim = _claim_from_relay(relay)
    if relay_claim:
        return f"lane_relay_claim_present:{relay_claim}"
    relay_status = relay.get("status") or relay.get("session_status")
    if _relay_status_is_idle(relay_status) is False:
        return f"lane_relay_not_idle:{_normalized_status(relay_status)}"

    if lane.platform == "claude":
        launcher = _live_headless_launcher(lane.role)
        if launcher is not None and launcher[1]:
            return f"lane_launcher_claim_present:{launcher[1]}"
    return ""


def _refresh_dispatch_lane(lane: LaneState) -> LaneState:
    """Rebuild a lane projection from current discovery inputs before launch."""
    candidates = [
        descriptor
        for descriptor in _discover_lanes()
        if descriptor.role == lane.role
        and descriptor.session == lane.session
        and descriptor.platform == lane.platform
        and (not lane.generation or descriptor.generation == lane.generation)
    ]
    if not candidates:
        return LaneState(
            role=lane.role,
            session=lane.session,
            platform=lane.platform,
            generation=lane.generation,
            alive=False,
            dispatch_ready=False,
            dispatch_blocked_reason="lane_disappeared_before_dispatch",
        )
    refreshed = _check_lane(candidates[0])
    if lane.pid is not None and refreshed.pid != lane.pid:
        return LaneState(
            role=lane.role,
            session=lane.session,
            platform=lane.platform,
            generation=lane.generation,
            alive=False,
            dispatch_ready=False,
            dispatch_blocked_reason="lane_process_replaced_before_dispatch",
        )
    return refreshed


def _relay_mq_db_path() -> Path:
    return Path(
        os.environ.get("HAPAX_RELAY_MQ_DB", str(CACHE_DIR / "relay" / "messages.db"))
    ).expanduser()


def _coord_event_log_from_env() -> CoordEventLog:
    base = coord_base_dir()
    return CoordEventLog(
        db_path=Path(os.environ.get("HAPAX_COORD_LEDGER_DB", str(base / "ledger.db"))),
        jsonl_path=Path(os.environ.get("HAPAX_COORD_JSONL_MIRROR", str(base / "ledger.jsonl"))),
        spool_dir=Path(os.environ.get("HAPAX_COORD_SPOOL_DIR", str(base / "spool"))),
    )


class _CoordinatorDispatchInFlight(RuntimeError):
    def __init__(self, preparation: CoordinatorDispatchPreparation) -> None:
        self.preparation = preparation
        super().__init__(preparation.message_id)


def _parent_spec_sha256(raw_path: str) -> str:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = Path.home() / "Documents" / "Personal" / path
    try:
        if path.is_symlink() or not path.is_file():
            raise OSError("parent spec is not a regular non-symlink file")
        content = path.read_bytes()
    except OSError as exc:
        raise CoordDispatchError("dispatch_parent_spec_preimage_unreadable") from exc
    return hashlib.sha256(content).hexdigest()


def _dispatch_preparation_binding(task: Task, lane: LaneState) -> DispatchPreparationBinding:
    if not task.source_sha256:
        raise CoordDispatchError("dispatch_task_preimage_hash_missing")
    if not lane.generation:
        raise CoordDispatchError("dispatch_lane_generation_missing")
    lane_pid_generation = _pid_generation(lane.pid) if lane.pid is not None else ""
    if lane.pid is not None and not lane_pid_generation:
        raise CoordDispatchError("dispatch_lane_pid_generation_unreadable")
    parent_spec = task.parent_spec or ""
    if not parent_spec:
        raise CoordDispatchError("dispatch_parent_spec_missing")
    claim_hash, relay_hash = lane_ownership_projection_hashes(
        cache_dir=CACHE_DIR,
        relay_dir=RELAY_DIR,
        role=lane.role,
        session=lane.session,
    )
    return DispatchPreparationBinding(
        task_id=task.task_id,
        task_path=str(task.path.resolve()),
        task_sha256=task.source_sha256,
        lane=lane.role,
        lane_session=lane.session,
        lane_generation=lane.generation,
        lane_pid=lane.pid,
        lane_pid_generation=lane_pid_generation,
        claim_projection_sha256=claim_hash,
        relay_projection_sha256=relay_hash,
        platform=lane.platform,
        mode=COORDINATOR_DISPATCH_MODE,
        authority_case=task.authority_case or "",
        authority_item=task.authority_item or task.task_id,
        parent_spec=parent_spec,
        parent_spec_sha256=_parent_spec_sha256(parent_spec),
    )


def _dispatch_binding_for_message(
    message_id: str,
    lane: LaneState,
) -> DispatchPreparationBinding:
    db_path = _relay_mq_db_path()
    if not db_path.exists():
        raise CoordDispatchError("durable_mq_database_missing")
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1.0) as conn:
        row = conn.execute(
            """
            SELECT m.payload, m.payload_hash
            FROM messages m
            JOIN recipients r ON r.message_id = m.message_id
            WHERE m.message_id = :message_id
              AND m.sender = 'hapax-coordinator'
              AND r.recipient = :recipient
            """,
            {
                "message_id": message_id,
                "recipient": lane.role.strip().lower().replace("_", "-"),
            },
        ).fetchone()
    if row is None:
        raise CoordDispatchError("strict_mq_message_id_mismatch")
    payload, payload_hash = row
    if (
        not isinstance(payload, str)
        or not isinstance(payload_hash, str)
        or compute_payload_hash(payload) != payload_hash
    ):
        raise CoordDispatchError("mq_payload_hash_mismatch")
    return dispatch_preparation_binding_from_payload(payload)


def _finalize_dispatch_pickup(
    task: Task,
    lane: LaneState,
    message_id: str | None,
) -> str:
    if not message_id:
        return ""
    if not task.authority_case:
        return "pickup_finalize_authority_case_missing"
    try:
        binding = _dispatch_binding_for_message(message_id, lane)
    except CoordDispatchError as exc:
        return f"pickup_finalize_failed:{exc.reason}"
    request = DispatchLaunchRequest(
        task_id=task.task_id,
        lane=lane.role,
        platform=lane.platform,
        mode=COORDINATOR_DISPATCH_MODE,
        profile=COORDINATOR_DISPATCH_PROFILE,
        authority_case=task.authority_case,
        authority_item=task.authority_item or task.task_id,
        parent_spec=binding.parent_spec,
        message_id=message_id,
        mq_db_path=_relay_mq_db_path(),
        event_log=_coord_event_log_from_env(),
        binding_hash=binding.binding_hash,
        prepared_platform=binding.platform,
        prepared_mode=binding.mode,
    )
    try:
        result = finalize_accepted_dispatch_on_pickup(request)
    except CoordDispatchError as exc:
        return f"pickup_finalize_failed:{exc.reason}"
    except Exception as exc:  # noqa: BLE001 - preserve unexpected finalizer failures.
        return f"pickup_finalize_failed:{type(exc).__name__}:{exc}"
    if not result.launched or result.cleanup_state != "processed":
        return f"pickup_finalize_nonterminal:{result.reason}:{result.cleanup_state}"
    return ""


def _prepare_dispatch_message(task: Task, lane: LaneState) -> str | None:
    if not task.authority_case:
        return None
    db_path = _relay_mq_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    binding = _dispatch_preparation_binding(task, lane)
    payload = json.dumps(
        {
            "dispatch_binding": binding.to_record(),
            "kind": "coordinator_dispatch",
            "task_id": task.task_id,
            "lane": lane.role,
            "platform": lane.platform,
            "mode": COORDINATOR_DISPATCH_MODE,
            "parent_spec": task.parent_spec,
            "next_action_on_binding_failure": (
                "Check HAPAX_RELAY_MQ_DB, relay DB parent permissions, and disk "
                "pressure; then rerun governed methodology dispatch for this task/lane."
            ),
        },
        sort_keys=True,
    )
    preparation = prepare_coordinator_dispatch(
        db_path,
        Envelope(
            sender="hapax-coordinator",
            message_type="dispatch",
            priority=0,
            subject=task.task_id,
            authority_case=task.authority_case,
            authority_item=task.authority_item or task.task_id,
            recipients_spec=lane.role,
            payload=payload,
            tags=["sdlc", "coordinator", "dispatch"],
        ),
    )
    if preparation.state == "accepted":
        raise _CoordinatorDispatchInFlight(preparation)
    return preparation.message_id


def _abort_prepared_dispatch_message(
    message_id: str | None,
    lane: LaneState,
    blocker: str,
) -> str:
    if not message_id:
        return blocker
    observed = coordinator_dispatch_recipient_state(_relay_mq_db_path(), message_id, lane.role)
    if (
        observed is not None
        and observed[0] == "accepted"
        and str(observed[1] or "").startswith("coord_dispatch_accepted:")
    ):
        return f"dispatch_in_flight:{message_id}:pickup_pending"
    try:
        aborted = abort_coordinator_prepared_dispatch(
            _relay_mq_db_path(),
            message_id,
            lane.role,
            blocker,
        )
    except Exception as exc:  # noqa: BLE001 - preserve the failed revocation in refusal evidence.
        log.error("prepared dispatch revocation failed for %s: %s", lane.role, exc)
        return f"{blocker};prepared_mq_abort_failed:{type(exc).__name__}:{exc}"
    if not aborted:
        log.error("prepared dispatch revocation race for %s message=%s", lane.role, message_id)
        return f"{blocker};prepared_mq_abort_not_applied"
    return blocker


def _headless_launcher_matches(argv: list[str], role: str) -> bool:
    return any(Path(arg).name == "hapax-claude-headless" for arg in argv) and role in argv


def _headless_task_from_argv(argv: list[str], role: str) -> str | None:
    if not _headless_launcher_matches(argv, role):
        return None
    task: str | None = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--task" and i + 1 < len(argv):
            task = argv[i + 1].strip()
            i += 2
            continue
        if arg.startswith("--task="):
            task = arg.split("=", 1)[1].strip()
        i += 1
    return task or None


def _read_proc_cmdline(pid: int) -> list[str]:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]


def _pid_is_live(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _pid_dir_for_platform(platform: str) -> Path:
    return CODEX_PID_DIR if platform == "codex" else PID_DIR


def _live_headless_launcher(role: str) -> tuple[int, str | None] | None:
    """Return a live lane launcher even when its pidfile/fifo was lost.

    The dispatch-blocking failure mode is a bash wrapper that still holds the
    lifetime flock but has no ``<lane>.launcher.pid``. Treating that lane as dead
    causes every dispatch attempt to hit the same lock and never reach pickup.
    """

    pidfile = PID_DIR / f"{role}.launcher.pid"
    try:
        pid = int(pidfile.read_text().strip())
    except (OSError, ValueError):
        pid = 0
    if pid > 0 and _pid_is_live(pid):
        argv = _read_proc_cmdline(pid)
        if _headless_launcher_matches(argv, role):
            return pid, _headless_task_from_argv(argv, role)

    proc_root = Path("/proc")
    try:
        pid_dirs = [path for path in proc_root.iterdir() if path.name.isdigit()]
    except OSError:
        return None
    for path in sorted(pid_dirs, key=lambda p: int(p.name)):
        pid = int(path.name)
        argv = _read_proc_cmdline(pid)
        if not argv:
            continue
        if _headless_launcher_matches(argv, role) and _pid_is_live(pid):
            task = _headless_task_from_argv(argv, role)
            return pid, task
    return None


COORDINATOR_DISPATCHABLE_PLATFORMS = dispatch_guards.COORDINATOR_HEADLESS_DISPATCHABLE_PLATFORMS
RETIRED_DISPATCH_PLATFORM_ALIASES = frozenset({"agy", "antigrav", "antigravity", "gemini-cli"})
_DISPATCH_CLOSE_GUARD_MARKERS = dispatch_guards.DISPATCH_CLOSE_GUARD_MARKERS


def _dispatch_worktree(role: str, platform: str) -> Path:
    """Resolve through the shared mapping used by hapax-methodology-dispatch.

    The coordinator must not advertise a lane as dispatch capacity when the
    dispatcher would immediately fail its worktree-local cc-task tool guard.
    ``HAPAX_DISPATCH_WORKTREE`` overrides the resolved worktree outright;
    ``HAPAX_DISPATCH_PROJECT_ROOT`` overrides the root used for lane mappings.
    """
    return dispatch_guards.dispatch_worktree(role, platform)


def _dispatch_tool_next_action(worktree: Path) -> str:
    return (
        f"relaunch or provision the lane with guarded cc-task scripts in {worktree}, "
        "or leave the lane unavailable for dispatch"
    )


def _lane_not_alive_next_action(role: str, platform: str, worktree: Path) -> str:
    if platform not in COORDINATOR_DISPATCHABLE_PLATFORMS:
        supported = ", ".join(COORDINATOR_DISPATCHABLE_PLATFORMS)
        return (
            f"do not count dead {platform!r} lane {role!r} as coordinator headless capacity; "
            f"route work to a supported platform ({supported}) or add coordinator support first"
        )
    return (
        f"start or relaunch lane {role!r} before checking guarded cc-task scripts in {worktree}, "
        "or leave the lane unavailable for dispatch"
    )


def _unsupported_dispatch_platform_next_action(platform: str) -> str:
    if platform.strip().lower() in RETIRED_DISPATCH_PLATFORM_ALIASES:
        return (
            "route work to Claude, Codex, or Vibe; for agy, mint measured supply-leaf intake "
            "with route/resource/governance receipts before any future interactive worker path"
        )
    supported = ", ".join(COORDINATOR_DISPATCHABLE_PLATFORMS)
    return (
        f"route work to a supported coordinator headless platform ({supported}), "
        f"or add coordinator headless dispatch support for {platform!r}"
    )


def _dispatch_tool_block(reason: str, worktree: Path, *, next_action: str | None = None) -> str:
    return f"{reason}; next_action={next_action or _dispatch_tool_next_action(worktree)}"


def _read_dispatch_guard(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _dispatch_tool_blocker(role: str, platform: str) -> str | None:
    worktree = _dispatch_worktree(role, platform)
    if platform not in COORDINATOR_DISPATCHABLE_PLATFORMS:
        return _dispatch_tool_block(
            f"unsupported dispatch platform {platform!r} for coordinator headless dispatch",
            worktree,
            next_action=_unsupported_dispatch_platform_next_action(platform),
        )

    # Intentionally uncached: these scripts are small, lane count is bounded, and
    # worktree guard repairs should affect dispatch readiness on the next tick.
    claim_ok, claim_reason = dispatch_guards.check_worktree_claim_guard(worktree)
    if not claim_ok:
        return _dispatch_tool_block(claim_reason, worktree)

    close = worktree / "scripts" / "cc-close"
    if not close.is_file():
        return _dispatch_tool_block(f"missing cc-close at {close}", worktree)
    try:
        close_text = _read_dispatch_guard(close)
    except OSError as exc:
        return _dispatch_tool_block(f"unreadable cc-close at {close}: {exc}", worktree)
    missing_close = [marker for marker in _DISPATCH_CLOSE_GUARD_MARKERS if marker not in close_text]
    if missing_close:
        return _dispatch_tool_block(
            f"stale cc-close in {worktree}: missing {', '.join(missing_close)}",
            worktree,
        )
    return None


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
        generation=descriptor.generation,
        alive=bool(descriptor.session),
    )
    if descriptor.platform == "claude" and is_claude_operator_pool_role(descriptor.role):
        state.dispatchable = False

    pidfile = _pid_dir_for_platform(descriptor.platform) / f"{descriptor.role}.pid"
    if pidfile.exists():
        try:
            pid = int(pidfile.read_text().strip())
            if not _pid_is_live(pid):
                raise OSError
            state.alive = True
            state.pid = pid
            state.pid_source = "pidfile"
        except (ValueError, OSError):
            pass

    if descriptor.platform == "claude":
        launcher = _live_headless_launcher(descriptor.role)
        if launcher is not None:
            launcher_pid, launcher_task = launcher
            state.alive = True
            if state.pid is None:
                state.pid = launcher_pid
                state.pid_source = "proc"
            if launcher_task and not state.claimed_task:
                state.claimed_task = launcher_task
                state.idle = False

    relay, relay_mtime = _load_freshest_relay(descriptor.role, descriptor.session)
    if relay_mtime is not None:
        state.relay_age_s = time.time() - relay_mtime

    if relay:
        relay_status = relay.get("status") or relay.get("session_status")
        if _relay_is_retired(relay):
            state.dispatchable = False
        relay_claim = _claim_from_relay(relay)
        if relay_claim:
            state.claimed_task = relay_claim
            state.idle = False
        relay_idle = _relay_status_is_idle(relay_status)
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

    if not state.alive:
        state.dispatch_ready = False
        worktree = _dispatch_worktree(state.role, state.platform)
        state.dispatch_blocked_reason = _dispatch_tool_block(
            "lane_not_alive",
            worktree,
            next_action=_lane_not_alive_next_action(state.role, state.platform, worktree),
        )
    else:
        blocker = _dispatch_tool_blocker(state.role, state.platform)
        if blocker:
            state.dispatch_ready = False
            state.dispatch_blocked_reason = blocker

    return state


def _launcher_pid_present(role: str, *, platform: str = "claude") -> bool:
    """True iff the supervising launcher PID for this lane is alive. Uses os.kill(pid, 0) —
    a liveness probe only (signal 0 delivers nothing); NEVER os.killpg or a real signal."""
    try:
        pid = int((_pid_dir_for_platform(platform) / f"{role}.launcher.pid").read_text().strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _lane_launcher_process_present(lane: LaneState) -> bool:
    if lane.pid is not None and _pid_is_live(lane.pid):
        return True
    if _launcher_pid_present(lane.role, platform=lane.platform):
        return True
    return lane.platform == "claude" and _live_headless_launcher(lane.role) is not None


def _lane_owner_present(lane: LaneState) -> bool:
    if lane.session:
        return True
    return _lane_launcher_process_present(lane)


def _dispatch_landed(task: Task, lane: LaneState, message_id: str | None = None) -> bool:
    if not message_id:
        return False
    observed = _refresh_dispatch_lane(lane)
    if not observed.alive or observed.dispatch_blocked_reason:
        return False
    try:
        snapshot = resolve_task_note(TASKS_DIR.parent, task.task_id, state="active")
        binding = load_claim_dispatch_binding(claim_dispatch_binding_path(CACHE_DIR, observed.role))
        expected_binding = _dispatch_binding_for_message(message_id, lane)
        parent_spec_sha256 = _parent_spec_sha256(expected_binding.parent_spec)
    except (TaskStoreError, CoordDispatchError):
        return False
    fields = snapshot.frontmatter
    status = str(fields.get("status") or "").strip().lower()
    owner = _normalized_task_owner(str(fields.get("assigned_to") or ""))
    authority_case = str(fields.get("authority_case") or "").strip()
    parent_spec = str(fields.get("parent_spec") or "").strip()
    recipient_state = coordinator_dispatch_recipient_state(
        _relay_mq_db_path(),
        message_id,
        observed.role,
    )
    if (
        snapshot.path != task.path.resolve()
        or expected_binding.task_path != str(task.path.resolve())
        or expected_binding.task_sha256 != task.source_sha256
        or status not in {"claimed", "in_progress"}
        or not _owner_matches_lane(owner, observed)
        or authority_case != (task.authority_case or "")
        or parent_spec != (task.parent_spec or "")
        or parent_spec_sha256 != expected_binding.parent_spec_sha256
        or binding.task_id != task.task_id
        or binding.lane != observed.role
        or binding.dispatch_message_id != message_id
        or binding.authority_case != authority_case
        or binding.binding_hash != expected_binding.binding_hash
        or not binding.coord_dispatch_idempotency_key
        or recipient_state
        != (
            "accepted",
            f"{COORDINATOR_ACCEPTED_DISPATCH_REASON_PREFIX}"
            f"{binding.coord_dispatch_idempotency_key}",
        )
    ):
        return False
    epoch_path = CACHE_DIR / f"cc-claim-epoch-{observed.role}"
    try:
        epoch_text, epoch_task = epoch_path.read_text(encoding="utf-8").split()
    except (OSError, ValueError):
        return False
    return (
        epoch_text.isdigit()
        and int(epoch_text) == binding.claim_epoch
        and epoch_task == task.task_id
        and observed.claimed_task == task.task_id
        and _active_task_claims_task(observed.role, observed.session, {task.task_id})
        and _lane_launcher_process_present(observed)
    )


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
    fixed STALL_OUTPUT_GRACE_S. This is an observation threshold only."""
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

    A lane is stalled iff it owns a non-terminal task and either its supervising
    launcher is gone or its progress signal is stale. This observation never
    authorizes changing task status or owner.
    """
    claim = lane.claimed_task
    if not claim or claim not in non_terminal_task_ids:
        return False  # idle, or the claim is already terminal → not stalled
    if not _lane_owner_present(lane):
        return True  # owner process gone, task still non-terminal
    if lane.platform == "claude" and lane.pid_source == "proc":
        return False  # pidfile-free launcher is live; supervisor owns any later recovery.
    return lane.output_age_s > output_grace_s


def _lane_to_dict(lane: LaneState) -> dict:
    return {
        "role": lane.role,
        "session": lane.session,
        "platform": lane.platform,
        "generation": lane.generation or None,
        "alive": lane.alive,
        "pid": lane.pid,
        "pid_source": lane.pid_source,
        "relay_age_s": round(lane.relay_age_s, 1) if lane.relay_age_s != float("inf") else None,
        "claimed_task": lane.claimed_task,
        "idle": lane.idle,
        "dispatchable": _lane_dispatchable(lane),
        "stalled": lane.stalled,
        "dispatch_ready": lane.dispatch_ready,
        "dispatch_blocked_reason": lane.dispatch_blocked_reason,
        "task_ssot_claims": list(lane.task_ssot_claims),
        "output_age_s": round(lane.output_age_s, 1) if lane.output_age_s != float("inf") else None,
    }
