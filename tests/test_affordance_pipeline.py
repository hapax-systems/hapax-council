"""Tests for the affordance-as-retrieval pipeline (Phase R0)."""

import time

import pytest

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


def test_get_embedding_is_nonblocking_for_event_loop():
    """The reactive recruitment embed MUST be non-blocking (block_gpu=False):
    _get_embedding runs synchronously in the logos-api asyncio loop via
    _handle_change -> select, so a blocking GPU-semaphore acquire there wedges
    the :8051 API (the logos-api hang)."""
    from unittest.mock import patch

    from shared.affordance_pipeline import AffordancePipeline

    captured: dict[str, object] = {}

    def fake_embed_safe(text, model=None, prefix="search_query", block_gpu=True):
        captured["block_gpu"] = block_gpu
        return None

    p = AffordancePipeline()
    imp = Impingement(
        timestamp=time.time(),
        source="dmn",
        type=ImpingementType.ABSOLUTE_THRESHOLD,
        strength=1.0,
        content={"metric": "x"},
    )
    with patch("shared.config.embed_safe", fake_embed_safe):
        p._get_embedding(imp)
    assert captured.get("block_gpu") is False


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

    def test_domain_field_survives_both_payload_writers(self):
        """Phase 1 unified-fx: the ``domain`` tag must serialize through BOTH
        index_capability and index_capabilities_batch. A miss in either writer
        silently falls back to ``content`` with no error — the exact invisible
        drift the domain tag exists to eliminate."""
        from unittest.mock import MagicMock, patch

        from shared.affordance import CapabilityRecord, OperationalProperties
        from shared.affordance_pipeline import AffordancePipeline

        both = CapabilityRecord(
            name="rutt_etra_cap",
            description="dual-domain effect",
            daemon="test",
            operational=OperationalProperties(domain="both"),
        )
        default = CapabilityRecord(
            name="plain_cap",
            description="content-only effect",
            daemon="test",
            operational=OperationalProperties(),
        )

        with (
            patch(
                "shared.affordance_pipeline.embed_batch_safe",
                side_effect=lambda texts, *a, **k: [[1.0] * 768 for _ in texts],
            ),
            patch("shared.config.embed_safe", return_value=[1.0] * 768),
            patch("shared.config.get_qdrant") as mock_qdrant,
        ):
            mock_client = MagicMock()
            mock_client.collection_exists.return_value = True
            mock_qdrant.return_value = mock_client
            pipeline = AffordancePipeline()

            # batch writer
            assert pipeline.index_capabilities_batch([both, default]) == 2
            by_name = {
                p.payload["capability_name"]: p.payload
                for p in mock_client.upsert.call_args.kwargs["points"]
            }
            assert by_name["rutt_etra_cap"]["domain"] == "both"
            assert by_name["plain_cap"]["domain"] == "content"

            # singular writer
            mock_client.upsert.reset_mock()
            assert pipeline.index_capability(both) is True
            single = mock_client.upsert.call_args.kwargs["points"][0].payload
            assert single["domain"] == "both"

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

    def test_consent_registry_is_cached_but_decision_is_revalidated(self):
        # The registry cache is the reason this gate can run per-frame in
        # the reverie mixer: two consecutive checks within the TTL window
        # trigger only one contract load. The decision itself is not
        # cached — every use re-runs the registry check, so a positive
        # grant never outlives the validation that produced it.
        from unittest.mock import MagicMock, patch

        p = self._pipeline()
        cand = self._candidate(consent_required=True)
        registry = MagicMock()
        registry.contract_check.return_value = True
        with patch("shared.governance.consent.load_contracts", return_value=registry) as mock_load:
            assert p._consent_allows(cand) is True
            assert p._consent_allows(cand) is True
            assert mock_load.call_count == 1
            assert registry.contract_check.call_count == 2

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


