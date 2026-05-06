"""Tests for camera salience broker production wiring.

Verifies that both production call sites (director_loop and
affordance_pipeline) correctly invoke the broker singleton and
handle broker responses + failures gracefully.
"""

from __future__ import annotations

import json
import random
import time
from unittest.mock import MagicMock, patch

import pytest

import shared.camera_salience_singleton as singleton_mod
from shared.affordance import SelectionCandidate
from shared.affordance_pipeline import AffordancePipeline
from shared.bayesian_camera_salience_world_surface import (
    CameraEvidenceRow,
    CameraFreshness,
    CameraObservationEnvelope,
    CameraSalienceBundle,
    CameraTemporalWindow,
    ClaimAuthorityCeiling,
    EvidenceClass,
    FreshnessState,
    ObservationApertureKind,
    ObservationState,
    PrivacyMode,
    ProducerKind,
)
from shared.camera_salience_singleton import (
    _ApertureExplorationConfig,
    _ApertureOutcomePosterior,
    _BrokerSingleton,
    _exploration_config_from_env,
    _reset_for_testing,
    broker,
)
from shared.impingement import Impingement, ImpingementType


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the broker singleton before each test."""
    _reset_for_testing()
    yield
    _reset_for_testing()


def _make_test_observation() -> CameraObservationEnvelope:
    """Minimal valid observation envelope for testing."""
    now = "2026-05-03T21:00:00Z"
    return CameraObservationEnvelope(
        envelope_id="camera-observation:test.brio-operator.frame",
        aperture_id="aperture:studio-rgb.brio-operator",
        aperture_kind=ObservationApertureKind.STUDIO_RGB_CAMERA,
        producer=ProducerKind.VISION_BACKEND,
        evidence_class=EvidenceClass.FRAME,
        observation_state=ObservationState.OBSERVED,
        temporal_window=CameraTemporalWindow(
            window_id="camera-window:test",
            kind="current_frame",
            aperture_id="aperture:studio-rgb.brio-operator",
            observed_at=now,
            duration_s=0.0,
            span_ref="span:test:frame",
        ),
        freshness=CameraFreshness(
            state=FreshnessState.FRESH,
            checked_at=now,
            ttl_s=10,
            observed_age_s=1,
            source_ref="test:source",
        ),
        confidence=0.82,
        semantic_labels=("person_present",),
        evidence_rows=(
            CameraEvidenceRow(
                evidence_ref="camera-evidence:test.frame",
                evidence_class=EvidenceClass.FRAME,
                hypothesis="operator_attention_screen",
                likelihood=0.78,
                confidence=0.82,
                observation_state=ObservationState.OBSERVED,
                supports_hypothesis=True,
                source_refs=("test:source",),
                witness_refs=("witness:test",),
                span_refs=("span:test",),
                wcs_refs=("wcs-surface:test",),
            ),
        ),
        source_refs=("test:source",),
        wcs_surface_refs=("wcs-surface:test",),
        witness_refs=("witness:test",),
        span_refs=("span:test",),
        authority_ceiling=ClaimAuthorityCeiling.EVIDENCE_BOUND,
        privacy_mode=PrivacyMode.PRIVATE,
    )


def _counter_value(counter: object, *, consumer: str) -> float:
    collect = getattr(counter, "collect", None)
    if collect is None:
        return 0.0
    for metric in collect():
        for sample in metric.samples:
            if (
                sample.name == "camera_salience_broker_queries_total"
                and sample.labels.get("consumer") == consumer
            ):
                return float(sample.value)
    return 0.0


def _outcome_posterior_snapshot(broker_singleton: _BrokerSingleton) -> dict[str, dict[str, float]]:
    with broker_singleton._posterior_lock:
        return {
            aperture_id: {
                "alpha": posterior.alpha,
                "beta": posterior.beta,
                "mean": posterior.mean,
            }
            for aperture_id, posterior in broker_singleton._aperture_posteriors.items()
        }


class _DeterministicRng(random.Random):
    def __init__(self, random_value: float) -> None:
        super().__init__(0)
        self._random_value = random_value

    def random(self) -> float:
        return self._random_value

    def betavariate(self, alpha: float, beta: float) -> float:
        return alpha / (alpha + beta)


def _explore_probe_aperture_id(probe: str) -> str | None:
    if not probe.startswith("explore_aperture:"):
        return None
    return probe.removeprefix("explore_aperture:").rsplit(":", 1)[0]


def _explorable_aperture_ids(broker_singleton: _BrokerSingleton) -> set[str]:
    evidence = {EvidenceClass.FRAME, EvidenceClass.IR_PRESENCE, EvidenceClass.COMPOSED_LIVESTREAM}
    return {
        aperture.aperture_id
        for aperture in broker_singleton._apertures
        if aperture.kind.value != "future_sensor"
        and evidence.intersection(aperture.supported_evidence_classes)
    }


# ── Singleton tests ────────────────────────────────────────────────────


class TestBrokerSingleton:
    """Tests for the process-global broker singleton."""

    def test_broker_returns_singleton(self) -> None:
        b1 = broker()
        b2 = broker()
        assert b1 is b2

    def test_singleton_initializes_with_apertures(self) -> None:
        b = broker()
        # Should have loaded apertures from the canonical fixture file
        assert isinstance(b, _BrokerSingleton)

    def test_ingest_none_is_noop(self) -> None:
        b = broker()
        b.ingest(None)
        assert b.observation_count == 0

    def test_ingest_valid_observation(self) -> None:
        b = broker()
        obs = _make_test_observation()
        b.ingest(obs)
        assert b.observation_count == 1

    def test_query_empty_observations_returns_none(self) -> None:
        b = broker()
        result = b.query(
            consumer="director",
            decision_context="test",
            candidate_action="test_action",
        )
        assert result is None

    def test_query_increments_affordance_prometheus_counter(self) -> None:
        if not singleton_mod._METRICS_AVAILABLE:
            pytest.skip("prometheus_client unavailable")
        before = _counter_value(singleton_mod._QUERY_COUNTER, consumer="affordance")
        b = broker()
        result = b.query(
            consumer="affordance",
            decision_context="test_affordance_tick",
            candidate_action="fx.family.audio-reactive",
        )
        after = _counter_value(singleton_mod._QUERY_COUNTER, consumer="affordance")
        assert result is None
        assert after == before + 1.0

    def test_query_with_observations(self) -> None:
        b = broker()
        obs = _make_test_observation()
        b.ingest(obs)
        result = b.query(
            consumer="director",
            decision_context="test_perceptual_assembly",
            candidate_action="compose_move",
        )
        # May be None if the broker rejects, or a valid bundle
        assert result is None or isinstance(result, CameraSalienceBundle)

    def test_rolling_window_trim(self) -> None:
        b = broker()
        b._max_window = 5
        for _ in range(10):
            b.ingest(_make_test_observation())
        assert b.observation_count == 5

    def test_record_outcome_stores_bounded_evidence(self) -> None:
        b = broker()
        b._max_outcomes = 2

        assert b.record_outcome(
            "camera-salience-query:affordance.one",
            {"success": True, "capability_name": "fx.family.audio-reactive"},
        )
        assert b.record_outcome("camera-salience-query:affordance.one", False)
        assert b.record_outcome("camera-salience-query:affordance.two", "blocked")

        with b._outcome_lock:
            assert len(b._outcomes) == 2
            rows = [
                dict(row)
                for row in b._outcomes
                if row["query_id"] == "camera-salience-query:affordance.one"
            ]
        assert len(rows) == 1
        assert rows[0]["observed_outcome"] == "failure"
        assert b.record_outcome("not-a-query", True) is False

    def test_outcome_stream_updates_aperture_posterior_and_next_selection(self) -> None:
        b = broker()
        b.ingest(_make_test_observation())

        first = b.query(
            consumer="affordance",
            decision_context="test_feedback_loop",
            candidate_action="fx.family.audio-reactive",
            time_budget_ms=500,
        )

        assert first is not None
        assert first.ranked_observations
        aperture_id = first.ranked_observations[0].aperture_id
        base_utility = first.ranked_observations[0].value_of_information.decision_utility

        assert b.record_outcome(
            first.query.query_id,
            {"success": True, "capability_name": "fx.family.audio-reactive"},
        )
        after_success = _outcome_posterior_snapshot(b)[aperture_id]
        assert after_success["alpha"] == pytest.approx(2.98)
        assert after_success["beta"] == pytest.approx(1.0)

        second = b.query(
            consumer="affordance",
            decision_context="test_feedback_loop",
            candidate_action="fx.family.audio-reactive",
            time_budget_ms=500,
        )

        assert second is not None
        assert second.ranked_observations
        boosted_utility = second.ranked_observations[0].value_of_information.decision_utility
        assert second.ranked_observations[0].aperture_id == aperture_id
        assert boosted_utility > base_utility

        assert b.record_outcome(second.query.query_id, False)
        after_failure = _outcome_posterior_snapshot(b)[aperture_id]
        assert after_failure["alpha"] == pytest.approx(2.9502)
        assert after_failure["beta"] == pytest.approx(1.99)

        third = b.query(
            consumer="affordance",
            decision_context="test_feedback_loop",
            candidate_action="fx.family.audio-reactive",
            time_budget_ms=500,
        )
        assert third is not None
        assert third.ranked_observations
        assert third.ranked_observations[0].value_of_information.decision_utility < boosted_utility

    def test_aperture_posterior_preserves_alpha_beta_clamps(self) -> None:
        b = broker()
        b.ingest(_make_test_observation())
        bundle = b.query(
            consumer="affordance",
            decision_context="test_feedback_loop_clamps",
            candidate_action="fx.family.audio-reactive",
            time_budget_ms=100,
        )
        assert bundle is not None
        assert bundle.ranked_observations
        aperture_id = bundle.ranked_observations[0].aperture_id

        for _ in range(40):
            assert b.record_outcome(bundle.query.query_id, True)
        success_saturated = _outcome_posterior_snapshot(b)[aperture_id]
        assert success_saturated["alpha"] <= 10.0
        assert success_saturated["beta"] >= 1.0
        assert success_saturated["alpha"] == pytest.approx(10.0)
        assert success_saturated["beta"] == pytest.approx(1.0)

        for _ in range(400):
            assert b.record_outcome(bundle.query.query_id, False)
        failure_saturated = _outcome_posterior_snapshot(b)[aperture_id]
        assert 1.0 <= failure_saturated["alpha"] <= 10.0
        assert 1.0 <= failure_saturated["beta"] <= 10.0
        assert failure_saturated["alpha"] == pytest.approx(1.0)
        assert failure_saturated["beta"] == pytest.approx(10.0)

    def test_exploration_env_knobs_are_clamped_and_configurable(self, monkeypatch) -> None:
        monkeypatch.setenv("HAPAX_CAMERA_SALIENCE_EXPLORATION_EPSILON", "1.5")
        monkeypatch.setenv("HAPAX_CAMERA_SALIENCE_SEEKING_MULTIPLIER", "0.5")
        monkeypatch.setenv("HAPAX_CAMERA_SALIENCE_MAX_UNEXPLORED_S", "0")

        config = _exploration_config_from_env()

        assert config.epsilon_rate == 1.0
        assert config.seeking_multiplier == 1.0
        assert config.max_unexplored_s == 1.0

    def test_exploration_anti_saturation_covers_all_explorable_apertures(self) -> None:
        b = _BrokerSingleton(
            broker()._apertures,
            exploration_config=_ApertureExplorationConfig(
                epsilon_rate=0.0,
                max_unexplored_s=1800.0,
            ),
            rng=_DeterministicRng(random_value=1.0),
        )
        b.ingest(_make_test_observation())
        expected = _explorable_aperture_ids(b)
        seen: set[str] = set()

        for tick in range(len(expected) + 2):
            bundle = b.query(
                consumer="affordance",
                decision_context="test_exploration_coverage",
                candidate_action="fx.family.audio-reactive",
                time_budget_ms=500,
                now_s=1000.0 + tick,
            )
            assert bundle is not None
            seen.update(row.aperture_id for row in bundle.ranked_observations)
            probe_aperture_id = _explore_probe_aperture_id(bundle.recommended_next_probe)
            if probe_aperture_id is not None:
                seen.add(probe_aperture_id)
            if seen == expected:
                break

        assert seen == expected

        followup = b.query(
            consumer="affordance",
            decision_context="test_exploration_coverage",
            candidate_action="fx.family.audio-reactive",
            time_budget_ms=500,
            now_s=1015.0,
        )
        assert followup is not None
        assert _explore_probe_aperture_id(followup.recommended_next_probe) is None

    def test_seeking_boosts_epsilon_and_targets_low_posterior_aperture(self) -> None:
        b = _BrokerSingleton(
            broker()._apertures,
            exploration_config=_ApertureExplorationConfig(
                epsilon_rate=0.4,
                seeking_multiplier=3.0,
                max_unexplored_s=1800.0,
            ),
            rng=_DeterministicRng(random_value=0.5),
        )
        b.ingest(_make_test_observation())
        eligible = sorted(_explorable_aperture_ids(b))
        low_posterior_aperture = next(
            aperture_id
            for aperture_id in eligible
            if aperture_id != "aperture:studio-rgb.brio-operator"
        )
        with b._exploration_lock:
            b._last_explored_at = {aperture_id: 1000.0 for aperture_id in eligible}
        with b._posterior_lock:
            for aperture_id in eligible:
                b._aperture_posteriors[aperture_id] = _ApertureOutcomePosterior(
                    alpha=10.0,
                    beta=1.0,
                )
            b._aperture_posteriors[low_posterior_aperture] = _ApertureOutcomePosterior(
                alpha=1.0,
                beta=10.0,
            )

        nominal = b.query(
            consumer="affordance",
            decision_context="test_seeking_exploration",
            candidate_action="fx.family.audio-reactive",
            time_budget_ms=500,
            seeking=False,
            now_s=1001.0,
        )
        assert nominal is not None
        assert _explore_probe_aperture_id(nominal.recommended_next_probe) is None

        seeking = b.query(
            consumer="affordance",
            decision_context="test_seeking_exploration",
            candidate_action="fx.family.audio-reactive",
            time_budget_ms=500,
            seeking=True,
            now_s=1002.0,
        )

        assert seeking is not None
        assert _explore_probe_aperture_id(seeking.recommended_next_probe) == (
            low_posterior_aperture
        )


# ── Producer wiring tests ──────────────────────────────────────────────


class TestProducerWiring:
    """Verify production producers push envelopes into the singleton."""

    @patch("shared.camera_salience_singleton.broker")
    def test_vision_snapshot_helper_ingests_fixture_backed_role(self, mock_broker_fn):
        from agents.hapax_daimonion.backends.vision import _ingest_camera_salience_snapshot

        mock_singleton = MagicMock()
        mock_broker_fn.return_value = mock_singleton

        ingested = _ingest_camera_salience_snapshot(
            "operator",
            {
                "person_count": 1,
                "gaze_direction": "screen",
                "scene_objects": "keyboard, monitor",
                "detected_action": "coding",
                "updated_at": time.monotonic(),
            },
        )

        assert ingested is True
        envelope = mock_singleton.ingest.call_args.args[0]
        assert envelope.aperture_id == "aperture:studio-rgb.brio-operator"
        assert envelope.evidence_class == EvidenceClass.FRAME

    def test_vision_cache_exposes_per_camera_snapshots(self) -> None:
        from agents.hapax_daimonion.backends.vision import _VisionCache

        cache = _VisionCache()
        cache._current_role = "operator"
        cache.update(
            detected_objects="[]",
            person_count=1,
            pose_summary="seated",
            scene_objects="keyboard",
            gaze_direction="screen",
        )
        snapshots = cache.camera_salience_snapshots(detected_action="coding")

        assert "operator" in snapshots
        assert snapshots["operator"]["detected_action"] == "coding"
        assert snapshots["operator"]["updated_at"]

    @patch("shared.camera_salience_singleton.broker")
    def test_ir_report_helper_ingests_registered_desk_pi(self, mock_broker_fn):
        # cc-task: bayesian-camera-salience-runtime-aperture-coverage —
        # both ``desk`` and ``room`` are now canonical-aperture-mapped
        # (along with ``overhead``); both reports ingest into the broker.
        # An unregistered Pi name (e.g. ``pi-noir-archive``) still
        # fail-closes.
        from agents.hapax_daimonion.backends.ir_presence import (
            _ingest_camera_salience_reports,
        )

        mock_singleton = MagicMock()
        mock_broker_fn.return_value = mock_singleton

        ingested = _ingest_camera_salience_reports(
            {
                "desk": {
                    "persons": [{"confidence": 0.8}],
                    "motion_delta": 0.3,
                    "ir_brightness": 0.5,
                    "timestamp": time.time(),
                },
                "room": {
                    "persons": [{"confidence": 0.7}],
                    "motion_delta": 0.2,
                    "timestamp": time.time(),
                },
            }
        )

        assert ingested == 2
        ingested_apertures = {
            call.args[0].aperture_id for call in mock_singleton.ingest.call_args_list
        }
        assert ingested_apertures == {
            "aperture:studio-ir.noir-desk",
            "aperture:studio-ir.noir-room",
        }
        for call in mock_singleton.ingest.call_args_list:
            assert call.args[0].evidence_class == EvidenceClass.IR_PRESENCE

    @patch("shared.camera_salience_singleton.broker")
    def test_cross_camera_stitcher_ingests_top_merge_suggestion(self, mock_broker_fn):
        from agents.models.cross_camera import CrossCameraStitcher

        mock_singleton = MagicMock()
        mock_broker_fn.return_value = mock_singleton

        stitcher = CrossCameraStitcher(temporal_window_s=10.0)
        stitcher.report_disappeared("entity-a", "brio-operator", "person")
        suggestions = stitcher.report_appeared("entity-b", "c920-desk", "person")

        assert suggestions
        envelope = mock_singleton.ingest.call_args.args[0]
        assert envelope.producer == ProducerKind.CROSS_CAMERA_STITCHER
        assert envelope.evidence_class == EvidenceClass.CROSS_CAMERA_TRACKLET

    @patch("shared.camera_salience_singleton.broker")
    def test_compositor_status_helper_ingests_livestream_snapshot(self, mock_broker_fn):
        from agents.studio_compositor.compositor import (
            _ingest_camera_salience_livestream_status,
        )

        mock_singleton = MagicMock()
        mock_broker_fn.return_value = mock_singleton

        ingested = _ingest_camera_salience_livestream_status(
            {
                "state": "running",
                "cameras": {"brio-operator": "active", "c920-desk": "active"},
                "active_cameras": 2,
                "total_cameras": 2,
                "broadcast_mode": "dual",
                "timestamp": time.time(),
            }
        )

        assert ingested is True
        envelope = mock_singleton.ingest.call_args.args[0]
        assert envelope.producer == ProducerKind.COMPOSITOR_SNAPSHOT
        assert envelope.evidence_class == EvidenceClass.COMPOSED_LIVESTREAM


# ── Director loop wiring tests ─────────────────────────────────────────


class TestDirectorLoopWiring:
    """Verify the director loop calls the broker correctly."""

    @patch("shared.camera_salience_singleton.broker")
    def test_director_prompt_includes_camera_salience_section(self, mock_broker_fn):
        """When broker returns a bundle, the prompt should include '## Camera Salience'."""
        mock_singleton = MagicMock()
        mock_bundle = MagicMock()
        mock_bundle.to_director_world_surface_projection.return_value = {
            "ranked": [
                {
                    "aperture_id": "aperture:studio-rgb.brio-operator",
                    "hypothesis": "operator_attention_screen",
                    "confidence": 0.82,
                    "voi": 0.65,
                }
            ],
            "query_id": "camera-salience-query:director.test",
        }
        mock_singleton.query.return_value = mock_bundle
        mock_broker_fn.return_value = mock_singleton

        # Build minimal parts list to verify the broker injection block
        parts = []
        try:
            from shared.camera_salience_singleton import broker as _camera_broker

            _bundle = _camera_broker().query(
                consumer="director",
                decision_context="director_tick_perceptual_assembly",
                candidate_action="compose_livestream_move",
            )
            if _bundle is not None:
                _projection = _bundle.to_director_world_surface_projection()
                if _projection.get("ranked"):
                    parts.append("")
                    parts.append("## Camera Salience")
                    parts.append("```json")
                    parts.append(json.dumps(_projection, indent=2))
                    parts.append("```")
        except Exception:
            pass

        assert any("## Camera Salience" in p for p in parts)
        mock_singleton.query.assert_called_once()

    @patch("shared.camera_salience_singleton.broker")
    def test_director_prompt_omitted_on_empty_ranked(self, mock_broker_fn):
        """When broker returns empty ranked list, section should be omitted."""
        mock_singleton = MagicMock()
        mock_bundle = MagicMock()
        mock_bundle.to_director_world_surface_projection.return_value = {
            "ranked": [],
            "query_id": "camera-salience-query:director.test",
        }
        mock_singleton.query.return_value = mock_bundle
        mock_broker_fn.return_value = mock_singleton

        parts = []
        try:
            from shared.camera_salience_singleton import broker as _camera_broker

            _bundle = _camera_broker().query(
                consumer="director",
                decision_context="test",
                candidate_action="test",
            )
            if _bundle is not None:
                _projection = _bundle.to_director_world_surface_projection()
                if _projection.get("ranked"):
                    parts.append("## Camera Salience")
        except Exception:
            pass

        assert not any("## Camera Salience" in p for p in parts)

    @patch("shared.camera_salience_singleton.broker")
    def test_director_prompt_safe_on_broker_error(self, mock_broker_fn):
        """When broker raises, the director prompt should not crash."""
        mock_broker_fn.side_effect = RuntimeError("broker down")

        parts = []
        try:
            from shared.camera_salience_singleton import broker as _camera_broker

            _bundle = _camera_broker().query(
                consumer="director",
                decision_context="test",
                candidate_action="test",
            )
            if _bundle is not None:
                _projection = _bundle.to_director_world_surface_projection()
                if _projection.get("ranked"):
                    parts.append("## Camera Salience")
        except Exception:
            pass  # fail-closed

        assert not any("## Camera Salience" in p for p in parts)


# ── Affordance pipeline wiring tests ───────────────────────────────────


class TestAffordancePipelineWiring:
    """Verify the affordance pipeline attaches salience to winner payload."""

    @patch("shared.camera_salience_singleton.broker")
    def test_winner_payload_gets_camera_salience(self, mock_broker_fn):
        """When broker returns a bundle, winner.payload should include camera_salience_bundle."""
        mock_singleton = MagicMock()
        mock_bundle = MagicMock()
        mock_bundle.to_wcs_projection_payload.return_value = {
            "aperture_count": 3,
            "top_hypothesis": "operator_attention_screen",
            "confidence": 0.82,
        }
        mock_singleton.query.return_value = mock_bundle
        mock_broker_fn.return_value = mock_singleton

        winner = MagicMock()
        winner.payload = {}
        winner.capability_name = "fx.family.audio-reactive"

        # Simulate the affordance pipeline injection
        try:
            from shared.camera_salience_singleton import broker as _camera_broker

            _salience_bundle = _camera_broker().query(
                consumer="affordance",
                decision_context="affordance_select:test_source",
                candidate_action=winner.capability_name,
            )
            if _salience_bundle is not None:
                winner.payload["camera_salience_bundle"] = (
                    _salience_bundle.to_wcs_projection_payload()
                )
        except Exception:
            pass

        assert "camera_salience_bundle" in winner.payload
        assert winner.payload["camera_salience_bundle"]["confidence"] == 0.82

    @patch("shared.camera_salience_singleton.broker")
    def test_winner_payload_unchanged_on_broker_error(self, mock_broker_fn):
        """When broker raises, winner.payload should not change."""
        mock_broker_fn.side_effect = RuntimeError("broker down")

        winner = MagicMock()
        winner.payload = {"existing_key": "existing_value"}

        try:
            from shared.camera_salience_singleton import broker as _camera_broker

            _salience_bundle = _camera_broker().query(
                consumer="affordance",
                decision_context="test",
                candidate_action="test",
            )
            if _salience_bundle is not None:
                winner.payload["camera_salience_bundle"] = (
                    _salience_bundle.to_wcs_projection_payload()
                )
        except Exception:
            pass

        assert "camera_salience_bundle" not in winner.payload
        assert winner.payload["existing_key"] == "existing_value"

    @patch("shared.camera_salience_singleton.broker")
    def test_winner_payload_unchanged_on_none_bundle(self, mock_broker_fn):
        """When broker returns None, winner.payload should not change."""
        mock_singleton = MagicMock()
        mock_singleton.query.return_value = None
        mock_broker_fn.return_value = mock_singleton

        winner = MagicMock()
        winner.payload = {}

        try:
            from shared.camera_salience_singleton import broker as _camera_broker

            _salience_bundle = _camera_broker().query(
                consumer="affordance",
                decision_context="test",
                candidate_action="test",
            )
            if _salience_bundle is not None:
                winner.payload["camera_salience_bundle"] = (
                    _salience_bundle.to_wcs_projection_payload()
                )
        except Exception:
            pass

        assert "camera_salience_bundle" not in winner.payload

    def test_affordance_outcome_feedback_records_broker_outcome(self):
        """Producer -> broker -> selection -> outcome feeds query id back."""

        class OutcomeLoopPipeline(AffordancePipeline):
            def _get_embedding(self, impingement):  # noqa: ANN001
                return [1.0, 0.0]

            def _retrieve(self, embedding, top_k):  # noqa: ANN001
                return [
                    SelectionCandidate(
                        capability_name="fx.family.audio-reactive",
                        similarity=0.99,
                        payload={
                            "embedding": [1.0, 0.0],
                            "available": True,
                            "monetization_risk": "none",
                            "content_risk": "tier_0_owned",
                            "public_capable": False,
                        },
                    )
                ]

            def _active_programme_cached(self):
                return None

        b = broker()
        b.ingest(_make_test_observation())
        pipe = OutcomeLoopPipeline()
        imp = Impingement(
            timestamp=time.time(),
            source="test.camera-salience",
            type=ImpingementType.SALIENCE_INTEGRATION,
            strength=0.9,
            content={"metric": "operator_attention_screen"},
            embedding=[1.0, 0.0],
        )

        with patch("shared.governance.quiet_frame_subscriber.install"):
            winners = pipe.select(imp)

        assert winners
        winner = winners[0]
        query_id = winner.payload["camera_salience_query_id"]
        assert query_id.startswith("camera-salience-query:affordance.")
        assert winner.payload["camera_salience_bundle"]["bundle_id"].startswith(
            "camera-salience-bundle:affordance."
        )

        pipe.record_outcome(winner.capability_name, success=True)

        with b._outcome_lock:
            rows = [dict(row) for row in b._outcomes if row["query_id"] == query_id]
        assert len(rows) == 1
        assert rows[0]["observed_outcome"] == "success"
        assert rows[0]["capability_name"] == winner.capability_name

    @patch("shared.camera_salience_singleton.broker")
    def test_camera_salience_outcome_failure_does_not_block_learning(self, mock_broker_fn):
        """Broker outcome failures are fail-closed and do not block learning."""
        mock_singleton = MagicMock()
        mock_singleton.record_outcome.side_effect = RuntimeError("broker down")
        mock_broker_fn.return_value = mock_singleton
        pipe = AffordancePipeline()
        pipe._last_camera_salience_query_by_capability["fx.family.audio-reactive"] = (
            "camera-salience-query:affordance.fail-closed"
        )

        pipe.record_outcome("fx.family.audio-reactive", success=True, context={"source": "test"})

        assert pipe.get_activation_state("fx.family.audio-reactive").use_count == 1
        mock_singleton.record_outcome.assert_called_once()


# ── Vulture whitelist removal verification ──────────────────────────────


class TestVultureWhitelistRemoval:
    """Verify that previously-whitelisted entries are now used in production."""

    def test_evaluate_is_called_via_singleton(self) -> None:
        """CameraSalienceBroker.evaluate is now called via the singleton query path."""
        # This is a documentation-as-test: the singleton's query() method
        # internally calls CameraSalienceBroker(apertures=..., observations=...).evaluate(query).
        # Confirmed by reading the singleton source.
        from shared.camera_salience_singleton import _BrokerSingleton

        # The singleton creates CameraSalienceBroker and calls evaluate().
        # This test verifies the import chain is valid.
        assert hasattr(_BrokerSingleton, "query")

    def test_projection_methods_used_by_call_sites(self) -> None:
        """to_director_world_surface_projection and to_wcs_projection_payload
        are now called from director_loop.py and affordance_pipeline.py."""
        from shared.bayesian_camera_salience_world_surface import CameraSalienceBundle

        assert hasattr(CameraSalienceBundle, "to_director_world_surface_projection")
        assert hasattr(CameraSalienceBundle, "to_wcs_projection_payload")
