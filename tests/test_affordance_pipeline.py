"""Tests for the affordance-as-retrieval pipeline (Phase R0)."""

import time

from shared.affordance import (
    ActivationState,
    CapabilityRecord,
    OperationalProperties,
    SelectionCandidate,
)
from shared.impingement import Impingement, ImpingementType, render_impingement_text


def test_base_level_never_used():
    state = ActivationState()
    assert state.base_level(time.time()) == -10.0


def test_base_level_recently_used():
    now = time.time()
    state = ActivationState(use_count=1, last_use_ts=now - 1.0, first_use_ts=now - 1.0)
    assert state.base_level(now) > -1.0


def test_base_level_decays_with_time():
    now = time.time()
    recent = ActivationState(use_count=5, last_use_ts=now - 2.0, first_use_ts=now - 100.0)
    old = ActivationState(use_count=5, last_use_ts=now - 600.0, first_use_ts=now - 3600.0)
    assert recent.base_level(now) > old.base_level(now)


def test_base_level_increases_with_frequency():
    now = time.time()
    few = ActivationState(use_count=2, last_use_ts=now - 5.0, first_use_ts=now - 100.0)
    many = ActivationState(use_count=50, last_use_ts=now - 5.0, first_use_ts=now - 100.0)
    assert many.base_level(now) > few.base_level(now)


def test_thompson_sample_uniform_prior():
    state = ActivationState()
    samples = [state.thompson_sample() for _ in range(100)]
    assert min(samples) < 0.3
    assert max(samples) > 0.7


def test_thompson_record_success_shifts_distribution():
    state = ActivationState()
    for _ in range(20):
        state.record_success()
    samples = [state.thompson_sample() for _ in range(50)]
    assert sum(samples) / len(samples) > 0.7


def test_thompson_record_failure_shifts_distribution():
    state = ActivationState()
    for _ in range(20):
        state.record_failure()
    samples = [state.thompson_sample() for _ in range(50)]
    assert sum(samples) / len(samples) < 0.3


def test_thompson_discount_decays():
    state = ActivationState()
    for _ in range(100):
        state.record_success(gamma=0.99)
    assert state.ts_alpha > state.ts_beta * 5


def test_capability_record_creation():
    rec = CapabilityRecord(
        name="speech_production",
        description="Produces audible natural language reaching the operator within 1 second.",
        daemon="hapax_voice",
        operational=OperationalProperties(requires_gpu=True),
    )
    assert rec.name == "speech_production"
    assert rec.operational.requires_gpu is True
    assert rec.operational.consent_required is False


def test_impingement_embedding_optional():
    imp = Impingement(
        timestamp=time.time(),
        source="test",
        type=ImpingementType.ABSOLUTE_THRESHOLD,
        strength=0.5,
    )
    assert imp.embedding is None


def test_impingement_with_embedding():
    imp = Impingement(
        timestamp=time.time(),
        source="test",
        type=ImpingementType.ABSOLUTE_THRESHOLD,
        strength=0.5,
        embedding=[0.1] * 768,
    )
    assert len(imp.embedding) == 768


def test_render_impingement_text():
    imp = Impingement(
        timestamp=time.time(),
        source="dmn.absolute_threshold",
        type=ImpingementType.ABSOLUTE_THRESHOLD,
        strength=0.9,
        content={"metric": "drink_per_capita", "value": 0, "threshold": 10},
    )
    text = render_impingement_text(imp)
    assert "source: dmn.absolute_threshold" in text
    assert "signal: drink_per_capita" in text
    assert "value: 0" in text


def test_render_impingement_text_with_interrupt():
    imp = Impingement(
        timestamp=time.time(),
        source="dmn.absolute_threshold",
        type=ImpingementType.ABSOLUTE_THRESHOLD,
        strength=1.0,
        content={"metric": "extinction_risk"},
        interrupt_token="population_critical",
    )
    text = render_impingement_text(imp)
    assert "critical: population_critical" in text


def test_embedding_cache_hit():
    from shared.affordance_pipeline import EmbeddingCache

    cache = EmbeddingCache(max_size=10)
    content = {"metric": "test", "value": 42}
    vec = [0.1] * 768
    cache.put(content, vec)
    assert cache.get(content) == vec


def test_embedding_cache_miss():
    from shared.affordance_pipeline import EmbeddingCache

    cache = EmbeddingCache()
    assert cache.get({"metric": "unknown"}) is None