def test_interrupt_path_runs_consent_gate():
    """Interrupt handlers must pass through hard gates — no bypass."""
    from unittest.mock import patch

    from shared.affordance_pipeline import AffordancePipeline

    p = AffordancePipeline()
    p.register_interrupt("test_token", "consent_gated_cap", "test_daemon")

    imp = Impingement(
        timestamp=time.time(),
        source="test",
        type=ImpingementType.ABSOLUTE_THRESHOLD,
        strength=1.0,
        content={"metric": "test"},
        interrupt_token="test_token",
    )

    with patch.object(p, "_consent_allows", return_value=False):
        results = p.select(imp)
        assert results == [], "Interrupt candidates must be blocked when consent gate denies"


def test_interrupt_path_runs_monetization_gate():
    """Interrupt handlers must pass through monetization gate."""
    from unittest.mock import patch

    from shared.affordance_pipeline import AffordancePipeline
    from shared.governance.monetization_safety import GATE

    p = AffordancePipeline()
    p.register_interrupt("test_token", "risky_cap", "test_daemon")

    imp = Impingement(
        timestamp=time.time(),
        source="test",
        type=ImpingementType.ABSOLUTE_THRESHOLD,
        strength=1.0,
        content={"metric": "test"},
        interrupt_token="test_token",
    )

    with patch.object(GATE, "candidate_filter", return_value=[]):
        results = p.select(imp)
        assert results == [], "Interrupt candidates must be blocked when monetization gate denies"


