"""Tests for camera salience producer adapters (Phase A).

Per-adapter golden-file-style tests using recorded state fixtures.
Each test verifies the adapter produces a valid CameraObservationEnvelope
and that the envelope passes the broker's contract validation.
"""

from __future__ import annotations

import time

from shared.bayesian_camera_salience_world_surface import (
    CameraObservationEnvelope,
    CameraSalienceBroker,
    CameraSalienceQuery,
    ClaimAuthorityCeiling,
    ConsumerKind,
    EvidenceClass,
    FreshnessState,
    ObservationApertureKind,
    ObservationState,
    PrivacyMode,
    ProducerKind,
    PublicClaimMode,
    load_camera_salience_fixtures,
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
        env = vision_to_envelope(snapshot, camera_role="c920-desk")
        assert env is not None
        assert env.evidence_rows[0].hypothesis == "operator_absent"

    def test_runtime_operator_role_maps_to_fixture_aperture(self) -> None:
        snapshot = self._fixture_snapshot()
        env = vision_to_envelope(snapshot, camera_role="operator")
        assert env is not None
        assert env.aperture_id == "aperture:studio-rgb.brio-operator"
        assert env.wcs_surface_refs == ("wcs-surface:camera.brio-operator",)

    def test_unregistered_vision_role_fails_closed(self) -> None:
        # c920-room / c920-overhead are now mapped to canonical apertures
        # (cc-task: bayesian-camera-salience-runtime-aperture-coverage);
        # a genuinely-unknown camera_role still returns None.
        snapshot = self._fixture_snapshot()
        assert vision_to_envelope(snapshot, camera_role="dvr-archive") is None

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
        assert env.aperture_id == "aperture:studio-ir.noir-desk"
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
            pi_name="desk",
        )
        assert env is not None
        assert env.evidence_rows[0].hypothesis == "motion_detected_ir"

    def test_no_person_no_motion(self) -> None:
        env = ir_to_envelope(
            self._fixture_ir(person_detected=False, motion_delta=0.0),
            pi_name="desk",
        )
        assert env is not None
        assert env.evidence_rows[0].hypothesis == "operator_absent_ir"

    def test_unregistered_ir_role_fails_closed(self) -> None:
        # `room`, `overhead`, and their canonical/short variants are now
        # mapped to aperture:studio-ir.noir-{room,overhead}; a genuinely
        # unknown pi_name still returns None.
        assert ir_to_envelope(self._fixture_ir(), pi_name="pi-noir-archive") is None

    def test_real_report_shape_maps_persons_and_ir_brightness(self) -> None:
        env = ir_to_envelope(
            {
                "persons": [{"confidence": 0.8}],
                "motion_delta": 0.2,
                "ir_brightness": 0.42,
                "timestamp": time.time(),
            },
            pi_name="pi-noir-desk",
        )
        assert env is not None
        assert env.evidence_rows[0].hypothesis == "operator_present_ir"
        assert env.evidence_rows[0].metadata["brightness"] == 0.42

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
            "cameras": ["brio-operator", "c920-desk"],
            "similarity": 0.88,
            "time_delta_s": 1.5,
            "confidence": 0.82,
            "topology_path": "operator->desk",
        }
        base.update(overrides)
        return base

    def test_produces_valid_envelope(self) -> None:
        env = cross_camera_to_envelope(self._fixture_tracklet())
        assert env is not None
        assert env.aperture_id == "aperture:studio-rgb.brio-operator"
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
            self._fixture_tracklet(cameras=["brio-operator", "c920-desk"]),
        )
        assert env is not None
        assert len(env.witness_refs) == 2
        assert any("brio-operator" in ref for ref in env.witness_refs)

    def test_empty_tracklet_fails_closed(self) -> None:
        env = cross_camera_to_envelope({})
        assert env is None

    def test_unregistered_tracklet_fails_closed(self) -> None:
        # c920-room is now a canonical aperture; a tracklet that names
        # only genuinely-unknown cameras still returns None.
        env = cross_camera_to_envelope(self._fixture_tracklet(cameras=["dvr-archive"]))
        assert env is None


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
        assert env.wcs_surface_refs == ("wcs-surface:livestream.composed-frame",)

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
                "cameras": ["brio-operator", "c920-desk"],
                "similarity": 0.9,
                "time_delta_s": 1.0,
                "confidence": 0.8,
                "topology_path": "brio-operator->c920-desk",
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
                    "cameras": ["brio-operator"],
                    "similarity": 0.7,
                    "time_delta_s": 0.5,
                    "confidence": 0.6,
                    "topology_path": "brio-operator->brio-operator",
                }
            ),
            livestream_to_envelope({"scene_name": "test", "frame_ts": time.time()}),
        ]
        for env in envs:
            assert env is not None
            for row in env.evidence_rows:
                assert row.evidence_class == env.evidence_class

    def test_default_adapter_outputs_are_accepted_by_fixture_broker(self) -> None:
        fixtures = load_camera_salience_fixtures()
        envs = tuple(
            env
            for env in (
                vision_to_envelope(
                    {"person_count": 1, "gaze_direction": "screen", "updated_at": time.monotonic()},
                    camera_role="operator",
                ),
                ir_to_envelope({"persons": [{"confidence": 0.8}], "timestamp": time.time()}),
                cross_camera_to_envelope(
                    {
                        "track_id": "t3",
                        "cameras": ["brio-operator", "c920-desk"],
                        "similarity": 0.86,
                        "time_delta_s": 1.0,
                        "confidence": 0.82,
                        "topology_path": "brio-operator->c920-desk",
                    }
                ),
                livestream_to_envelope({"scene_name": "dual", "frame_ts": time.time()}),
            )
            if env is not None
        )
        assert len(envs) == 4

        broker = CameraSalienceBroker(fixtures.apertures, envs)
        bundle = broker.evaluate(
            CameraSalienceQuery(
                query_id="camera-salience-query:adapter-integration",
                consumer=ConsumerKind.DIRECTOR,
                decision_context="adapter_fixture_acceptance",
                candidate_action="compose_livestream_move",
                time_budget_ms=50,
                privacy_mode=PrivacyMode.PRIVATE,
                public_claim_mode=PublicClaimMode.NONE,
                evidence_classes=(
                    EvidenceClass.FRAME,
                    EvidenceClass.IR_PRESENCE,
                    EvidenceClass.CROSS_CAMERA_TRACKLET,
                    EvidenceClass.COMPOSED_LIVESTREAM,
                ),
                max_images=0,
                max_tokens=200,
            )
        )
        assert bundle.ranked_observations


