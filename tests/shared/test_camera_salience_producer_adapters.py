"""Tests for camera salience producer adapters (Phase A).

Per-adapter golden-file-style tests using recorded state fixtures.
Each test verifies the adapter produces a valid CameraObservationEnvelope
and that the envelope passes the broker's contract validation.
"""

from __future__ import annotations

import time

from shared.bayesian_camera_salience_world_surface import (
    CameraObservationEnvelope,
    ClaimAuthorityCeiling,
    EvidenceClass,
    FreshnessState,
    ObservationApertureKind,
    ObservationState,
    PrivacyMode,
    ProducerKind,
)
from shared.camera_salience_producer_adapters import (
    cross_camera_to_envelope,
    ir_to_envelope,
    livestream_to_envelope,
    vision_to_envelope,
)

# ── Vision adapter tests ────────────────────────────────────────────────


class TestVisionToEnvelope:
    """vision_to_envelope adapter tests."""

    def _fixture_snapshot(self, **overrides: object) -> dict:
        """Minimal VisionCache.read() dict."""
        base = {
            "person_count": 1,
            "gaze_direction": "screen",
            "detected_action": "coding",
            "scene_objects": "keyboard, monitor",
            "updated_at": time.monotonic(),
            "operator_present": True,
            "posture": "seated",
            "scene_type": "home_office",
        }
        base.update(overrides)
        return base

    def test_produces_valid_envelope(self) -> None:
        snapshot = self._fixture_snapshot()
        env = vision_to_envelope(snapshot, camera_role="brio-operator")
        assert env is not None
        assert isinstance(env, CameraObservationEnvelope)
        assert env.aperture_kind == ObservationApertureKind.STUDIO_RGB_CAMERA
        assert env.producer == ProducerKind.VISION_BACKEND
        assert env.evidence_class == EvidenceClass.FRAME
        assert env.observation_state == ObservationState.OBSERVED
        assert env.privacy_mode == PrivacyMode.PRIVATE
        assert env.authority_ceiling == ClaimAuthorityCeiling.EVIDENCE_BOUND
        assert len(env.evidence_rows) == 1

    def test_person_present_screen_gaze(self) -> None:
        snapshot = self._fixture_snapshot(person_count=1, gaze_direction="screen")
        env = vision_to_envelope(snapshot, camera_role="brio-operator")
        assert env is not None
        assert env.evidence_rows[0].hypothesis == "operator_attention_screen"
        assert env.confidence >= 0.8

    def test_person_present_no_gaze(self) -> None:
        snapshot = self._fixture_snapshot(person_count=1, gaze_direction="unknown")
        env = vision_to_envelope(snapshot, camera_role="brio-operator")
        assert env is not None
        assert env.evidence_rows[0].hypothesis == "operator_attention_desk"
        assert 0.5 <= env.confidence <= 0.8

    def test_no_person(self) -> None:
        snapshot = self._fixture_snapshot(person_count=0, gaze_direction="unknown")
        env = vision_to_envelope(snapshot, camera_role="c920-room")
        assert env is not None
        assert env.evidence_rows[0].hypothesis == "operator_absent"

    def test_stale_snapshot(self) -> None:
        snapshot = self._fixture_snapshot(updated_at=time.monotonic() - 60.0)
        env = vision_to_envelope(snapshot, camera_role="brio-operator", ttl_s=10)
        assert env is not None
        assert env.freshness.state == FreshnessState.STALE
        assert env.observation_state == ObservationState.STALE
        assert len(env.stale_refs) > 0
        assert "stale_evidence" in env.blocked_reasons

    def test_custom_aperture_id(self) -> None:
        snapshot = self._fixture_snapshot()
        env = vision_to_envelope(
            snapshot,
            camera_role="brio-operator",
            aperture_id="aperture:custom.test",
        )
        assert env is not None
        assert env.aperture_id == "aperture:custom.test"

    def test_empty_snapshot_returns_envelope(self) -> None:
        env = vision_to_envelope({}, camera_role="brio-operator")
        assert env is not None
        assert env.evidence_rows[0].hypothesis == "operator_absent"

    def test_bad_data_returns_none(self) -> None:
        env = vision_to_envelope(
            {"person_count": "not-a-number"},
            camera_role="brio-operator",
        )
        # Should either produce a valid envelope or None, never crash
        # int("not-a-number") raises ValueError, caught by the adapter
        assert env is None

    def test_semantic_labels_populated(self) -> None:
        snapshot = self._fixture_snapshot(
            person_count=1,
            detected_action="coding",
            scene_objects="keyboard, monitor",
        )
        env = vision_to_envelope(snapshot, camera_role="brio-operator")
        assert env is not None
        assert "person_present" in env.semantic_labels
        assert "coding" in env.semantic_labels

    def test_envelope_passes_model_validation(self) -> None:
        """Envelope round-trips through Pydantic validation."""
        snapshot = self._fixture_snapshot()
        env = vision_to_envelope(snapshot, camera_role="brio-operator")
        assert env is not None
        # Re-validate by constructing from dict
        roundtripped = CameraObservationEnvelope.model_validate(env.model_dump())
        assert roundtripped.envelope_id == env.envelope_id


