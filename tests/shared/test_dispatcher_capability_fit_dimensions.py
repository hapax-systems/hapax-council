"""The conditional execution-axis dispatcher dimensions (effort_fit / context_mode_fit).

Proves the capability-dispatcher-dims slice: a task can DEMAND a reasoning-effort level and a
context-window mode, the dispatcher scores routes on base-or-variant SATISFIABILITY, and the
LAUNCH result resolves the matching descriptor leaf — WITHOUT perturbing undemanded dispatch
(the non-perturbation regression pin) and WITHOUT making variant leaves first-class candidates
(routes stay candidates; the leaf is advisory result metadata).

Self-contained per the repo testing convention (no shared conftest fixtures).
"""

from __future__ import annotations

from datetime import UTC, datetime

from shared.dispatcher_policy import (
    DIMENSION_WEIGHTS,
    DispatchAction,
    DispatchRequest,
    QuotaSpendState,
    RouteCapabilityState,
    _aggregate_score,
    _effort_fit_score,
    _resolve_descriptor_leaf,
    _score_candidate,
    evaluate_dispatch_policy,
)
from shared.platform_capability_registry import (
    PlatformCapabilityRoute,
    build_supply_vector,
    load_platform_capability_registry,
    materialize_variant_leaf,
)
from shared.route_metadata_schema import DemandVector, build_demand_vector

NOW = datetime(2026, 5, 9, 22, 30, tzinfo=UTC)

# The 7 legacy scoring dimensions, in order — the non-perturbation contract.
_LEGACY_DIMENSIONS = (
    "grounding_governance_fit",
    "implementation_architecture_fit",
    "context_tools_execution_fit",
    "verification_fit",
    "coordination_worktree_fit",
    "historical_local_calibration",
    "quota_latency_scarcity",
)


def _capability(**overrides: object) -> RouteCapabilityState:
    payload = {
        "route_id": "codex.headless.full",
        "supported": True,
        "route_state": "active",
        "blocked_reasons": (),
        "capacity_pool": "subscription_quota",
        "authority_ceiling": "authoritative",
        "privacy_posture": "provider_private",
        "eligible_quality_floors": (
            "frontier_required",
            "frontier_review_required",
            "deterministic_ok",
        ),
        "explicit_equivalence_records": (),
        "excluded_task_classes": (),
        "mutability": {
            "vault_docs": True,
            "source": True,
            "runtime": False,
            "public": False,
            "provider_spend": False,
        },
        "freshness_ok": True,
        "freshness_errors": (),
        "telemetry_quota_source": "manual",
        "telemetry_resource_source": "local_probe",
    }
    payload.update(overrides)
    return RouteCapabilityState.model_validate(payload)


def _quota(**overrides: object) -> QuotaSpendState:
    payload = {
        "available": True,
        "budget_ledger_stale": False,
        "paid_api_budget_state": None,
        "local_resource_state": "green",
        "paid_api_route_eligible": None,
        "paid_api_blocking_reasons": (),
        "paid_route_eligibility_state": None,
        "paid_route_eligibility_reasons": (),
        "evidence_refs": (),
    }
    payload.update(overrides)
    return QuotaSpendState.model_validate(payload)


def _request(**overrides: object) -> DispatchRequest:
    payload: dict[str, object] = {
        "task_id": "policy-test",
        "lane": "cx-green",
        "platform": "codex",
        "mode": "headless",
        "profile": "full",
        "route_id": "codex.headless.full",
        "task_status": "claimed",
        "assigned_to": "cx-green",
        "authority_case": "CASE-TEST-001",
        "route_metadata_status": "explicit",
        "route_metadata_hold_reasons": (),
        "route_metadata_missing_fields": (),
        "route_metadata_validation_errors": (),
        "quality_floor": "frontier_required",
        "authority_level": "authoritative",
        "mutation_surface": "source",
        "mutation_scope_refs": ("shared/dispatcher_policy.py",),
        "risk_flags": {
            "governance_sensitive": False,
            "privacy_or_secret_sensitive": False,
            "public_claim_sensitive": False,
            "aesthetic_theory_sensitive": False,
            "audio_or_live_egress_sensitive": False,
            "provider_billing_sensitive": False,
        },
        "context_shape": {},
        "route_constraints": {},
        "review_requirement": {},
        "capability": _capability(),
        "quota": _quota(),
        "resource_state_refs": (),
        "rollback_mode": False,
        "legacy_route_supported": True,
        "legacy_route_mutable": True,
    }
    payload.update(overrides)
    return DispatchRequest.model_validate(payload)


