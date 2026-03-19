"""Tests for ByteTrack multi-object tracker."""

from __future__ import annotations

from agents.byte_tracker import ByteTracker


def _det(x1: float, y1: float, x2: float, y2: float, conf: float = 0.9, label: str = "person"):
    return {"box": [x1, y1, x2, y2], "confidence": conf, "label": label}


class TestByteTracker:
    def test_single_detection_creates_track(self):
        bt = ByteTracker()
        results = bt.update([_det(100, 100, 200, 200)])
        assert len(results) == 1
        assert results[0]["track_id"] == 1
        assert results[0]["label"] == "person"

    def test_consistent_detection_confirms_track(self):
        bt = ByteTracker(min_hits=3)
        for _ in range(3):
            results = bt.update([_det(100, 100, 200, 200)])
        assert results[0]["confirmed"] is True

    def test_two_objects_get_different_ids(self):
        bt = ByteTracker()
        results = bt.update(
            [
                _det(100, 100, 200, 200, label="person"),
                _det(500, 500, 600, 600, label="chair"),
            ]
        )
        ids = {r["track_id"] for r in results}
        assert len(ids) == 2

    def test_track_follows_moving_object(self):
        bt = ByteTracker()
        bt.update([_det(100, 100, 200, 200)])
        results = bt.update([_det(110, 110, 210, 210)])  # slight movement
        assert len(results) == 1
        assert results[0]["track_id"] == 1  # same track

    def test_lost_track_removed_after_max_age(self):
        bt = ByteTracker(max_age=2)
        bt.update([_det(100, 100, 200, 200)])
        bt.update([])  # lost
        bt.update([])  # still lost
        results = bt.update([])  # exceeded max_age
        assert len(results) == 0

    def test_low_confidence_second_stage(self):
        bt = ByteTracker(high_thresh=0.6, low_thresh=0.1)
        bt.update([_det(100, 100, 200, 200, conf=0.9)])
        # Low confidence detection still matches existing track
        results = bt.update([_det(105, 105, 205, 205, conf=0.3)])
        assert len(results) == 1
        assert results[0]["track_id"] == 1

    def test_empty_detections(self):
        bt = ByteTracker()
        results = bt.update([])
        assert len(results) == 0

    def test_reset_clears_state(self):
        bt = ByteTracker()
        bt.update([_det(100, 100, 200, 200)])
        bt.reset()
        results = bt.update([_det(100, 100, 200, 200)])
        assert results[0]["track_id"] == 1  # IDs restart

    def test_non_overlapping_objects_separate_tracks(self):
        bt = ByteTracker()
        bt.update([_det(0, 0, 50, 50), _det(900, 900, 950, 950)])
        results = bt.update([_det(0, 0, 50, 50), _det(900, 900, 950, 950)])
        assert len(results) == 2
        ids = [r["track_id"] for r in results]
        assert ids[0] != ids[1]
