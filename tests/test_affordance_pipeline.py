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

    def test_batch_payload_includes_risk_metadata(self):
        from unittest.mock import MagicMock, patch

        from shared.affordance import CapabilityRecord, OperationalProperties
        from shared.affordance_pipeline import AffordancePipeline

        records = [
            CapabilityRecord(
                name="public_cap",
                description="Public capability description",
                daemon="test",
                operational=OperationalProperties(
                    latency_class="fast",
                    medium="visual",
                    public_capable=True,
                    consent_required=True,
                    consent_person_id="guest",
                    consent_data_category="video",
                    monetization_risk="low",
                    risk_reason="test monetization reason",
                    content_risk="tier_1_platform_cleared",
                    content_risk_reason="test content reason",
                    rights_ref="rights:test",
                    provenance_ref="provenance:test",
                    evidence_refs=("evidence:test",),
                ),
            )
        ]

        with (
            patch("shared.affordance_pipeline.embed_batch_safe", return_value=[[1.0] * 768]),
            patch("shared.config.get_qdrant") as mock_qdrant,
        ):
            mock_client = MagicMock()
            mock_client.collection_exists.return_value = True
            mock_qdrant.return_value = mock_client

            pipeline = AffordancePipeline()
            assert pipeline.index_capabilities_batch(records) == 1

        point = mock_client.upsert.call_args.kwargs["points"][0]
        assert point.payload["consent_required"] is True
        assert point.payload["consent_person_id"] == "guest"
        assert point.payload["consent_data_category"] == "video"
        assert point.payload["public_capable"] is True
        assert point.payload["monetization_risk"] == "low"
        assert point.payload["risk_reason"] == "test monetization reason"
        assert point.payload["content_risk"] == "tier_1_platform_cleared"
        assert point.payload["content_risk_reason"] == "test content reason"
        assert point.payload["rights_ref"] == "rights:test"
        assert point.payload["provenance_ref"] == "provenance:test"
        assert point.payload["evidence_refs"] == ["evidence:test"]

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


# ----- Consent gate (2026-04-12 audit follow-up) -----
#
# Closes a systemic axiom-enforcement gap surfaced by the beta audit:
# every capability declaring `consent_required=True` in
# shared/affordance_registry.py was being recruited as if no consent
# contract gate existed. The gate now lives in
# AffordancePipeline._consent_allows and is exercised by select() before
# scoring.


