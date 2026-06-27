"""EDT scorer — the equal-depth-of-treatment engine (v1 floor).

Pure, side-effect-free, SYNCHRONOUS supply-side capability descriptor scorer. Reads the
post-receipt-overlay :class:`PlatformCapabilityRegistry` (the caller MUST pass the output of
``load_platform_capability_registry``, which applies ``apply_platform_capability_receipts``) and
emits a per-platform :class:`EdtMeasure` built from per-variant-leaf D0–D5 descriptors. A
platform's EDT is the MIN over its route leaves. Fail-closed everywhere: a missing STEP-0 field
or ``None`` supply OMITS the dimension rather than crashing (all STEP-0 fields read via
``getattr``-optional defaults).

The objective artifact behind "every capability received equal depth of treatment": it makes the
structural shape of the (self-attested) capability registry legible per routing-class slice. It does
NOT independently re-measure the scores/confidence it consumes — those remain self-attested (see
``defense_caveat``); making "measured (not asserted)" REAL is the job of the downstream outcome-gate
producer + aggregation watcher that overlay evidence receipts onto this descriptive floor.

DISPARITY HONESTY (carried into every receipt's ``defense_caveat``): the ratio is provisional-,
freshness- and omission-aware, but it is NOT structurally capped against a rich self-attesting
platform. What actually holds a rich platform below a PASS today is the CONJUNCTIVE GATE
(``specificity_ratio>=0.90`` AND ``slice_policy_completeness>=0.90`` AND ``evidence_health>=0.70``
AND ``provisional_density<=0.30``), NOT a structural ratio cap. The ``depth_class`` rank is a SEPARATE
anti-disparity lever for RANKING/selection only — it does NOT enter the pass gate. The
slicing-test dedupe + a fidelity-gated confidence validator land with STEP-0
(``cc-task-edt-schema-plumbing-20260626``); until then the corresponding paths are INERT and the
receipt SURFACES which defenses are inert, so a reader does not mistake provisional under-count for
genuine capability poverty.

NON-GOALS: no registry mutation; no ``_aggregate_score`` import (it would collapse the deliberately
two-layer normalization); no routing/dispatch wiring (MIN-over-platform is a DESCRIPTIVE supply-side
health floor — it can mask a strong single route behind a weak sibling; fine for a floor, wrong for
routing). The two-layer normalization (``specificity_ratio`` + ``slice_policy_completeness``) is
computed by SEPARATE divisions and must never be collapsed into one (the "never collapsed" invariant,
pinned by test #1).

DELIBERATE DEVIATION FROM THE SPEC (dev2 2026-06-27, ratified in the spec artifact's LAYER-1 section):
LAYER 1 ``specificity_ratio`` is the MEAN of three independently [0,1]-normalized components
(cap-scaled D1, fresh-weighted D2 fraction = ``done/(required*5)``, D5 boundary fraction), NOT the
spec's summed-raw ``(d1_norm + d2.done + d5.cells_present) / (1 + d2.required + d5.cells_required)``.
The raw form lets ``d2.done`` (0..~70) dominate and SATURATES the ratio to ~1.0 for any fresh,
high-confidence platform — making the ratio gate vacuous. The mean-of-thirds keeps each dimension
legible and the ratio discriminating; the frozen anchor (test #1) pins THIS form.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from shared.dispatcher_policy import DimensionalScore, _dimension_score
from shared.platform_capability_receipts import EvidenceStatus, PlatformCapabilityReceipt
from shared.platform_capability_registry import (
    REQUIRED_ROUTE_IDS,
    AuthorityCeiling,
    CapacityPool,
    DescriptorVariant,
    ExecutionDescriptor,
    PlatformCapabilityRegistry,
    PlatformCapabilityRoute,
    RouteState,
    check_route_freshness,
    ensure_utc,
    materialize_descriptor_leaves,
    parse_duration_spec,
)

# --- locked parameters --------------------------------------------------------------------
CONFIDENCE_MAX = 5

#: The 11 substantive routing classes (the EDT denominator). ``unknown`` is the 12th placeholder
#: in the upstream ``RoutingClassValue`` Literal and is EXCLUDED here. Defined locally (not imported)
#: because the upstream Literal lives in a branch-gated module; drift-pinned by test #12.
ROUTING_CLASSES: tuple[str, ...] = (
    "coordination",
    "research_support",
    "docs_planning",
    "source_python",
    "source_other",
    "source_governance",
    "runtime_ops",
    "public_surface",
    "provider_spend",
    "operator_action",
    "verification",
)
NUM_ROUTING_CLASSES = len(ROUTING_CLASSES)  # = 11

DEPTH_CLASS_TRIVIAL_MAX = 5  # < 5 cells -> trivial
DEPTH_CLASS_BOUNDED_MAX = 20  # 5..20 -> bounded ; > 20 -> rich

RATIO_THRESHOLD = 0.90
COMPLETENESS_THRESHOLD = 0.90
EVIDENCE_HEALTH_THRESHOLD = 0.70
PROVISIONAL_DENSITY_THRESHOLD = 0.30

DEFAULT_EXPECTED_PLATFORM_SET = 12
DEFAULT_DEPTH_CAP = 20
DEFAULT_KNOBS_PATH = Path("config/edt-platform-knobs.yaml")

#: The 14 REQUIRED CapabilityScores dimensions, in declared order.
REQUIRED_CAPABILITY_DIMS: tuple[str, ...] = (
    "grounding",
    "governance_reasoning",
    "source_editing",
    "architecture",
    "ambiguity_resolution",
    "long_context",
    "current_docs_grounding",
    "multimodal_verification",
    "runtime_debugging",
    "test_authoring",
    "coordination_reliability",
    "privacy_safety",
    "public_claim_safety",
    "local_calibration",
)
#: 4 OPTIONAL D2 axes — additive in STEP-0; absent today (consumed via getattr-optional / key-present).
OPTIONAL_CAPABILITY_DIMS: tuple[str, ...] = (
    "multi_source_aggregation",
    "search_grounding_recall",
    "citation_provenance",
    "reasoning_profile_novelty",
)

#: Routing-class alias map: collapses the type gap between TaskSpec.routing_class (validated 11-enum),
#: ClassificationEnvelope.label (free str) and GateEvent.routing_class (bare str). Re-authored here
#: (the upstream normalizer is branch-gated); drift-pinned by test #9.
_ROUTING_CLASS_ALIASES: dict[str, str] = {
    "source_patch": "source_other",
    "source_mutation": "source_other",
    "source": "source_other",
    "python": "source_python",
    "governance": "source_governance",
    "runtime": "runtime_ops",
    "public_claim": "public_surface",
    "public": "public_surface",
    "spend": "provider_spend",
    "operator": "operator_action",
    "verify": "verification",
    "test": "verification",
    "tests": "verification",
    "relay": "coordination",
    "docs": "docs_planning",
    "planning": "docs_planning",
    "research": "research_support",
    "support": "research_support",
}

#: Build-wide caveats: the defenses that are INERT until STEP-0 lands.
_BUILD_DEFENSE_CAVEATS: tuple[str, ...] = (
    "slicing-test dedupe inert: STEP-0 interaction records not landed (D1 cell_count may over-count)",
    "D3/D4/D5 slice/use/boundary cells derived from a single mutability+capability fit-class PROXY "
    "(collinear; no declared slice or boundary table until STEP-0)",
    "evidence_refs presence-gated not fidelity-gated: self-attested confidence is accepted",
    "D0 expected_platform_set is an operator ASSERTION co-located in the same repo (no independent oracle)",
)
_LEAF_DEFENSE_CAVEATS: tuple[str, ...] = (
    "specificity_ratio is provisional/freshness aware but NOT structurally capped (gate-only defense)",
    "D3/D4/D5 cells_present is a single derived fit-class proxy until STEP-0 slice/boundary records land",
)


# --- knobs (the exogenous floor) ----------------------------------------------------------
@dataclass(frozen=True)
class EdtKnobs:
    expected_platform_set: int
    expected_platform_members: tuple[str, ...]
    depth_cap: int
    retired_phantoms: tuple[str, ...]


def _default_members() -> tuple[str, ...]:
    return tuple(sorted({route_id.split(".")[0] for route_id in REQUIRED_ROUTE_IDS} | {"gemini"}))


def load_edt_knobs(path: Path | None = None) -> EdtKnobs:
    """Load the operator-maintained knobs floor; fail-safe defaults when absent/unreadable."""
    knobs_path = path or DEFAULT_KNOBS_PATH
    try:
        raw = yaml.safe_load(knobs_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        raw = None
    if not isinstance(raw, Mapping):
        raw = {}

    expected_set = raw.get("expected_platform_set", DEFAULT_EXPECTED_PLATFORM_SET)
    expected_set = (
        int(expected_set) if isinstance(expected_set, int) else DEFAULT_EXPECTED_PLATFORM_SET
    )

    members_raw = raw.get("expected_platform_members")
    if isinstance(members_raw, list) and members_raw:
        members = tuple(str(member) for member in members_raw)
    else:
        members = _default_members()

    depth_cap = raw.get("depth_cap", DEFAULT_DEPTH_CAP)
    depth_cap = (
        int(depth_cap) if isinstance(depth_cap, int) and depth_cap > 0 else DEFAULT_DEPTH_CAP
    )

    phantoms_raw = raw.get("retired_phantoms")
    phantoms = tuple(str(p) for p in phantoms_raw) if isinstance(phantoms_raw, list) else ()

    return EdtKnobs(
        expected_platform_set=expected_set,
        expected_platform_members=members,
        depth_cap=depth_cap,
        retired_phantoms=phantoms,
    )


# --- receipt models -----------------------------------------------------------------------
class _EdtModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class D1Descriptor(_EdtModel):
    leaf: str
    specificity_cells: tuple[str, ...]
    cell_count: int
    meta_modes: tuple[str, ...] = ()
    platform_features: tuple[str, ...] = ()
    depth_class: str
    dedupe_inert: bool = True


class D2Fitness(_EdtModel):
    leaf: str
    done: float
    required: int
    provisional_dims: tuple[str, ...]
    dim_scores: tuple[DimensionalScore, ...]


class D3SliceFit(_EdtModel):
    leaf: str
    cells_present: int
    cells_required: int


class D4UsePolicy(_EdtModel):
    leaf: str
    cells_present: int
    cells_required: int
    interaction_records: tuple[str, ...] = ()
    provisional_capped: bool = False
    available: bool = True
    unavailability_reason: str | None = None


class D5Boundaries(_EdtModel):
    leaf: str
    cells_present: int
    cells_required: int
    equivalence_pending: int = 0


class LeafEdt(_EdtModel):
    leaf: str
    platform: str
    d1: D1Descriptor | None
    d2: D2Fitness | None
    d3: D3SliceFit | None
    d4: D4UsePolicy | None
    d5: D5Boundaries | None
    d0_omitted: bool
    # two-layer normalization — computed by SEPARATE divisions, NEVER collapsed:
    specificity_ratio: float | None
    slice_policy_completeness: float | None
    specificity_num: float | None
    specificity_den: float | None
    completeness_num: float | None
    completeness_den: float | None
    evidence_health: float | None
    provisional_density: float | None
    passes: bool
    defense_caveat: tuple[str, ...] = ()


class EdtMeasure(_EdtModel):
    platform: str
    platform_ratio: float | None
    platform_completeness: float | None
    platform_evidence_health: float | None
    platform_provisional_density: float | None
    depth_class: str
    platform_passes: bool
    leaves: tuple[LeafEdt, ...]
    expected_platform_set: int
    expected_platform_members: tuple[str, ...]
    observed_platform_count: int
    omitted_platforms: tuple[str, ...]
    build_defense_caveat: tuple[str, ...]


# --- small public helpers -----------------------------------------------------------------
def resolve_depth_class(cell_count: int) -> str:
    if cell_count < DEPTH_CLASS_TRIVIAL_MAX:
        return "trivial"
    if cell_count <= DEPTH_CLASS_BOUNDED_MAX:
        return "bounded"
    return "rich"


def normalize_routing_class(label: str) -> str:
    candidate = label.strip().lower()
    if candidate in ROUTING_CLASSES:
        return candidate
    return _ROUTING_CLASS_ALIASES.get(candidate, "unknown")


def platform_depth_rank(measure: EdtMeasure) -> int:
    return {"trivial": 0, "bounded": 1, "rich": 2}.get(measure.depth_class, 0)


def slicing_test_dedupe(
    cells: Iterable[str],
    *,
    policy_signatures: Mapping[str, tuple[str, ...]] | None = None,
) -> tuple[tuple[str, ...], bool]:
    """Merge cells with identical (policy, rationale) signatures across all 11 routing_classes.

    Returns ``(deduped, ran)``. When ``policy_signatures`` is ``None`` (pre-STEP-0) the signature
    degenerates to the cell key, so NO merge runs (conservative, fail-safe) and ``ran`` is False.
    """
    ordered = list(dict.fromkeys(cells))
    if not policy_signatures:
        return tuple(ordered), False
    seen_signatures: dict[tuple[str, ...], str] = {}
    deduped: list[str] = []
    for cell in ordered:
        signature = policy_signatures.get(cell, (cell,))
        if signature in seen_signatures:
            continue
        seen_signatures[signature] = cell
        deduped.append(cell)
    return tuple(deduped), True


# --- private helpers ----------------------------------------------------------------------
@dataclass(frozen=True)
class _FreshWeightedScore:
    """Adapter exposing the (.score, .confidence, .evidence_refs) attrs ``_dimension_score`` reads,
    with the score pre-weighted by ``confidence/5 * freshness_factor`` — so reuse does not silently
    drop the freshness weight (the frozen ScoreConfidence must not be mutated)."""

    score: float
    confidence: float
    evidence_refs: tuple[str, ...]


def _freshness_factor(observed_at: datetime | None, stale_after: str, now: datetime) -> float:
    if observed_at is None:
        return 0.0
    try:
        window = parse_duration_spec(stale_after)
    except ValueError:
        return 0.0
    if window <= timedelta(0):
        return 0.0
    age = ensure_utc(now) - ensure_utc(observed_at)
    if age <= timedelta(0):
        return 1.0
    if age >= window:
        return 0.0
    return 1.0 - (age / window)


def _optional_meta_modes(variant: DescriptorVariant | None) -> tuple[str, ...]:
    if variant is None:
        return ()
    meta_mode = getattr(variant, "meta_mode", None)
    if meta_mode and str(meta_mode) != "none":
        return (str(meta_mode),)
    return ()


def _platform_features(route: PlatformCapabilityRoute) -> tuple[str, ...]:
    # STEP-0 / future: platform-distinguishing features (spark/model-council/sonar-pro/fugu-ultra).
    # Inert today — no anchoring field in the registry; returns () so D1 does not over-count. Wired
    # into _resolve_d1 (surfaced on D1Descriptor.platform_features) so the seam is live, not dead.
    return ()


def _locality(route: PlatformCapabilityRoute) -> str:
    return "local" if route.capacity_pool is CapacityPool.LOCAL_COMPUTE else "cloud"


def _cell_key(descriptor: ExecutionDescriptor, locality: str) -> str:
    return "|".join(
        (
            descriptor.effort.value,
            descriptor.context_mode.value,
            descriptor.fast_mode.value,
            descriptor.quantization.value,
            locality,
        )
    )


def _descriptor_axes(descriptor: ExecutionDescriptor) -> tuple[str, ...]:
    """The 4 (axis=value) pairs THIS leaf's descriptor selects — the per-leaf D4 axis denominator.
    Leaf-specific (the leaf is scored on ITS OWN descriptor, not the route-wide reachable union)."""
    return (
        f"effort={descriptor.effort.value}",
        f"context_mode={descriptor.context_mode.value}",
        f"fast_mode={descriptor.fast_mode.value}",
        f"quantization={descriptor.quantization.value}",
    )


def _fit_classes(route: PlatformCapabilityRoute) -> frozenset[str]:
    """Deterministic proxy for which routing_classes the leaf could serve (the un-declared slice/use
    table). Derived from mutability + authority + capability signals; a route fitting more classes
    has more declared coverage. STEP-0 will replace this with an explicit slice table."""
    fit: set[str] = {"coordination", "research_support"}
    scores = route.capability_scores
    if route.mutability.vault_docs:
        fit.add("docs_planning")
    if route.mutability.source:
        fit.add("source_python")
        fit.add("source_other")
        if route.authority_ceiling is AuthorityCeiling.AUTHORITATIVE:
            fit.add("source_governance")
    if route.mutability.runtime:
        fit.add("runtime_ops")
    if route.mutability.public:
        fit.add("public_surface")
    if route.mutability.provider_spend:
        fit.add("provider_spend")
    if scores.test_authoring.score >= 1 or scores.multimodal_verification.score >= 1:
        fit.add("verification")
    if route.authority_ceiling is AuthorityCeiling.AUTHORITATIVE:
        fit.add("operator_action")
    return frozenset(fit & set(ROUTING_CLASSES))


def _d4_signatures_for(route: PlatformCapabilityRoute) -> Mapping[str, tuple[str, ...]] | None:
    # Pre-STEP-0 there are no per-cell interaction records, so the slicing test stays inert.
    return None


def _mirrored_quota_unobservable_nonblocking(
    route: PlatformCapabilityRoute, receipt: PlatformCapabilityReceipt | None
) -> bool:
    """Mirror of ``platform_capability_registry._quota_unobservable_nonblocking`` (private upstream).

    Drift-pinned by intent: expected local quota unobservability is EVIDENCE, not a hold."""
    if receipt is None:
        return False
    if receipt.quota.status is not EvidenceStatus.UNOBSERVABLE:
        return False
    if set(receipt.quota.reason_codes) - {
        "account_live_quota_receipt_absent",
        "quota_telemetry_unknown",
    }:
        return False
    if (
        receipt.capability.status is not EvidenceStatus.OBSERVED
        or receipt.resource.status is not EvidenceStatus.OBSERVED
    ):
        return False
    if route.capacity_pool is CapacityPool.SUBSCRIPTION_QUOTA:
        return True
    return (
        route.capacity_pool in {CapacityPool.API_PAID_SPEND, CapacityPool.BOOTSTRAP_BUDGET}
        and route.telemetry.quota_source.value == "ledger"
    )


def _blend_evidence_health(freshness_ok: bool, evidence_ref_density: float) -> float:
    base = 1.0 if freshness_ok else 0.0
    return round(0.7 * base + 0.3 * evidence_ref_density, 6)


def _blend_with_pending(base_density: float, equivalence_pending: int) -> float:
    if equivalence_pending <= 0:
        return base_density
    return min(1.0, base_density + 0.1 * equivalence_pending)


def _variant_for_leaf(leaf_key: str, route: PlatformCapabilityRoute) -> DescriptorVariant | None:
    """The DescriptorVariant a ``route_id#variant_id`` leaf names, or None for a base-route leaf."""
    if "#" not in leaf_key:
        return None
    variant_id = leaf_key.split("#", 1)[1]
    for variant in route.descriptor_variants:
        if variant.variant_id == variant_id:
            return variant
    return None


