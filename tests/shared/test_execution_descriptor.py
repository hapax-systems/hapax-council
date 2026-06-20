"""ExecutionDescriptor foundation — the operator-steered capability axes beyond
platform.mode.profile (model_id / effort / context_mode / fast_mode / quantization).

This is the structural vocabulary for "a capability is the FULL descriptor". The
companion backfill makes ``execution_descriptor`` a stored, required route field with a
strict ``ModelId``; this module pins the type vocabulary + the best-effort
`derive`/`materialize` that projects a route's descriptor from its legacy fields — notably
SURFACING the effort smuggled into ``model_or_engine`` (codex.headless.full = "gpt-5.5-xhigh")
and mapping the free-text ``model_or_engine`` onto the structured ``ModelId`` catalog.
"""

from __future__ import annotations

from shared.platform_capability_registry import (
    ContextMode,
    DescriptorVariant,
    Effort,
    ExecutionDescriptor,
    FastMode,
    ModelId,
    PlatformCapabilityRegistry,
    PlatformCapabilityRoute,
    Quantization,
    derive_execution_descriptor,
    load_platform_capability_registry,
    materialize_descriptor_leaves,
    materialize_descriptors,
    materialize_variant_leaf,
)


def test_axis_enums_cover_the_operator_steered_values() -> None:
    assert {e.value for e in Effort} == {"none", "low", "medium", "high", "xhigh", "max"}
    assert {c.value for c in ContextMode} == {"standard", "extended_1m", "not_applicable"}
    assert {f.value for f in FastMode} == {"off", "fast", "not_applicable"}
    assert {q.value for q in Quantization} == {
        "none",
        "exl3_4_0bpw",
        "exl3_5_0bpw",
        "not_applicable",
    }


def test_execution_descriptor_has_exactly_the_five_capability_axes() -> None:
    # the descriptor IS the operator-steered axis set beyond platform.mode.profile
    assert set(ExecutionDescriptor.model_fields) == {
        "model_id",
        "effort",
        "context_mode",
        "fast_mode",
        "quantization",
    }


def test_execution_descriptor_defaults_are_conservative() -> None:
    d = ExecutionDescriptor(model_id=ModelId.CLAUDE_OPUS_4_8, effort=Effort.MAX)
    assert d.context_mode is ContextMode.STANDARD
    assert d.fast_mode is FastMode.OFF
    assert d.quantization is Quantization.NONE


def test_descriptor_variant_inherits_scores_with_provenance_by_default() -> None:
    v = DescriptorVariant(
        variant_id="opus@extended_1m", knobs_override={"context_mode": "extended_1m"}
    )
    assert v.score_delta == {}  # no fabricated per-knob numbers
    assert v.scores_inherited_from is None
    assert v.blocked_reasons == []


def test_derive_splits_the_smuggled_effort_suffix() -> None:
    # the verified smoking gun: effort smuggled into a model string
    registry = load_platform_capability_registry()
    codex = registry.require("codex.headless.full")
    assert codex.model_or_engine == "gpt-5.5-xhigh"  # the smuggle, as stored
    d = derive_execution_descriptor(codex)
    assert d.model_id is ModelId.GPT_5_5  # effort split OUT, model mapped to the catalog
    assert d.effort is Effort.XHIGH


def test_derive_is_none_effort_when_not_smuggled() -> None:
    registry = load_platform_capability_registry()
    # claude.headless.opus carries no smuggled effort suffix -> effort unknown-at-rest;
    # the free-text "claude-opus" alias maps onto the canonical ModelId catalog entry.
    d = derive_execution_descriptor(registry.require("claude.headless.opus"))
    assert d.effort is Effort.NONE
    assert d.model_id is ModelId.CLAUDE_OPUS_4_8


def test_materialize_covers_every_route() -> None:
    registry = load_platform_capability_registry()
    leaves = materialize_descriptors(registry)
    assert set(leaves) == set(registry.route_map())
    assert all(isinstance(v, ExecutionDescriptor) for v in leaves.values())
    # the foundation makes the implicit per-route descriptor explicit and surfaces the smuggle
    assert leaves["codex.headless.full"].effort is Effort.XHIGH