def _demand(**overrides: object) -> DemandVector:
    payload: dict[str, object] = {
        "route_metadata_schema": 1,
        "quality_floor": "frontier_required",
        "authority_level": "authoritative",
        "mutation_surface": "source",
        "mutation_scope_refs": ["shared/dispatcher_policy.py"],
        "risk_flags": {
            "governance_sensitive": True,
            "privacy_or_secret_sensitive": False,
            "public_claim_sensitive": False,
            "aesthetic_theory_sensitive": False,
            "audio_or_live_egress_sensitive": False,
            "provider_billing_sensitive": False,
        },
        "context_shape": {
            "codebase_locality": "cross_module",
            "vault_context_required": True,
            "external_docs_required": False,
            "currentness_required": False,
        },
        "verification_surface": {
            "deterministic_tests": ["uv run pytest tests/shared"],
            "static_checks": ["uv run ruff check shared/dispatcher_policy.py"],
            "runtime_observation": [],
            "operator_only": False,
        },
        "route_constraints": {},
        "review_requirement": {},
        "task_id": "policy-test",
        "authority_case": "CASE-TEST-001",
    }
    payload.update(overrides)
    return build_demand_vector(payload, observed_at=NOW)


def _active_route(route_id: str, *, score: int, confidence: int = 4) -> PlatformCapabilityRoute:
    """A registry route forced ACTIVE with fresh evidence and uniform capability scores — so a
    SELECTION golden exercises selection, not a route_state veto. The route keeps its
    descriptor_variants (e.g. claude.headless.opus -> opus@extended_1m)."""
    registry = load_platform_capability_registry()
    payload = registry.require(route_id).model_dump(mode="json")
    payload["route_state"] = "active"
    payload["blocked_reasons"] = []
    for surface in ("capability", "quota", "resource", "provider_docs"):
        payload["freshness"][f"{surface}_checked_at"] = "2026-05-09T22:00:00Z"
        payload["freshness"]["evidence"][surface] = {
            "evidence_refs": [f"test:{route_id}:{surface}"],
            "blocked_reasons": [],
        }
    for item in payload["capability_scores"].values():
        item["score"] = score
        item["confidence"] = confidence
        item["observed_at"] = "2026-05-09T22:00:00Z"
    for tool in payload["tool_state"]:
        tool["observed_at"] = "2026-05-09T22:00:00Z"
    return PlatformCapabilityRoute.model_validate(payload)


def _dimensional_request(
    route_id: str,
    *,
    score: int,
    confidence: int = 4,
    demand: DemandVector | None = None,
) -> DispatchRequest:
    parts = route_id.split(".")
    return _request(
        route_id=route_id,
        platform=parts[0],
        mode=parts[1],
        profile=parts[2],
        capability=_capability(route_id=route_id),
        demand_vector=demand or _demand(),
        supply_vector=build_supply_vector(
            _active_route(route_id, score=score, confidence=confidence), now=NOW
        ),
    )


# ----------------------------------------------------------------------------------
# NON-PERTURBATION REGRESSION PIN — the load-bearing safety test
# ----------------------------------------------------------------------------------
def test_undemanded_scoring_is_byte_identical_to_pre_change() -> None:
    """An undemanded task (no effort_demand / context_mode_demand) MUST score exactly as it did
    before this slice: the 7 legacy dimensions in order, NO conditional dims, and the frozen
    aggregate (4.06 for codex.headless.full @ score 4, captured from origin/main @ 59a404f8)."""
    request = _dimensional_request("codex.headless.full", score=4)
    scores = _score_candidate(request)
    assert tuple(s.dimension for s in scores) == _LEGACY_DIMENSIONS
    assert "effort_fit" not in {s.dimension for s in scores}
    assert "context_mode_fit" not in {s.dimension for s in scores}
    assert _aggregate_score(scores) == 4.06


def test_legacy_dimension_weights_unchanged_and_new_keys_present() -> None:
    expected_legacy = {
        "grounding_governance_fit": 24,
        "implementation_architecture_fit": 20,
        "context_tools_execution_fit": 18,
        "verification_fit": 14,
        "coordination_worktree_fit": 10,
        "historical_local_calibration": 8,
        "quota_latency_scarcity": 6,
    }
    for dimension, weight in expected_legacy.items():
        assert DIMENSION_WEIGHTS[dimension] == weight
    assert DIMENSION_WEIGHTS["effort_fit"] == 12
    assert DIMENSION_WEIGHTS["context_mode_fit"] == 12


# ----------------------------------------------------------------------------------
# SELECTION GOLDENS (active/synthetic routes; the live opus/sonnet are blocked)
# ----------------------------------------------------------------------------------
def test_extended_1m_demand_selects_the_extended_1m_leaf() -> None:
    demand = _demand(task_demand={"context_mode_demand": "extended_1m"})
    opus = _dimensional_request("claude.headless.opus", score=5, demand=demand)
    standard_sibling = _dimensional_request("claude.headless.sonnet", score=5, demand=demand)

    # the conditional dimension discriminates: opus reaches extended_1m via its variant, sonnet does not
    opus_fit = {s.dimension: s.score for s in _score_candidate(opus)}
    sibling_fit = {s.dimension: s.score for s in _score_candidate(standard_sibling)}
    assert opus_fit["context_mode_fit"] == 5.0
    assert sibling_fit["context_mode_fit"] == 1.0

    decision = evaluate_dispatch_policy(opus, candidate_requests=(opus, standard_sibling), now=NOW)
    assert decision.action is DispatchAction.LAUNCH
    assert decision.route_id == "claude.headless.opus"
    assert decision.selected_descriptor_leaf == "claude.headless.opus#opus@extended_1m"


