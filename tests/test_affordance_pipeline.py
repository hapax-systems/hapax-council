"""Tests for the affordance-as-retrieval pipeline (Phase R0)."""

import time

from shared.affordance import (
    ActivationState,
    CapabilityRecord,
    OperationalProperties,
)
from shared.impingement import Impingement, ImpingementType, render_impingement_text


def test_base_level_never_used():
    assert ActivationState().base_level(time.time()) == -10.0


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
    assert min(samples) < 0.3 and max(samples) > 0.7


def test_thompson_record_success_shifts():
    state = ActivationState()
    for _ in range(20):
        state.record_success()
    assert sum(state.thompson_sample() for _ in range(50)) / 50 > 0.7


def test_thompson_record_failure_shifts():
    state = ActivationState()
    for _ in range(20):
        state.record_failure()
    assert sum(state.thompson_sample() for _ in range(50)) / 50 < 0.3


def test_thompson_discount():
    state = ActivationState()
    for _ in range(100):
        state.record_success(gamma=0.99)
    assert state.ts_alpha > state.ts_beta * 5


def test_capability_record():
    rec = CapabilityRecord(
        name="speech",
        description="Produces audible language.",
        daemon="voice",
        operational=OperationalProperties(requires_gpu=True),
    )
    assert rec.operational.requires_gpu and not rec.operational.consent_required


def test_impingement_embedding_optional():
    imp = Impingement(
        timestamp=time.time(), source="test", type=ImpingementType.ABSOLUTE_THRESHOLD, strength=0.5
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
        content={"metric": "drink_per_capita", "value": 0},
    )
    text = render_impingement_text(imp)
    assert "signal: drink_per_capita" in text and "value: 0" in text


def test_render_with_interrupt():
    imp = Impingement(
        timestamp=time.time(),
        source="dmn",
        type=ImpingementType.ABSOLUTE_THRESHOLD,
        strength=1.0,
        content={"metric": "x"},
        interrupt_token="population_critical",
    )
    assert "critical: population_critical" in render_impingement_text(imp)


def test_embedding_cache_hit():
    from shared.affordance_pipeline import EmbeddingCache

    cache = EmbeddingCache(max_size=10)
    cache.put({"metric": "test"}, [0.1] * 768)
    assert cache.get({"metric": "test"}) == [0.1] * 768


def test_embedding_cache_miss():
    from shared.affordance_pipeline import EmbeddingCache

    assert EmbeddingCache().get({"metric": "unknown"}) is None


def test_embedding_cache_eviction():
    from shared.affordance_pipeline import EmbeddingCache

    cache = EmbeddingCache(max_size=2)
    cache.put({"a": 1}, [0.1])
    cache.put({"b": 2}, [0.2])
    cache.put({"c": 3}, [0.3])
    assert cache.get({"a": 1}) is None and cache.get({"c": 3}) == [0.3]


def test_interrupt_bypass():
    from shared.affordance_pipeline import AffordancePipeline

    p = AffordancePipeline()
    p.register_interrupt("population_critical", "fortress_governance", "fortress")
    imp = Impingement(
        timestamp=time.time(),
        source="dmn",
        type=ImpingementType.ABSOLUTE_THRESHOLD,
        strength=1.0,
        content={"metric": "x"},
        interrupt_token="population_critical",
    )
    results = p.select(imp)
    assert len(results) == 1 and results[0].capability_name == "fortress_governance"


def test_interrupt_no_handler():
    from shared.affordance_pipeline import AffordancePipeline

    imp = Impingement(
        timestamp=time.time(),
        source="test",
        type=ImpingementType.PATTERN_MATCH,
        strength=0.5,
        interrupt_token="unknown",
    )
    assert AffordancePipeline().select(imp) == []


def test_inhibition_blocks():
    from shared.affordance_pipeline import AffordancePipeline

    p = AffordancePipeline()
    imp = Impingement(
        timestamp=time.time(),
        source="dmn",
        type=ImpingementType.STATISTICAL_DEVIATION,
        strength=0.5,
        content={"metric": "flow_drop"},
    )
    p.add_inhibition(imp, duration_s=60.0)
    assert p.select(imp) == []


def test_normalize_base_level():
    from shared.affordance_pipeline import AffordancePipeline

    assert AffordancePipeline._normalize_base_level(-10.0) < 0.001
    assert AffordancePipeline._normalize_base_level(5.0) > 0.99
    assert abs(AffordancePipeline._normalize_base_level(0.0) - 0.5) < 0.01


def test_context_boost_with_association():
    from shared.affordance_pipeline import AffordancePipeline

    p = AffordancePipeline()
    p.update_context_association("nominal", "speech", delta=0.5)
    assert p._compute_context_boost("speech", {"stance": "nominal"}) > 0.0


def test_context_boost_no_association():
    from shared.affordance_pipeline import AffordancePipeline

    assert AffordancePipeline()._compute_context_boost("speech", {"stance": "critical"}) == 0.0