# --- D-resolvers --------------------------------------------------------------------------
def _resolve_d1(
    leaf_key: str, descriptor: ExecutionDescriptor, route: PlatformCapabilityRoute
) -> D1Descriptor:
    """Per-leaf specificity: THIS leaf's own descriptor cell + the meta-modes/features declared FOR
    THIS leaf — NOT the route-wide reachable union (a rich sibling variant must not inflate the base
    leaf's depth; the platform MIN must be able to expose an under-treated leaf)."""
    locality = _locality(route)
    cells = {_cell_key(descriptor, locality)}
    meta_modes = set(_optional_meta_modes(_variant_for_leaf(leaf_key, route)))
    features = _platform_features(route)
    deduped, ran = slicing_test_dedupe(
        sorted(cells | meta_modes | set(features)), policy_signatures=_d4_signatures_for(route)
    )
    cell_count = len(deduped)
    return D1Descriptor(
        leaf=leaf_key,
        specificity_cells=deduped,
        cell_count=cell_count,
        meta_modes=tuple(sorted(meta_modes)),
        platform_features=tuple(sorted(features)),
        depth_class=resolve_depth_class(cell_count),
        dedupe_inert=not ran,
    )


def _resolve_d2(leaf_key: str, route: PlatformCapabilityRoute, now: datetime) -> D2Fitness:
    raw: Mapping[str, Any] = route.capability_scores.model_dump()
    done = 0.0
    required = 0
    provisional_dims: list[str] = []
    dim_scores: list[DimensionalScore] = []
    for dim in (*REQUIRED_CAPABILITY_DIMS, *OPTIONAL_CAPABILITY_DIMS):
        sc = raw.get(dim)
        if not isinstance(sc, Mapping):
            continue  # optional dim absent pre-STEP-0
        score = float(sc["score"])
        confidence = int(sc["confidence"])
        factor = _freshness_factor(sc.get("observed_at"), str(sc["stale_after"]), now)
        done_dim = score * (confidence / CONFIDENCE_MAX) * factor
        done += done_dim
        required += 1
        if confidence == 1:
            provisional_dims.append(dim)
        adapter = _FreshWeightedScore(
            score=done_dim,
            confidence=float(confidence),
            evidence_refs=tuple(sc.get("evidence_refs", ())),
        )
        # demand is non-applicable for this supply-side reuse — pass an explicit 0 sentinel
        dim_scores.append(_dimension_score(dim, 0, [adapter]))
    return D2Fitness(
        leaf=leaf_key,
        done=round(done, 6),
        required=required,
        provisional_dims=tuple(provisional_dims),
        dim_scores=tuple(dim_scores),
    )