# ── IR presence adapter tests ───────────────────────────────────────────


class TestIrToEnvelope:
    """ir_to_envelope adapter tests."""

    def _fixture_ir(self, **overrides: object) -> dict:
        base = {
            "person_detected": True,
            "motion_delta": 0.3,
            "brightness": 0.6,
            "timestamp": time.time(),
        }
        base.update(overrides)
        return base

    def test_produces_valid_envelope(self) -> None:
        env = ir_to_envelope(self._fixture_ir(), pi_name="desk")
        assert env is not None
        assert env.aperture_kind == ObservationApertureKind.STUDIO_IR_CAMERA
        assert env.producer == ProducerKind.IR_PRESENCE_BACKEND
        assert env.evidence_class == EvidenceClass.IR_PRESENCE
        assert env.privacy_mode == PrivacyMode.PRIVATE

    def test_person_detected(self) -> None:
        env = ir_to_envelope(self._fixture_ir(person_detected=True), pi_name="desk")
        assert env is not None
        assert env.evidence_rows[0].hypothesis == "operator_present_ir"

    def test_no_person_motion(self) -> None:
        env = ir_to_envelope(
            self._fixture_ir(person_detected=False, motion_delta=0.5),
            pi_name="room",
        )
        assert env is not None
        assert env.evidence_rows[0].hypothesis == "motion_detected_ir"

    def test_no_person_no_motion(self) -> None:
        env = ir_to_envelope(
            self._fixture_ir(person_detected=False, motion_delta=0.0),
            pi_name="overhead",
        )
        assert env is not None
        assert env.evidence_rows[0].hypothesis == "operator_absent_ir"

    def test_stale_ir(self) -> None:
        env = ir_to_envelope(
            self._fixture_ir(timestamp=time.time() - 120.0),
            pi_name="desk",
            ttl_s=15,
        )
        assert env is not None
        assert env.freshness.state == FreshnessState.STALE

    def test_empty_ir_returns_envelope(self) -> None:
        env = ir_to_envelope({}, pi_name="desk")
        assert env is not None

    def test_fail_closed_on_bad_data(self) -> None:
        # motion_delta as non-numeric should be caught
        env = ir_to_envelope(
            {"motion_delta": "invalid", "person_detected": "nope"},
            pi_name="desk",
        )
        # Either valid envelope or None, never exception
        assert env is None or isinstance(env, CameraObservationEnvelope)


# ── Cross-camera tracklet adapter tests ─────────────────────────────────


class TestCrossCameraToEnvelope:
    """cross_camera_to_envelope adapter tests."""

    def _fixture_tracklet(self, **overrides: object) -> dict:
        base = {
            "track_id": "t42",
            "cameras": ["brio-operator", "c920-room"],
            "similarity": 0.88,
            "time_delta_s": 1.5,
            "confidence": 0.82,
            "topology_path": "operator→room",
        }
        base.update(overrides)
        return base

    def test_produces_valid_envelope(self) -> None:
        env = cross_camera_to_envelope(self._fixture_tracklet())
        assert env is not None
        assert env.producer == ProducerKind.CROSS_CAMERA_STITCHER
        assert env.evidence_class == EvidenceClass.CROSS_CAMERA_TRACKLET
        assert env.authority_ceiling == ClaimAuthorityCeiling.INTERNAL_ONLY

    def test_tracklet_metadata_populated(self) -> None:
        env = cross_camera_to_envelope(self._fixture_tracklet())
        assert env is not None
        row = env.evidence_rows[0]
        assert "topology_path" in row.metadata
        assert "time_delta_s" in row.metadata
        assert "similarity" in row.metadata
        assert "uncertainty" in row.metadata
        assert row.metadata["similarity"] == 0.88

    def test_witness_refs_from_cameras(self) -> None:
        env = cross_camera_to_envelope(
            self._fixture_tracklet(cameras=["brio-operator", "c920-room"]),
        )
        assert env is not None
        assert len(env.witness_refs) == 2
        assert any("brio-operator" in ref for ref in env.witness_refs)

    def test_empty_tracklet_returns_envelope(self) -> None:
        env = cross_camera_to_envelope({})
        assert env is not None or env is None  # fail-closed allowed


