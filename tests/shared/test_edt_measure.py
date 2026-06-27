"""EDT scorer — shared/edt_measure.py (equal-depth-of-treatment engine, v1 floor).

Self-contained per the repo testing convention (no shared conftest, synchronous, unittest.mock
only where unavoidable). Builds test registries by loading the REAL 13-route registry (the
PlatformCapabilityRegistry validator requires the full required_route_ids set) and mutating
specific routes — mirroring the `_active_route` freshening idiom from
tests/shared/test_dispatcher_capability_fit_dimensions.py so tests exercise SCORING, not vetoes.

The two-layer-never-collapsed pin (test #1) follows the codebase convention from
test_undemanded_scoring_is_byte_identical_to_pre_change: a structural assertion is load-bearing,
a frozen numeric anchor is a drift tripwire captured after first green.
"""

from __future__ import annotations

import tempfile
import typing
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

import pytest

from shared.edt_measure import (
    NUM_ROUTING_CLASSES,
    ROUTING_CLASSES,
    EdtKnobs,
    _resolve_d2,
    load_edt_knobs,
    normalize_routing_class,
    platform_depth_rank,
    resolve_depth_class,
    score_edt,
    score_platform,
    score_variant_leaf,
    slicing_test_dedupe,
)
from shared.platform_capability_receipts import (
    CliEvidence,
    EvidenceStatus,
    PlatformCapabilityReceipt,
    ProviderDocsEvidence,
    SurfaceEvidence,
    WrapperEvidence,
)
from shared.platform_capability_registry import (
    PlatformCapabilityRegistry,
    load_platform_capability_registry,
)

NOW = datetime(2026, 6, 27, 5, 0, tzinfo=UTC)
# 1 minute before NOW: inside even the shortest surface stale window (quota=15m on some routes)
_FRESH_TS = "2026-06-27T04:59:00Z"


# --------------------------------------------------------------------------------------------
# Registry construction: load the real 13-route registry, force every route ACTIVE + fresh +
# uniform scores, then apply per-route mutations. Mirrors _active_route but over all routes.
# --------------------------------------------------------------------------------------------
def _fresh_payload(*, score: int = 4, confidence: int = 4) -> dict:
    registry = load_platform_capability_registry()
    payload = registry.model_dump(mode="json")
    for route in payload["routes"]:
        route["route_state"] = "active"
        route["blocked_reasons"] = []
        # force telemetry + privacy healthy so check_route_freshness passes for the "fresh" baseline
        # (some real routes — e.g. the aspirational opus — carry unknown telemetry/privacy upstream)
        route["privacy_posture"] = "provider_private"
        route["telemetry"] = {
            "quota_source": "manual",
            "cost_source": "estimated",
            "resource_source": "local_probe",
        }
        for surface in ("capability", "quota", "resource", "provider_docs"):
            route["freshness"][f"{surface}_checked_at"] = _FRESH_TS
            route["freshness"]["evidence"][surface] = {
                "evidence_refs": [f"test:{route['route_id']}:{surface}"],
                "blocked_reasons": [],
            }
        for item in route["capability_scores"].values():
            item["score"] = score
            item["confidence"] = confidence
            item["observed_at"] = _FRESH_TS
            if not item.get("evidence_refs"):
                item["evidence_refs"] = ["test:capability-evidence"]
        for tool in route.get("tool_state", []):
            tool["observed_at"] = _FRESH_TS
    return payload


def _route_in(payload: dict, route_id: str) -> dict:
    for route in payload["routes"]:
        if route["route_id"] == route_id:
            return route
    raise KeyError(route_id)


_VARIANT_KNOBS: tuple[dict[str, str], ...] = tuple(
    {"effort": e, "context_mode": c, "fast_mode": f}
    for f in ("off", "fast", "not_applicable")
    for c in ("standard", "extended_1m", "not_applicable")
    for e in ("none", "low", "medium", "high", "xhigh", "max")
)  # 54 distinct (effort, context_mode, fast_mode) tuples -> distinct D1 cells


def _add_distinct_variants(route: dict, n: int) -> None:
    """Attach n non-inert descriptor variants with distinct knob tuples (distinct D1 cells)."""
    variants = []
    for i, knobs in enumerate(_VARIANT_KNOBS[:n]):
        variants.append(
            {
                "variant_id": f"v{i}",
                "knobs_override": dict(knobs),
                "score_delta": {},
                "scores_inherited_from": None,
                "blocked_reasons": [],
            }
        )
    route["descriptor_variants"] = variants