def _resolve_d3(leaf_key: str, route: PlatformCapabilityRoute) -> D3SliceFit:
    fit = _fit_classes(route)
    return D3SliceFit(
        leaf=leaf_key,
        cells_present=len(fit),
        cells_required=NUM_ROUTING_CLASSES,
    )


def _removable_quota_reasons(route: PlatformCapabilityRoute) -> frozenset[str]:
    """Mirror of ``_quota_unobservable_removable_reasons``: the blocked_reasons the upstream overlay
    is allowed to clear given a quota-unobservable receipt. A route blocked for ANY OTHER reason
    stays blocked — the quota path must not unblock it."""
    reasons = {"account_live_quota_receipt_absent", "quota_telemetry_unknown"}
    if route.capacity_pool in {CapacityPool.API_PAID_SPEND, CapacityPool.BOOTSTRAP_BUDGET}:
        reasons.add("provider_budget_receipt_absent")
    return frozenset(reasons)


def _resolve_d4(
    leaf_key: str,
    descriptor: ExecutionDescriptor,
    route: PlatformCapabilityRoute,
    receipt: PlatformCapabilityReceipt | None,
    *,
    variant_blocked: bool = False,
) -> D4UsePolicy:
    active_clean = route.route_state is RouteState.ACTIVE and not route.blocked_reasons
    # the quota-unobservable receipt may unblock a route ONLY when EVERY blocked_reason is a
    # removable quota reason (fail-closed): an unrelated blocker (e.g. session_dead) is preserved,
    # matching the upstream overlay which clears only the removable reasons.
    quota_override = (
        bool(route.blocked_reasons)
        and set(route.blocked_reasons) <= _removable_quota_reasons(route)
        and _mirrored_quota_unobservable_nonblocking(route, receipt)
    )
    route_available = active_clean or quota_override
    # a BLOCKED descriptor variant is unavailable even on an active route (fail-closed): its leaf
    # neither counts toward the productive denominator nor can pass.
    available = route_available and not variant_blocked
    unavailability_reason: str | None = None
    if not available:
        if variant_blocked:
            unavailability_reason = "variant_blocked"
        elif route.blocked_reasons:
            unavailability_reason = "; ".join(route.blocked_reasons)
        else:
            unavailability_reason = "route_state_blocked"
    axes = _descriptor_axes(descriptor)  # THIS leaf's own 4 axes (leaf-specific, not route-union)
    fit = _fit_classes(route)
    cells_present = len(fit) * len(axes) if available else 0
    interaction_records: list[str] = []
    leaf_variant = _variant_for_leaf(leaf_key, route)
    ref = getattr(leaf_variant, "interaction_record_ref", None) if leaf_variant else None
    if ref:
        interaction_records.append(str(ref))
    return D4UsePolicy(
        leaf=leaf_key,
        cells_present=cells_present,
        cells_required=NUM_ROUTING_CLASSES * len(axes),
        interaction_records=tuple(interaction_records),
        available=available,
        unavailability_reason=unavailability_reason,
    )