# ── Runtime aperture-coverage tests ──────────────────────────────────────
#
# cc-task: bayesian-camera-salience-runtime-aperture-coverage
#
# Pin the full studio-camera-fleet → canonical-aperture mapping. Every
# camera role string the live producers emit (per CLAUDE.md: brio-
# operator, c920-desk/room/overhead, noir-desk/room/overhead) must
# resolve to an aperture declared in
# ``config/bayesian-camera-salience-world-surface-fixtures.json``. If a
# fixture is removed or a producer starts emitting a new role string
# that wasn't added to the adapter map, these tests fire — guaranteeing
# ``camera-classifications.json`` never silently shows ``unspecified``
# for a known live camera.

import json
from pathlib import Path

import pytest

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "bayesian-camera-salience-world-surface-fixtures.json"
)


def _fixture_aperture_ids() -> set[str]:
    raw = json.loads(_FIXTURE_PATH.read_text())
    return {a["aperture_id"] for a in raw["apertures"]}


class TestRuntimeApertureCoverage:
    """The full live camera fleet maps onto canonical apertures."""

    @pytest.fixture(autouse=True)
    def _aperture_ids(self) -> None:
        self.canonical = _fixture_aperture_ids()

    def _vision_snapshot(self) -> dict:
        return {
            "person_count": 0,
            "operator_present": False,
            "updated_at": time.monotonic(),
        }

    def _ir_snapshot(self) -> dict:
        return {"persons": [], "motion_delta": 0.0, "timestamp": time.time()}

    @pytest.mark.parametrize(
        "role,expected_aperture",
        [
            # RGB cameras — every form a producer is known to emit.
            ("operator", "aperture:studio-rgb.brio-operator"),
            ("brio-operator", "aperture:studio-rgb.brio-operator"),
            ("desk", "aperture:studio-rgb.c920-desk"),
            ("c920-desk", "aperture:studio-rgb.c920-desk"),
            ("room", "aperture:studio-rgb.c920-room"),
            ("c920-room", "aperture:studio-rgb.c920-room"),
            ("overhead", "aperture:studio-rgb.c920-overhead"),
            ("c920-overhead", "aperture:studio-rgb.c920-overhead"),
        ],
    )
    def test_vision_role_maps_to_canonical_aperture(
        self, role: str, expected_aperture: str
    ) -> None:
        env = vision_to_envelope(self._vision_snapshot(), camera_role=role)
        assert env is not None, f"vision adapter fail-closed for live role {role!r}"
        assert env.aperture_id == expected_aperture, (
            f"vision role {role!r} → {env.aperture_id}, expected {expected_aperture}"
        )
        assert env.aperture_id in self.canonical, (
            f"vision aperture {env.aperture_id} not in canonical fixture"
        )

    @pytest.mark.parametrize(
        "pi_name,expected_aperture",
        [
            # IR Pis — every form a producer is known to emit.
            ("desk", "aperture:studio-ir.noir-desk"),
            ("noir-desk", "aperture:studio-ir.noir-desk"),
            ("pi-noir-desk", "aperture:studio-ir.noir-desk"),
            ("room", "aperture:studio-ir.noir-room"),
            ("noir-room", "aperture:studio-ir.noir-room"),
            ("pi-noir-room", "aperture:studio-ir.noir-room"),
            ("overhead", "aperture:studio-ir.noir-overhead"),
            ("noir-overhead", "aperture:studio-ir.noir-overhead"),
            ("pi-noir-overhead", "aperture:studio-ir.noir-overhead"),
        ],
    )
    def test_ir_role_maps_to_canonical_aperture(self, pi_name: str, expected_aperture: str) -> None:
        env = ir_to_envelope(self._ir_snapshot(), pi_name=pi_name)
        assert env is not None, f"ir adapter fail-closed for live pi_name {pi_name!r}"
        assert env.aperture_id == expected_aperture
        assert env.aperture_id in self.canonical

    def test_no_producer_emits_aperture_unknown_to_singleton(self) -> None:
        """The canonical fleet must be a strict subset of the fixture's
        aperture set. This is the load-bearing acceptance criterion: no
        adapter ever produces an envelope whose ``aperture_id`` is unknown
        to the singleton's loaded apertures."""
        # The full set of aperture_ids the producer adapters can emit.
        from shared.camera_salience_producer_adapters import (
            _IR_ROLE_TO_APERTURE_ID,
            _VISION_ROLE_TO_APERTURE_ID,
        )

        emitted = set(_VISION_ROLE_TO_APERTURE_ID.values()) | set(_IR_ROLE_TO_APERTURE_ID.values())
        # Plus the livestream composed-frame aperture the livestream adapter
        # hard-codes (not table-driven).
        emitted.add("aperture:livestream.composed-frame")
        unknown = emitted - self.canonical
        assert not unknown, (
            f"adapters can emit aperture_ids not in the canonical fixture: {unknown}"
        )
