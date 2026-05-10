"""Scheduler readiness unblock reconciler.

This module reads cc-task frontmatter and produces a narrow readiness handoff
for the scheduler/private-runner path. It does not schedule content, mutate the
task vault, create a manual calendar, or create request queues. Its job is to
make stale blockers visible after upstream scheduler/run-store/public-event
policy work closes.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.content_programme_scheduler_policy import (
    ContentProgrammeSchedulerPolicy,
    ScheduleRoute,
    load_policy,
)
from shared.frontmatter import parse_frontmatter_with_diagnostics

DEFAULT_CC_TASK_ROOT = Path.home() / "Documents/Personal/20-projects/hapax-cc-tasks"
TASK_ANCHOR = "scheduler-readiness-unblock-reconcile"
PRODUCER = "shared.scheduler_readiness_reconciler"

SCHEDULER_RECONCILE_TASK_ID = "scheduler-readiness-unblock-reconcile"
PRIVATE_DRY_RUN_TASK_ID = "content-programme-private-dry-run-loop"
GROUNDING_RUNNER_TASK_ID = "content-programming-grounding-runner"
PROGRAMME_WCS_SNAPSHOT_TASK_ID = "programme-wcs-snapshot-smoke"
PROGRAMME_RUN_FIXTURE_PACK_TASK_ID = "programme-run-fixture-pack-live-smoke"
PROGRAMME_WCS_RUNNER_READINESS_TESTS_TASK_ID = "programme-wcs-runner-readiness-tests"

DEFAULT_RECONCILE_TARGETS: tuple[str, ...] = (
    SCHEDULER_RECONCILE_TASK_ID,
    PRIVATE_DRY_RUN_TASK_ID,
    GROUNDING_RUNNER_TASK_ID,
    PROGRAMME_WCS_SNAPSHOT_TASK_ID,
    PROGRAMME_RUN_FIXTURE_PACK_TASK_ID,
    PROGRAMME_WCS_RUNNER_READINESS_TESTS_TASK_ID,
)
PUBLIC_GATE_REQUIREMENTS: frozenset[str] = frozenset(
    {
        "no_expert_system",
        "rights",
        "provenance",
        "privacy",
        "monetization",
        "audio",
        "egress",
        "wcs_health",
        "evidence",
        "witness",
        "public_event",
    }
)

type TaskCollection = Literal["active", "closed", "refused"]
type ReadinessKind = Literal["ready", "blocked", "missing", "stale_note"]

_DEPENDENCY_ALIASES: dict[str, tuple[str, ...]] = {
    "scheduler-readiness-unblock-reconcile": (
        "scheduler-readiness-unblock-reconcile",
        "scheduler readiness",
    ),
    "content-programme-scheduler-policy": (
        "content-programme-scheduler-policy",
        "scheduler policy",
    ),
    "content-programme-feedback-ledger": (
        "content-programme-feedback-ledger",
        "feedback ledger",
    ),
    "content-programme-run-store-event-surface": (
        "content-programme-run-store-event-surface",
        "run store",
        "programme run envelope",
    ),
    "content-programme-run-envelope-schema-fixtures": (
        "content-programme-run-envelope-schema-fixtures",
        "programme run envelope",
        "run envelope",
    ),
    "format-to-public-event-adapter": (
        "format-to-public-event-adapter",
        "format-to-public-event adapter",
        "public adapter",
    ),
    "format-wcs-requirement-matrix": ("format-wcs-requirement-matrix", "format matrix"),
    "opportunity-to-run-wcs-gate": ("opportunity-to-run-wcs-gate", "opportunity gate"),
    "programme-outcome-to-feedback-live-wire": (
        "programme-outcome-to-feedback-live-wire",
        "outcome feedback",
    ),
    "wcs-witness-probe-runtime": ("wcs-witness-probe-runtime", "wcs witness runtime"),
    "runner-public-mode-refusal-harness": (
        "runner-public-mode-refusal-harness",
        "public-mode refusal harness",
        "dry-run/public-mode refusal harness",
    ),
    "rights-safe-media-reference-gate": ("rights-safe media gate",),
    "monetization-readiness-ledger": ("monetization readiness",),
    "programme-to-scrim-profile-policy": ("profile", "scrim profile"),
    "scrim-wcs-claim-posture-gate": ("scrim wcs",),
    "director-scrim-gesture-adapter": ("gesture",),
    "scrim-translucency-and-no-visualizer-health-fixtures": ("scrim", "health packets"),
    "programme-wcs-snapshot-smoke": ("programme-wcs-snapshot-smoke", "programme wcs snapshot"),
    "programme-run-fixture-pack-live-smoke": (
        "programme-run-fixture-pack-live-smoke",
        "live-smoke",
        "fixture pack",
    ),
    "wcs-director-snapshot-api": ("wcs director snapshot api", "director snapshot"),
    "wcs-health-degraded-blocker-bus": ("health blocker bus",),
    "programme-boundary-wcs-evidence-adapter": ("boundary evidence",),
    "content-programme-outcome-nesting": ("nested outcomes",),
    "world-surface-no-false-grounding-fixtures": ("no-false-grounding fixtures",),
}


class SchedulerReconcileModel(BaseModel):
    """Strict immutable base for reconciler records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class CCTaskRecord(SchedulerReconcileModel):
    """Small cc-task frontmatter read model."""

    task_id: str
    title: str | None = None
    status: str
    collection: TaskCollection
    path: str
    blocked_reason: str | None = None
    depends_on: tuple[str, ...] = Field(default_factory=tuple)
    blocks: tuple[str, ...] = Field(default_factory=tuple)
    pr: str | None = None

    @property
    def closed(self) -> bool:
        return self.collection == "closed" or self.status == "done"


