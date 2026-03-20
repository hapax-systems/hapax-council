"""Tests for classification detection overlay data pipeline.

Covers:
- Consent gating: person enrichment suppression, person removal on refusal
- Confidence gating: low-confidence objects excluded, top 5 cap
- Novelty computation: new objects high novelty, familiar objects low
- Bbox normalization: pixel coords → 0-1 range
"""

from agents.visual_layer_aggregator import _map_scene_inventory


def _make_perception(
    objects: list[dict],
    consent_phase: str = "no_guest",
) -> dict:
    """Build minimal perception state dict with scene inventory."""
    return {
        "consent_phase": consent_phase,
        "scene_inventory": {
            "object_count": len(objects),
            "objects": objects,
        },
    }


def _obj(
    label: str = "keyboard",
    camera: str = "brio-operator",
    box: list | None = None,
    confidence: float = 0.8,
    seen_count: int = 10,
    mobility: str = "static",
    entity_id: str = "abc123",
) -> dict:
    """Build a minimal scene inventory object."""
    return {
        "entity_id": entity_id,
        "label": label,
        "camera": camera,
        "box": box or [100, 100, 400, 400],
        "confidence": confidence,
        "seen_count": seen_count,
        "mobility": mobility,
    }


class TestConsentGating:
    def test_no_guest_person_not_suppressed(self):
        data = _make_perception([_obj(label="person")], consent_phase="no_guest")
        dets = _map_scene_inventory(data)
        assert len(dets) == 1
        assert not dets[0].consent_suppressed

    def test_consent_granted_person_not_suppressed(self):
        data = _make_perception([_obj(label="person")], consent_phase="consent_granted")
        dets = _map_scene_inventory(data)
        assert len(dets) == 1
        assert not dets[0].consent_suppressed

    def test_guest_detected_person_suppressed(self):
        data = _make_perception([_obj(label="person")], consent_phase="guest_detected")
        dets = _map_scene_inventory(data)
        assert len(dets) == 1
        assert dets[0].consent_suppressed

    def test_consent_pending_person_suppressed(self):
        data = _make_perception([_obj(label="person")], consent_phase="consent_pending")
        dets = _map_scene_inventory(data)
        assert len(dets) == 1
        assert dets[0].consent_suppressed

    def test_consent_refused_person_removed(self):
        data = _make_perception([_obj(label="person")], consent_phase="consent_refused")
        dets = _map_scene_inventory(data)
        # Person detections entirely removed during refusal
        assert len(dets) == 0

    def test_consent_refused_non_person_retained(self):
        data = _make_perception(
            [_obj(label="person"), _obj(label="keyboard", entity_id="kb1")],
            consent_phase="consent_refused",
        )
        dets = _map_scene_inventory(data)
        assert len(dets) == 1
        assert dets[0].label == "keyboard"

    def test_non_person_never_suppressed(self):
        for phase in ("guest_detected", "consent_pending"):
            data = _make_perception([_obj(label="monitor")], consent_phase=phase)
            dets = _map_scene_inventory(data)
            assert len(dets) == 1
            assert not dets[0].consent_suppressed


class TestConfidenceGating:
    def test_low_confidence_excluded(self):
        data = _make_perception([_obj(confidence=0.2)])
        dets = _map_scene_inventory(data)
        assert len(dets) == 0

    def test_threshold_confidence_included(self):
        data = _make_perception([_obj(confidence=0.3)])
        dets = _map_scene_inventory(data)
        assert len(dets) == 1

    def test_top_5_cap(self):
        objects = [_obj(entity_id=f"e{i}", confidence=0.9 - i * 0.05) for i in range(8)]
        data = _make_perception(objects)
        dets = _map_scene_inventory(data)
        assert len(dets) == 5
        # Sorted by confidence descending
        assert dets[0].confidence >= dets[-1].confidence


class TestNoveltyComputation:
    def test_new_object_high_novelty(self):
        data = _make_perception([_obj(seen_count=1)])
        dets = _map_scene_inventory(data)
        assert dets[0].novelty >= 0.7  # blended: high count + high recency

    def test_familiar_object_low_novelty(self):
        data = _make_perception([_obj(seen_count=21)])
        dets = _map_scene_inventory(data)
        assert dets[0].novelty <= 0.4  # blended: zero count + some recency

    def test_moderate_sighting_moderate_novelty(self):
        data = _make_perception([_obj(seen_count=11)])
        dets = _map_scene_inventory(data)
        assert 0.3 < dets[0].novelty < 0.7


class TestBboxNormalization:
    def test_brio_normalization(self):
        # BRIO: 1920x1080
        data = _make_perception([_obj(camera="brio-operator", box=[960, 540, 1920, 1080])])
        dets = _map_scene_inventory(data)
        box = dets[0].box
        assert abs(box[0] - 0.5) < 0.01
        assert abs(box[1] - 0.5) < 0.01
        assert abs(box[2] - 1.0) < 0.01
        assert abs(box[3] - 1.0) < 0.01

    def test_c920_normalization(self):
        # C920: 1280x720
        data = _make_perception([_obj(camera="c920-room", box=[640, 360, 1280, 720])])
        dets = _map_scene_inventory(data)
        box = dets[0].box
        assert abs(box[0] - 0.5) < 0.01
        assert abs(box[1] - 0.5) < 0.01
        assert abs(box[2] - 1.0) < 0.01
        assert abs(box[3] - 1.0) < 0.01

    def test_no_box_skipped(self):
        obj = _obj()
        del obj["box"]
        data = _make_perception([obj])
        dets = _map_scene_inventory(data)
        assert len(dets) == 0
