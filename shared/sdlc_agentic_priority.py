"""Agentic-native SDLC prioritization contract.

This module is an additive source contract for replacing anthropomorphic
``WSJF``/priority-scalar dispatch with task-capability cells. It does not wire
the live scheduler yet; it names the current scalar surfaces, the replacement
cell fields, and the staged source cutover so follow-on work can converge on the
same calculus instead of spawning another local policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from shared.dispatch_frontier import FRONTIER_AXES
from shared.edt_measure import ROUTING_CLASSES
from shared.sdlc_router import REQUIREMENT_VECTOR_DIMENSIONS

CellFieldRole = Literal["identity", "partition", "demand", "max", "min", "status", "gate"]
CutoverPhase = Literal[
    "inventory",
    "demand_backfill",
    "evidence_producer",
    "frontier_shadow",
    "scheduler_cutover",
    "surface_cutover",
    "enforcement",
]


@dataclass(frozen=True, slots=True)
class DecompositionCriterion:
    """Machine-native reason to split or keep a dispatchable unit."""

    key: str
    decision_rule: str
    rejects: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CellField:
    """One field in the ``task x capability`` dispatch cell."""

    key: str
    role: CellFieldRole
    source: str
    invariant: str
    required_for_frontier: bool = True


@dataclass(frozen=True, slots=True)
class ScalarPrioritySurface:
    """A live surface that still treats scalar priority as a selector or display."""

    path: str
    current_scalar: str
    current_behavior: str
    replacement: str
    phase: CutoverPhase


@dataclass(frozen=True, slots=True)
class CutoverStep:
    """One sequenced source step in the scalar-to-frontier migration."""

    key: str
    phase: CutoverPhase
    files: tuple[str, ...]
    produces: tuple[str, ...]
    exit_predicate: str


@dataclass(frozen=True, slots=True)
class OperatorValueTierBoundary:
    """The only legitimate human-value input to dispatch."""

    parameter: str
    allowed_role: str
    forbidden_roles: tuple[str, ...]


FROZEN_ROUTING_CLASSES: tuple[str, ...] = tuple(ROUTING_CLASSES)
"""The shared 11-class value partition. ``unknown`` is intentionally excluded."""

REQUIREMENT_VECTOR_CONTRACT_DIMENSIONS: tuple[str, ...] = tuple(REQUIREMENT_VECTOR_DIMENSIONS)
"""The shared eight-dimension task demand shape required before route scoring."""

FRONTIER_SELECTION_OUTCOMES: tuple[str, ...] = ("FRONTIER", "HOLD", "INCOMPARABLE")
"""Allowed non-scalar dispatch partitions after feasibility gates run."""

FRONTIER_AXIS_ROLES: dict[str, CellFieldRole] = {
    axis: direction for axis, direction in FRONTIER_AXES.items()
}
"""The Pareto axes and optimization roles imported from ``shared.dispatch_frontier``."""

AGENTIC_DECOMPOSITION_CRITERIA: tuple[DecompositionCriterion, ...] = (
    DecompositionCriterion(
        key="capability_fit",
        decision_rule=(
            "Split when different capability routes would face materially different "
            "requirement vectors, authority ceilings, or verifier predicates."
        ),
        rejects=("one_owner_convenience", "human_tool_familiarity"),
    ),
    DecompositionCriterion(
        key="context_state_locality",
        decision_rule=(
            "Keep facts that must share loaded context or mutable state together; split facts "
            "that can be verified from independent local state."
        ),
        rejects=("human_attention_span", "status_report_legibility"),
    ),
    DecompositionCriterion(
        key="dependency_mitigation",
        decision_rule=(
            "Carve blockers into cells that unlock dependent DAG branches or expose a HOLD "
            "without masking unrelated executable work."
        ),
        rejects=("single_backlog_story_shape",),
    ),
    DecompositionCriterion(
        key="parallelizability",
        decision_rule=(
            "Split units that can run concurrently without shared write claims, route contention, "
            "or coupled acceptance evidence."
        ),
        rejects=("human_batching",),
    ),
    DecompositionCriterion(
        key="verifiability",
        decision_rule=(
            "Decompose at machine-checkable acceptance predicates, quality gates, or receipts; "
            "do not keep a unit large only because a person can review it as one narrative."
        ),
        rejects=("review_narrative_continuity", "estimate_padding"),
    ),
    DecompositionCriterion(
        key="information_gain",
        decision_rule=(
            "Prefer cells whose execution or verifier result updates route posteriors, demand "
            "shape, or dependency uncertainty for later cells."
        ),
        rejects=("comforting_progress_scalar",),
    ),
    DecompositionCriterion(
        key="cost_optimal_granularity",
        decision_rule=(
            "Choose the smallest cell that avoids duplicate context load, provider spend, and "
            "queue congestion while still producing durable evidence."
        ),
        rejects=("human_sized_ticket",),
    ),
    DecompositionCriterion(
        key="blast_radius_isolation",
        decision_rule=(
            "Separate high-risk mutation surfaces, public/provider-spend surfaces, and reversible "
            "support work so a bad route decision does not contaminate unrelated cells."
        ),
        rejects=("scope_padding", "all_or_nothing_project_chunk"),
    ),
    DecompositionCriterion(
        key="reversibility",
        decision_rule=(
            "Prefer reversible cells for exploration and isolate irreversible cells behind "
            "stronger gates, receipts, and route evidence."
        ),
        rejects=("human_confidence_proxy",),
    ),
)

TASK_CAPABILITY_CELL_CONTRACT: tuple[CellField, ...] = (
    CellField(
        key="task_id",
        role="identity",
        source="cc-task frontmatter and dispatch receipt",
        invariant="Identifies the work item but never ranks it by itself.",
        required_for_frontier=False,
    ),
    CellField(
        key="capability_route_id",
        role="identity",
        source="platform capability registry route_id",
        invariant="The capability is part of the dispatch unit, not a later assignment.",
        required_for_frontier=False,
    ),
    CellField(
        key="routing_class",
        role="partition",
        source="request decomposition and route metadata",
        invariant="Uses the frozen 11-class value partition shared by EDT, router, and Reins.",
        required_for_frontier=False,
    ),
    CellField(
        key="requirement_vector",
        role="demand",
        source="SdlcRoutingRequest.requirement_vector",
        invariant=(
            "Contains all eight demand dimensions before route scoring; missing dimensions HOLD."
        ),
    ),
    CellField(
        key="acceptance_predicate_ref",
        role="gate",
        source="cc-task quality gates, frontier review receipts, and deterministic verifiers",
        invariant="Each cell has an independent machine-checkable acceptance predicate.",
    ),
    CellField(
        key="v_hat",
        role="max",
        source="gate outcomes and route_posteriors in SdlcRouter",
        invariant="Estimated value is posterior evidence, not a human priority scalar.",
    ),
    CellField(
        key="c_hat",
        role="min",
        source="SpendReceipt and quota_spend_ledger cost observations",
        invariant="Absent cost stays absent; it is never imputed as zero.",
    ),
    CellField(
        key="fit",
        role="max",
        source="requirement_vector x capability_scores fit projection",
        invariant="Capability fit is cell-specific and cannot be added to task WSJF.",
    ),
    CellField(
        key="u",
        role="max",
        source="task graph tree-effect and dependency-unlock evidence",
        invariant="Unlock value is a DAG effect at the cell boundary.",
    ),
    CellField(
        key="mu",
        role="min",
        source="dispatch service-time, queue pressure, and route capacity evidence",
        invariant="Congestion pressure is minimized as its own axis, not hidden in aging.",
    ),
    CellField(
        key="confidence",
        role="status",
        source="capability confidence, evidence freshness, and gate witness quality",
        invariant="Confidence explains evidence quality; it is not a rank tie-break.",
        required_for_frontier=False,
    ),
    CellField(
        key="value_status",
        role="status",
        source="gate outcome producer and Reins dispatch measurement projection",
        invariant="One of measured, projected, absent; absent is rendered honestly, never as 0.",
        required_for_frontier=False,
    ),
    CellField(
        key="route_feasibility",
        role="gate",
        source="SdlcRouter floor vetoes, authority ceiling, activation gates, and blockers",
        invariant="Infeasible cells go to HOLD before any frontier comparison.",
        required_for_frontier=False,
    ),
)

OPERATOR_VALUE_TIER_BOUNDARY = OperatorValueTierBoundary(
    parameter="routing_class -> served_tier",
    allowed_role=(
        "Filter which value-tier partition is served before frontier selection; never score, "
        "multiply, or reorder cells inside a served tier."
    ),
    forbidden_roles=(
        "multiplicative_weight",
        "wsjf_adjustment",
        "priority_scalar",
        "human_legibility_tiebreak",
        "owner_attention_proxy",
    ),
)

SCALAR_PRIORITY_SURFACES: tuple[ScalarPrioritySurface, ...] = (
    ScalarPrioritySurface(
        path="agents/coordinator/core.py",
        current_scalar="Task.wsjf plus wsjf_effective/composite_rank_key",
        current_behavior="Coordinator planning and cooldown repair choose eligible work by scalar rank.",
        replacement=(
            "Plan over feasible task-capability cells and emit FRONTIER, HOLD, or INCOMPARABLE "
            "partitions with the selected route evidence attached."
        ),
        phase="scheduler_cutover",
    ),
    ScalarPrioritySurface(
        path="shared/dispatch_service_time.py",
        current_scalar="QueueTask.wsjf, wsjf_effective, and fit_blend",
        current_behavior="Queue planning ages a task scalar and optionally adds fit as another scalar.",
        replacement=(
            "Use queue pressure as the mu axis and route feasibility as gates while frontier "
            "selection owns non-dominated cell choice."
        ),
        phase="scheduler_cutover",
    ),
    ScalarPrioritySurface(
        path="shared/intake_fit_scorer.py",
        current_scalar="composite_rank_key",
        current_behavior="Capability fit can be blended into task priority as a single number.",
        replacement=(
            "Expose fit only as a cell axis derived from requirement_vector and route capability "
            "scores; do not add it to task priority."
        ),
        phase="scheduler_cutover",
    ),
    ScalarPrioritySurface(
        path="shared/orchestration_ledger.py",
        current_scalar="priority_bucket then wsjf",
        current_behavior="Dispatch candidates are sorted by bucket and scalar score.",
        replacement=(
            "Persist the selected cell, route_id, frontier partition, and veto reasons so ledger "
            "readers reconstruct the partial order."
        ),
        phase="frontier_shadow",
    ),
    ScalarPrioritySurface(
        path="scripts/request-intake-consumer",
        current_scalar="ranking_basis=wsjf_v0 and descending wsjf sort",
        current_behavior="Intake output advertises WSJF as the dispatch ordering basis.",
        replacement=(
            "Publish demand vectors, routing_class, value-tier filter, and cell frontier status "
            "instead of a ranked task list."
        ),
        phase="surface_cutover",
    ),
    ScalarPrioritySurface(
        path="agents/coordination_tui/data.py",
        current_scalar="TaskInfo.wsjf",
        current_behavior="TUI data loading sorts task rows by descending scalar priority.",
        replacement=(
            "Group by served tier and frontier partition, then display per-cell axes and HOLD "
            "reasons without ordinal rank."
        ),
        phase="surface_cutover",
    ),
    ScalarPrioritySurface(
        path="agents/coordination_tui/app.py",
        current_scalar="visible wsjf field",
        current_behavior="The coordination view presents scalar priority as task status.",
        replacement=(
            "Render route_id, routing_class, requirement summary, frontier partition, and "
            "value_status as the dispatch readout."
        ),
        phase="surface_cutover",
    ),
    ScalarPrioritySurface(
        path="scripts/braided_value_snapshot_runner.py",
        current_scalar="dispatch_sort.primary=wsjf and WSJF Primary dashboard sections",
        current_behavior="Snapshot dashboards preserve scalar primary ordering.",
        replacement=(
            "Snapshot the same task-capability cell fields consumed by Reins: v_hat, c_hat, fit, "
            "u, mu, value_status, and partition."
        ),
        phase="surface_cutover",
    ),
    ScalarPrioritySurface(
        path="scripts/request-decompose",
        current_scalar="task-level wsjf output",
        current_behavior="Decomposition still emits human-sized task scalar priority.",
        replacement=(
            "Emit complete requirement_vector, routing_class, and acceptance predicate refs for "
            "each dispatchable cell."
        ),
        phase="demand_backfill",
    ),
    ScalarPrioritySurface(
        path="agents/request_decomposer/writer.py",
        current_scalar="frontmatter wsjf",
        current_behavior="Generated task notes carry scalar priority as a first-class field.",
        replacement=(
            "Keep compatibility fields only as intake metadata while routing inputs come from "
            "requirement_vector, routing_class, and cell predicates."
        ),
        phase="demand_backfill",
    ),
    ScalarPrioritySurface(
        path="scripts/security-signal-intake",
        current_scalar="Convert through WSJF",
        current_behavior="Security intake prose routes work through scalar planning before mutation.",
        replacement=(
            "Convert through governed decomposition, requirement_vector assignment, and frontier "
            "cell routing before mutation."
        ),
        phase="surface_cutover",
    ),
)

CALCULUS_CUTOVER_SEQUENCE: tuple[CutoverStep, ...] = (
    CutoverStep(
        key="backfill_task_demand",
        phase="demand_backfill",
        files=(
            "scripts/request-decompose",
            "agents/request_decomposer/writer.py",
            "shared/route_metadata_schema.py",
        ),
        produces=("requirement_vector", "routing_class", "acceptance_predicate_ref"),
        exit_predicate=(
            "Every dispatchable task note has all eight demand dimensions, a frozen routing_class, "
            "and a verifier or receipt reference."
        ),
    ),
    CutoverStep(
        key="produce_cell_evidence",
        phase="evidence_producer",
        files=(
            "shared/gate_event_producer.py",
            "shared/gate_outcome_producer.py",
            "shared/sdlc_router.py",
            "shared/quota_spend_ledger.py",
            "shared/task_graph_tree_effect_scorer.py",
            "shared/dispatch_service_time.py",
        ),
        produces=("v_hat", "c_hat", "fit", "u", "mu", "value_status", "confidence"),
        exit_predicate=(
            "Outcome producers and route posteriors write the same cell axes consumed by the "
            "frontier selector, with absent values represented as absent."
        ),
    ),
    CutoverStep(
        key="shadow_frontier_selection",
        phase="frontier_shadow",
        files=(
            "shared/dispatch_frontier.py",
            "shared/sdlc_router.py",
            "shared/orchestration_ledger.py",
            "agents/coordinator/core.py",
        ),
        produces=("FRONTIER", "HOLD", "INCOMPARABLE"),
        exit_predicate=(
            "The scalar scheduler still dispatches, but every candidate logs its cell vector, "
            "frontier partition, route_id, and veto reasons for comparison."
        ),
    ),
    CutoverStep(
        key="cut_over_scheduler",
        phase="scheduler_cutover",
        files=(
            "agents/coordinator/core.py",
            "shared/dispatch_service_time.py",
            "shared/intake_fit_scorer.py",
        ),
        produces=("selected_task_capability_cell", "route_feasibility"),
        exit_predicate=(
            "Coordinator dispatch selects feasible non-dominated cells; WSJF remains intake "
            "metadata only and cannot choose a route."
        ),
    ),
    CutoverStep(
        key="cut_over_read_surfaces",
        phase="surface_cutover",
        files=(
            "scripts/request-intake-consumer",
            "agents/coordination_tui/data.py",
            "agents/coordination_tui/app.py",
            "scripts/braided_value_snapshot_runner.py",
            "/home/hapax/projects/reins/docs/PURVIEW-INTAKE.md",
            "/home/hapax/projects/reins/internal/grammar/econ.go",
        ),
        produces=("frontier_partition_display", "cell_axis_display", "honest_value_status"),
        exit_predicate=(
            "Dispatch views expose the partial order and cell evidence without a WSJF/priority "
            "rank or sorted priority list."
        ),
    ),
    CutoverStep(
        key="enforce_no_scalar_recollapse",
        phase="enforcement",
        files=(
            "tests/shared/test_dispatch_frontier.py",
            "tests/shared/test_sdlc_agentic_priority.py",
            "tests/test_request_intake_consumer.py",
            "/home/hapax/projects/reins/internal/model/dispatch_no_scalar_test.go",
        ),
        produces=("no_scalar_dispatch_guard", "value_status_honesty_guard"),
        exit_predicate=(
            "Tests fail if a dispatch selector or dispatch-facing readout reintroduces a scalar "
            "rank, imputes absent value/cost as zero, or hides HOLD/INCOMPARABLE cells."
        ),
    ),
)