class TestConsentFailureNeverBecomesPermission:
    """A warm positive grant never outlives the validation that produced it.

    Every case here starts from a real, granted decision and then breaks
    the consent state underneath it inside the cache TTL: revocation,
    removal, malformed or unreadable contract bytes, a failed current
    check (the custody-failure shape once identity custody is required),
    or a non-boolean answer. Each must refuse on the very next decision.
    """

    SUBJECT = "synthetic-subject-a"

    def _candidate(self, data_category: str = "video"):
        from shared.affordance import SelectionCandidate

        return SelectionCandidate(
            capability_name="studio.toggle_livestream",
            similarity=0.9,
            payload={
                "consent_required": True,
                "consent_person_id": self.SUBJECT,
                "consent_data_category": data_category,
            },
        )

    def _write_contract(self, directory, *, revoked: bool = False) -> None:
        import yaml

        data = {
            "id": "contract-synthetic-a",
            "parties": ["operator", self.SUBJECT],
            "scope": ["video"],
            "direction": "one_way",
            "visibility_mechanism": "on_request",
            "created_at": "2026-09-25T00:00:00Z",
        }
        if revoked:
            data["revoked_at"] = "2026-09-25T00:00:01Z"
        (directory / "contract-synthetic-a.yaml").write_text(yaml.safe_dump(data))

    def _contracts_dir(self, tmp_path, monkeypatch):
        import shared.governance.consent as consent_mod

        directory = tmp_path / "contracts"
        directory.mkdir()
        self._write_contract(directory)
        monkeypatch.setattr(consent_mod, "_CONTRACTS_DIR", directory)
        # Keep the live consent-engine health file out of the test.
        monkeypatch.setattr(consent_mod, "publish_health", lambda *_a, **_k: None)
        return directory

    def _capture_refusals(self, monkeypatch) -> list:
        import agents.refusal_brief as _pkg

        captured: list = []
        monkeypatch.setattr(_pkg, "append", lambda ev, **_: captured.append(ev) or True)
        return captured

    def test_positive_control_grant_is_allowed_and_registry_reused(self, tmp_path, monkeypatch):
        from unittest.mock import patch

        import shared.governance.consent as consent_mod
        from shared.affordance_pipeline import AffordancePipeline

        self._contracts_dir(tmp_path, monkeypatch)
        p = AffordancePipeline()
        with patch.object(
            consent_mod, "load_contracts", wraps=consent_mod.load_contracts
        ) as mock_load:
            for _ in range(3):
                assert p._consent_allows(self._candidate()) is True
        assert mock_load.call_count == 1

    def test_negative_control_other_category_is_refused(self, tmp_path, monkeypatch):
        from shared.affordance_pipeline import AffordancePipeline

        self._contracts_dir(tmp_path, monkeypatch)
        assert AffordancePipeline()._consent_allows(self._candidate("audio")) is False

    def test_warm_grant_does_not_survive_revocation_within_ttl(self, tmp_path, monkeypatch):
        from shared.affordance_pipeline import AffordancePipeline

        directory = self._contracts_dir(tmp_path, monkeypatch)
        p = AffordancePipeline()
        assert p._consent_allows(self._candidate()) is True
        self._write_contract(directory, revoked=True)
        assert p._consent_allows(self._candidate()) is False

    def test_warm_grant_does_not_survive_contract_removal(self, tmp_path, monkeypatch):
        from shared.affordance_pipeline import AffordancePipeline

        directory = self._contracts_dir(tmp_path, monkeypatch)
        p = AffordancePipeline()
        assert p._consent_allows(self._candidate()) is True
        (directory / "contract-synthetic-a.yaml").unlink()
        assert p._consent_allows(self._candidate()) is False

    def test_warm_grant_does_not_survive_missing_contracts_dir(self, tmp_path, monkeypatch):
        import shutil

        from shared.affordance_pipeline import AffordancePipeline

        directory = self._contracts_dir(tmp_path, monkeypatch)
        p = AffordancePipeline()
        assert p._consent_allows(self._candidate()) is True
        shutil.rmtree(directory)
        assert p._consent_allows(self._candidate()) is False

    def test_warm_grant_does_not_survive_malformed_contract(self, tmp_path, monkeypatch):
        from shared.affordance_pipeline import AffordancePipeline

        directory = self._contracts_dir(tmp_path, monkeypatch)
        p = AffordancePipeline()
        assert p._consent_allows(self._candidate()) is True
        (directory / "contract-synthetic-a.yaml").write_text("{")
        assert p._consent_allows(self._candidate()) is False

    def test_warm_grant_does_not_survive_unreadable_contract(self, tmp_path, monkeypatch):
        import os

        import pytest

        from shared.affordance_pipeline import AffordancePipeline

        if os.geteuid() == 0:
            pytest.skip("root reads mode-000 files")
        directory = self._contracts_dir(tmp_path, monkeypatch)
        p = AffordancePipeline()
        assert p._consent_allows(self._candidate()) is True
        target = directory / "contract-synthetic-a.yaml"
        target.chmod(0)
        try:
            assert p._consent_allows(self._candidate()) is False
        finally:
            target.chmod(0o600)

    def test_warm_grant_does_not_survive_failed_current_validation(self):
        # The custody-failure shape: the same held registry that granted a
        # moment ago now raises when asked (identity custody unreadable,
        # missing or conflicting). The failure must refuse, not fall back
        # to the earlier grant.
        from unittest.mock import MagicMock, patch

        from shared.affordance_pipeline import AffordancePipeline

        registry = MagicMock()
        registry.contract_check.side_effect = [True, RuntimeError("custody unavailable")]
        p = AffordancePipeline()
        with patch("shared.governance.consent.load_contracts", return_value=registry):
            assert p._consent_allows(self._candidate()) is True
            assert p._consent_allows(self._candidate()) is False

    def test_non_boolean_answer_is_not_permission(self):
        from unittest.mock import MagicMock, patch

        from shared.affordance_pipeline import AffordancePipeline

        registry = MagicMock()
        registry.contract_check.return_value = "yes"
        with patch("shared.governance.consent.load_contracts", return_value=registry):
            assert AffordancePipeline()._consent_allows(self._candidate()) is False

    def test_fingerprint_covers_exactly_the_files_the_loader_reads(self, tmp_path, monkeypatch):
        # The warm registry is only as fresh as its fingerprint, so the
        # fingerprint must select the same files the strict loader parses:
        # a file the loader reads but the fingerprint skips could change
        # under a warm grant unseen.
        import pathlib

        import shared.governance.consent as consent_mod
        from shared.affordance_pipeline import _contracts_fingerprint

        directory = self._contracts_dir(tmp_path, monkeypatch)
        outside = tmp_path / "outside-target.yaml"
        outside.write_text("")
        for name in (".hidden.yaml", "other.yml", "UPPER.YAML", "notes.txt", "empty.yaml"):
            (directory / name).write_text("")
        (directory / "linked.yaml").symlink_to(outside)
        (directory / "revoked").mkdir()
        (directory / "revoked" / "old.yaml").write_text("")

        read: set[str] = set()
        real_read_text = pathlib.Path.read_text

        def _spy(path, *a, **k):
            if directory in path.parents:
                read.add(path.relative_to(directory).as_posix())
            return real_read_text(path, *a, **k)

        monkeypatch.setattr(pathlib.Path, "read_text", _spy)
        consent_mod.load_contracts(strict=True)
        monkeypatch.setattr(pathlib.Path, "read_text", real_read_text)

        fingerprinted = {entry[0] for entry in _contracts_fingerprint(directory)[3]}
        assert "contract-synthetic-a.yaml" in read
        assert fingerprinted == read

    def test_registry_changed_during_load_is_refused(self, tmp_path, monkeypatch):
        # One coherent snapshot per decision: if the contracts change while
        # they are being loaded, the loaded registry is not the state the
        # decision would claim to rest on.
        import os
        from unittest.mock import MagicMock, patch

        from shared.affordance_pipeline import AffordancePipeline

        directory = self._contracts_dir(tmp_path, monkeypatch)
        registry = MagicMock()
        registry.contract_check.return_value = True

        def _load_while_revoking(*_a, **_k):
            target = directory / "contract-synthetic-a.yaml"
            self._write_contract(directory, revoked=True)
            st = target.stat()
            os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
            return registry

        with patch("shared.governance.consent.load_contracts", side_effect=_load_while_revoking):
            assert AffordancePipeline()._consent_allows(self._candidate()) is False

    def test_changed_during_load_audit_carries_the_reason_token(self, tmp_path, monkeypatch):
        import os
        from unittest.mock import MagicMock, patch

        from shared.affordance_pipeline import AffordancePipeline

        directory = self._contracts_dir(tmp_path, monkeypatch)
        captured = self._capture_refusals(monkeypatch)
        registry = MagicMock()
        registry.contract_check.return_value = True

        def _load_while_touching(*_a, **_k):
            target = directory / "contract-synthetic-a.yaml"
            st = target.stat()
            os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
            return registry

        with patch("shared.governance.consent.load_contracts", side_effect=_load_while_touching):
            assert AffordancePipeline()._consent_allows(self._candidate()) is False
        assert len(captured) == 1
        assert "ConsentSnapshotChanged:contracts_changed_during_load" in captured[0].reason

    def test_custom_failure_reason_token_reaches_the_audit(self, monkeypatch):
        # A check failure class that declares a snake_case reason token (the
        # shape an identity-custody failure takes) is audited as
        # Class:token; its message, which names the subject, is not.
        from unittest.mock import MagicMock, patch

        from shared.affordance_pipeline import AffordancePipeline

        class CustodyUnavailable(RuntimeError):
            reason = "identity_custody_missing"

        captured = self._capture_refusals(monkeypatch)
        registry = MagicMock()
        registry.contract_check.side_effect = CustodyUnavailable(f"custody for {self.SUBJECT}")
        with patch("shared.governance.consent.load_contracts", return_value=registry):
            assert AffordancePipeline()._consent_allows(self._candidate()) is False
        assert len(captured) == 1
        assert "CustodyUnavailable:identity_custody_missing" in captured[0].reason
        assert self.SUBJECT not in captured[0].reason

    @pytest.mark.parametrize(
        ("token", "kept"),
        [
            ("identity_custody_missing", True),
            ("a" * 48, True),
            ("a" * 49, False),
            ("Custody_Missing", False),
            ("custody missing", False),
            ("synthetic-subject-a", False),
            ("custody/path", False),
            ("", False),
            (5, False),
            (None, False),
        ],
    )
    def test_failure_cause_keeps_only_a_bare_snake_case_class_token(self, token, kept):
        from shared.affordance_pipeline import _consent_failure_cause

        exc_type = type("CheckFailed", (RuntimeError,), {"reason": token})
        cause = _consent_failure_cause(exc_type("message naming synthetic-subject-a"))
        assert cause == (f"CheckFailed:{token}" if kept else "CheckFailed")

    def test_failure_cause_ignores_an_instance_reason(self):
        # An instance attribute is runtime data, not a code-authored token:
        # a subject identifier that happens to be a bare lowercase word must
        # not reach the audit through it.
        from shared.affordance_pipeline import _consent_failure_cause

        exc = RuntimeError("custody failure")
        exc.reason = "alice"
        assert _consent_failure_cause(exc) == "RuntimeError"

    def test_fingerprint_sentinels_for_unconfigured_and_missing_directory(self, tmp_path):
        from shared.affordance_pipeline import _contracts_fingerprint

        assert _contracts_fingerprint(None) == ("unconfigured",)
        assert _contracts_fingerprint(tmp_path / "absent") == ("missing",)

    def test_unconfigured_contracts_dir_is_ttl_bounded_and_rechecked(self, monkeypatch):
        # With no contracts directory to fingerprint, a held registry is
        # bounded by the TTL alone, and every decision still re-runs the check.
        from unittest.mock import MagicMock, patch

        import shared.governance.consent as consent_mod
        from shared import affordance_pipeline as ap_mod

        monkeypatch.setattr(consent_mod, "_CONTRACTS_DIR", None)
        clock = {"now": 1_000_000.0}
        monkeypatch.setattr(ap_mod.time, "time", lambda: clock["now"])
        registry = MagicMock()
        registry.contract_check.return_value = True
        p = ap_mod.AffordancePipeline()
        with patch("shared.governance.consent.load_contracts", return_value=registry) as mock_load:
            assert p._consent_allows(self._candidate()) is True
            assert p._consent_allows(self._candidate()) is True
            assert mock_load.call_count == 1
            clock["now"] += ap_mod._CONSENT_CACHE_TTL_S + 1
            assert p._consent_allows(self._candidate()) is True
            assert mock_load.call_count == 2
            registry.contract_check.return_value = False
            assert p._consent_allows(self._candidate()) is False
        assert registry.contract_check.call_count == 4

    def test_contracts_dir_stat_failure_is_refused(self, tmp_path, monkeypatch):
        # A stat failure other than a missing directory is not "missing": it
        # raises and the gate refuses, even when the loader would grant.
        import pathlib
        from unittest.mock import MagicMock, patch

        from shared.affordance_pipeline import AffordancePipeline

        directory = self._contracts_dir(tmp_path, monkeypatch)
        real_stat = pathlib.Path.stat

        def _stat(path, *a, **k):
            if path == directory:
                raise PermissionError("denied")
            return real_stat(path, *a, **k)

        monkeypatch.setattr(pathlib.Path, "stat", _stat)
        registry = MagicMock()
        registry.contract_check.return_value = True
        with patch("shared.governance.consent.load_contracts", return_value=registry):
            assert AffordancePipeline()._consent_allows(self._candidate()) is False

    def test_registry_ttl_does_not_slide_on_new_requirements(self, monkeypatch):
        # A registry is at most _CONSENT_CACHE_TTL_S old, measured from its
        # load — checking a new requirement must not re-stamp it.
        from unittest.mock import MagicMock, patch

        from shared import affordance_pipeline as ap_mod

        clock = {"now": 1_000_000.0}
        monkeypatch.setattr(ap_mod.time, "time", lambda: clock["now"])
        registry = MagicMock()
        registry.contract_check.return_value = True
        p = ap_mod.AffordancePipeline()
        ttl = ap_mod._CONSENT_CACHE_TTL_S
        with patch("shared.governance.consent.load_contracts", return_value=registry) as mock_load:
            assert p._consent_allows(self._candidate("video")) is True
            clock["now"] += ttl * 0.8
            assert p._consent_allows(self._candidate("audio")) is True
            clock["now"] += ttl * 0.4
            assert p._consent_allows(self._candidate("video")) is True
        assert mock_load.call_count == 2

    def test_select_caller_drops_warm_grant_after_revocation(self, tmp_path, monkeypatch):
        # The actual caller: select() -> _apply_hard_gates -> _consent_allows.
        import json
        from unittest.mock import patch

        from shared.affordance import SelectionCandidate
        from shared.affordance_pipeline import AffordancePipeline

        directory = self._contracts_dir(tmp_path, monkeypatch)
        trace = tmp_path / "dispatch-trace.jsonl"
        monkeypatch.setattr("shared.affordance_pipeline.DISPATCH_TRACE_FILE", trace)
        monkeypatch.delenv("HAPAX_DISPATCH_TRACE", raising=False)
        candidate_payload = {
            "consent_required": True,
            "consent_person_id": self.SUBJECT,
            "consent_data_category": "video",
            "public_capable": False,
            "monetization_risk": "none",
            "content_risk": "tier_0_owned",
        }

        def _fallback(*_a, **_k):
            return [
                SelectionCandidate(
                    capability_name="fallback.capability",
                    similarity=0.9,
                    payload=dict(candidate_payload),
                )
            ]

        imp = Impingement(
            timestamp=time.time(),
            source="dmn",
            type=ImpingementType.STATISTICAL_DEVIATION,
            strength=0.5,
            content={"metric": "x"},
        )
        p = AffordancePipeline()
        with (
            patch.object(p, "_get_embedding", return_value=None),
            patch.object(p, "_fallback_keyword_match", side_effect=_fallback),
        ):
            p.select(imp)
            self._write_contract(directory, revoked=True)
            p.select(imp)
        rows = [json.loads(line) for line in trace.read_text().splitlines() if line.strip()]
        assert rows[-2]["stages"]["after_consent"] == 1
        assert rows[-1]["stages"]["after_consent"] == 0
        assert rows[-1]["dropout_at"] == "consent_filter_empty"

    def test_refusal_audit_is_sanitized_and_names_a_remedy(self, tmp_path, monkeypatch):
        from shared.affordance_pipeline import AffordancePipeline

        self._contracts_dir(tmp_path, monkeypatch)
        captured = self._capture_refusals(monkeypatch)
        assert AffordancePipeline()._consent_allows(self._candidate("audio")) is False
        assert len(captured) == 1
        reason = captured[0].reason
        assert self.SUBJECT not in reason
        assert "no matching active consent contract" in reason
        assert "remedy" in reason

    def test_check_failure_audit_is_sanitized_and_names_a_remedy(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        from shared.affordance_pipeline import AffordancePipeline

        captured = self._capture_refusals(monkeypatch)
        registry = MagicMock()
        registry.contract_check.side_effect = RuntimeError(f"custody for {self.SUBJECT}")
        with patch("shared.governance.consent.load_contracts", return_value=registry):
            assert AffordancePipeline()._consent_allows(self._candidate()) is False
        assert len(captured) == 1
        reason = captured[0].reason
        assert self.SUBJECT not in reason
        assert "RuntimeError" in reason
        assert "remedy" in reason
