"""Tests for Batch 1: signal convergence — enriched ClassificationDetection.

Covers:
- SceneInventory.snapshot_for_overlay() includes new metadata fields
- _map_scene_inventory() forwards person enrichments from perception state
- Consent suppression nulls person enrichments
- Backward compatibility with 8-field-only ClassificationDetection
- Sightings box normalization
"""

from __future__ import annotations

import time

from agents.hapax_voice.scene_inventory import SceneInventory
from agents.visual_layer_aggregator import _map_scene_inventory
from agents.visual_layer_state import ClassificationDetection

# ── Helpers ────────────────────────────────────────────────────────────


def _make_perception_data(
    *,
    objects: list[dict] | None = None,
    consent_phase: str = "no_guest",
    gaze: str = "",
    emotion: str = "",
    posture: str = "",
    gesture: str = "",
    action: str = "",
    depth: str = "",
) -> dict:
    """Build a minimal perception-state dict for testing _map_scene_inventory."""
    return {
        "scene_inventory": {
            "objects": objects or [],
        },
        "consent_phase": consent_phase,
        "gaze_direction": gaze,
        "top_emotion": emotion,
        "posture": posture,
        "hand_gesture": gesture,
        "detected_action": action,
        "nearest_person_distance": depth,
    }


def _make_object(
    *,
    entity_id: str = "abc123",
    label: str = "person",
    camera: str = "operator",
    box: list[float] | None = None,
    confidence: float = 0.9,
    mobility: str = "dynamic",
    mobility_score: float = 0.6,
    seen_count: int = 10,
    first_seen_age_s: float = 120.0,
    camera_count: int = 2,
    sightings: list[list[float]] | None = None,
) -> dict:
    """Build a scene inventory object dict."""
    return {
        "entity_id": entity_id,
        "label": label,
        "camera": camera,
        "box": box or [100, 100, 300, 400],
        "confidence": confidence,
        "mobility": mobility,
        "mobility_score": mobility_score,
        "seen_count": seen_count,
        "first_seen_age_s": first_seen_age_s,
        "camera_count": camera_count,
        "sightings": sightings,
    }


# ── ClassificationDetection backward compatibility ─────────────────────


class TestClassificationDetectionCompat:
    """8-field-only construction still works (all new fields optional)."""

    def test_minimal_construction(self):
        det = ClassificationDetection(
            entity_id="x",
            label="chair",
            camera="c920-room",
            box=(0.1, 0.2, 0.3, 0.4),
            confidence=0.8,
        )
        assert det.entity_id == "x"
        assert det.gaze_direction is None
        assert det.emotion is None
        assert det.mobility_score is None
        assert det.sightings is None
        assert det.camera_count is None

    def test_full_construction(self):
        det = ClassificationDetection(
            entity_id="p1",
            label="person",
            camera="brio-operator",
            box=(0.1, 0.2, 0.5, 0.8),
            confidence=0.95,
            gaze_direction="screen",
            emotion="happy",
            posture="upright",
            gesture="open_palm",
            action="typing",
            depth="close",
            mobility_score=0.3,
            first_seen_age_s=60.0,
            camera_count=1,
            sightings=[(0.1, 0.2, 0.5, 0.8), (0.12, 0.21, 0.52, 0.81)],
        )
        assert det.gaze_direction == "screen"
        assert det.emotion == "happy"
        assert det.sightings is not None
        assert len(det.sightings) == 2

    def test_serialization_roundtrip(self):
        det = ClassificationDetection(
            entity_id="p1",
            label="person",
            camera="brio-operator",
            box=(0.1, 0.2, 0.5, 0.8),
            confidence=0.95,
            gaze_direction="hardware",
            mobility_score=0.7,
            sightings=[(0.1, 0.2, 0.3, 0.4)],
        )
        data = det.model_dump()
        restored = ClassificationDetection(**data)
        assert restored.gaze_direction == "hardware"
        assert restored.mobility_score == 0.7
        assert restored.sightings == [(0.1, 0.2, 0.3, 0.4)]


# ── _map_scene_inventory enrichment forwarding ─────────────────────────