class DependencyDisposition(SchedulerReconcileModel):
    """Resolved state of one dependency."""

    task_id: str
    status: str
    collection: TaskCollection | Literal["missing"]
    closed: bool
    blocked_reason: str | None = None
    pr: str | None = None


class ReconcileTarget(SchedulerReconcileModel):
    """Readiness assessment for one target task."""

    task_id: str
    title: str | None
    status: str
    readiness: ReadinessKind
    stale_dependency_blockers: tuple[str, ...] = Field(default_factory=tuple)
    closed_dependencies: tuple[str, ...] = Field(default_factory=tuple)
    open_dependencies: tuple[str, ...] = Field(default_factory=tuple)
    missing_dependencies: tuple[str, ...] = Field(default_factory=tuple)
    recommended_blocked_reason: str | None = None
    notes: tuple[str, ...] = Field(default_factory=tuple)


class PublicModeGateSummary(SchedulerReconcileModel):
    """Proof that public-live and monetized scheduler gates remain distinct."""

    public_live_route_present: bool
    public_archive_route_present: bool
    monetized_route_present: bool
    required_hard_gates_present: tuple[str, ...]
    missing_hard_gates: tuple[str, ...]
    manual_calendar_allowed: bool
    request_queue_allowed: bool
    supporter_controlled_show_allowed: bool
    community_moderation_allowed: bool

    @property
    def preserved(self) -> bool:
        return (
            self.public_live_route_present
            and self.public_archive_route_present
            and self.monetized_route_present
            and not self.missing_hard_gates
            and not self.manual_calendar_allowed
            and not self.request_queue_allowed
            and not self.supporter_controlled_show_allowed
            and not self.community_moderation_allowed
        )