def test_effort_low_demand_resolves_the_effort_low_leaf() -> None:
    """The effort axis shares the leaf resolver proven through a full LAUNCH by the extended_1m
    golden; here we pin the effort-specific discrimination on the REAL registry variant. (The
    live claude.headless.sonnet is a fallback/support profile the policy gate correctly refuses
    under an authoritative demand, so this asserts the resolver + score directly, not a LAUNCH.)"""
    demand = _demand(task_demand={"effort_demand": "low"})
    sonnet = _dimensional_request("claude.headless.sonnet", score=5, demand=demand)

    # downward cost discrimination: the resolver picks the CHEAPEST leaf meeting 'low' — the
    # effort_low variant, not the xhigh base.
    assert _resolve_descriptor_leaf(sonnet) == "claude.headless.sonnet#sonnet@effort_low"
    fit = {s.dimension: s.score for s in _score_candidate(sonnet)}
    assert fit["effort_fit"] == 5.0  # xhigh base meets-or-exceeds the 'low' demand


def test_standard_context_mode_demand_does_not_emit_context_mode_fit() -> None:
    """'standard' (and 'not_applicable') is the floor every base satisfies — emitting a fit
    dimension for it would perturb every task, so it is treated as no demand."""
    for value in ("standard", "not_applicable"):
        demand = _demand(task_demand={"context_mode_demand": value})
        request = _dimensional_request("claude.headless.opus", score=5, demand=demand)
        assert tuple(s.dimension for s in _score_candidate(request)) == _LEGACY_DIMENSIONS


def test_none_supply_descriptor_fails_closed_omitting_the_dimension() -> None:
    """A present demand against a route whose supply cannot describe its execution axes omits the
    conditional dimension rather than raising — guards live dispatch against AttributeError."""
    demand = _demand(task_demand={"context_mode_demand": "extended_1m"})
    request = _dimensional_request("claude.headless.opus", score=5, demand=demand)
    assert request.supply_vector is not None
    no_descriptor = request.model_copy(
        update={
            "supply_vector": request.supply_vector.model_copy(update={"supply_descriptor": None})
        }
    )
    dims = {s.dimension for s in _score_candidate(no_descriptor)}
    assert "context_mode_fit" not in dims
    assert _resolve_descriptor_leaf(no_descriptor) is None


def test_leaf_resolution_is_consistent_with_the_satisfiability_score() -> None:
    """When context_mode_fit scored 5.0 on the launching route, the resolved leaf's materialized
    context_mode equals the demand (score and resolver read the SAME supply_descriptor)."""
    demand = _demand(task_demand={"context_mode_demand": "extended_1m"})
    opus = _dimensional_request("claude.headless.opus", score=5, demand=demand)
    sibling = _dimensional_request("claude.headless.sonnet", score=5, demand=demand)
    decision = evaluate_dispatch_policy(opus, candidate_requests=(opus, sibling), now=NOW)

    leaf = decision.selected_descriptor_leaf
    assert leaf is not None
    _, _, variant_id = leaf.partition("#")
    route = _active_route("claude.headless.opus", score=5)
    variant = next(v for v in route.descriptor_variants if v.variant_id == variant_id)
    assert materialize_variant_leaf(route, variant).context_mode.value == "extended_1m"


def test_blocked_route_vetoes_and_resolves_no_leaf() -> None:
    """Veto inheritance: a route the policy gate vetoes cannot be selected, so its variant can
    never be reached — proving the variant inherits the route's eligibility wholesale."""
    demand = _demand(task_demand={"context_mode_demand": "extended_1m"})
    request = _dimensional_request("claude.headless.opus", score=5, demand=demand).model_copy(
        update={"capability": _capability(route_id="claude.headless.opus", supported=False)}
    )
    decision = evaluate_dispatch_policy(request, candidate_requests=(request,), now=NOW)
    assert decision.action is not DispatchAction.LAUNCH
    assert decision.selected_descriptor_leaf is None


# ----------------------------------------------------------------------------------
# UNIT: the effort ladder
# ----------------------------------------------------------------------------------
def test_effort_fit_score_is_meet_or_exceed() -> None:
    # reaches the demand or stronger -> 5.0
    assert _effort_fit_score("low", ("xhigh", "low")) == 5.0
    assert _effort_fit_score("high", ("high",)) == 5.0
    # exactly one rung short -> 3.0  (best reachable = high, demand = xhigh)
    assert _effort_fit_score("xhigh", ("high",)) == 3.0
    # two or more rungs short -> 1.0  (best reachable = low, demand = high)
    assert _effort_fit_score("high", ("low",)) == 1.0
    # unknown demand string fails closed
    assert _effort_fit_score("galaxy", ("xhigh",)) == 1.0
    # no reachable efforts fails closed
    assert _effort_fit_score("low", ()) == 1.0