class TestMapSceneInventoryEnrichments:
    """Person enrichments from perception-state are forwarded correctly."""

    def test_person_on_operator_camera_gets_enrichments(self):
        data = _make_perception_data(
            objects=[_make_object(camera="operator")],
            gaze="screen",
            emotion="neutral",
            posture="upright",
            action="typing",
            depth="close",
        )
        dets = _map_scene_inventory(data)
        assert len(dets) == 1
        det = dets[0]
        assert det.gaze_direction == "screen"
        assert det.emotion == "neutral"
        assert det.posture == "upright"
        assert det.action == "typing"
        assert det.depth == "close"

    def test_person_on_c920_camera_no_enrichments(self):
        """C920 cameras don't run person classifiers — no enrichments."""
        data = _make_perception_data(
            objects=[_make_object(camera="room")],
            gaze="screen",
            emotion="happy",
        )
        dets = _map_scene_inventory(data)
        assert len(dets) == 1
        det = dets[0]
        assert det.gaze_direction is None
        assert det.emotion is None

    def test_person_on_non_operator_brio_gets_enrichments(self):
        """Any Brio-class camera can enrich persons (multi-perspective)."""
        data = _make_perception_data(
            objects=[_make_object(camera="room-brio")],
            gaze="screen",
            emotion="happy",
        )
        dets = _map_scene_inventory(data)
        assert len(dets) == 1
        det = dets[0]
        assert det.gaze_direction == "screen"
        assert det.emotion == "happy"

    def test_person_on_aux_brio_gets_enrichments(self):
        data = _make_perception_data(
            objects=[_make_object(camera="aux-brio")],
            gaze="hardware",
            posture="slouching",
        )
        dets = _map_scene_inventory(data)
        assert len(dets) == 1
        assert dets[0].gaze_direction == "hardware"
        assert dets[0].posture == "slouching"

    def test_non_person_no_enrichments(self):
        data = _make_perception_data(
            objects=[_make_object(label="chair", camera="operator")],
            gaze="screen",
            emotion="happy",
        )
        dets = _map_scene_inventory(data)
        assert len(dets) == 1
        det = dets[0]
        assert det.gaze_direction is None
        assert det.emotion is None

    def test_empty_enrichment_values_become_none(self):
        data = _make_perception_data(
            objects=[_make_object(camera="operator")],
            gaze="",
            emotion="",
        )
        dets = _map_scene_inventory(data)
        assert dets[0].gaze_direction is None
        assert dets[0].emotion is None


# ── Consent suppression ────────────────────────────────────────────────


class TestConsentSuppression:
    """Person enrichments are nulled when consent is not granted."""

    def test_guest_detected_suppresses_enrichments(self):
        data = _make_perception_data(
            objects=[_make_object(camera="operator")],
            consent_phase="guest_detected",
            gaze="screen",
            emotion="happy",
        )
        dets = _map_scene_inventory(data)
        assert len(dets) == 1
        assert dets[0].consent_suppressed is True
        assert dets[0].gaze_direction is None
        assert dets[0].emotion is None

    def test_consent_pending_suppresses_enrichments(self):
        data = _make_perception_data(
            objects=[_make_object(camera="operator")],
            consent_phase="consent_pending",
            gaze="hardware",
        )
        dets = _map_scene_inventory(data)
        assert dets[0].consent_suppressed is True
        assert dets[0].gaze_direction is None

    def test_consent_refused_removes_person_detections(self):
        data = _make_perception_data(
            objects=[_make_object(camera="operator")],
            consent_phase="consent_refused",
        )
        dets = _map_scene_inventory(data)
        assert len(dets) == 0

    def test_consent_granted_allows_enrichments(self):
        data = _make_perception_data(
            objects=[_make_object(camera="operator")],
            consent_phase="consent_granted",
            gaze="screen",
            emotion="happy",
        )
        dets = _map_scene_inventory(data)
        assert len(dets) == 1
        assert dets[0].consent_suppressed is False
        assert dets[0].gaze_direction == "screen"
        assert dets[0].emotion == "happy"

    def test_non_person_not_suppressed_during_guest_detected(self):
        data = _make_perception_data(
            objects=[_make_object(label="laptop", camera="operator")],
            consent_phase="guest_detected",
        )
        dets = _map_scene_inventory(data)
        assert len(dets) == 1
        assert dets[0].consent_suppressed is False


