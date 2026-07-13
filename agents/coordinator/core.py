"""Core coordinator logic - task queue, lane health, and held dispatch candidates."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import subprocess
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

import yaml

from agents.coordinator.refusal_ledger import DispatchRefusalLedger
from shared import sdlc_dispatch_guards as dispatch_guards
from shared.coord_event_log import default_event_log
from shared.coord_projection import (
    capture_coord_replay_snapshot,
    inspect_lifecycle_transactions,
)
from shared.dispatch_service_time import (
    AGE_NORM_S,
    QueueLane,
    QueueTask,
    is_claude_operator_pool_role,
    parse_ts,
    plan_dispatches,
)
from shared.dispatcher_policy import LOCAL_DEV_TARGET
from shared.methodology_dispatch_carrier import (
    MethodologyDispatchCarrierError,
    validate_methodology_dispatch_carrier_line,
)
from shared.relay_lifecycle import (
    parse_relay_document,
    relay_status_values,
    relay_value_is_retired,
    relay_values_are_retired,
)
from shared.relay_mq import (
    CanonEchoError,
    CanonEchoReconciliation,
    reconcile_canon_echo,
    resolve_claim_bound_canon_position,
)
from shared.route_metadata_schema import (
    RouteMetadataStatus,
    assess_route_metadata,
    route_metadata_payload_from_frontmatter,
)
from shared.sdlc_claim import (
    ClaimPublicationError,
    inspect_claim_publications,
    resolve_applied_claim_publication_for_task,
)
from shared.sdlc_lifecycle import TASK_TERMINAL_STATUSES, stage_token
from shared.sdlc_pressure_gate import observe_admission_state
from shared.sdlc_task_store import (
    TaskIdentityIndex,
    TaskStoreError,
    assess_task_identity_index,
    build_task_identity_index,
    validate_task_identity_index,
)

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
    """Hold legacy notification escalation at the protected effect boundary."""
    log.warning(
        "notification HOLD: title_length=%d body_length=%d",
        len(title),
        len(body),
    )


def _queue_task_routable(task: QueueTask, lane: QueueLane) -> bool:
    platforms = {platform.lower() for platform in task.platform_suitability}
    return "any" in platforms or lane.platform.lower() in platforms


TASKS_DIR = Path.home() / "Documents/Personal/20-projects/hapax-cc-tasks/active"
CACHE_DIR = Path.home() / ".cache/hapax"
RELAY_DIR = CACHE_DIR / "relay"
PID_DIR = Path(f"/run/user/{os.getuid()}/hapax-claude")
CODEX_PID_DIR = Path(f"/run/user/{os.getuid()}/hapax-codex")
SHM_DIR = Path("/dev/shm/hapax-coordinator")
SHM_FILE = SHM_DIR / "state.json"
REPO_ROOT = Path(__file__).resolve().parents[2]

# The same authority-case ledger cc-stage-advance writes — one SSOT for transitions.
# Honor the same env override so both producers target the same inode.
REOFFER_LEDGER = Path(
    os.environ.get("HAPAX_AUTHORITY_CASE_LEDGER", str(CACHE_DIR / "authority-case-ledger.jsonl"))
).expanduser()

FALLBACK_LANE_ROLES = (
    "alpha",
    "beta",
    "gamma",
    "delta",
    "epsilon",
    "zeta",
    "eta",
    "theta",
)
LANE_ROLES = FALLBACK_LANE_ROLES
SESSION_PREFIXES = (
    ("hapax-claude-", "claude"),
    ("hapax-codex-", "codex"),
    ("hapax-gemini-", "gemini"),
)
DISPATCH_COOLDOWN_S = 120.0
MAX_HELD_CANDIDATES_PER_TICK = 1
DISPATCH_TIMEOUT_S = _positive_env_float("HAPAX_COORDINATOR_DISPATCH_TIMEOUT_S", 30.0)
ORPHAN_CLAIM_REOFFER_GRACE_S = _positive_env_float(
    "HAPAX_COORDINATOR_ORPHAN_CLAIM_REOFFER_GRACE_S", 300.0
)
MAX_ORPHAN_CLAIM_REOFFERS_PER_TICK = 5
COORDINATOR_DISPATCH_MODE = "headless"
COORDINATOR_DISPATCH_PROFILE = "full"
SUPPORTED_DISPATCH_PLATFORMS = ("claude", "codex", "gemini", "vibe", "api")

# Gate-0A has one repository-bound methodology intake path. Runtime-selected
# executors belong behind the authenticated Gate-0B registry, never in an env var.
METHODOLOGY_DISPATCHER = REPO_ROOT / "scripts" / "hapax-methodology-dispatch"
METHODOLOGY_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
TMUX_EXECUTABLE = Path("/usr/bin/tmux")

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
# Intake fit-shadow: blend the demand-shape fit_score into the dispatch rank-key.
# Default 0.0 => composite short-circuits to wsjf_effective (byte-identical plan, the
# golden guarantee); a non-zero value (positive OR negative) is the operator's dial.
INTAKE_FIT_BLEND_ENV = "HAPAX_INTAKE_FIT_BLEND"
CANON_ECHO_ENFORCEMENT_ENV = "HAPAX_CANON_ECHO_ENFORCEMENT"


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
    stage: str | None = None
    frontmatter: dict[str, object] = field(default_factory=dict, compare=False)


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
    pid_source: str | None = None
    relay_age_s: float = float("inf")
    claimed_task: str | None = None
    idle: bool = True
    dispatchable: bool = True
    output_age_s: float = float("inf")  # age of the freshest progress signal
    stalled: bool = False  # ground-truth projection, re-derived each tick
    dispatch_ready: bool = True
    dispatch_blocked_reason: str | None = None


def _lane_dispatchable(lane: LaneState) -> bool:
    if not lane.dispatchable:
        return False
    return not (lane.platform.lower() == "claude" and is_claude_operator_pool_role(lane.role))


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
    pressure_observation: dict[str, object] | None = None
    task_store_observation: dict[str, object] | None = None


@dataclass(frozen=True)
class CanonEchoPass:
    blocked_count: int = 0
    held_task_ids: frozenset[str] = frozenset()


class DispatchDisposition(StrEnum):
    HELD_CANDIDATE = "held_candidate"
    REFUSED = "refused"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class MethodologyDispatchResult:
    disposition: DispatchDisposition
    reason: str
    carrier_ref: str | None = None


def _methodology_dispatch_result(
    disposition: DispatchDisposition,
    reason: str,
    carrier: dict[str, object] | None = None,
) -> MethodologyDispatchResult:
    carrier_ref = carrier.get("carrier_ref") if carrier is not None else None
    return MethodologyDispatchResult(
        disposition=disposition,
        reason=reason,
        carrier_ref=carrier_ref if isinstance(carrier_ref, str) else None,
    )


def _parse_methodology_dispatch_carrier(
    stdout: bytes,
    *,
    task_id: str,
    lane: str,
    platform: str,
    mode: str,
    profile: str,
) -> MethodologyDispatchResult:
    """Validate and classify the dispatcher's sole content-addressed carrier.

    Process status and pickup probes are not admission evidence. Only one carrier
    with the exact invocation identity and a valid self-hash can classify the
    result. Unknown state combinations remain indeterminate rather than being
    inferred as success or refusal.
    """

    try:
        carrier = validate_methodology_dispatch_carrier_line(
            stdout,
            task_id=task_id,
            lane=lane,
            platform=platform,
            mode=mode,
            profile=profile,
        )
    except MethodologyDispatchCarrierError as exc:
        return _methodology_dispatch_result(
            DispatchDisposition.INDETERMINATE,
            exc.reason_code,
        )
    return _methodology_dispatch_result(
        DispatchDisposition.HELD_CANDIDATE,
        "methodology_candidate_held_not_admitted",
        carrier,
    )


class Coordinator:
    """Main coordinator — scans tasks, checks lanes, dispatches work."""

    def __init__(self) -> None:
        # per-task-lifetime reoffer counter (process-local); caps the
        # offered→claim→stall→offered loop and escalates to `blocked` past the cap.
        self._reoffer_counts: dict[str, int] = {}
        # No-spin law: refusal ledger tracks (task, lane, reason) triples and
        # enters cooldown after K identical deterministic refusals.
        self._refusal_ledger = DispatchRefusalLedger(
            _escalate_fn=_ntfy_escalate,
        )
        self._task_identity_index: TaskIdentityIndex | None = None
        self._task_store_observation: dict[str, object] | None = None

    def _recover_canon_transactions(self) -> bool:
        if os.environ.get(CANON_ECHO_ENFORCEMENT_ENV) != "1":
            return True
        event_log = default_event_log()
        lifecycle_inspection = inspect_lifecycle_transactions(
            event_plane_snapshot=capture_coord_replay_snapshot(event_log)
        )
        if not lifecycle_inspection.estate_complete:
            log.critical(
                "canonical transition inspection HOLD: %s",
                ",".join(lifecycle_inspection.reason_codes),
            )
            return False
        claim_inspections = inspect_claim_publications(cache_dir=CACHE_DIR)
        held_claims = [item for item in claim_inspections if item.disposition == "hold"]
        if held_claims:
            log.critical(
                "canonical claim inspection HOLD: %s",
                ",".join(f"{item.publication_id}:{item.reason_code}" for item in held_claims),
            )
            return False
        return True

    def _reconcile_canon_echoes(
        self, tasks: list[Task], lanes: dict[str, LaneState]
    ) -> CanonEchoPass:
        if os.environ.get(CANON_ECHO_ENFORCEMENT_ENV) != "1":
            return CanonEchoPass()
        blocked = 0
        held: set[str] = set()
        for task in tasks:
            if task.status not in {"claimed", "in_progress"}:
                continue
            if not task.assigned_to or task.assigned_to == "unassigned":
                held.add(task.task_id)
                continue
            lane = lanes.get(task.assigned_to) or LaneState(
                role=task.assigned_to,
                alive=False,
                claimed_task=task.task_id,
                idle=False,
                dispatchable=False,
                dispatch_ready=False,
            )
            try:
                reconciliation, transaction_id = _reconcile_task_canon_echo(task, lane)
            except (CanonEchoError, OSError, RuntimeError, ValueError) as exc:
                held.add(task.task_id)
                lane.dispatch_ready = False
                lane.dispatch_blocked_reason = getattr(
                    exc, "reason_code", "canon_echo_reconciliation_failed"
                )
                log.warning(
                    "canon echo reconciliation held task=%s lane=%s: %s",
                    task.task_id,
                    lane.role,
                    exc,
                )
                continue
            if reconciliation.action != "grounded":
                lane.dispatch_ready = False
                lane.dispatch_blocked_reason = reconciliation.reason_code
            if transaction_id is not None:
                blocked += 1
                log.error(
                    "canon echo failed twice: task=%s lane=%s transaction=%s -> BLOCKED",
                    task.task_id,
                    lane.role,
                    transaction_id,
                )
            elif reconciliation.action != "grounded":
                held.add(task.task_id)
        return CanonEchoPass(blocked, frozenset(held))

    def tick(self) -> None:
        if not self._recover_canon_transactions():
            return
        tasks = self._scan_tasks()
        lanes = self._check_lanes()
        echo_pass = self._reconcile_canon_echoes(tasks, lanes)
        if echo_pass.blocked_count:
            tasks = self._scan_tasks()
        # Observe pressure on the dispatch target, not the local box. This is a
        # read-only support signal and cannot change candidate calculation.
        admission = observe_admission_state(target_host=LOCAL_DEV_TARGET)
        # Ambient liveness cannot release ownership. Claim release is a protected
        # lifecycle operation and remains held until the execution composition
        # supplies an exact current lease and authenticated outcome path.
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
            task_store_observation=self._task_store_observation,
        )

        idle_lanes = [
            l
            for l in lanes.values()
            if l.alive
            and l.idle
            and l.claimed_task is None
            and l.dispatch_ready
            and _lane_dispatchable(l)
        ]

        # Candidate calculation is bounded but effect-pure. Ambient pressure is
        # support evidence for a later admission decision; it cannot suppress or
        # authorize intake before a current execution composition exists.
        cooldown_s = 0.0
        max_dispatches = min(len(idle_lanes), MAX_HELD_CANDIDATES_PER_TICK)
        state.pressure_observation = {
            "admission_state": admission.state,
            "reasons": list(getattr(admission, "reasons", []) or []),
            "candidate_influence": "none",
            "may_authorize": False,
        }

        # Service-time evidence is a support projection, never dispatch authority.
        # Keep the compatibility planner flag stable while refusing ambient cache
        # influence over candidate ordering or lifecycle effects.
        legacy = False
        # bb-intake-fit-shadow: blend the demand-shape fit_score into the dispatch
        # rank-key. Default 0.0 => byte-identical to pure WSJF (the golden guarantee).
        fit_blend = _env_float(INTAKE_FIT_BLEND_ENV, 0.0)
        cache = None

        # Project ground-truth `stalled` for every lane, then reoffer held tasks off
        # stalled lanes — bounded, and gated on the SAME #3850 admission read. 'closed'
        # reoffers nothing (the held task stays offered — queued, never dropped). Runs
        # before the dispatch loop so a just-freed lane re-enters the pool next tick.
        # The stall grace is now the MEASURED tau(lineage) when the cache is present
        # (one timeout, not three divergent fixed numbers); 900s fallback when blind.
        reofferable_claim_ids = frozenset(
            alias
            for task in tasks
            if task.status in {"claimed", "in_progress"}
            and task.task_id not in echo_pass.held_task_ids
            for alias in (task.task_id, task.path.stem)
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
        # loop. The Gate-0A candidate ceiling remains fixed and pressure-independent.
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
                cooldown_remaining_s=cooldown_s,
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
        non_escalating_dispatch_ids: set[str] = set()
        for task_id, role in plan:
            task = task_by_id.get(task_id)
            lane = lane_by_role.get(role)
            if task is None or lane is None:
                continue
            dispatch_result = self._dispatch(task, lane)
            if dispatch_result.disposition is DispatchDisposition.REFUSED:
                self._refusal_ledger.record_refusal(
                    task_id,
                    role,
                    dispatch_result.reason,
                    now=now_mono,
                )
            else:
                # A held candidate or an unproven process outcome is neither a
                # refusal nor an actionable starvation signal.
                non_escalating_dispatch_ids.add(task_id)

        # No Gate-0A result can attest a domain effect. Gate-0B must consume an
        # authenticated OutcomeReceipt before this telemetry can become non-zero.
        state.dispatches_this_tick = 0
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
        non_escalating_offered = sum(
            1 for task in offered if task.task_id in non_escalating_dispatch_ids
        )
        starvation_capacity = bool(idle_lanes)
        uncooled_offered = max(
            0,
            len(offered) - cooled_offered - non_escalating_offered,
        )
        starvation_offered = uncooled_offered if starvation_capacity else 0
        self._refusal_ledger.tick_starvation(starvation_offered, 0, now=now_mono)

        # Surface refusal stats in SHM.
        refusal_stats = self._refusal_ledger.stats()
        self._write_state(state, refusal_stats=refusal_stats)

        log.info(
            "tick: offered=%d idle_lanes=%d dispatched=%d alive=%d/%d cooled=%d skipped=%d",
            len(offered),
            state.lanes_idle,
            0,
            state.lanes_alive,
            state.lanes_total,
            refusal_stats.get("cooled_down", 0),
            skipped_cooldown,
        )

    def _scan_tasks(self) -> list[Task]:
        def hold_task_store_error(
            exc: TaskStoreError,
            *,
            index: TaskIdentityIndex | None = None,
        ) -> list[Task]:
            observation: dict[str, object] = {
                "disposition": "hold",
                "reason_code": exc.reason_code,
                "detail": exc.detail,
                "evidence_refs": list(exc.evidence_refs),
                "source_ref": str(TASKS_DIR.parent),
                "candidate_count": 0,
                "no_effect": True,
                "may_authorize": False,
            }
            if index is not None:
                observation["frontier_ref"] = (
                    f"task-identity-index-frontier@sha256:{index.frontier_hash}"
                )
            self._task_store_observation = observation
            log.critical("task identity index HOLD: %s", exc)
            return []

        if not TASKS_DIR.is_dir():
            self._task_identity_index = None
            self._task_store_observation = {
                "disposition": "hold",
                "reason_code": "task_store_active_directory_missing",
                "source_ref": str(TASKS_DIR),
                "may_authorize": False,
            }
            return []
        vault_root = TASKS_DIR.parent
        try:
            if (
                self._task_identity_index is None
                or self._task_identity_index.vault_root != vault_root.resolve()
            ):
                index = build_task_identity_index(vault_root)
            else:
                validate_task_identity_index(self._task_identity_index)
                index = self._task_identity_index
        except TaskStoreError as exc:
            stale_index = self._task_identity_index
            self._task_identity_index = None
            return hold_task_store_error(exc, index=stale_index)

        self._task_identity_index = index
        assessment = assess_task_identity_index(index)
        classified_legacy_paths = {
            snapshot.relative_path for snapshot in assessment.legacy_snapshots
        }
        duplicate_task_ids = sorted(
            task_id for task_id, entries in index.by_task_id.items() if len(entries) > 1
        )
        unbound_refs = [
            entry.path.relative_to(index.vault_root).as_posix()
            for entry in index.unbound_entries
            if entry.path.relative_to(index.vault_root).as_posix()
            not in classified_legacy_paths
        ]
        tasks: list[Task] = []
        parse_refused_refs: list[str] = []
        for task_id, entries in index.by_task_id.items():
            if len(entries) != 1 or entries[0].state != "active":
                continue
            task = _parse_task(entries[0].path)
            if task is None or task.task_id != task_id:
                parse_refused_refs.append(entries[0].path.relative_to(index.vault_root).as_posix())
                continue
            tasks.append(task)
        try:
            validate_task_identity_index(index)
        except TaskStoreError as exc:
            self._task_identity_index = None
            return hold_task_store_error(exc, index=index)
        hold = bool(duplicate_task_ids or unbound_refs or parse_refused_refs)
        self._task_store_observation = {
            "disposition": "hold" if hold else "current",
            "reason_code": "task_store_integrity_hold" if hold else None,
            "frontier_ref": f"task-identity-index-frontier@sha256:{index.frontier_hash}",
            "assessment_ref": (
                f"task-store-assessment@sha256:{assessment.assessment_hash}"
            ),
            "blocking_unbound_refs": list(assessment.blocking_unbound_refs),
            "duplicate_task_ids": duplicate_task_ids,
            "legacy_snapshots": [
                snapshot.to_record() for snapshot in assessment.legacy_snapshots
            ],
            "unbound_refs": unbound_refs,
            "parse_refused_refs": parse_refused_refs,
            "candidate_count": 0 if hold else len(tasks),
            "no_effect": True,
            "may_authorize": False,
        }
        if hold:
            log.critical(
                "task store integrity HOLD: duplicates=%d unbound=%d parse_refused=%d",
                len(duplicate_task_ids),
                len(unbound_refs),
                len(parse_refused_refs),
            )
            return []
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
        """Preserve pure candidates without refusal-ledger reranking or effects."""
        del queue_tasks, queue_lanes, age_norm_s, now_mono, fit_blend
        return list(plan), 0

    def _dispatch(self, task: Task, lane: LaneState) -> MethodologyDispatchResult:
        """Request methodology carriage without inferring an effect from the process."""
        dispatcher = METHODOLOGY_DISPATCHER
        if not dispatcher.is_file() or dispatcher.is_symlink():
            log.warning("hapax-methodology-dispatch not found, cannot dispatch to %s", lane.role)
            return _methodology_dispatch_result(
                DispatchDisposition.INDETERMINATE,
                "dispatcher_not_found",
            )
        project_python = METHODOLOGY_PYTHON
        if not project_python.is_file() or not os.access(project_python, os.X_OK):
            log.warning("pinned methodology interpreter unavailable")
            return _methodology_dispatch_result(
                DispatchDisposition.INDETERMINATE,
                "methodology_interpreter_not_found",
            )

        cmd = [
            str(project_python),
            "-I",
            str(dispatcher),
            "--task",
            task.task_id,
            "--lane",
            lane.role,
            "--platform",
            lane.platform,
            "--mode",
            COORDINATOR_DISPATCH_MODE,
            "--profile",
            COORDINATOR_DISPATCH_PROFILE,
            "--launch",
        ]

        child_env = os.environ.copy()
        child_env.pop("PYTHONPATH", None)
        child_env.pop("PYTHONHOME", None)
        try:
            result = subprocess.run(
                cmd,
                timeout=DISPATCH_TIMEOUT_S,
                capture_output=True,
                env=child_env,
            )
        except subprocess.TimeoutExpired as exc:
            pickup_observed = _dispatch_landed(task, lane)
            log.warning(
                "Dispatch to %s timed out; pickup_observed=%s is diagnostic only: %s",
                lane.role,
                pickup_observed,
                exc,
            )
            timeout_stdout = exc.stdout or b""
            return _parse_methodology_dispatch_carrier(
                timeout_stdout,
                task_id=task.task_id,
                lane=lane.role,
                platform=lane.platform,
                mode=COORDINATOR_DISPATCH_MODE,
                profile=COORDINATOR_DISPATCH_PROFILE,
            )
        except OSError as exc:
            log.warning("Dispatch to %s failed: %s", lane.role, exc)
            return _methodology_dispatch_result(
                DispatchDisposition.INDETERMINATE,
                f"dispatcher_oserror:{type(exc).__name__}",
            )

        dispatch_result = _parse_methodology_dispatch_carrier(
            result.stdout,
            task_id=task.task_id,
            lane=lane.role,
            platform=lane.platform,
            mode=COORDINATOR_DISPATCH_MODE,
            profile=COORDINATOR_DISPATCH_PROFILE,
        )
        log.warning(
            "Methodology dispatch task=%s lane=%s disposition=%s reason=%s process_returncode=%d",
            task.task_id,
            lane.role,
            dispatch_result.disposition.value,
            dispatch_result.reason,
            result.returncode,
        )
        return dispatch_result

    def _reoffer_stalled(self, lane: LaneState) -> bool:
        """Hold stalled-claim release before every lifecycle or filesystem effect."""
        claim = lane.claimed_task
        if not claim:
            return False
        log.warning(
            "claim release HOLD: stalled task=%s lane=%s requires a valid authority "
            "grant, admission decision, and exact execution lease",
            claim,
            lane.role,
        )
        return False

    def _escalate_stalled(self, lane: LaneState, claim: str, path: Path, text: str) -> bool:
        """Hold task blocking and notification; liveness never grants either effect."""
        del path, text
        log.warning(
            "stalled escalation HOLD: task=%s lane=%s requires a valid authority "
            "grant, admission decision, and exact execution lease",
            claim,
            lane.role,
        )
        return False

    def _clear_claim_signal(self, lane: LaneState, task_id: str) -> None:
        """Hold claim-file deletion; only the admitted claim adapter may clear it."""
        log.warning(
            "claim signal clear HOLD: task=%s lane=%s",
            task_id,
            lane.role,
        )

    def _clear_claim_signal_for_task(self, role: str, session: str, aliases: set[str]) -> None:
        """Hold orphan claim-file deletion at the same protected boundary."""
        log.warning(
            "claim signal clear HOLD: aliases=%s lane=%s session=%s",
            ",".join(sorted(aliases)),
            role,
            session,
        )

    def _reoffer_orphaned_claims(
        self,
        tasks: Sequence[Task],
        lanes: dict[str, LaneState],
        *,
        now_wall: float,
        held_task_ids: frozenset[str] = frozenset(),
    ) -> int:
        """Expose no release effect from orphan observations at Gate-0A."""
        del tasks, lanes, now_wall, held_task_ids
        log.warning(
            "orphan claim release HOLD: valid authority, admission, and an exact "
            "execution lease are required"
        )
        return 0

    def _reoffer_orphaned_claim(self, task: Task, lanes: dict[str, LaneState]) -> bool:
        """Hold one orphan release without reading or mutating its task note."""
        del lanes
        log.warning(
            "orphan claim release HOLD: task=%s lane=%s",
            task.task_id,
            task.assigned_to,
        )
        return False

    @staticmethod
    def _claim_release_requires_governance(role: str) -> bool:
        del role
        return True

    def _emit_reoffer_ledger(
        self, lane: LaneState, task_id: str, *, kind: str, to_stage: str
    ) -> None:
        """Hold legacy transition publication; observations cannot append events."""
        log.warning(
            "reoffer event HOLD: task=%s lane=%s kind=%s requested_stage=%s",
            task_id,
            lane.role,
            kind,
            to_stage,
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
            "task_status_counts": state.task_status_counts,
            "task_flow_counts": state.task_flow_counts,
            "lanes": state.lanes,
        }
        if state.pressure_observation:
            payload["pressure_observation"] = state.pressure_observation
        if state.task_store_observation:
            payload["task_store_observation"] = state.task_store_observation
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
    status = str(meta.get("status", "")).strip().lower()
    if status in TASK_TERMINAL_STATUSES:
        return None
    platforms = meta.get("platform_suitability", ["any"])
    if isinstance(platforms, str):
        platforms = [platforms]
    platforms = _effective_platform_suitability(platforms, meta)
    return Task(
        task_id=_frontmatter_text(meta.get("task_id")) or path.stem,
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
        stage=_frontmatter_text(meta.get("stage")),
        frontmatter={str(key): value for key, value in meta.items()},
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


def _is_p0_or_remediation_task(task: Task) -> bool:
    return task.priority == "p0" or _is_remediation_task(task)


def _task_claim_age_s(task: Task, *, now_wall: float) -> float:
    if task.claimed_at is not None:
        return max(0.0, now_wall - task.claimed_at)
    try:
        return max(0.0, now_wall - task.path.stat().st_mtime)
    except OSError:
        return float("inf")


def _task_has_live_pickup(task: Task, lanes: dict[str, LaneState]) -> bool:
    if task.assigned_to.strip().lower() in {"", "null", "none", "~", "unassigned"}:
        return False
    lane = lanes.get(task.assigned_to)
    if lane is None or not lane.alive:
        return False
    aliases = {task.task_id, task.path.stem}
    return lane.claimed_task in aliases and _lane_owner_present(lane)


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
    lanes_by_role: dict[str, LaneDescriptor] = {
        role: LaneDescriptor(role=role, session="", platform="claude")
        for role in FALLBACK_LANE_ROLES
    }
    proc = None
    if TMUX_EXECUTABLE.is_file() and os.access(TMUX_EXECUTABLE, os.X_OK):
        try:
            proc = subprocess.run(
                [
                    str(TMUX_EXECUTABLE),
                    "-f",
                    "/dev/null",
                    "list-sessions",
                    "-F",
                    "#{session_name}",
                ],
                timeout=5,
                capture_output=True,
                text=True,
                check=False,
                env={"HOME": "/nonexistent", "LANG": "C.UTF-8", "PATH": "/usr/bin:/bin"},
            )
        except (subprocess.TimeoutExpired, OSError):
            proc = None
    if proc is not None and proc.returncode == 0:
        for line in proc.stdout.splitlines():
            descriptor = _lane_from_tmux_session(line.strip())
            if descriptor is not None:
                lanes_by_role[descriptor.role] = descriptor

    for pid_dir, platform in ((PID_DIR, "claude"), (CODEX_PID_DIR, "codex")):
        try:
            pid_paths = list(pid_dir.glob("*.pid"))
        except OSError:
            pid_paths = []
        for path in pid_paths:
            name = path.name
            if name.endswith(".launcher.pid"):
                role = name.removesuffix(".launcher.pid")
            else:
                role = name.removesuffix(".pid")
            if role:
                lanes_by_role.setdefault(
                    role,
                    LaneDescriptor(role=role, session="", platform=platform),
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
    return status in {
        "active",
        "executing",
        "claimed",
        "in-progress",
        "working",
    } or any(token in status for token in ("active-claim", "in-progress", "working"))


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
    if status in {
        "active",
        "executing",
        "claimed",
        "in-progress",
        "working",
        "retiring",
    }:
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


def _relay_mq_db_path() -> Path:
    return Path(
        os.environ.get("HAPAX_RELAY_MQ_DB", str(CACHE_DIR / "relay" / "messages.db"))
    ).expanduser()


@lru_cache(maxsize=16)
def _render_expected_canon_payload(
    canon_hash: str,
    image_hash: str,
    stage: str,
    level: str,
    payload_sha256: str,
) -> str:
    try:
        from shared.session_context_canon import build_canon_bundle

        bundle = build_canon_bundle()
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        raise CanonEchoError(
            "canon_echo_repair_materialization_failed",
            "restore the checked canon sources, encoder, and package dependencies",
            str(exc),
        ) from exc
    if bundle.canon_hash != canon_hash:
        raise CanonEchoError(
            "canon_echo_repair_canon_hash_mismatch",
            "restore the canon committed by the dispatch receipt",
        )
    image = next(
        (item for item in bundle.images if item.stage_token == stage and item.level.value == level),
        None,
    )
    if (
        image is None
        or image.image_hash != image_hash
        or hashlib.sha256(image.rendered_payload.encode("utf-8")).hexdigest() != payload_sha256
    ):
        raise CanonEchoError(
            "canon_echo_repair_image_mismatch",
            "restore the exact same-level image committed by the dispatch receipt",
        )
    return image.rendered_payload


def _reconcile_task_canon_echo(
    task: Task,
    lane: LaneState,
    *,
    db_path: Path | None = None,
    ledger_path: Path | None = None,
    now: datetime | None = None,
) -> tuple[CanonEchoReconciliation, str | None]:
    del ledger_path
    relay_db = db_path or _relay_mq_db_path()
    event_log = default_event_log()
    lifecycle_inspection = inspect_lifecycle_transactions(
        task_id=task.task_id,
        event_plane_snapshot=capture_coord_replay_snapshot(event_log),
    )
    if not lifecycle_inspection.scope_complete:
        raise CanonEchoError(
            "canon_transition_inspection_hold",
            "reconcile the inspected transition frontier before Echo reconciliation",
            ",".join(lifecycle_inspection.reason_codes),
        )
    try:
        applied_claim = resolve_applied_claim_publication_for_task(
            vault_root=TASKS_DIR.parent,
            cache_dir=CACHE_DIR,
            role=lane.role,
            task_id=task.task_id,
        )
        snapshot = applied_claim.current_task
        leases = applied_claim.leases
    except (ClaimPublicationError, TaskStoreError) as exc:
        raise CanonEchoError(exc.reason_code, exc.repair_action, exc.detail) from exc
    frontmatter = snapshot.frontmatter
    snapshot_stage = str(frontmatter.get("stage") or "")
    canonical_stage = stage_token(snapshot_stage) if snapshot_stage else None
    if (
        snapshot.path != task.path.resolve()
        or str(frontmatter.get("status") or "") not in {"claimed", "in_progress"}
        or str(frontmatter.get("assigned_to") or "") != lane.role
        or not canonical_stage
        or leases[0].binding.authority_case != str(frontmatter.get("authority_case") or "")
    ):
        raise CanonEchoError(
            "canon_echo_claim_position_mismatch",
            "make the exact task, claim, lane, session, stage, and AuthorityCase agree",
            task.task_id,
        )
    expected = resolve_claim_bound_canon_position(
        leases[0].binding,
        stage_token=canonical_stage,
    )
    if canonical_stage != expected.stage_token:
        raise CanonEchoError(
            "canon_echo_dispatch_position_stale",
            "reinject and receipt the exact current successor position before reconciliation",
            task.task_id,
        )
    rendered_payload = _render_expected_canon_payload(
        expected.canon_hash,
        expected.canon_image_hash,
        expected.stage_token,
        expected.canon_level,
        expected.canon_payload_sha256,
    )
    observed_at = (now or datetime.now(UTC)).astimezone(UTC)
    reconciliation = reconcile_canon_echo(
        relay_db,
        expected,
        rendered_payload=rendered_payload,
        now=observed_at,
        expected_sender=lane.role,
        expected_session_id=leases[0].binding.session_id,
    )
    # A failed Echo is support evidence, not unilateral transition authority.
    # Until the failure can be fenced in Relay MQ and bound to the applied claim
    # publication inside one transaction, the only lawful action is HOLD.
    return reconciliation, None


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
_DISPATCH_CLAIM_GUARD_MARKERS = dispatch_guards.DISPATCH_CLAIM_GUARD_MARKERS
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
    claim = worktree / "scripts" / "cc-claim"
    if not claim.is_file():
        return _dispatch_tool_block(f"missing cc-claim at {claim}", worktree)
    try:
        claim_text = _read_dispatch_guard(claim)
    except OSError as exc:
        return _dispatch_tool_block(f"unreadable cc-claim at {claim}: {exc}", worktree)
    missing_claim = [marker for marker in _DISPATCH_CLAIM_GUARD_MARKERS if marker not in claim_text]
    if missing_claim:
        return _dispatch_tool_block(
            f"stale cc-claim in {worktree}: missing {', '.join(missing_claim)}",
            worktree,
        )

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


def _dispatch_landed(task: Task, lane: LaneState) -> bool:
    observed = _check_lane(
        LaneDescriptor(role=lane.role, session=lane.session, platform=lane.platform)
    )
    aliases = {task.task_id, task.path.stem}
    return (
        observed.claimed_task in aliases
        and _active_task_claims_task(observed.role, observed.session, aliases)
        and _lane_launcher_process_present(observed)
    )


def _load_dispatch_cache() -> dict | None:
    """Retired authority consumer; the cache remains support-only elsewhere."""
    return None


def _stall_grace_for(role: str, cache: dict | None) -> float:
    """Return a fixed diagnostic threshold without consuming support data."""
    del role, cache
    return STALL_OUTPUT_GRACE_S


def _age_norm_s(cache: dict | None) -> float:
    """Return the static support baseline; cache data cannot rank effect candidates."""
    del cache
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
    if not _lane_owner_present(lane):
        return True  # owner process gone, task still non-terminal
    if lane.platform == "claude" and lane.pid_source == "proc":
        return False  # pidfile-free launcher is live; supervisor owns any later reap.
    return lane.output_age_s > output_grace_s


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
        "pid_source": lane.pid_source,
        "relay_age_s": round(lane.relay_age_s, 1) if lane.relay_age_s != float("inf") else None,
        "claimed_task": lane.claimed_task,
        "idle": lane.idle,
        "dispatchable": _lane_dispatchable(lane),
        "stalled": lane.stalled,
        "dispatch_ready": lane.dispatch_ready,
        "dispatch_blocked_reason": lane.dispatch_blocked_reason,
        "output_age_s": round(lane.output_age_s, 1) if lane.output_age_s != float("inf") else None,
    }
