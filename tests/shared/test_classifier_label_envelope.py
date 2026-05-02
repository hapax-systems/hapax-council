"""Tests for ``shared.classifier_label_envelope``.

Per cc-task ``archive-and-classifier-label-grounding-normalizer``
(WSJF 9.2). The envelope is the load-bearing predicate every legacy
classifier (scene, chat tier, activity mode, value score, camera
recommendation, circadian alignment, album/track/lyric) consults
before any public/archive/replay/demo/dataset/monetization consumer
can use the raw label.

Coverage maps to the cc-task acceptance criteria:

  - raw labels carry priors with authority ceilings → TestEnvelopeShape
  - public consumers require WCS+public-event+rights+privacy+
    freshness+correction → TestPublicConsumerInvariants
  - failed scene classification cannot publish → TestClassifierFailure
  - chat high_value/research_relevant aggregate-only →
    TestPrivacyGatedKinds
  - camera recommendations route through privacy gates →
    TestPrivacyGatedKinds
  - album/track/lyric require playback witness + rights gate →
    TestRightsGatedKinds
  - negative cases for missing WCS, stale, confidence zero, missing
    rights, missing privacy → distributed across all suites
"""

from __future__ import annotations

import time

from shared.classifier_label_envelope import (
    DEFAULT_FRESHNESS_S,
    MIN_CONFIDENCE_FOR_PRIOR,
    AuthorityCeiling,
    ConsumerKind,
    LabelEnvelope,
    LabelKind,
    PublishVerdict,
    can_publish_label,
)

# ── Module surface ───────────────────────────────────────────────────


class TestModuleSurface:
    def test_label_kind_taxonomy(self) -> None:
        # The 9-kind taxonomy is the cc-task contract.
        assert {k.value for k in LabelKind} == {
            "value_score",
            "scene",
            "chat_tier",
            "activity_mode",
            "camera_recommendation",
            "circadian_alignment",
            "album",
            "track",
            "lyric",
        }

    def test_authority_ceiling_taxonomy(self) -> None:
        # Mirrors PerceptualField + livestream-role taxonomy.
        assert {c.value for c in AuthorityCeiling} == {
            "none",
            "diagnostic",
            "private_triage",
            "aggregate",
            "public_visible",
            "public_live",
        }

    def test_consumer_kind_taxonomy(self) -> None:
        assert {c.value for c in ConsumerKind} == {
            "private",
            "dashboard",
            "public_archive",
            "public_live",
            "demo",
            "dataset",
            "monetization",
        }

    def test_default_thresholds(self) -> None:
        assert DEFAULT_FRESHNESS_S == 30.0
        assert MIN_CONFIDENCE_FOR_PRIOR == 0.30


# ── Envelope shape + effective_ceiling ───────────────────────────────


class TestEnvelopeShape:
    def _scene(self, **overrides) -> LabelEnvelope:
        base = {
            "label_kind": LabelKind.SCENE,
            "raw_value": "studio_desk",
            "confidence": 0.85,
            "declared_ceiling": AuthorityCeiling.PUBLIC_VISIBLE,
            "captured_at_s": time.time(),
        }
        base.update(overrides)
        return LabelEnvelope(**base)

    def test_well_formed_envelope_keeps_declared_ceiling(self) -> None:
        env = self._scene()
        assert env.effective_ceiling is AuthorityCeiling.PUBLIC_VISIBLE

    def test_classifier_failed_downgrades_to_diagnostic(self) -> None:
        env = self._scene(classifier_failed=True, raw_value="")
        assert env.effective_ceiling is AuthorityCeiling.DIAGNOSTIC

    def test_low_confidence_downgrades_to_diagnostic(self) -> None:
        env = self._scene(confidence=0.10)
        assert env.effective_ceiling is AuthorityCeiling.DIAGNOSTIC

    def test_at_min_confidence_keeps_declared_ceiling(self) -> None:
        env = self._scene(confidence=MIN_CONFIDENCE_FOR_PRIOR)
        assert env.effective_ceiling is AuthorityCeiling.PUBLIC_VISIBLE

    def test_envelope_is_frozen(self) -> None:
        env = self._scene()
        try:
            env.raw_value = "other"  # type: ignore[misc]
            failed = False
        except Exception:
            failed = True
        assert failed, "envelope must be frozen"

    def test_is_fresh_within_window(self) -> None:
        now = time.time()
        env = self._scene(captured_at_s=now - 5.0)
        assert env.is_fresh(now_s=now) is True

    def test_is_fresh_outside_window(self) -> None:
        now = time.time()
        env = self._scene(captured_at_s=now - 60.0)
        assert env.is_fresh(now_s=now) is False

    def test_is_fresh_kwarg_freshness(self) -> None:
        now = time.time()
        env = self._scene(captured_at_s=now - 5.0)
        # Tightened to 2s — should now be stale.
        assert env.is_fresh(now_s=now, freshness_s=2.0) is False