# ── Entity metadata forwarding ─────────────────────────────────────────


class TestEntityMetadata:
    """mobility_score, first_seen_age_s, camera_count, sightings forwarded."""

    def test_metadata_forwarded(self):
        data = _make_perception_data(
            objects=[
                _make_object(
                    mobility_score=0.75,
                    first_seen_age_s=300.0,
                    camera_count=3,
                    sightings=[[0.1, 0.2, 0.3, 0.4], [0.15, 0.25, 0.35, 0.45]],
                )
            ],
        )
        dets = _map_scene_inventory(data)
        det = dets[0]
        assert det.mobility_score == 0.75
        assert det.first_seen_age_s == 300.0
        assert det.camera_count == 3
        assert det.sightings is not None
        assert len(det.sightings) == 2
        assert det.sightings[0] == (0.1, 0.2, 0.3, 0.4)

    def test_missing_metadata_is_none(self):
        obj = _make_object()
        del obj["mobility_score"]
        del obj["first_seen_age_s"]
        del obj["camera_count"]
        data = _make_perception_data(objects=[obj])
        dets = _map_scene_inventory(data)
        det = dets[0]
        assert det.mobility_score is None
        assert det.first_seen_age_s is None
        assert det.camera_count is None

    def test_sightings_capped_at_5(self):
        sightings = [[i * 0.01, 0.1, i * 0.01 + 0.1, 0.2] for i in range(10)]
        data = _make_perception_data(
            objects=[_make_object(sightings=sightings)],
        )
        dets = _map_scene_inventory(data)
        assert dets[0].sightings is not None
        assert len(dets[0].sightings) <= 5

    def test_empty_sightings_becomes_none(self):
        data = _make_perception_data(
            objects=[_make_object(sightings=[])],
        )
        dets = _map_scene_inventory(data)
        assert dets[0].sightings is None


# ── SceneInventory.snapshot_for_overlay() enrichments ──────────────────


class TestSnapshotForOverlay:
    """snapshot_for_overlay() includes mobility_score, camera_count, sightings."""

    def test_includes_new_fields(self):
        inv = SceneInventory(persist_path=None)
        now = time.time()
        inv.ingest(
            [
                {"label": "person", "confidence": 0.9, "box": [100, 200, 300, 500], "track_id": 1},
            ],
            camera_role="brio-operator",
            timestamp=now,
        )
        # Ingest a second time to get camera_history and sightings
        inv.ingest(
            [
                {"label": "person", "confidence": 0.88, "box": [110, 210, 310, 510], "track_id": 1},
            ],
            camera_role="brio-operator",
            timestamp=now + 0.5,
        )

        results = inv.snapshot_for_overlay()
        assert len(results) >= 1
        obj = results[0]
        assert "mobility_score" in obj
        assert "first_seen_age_s" in obj
        assert "camera_count" in obj
        assert "sightings" in obj
        assert isinstance(obj["sightings"], list)
        assert obj["camera_count"] >= 1

    def test_sightings_normalized_to_01(self):
        inv = SceneInventory(persist_path=None)
        now = time.time()
        # Use brio (1920x1080)
        inv.ingest(
            [
                {"label": "desk", "confidence": 0.7, "box": [960, 540, 1920, 1080], "track_id": 1},
            ],
            camera_role="brio-operator",
            timestamp=now,
        )
        results = inv.snapshot_for_overlay()
        assert len(results) >= 1
        obj = results[0]
        sightings = obj["sightings"]
        assert len(sightings) >= 1
        # Box [960, 540, 1920, 1080] / (1920, 1080) → [0.5, 0.5, 1.0, 1.0]
        s = sightings[0]
        assert abs(s[0] - 0.5) < 0.01
        assert abs(s[1] - 0.5) < 0.01
        assert abs(s[2] - 1.0) < 0.01
        assert abs(s[3] - 1.0) < 0.01


# ── Batch 3: per-entity enrichment wiring ──────────────────────────────


