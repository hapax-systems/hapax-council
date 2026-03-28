"""Tests for the visual chain capability — semantic visual expression."""

from agents.visual_chain import (
    VISUAL_CHAIN_RECORDS,
    VISUAL_DIMENSIONS,
    ParameterMapping,
    VisualChainCapability,
    param_value_from_level,
)
from shared.impingement import Impingement, ImpingementType


def test_param_value_at_zero():
    mapping = ParameterMapping(
        technique="gradient",
        param="brightness",
        breakpoints=[(0.0, 0.0), (0.5, 0.15), (1.0, 0.40)],
    )
    assert param_value_from_level(0.0, mapping.breakpoints) == 0.0


def test_param_value_at_midpoint():
    mapping = ParameterMapping(
        technique="gradient",
        param="brightness",
        breakpoints=[(0.0, 0.0), (0.5, 0.15), (1.0, 0.40)],
    )
    result = param_value_from_level(0.5, mapping.breakpoints)
    assert abs(result - 0.15) < 0.001


def test_param_value_interpolates():
    mapping = ParameterMapping(
        technique="gradient",
        param="brightness",
        breakpoints=[(0.0, 0.0), (1.0, 1.0)],
    )
    result = param_value_from_level(0.25, mapping.breakpoints)
    assert abs(result - 0.25) < 0.001


def test_param_value_clamps_below():
    mapping = ParameterMapping(
        technique="gradient",
        param="brightness",
        breakpoints=[(0.0, 0.0), (1.0, 1.0)],
    )
    assert param_value_from_level(-0.5, mapping.breakpoints) == 0.0


def test_param_value_clamps_above():
    mapping = ParameterMapping(
        technique="gradient",
        param="brightness",
        breakpoints=[(0.0, 0.0), (1.0, 1.0)],
    )
    assert param_value_from_level(1.5, mapping.breakpoints) == 1.0


def test_nine_dimensions_defined():
    assert len(VISUAL_DIMENSIONS) == 9


def test_all_dimensions_have_visual_chain_prefix():
    for name in VISUAL_DIMENSIONS:
        assert name.startswith("visual_chain."), f"{name} missing prefix"


def test_all_dimensions_have_mappings():
    for name, dim in VISUAL_DIMENSIONS.items():
        assert len(dim.parameter_mappings) > 0, f"{name} has no mappings"


def test_all_breakpoints_start_at_zero_delta():
    """At level 0.0, every mapping must produce 0.0 (no change from baseline)."""
    for name, dim in VISUAL_DIMENSIONS.items():
        for m in dim.parameter_mappings:
            val = param_value_from_level(0.0, m.breakpoints)
            assert val == 0.0, (
                f"{name}/{m.technique}.{m.param}: level=0.0 should produce 0.0, got {val}"
            )


def test_dimension_names_match_vocal_chain():
    expected_suffixes = {
        "intensity",
        "tension",
        "diffusion",
        "degradation",
        "depth",
        "pitch_displacement",
        "temporal_distortion",
        "spectral_color",
        "coherence",
    }
    actual_suffixes = {name.split(".", 1)[1] for name in VISUAL_DIMENSIONS}
    assert actual_suffixes == expected_suffixes


def test_nine_capability_records():
    assert len(VISUAL_CHAIN_RECORDS) == 9


def test_records_use_visual_layer_aggregator_daemon():
    for rec in VISUAL_CHAIN_RECORDS:
        assert rec.daemon == "visual_layer_aggregator"


def test_records_are_realtime_latency():
    for rec in VISUAL_CHAIN_RECORDS:
        assert rec.operational.latency_class == "realtime"


# ---------------------------------------------------------------------------
# Task 4: VisualChainCapability tests
# ---------------------------------------------------------------------------


def _make_impingement(strength: float = 0.6, source: str = "dmn.evaluative") -> Impingement:
    return Impingement(
        id="test-001",
        timestamp=0.0,
        source=source,
        type=ImpingementType.SALIENCE_INTEGRATION,
        strength=strength,
        content={"metric": "stimmung_shift", "trajectory": "degrading"},
        context={},
        interrupt_token=None,
        embedding=None,
    )


def test_capability_initial_levels_are_zero():
    cap = VisualChainCapability()
    for name in VISUAL_DIMENSIONS:
        assert cap.get_dimension_level(name) == 0.0


def test_activate_dimension_sets_level():
    cap = VisualChainCapability()
    imp = _make_impingement(strength=0.6)
    cap.activate_dimension("visual_chain.intensity", imp, 0.6)
    assert cap.get_dimension_level("visual_chain.intensity") == 0.6


def test_activate_dimension_clamps_to_unit():
    cap = VisualChainCapability()
    imp = _make_impingement(strength=1.0)
    cap.activate_dimension("visual_chain.intensity", imp, 1.5)
    assert cap.get_dimension_level("visual_chain.intensity") == 1.0


def test_decay_reduces_levels():
    cap = VisualChainCapability(decay_rate=0.1)
    imp = _make_impingement()
    cap.activate_dimension("visual_chain.intensity", imp, 0.5)
    cap.decay(1.0)
    assert abs(cap.get_dimension_level("visual_chain.intensity") - 0.4) < 0.001


def test_decay_does_not_go_below_zero():
    cap = VisualChainCapability(decay_rate=1.0)
    imp = _make_impingement()
    cap.activate_dimension("visual_chain.intensity", imp, 0.1)
    cap.decay(10.0)
    assert cap.get_dimension_level("visual_chain.intensity") == 0.0


def test_deactivate_resets_all():
    cap = VisualChainCapability()
    imp = _make_impingement()
    cap.activate_dimension("visual_chain.intensity", imp, 0.8)
    cap.activate_dimension("visual_chain.tension", imp, 0.5)
    cap.deactivate()
    for name in VISUAL_DIMENSIONS:
        assert cap.get_dimension_level(name) == 0.0


def test_compute_deltas_at_zero_is_empty():
    cap = VisualChainCapability()
    deltas = cap.compute_param_deltas()
    assert all(v == 0.0 for v in deltas.values())


def test_compute_deltas_at_nonzero():
    cap = VisualChainCapability()
    imp = _make_impingement()
    cap.activate_dimension("visual_chain.intensity", imp, 1.0)
    deltas = cap.compute_param_deltas()
    assert deltas.get("gradient.brightness", 0.0) > 0.0