# ── Classifier failure path ──────────────────────────────────────────


class TestClassifierFailure:
    def test_failed_scene_only_consumable_by_private(self) -> None:
        env = LabelEnvelope(
            label_kind=LabelKind.SCENE,
            raw_value="",
            confidence=0.0,
            declared_ceiling=AuthorityCeiling.PUBLIC_VISIBLE,
            captured_at_s=time.time(),
            classifier_failed=True,
        )
        for consumer in (
            ConsumerKind.PUBLIC_LIVE,
            ConsumerKind.PUBLIC_ARCHIVE,
            ConsumerKind.DEMO,
            ConsumerKind.DATASET,
            ConsumerKind.MONETIZATION,
            ConsumerKind.DASHBOARD,
        ):
            verdict = can_publish_label(env, consumer=consumer)
            assert verdict.allowed is False, f"failed scene must not publish to {consumer.value}"

    def test_failed_scene_allowed_for_private(self) -> None:
        env = LabelEnvelope(
            label_kind=LabelKind.SCENE,
            raw_value="",
            confidence=0.0,
            declared_ceiling=AuthorityCeiling.PUBLIC_VISIBLE,
            captured_at_s=time.time(),
            classifier_failed=True,
        )
        verdict = can_publish_label(env, consumer=ConsumerKind.PRIVATE)
        assert verdict.allowed is True


# ── Confidence-floor downgrade ───────────────────────────────────────


class TestConfidenceFloor:
    def test_zero_confidence_blocks_dashboard(self) -> None:
        env = LabelEnvelope(
            label_kind=LabelKind.ACTIVITY_MODE,
            raw_value="coding",
            confidence=0.0,
            declared_ceiling=AuthorityCeiling.PUBLIC_VISIBLE,
            captured_at_s=time.time(),
        )
        verdict = can_publish_label(env, consumer=ConsumerKind.DASHBOARD)
        assert verdict.allowed is False
        assert "ceiling=diagnostic" in verdict.reason

    def test_zero_confidence_allowed_for_private(self) -> None:
        env = LabelEnvelope(
            label_kind=LabelKind.ACTIVITY_MODE,
            raw_value="coding",
            confidence=0.0,
            declared_ceiling=AuthorityCeiling.PUBLIC_VISIBLE,
            captured_at_s=time.time(),
        )
        verdict = can_publish_label(env, consumer=ConsumerKind.PRIVATE)
        assert verdict.allowed is True


# ── Public-consumer invariants ───────────────────────────────────────