class TestEnrichEntity:
    """SceneInventory.enrich_entity() attaches per-entity enrichments."""

    def test_enrich_sets_fields(self):
        inv = SceneInventory(persist_path=None)
        now = time.time()
        inv.ingest(
            [{"label": "person", "confidence": 0.9, "box": [100, 200, 300, 500], "track_id": 1}],
            camera_role="brio-operator",
            timestamp=now,
        )
        # Find entity by track_id
        eid = inv.find_by_track_id("brio-operator", 1)
        assert eid is not None

        result = inv.enrich_entity(
            eid,
            gaze_direction="screen",
            emotion="neutral",
            posture="upright",
            gesture="none",
            action="typing",
            depth="close",
        )
        assert result is True

        # Verify enrichments appear in snapshot
        results = inv.snapshot_for_overlay()
        assert len(results) >= 1
        obj = results[0]
        assert obj.get("gaze_direction") == "screen"
        assert obj.get("emotion") == "neutral"
        assert obj.get("action") == "typing"
        assert obj.get("depth") == "close"

    def test_enrich_nonexistent_entity(self):
        inv = SceneInventory(persist_path=None)
        result = inv.enrich_entity("nonexistent", gaze_direction="screen")
        assert result is False

    def test_enrich_ignores_invalid_keys(self):
        inv = SceneInventory(persist_path=None)
        now = time.time()
        inv.ingest(
            [{"label": "person", "confidence": 0.9, "box": [100, 200, 300, 500], "track_id": 1}],
            camera_role="brio-operator",
            timestamp=now,
        )
        eid = inv.find_by_track_id("brio-operator", 1)
        assert eid is not None
        # "invalid_field" should be silently ignored
        result = inv.enrich_entity(eid, invalid_field="bad", gaze_direction="screen")
        assert result is True


class TestFindByTrackId:
    """SceneInventory.find_by_track_id() resolves track_id to entity_id."""

    def test_find_existing(self):
        inv = SceneInventory(persist_path=None)
        now = time.time()
        inv.ingest(
            [{"label": "person", "confidence": 0.9, "box": [100, 200, 300, 500], "track_id": 42}],
            camera_role="brio-operator",
            timestamp=now,
        )
        eid = inv.find_by_track_id("brio-operator", 42)
        assert eid is not None
        assert len(eid) > 0

    def test_find_wrong_camera(self):
        inv = SceneInventory(persist_path=None)
        now = time.time()
        inv.ingest(
            [{"label": "person", "confidence": 0.9, "box": [100, 200, 300, 500], "track_id": 42}],
            camera_role="brio-operator",
            timestamp=now,
        )
        eid = inv.find_by_track_id("c920-room", 42)
        assert eid is None

    def test_find_wrong_track_id(self):
        inv = SceneInventory(persist_path=None)
        now = time.time()
        inv.ingest(
            [{"label": "person", "confidence": 0.9, "box": [100, 200, 300, 500], "track_id": 42}],
            camera_role="brio-operator",
            timestamp=now,
        )
        eid = inv.find_by_track_id("brio-operator", 99)
        assert eid is None


class TestPerEntityEnrichmentForwarding:
    """_map_scene_inventory reads per-entity enrichments from objects."""

    def test_prefers_entity_enrichments_over_global(self):
        """Per-entity enrichments take precedence over global perception-state."""
        obj = _make_object(camera="operator")
        obj["gaze_direction"] = "hardware"  # per-entity
        obj["emotion"] = "happy"  # per-entity
        data = _make_perception_data(
            objects=[obj],
            gaze="screen",  # global (should be overridden)
            emotion="neutral",  # global (should be overridden)
            posture="slouching",
        )
        dets = _map_scene_inventory(data)
        assert len(dets) == 1
        assert dets[0].gaze_direction == "hardware"  # from entity
        assert dets[0].emotion == "happy"  # from entity
        assert dets[0].posture == "slouching"  # from global (no entity value)

    def test_falls_back_to_global_when_no_entity_enrichment(self):
        obj = _make_object(camera="operator")
        # No per-entity enrichments
        data = _make_perception_data(
            objects=[obj],
            gaze="screen",
            emotion="neutral",
        )
        dets = _map_scene_inventory(data)
        assert dets[0].gaze_direction == "screen"  # from global
        assert dets[0].emotion == "neutral"  # from global