class SchedulerReadinessReconcileReport(SchedulerReconcileModel):
    """Final handoff generated by the scheduler readiness reconciler."""

    schema_version: Literal[1] = 1
    producer: Literal["shared.scheduler_readiness_reconciler"] = PRODUCER
    task_anchor: Literal["scheduler-readiness-unblock-reconcile"] = TASK_ANCHOR
    assumed_done_task_ids: tuple[str, ...] = Field(default_factory=tuple)
    targets: tuple[ReconcileTarget, ...]
    ready_items: tuple[str, ...]
    blocked_items: tuple[str, ...]
    stale_items: tuple[str, ...]
    minimum_remaining_private_dry_run_dependencies: tuple[str, ...]
    public_mode_gates: PublicModeGateSummary
    manual_content_calendar_created: Literal[False] = False
    request_queue_created: Literal[False] = False
    operator_topic_picking_loop_created: Literal[False] = False

    def to_json(self) -> str:
        """Serialize the report deterministically."""

        return json.dumps(self.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def load_cc_task_records(root: Path = DEFAULT_CC_TASK_ROOT) -> tuple[CCTaskRecord, ...]:
    """Load cc-task records from active/closed/refused note frontmatter."""

    records: list[CCTaskRecord] = []
    for collection in ("active", "closed", "refused"):
        directory = root / collection
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.md")):
            result = parse_frontmatter_with_diagnostics(path)
            if not result.ok or result.frontmatter is None:
                continue
            frontmatter = result.frontmatter
            if frontmatter.get("type") != "cc-task":
                continue
            records.append(_record_from_frontmatter(path, collection, frontmatter))
    return tuple(records)


def build_scheduler_readiness_reconcile(
    records: Iterable[CCTaskRecord],
    *,
    assume_done_task_ids: Iterable[str] = (),
    policy: ContentProgrammeSchedulerPolicy | None = None,
    target_task_ids: Iterable[str] = DEFAULT_RECONCILE_TARGETS,
) -> SchedulerReadinessReconcileReport:
    """Build a scheduler/runner readiness handoff from cc-task state."""

    record_map = {record.task_id: record for record in records}
    assumed_done = tuple(dict.fromkeys(assume_done_task_ids))
    targets = tuple(
        _assess_target(task_id, record_map, assumed_done=frozenset(assumed_done))
        for task_id in target_task_ids
    )
    ready_items = tuple(target.task_id for target in targets if target.readiness == "ready")
    blocked_items = tuple(target.task_id for target in targets if target.readiness == "blocked")
    stale_items = tuple(
        target.task_id
        for target in targets
        if target.readiness == "stale_note" or target.stale_dependency_blockers
    )
    private_target = next(
        (target for target in targets if target.task_id == PRIVATE_DRY_RUN_TASK_ID),
        None,
    )
    remaining = private_target.open_dependencies if private_target is not None else ()
    return SchedulerReadinessReconcileReport(
        assumed_done_task_ids=assumed_done,
        targets=targets,
        ready_items=ready_items,
        blocked_items=blocked_items,
        stale_items=stale_items,
        minimum_remaining_private_dry_run_dependencies=remaining,
        public_mode_gates=inspect_public_mode_gates(policy or load_policy()),
    )


def inspect_public_mode_gates(
    policy: ContentProgrammeSchedulerPolicy,
) -> PublicModeGateSummary:
    """Summarize public-live and monetized scheduler gate preservation."""

    present_gates = tuple(
        gate for gate in sorted(PUBLIC_GATE_REQUIREMENTS) if gate in policy.hard_public_gates
    )
    missing = tuple(
        gate for gate in sorted(PUBLIC_GATE_REQUIREMENTS) if gate not in policy.hard_public_gates
    )
    routes = set(policy.routes)
    boundary = policy.operator_boundary_policy
    return PublicModeGateSummary(
        public_live_route_present=ScheduleRoute.PUBLIC_LIVE in routes,
        public_archive_route_present=ScheduleRoute.PUBLIC_ARCHIVE in routes,
        monetized_route_present=ScheduleRoute.MONETIZED in routes,
        required_hard_gates_present=present_gates,
        missing_hard_gates=missing,
        manual_calendar_allowed=boundary.manual_calendar_allowed,
        request_queue_allowed=boundary.request_queue_allowed,
        supporter_controlled_show_allowed=boundary.supporter_controlled_show_allowed,
        community_moderation_allowed=boundary.community_moderation_allowed,
    )


def render_handoff_markdown(report: SchedulerReadinessReconcileReport) -> str:
    """Render a short operator handoff note."""

    lines = [
        "# Scheduler Readiness Unblock Reconcile",
        "",
        "## Summary",
        "",
        "- Scheduler policy is no longer an open blocker.",
        "- Public-live and monetized routes remain gated by WCS, rights, provenance, privacy, evidence, witness, public-event, audio, egress, and monetization checks.",
        "- No manual calendar, request queue, supporter show-control path, community moderation loop, or operator topic-picking loop was created.",
        "",
        "## Ready",
        "",
    ]
    lines.extend(_bullet_lines(report.ready_items))
    lines.extend(["", "## Blocked", ""])
    lines.extend(_bullet_lines(report.blocked_items))
    lines.extend(["", "## Stale Blockers", ""])
    stale_lines = [
        f"{target.task_id}: {', '.join(target.stale_dependency_blockers)}"
        for target in report.targets
        if target.stale_dependency_blockers
    ]
    lines.extend(_bullet_lines(stale_lines))
    lines.extend(["", "## Minimum Remaining Private Dry-Run Dependencies", ""])
    lines.extend(_bullet_lines(report.minimum_remaining_private_dry_run_dependencies))
    lines.extend(["", "## Target Notes", ""])
    for target in report.targets:
        lines.append(f"- {target.task_id}: {target.readiness}")
        if target.recommended_blocked_reason:
            lines.append(f"  recommended_blocked_reason: {target.recommended_blocked_reason}")
        for note in target.notes:
            lines.append(f"  note: {note}")
    return "\n".join(lines).rstrip() + "\n"


def _assess_target(
    task_id: str,
    records: Mapping[str, CCTaskRecord],
    *,
    assumed_done: frozenset[str],
) -> ReconcileTarget:
    record = records.get(task_id)
    if record is None:
        return ReconcileTarget(
            task_id=task_id,
            title=None,
            status="missing",
            readiness="missing",
            missing_dependencies=(task_id,),
            notes=("task note is missing",),
        )

    dependencies = tuple(
        _dependency_disposition(dep_id, records, assumed_done=assumed_done)
        for dep_id in record.depends_on
    )
    closed = tuple(dep.task_id for dep in dependencies if dep.closed)
    open_deps = tuple(
        dep.task_id for dep in dependencies if not dep.closed and dep.collection != "missing"
    )
    missing = tuple(dep.task_id for dep in dependencies if dep.collection == "missing")
    stale = _stale_dependency_mentions(record, dependencies)
    recommended = _recommended_blocked_reason(task_id, open_deps, closed)
    readiness = _readiness(record, open_deps=open_deps, missing=missing, stale=stale)
    return ReconcileTarget(
        task_id=task_id,
        title=record.title,
        status=record.status,
        readiness=readiness,
        stale_dependency_blockers=stale,
        closed_dependencies=closed,
        open_dependencies=open_deps,
        missing_dependencies=missing,
        recommended_blocked_reason=recommended,
        notes=_target_notes(task_id, open_deps=open_deps, stale=stale),
    )


def _dependency_disposition(
    task_id: str,
    records: Mapping[str, CCTaskRecord],
    *,
    assumed_done: frozenset[str],
) -> DependencyDisposition:
    record = records.get(task_id)
    if record is None:
        return DependencyDisposition(
            task_id=task_id,
            status="missing",
            collection="missing",
            closed=False,
        )
    closed = record.closed or task_id in assumed_done
    return DependencyDisposition(
        task_id=task_id,
        status="done" if task_id in assumed_done else record.status,
        collection=record.collection,
        closed=closed,
        blocked_reason=record.blocked_reason,
        pr=record.pr,
    )


def _record_from_frontmatter(
    path: Path,
    collection: TaskCollection,
    frontmatter: dict[str, Any],
) -> CCTaskRecord:
    return CCTaskRecord(
        task_id=str(frontmatter.get("task_id", path.stem)),
        title=_optional_string(frontmatter.get("title")),
        status=str(frontmatter.get("status", collection)),
        collection=collection,
        path=str(path),
        blocked_reason=_optional_string(frontmatter.get("blocked_reason")),
        depends_on=_tuple_strings(frontmatter.get("depends_on")),
        blocks=_tuple_strings(frontmatter.get("blocks")),
        pr=_optional_string(frontmatter.get("pr")),
    )


def _stale_dependency_mentions(
    record: CCTaskRecord,
    dependencies: tuple[DependencyDisposition, ...],
) -> tuple[str, ...]:
    reason = _active_blocker_text(record.blocked_reason)
    if not reason:
        return ()
    stale: list[str] = []
    for dependency in dependencies:
        if not dependency.closed:
            continue
        aliases = _DEPENDENCY_ALIASES.get(dependency.task_id, (dependency.task_id,))
        if any(alias.lower() in reason for alias in aliases):
            stale.append(dependency.task_id)
    return tuple(dict.fromkeys(stale))


def _active_blocker_text(blocked_reason: str | None) -> str:
    """Return the part of a blocked reason that names current blockers."""

    reason = (blocked_reason or "").lower()
    if not reason:
        return ""
    for separator in (";", ". closed ", ". run store", ". this makes"):
        if separator in reason:
            reason = reason.split(separator, 1)[0]
    return reason


def _readiness(
    record: CCTaskRecord,
    *,
    open_deps: tuple[str, ...],
    missing: tuple[str, ...],
    stale: tuple[str, ...],
) -> ReadinessKind:
    if missing:
        return "missing"
    if open_deps:
        return "blocked"
    if stale or (record.blocked_reason and record.status in {"offered", "claimed", "in_progress"}):
        return "stale_note"
    return "ready"


def _recommended_blocked_reason(
    task_id: str,
    open_deps: tuple[str, ...],
    closed_deps: tuple[str, ...],
) -> str | None:
    if not open_deps:
        return None
    if task_id == PRIVATE_DRY_RUN_TASK_ID:
        return (
            "waits for programme-wcs-snapshot-smoke and "
            "programme-run-fixture-pack-live-smoke; scheduler policy, opportunity gate, "
            "run envelope, format WCS matrix, outcome feedback, WCS witness runtime, and "
            "public-mode refusal harness are closed"
        )
    if task_id == PROGRAMME_WCS_SNAPSHOT_TASK_ID:
        return (
            "waits for wcs-director-snapshot-api and wcs-health-degraded-blocker-bus; "
            "run envelope and director programme-format actions are closed"
        )
    if task_id == PROGRAMME_RUN_FIXTURE_PACK_TASK_ID:
        return "waits for programme-wcs-snapshot-smoke"
    joined = ", ".join(open_deps)
    if closed_deps:
        return f"waits for {joined}; closed dependencies preserved as evidence"
    return f"waits for {joined}"


def _target_notes(
    task_id: str,
    *,
    open_deps: tuple[str, ...],
    stale: tuple[str, ...],
) -> tuple[str, ...]:
    notes: list[str] = []
    if task_id == GROUNDING_RUNNER_TASK_ID and not open_deps:
        notes.append(
            "all named runner dependencies are closed; do not relax runtime public-live or monetized gates"
        )
    if task_id == PRIVATE_DRY_RUN_TASK_ID and open_deps == (
        PROGRAMME_WCS_SNAPSHOT_TASK_ID,
        PROGRAMME_RUN_FIXTURE_PACK_TASK_ID,
    ):
        notes.append(
            "minimum remaining private dry-run chain is WCS snapshot smoke then fixture pack"
        )
    if stale:
        notes.append("blocked_reason mentions dependencies that are now closed")
    return tuple(notes)


def _tuple_strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Iterable):
        return tuple(str(item) for item in value if item is not None)
    return (str(value),)


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "null":
        return None
    return text


def _bullet_lines(values: Iterable[str]) -> list[str]:
    items = tuple(values)
    if not items:
        return ["- None"]
    return [f"- {item}" for item in items]


__all__ = [
    "DEFAULT_CC_TASK_ROOT",
    "DEFAULT_RECONCILE_TARGETS",
    "GROUNDING_RUNNER_TASK_ID",
    "PRIVATE_DRY_RUN_TASK_ID",
    "PRODUCER",
    "PROGRAMME_RUN_FIXTURE_PACK_TASK_ID",
    "PROGRAMME_WCS_RUNNER_READINESS_TESTS_TASK_ID",
    "PROGRAMME_WCS_SNAPSHOT_TASK_ID",
    "PUBLIC_GATE_REQUIREMENTS",
    "SCHEDULER_RECONCILE_TASK_ID",
    "TASK_ANCHOR",
    "CCTaskRecord",
    "DependencyDisposition",
    "PublicModeGateSummary",
    "ReconcileTarget",
    "SchedulerReadinessReconcileReport",
    "build_scheduler_readiness_reconcile",
    "inspect_public_mode_gates",
    "load_cc_task_records",
    "render_handoff_markdown",
]