def _set_scores(route: dict, *, score: int, confidence: int) -> None:
    for item in route["capability_scores"].values():
        item["score"] = score
        item["confidence"] = confidence
        item["observed_at"] = _FRESH_TS
        if not item.get("evidence_refs"):
            item["evidence_refs"] = ["test:capability-evidence"]


def _registry(payload: dict) -> PlatformCapabilityRegistry:
    return PlatformCapabilityRegistry.model_validate(payload)


def _by_platform(measures: tuple, platform: str):
    for m in measures:
        if m.platform == platform:
            return m
    raise KeyError(platform)


def _leaf_for(measures: tuple, leaf_key: str):
    for m in measures:
        for leaf in m.leaves:
            if leaf.leaf == leaf_key:
                return leaf
    raise KeyError(leaf_key)


_CLAUDE_ROUTES = (
    "claude.headless.full",
    "claude.headless.haiku",
    "claude.headless.opus",
    "claude.headless.sonnet",
    "claude.interactive.full",
)


def _knobs_file(members: list[str], *, expected_set: int = 12, depth_cap: int = 20) -> Path:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8")
    tmp.write(f"expected_platform_set: {expected_set}\n")
    tmp.write("expected_platform_members:\n")
    for m in members:
        tmp.write(f"  - {m}\n")
    tmp.write(f"depth_cap: {depth_cap}\n")
    tmp.write("retired_phantoms: []\n")
    tmp.close()
    return Path(tmp.name)


_OBSERVED_MEMBERS = ["antigrav", "api", "claude", "codex", "glmcp", "local_tool", "vibe", "gemini"]

# Frozen drift anchors for the 24-cell opus leaf at score=4/confidence=4 (captured after first green):
# specificity = mean(d1_comp=1.0, d2_comp~0.64, d5_comp=8/11) ~= 0.789 ; completeness = 8/11 ~= 0.727.
_ANCHOR_SPECIFICITY = 0.789
_ANCHOR_COMPLETENESS = 0.727


# --------------------------------------------------------------------------------------------
# 1. The two-layer "never collapsed" invariant
# --------------------------------------------------------------------------------------------
def test_specificity_and_slice_completeness_are_never_collapsed() -> None:
    payload = _fresh_payload(score=4, confidence=4)
    _add_distinct_variants(_route_in(payload, "claude.headless.opus"), 24)
    measures = score_edt(_registry(payload), knobs_path=_knobs_file(_OBSERVED_MEMBERS), now=NOW)
    leaf = _leaf_for(measures, "claude.headless.opus")  # the enriched (24-cell) leaf

    assert leaf.specificity_ratio is not None
    assert leaf.slice_policy_completeness is not None
    # the two layers are computed by SEPARATE divisions — they are distinct quantities
    assert leaf.specificity_ratio != leaf.slice_policy_completeness
    # a single-collapse analog over the combined numerators/denominators differs from BOTH layers
    # (the tripwire: collapsing the two layers into one division changes the result)
    assert leaf.specificity_num is not None and leaf.specificity_den is not None
    assert leaf.completeness_num is not None and leaf.completeness_den is not None
    collapsed = (leaf.specificity_num + leaf.completeness_num) / (
        leaf.specificity_den + leaf.completeness_den
    )
    assert abs(collapsed - leaf.specificity_ratio) > 1e-9
    assert abs(collapsed - leaf.slice_policy_completeness) > 1e-9

    # loose frozen anchor (drift canary; the never-collapsed structural assertion above is the
    # load-bearing guarantee). Pinned loosely to survive cosmetic refactors per the task spec.
    # On the 24-cell opus leaf: d1_comp saturates (min(24/20,1)=1.0).
    assert leaf.d1 is not None and leaf.d1.depth_class == "rich"
    assert leaf.specificity_ratio == pytest.approx(_ANCHOR_SPECIFICITY, abs=0.03)
    assert leaf.slice_policy_completeness == pytest.approx(_ANCHOR_COMPLETENESS, abs=0.01)