class TestPublicConsumerInvariants:
    def _live_env(self, **overrides) -> LabelEnvelope:
        base = {
            "label_kind": LabelKind.ACTIVITY_MODE,
            "raw_value": "coding",
            "confidence": 0.85,
            "declared_ceiling": AuthorityCeiling.PUBLIC_LIVE,
            "captured_at_s": time.time(),
            "wcs_evidence_ref": "wcs-1",
            "public_event_ref": "evt-1",
        }
        base.update(overrides)
        return LabelEnvelope(**base)

    def test_public_live_requires_wcs_evidence(self) -> None:
        env = self._live_env(wcs_evidence_ref="")
        verdict = can_publish_label(env, consumer=ConsumerKind.PUBLIC_LIVE)
        assert verdict.allowed is False
        assert "wcs_evidence_ref" in verdict.reason

    def test_public_live_requires_public_event_ref(self) -> None:
        env = self._live_env(public_event_ref="")
        verdict = can_publish_label(env, consumer=ConsumerKind.PUBLIC_LIVE)
        assert verdict.allowed is False
        assert "public_event_ref" in verdict.reason

    def test_public_archive_requires_wcs_evidence(self) -> None:
        env = self._live_env(wcs_evidence_ref="")
        verdict = can_publish_label(env, consumer=ConsumerKind.PUBLIC_ARCHIVE)
        assert verdict.allowed is False

    def test_public_live_allowed_with_full_evidence(self) -> None:
        env = self._live_env()
        verdict = can_publish_label(env, consumer=ConsumerKind.PUBLIC_LIVE)
        assert verdict.allowed is True

    def test_stale_label_blocks_public_live(self) -> None:
        now = time.time()
        env = self._live_env(captured_at_s=now - 60.0)
        verdict = can_publish_label(env, consumer=ConsumerKind.PUBLIC_LIVE, now_s=now)
        assert verdict.allowed is False
        assert "fresh" in verdict.reason

    def test_stale_label_allowed_for_dashboard(self) -> None:
        # Dashboard / dataset consumers may consult stale priors.
        now = time.time()
        env = self._live_env(captured_at_s=now - 60.0)
        verdict = can_publish_label(env, consumer=ConsumerKind.DASHBOARD, now_s=now)
        assert verdict.allowed is True

    def test_demo_consumer_requires_wcs(self) -> None:
        env = self._live_env(wcs_evidence_ref="")
        verdict = can_publish_label(env, consumer=ConsumerKind.DEMO)
        assert verdict.allowed is False

    def test_dataset_consumer_requires_wcs(self) -> None:
        env = self._live_env(
            wcs_evidence_ref="",
            declared_ceiling=AuthorityCeiling.AGGREGATE,
        )
        verdict = can_publish_label(env, consumer=ConsumerKind.DATASET)
        assert verdict.allowed is False

    def test_monetization_consumer_requires_wcs(self) -> None:
        env = self._live_env(wcs_evidence_ref="")
        verdict = can_publish_label(env, consumer=ConsumerKind.MONETIZATION)
        assert verdict.allowed is False


# ── Rights-gated kinds (album/track/lyric) ───────────────────────────


class TestRightsGatedKinds:
    def _track_env(self, **overrides) -> LabelEnvelope:
        base = {
            "label_kind": LabelKind.TRACK,
            "raw_value": "Song Name",
            "confidence": 0.85,
            "declared_ceiling": AuthorityCeiling.PUBLIC_LIVE,
            "captured_at_s": time.time(),
            "wcs_evidence_ref": "wcs-1",
            "public_event_ref": "evt-1",
        }
        base.update(overrides)
        return LabelEnvelope(**base)

    def test_track_without_rights_clear_blocks_public(self) -> None:
        env = self._track_env(rights_clear=False)
        verdict = can_publish_label(env, consumer=ConsumerKind.PUBLIC_LIVE)
        assert verdict.allowed is False
        assert "rights_clear" in verdict.reason

    def test_track_with_rights_clear_publishes(self) -> None:
        env = self._track_env(rights_clear=True)
        verdict = can_publish_label(env, consumer=ConsumerKind.PUBLIC_LIVE)
        assert verdict.allowed is True

    def test_album_without_rights_blocks_demo(self) -> None:
        env = self._track_env(label_kind=LabelKind.ALBUM, rights_clear=False)
        verdict = can_publish_label(env, consumer=ConsumerKind.DEMO)
        assert verdict.allowed is False

    def test_lyric_without_rights_blocks_archive(self) -> None:
        env = self._track_env(label_kind=LabelKind.LYRIC, rights_clear=False)
        verdict = can_publish_label(env, consumer=ConsumerKind.PUBLIC_ARCHIVE)
        assert verdict.allowed is False

    def test_track_without_rights_allowed_private(self) -> None:
        env = self._track_env(rights_clear=False)
        verdict = can_publish_label(env, consumer=ConsumerKind.PRIVATE)
        assert verdict.allowed is True


