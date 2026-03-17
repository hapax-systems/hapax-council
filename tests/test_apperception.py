"""Matrix tests for ApperceptionCascade — Batch 1.

Test matrix: each step × each source × each stimmung state + safeguard tests.
Pure logic, no I/O, no mocks of external systems.
"""

from __future__ import annotations

import random
import time

import pytest

from shared.apperception import (
    ALL_SOURCES,
    COHERENCE_FLOOR,
    RUMINATION_LIMIT,
    Apperception,
    ApperceptionCascade,
    CascadeEvent,
    SelfDimension,
    SelfModel,
    Source,
    get_stimmung_modulation,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_event(
    source: Source = "prediction_error",
    text: str = "test event",
    magnitude: float = 0.5,
    metadata: dict | None = None,
) -> CascadeEvent:
    return CascadeEvent(
        source=source,
        text=text,
        magnitude=magnitude,
        metadata=metadata or {},
    )


def _make_cascade(
    seed: int = 42,
    model: SelfModel | None = None,
) -> ApperceptionCascade:
    return ApperceptionCascade(
        self_model=model,
        rng=random.Random(seed),
    )


# ── Data Model Tests ─────────────────────────────────────────────────────────


class TestApperceptionModel:
    def test_frozen(self):
        a = Apperception(
            source="correction",
            trigger_text="test",
            cascade_depth=5,
            observation="I notice",
            valence=-0.3,
            valence_target="accuracy",
        )
        with pytest.raises(Exception):
            a.source = "absence"  # type: ignore[misc]

    def test_valence_clamped(self):
        a = Apperception(
            source="correction",
            trigger_text="test",
            cascade_depth=5,
            observation="I notice",
            valence=-1.0,
            valence_target="accuracy",
        )
        assert a.valence == -1.0

    def test_cascade_depth_bounds(self):
        with pytest.raises(Exception):
            Apperception(
                source="correction",
                trigger_text="test",
                cascade_depth=0,
                observation="I notice",
                valence=0.0,
                valence_target="accuracy",
            )
        with pytest.raises(Exception):
            Apperception(
                source="correction",
                trigger_text="test",
                cascade_depth=8,
                observation="I notice",
                valence=0.0,
                valence_target="accuracy",
            )


class TestSelfDimension:
    def test_initial_confidence(self):
        d = SelfDimension(name="test")
        assert d.confidence == 0.5

    def test_affirming_update(self):
        d = SelfDimension(name="test")
        d.update(0.5)
        assert d.affirming_count == 1
        assert d.confidence > 0.5

    def test_problematizing_update(self):
        d = SelfDimension(name="test")
        d.update(-0.5)
        assert d.problematizing_count == 1
        assert d.confidence < 0.5

    def test_confidence_floor(self):
        d = SelfDimension(name="test", confidence=0.06)
        d.update(-1.0)
        assert d.confidence >= 0.05

    def test_confidence_ceiling(self):
        d = SelfDimension(name="test", confidence=0.94)
        d.update(1.0)
        assert d.confidence <= 0.95

    def test_dampening_large_errors(self):
        """Large errors (>0.7 magnitude) dampen change rate — anti-inflation guard."""
        d1 = SelfDimension(name="normal")
        d1.update(0.6)
        normal_delta = d1.confidence - 0.5

        d2 = SelfDimension(name="large")
        d2.update(0.9)
        large_delta = d2.confidence - 0.5

        # Large error should produce smaller change (dampened)
        assert large_delta < normal_delta

    def test_stability_increases_with_no_change(self):
        d = SelfDimension(name="test", last_shift_time=time.time() - 100)
        assert d.stability >= 99


class TestSelfModel:
    def test_get_or_create_dimension(self):
        m = SelfModel()
        d = m.get_or_create_dimension("test_dim")
        assert d.name == "test_dim"
        assert "test_dim" in m.dimensions
        # Second call returns same instance
        d2 = m.get_or_create_dimension("test_dim")
        assert d is d2

    def test_coherence_floor(self):
        m = SelfModel()
        for i in range(10):
            d = m.get_or_create_dimension(f"dim_{i}")
            d.confidence = 0.05  # all at floor
        m.update_coherence()
        assert m.coherence >= COHERENCE_FLOOR

    def test_serialization_roundtrip(self):
        m = SelfModel()
        d = m.get_or_create_dimension("test")
        d.update(0.3)
        m.recent_observations.append("I notice something")
        m.recent_reflections.append("Tension detected")
        m.update_coherence()

        data = m.to_dict()
        m2 = SelfModel.from_dict(data)

        assert "test" in m2.dimensions
        assert m2.dimensions["test"].affirming_count == 1
        assert list(m2.recent_observations) == ["I notice something"]
        assert list(m2.recent_reflections) == ["Tension detected"]

    def test_observation_deque_maxlen(self):
        m = SelfModel()
        for i in range(25):
            m.recent_observations.append(f"obs_{i}")
        assert len(m.recent_observations) == 20
        assert m.recent_observations[0] == "obs_5"


# ── Stimmung Modulation Tests ────────────────────────────────────────────────


class TestStimmungModulation:
    def test_nominal_allows_all_sources(self):
        mod = get_stimmung_modulation("nominal")
        assert mod.sources_allowed is None

    def test_critical_restricts_sources(self):
        mod = get_stimmung_modulation("critical")
        assert mod.sources_allowed is not None
        assert "prediction_error" in mod.sources_allowed
        assert "correction" in mod.sources_allowed
        assert "absence" not in mod.sources_allowed

    def test_critical_disables_reflection(self):
        mod = get_stimmung_modulation("critical")
        assert mod.reflection_enabled is False

    def test_degraded_doubles_reflection_threshold(self):
        mod = get_stimmung_modulation("degraded")
        assert mod.reflection_threshold_multiplier == 2.0

    def test_cautious_reduces_noise(self):
        mod = get_stimmung_modulation("cautious")
        assert mod.noise_reduction == 0.5

    def test_unknown_stance_defaults_to_nominal(self):
        mod = get_stimmung_modulation("unknown_stance")
        nominal = get_stimmung_modulation("nominal")
        assert mod == nominal


# ── Step 1: Attention Tests ──────────────────────────────────────────────────


class TestAttention:
    def test_all_sources_pass_nominal(self):
        """All system events pass attention in nominal stance."""
        for source in ALL_SOURCES:
            cascade = _make_cascade()
            event = _make_event(source=source, text=f"unique_{source}")
            result = cascade._step_attention(event, get_stimmung_modulation("nominal"))
            assert result is True, f"Source {source} should pass attention"

    def test_critical_filters_non_essential(self):
        """Critical stance only allows prediction_error and correction."""
        mod = get_stimmung_modulation("critical")
        cascade = _make_cascade()

        assert cascade._step_attention(_make_event(source="prediction_error", text="a"), mod)
        assert cascade._step_attention(_make_event(source="correction", text="b"), mod)
        assert not cascade._step_attention(_make_event(source="pattern_shift", text="c"), mod)
        assert not cascade._step_attention(_make_event(source="absence", text="d"), mod)

    def test_dedup_identical_triggers(self):
        """Duplicate triggers within window are filtered."""
        cascade = _make_cascade()
        mod = get_stimmung_modulation("nominal")
        event = _make_event(text="same trigger")

        assert cascade._step_attention(event, mod) is True
        assert cascade._step_attention(event, mod) is False

    def test_dedup_different_triggers_pass(self):
        cascade = _make_cascade()
        mod = get_stimmung_modulation("nominal")

        assert cascade._step_attention(_make_event(text="trigger_a"), mod)
        assert cascade._step_attention(_make_event(text="trigger_b"), mod)


# ── Step 2: Relevance Tests ─────────────────────────────────────────────────


class TestRelevance:
    def test_corrections_always_relevant(self):
        cascade = _make_cascade()
        mod = get_stimmung_modulation("nominal")
        event = _make_event(source="correction", magnitude=0.01)
        passes, score = cascade._step_relevance(event, mod)
        assert passes is True
        assert score >= 0.5

    def test_low_magnitude_filtered(self):
        cascade = _make_cascade(seed=0)
        mod = get_stimmung_modulation("nominal")
        event = _make_event(source="absence", magnitude=0.05)
        passes, _ = cascade._step_relevance(event, mod)
        assert passes is False

    def test_high_magnitude_passes(self):
        cascade = _make_cascade()
        mod = get_stimmung_modulation("nominal")
        event = _make_event(magnitude=0.8)
        passes, _ = cascade._step_relevance(event, mod)
        assert passes is True

    def test_low_coherence_lowers_threshold(self):
        """Low coherence reduces threshold to help rebuild self-model."""
        model = SelfModel(coherence=0.2)
        cascade = _make_cascade(model=model, seed=0)
        mod = get_stimmung_modulation("nominal")
        # Magnitude that would normally be below threshold
        event = _make_event(source="absence", magnitude=0.15)
        passes, _ = cascade._step_relevance(event, mod)
        assert passes is True

    def test_stochastic_resonance(self):
        """Noise injection can push borderline events over threshold."""
        results = set()
        for seed in range(100):
            cascade = _make_cascade(seed=seed)
            mod = get_stimmung_modulation("nominal")
            event = _make_event(magnitude=0.19)  # just below threshold
            passes, _ = cascade._step_relevance(event, mod)
            results.add(passes)
        # With stochastic resonance, some should pass and some shouldn't
        assert True in results and False in results


# ── Step 3: Integration Tests ────────────────────────────────────────────────


class TestIntegration:
    def test_source_maps_to_dimension(self):
        cascade = _make_cascade()
        target, _ = cascade._step_integration(_make_event(source="prediction_error"))
        assert target == "temporal_prediction"

    def test_correction_maps_to_accuracy(self):
        cascade = _make_cascade()
        target, _ = cascade._step_integration(_make_event(source="correction"))
        assert target == "accuracy"

    def test_metadata_dimension_override(self):
        cascade = _make_cascade()
        event = _make_event(
            source="performance",
            metadata={"dimension": "music_production"},
        )
        target, _ = cascade._step_integration(event)
        assert target == "music_production"

    def test_integration_finds_links(self):
        model = SelfModel()
        model.recent_observations.append("I notice temporal_prediction issue")
        cascade = _make_cascade(model=model)
        _, links = cascade._step_integration(_make_event(source="prediction_error"))
        assert len(links) == 1


# ── Step 4: Valence Tests ───────────────────────────────────────────────────


class TestValence:
    def test_correction_is_problematizing(self):
        cascade = _make_cascade()
        valence = cascade._step_valence(_make_event(source="correction", magnitude=0.5))
        assert valence < 0

    def test_prediction_error_is_problematizing(self):
        cascade = _make_cascade()
        valence = cascade._step_valence(_make_event(source="prediction_error", magnitude=0.5))
        assert valence < 0

    def test_cross_resonance_is_affirming(self):
        cascade = _make_cascade()
        valence = cascade._step_valence(_make_event(source="cross_resonance", magnitude=0.5))
        assert valence > 0

    def test_pattern_confirmed_is_affirming(self):
        cascade = _make_cascade()
        valence = cascade._step_valence(
            _make_event(
                source="pattern_shift",
                magnitude=0.5,
                metadata={"confirmed": True},
            )
        )
        assert valence > 0

    def test_pattern_contradicted_is_problematizing(self):
        cascade = _make_cascade()
        valence = cascade._step_valence(
            _make_event(
                source="pattern_shift",
                magnitude=0.5,
                metadata={"confirmed": False},
            )
        )
        assert valence < 0

    def test_stimmung_improving_is_affirming(self):
        cascade = _make_cascade()
        valence = cascade._step_valence(
            _make_event(
                source="stimmung_event",
                magnitude=0.5,
                metadata={"direction": "improving"},
            )
        )
        assert valence > 0

    def test_stimmung_degrading_is_problematizing(self):
        cascade = _make_cascade()
        valence = cascade._step_valence(
            _make_event(
                source="stimmung_event",
                magnitude=0.5,
                metadata={"direction": "degrading"},
            )
        )
        assert valence < 0

    def test_valence_clamped(self):
        cascade = _make_cascade()
        valence = cascade._step_valence(_make_event(source="correction", magnitude=1.0))
        assert -1.0 <= valence <= 1.0

    def test_valence_scaled_by_magnitude(self):
        cascade = _make_cascade()
        v_low = cascade._step_valence(_make_event(source="correction", magnitude=0.2))
        v_high = cascade._step_valence(_make_event(source="correction", magnitude=0.8))
        assert abs(v_high) > abs(v_low)


# ── Step 5: Action Tests ────────────────────────────────────────────────────


class TestAction:
    def test_no_action_for_mild_problematizing(self):
        cascade = _make_cascade()
        action = cascade._step_action(-0.3, "accuracy", 0.7)
        assert action == ""

    def test_action_for_strong_problematizing_high_confidence(self):
        cascade = _make_cascade()
        action = cascade._step_action(-0.6, "accuracy", 0.7)
        assert "accuracy" in action

    def test_no_action_for_affirming(self):
        cascade = _make_cascade()
        action = cascade._step_action(0.8, "accuracy", 0.9)
        assert action == ""

    def test_no_action_for_low_confidence_dimension(self):
        cascade = _make_cascade()
        action = cascade._step_action(-0.8, "accuracy", 0.3)
        assert action == ""


# ── Step 6: Reflection Tests ────────────────────────────────────────────────


class TestReflection:
    def test_reflection_on_conflict(self):
        """Reflection fires when valence conflicts with dimension trend."""
        cascade = _make_cascade()
        dim = SelfDimension(name="accuracy", affirming_count=10, problematizing_count=2)
        mod = get_stimmung_modulation("nominal")
        reflection = cascade._step_reflection(-0.5, "accuracy", [], dim, mod)
        assert "tension" in reflection.lower()

    def test_no_reflection_when_aligned(self):
        cascade = _make_cascade()
        dim = SelfDimension(name="accuracy", affirming_count=10, problematizing_count=2)
        mod = get_stimmung_modulation("nominal")
        reflection = cascade._step_reflection(0.5, "accuracy", [], dim, mod)
        assert reflection == ""

    def test_no_conflict_on_new_dimension(self):
        """New dimensions (< 3 total evidence) don't trigger conflict reflection."""
        cascade = _make_cascade()
        dim = SelfDimension(name="accuracy")  # 0/0 counts
        mod = get_stimmung_modulation("nominal")
        reflection = cascade._step_reflection(0.1, "accuracy", [], dim, mod)
        assert reflection == ""

    def test_reflection_on_many_links(self):
        cascade = _make_cascade()
        dim = SelfDimension(name="accuracy")  # no conflict history → link check runs
        mod = get_stimmung_modulation("nominal")
        links = ["link1", "link2", "link3"]
        reflection = cascade._step_reflection(0.1, "accuracy", links, dim, mod)
        assert "recurring" in reflection.lower()

    def test_reflection_disabled_in_critical(self):
        cascade = _make_cascade()
        dim = SelfDimension(name="accuracy", affirming_count=10, problematizing_count=2)
        mod = get_stimmung_modulation("critical")
        reflection = cascade._step_reflection(-0.5, "accuracy", [], dim, mod)
        assert reflection == ""

    def test_degraded_doubles_link_threshold(self):
        cascade = _make_cascade()
        dim = SelfDimension(name="accuracy")  # new dimension, no conflict trigger
        mod = get_stimmung_modulation("degraded")
        links = ["link1", "link2", "link3"]
        # 3 links < 6 (3 * 2.0 threshold multiplier), no conflict → empty
        reflection = cascade._step_reflection(0.1, "accuracy", links, dim, mod)
        assert reflection == ""


# ── Step 7: Retention Tests ──────────────────────────────────────────────────


class TestRetention:
    def test_corrections_always_retained(self):
        cascade = _make_cascade()
        assert cascade._step_retention(1, 0.0, 0.0, "", "correction") is True

    def test_shallow_cascade_not_retained(self):
        cascade = _make_cascade()
        assert cascade._step_retention(4, 0.5, 0.5, "reflection", "prediction_error") is False

    def test_deep_with_relevance_retained(self):
        cascade = _make_cascade()
        assert cascade._step_retention(5, 0.5, 0.0, "", "prediction_error") is True

    def test_deep_with_valence_retained(self):
        cascade = _make_cascade()
        assert cascade._step_retention(5, 0.0, 0.3, "", "prediction_error") is True

    def test_deep_with_reflection_retained(self):
        cascade = _make_cascade()
        assert cascade._step_retention(5, 0.0, 0.0, "some reflection", "prediction_error") is True

    def test_deep_but_boring_not_retained(self):
        cascade = _make_cascade()
        assert cascade._step_retention(5, 0.1, 0.1, "", "prediction_error") is False


# ── Safeguard Tests ──────────────────────────────────────────────────────────


class TestSafeguards:
    def test_narcissistic_inflation_dampening(self):
        """Large errors dampen change rate instead of being rejected."""
        dim = SelfDimension(name="test")
        # Normal update
        dim.update(0.5)
        normal_conf = dim.confidence

        dim2 = SelfDimension(name="test2")
        # Large error — should be dampened, not rejected
        dim2.update(0.9)
        # The large error still moves confidence, but less than the normal one
        assert dim2.confidence > 0.5  # still affirms
        assert dim2.confidence < normal_conf  # but less than normal

    def test_shame_spiral_coherence_floor(self):
        """Coherence floor at 0.15 prevents total collapse."""
        model = SelfModel()
        for i in range(20):
            d = model.get_or_create_dimension(f"dim_{i}")
            d.confidence = 0.05
        model.update_coherence()
        assert model.coherence >= COHERENCE_FLOOR

    def test_no_suppression_pathway(self):
        """Valence cannot be modified after step 4 — no suppression pathway.

        This is verified by Apperception being frozen (immutable).
        """
        cascade = _make_cascade()
        event = _make_event(
            source="correction",
            text="you were wrong about X",
            magnitude=0.8,
        )
        result = cascade.process(event)
        assert result is not None
        assert result.valence < 0  # problematizing is preserved
        with pytest.raises(Exception):
            result.valence = 0.0  # type: ignore[misc]

    def test_rumination_breaker(self):
        """5 consecutive negative valences on same dimension triggers 10min gate."""
        cascade = _make_cascade()

        # Send RUMINATION_LIMIT negative events to the same dimension
        results = []
        for i in range(RUMINATION_LIMIT + 2):
            event = _make_event(
                source="prediction_error",
                text=f"error_{i}",
                magnitude=0.6,
            )
            result = cascade.process(event, stimmung_stance="nominal")
            results.append(result)

        # After RUMINATION_LIMIT, the dimension should be gated
        assert "temporal_prediction" in cascade._attention_gates

    def test_rumination_gate_expires(self):
        """Rumination gate expires after RUMINATION_GATE_SECONDS."""
        cascade = _make_cascade()

        # Set an expired gate
        cascade._attention_gates["test_dim"] = time.time() - 1

        # Should not be gated anymore
        assert cascade._check_rumination("test_dim", -0.5) is False
        assert "test_dim" not in cascade._attention_gates

    def test_sycophancy_guard(self):
        """No 'what would operator want?' filter — relevance uses own dimensions."""
        cascade = _make_cascade()
        # Correction is always relevant regardless of operator preference
        event = _make_event(source="correction", text="you were wrong", magnitude=0.3)
        result = cascade.process(event)
        assert result is not None
        assert result.valence < 0  # not suppressed to please operator

    def test_intellectual_dissociation_guard(self):
        """Reflection only fires on pattern or conflict, not every cycle."""
        cascade = _make_cascade()
        reflections = 0
        for i in range(20):
            event = _make_event(
                source="performance",
                text=f"perf_{i}",
                magnitude=0.5,
                metadata={"baseline": 0.5},
            )
            result = cascade.process(event)
            if result and result.reflection:
                reflections += 1
        # Reflection should not fire on most events
        assert reflections < 10

    def test_transparency_full_model_inspectable(self):
        """Entire self-model is serializable and inspectable — no hidden state."""
        cascade = _make_cascade()
        for i in range(5):
            cascade.process(
                _make_event(
                    source="correction",
                    text=f"correction_{i}",
                    magnitude=0.5,
                )
            )
        data = cascade.model.to_dict()
        assert "dimensions" in data
        assert "recent_observations" in data
        assert "coherence" in data
        # Roundtrip works
        restored = SelfModel.from_dict(data)
        assert set(restored.dimensions.keys()) == set(cascade.model.dimensions.keys())


# ── Full Cascade Integration Tests ───────────────────────────────────────────


class TestFullCascade:
    @pytest.mark.parametrize("source", ALL_SOURCES)
    def test_each_source_nominal(self, source: Source):
        """Each source type can produce an apperception under nominal conditions."""
        cascade = _make_cascade()
        metadata: dict = {}
        if source == "pattern_shift":
            metadata = {"confirmed": True}
        elif source == "stimmung_event":
            metadata = {"direction": "improving"}
        elif source == "performance":
            metadata = {"baseline": 0.3}

        event = _make_event(source=source, text=f"test_{source}", magnitude=0.7, metadata=metadata)
        result = cascade.process(event, stimmung_stance="nominal")
        # Not all sources guaranteed to produce retained apperception,
        # but all should at least not crash
        if result is not None:
            assert result.source == source
            assert result.stimmung_stance == "nominal"

    @pytest.mark.parametrize("stance", ["nominal", "cautious", "degraded", "critical"])
    def test_correction_retained_all_stances(self, stance: str):
        """Corrections are retained regardless of stimmung stance."""
        cascade = _make_cascade()
        event = _make_event(
            source="correction",
            text=f"correction_{stance}",
            magnitude=0.5,
        )
        result = cascade.process(event, stimmung_stance=stance)
        assert result is not None
        assert result.source == "correction"

    @pytest.mark.parametrize("stance", ["nominal", "cautious", "degraded", "critical"])
    def test_stimmung_affects_noise(self, stance: str):
        """Each stance produces expected noise modulation."""
        cascade = _make_cascade()
        mod = get_stimmung_modulation(stance)
        noise = cascade._compute_noise(mod)
        if stance == "critical":
            assert noise == 0.0
        elif stance == "degraded":
            assert noise == 0.1
        elif stance == "cautious":
            assert noise < cascade._base_noise
        else:
            assert noise == cascade._base_noise

    def test_cascade_updates_self_model(self):
        """Processing events accumulates self-knowledge."""
        cascade = _make_cascade()
        cascade.process(_make_event(source="correction", text="wrong prediction", magnitude=0.5))
        assert "accuracy" in cascade.model.dimensions
        assert cascade.model.dimensions["accuracy"].problematizing_count > 0
        assert len(cascade.model.recent_observations) > 0

    def test_critical_filters_non_essential_sources(self):
        """Critical stance filters non-essential sources end-to-end."""
        cascade = _make_cascade()
        event = _make_event(source="absence", text="absence event", magnitude=0.8)
        result = cascade.process(event, stimmung_stance="critical")
        assert result is None

    def test_low_coherence_easier_retention(self):
        """Low coherence model accepts events more readily (rebuild mode)."""
        model = SelfModel(coherence=COHERENCE_FLOOR)
        cascade = _make_cascade(model=model)
        # Low magnitude event that might normally be filtered
        event = _make_event(source="absence", text="low_coherence_test", magnitude=0.15)
        # With low coherence, relevance threshold is halved
        mod = get_stimmung_modulation("nominal")
        passes, _ = cascade._step_relevance(event, mod)
        assert passes is True

    def test_observation_format(self):
        """Observations start with 'I notice' pattern."""
        cascade = _make_cascade()
        result = cascade.process(
            _make_event(source="correction", text="wrong about weather", magnitude=0.5)
        )
        assert result is not None
        assert result.observation.startswith("I notice")


# ── Source × Stimmung Matrix ─────────────────────────────────────────────────


class TestSourceStimmungMatrix:
    """Cross-product: every source × every stimmung stance.

    Ensures no combination crashes and critical stance filtering is correct.
    """

    _STANCES = ["nominal", "cautious", "degraded", "critical"]
    _CRITICAL_ALLOWED = {"prediction_error", "correction"}

    @pytest.mark.parametrize("source", ALL_SOURCES)
    @pytest.mark.parametrize("stance", _STANCES)
    def test_source_stance_combination(self, source: Source, stance: str):
        cascade = _make_cascade()
        metadata: dict = {}
        if source == "pattern_shift":
            metadata = {"confirmed": True}
        elif source == "stimmung_event":
            metadata = {"direction": "stable"}
        elif source == "performance":
            metadata = {"baseline": 0.5}

        event = _make_event(
            source=source,
            text=f"{source}_{stance}",
            magnitude=0.6,
            metadata=metadata,
        )
        result = cascade.process(event, stimmung_stance=stance)

        if stance == "critical" and source not in self._CRITICAL_ALLOWED:
            assert result is None, f"Source {source} should be filtered in critical stance"