def _resolve_d5(leaf_key: str, route: PlatformCapabilityRoute) -> D5Boundaries:
    fit = _fit_classes(route)
    equivalence_pending = len(getattr(route.quality_envelope, "equivalence_pending", ()) or ())
    return D5Boundaries(
        leaf=leaf_key,
        cells_present=len(fit),
        cells_required=NUM_ROUTING_CLASSES,
        equivalence_pending=equivalence_pending,
    )


# --- per-leaf scoring ---------------------------------------------------------------------
def score_variant_leaf(
    leaf_key: str,
    descriptor: ExecutionDescriptor,
    route: PlatformCapabilityRoute,
    *,
    knobs: EdtKnobs,
    registry: PlatformCapabilityRegistry,
    receipt: PlatformCapabilityReceipt | None = None,
    now: datetime,
    d0_omitted: bool = False,
) -> LeafEdt:
    """Per-leaf D0..D5 descriptors + the two-layer normalization. An omitted/unavailable leaf gets
    every D-descriptor computed for transparency but ``passes=False``.

    Scoring is LEAF-SPECIFIC: D1 (specificity) and D4 (use-policy axes/availability) are computed from
    THIS leaf's own ``descriptor`` (+ its own meta-modes / blocked status), NOT the route-wide reachable
    union — so a rich sibling variant cannot inflate a shallow base leaf, and the platform MIN can
    expose an under-treated leaf. D2/D3/D5 are route-level (capability scores, mutability fit, and
    boundaries are route properties in v1; per-leaf ``score_delta`` differentiation lands with STEP-0).

    ``registry`` is part of the declared public-API contract (the EDT scorer-spec signature); it is
    RESERVED for STEP-0 cross-route resolution (e.g. a variant's ``scores_inherited_from`` provenance)
    and accepted now so callers code against the stable signature."""
    variant = _variant_for_leaf(leaf_key, route)
    variant_blocked = variant is not None and bool(variant.blocked_reasons)
    d1 = _resolve_d1(leaf_key, descriptor, route)
    d2 = _resolve_d2(leaf_key, route, now)
    d3 = _resolve_d3(leaf_key, route)
    d4 = _resolve_d4(leaf_key, descriptor, route, receipt, variant_blocked=variant_blocked)
    d5 = _resolve_d5(leaf_key, route)

    # LAYER 1 — specificity_ratio (cap-scaled D1, fresh-weighted D2 fraction, D5 boundary fraction).
    d1_comp = min(d1.cell_count / knobs.depth_cap, 1.0) if knobs.depth_cap else 0.0
    d2_comp = d2.done / (d2.required * CONFIDENCE_MAX) if d2.required else 0.0
    d5_comp = d5.cells_present / d5.cells_required if d5.cells_required else 0.0
    specificity_num = d1_comp + d2_comp + d5_comp
    specificity_den = 3.0
    specificity_ratio = min(specificity_num / specificity_den, 1.0)

    # LAYER 2 — slice_policy_completeness (FIXED 11-class denominator; SEPARATE division).
    completeness_num = float(d3.cells_present + d4.cells_present)
    completeness_den = float(d3.cells_required + d4.cells_required)
    slice_policy_completeness = (
        min(completeness_num / completeness_den, 1.0) if completeness_den else None
    )

    evidence_ref_density = (
        sum(1 for score in d2.dim_scores if score.evidence_refs) / d2.required
        if d2.required
        else 0.0
    )
    freshness_ok = check_route_freshness(route, now=now).ok
    evidence_health = _blend_evidence_health(freshness_ok, evidence_ref_density)

    base_provisional = len(d2.provisional_dims) / d2.required if d2.required else 0.0
    provisional_density = round(_blend_with_pending(base_provisional, d5.equivalence_pending), 6)

    # provisional evidence (confidence-1 dims) depresses the fresh-weighted D2 component (via the
    # confidence/5 factor in D2.done) and thus the specificity_ratio — flag it so the cap is legible.
    provisional_capped = provisional_density > 0
    d4 = d4.model_copy(update={"provisional_capped": provisional_capped})

    passes = (
        slice_policy_completeness is not None
        and specificity_ratio >= RATIO_THRESHOLD
        and slice_policy_completeness >= COMPLETENESS_THRESHOLD
        and evidence_health >= EVIDENCE_HEALTH_THRESHOLD
        and provisional_density <= PROVISIONAL_DENSITY_THRESHOLD
        and not d0_omitted
        and d4.available
    )

    return LeafEdt(
        leaf=leaf_key,
        platform=route.platform.value,
        d1=d1,
        d2=d2,
        d3=d3,
        d4=d4,
        d5=d5,
        d0_omitted=d0_omitted,
        specificity_ratio=round(specificity_ratio, 6),
        slice_policy_completeness=round(slice_policy_completeness, 6)
        if slice_policy_completeness is not None
        else None,
        specificity_num=round(specificity_num, 6),
        specificity_den=specificity_den,
        completeness_num=completeness_num,
        completeness_den=completeness_den,
        evidence_health=evidence_health,
        provisional_density=provisional_density,
        passes=passes,
        defense_caveat=_LEAF_DEFENSE_CAVEATS,
    )


