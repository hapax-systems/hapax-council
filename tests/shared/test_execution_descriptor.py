"""ExecutionDescriptor foundation — the operator-steered capability axes beyond
platform.mode.profile (model_id / effort / context_mode / fast_mode / quantization).

This is the structural vocabulary for "a capability is the FULL descriptor". It does NOT
yet make execution_descriptor a stored route field (that backfill is a later slice); it
defines the types + a best-effort `derive`/`materialize` that projects each route's CURRENT
implicit descriptor from existing fields — notably SURFACING the effort smuggled into
`model_or_engine` (codex.headless.full = "gpt-5.5-xhigh").
"""

from __future__ import annotations

from shared.platform_capability_registry import (
    ContextMode,
    DescriptorVariant,
    Effort,
    ExecutionDescriptor,
    FastMode,
    Quantization,
    derive_execution_descriptor,
    load_platform_capability_registry,
    materialize_descriptors,
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
    d = ExecutionDescriptor(model_id="claude-opus-4-8", effort=Effort.MAX)
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
    assert d.model_id == "gpt-5.5"  # effort split OUT of the model string
    assert d.effort is Effort.XHIGH


def test_derive_is_none_effort_when_not_smuggled() -> None:
    registry = load_platform_capability_registry()
    # claude.headless.opus carries no smuggled effort suffix -> effort unknown-at-rest
    d = derive_execution_descriptor(registry.require("claude.headless.opus"))
    assert d.effort is Effort.NONE
    assert d.model_id == "claude-opus"


def test_materialize_covers_every_route() -> None:
    registry = load_platform_capability_registry()
    leaves = materialize_descriptors(registry)
    assert set(leaves) == set(registry.route_map())
    assert all(isinstance(v, ExecutionDescriptor) for v in leaves.values())
    # the foundation makes the implicit per-route descriptor explicit and surfaces the smuggle
    assert leaves["codex.headless.full"].effort is Effort.XHIGH