def test_context_boost_no_context():
    from shared.affordance_pipeline import AffordancePipeline

    assert AffordancePipeline()._compute_context_boost("speech", None) == 0.0


def test_record_success():
    from shared.affordance_pipeline import AffordancePipeline

    p = AffordancePipeline()
    p.record_success("cap")
    assert p.get_activation_state("cap").use_count == 1


def test_record_failure():
    from shared.affordance_pipeline import AffordancePipeline

    p = AffordancePipeline()
    p.record_failure("cap")
    assert (
        p.get_activation_state("cap").ts_beta > 1.0 and p.get_activation_state("cap").use_count == 1
    )


def test_affordances_in_schema():
    from shared.qdrant_schema import EXPECTED_COLLECTIONS

    assert "affordances" in EXPECTED_COLLECTIONS


class TestBatchIndexing:
    def test_batch_indexes_all_capabilities(self):
        from unittest.mock import MagicMock, patch

        from shared.affordance import CapabilityRecord, OperationalProperties
        from shared.affordance_pipeline import AffordancePipeline

        records = [
            CapabilityRecord(
                name=f"cap_{i}",
                description=f"Capability {i} description",
                daemon="test",
                operational=OperationalProperties(),
            )
            for i in range(5)
        ]

        fake_embeddings = [[float(i)] * 768 for i in range(5)]

        with (
            patch("shared.affordance_pipeline.embed_batch_safe", return_value=fake_embeddings),
            patch("shared.config.get_qdrant") as mock_qdrant,
        ):
            mock_client = MagicMock()
            mock_client.collection_exists.return_value = True
            mock_qdrant.return_value = mock_client

            pipeline = AffordancePipeline()
            count = pipeline.index_capabilities_batch(records)

        assert count == 5
        mock_client.upsert.assert_called_once()
        points = mock_client.upsert.call_args.kwargs["points"]
        assert len(points) == 5

    def test_batch_uses_disk_cache(self, tmp_path):
        from unittest.mock import MagicMock, patch

        from shared.affordance import CapabilityRecord, OperationalProperties
        from shared.affordance_pipeline import AffordancePipeline
        from shared.embed_cache import DiskEmbeddingCache

        records = [
            CapabilityRecord(
                name="cached_cap",
                description="Already cached description",
                daemon="test",
                operational=OperationalProperties(),
            ),
            CapabilityRecord(
                name="new_cap",
                description="Brand new description",
                daemon="test",
                operational=OperationalProperties(),
            ),
        ]

        # Pre-populate cache with one entry
        cache = DiskEmbeddingCache(
            cache_path=tmp_path / "cache.json", model="nomic-embed-cpu", dimension=768
        )
        cache.put("search_document: Already cached description", [0.5] * 768)
        cache.save()

        with (
            patch(
                "shared.affordance_pipeline.embed_batch_safe",
                return_value=[[0.9] * 768],
            ) as mock_embed,
            patch("shared.config.get_qdrant") as mock_qdrant,
            patch(
                "shared.affordance_pipeline._DISK_CACHE_PATH",
                tmp_path / "cache.json",
            ),
        ):
            mock_client = MagicMock()
            mock_client.collection_exists.return_value = True
            mock_qdrant.return_value = mock_client

            pipeline = AffordancePipeline()
            count = pipeline.index_capabilities_batch(records)

        assert count == 2
        # Only the uncached description should have been embedded
        mock_embed.assert_called_once()
        embedded_texts = mock_embed.call_args.args[0]
        assert len(embedded_texts) == 1
        assert "Brand new" in embedded_texts[0]

    def test_batch_empty_list_returns_zero(self):
        from shared.affordance_pipeline import AffordancePipeline

        pipeline = AffordancePipeline()
        assert pipeline.index_capabilities_batch([]) == 0


class TestEmbeddingCacheTextKey:
    def test_same_text_hits_cache(self):
        from shared.affordance_pipeline import EmbeddingCache

        cache = EmbeddingCache()
        vec = [0.1, 0.2, 0.3]
        cache.put_by_text("source: dmn intent: stable", vec)
        assert cache.get_by_text("source: dmn intent: stable") == vec

    def test_different_text_misses_cache(self):
        from shared.affordance_pipeline import EmbeddingCache

        cache = EmbeddingCache()
        cache.put_by_text("source: dmn intent: stable", [0.1, 0.2, 0.3])
        assert cache.get_by_text("source: dmn intent: degrading") is None

    def test_lru_eviction_by_text(self):
        from shared.affordance_pipeline import EmbeddingCache

        cache = EmbeddingCache(max_size=2)
        cache.put_by_text("a", [1.0])
        cache.put_by_text("b", [2.0])
        cache.put_by_text("c", [3.0])  # evicts "a"
        assert cache.get_by_text("a") is None
        assert cache.get_by_text("b") == [2.0]