class TestConsentGate:
    def _candidate(
        self,
        *,
        consent_required: bool,
        person_id: str | None = "guest",
        data_category: str | None = "video",
    ):
        from shared.affordance import SelectionCandidate

        name = "studio.toggle_livestream" if consent_required else "studio.activate_preset"
        payload = {"consent_required": consent_required}
        if person_id is not None:
            payload["consent_person_id"] = person_id
        if data_category is not None:
            payload["consent_data_category"] = data_category
        return SelectionCandidate(
            capability_name=name,
            similarity=0.9,
            payload=payload,
        )

    def _pipeline(self):
        from shared.affordance_pipeline import AffordancePipeline

        return AffordancePipeline()

    def _registry(self, person_id: str, scope: frozenset[str]):
        from shared.governance.consent import ConsentRegistry

        registry = ConsentRegistry(_contracts_dir=None)
        registry.create_contract(person_id, scope, contract_id=f"contract-{person_id}")
        return registry

    def test_candidate_without_consent_flag_passes_unconditionally(self):
        # Fast path: consent_required absent or False short-circuits
        # before any contract load.
        from unittest.mock import patch

        p = self._pipeline()
        cand = self._candidate(consent_required=False)
        with patch("shared.governance.consent.load_contracts") as mock_load:
            assert p._consent_allows(cand) is True
            mock_load.assert_not_called()

    def test_consent_required_blocked_when_no_active_contracts(self):
        # The case the audit surfaced — the pipeline previously failed
        # OPEN here, recruiting consent_required capabilities even with
        # no active contracts.
        from unittest.mock import MagicMock, patch

        p = self._pipeline()
        cand = self._candidate(consent_required=True)
        empty_registry = MagicMock()
        empty_registry.contract_check.return_value = False
        with patch(
            "shared.governance.consent.load_contracts",
            return_value=empty_registry,
        ) as mock_load:
            assert p._consent_allows(cand) is False
        mock_load.assert_called_once_with(strict=True)
        empty_registry.contract_check.assert_called_once_with("guest", "video")

    def test_consent_required_allowed_when_matching_scoped_contract_exists(self):
        # Happy path: the active contract must match the candidate's
        # person/category requirement, not merely exist.
        from unittest.mock import patch

        p = self._pipeline()
        cand = self._candidate(consent_required=True)
        registry = self._registry("guest", frozenset({"video"}))
        with patch("shared.governance.consent.load_contracts", return_value=registry):
            assert p._consent_allows(cand) is True

    def test_audio_contract_does_not_authorize_video_candidate(self):
        from unittest.mock import patch

        p = self._pipeline()
        cand = self._candidate(consent_required=True, person_id="guest", data_category="video")
        registry = self._registry("guest", frozenset({"audio"}))
        with patch("shared.governance.consent.load_contracts", return_value=registry):
            assert p._consent_allows(cand) is False

    def test_unrelated_active_contract_does_not_authorize_all_candidates(self):
        from unittest.mock import patch

        p = self._pipeline()
        cand = self._candidate(consent_required=True, person_id="guest", data_category="video")
        registry = self._registry("jason_kleeberger", frozenset({"video"}))
        with patch("shared.governance.consent.load_contracts", return_value=registry):
            assert p._consent_allows(cand) is False

    def test_missing_consent_scope_fails_closed(self):
        from unittest.mock import patch

        p = self._pipeline()
        cand = self._candidate(
            consent_required=True,
            person_id=None,
            data_category=None,
        )
        with patch("shared.governance.consent.load_contracts") as mock_load:
            assert p._consent_allows(cand) is False
            mock_load.assert_not_called()

    def test_operator_network_authorization_is_not_interpersonal_consent(self):
        from unittest.mock import patch

        p = self._pipeline()
        cand = self._candidate(
            consent_required=True,
            person_id="operator",
            data_category="network",
        )
        with patch("shared.governance.consent.load_contracts") as mock_load:
            assert p._consent_allows(cand) is False
            mock_load.assert_not_called()

    def test_consent_load_failure_fails_closed(self):
        # If contract loading raises (consent infra broken), the gate
        # blocks consent_required candidates. Matches the wider
        # consent-engine fail-closed control law.
        from unittest.mock import patch

        p = self._pipeline()
        cand = self._candidate(consent_required=True)
        with patch(
            "shared.governance.consent.load_contracts", side_effect=RuntimeError("bad yaml")
        ):
            assert p._consent_allows(cand) is False

    def test_consent_decision_is_cached(self):
        # The cache is the reason this gate can run per-frame in the
        # reverie mixer. Two consecutive consent-required checks within
        # the TTL window must trigger only one contract load.
        from unittest.mock import MagicMock, patch

        p = self._pipeline()
        cand = self._candidate(consent_required=True)
        registry = MagicMock()
        registry.contract_check.return_value = True
        with patch("shared.governance.consent.load_contracts", return_value=registry) as mock_load:
            assert p._consent_allows(cand) is True
            assert p._consent_allows(cand) is True
            assert mock_load.call_count == 1
            assert registry.contract_check.call_count == 1

    def test_consent_cache_is_keyed_by_scope_signature(self):
        from unittest.mock import MagicMock, patch

        p = self._pipeline()
        video = self._candidate(
            consent_required=True,
            person_id="guest",
            data_category="video",
        )
        audio = self._candidate(
            consent_required=True,
            person_id="guest",
            data_category="audio",
        )
        registry = MagicMock()
        registry.contract_check.side_effect = lambda person_id, data_category: (
            person_id == "guest" and data_category == "audio"
        )
        with patch("shared.governance.consent.load_contracts", return_value=registry) as mock_load:
            assert p._consent_allows(video) is False
            assert p._consent_allows(audio) is True
            assert mock_load.call_count == 1
            assert registry.contract_check.call_count == 2

    def test_consent_cache_refreshes_after_ttl(self):
        # After the TTL window expires, the next consent-required check
        # must reload — otherwise newly-revoked contracts would not take
        # effect until daemon restart.
        from unittest.mock import MagicMock, patch

        from shared import affordance_pipeline as ap_mod

        p = self._pipeline()
        cand = self._candidate(consent_required=True)
        registry = MagicMock()
        registry.contract_check.return_value = True
        with patch("shared.governance.consent.load_contracts", return_value=registry) as mock_load:
            assert p._consent_allows(cand) is True
            # Force the cache stamp into the past so the next call
            # exceeds _CONSENT_CACHE_TTL_S regardless of wall-clock.
            p._consent_loaded_at -= ap_mod._CONSENT_CACHE_TTL_S + 1.0
            assert p._consent_allows(cand) is True
            assert mock_load.call_count == 2
            assert registry.contract_check.call_count == 2