# --- platform aggregation -----------------------------------------------------------------
def _min_optional(values: Sequence[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return min(present) if present else None


def _max_optional(values: Sequence[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def score_platform(
    platform: str,
    leaves: Sequence[LeafEdt],
    *,
    knobs: EdtKnobs,
    observed_platform_count: int = 0,
    omitted_platforms: tuple[str, ...] = (),
) -> EdtMeasure:
    """Aggregate a platform's leaves (MIN ratio/completeness/evidence, MAX provisional, MIN-by-rank
    depth_class). An OMITTED platform is scored with empty ``leaves`` -> ``platform_passes=False``.

    Matches the declared public-API signature ``(platform, leaves, *, knobs)``: ``expected_platform_set``
    and ``expected_platform_members`` are read from ``knobs`` (so a contract caller needs only knobs),
    while ``observed_platform_count``/``omitted_platforms`` are OPTIONAL registry-global context that
    ``score_edt`` supplies for the full D0 canary (a standalone call defaults them to 0/()."""
    platform_ratio = _min_optional([leaf.specificity_ratio for leaf in leaves])
    platform_completeness = _min_optional([leaf.slice_policy_completeness for leaf in leaves])
    platform_evidence = _min_optional([leaf.evidence_health for leaf in leaves])
    platform_provisional = _max_optional([leaf.provisional_density for leaf in leaves])

    depth_ranks = {"trivial": 0, "bounded": 1, "rich": 2}
    rank_to_class = {rank: name for name, rank in depth_ranks.items()}
    leaf_ranks = [depth_ranks.get(leaf.d1.depth_class, 0) for leaf in leaves if leaf.d1 is not None]
    depth_class = rank_to_class[min(leaf_ranks)] if leaf_ranks else "trivial"

    any_available = any(leaf.d4.available for leaf in leaves if leaf.d4 is not None)
    any_omitted = any(leaf.d0_omitted for leaf in leaves)
    platform_passes = (
        platform_ratio is not None
        and platform_ratio >= RATIO_THRESHOLD
        and platform_completeness is not None
        and platform_completeness >= COMPLETENESS_THRESHOLD
        and platform_evidence is not None
        and platform_evidence >= EVIDENCE_HEALTH_THRESHOLD
        and platform_provisional is not None
        and platform_provisional <= PROVISIONAL_DENSITY_THRESHOLD
        and any_available
        and not any_omitted
    )

    return EdtMeasure(
        platform=platform,
        platform_ratio=platform_ratio,
        platform_completeness=platform_completeness,
        platform_evidence_health=platform_evidence,
        platform_provisional_density=platform_provisional,
        depth_class=depth_class,
        platform_passes=platform_passes,
        leaves=tuple(leaves),
        expected_platform_set=knobs.expected_platform_set,
        expected_platform_members=knobs.expected_platform_members,
        observed_platform_count=observed_platform_count,
        omitted_platforms=omitted_platforms,
        build_defense_caveat=_BUILD_DEFENSE_CAVEATS,
    )


# --- top-level entry point ----------------------------------------------------------------
def score_edt(
    registry: PlatformCapabilityRegistry,
    *,
    knobs_path: Path | None = None,
    receipts: Mapping[str, PlatformCapabilityReceipt] | None = None,
    now: datetime | None = None,
) -> tuple[EdtMeasure, ...]:
    """Score the (post-overlay) registry into one :class:`EdtMeasure` per platform prefix, sorted by
    ``(depth_class_rank, platform_ratio)`` descending. The caller MUST pass the post-receipt-overlay
    registry; this function is pure (it does not load or mutate the registry)."""
    knobs = load_edt_knobs(knobs_path)
    resolved_now = ensure_utc(now or datetime.now(UTC))
    route_map = registry.route_map()

    observed_platforms = {route.platform.value for route in registry.routes}
    omitted_platforms = tuple(sorted(set(knobs.expected_platform_members) - observed_platforms))

    def _receipt_for(route: PlatformCapabilityRoute) -> PlatformCapabilityReceipt | None:
        # The repository loader (load_platform_capability_receipts) keys receipts by PLATFORM and
        # carries route coverage in receipt.routes — match that shape, not a route_id key.
        if not receipts:
            return None
        candidate = receipts.get(route.platform.value)
        if candidate is not None and route.route_id in candidate.routes:
            return candidate
        return None

    leaves_by_platform: dict[str, list[LeafEdt]] = {}
    for leaf_key, descriptor in materialize_descriptor_leaves(registry).items():
        route = route_map[leaf_key.split("#")[0]]
        platform = route.platform.value
        leaf = score_variant_leaf(
            leaf_key,
            descriptor,
            route,
            knobs=knobs,
            registry=registry,
            receipt=_receipt_for(route),
            now=resolved_now,
            d0_omitted=platform in omitted_platforms,
        )
        leaves_by_platform.setdefault(platform, []).append(leaf)

    def _measure(platform: str, leaves: list[LeafEdt]) -> EdtMeasure:
        return score_platform(
            platform,
            leaves,
            knobs=knobs,
            observed_platform_count=len(observed_platforms),
            omitted_platforms=omitted_platforms,
        )

    measures = [_measure(platform, leaves) for platform, leaves in leaves_by_platform.items()]
    # D0 canary: an EXPECTED-but-absent platform surfaces as an explicit FAILING measure with no
    # leaves (not silently dropped) — the omitted-cap floor made legible to downstream consumers.
    measures.extend(_measure(platform, []) for platform in omitted_platforms)
    measures.sort(key=lambda m: (platform_depth_rank(m), m.platform_ratio or 0.0), reverse=True)
    return tuple(measures)