def test_descriptor_leaves_expand_sparse_variants_as_distinct_capabilities() -> None:
    registry = load_platform_capability_registry()
    base = materialize_descriptors(registry)
    leaves = materialize_descriptor_leaves(registry)
    # every base route is a leaf; variants add MORE leaves keyed route_id#variant_id
    assert set(base) <= set(leaves)
    assert len(leaves) > len(base)
    assert all("#" in key for key in set(leaves) - set(base))


def test_opus_extended_1m_is_distinguishable_from_opus_standard() -> None:
    # the criterion the bare max_context_class enum could NOT express: opus-1M vs opus-standard
    registry = load_platform_capability_registry()
    leaves = materialize_descriptor_leaves(registry)
    standard = leaves["claude.headless.opus"]
    extended = leaves["claude.headless.opus#opus@extended_1m"]
    assert standard.context_mode is ContextMode.STANDARD
    assert extended.context_mode is ContextMode.EXTENDED_1M
    # the variant changes ONLY the context axis — same model, same effort
    assert extended.model_id is standard.model_id
    assert extended.effort is standard.effort
    assert extended != standard


def test_sonnet_effort_low_variant_lowers_only_effort() -> None:
    registry = load_platform_capability_registry()
    leaves = materialize_descriptor_leaves(registry)
    base = leaves["claude.headless.sonnet"]
    low = leaves["claude.headless.sonnet#sonnet@effort_low"]
    assert low.effort is Effort.LOW
    assert low.model_id is base.model_id is ModelId.CLAUDE_SONNET_4_6


def test_variant_leaf_fails_closed_on_non_descriptor_knob() -> None:
    # defense-in-depth: even if a bad variant slipped past route validation, resolving it
    # into a full descriptor must raise rather than silently drop the unknown knob
    import pytest

    registry = load_platform_capability_registry()
    route = registry.require("claude.headless.opus")
    bogus = DescriptorVariant(variant_id="bogus", knobs_override={"not_a_knob": "1"})
    with pytest.raises(ValueError):
        materialize_variant_leaf(route, bogus)


def _route_with_variants(route_id: str, variants: list[dict]) -> PlatformCapabilityRoute:
    """Re-validate a real route with injected descriptor_variants — exercises the route
    contract validator directly (model_validate re-runs validators; model_copy does not)."""
    registry = load_platform_capability_registry()
    data = registry.require(route_id).model_dump()
    data["descriptor_variants"] = variants
    return PlatformCapabilityRoute.model_validate(data)


def test_route_rejects_duplicate_variant_id() -> None:
    import pytest

    good = {"variant_id": "dup", "knobs_override": {"effort": "low"}}
    with pytest.raises(ValueError, match="duplicate descriptor variant_id"):
        _route_with_variants("claude.headless.opus", [good, dict(good)])


def test_route_rejects_non_descriptor_knob_override() -> None:
    import pytest

    with pytest.raises(ValueError, match="non-descriptor knobs"):
        _route_with_variants(
            "claude.headless.opus",
            [{"variant_id": "x", "knobs_override": {"nonsense": "1"}}],
        )


def test_route_rejects_unknown_score_delta() -> None:
    import pytest

    with pytest.raises(ValueError, match="unknown scores"):
        _route_with_variants(
            "claude.headless.opus",
            [
                {
                    "variant_id": "x",
                    "knobs_override": {"effort": "low"},
                    "score_delta": {"not_a_real_score": 1},
                }
            ],
        )


def test_route_rejects_inert_variant() -> None:
    import pytest

    with pytest.raises(ValueError, match="inert"):
        _route_with_variants("claude.headless.opus", [{"variant_id": "x"}])


def test_registry_rejects_variant_inheriting_unknown_route() -> None:
    import pytest

    registry = load_platform_capability_registry()
    data = registry.model_dump()
    for route in data["routes"]:
        if route["route_id"] == "claude.headless.opus":
            route["descriptor_variants"] = [
                {
                    "variant_id": "x",
                    "knobs_override": {"effort": "low"},
                    "scores_inherited_from": "no.such.route",
                }
            ]
    with pytest.raises(ValueError, match="unknown route_id"):
        PlatformCapabilityRegistry.model_validate(data)