class TestConsentRefusalBriefEmission:
    """Refusal-as-data emission: when the consent gate blocks, an event
    lands in the canonical refusal log. Bounded to ≤1 emit per cache TTL
    per pipeline because emit only fires inside the cache-load branch.
    """

    def _candidate(self):
        from shared.affordance import SelectionCandidate

        return SelectionCandidate(
            capability_name="studio.toggle_livestream",
            similarity=0.9,
            payload={
                "consent_required": True,
                "consent_person_id": "guest",
                "consent_data_category": "video",
            },
        )

    def test_emits_on_no_active_contracts(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        from shared.affordance_pipeline import AffordancePipeline

        captured = []
        import agents.refusal_brief as _pkg

        monkeypatch.setattr(_pkg, "append", lambda ev, **_: captured.append(ev) or True)

        empty_registry = MagicMock()
        empty_registry.contract_check.return_value = False
        with patch("shared.governance.consent.load_contracts", return_value=empty_registry):
            assert AffordancePipeline()._consent_allows(self._candidate()) is False

        assert len(captured) == 1
        assert captured[0].surface == "affordance_pipeline:consent_gate"
        assert captured[0].axiom == "interpersonal_transparency"
        assert "no matching active consent contract" in captured[0].reason

    def test_emits_on_loader_exception(self, monkeypatch):
        from unittest.mock import patch

        from shared.affordance_pipeline import AffordancePipeline

        captured = []
        import agents.refusal_brief as _pkg

        monkeypatch.setattr(_pkg, "append", lambda ev, **_: captured.append(ev) or True)

        with patch(
            "shared.governance.consent.load_contracts", side_effect=RuntimeError("bad yaml")
        ):
            assert AffordancePipeline()._consent_allows(self._candidate()) is False

        assert len(captured) == 1
        assert "exception" in captured[0].reason.lower()

    def test_no_emit_when_consent_active(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        from shared.affordance_pipeline import AffordancePipeline

        captured = []
        import agents.refusal_brief as _pkg

        monkeypatch.setattr(_pkg, "append", lambda ev, **_: captured.append(ev) or True)

        registry = MagicMock()
        registry.contract_check.return_value = True
        with patch("shared.governance.consent.load_contracts", return_value=registry):
            assert AffordancePipeline()._consent_allows(self._candidate()) is True

        assert captured == []

    def test_emit_bounded_by_cache_ttl(self, monkeypatch):
        """N consecutive blocked checks within the TTL window → at most one emit."""
        from unittest.mock import MagicMock, patch

        from shared.affordance_pipeline import AffordancePipeline

        captured = []
        import agents.refusal_brief as _pkg

        monkeypatch.setattr(_pkg, "append", lambda ev, **_: captured.append(ev) or True)

        empty_registry = MagicMock()
        empty_registry.contract_check.return_value = False
        p = AffordancePipeline()
        cand = self._candidate()
        with patch("shared.governance.consent.load_contracts", return_value=empty_registry):
            for _ in range(20):
                p._consent_allows(cand)

        assert len(captured) == 1

    def test_missing_scope_emit_bounded_by_cache_ttl(self, monkeypatch):
        """Missing scoped metadata also stays bounded on hot paths."""
        from shared.affordance import SelectionCandidate
        from shared.affordance_pipeline import AffordancePipeline

        captured = []
        import agents.refusal_brief as _pkg

        monkeypatch.setattr(_pkg, "append", lambda ev, **_: captured.append(ev) or True)

        p = AffordancePipeline()
        cand = SelectionCandidate(
            capability_name="studio.toggle_livestream",
            similarity=0.9,
            payload={"consent_required": True},
        )
        for _ in range(20):
            p._consent_allows(cand)

        assert len(captured) == 1

    def test_writer_failure_does_not_break_gate(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        import agents.refusal_brief as _pkg
        from shared.affordance_pipeline import AffordancePipeline

        def _boom(*_a, **_k):
            raise RuntimeError("writer is on fire")

        monkeypatch.setattr(_pkg, "append", _boom)

        empty_registry = MagicMock()
        empty_registry.contract_check.return_value = False
        with patch("shared.governance.consent.load_contracts", return_value=empty_registry):
            # Must not raise — gate decision still returned.
            assert AffordancePipeline()._consent_allows(self._candidate()) is False


class TestFallbackHardGates:
    def _candidate(self, **payload):
        from shared.affordance import SelectionCandidate

        base_payload = {
            "consent_required": False,
            "consent_person_id": "guest",
            "consent_data_category": "video",
            "public_capable": False,
            "monetization_risk": "none",
            "content_risk": "tier_0_owned",
        }
        base_payload.update(payload)
        return SelectionCandidate(
            capability_name="fallback.capability",
            similarity=0.9,
            payload=base_payload,
        )

    def _impingement(self):
        return Impingement(
            timestamp=time.time(),
            source="dmn",
            type=ImpingementType.STATISTICAL_DEVIATION,
            strength=0.5,
            content={"metric": "fallback keyword"},
        )

    def _select_fallback(self, pipeline, candidate):
        from unittest.mock import patch

        with (
            patch.object(pipeline, "_get_embedding", return_value=None),
            patch.object(pipeline, "_fallback_keyword_match", return_value=[candidate]),
            patch.object(pipeline, "_active_programme_cached", return_value=None),
        ):
            return pipeline.select(self._impingement())

    def test_safe_fallback_candidate_survives_hard_gates(self):
        from shared.affordance_pipeline import AffordancePipeline

        p = AffordancePipeline()
        candidate = self._candidate()

        assert self._select_fallback(p, candidate) == [candidate]

    def test_fallback_runs_consent_gate(self):
        from unittest.mock import MagicMock, patch

        from shared.affordance_pipeline import AffordancePipeline

        empty_registry = MagicMock()
        empty_registry.contract_check.return_value = False
        p = AffordancePipeline()
        candidate = self._candidate(consent_required=True)

        with patch("shared.governance.consent.load_contracts", return_value=empty_registry):
            assert self._select_fallback(p, candidate) == []

    def test_fallback_runs_monetization_gate(self):
        from unittest.mock import patch

        from shared.affordance_pipeline import AffordancePipeline

        p = AffordancePipeline()
        candidate = self._candidate(monetization_risk="high")

        with patch("shared.governance.monetization_safety._AUDIT_ENABLED", False):
            assert self._select_fallback(p, candidate) == []

    def test_fallback_runs_content_risk_gate(self):
        from shared.affordance_pipeline import AffordancePipeline

        p = AffordancePipeline()
        candidate = self._candidate(content_risk="tier_4_risky")

        assert self._select_fallback(p, candidate) == []