# ── Privacy-gated kinds (chat tier / camera / scene) ─────────────────


class TestPrivacyGatedKinds:
    def _chat_env(self, **overrides) -> LabelEnvelope:
        base = {
            "label_kind": LabelKind.CHAT_TIER,
            "raw_value": "high_value",
            "confidence": 0.85,
            "declared_ceiling": AuthorityCeiling.AGGREGATE,
            "captured_at_s": time.time(),
            "wcs_evidence_ref": "wcs-1",
        }
        base.update(overrides)
        return LabelEnvelope(**base)

    def test_chat_tier_without_privacy_clear_blocks_dataset(self) -> None:
        env = self._chat_env(privacy_clear=False)
        verdict = can_publish_label(env, consumer=ConsumerKind.DATASET)
        assert verdict.allowed is False
        assert "privacy_clear" in verdict.reason

    def test_chat_tier_with_privacy_clear_publishes_dataset(self) -> None:
        env = self._chat_env(privacy_clear=True)
        verdict = can_publish_label(env, consumer=ConsumerKind.DATASET)
        assert verdict.allowed is True

    def test_camera_recommendation_privacy_gated(self) -> None:
        env = self._chat_env(
            label_kind=LabelKind.CAMERA_RECOMMENDATION,
            raw_value="follow_face",
            declared_ceiling=AuthorityCeiling.PUBLIC_LIVE,
            public_event_ref="evt-1",
            privacy_clear=False,
        )
        verdict = can_publish_label(env, consumer=ConsumerKind.PUBLIC_LIVE)
        assert verdict.allowed is False
        assert "privacy_clear" in verdict.reason

    def test_scene_privacy_gated(self) -> None:
        # Scenes often capture environment with people; require
        # privacy_clear before any public consumer.
        env = self._chat_env(
            label_kind=LabelKind.SCENE,
            raw_value="studio_with_guest",
            declared_ceiling=AuthorityCeiling.PUBLIC_VISIBLE,
            privacy_clear=False,
        )
        verdict = can_publish_label(env, consumer=ConsumerKind.DEMO)
        assert verdict.allowed is False

    def test_chat_tier_high_value_only_aggregate_or_above(self) -> None:
        # Pin the cc-task acceptance: chat high_value/research_relevant
        # are aggregate-only; cannot reach PUBLIC_LIVE without
        # explicit upgrade.
        env = self._chat_env(
            raw_value="high_value",
            declared_ceiling=AuthorityCeiling.AGGREGATE,
            privacy_clear=True,
            public_event_ref="evt-1",
        )
        verdict = can_publish_label(env, consumer=ConsumerKind.PUBLIC_LIVE)
        assert verdict.allowed is False
        assert "below public_live" in verdict.reason


# ── Verdict structure ────────────────────────────────────────────────


class TestVerdictStructure:
    def test_verdict_carries_reason_on_allow(self) -> None:
        env = LabelEnvelope(
            label_kind=LabelKind.ACTIVITY_MODE,
            raw_value="coding",
            confidence=0.85,
            declared_ceiling=AuthorityCeiling.PRIVATE_TRIAGE,
            captured_at_s=time.time(),
        )
        verdict = can_publish_label(env, consumer=ConsumerKind.DASHBOARD)
        assert isinstance(verdict, PublishVerdict)
        assert verdict.allowed is True
        assert verdict.reason

    def test_verdict_carries_reason_on_refuse(self) -> None:
        env = LabelEnvelope(
            label_kind=LabelKind.TRACK,
            raw_value="Song",
            confidence=0.85,
            declared_ceiling=AuthorityCeiling.PUBLIC_LIVE,
            captured_at_s=time.time(),
            wcs_evidence_ref="wcs-1",
            public_event_ref="evt-1",
            rights_clear=False,
        )
        verdict = can_publish_label(env, consumer=ConsumerKind.PUBLIC_LIVE)
        assert verdict.allowed is False
        assert "rights_clear" in verdict.reason