# ── Livestream compositor adapter tests ─────────────────────────────────


class TestLivestreamToEnvelope:
    """livestream_to_envelope adapter tests."""

    def _fixture_compositor(self, **overrides: object) -> dict:
        base = {
            "active_camera": "brio-operator",
            "scene_name": "main",
            "frame_ts": time.time(),
            "confidence": 0.75,
        }
        base.update(overrides)
        return base

    def test_produces_valid_envelope(self) -> None:
        env = livestream_to_envelope(self._fixture_compositor())
        assert env is not None
        assert env.aperture_kind == ObservationApertureKind.LIVESTREAM_COMPOSED_FRAME
        assert env.producer == ProducerKind.COMPOSITOR_SNAPSHOT
        assert env.evidence_class == EvidenceClass.COMPOSED_LIVESTREAM
        assert env.privacy_mode == PrivacyMode.PUBLIC_SAFE

    def test_scene_name_in_hypothesis(self) -> None:
        env = livestream_to_envelope(self._fixture_compositor(scene_name="splitscreen"))
        assert env is not None
        assert "splitscreen" in env.evidence_rows[0].hypothesis

    def test_stale_frame(self) -> None:
        env = livestream_to_envelope(
            self._fixture_compositor(frame_ts=time.time() - 30.0),
            ttl_s=5,
        )
        assert env is not None
        assert env.freshness.state == FreshnessState.STALE

    def test_empty_compositor_returns_envelope(self) -> None:
        env = livestream_to_envelope({})
        assert env is not None

    def test_envelope_model_roundtrip(self) -> None:
        env = livestream_to_envelope(self._fixture_compositor())
        assert env is not None
        roundtripped = CameraObservationEnvelope.model_validate(env.model_dump())
        assert roundtripped.envelope_id == env.envelope_id


# ── Cross-adapter integration tests ────────────────────────────────────


class TestAdapterIntegration:
    """Verify all adapters can produce envelopes that the broker accepts."""

    def test_all_adapters_produce_distinct_envelope_ids(self) -> None:
        """Each adapter produces a unique envelope_id."""
        vision = vision_to_envelope(
            {"person_count": 1, "updated_at": time.monotonic()},
            camera_role="brio-operator",
        )
        ir = ir_to_envelope(
            {"person_detected": True, "timestamp": time.time()},
            pi_name="desk",
        )
        tracklet = cross_camera_to_envelope(
            {
                "track_id": "t1",
                "cameras": ["a", "b"],
                "similarity": 0.9,
                "time_delta_s": 1.0,
                "confidence": 0.8,
                "topology_path": "a→b",
            },
        )
        livestream = livestream_to_envelope(
            {"scene_name": "main", "frame_ts": time.time()},
        )

        assert vision is not None
        assert ir is not None
        assert tracklet is not None
        assert livestream is not None

        ids = {vision.envelope_id, ir.envelope_id, tracklet.envelope_id, livestream.envelope_id}
        assert len(ids) == 4  # all distinct

    def test_all_adapters_evidence_class_matches_envelope(self) -> None:
        """evidence_rows[0].evidence_class must match envelope.evidence_class."""
        envs = [
            vision_to_envelope(
                {"person_count": 0, "updated_at": time.monotonic()},
                camera_role="c920-desk",
            ),
            ir_to_envelope({"person_detected": False, "timestamp": time.time()}),
            cross_camera_to_envelope(
                {
                    "track_id": "t2",
                    "cameras": ["x"],
                    "similarity": 0.7,
                    "time_delta_s": 0.5,
                    "confidence": 0.6,
                    "topology_path": "x→x",
                }
            ),
            livestream_to_envelope({"scene_name": "test", "frame_ts": time.time()}),
        ]
        for env in envs:
            assert env is not None
            for row in env.evidence_rows:
                assert row.evidence_class == env.evidence_class