# --------------------------------------------------------------------------------------------
# 2. Disparity-awareness: depth_class rank is the PRIMARY selection key
# --------------------------------------------------------------------------------------------
def test_rich_platform_beats_trivial_platform_on_depth_class_rank() -> None:
    payload = _fresh_payload()
    for rid in _CLAUDE_ROUTES:  # the platform depth_class is MIN over leaves -> enrich every route
        rich = _route_in(payload, rid)
        _add_distinct_variants(rich, 24)
        _set_scores(rich, score=4, confidence=4)
    trivial = _route_in(payload, "local_tool.local.worker")
    trivial["descriptor_variants"] = []
    _set_scores(trivial, score=2, confidence=2)

    measures = score_edt(_registry(payload), knobs_path=_knobs_file(_OBSERVED_MEMBERS), now=NOW)
    claude = _by_platform(measures, "claude")
    local = _by_platform(measures, "local_tool")

    assert claude.depth_class == "rich"
    assert local.depth_class == "trivial"
    assert platform_depth_rank(claude) > platform_depth_rank(local)
    # score_edt sorts by (depth_class_rank, ratio) descending — rich claude ranks before trivial local
    order = [m.platform for m in measures]
    assert order.index("claude") < order.index("local_tool")


# --------------------------------------------------------------------------------------------
# 3. confidence-1 dims are denominator-provisional
# --------------------------------------------------------------------------------------------
def test_confidence_1_dims_marked_denominator_provisional() -> None:
    payload = _fresh_payload(score=5, confidence=5)
    route = _route_in(payload, "claude.headless.opus")
    # one dim confidence-1 (still has evidence_refs from _fresh, so it validates)
    route["capability_scores"]["grounding"]["confidence"] = 1
    measures = score_edt(_registry(payload), knobs_path=_knobs_file(_OBSERVED_MEMBERS), now=NOW)
    leaf = _leaf_for(measures, "claude.headless.opus")
    assert leaf.d2 is not None
    assert "grounding" in leaf.d2.provisional_dims
    assert leaf.provisional_density is not None and leaf.provisional_density > 0

    # >30% of dims confidence-1 -> provisional_density gate violated -> passes False
    payload2 = _fresh_payload(score=5, confidence=5)
    route2 = _route_in(payload2, "claude.headless.opus")
    dims = list(route2["capability_scores"].keys())
    for dim in dims[: (len(dims) // 2) + 1]:
        route2["capability_scores"][dim]["confidence"] = 1
    leaf2 = _leaf_for(
        score_edt(_registry(payload2), knobs_path=_knobs_file(_OBSERVED_MEMBERS), now=NOW),
        "claude.headless.opus",
    )
    assert leaf2.provisional_density is not None and leaf2.provisional_density > 0.30
    assert leaf2.passes is False


# --------------------------------------------------------------------------------------------
# 4. D0 exogenous floor blocks an omitted platform (read from knobs, not REQUIRED_ROUTE_IDS)
# --------------------------------------------------------------------------------------------
def test_exogenous_denominator_floor_blocks_omitted_platform() -> None:
    payload = _fresh_payload()
    members = [*_OBSERVED_MEMBERS, "phantom_co"]
    measures = score_edt(_registry(payload), knobs_path=_knobs_file(members), now=NOW)
    any_measure = measures[0]
    assert "phantom_co" in any_measure.omitted_platforms

    # the omitted platform surfaces as an EXPLICIT failing measure (not silently dropped)
    phantom = _by_platform(measures, "phantom_co")
    assert phantom.platform_passes is False
    assert phantom.leaves == ()

    # mutating the knobs members changes the omitted set while the registry is fixed
    measures_no_phantom = score_edt(
        _registry(payload), knobs_path=_knobs_file(_OBSERVED_MEMBERS), now=NOW
    )
    assert "phantom_co" not in measures_no_phantom[0].omitted_platforms


# --------------------------------------------------------------------------------------------
# 5. FIXED 11-class denominator, identical for bare and rich leaves
# --------------------------------------------------------------------------------------------
def test_fixed_11_class_denominator_identical_for_bare_and_rich() -> None:
    payload = _fresh_payload()
    bare = _route_in(payload, "claude.headless.haiku")
    bare["descriptor_variants"] = []
    rich = _route_in(payload, "claude.headless.opus")
    _add_distinct_variants(rich, 8)

    measures = score_edt(_registry(payload), knobs_path=_knobs_file(_OBSERVED_MEMBERS), now=NOW)
    all_leaves = [leaf for m in measures for leaf in m.leaves]
    for leaf in all_leaves:
        if leaf.d3 is not None:
            assert leaf.d3.cells_required == NUM_ROUTING_CLASSES == 11
        if leaf.d4 is not None and leaf.d4.available:
            assert leaf.d4.cells_required % NUM_ROUTING_CLASSES == 0


# --------------------------------------------------------------------------------------------
# 6. The slicing test dedupe
# --------------------------------------------------------------------------------------------
def test_slicing_test_merges_policy_identical_cells() -> None:
    sigs = {
        "cellA": ("use",) * 11,
        "cellB": ("use",) * 11,  # identical signature -> merges with A
        "cellC": ("use",) * 10 + ("dont_use",),  # differs in one class -> stays
    }
    deduped, ran = slicing_test_dedupe(["cellA", "cellB", "cellC"], policy_signatures=sigs)
    assert ran is True
    assert len(deduped) == 2  # A/B merged, C distinct

    # pre-STEP-0: no signatures -> conservative, no merge
    deduped2, ran2 = slicing_test_dedupe(["cellA", "cellB", "cellC"], policy_signatures=None)
    assert ran2 is False
    assert len(deduped2) == 3


# --------------------------------------------------------------------------------------------
# 7. Availability pre-filter (task-fit SPLIT from availability)
# --------------------------------------------------------------------------------------------
def test_availability_pre_filter_excludes_unavailable_leaf() -> None:
    payload = _fresh_payload()
    blocked = _route_in(payload, "vibe.headless.full")
    blocked["route_state"] = "blocked"
    blocked["blocked_reasons"] = ["test: forced blocked"]
    measures = score_edt(_registry(payload), knobs_path=_knobs_file(_OBSERVED_MEMBERS), now=NOW)
    vibe = _by_platform(measures, "vibe")
    for leaf in vibe.leaves:
        if leaf.d4 is not None:
            assert leaf.d4.available is False
            assert leaf.d4.unavailability_reason is not None


# --------------------------------------------------------------------------------------------
# 8. provisional_density caps the ratio below threshold
# --------------------------------------------------------------------------------------------
def test_provisional_density_caps_ratio_below_threshold() -> None:
    payload = _fresh_payload(score=5, confidence=5)
    route = _route_in(payload, "claude.headless.opus")
    _add_distinct_variants(route, 24)
    # make MANY dims confidence-1 so provisional_density is high
    for dim in list(route["capability_scores"].keys()):
        route["capability_scores"][dim]["confidence"] = 1
    leaf = _leaf_for(
        score_edt(_registry(payload), knobs_path=_knobs_file(_OBSERVED_MEMBERS), now=NOW),
        "claude.headless.opus",
    )
    assert leaf.provisional_density is not None and leaf.provisional_density > 0.30
    assert leaf.passes is False
    assert leaf.d4 is not None and leaf.d4.provisional_capped is True


# --------------------------------------------------------------------------------------------
# 9. normalize_routing_class collapses the alias map
# --------------------------------------------------------------------------------------------
def test_normalize_routing_class_collapses_aliases() -> None:
    aliases = {
        "source_patch": "source_other",
        "source_mutation": "source_other",
        "governance": "source_governance",
        "runtime": "runtime_ops",
        "public_claim": "public_surface",
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
        "python": "source_python",
        "source": "source_other",
    }
    for alias, canonical in aliases.items():
        assert normalize_routing_class(alias) == canonical
    for canonical in ROUTING_CLASSES:
        assert normalize_routing_class(canonical) == canonical
    assert normalize_routing_class("totally-unknown-thing") == "unknown"


# --------------------------------------------------------------------------------------------
# 10. depth_class buckets on cardinality
# --------------------------------------------------------------------------------------------
def test_depth_class_buckets_on_cardinality() -> None:
    assert resolve_depth_class(4) == "trivial"
    assert resolve_depth_class(5) == "bounded"
    assert resolve_depth_class(20) == "bounded"
    assert resolve_depth_class(21) == "rich"


# --------------------------------------------------------------------------------------------
# 11. STEP-0 fields are consumed when present and None-safe when absent
# --------------------------------------------------------------------------------------------
def test_step0_fields_consumed_optional_and_none_safe() -> None:
    # absent today: score_edt must not raise; getattr-optional defaults; defense_caveat populated
    payload = _fresh_payload()
    measures = score_edt(_registry(payload), knobs_path=_knobs_file(_OBSERVED_MEMBERS), now=NOW)
    leaf = _by_platform(measures, "claude").leaves[0]
    assert leaf.d1 is not None
    assert leaf.d1.meta_modes == ()
    assert leaf.d1.dedupe_inert is True
    assert leaf.d4 is not None and leaf.d4.interaction_records == ()
    assert leaf.d5 is not None and leaf.d5.equivalence_pending == 0
    assert leaf.defense_caveat  # non-empty

    # with STEP-0 fields injected (getattr-optional reads them)
    class _MetaVariant:
        variant_id = "vm"
        knobs_override = {"effort": "high"}
        blocked_reasons: list[str] = []
        meta_mode = "ultracode"
        interaction_record_ref = "ref:interaction-1"

    from shared import edt_measure

    assert edt_measure._optional_meta_modes(_MetaVariant()) == ("ultracode",)


# --------------------------------------------------------------------------------------------
# 12. the 11-enum drift pin against the branch-gated Literal
# --------------------------------------------------------------------------------------------
def test_routing_class_literal_drift_pin() -> None:
    try:
        from agents.request_decomposer.models import RoutingClassValue
    except ImportError:
        pytest.skip("caprouting RoutingClassValue not importable")
    literal_members = set(typing.get_args(RoutingClassValue)) - {"unknown"}
    assert literal_members == set(ROUTING_CLASSES)


# --------------------------------------------------------------------------------------------
# 13. platform MIN aggregation picks the weakest leaf
# --------------------------------------------------------------------------------------------
def test_platform_min_aggregation_picks_weakest_leaf() -> None:
    payload = _fresh_payload(score=5, confidence=5)
    opus = _route_in(payload, "claude.headless.opus")
    _add_distinct_variants(opus, 24)  # rich, high ratio
    weak = _route_in(payload, "claude.headless.haiku")
    weak["descriptor_variants"] = []
    _set_scores(weak, score=1, confidence=2)  # drag the claude platform MIN down

    claude = _by_platform(
        score_edt(_registry(payload), knobs_path=_knobs_file(_OBSERVED_MEMBERS), now=NOW),
        "claude",
    )
    leaf_ratios = [
        leaf.specificity_ratio for leaf in claude.leaves if leaf.specificity_ratio is not None
    ]
    assert claude.platform_ratio == min(leaf_ratios)


# --------------------------------------------------------------------------------------------
# 14. evidence_health blends freshness with evidence_refs
# --------------------------------------------------------------------------------------------
def test_evidence_health_blends_freshness_and_evidence_refs() -> None:
    fresh = _fresh_payload()
    fresh_leaf = _leaf_for(
        score_edt(_registry(fresh), knobs_path=_knobs_file(_OBSERVED_MEMBERS), now=NOW),
        "claude.headless.opus",
    )
    assert fresh_leaf.evidence_health is not None and fresh_leaf.evidence_health >= 0.70

    stale = _fresh_payload()
    route = _route_in(stale, "claude.headless.opus")
    # drive capability evidence stale (checked far in the past, beyond the stale window)
    route["freshness"]["capability_checked_at"] = "2020-01-01T00:00:00Z"
    stale_leaf = _leaf_for(
        score_edt(_registry(stale), knobs_path=_knobs_file(_OBSERVED_MEMBERS), now=NOW),
        "claude.headless.opus",
    )
    assert stale_leaf.evidence_health is not None
    assert stale_leaf.evidence_health < fresh_leaf.evidence_health


# --------------------------------------------------------------------------------------------
# 15. knobs absent -> fail-safe defaults
# --------------------------------------------------------------------------------------------
def test_knobs_absent_uses_defaults_fail_safe() -> None:
    knobs = load_edt_knobs(Path("/nonexistent/edt-platform-knobs.yaml"))
    assert isinstance(knobs, EdtKnobs)
    assert knobs.expected_platform_set == 12
    assert knobs.depth_cap == 20
    assert "gemini" in knobs.expected_platform_members
    assert "claude" in knobs.expected_platform_members


# --------------------------------------------------------------------------------------------
# 16. D0 honesty: the platform set is an operator assertion, not a code-derived fact
# --------------------------------------------------------------------------------------------
def test_d0_platform_set_is_operator_assertion() -> None:
    payload = _fresh_payload()
    measures = score_edt(_registry(payload), knobs_path=_knobs_file(_OBSERVED_MEMBERS), now=NOW)
    m = measures[0]
    assert m.observed_platform_count == 7  # the real registry prefixes
    assert tuple(m.expected_platform_members) == tuple(
        _OBSERVED_MEMBERS
    )  # read verbatim from knobs


# --------------------------------------------------------------------------------------------
# 17. D1 locality axis is degenerate today (one local-resident route)
# --------------------------------------------------------------------------------------------
def test_d1_locality_axis_is_degenerate_today() -> None:
    payload = _fresh_payload()
    measures = score_edt(_registry(payload), knobs_path=_knobs_file(_OBSERVED_MEMBERS), now=NOW)
    local = _by_platform(measures, "local_tool")
    other = _by_platform(measures, "claude")
    local_cells = "".join(local.leaves[0].d1.specificity_cells)
    other_cells = "".join(other.leaves[0].d1.specificity_cells)
    assert "local" in local_cells
    assert "local" not in other_cells


# --------------------------------------------------------------------------------------------
# 18. defense_caveat surfaced when STEP-0 absent (honesty requirement)
# --------------------------------------------------------------------------------------------
def test_defense_caveat_surfaced_when_step0_absent() -> None:
    payload = _fresh_payload()
    measures = score_edt(_registry(payload), knobs_path=_knobs_file(_OBSERVED_MEMBERS), now=NOW)
    m = measures[0]
    assert m.build_defense_caveat  # non-empty build-wide caveat
    joined = " ".join(m.build_defense_caveat).lower()
    assert "slicing" in joined or "dedupe" in joined or "step-0" in joined or "step 0" in joined
    for leaf in m.leaves:
        assert leaf.defense_caveat


# --------------------------------------------------------------------------------------------
# 19. the receipts= quota-unobservable path makes a blocked subscription route AVAILABLE
# --------------------------------------------------------------------------------------------
def _make_receipt(route_id: str, platform: str) -> PlatformCapabilityReceipt:
    obs = datetime(2026, 6, 27, 4, 59, tzinfo=UTC)
    surf = lambda status, **kw: SurfaceEvidence(  # noqa: E731
        status=status, source="probe", observed_at=obs, stale_after="24h", **kw
    )
    return PlatformCapabilityReceipt(
        receipt_id=f"r:{route_id}",
        platform=platform,
        routes=[route_id],
        observed_at=obs,
        stale_after="24h",
        cli=CliEvidence(binary="claude", available=True),
        wrapper=WrapperEvidence(path="/usr/bin/claude", exists=True, executable=True),
        capability=surf(EvidenceStatus.OBSERVED, evidence_refs=["e:cap"]),
        resource=surf(EvidenceStatus.OBSERVED, evidence_refs=["e:res"]),
        quota=surf(EvidenceStatus.UNOBSERVABLE, reason_codes=["account_live_quota_receipt_absent"]),
        provider_docs=ProviderDocsEvidence(refs=["d:docs"], fetched_at=obs, stale_after="24h"),
    )


def test_receipts_quota_unobservable_makes_blocked_subscription_route_available() -> None:
    payload = _fresh_payload()
    opus = _route_in(payload, "claude.headless.opus")  # subscription_quota
    opus["route_state"] = "blocked"
    opus["blocked_reasons"] = ["test: route_state forced blocked"]
    receipts = {"claude.headless.opus": _make_receipt("claude.headless.opus", "claude")}

    # without receipts: blocked -> unavailable
    leaf_no_receipt = _leaf_for(
        score_edt(_registry(payload), knobs_path=_knobs_file(_OBSERVED_MEMBERS), now=NOW),
        "claude.headless.opus",
    )
    assert leaf_no_receipt.d4 is not None and leaf_no_receipt.d4.available is False

    # WITH the quota-unobservable receipt: the mirror treats it as evidence -> available
    leaf_with_receipt = _leaf_for(
        score_edt(
            _registry(payload),
            knobs_path=_knobs_file(_OBSERVED_MEMBERS),
            receipts=receipts,
            now=NOW,
        ),
        "claude.headless.opus",
    )
    assert leaf_with_receipt.d4 is not None and leaf_with_receipt.d4.available is True


# --------------------------------------------------------------------------------------------
# 20. d0_omitted gate fails closed at leaf AND platform level (direct unit)
# --------------------------------------------------------------------------------------------
def test_d0_omitted_gate_fails_closed() -> None:
    payload = _fresh_payload()
    route = _registry(payload).route_map()["claude.headless.full"]
    knobs = load_edt_knobs(_knobs_file(_OBSERVED_MEMBERS))
    leaf = score_variant_leaf(
        "claude.headless.full",
        route.execution_descriptor,
        route,
        knobs=knobs,
        now=NOW,
        d0_omitted=True,
    )
    assert leaf.d0_omitted is True
    assert leaf.passes is False
    measure = score_platform(
        "claude",
        [leaf],
        expected_platform_set=12,
        expected_platform_members=tuple(_OBSERVED_MEMBERS),
        observed_platform_count=7,
        omitted_platforms=(),
    )
    assert measure.platform_passes is False


# --------------------------------------------------------------------------------------------
# 21. _dimension_score reuse propagates evidence_refs (mutant-killer for the reuse seam)
# --------------------------------------------------------------------------------------------
def test_dimension_score_propagates_evidence_refs() -> None:
    # evidence_health = 0.7*freshness + 0.3*evidence_ref_density. A fresh route with evidence_refs on
    # every dim must reach exactly 1.0 — pinning that _dimension_score propagates the adapter's
    # evidence_refs through to D2.dim_scores (a mutant that drops them would yield 0.7).
    payload = _fresh_payload()
    leaf = _leaf_for(
        score_edt(_registry(payload), knobs_path=_knobs_file(_OBSERVED_MEMBERS), now=NOW),
        "claude.headless.full",
    )
    assert leaf.d2 is not None and all(s.evidence_refs for s in leaf.d2.dim_scores)
    assert leaf.evidence_health == 1.0


# --------------------------------------------------------------------------------------------
# 22. an OPTIONAL D2 axis is consumed when present (STEP-0 forward-compat present-branch)
# --------------------------------------------------------------------------------------------
def test_optional_d2_axis_consumed_when_present() -> None:
    payload = _fresh_payload()
    route = _registry(payload).route_map()["claude.headless.full"]
    extended = dict(route.capability_scores.model_dump())
    extended["citation_provenance"] = {
        "score": 5,
        "confidence": 5,
        "evidence_refs": ["e:opt"],
        "observed_at": datetime(2026, 6, 27, 4, 59, tzinfo=UTC),
        "stale_after": "24h",
    }
    with mock.patch.object(type(route.capability_scores), "model_dump", return_value=extended):
        d2 = _resolve_d2("claude.headless.full", route, NOW)
    assert d2.required == 15  # 14 required + 1 optional present
    assert "citation_provenance" not in d2.provisional_dims  # confidence 5, not provisional


# --------------------------------------------------------------------------------------------
# 23. a BLOCKED descriptor-variant leaf is unavailable; the base route leaf stays available
# --------------------------------------------------------------------------------------------
def test_blocked_variant_leaf_is_unavailable() -> None:
    payload = _fresh_payload()
    route = _route_in(payload, "claude.headless.opus")
    route["descriptor_variants"] = [
        {
            "variant_id": "blocked_v",
            "knobs_override": {"effort": "high"},
            "score_delta": {},
            "scores_inherited_from": None,
            "blocked_reasons": ["test: variant blocked"],
        }
    ]
    measures = score_edt(_registry(payload), knobs_path=_knobs_file(_OBSERVED_MEMBERS), now=NOW)
    blocked_leaf = _leaf_for(measures, "claude.headless.opus#blocked_v")
    assert blocked_leaf.d4 is not None
    assert blocked_leaf.d4.available is False
    assert blocked_leaf.d4.unavailability_reason == "variant_blocked"
    base_leaf = _leaf_for(measures, "claude.headless.opus")
    assert base_leaf.d4 is not None and base_leaf.d4.available is True