def test_embedding_cache_eviction():
    from shared.affordance_pipeline import EmbeddingCache

    cache = EmbeddingCache(max_size=2)
    cache.put({"a": 1}, [0.1])
    cache.put({"b": 2}, [0.2])
    cache.put({"c": 3}, [0.3])
    assert cache.get({"a": 1}) is None
    assert cache.get({"b": 2}) == [0.2]
    assert cache.get({"c": 3}) == [0.3]


def test_interrupt_bypass():
    from shared.affordance_pipeline import AffordancePipeline

    pipeline = AffordancePipeline()
    pipeline.register_interrupt("population_critical", "fortress_governance", "fortress")
    imp = Impingement(
        timestamp=time.time(),
        source="dmn.absolute_threshold",
        type=ImpingementType.ABSOLUTE_THRESHOLD,
        strength=1.0,
        content={"metric": "extinction_risk"},
        interrupt_token="population_critical",
    )
    results = pipeline.select(imp)
    assert len(results) == 1
    assert results[0].capability_name == "fortress_governance"
    assert results[0].combined == 1.0


def test_interrupt_bypass_no_handler():
    from shared.affordance_pipeline import AffordancePipeline

    pipeline = AffordancePipeline()
    imp = Impingement(
        timestamp=time.time(),
        source="test",
        type=ImpingementType.PATTERN_MATCH,
        strength=0.5,
        interrupt_token="unknown_token",
    )
    results = pipeline.select(imp)
    assert len(results) == 0


def test_inhibition_blocks_repeat():
    from shared.affordance_pipeline import AffordancePipeline

    pipeline = AffordancePipeline()
    imp = Impingement(
        timestamp=time.time(),
        source="dmn.sensory",
        type=ImpingementType.STATISTICAL_DEVIATION,
        strength=0.5,
        content={"metric": "flow_drop", "value": 0.3},
    )
    pipeline.add_inhibition(imp, duration_s=60.0)
    results = pipeline.select(imp)
    assert results == []


def test_normalize_base_level():
    from shared.affordance_pipeline import AffordancePipeline

    norm = AffordancePipeline._normalize_base_level
    assert norm(-10.0) < 0.001
    assert norm(5.0) > 0.99
    assert abs(norm(0.0) - 0.5) < 0.01


def test_context_boost_with_learned_association():
    from shared.affordance_pipeline import AffordancePipeline

    pipeline = AffordancePipeline()
    pipeline.update_context_association("nominal", "speech_production", delta=0.5)
    boost = pipeline._compute_context_boost("speech_production", {"stimmung_stance": "nominal"})
    assert boost > 0.0


def test_context_boost_without_association():
    from shared.affordance_pipeline import AffordancePipeline

    pipeline = AffordancePipeline()
    boost = pipeline._compute_context_boost("speech_production", {"stimmung_stance": "critical"})
    assert boost == 0.0


def test_context_boost_without_context():
    from shared.affordance_pipeline import AffordancePipeline

    pipeline = AffordancePipeline()
    assert pipeline._compute_context_boost("speech_production", None) == 0.0


def test_selection_candidate_fields():
    c = SelectionCandidate(
        capability_name="test",
        similarity=0.8,
        base_level=0.5,
        thompson_score=0.6,
        cost_weight=0.85,
        combined=0.72,
    )
    assert c.capability_name == "test"
    assert not c.suppressed


def test_record_success_updates_activation():
    from shared.affordance_pipeline import AffordancePipeline

    pipeline = AffordancePipeline()
    pipeline.record_success("test_cap")
    state = pipeline.get_activation_state("test_cap")
    assert state.use_count == 1
    assert state.ts_alpha > 1.0


def test_record_failure_updates_activation():
    from shared.affordance_pipeline import AffordancePipeline

    pipeline = AffordancePipeline()
    pipeline.record_failure("test_cap")
    state = pipeline.get_activation_state("test_cap")
    assert state.ts_beta > 1.0
    assert state.use_count == 0


def test_affordances_collection_in_schema():
    from shared.qdrant_schema import EXPECTED_COLLECTIONS

    assert "affordances" in EXPECTED_COLLECTIONS
    assert EXPECTED_COLLECTIONS["affordances"]["distance"] == "Cosine"
