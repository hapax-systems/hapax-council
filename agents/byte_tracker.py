"""ByteTrack multi-object tracker — proper association across frames.

Replaces IoU-only matching in SceneInventory with the ByteTrack algorithm
(Zhang et al., 2022). Two-stage association: high-confidence detections
matched first via IoU, then low-confidence detections fill gaps.

Pure computation module: no I/O, no GPU. Designed to run per-camera
per-tick in the vision inference loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Track:
    """A tracked object across frames."""

    track_id: int
    box: np.ndarray  # [x1, y1, x2, y2]
    confidence: float
    label: str
    age: int = 0  # frames since creation
    hits: int = 1  # total successful associations
    time_since_update: int = 0  # frames since last association
    velocity: np.ndarray = field(default_factory=lambda: np.zeros(4))

    def predict(self) -> np.ndarray:
        """Predict next position using constant velocity model."""
        self.age += 1
        self.time_since_update += 1
        predicted = self.box + self.velocity
        return predicted

    def update(self, box: np.ndarray, confidence: float) -> None:
        """Update track with matched detection."""
        self.velocity = 0.7 * self.velocity + 0.3 * (box - self.box)
        self.box = box
        self.confidence = confidence
        self.hits += 1
        self.time_since_update = 0


def _iou_batch(boxes_a: np.ndarray, boxes_b: np.ndarray) -> np.ndarray:
    """Compute IoU between two sets of boxes. Returns (N, M) matrix."""
    if len(boxes_a) == 0 or len(boxes_b) == 0:
        return np.empty((len(boxes_a), len(boxes_b)))

    x1 = np.maximum(boxes_a[:, 0:1], boxes_b[:, 0:1].T)
    y1 = np.maximum(boxes_a[:, 1:2], boxes_b[:, 1:2].T)
    x2 = np.minimum(boxes_a[:, 2:3], boxes_b[:, 2:3].T)
    y2 = np.minimum(boxes_a[:, 3:4], boxes_b[:, 3:4].T)

    inter = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    area_a = (boxes_a[:, 2] - boxes_a[:, 0]) * (boxes_a[:, 3] - boxes_a[:, 1])
    area_b = (boxes_b[:, 2] - boxes_b[:, 0]) * (boxes_b[:, 3] - boxes_b[:, 1])
    union = area_a[:, None] + area_b[None, :] - inter

    return np.where(union > 0, inter / union, 0.0)


def _linear_assignment(cost_matrix: np.ndarray, threshold: float) -> tuple[list, list, list]:
    """Greedy assignment (good enough for <50 objects, avoids scipy dependency).

    Returns: (matches, unmatched_tracks, unmatched_detections)
    """
    if cost_matrix.size == 0:
        return [], list(range(cost_matrix.shape[0])), list(range(cost_matrix.shape[1]))

    matches = []
    used_rows: set[int] = set()
    used_cols: set[int] = set()

    # Greedy: pick highest IoU pairs first
    flat_indices = np.argsort(-cost_matrix.ravel())
    for idx in flat_indices:
        row = int(idx // cost_matrix.shape[1])
        col = int(idx % cost_matrix.shape[1])
        if row in used_rows or col in used_cols:
            continue
        if cost_matrix[row, col] < threshold:
            break
        matches.append((row, col))
        used_rows.add(row)
        used_cols.add(col)

    unmatched_tracks = [i for i in range(cost_matrix.shape[0]) if i not in used_rows]
    unmatched_dets = [j for j in range(cost_matrix.shape[1]) if j not in used_cols]
    return matches, unmatched_tracks, unmatched_dets


class ByteTracker:
    """ByteTrack multi-object tracker.

    Two-stage association:
    1. High-confidence detections (>= high_thresh) matched to tracks via IoU
    2. Low-confidence detections (>= low_thresh) fill remaining tracks

    Args:
        high_thresh: Confidence threshold for first-stage association.
        low_thresh: Confidence threshold for second-stage association.
        iou_thresh: IoU threshold for matching.
        max_age: Frames before an unmatched track is removed.
        min_hits: Minimum associations before a track is confirmed.
    """

    def __init__(
        self,
        high_thresh: float = 0.6,
        low_thresh: float = 0.1,
        iou_thresh: float = 0.3,
        max_age: int = 30,
        min_hits: int = 3,
    ) -> None:
        self.high_thresh = high_thresh
        self.low_thresh = low_thresh
        self.iou_thresh = iou_thresh
        self.max_age = max_age
        self.min_hits = min_hits
        self._tracks: list[Track] = []
        self._next_id = 1

    def update(
        self,
        detections: list[dict],
    ) -> list[dict]:
        """Process one frame of detections.

        Args:
            detections: List of dicts with keys: box ([x1,y1,x2,y2]), confidence, label.

        Returns:
            List of dicts with keys: track_id, box, confidence, label, confirmed.
        """
        # Predict existing tracks
        for track in self._tracks:
            track.predict()

        if not detections:
            self._tracks = [t for t in self._tracks if t.time_since_update <= self.max_age]
            return self._format_output()

        # Split detections by confidence
        det_boxes = np.array([d["box"] for d in detections])
        det_confs = np.array([d.get("confidence", 0.0) for d in detections])
        det_labels = [d.get("label", "") for d in detections]

        high_mask = det_confs >= self.high_thresh
        low_mask = (det_confs >= self.low_thresh) & ~high_mask

        high_indices = np.where(high_mask)[0]
        low_indices = np.where(low_mask)[0]

        # ── Stage 1: Match high-confidence detections to tracks ──
        if len(self._tracks) > 0 and len(high_indices) > 0:
            track_boxes = np.array([t.box for t in self._tracks])
            high_boxes = det_boxes[high_indices]
            iou_matrix = _iou_batch(track_boxes, high_boxes)
            matches, unmatched_trk, unmatched_det = _linear_assignment(iou_matrix, self.iou_thresh)

            for t_idx, d_idx in matches:
                orig_d = int(high_indices[d_idx])
                self._tracks[t_idx].update(det_boxes[orig_d], det_confs[orig_d])
                self._tracks[t_idx].label = det_labels[orig_d]

            remaining_tracks = [self._tracks[i] for i in unmatched_trk]
            remaining_high_dets = [int(high_indices[i]) for i in unmatched_det]
        else:
            remaining_tracks = list(self._tracks)
            remaining_high_dets = list(high_indices)

        # ── Stage 2: Match low-confidence detections to remaining tracks ──
        if len(remaining_tracks) > 0 and len(low_indices) > 0:
            rem_boxes = np.array([t.box for t in remaining_tracks])
            low_boxes = det_boxes[low_indices]
            iou_matrix = _iou_batch(rem_boxes, low_boxes)
            matches, unmatched_trk2, _ = _linear_assignment(iou_matrix, self.iou_thresh)

            for t_idx, d_idx in matches:
                orig_d = int(low_indices[d_idx])
                remaining_tracks[t_idx].update(det_boxes[orig_d], det_confs[orig_d])
                remaining_tracks[t_idx].label = det_labels[orig_d]

            # Tracks still unmatched after both stages
            for _i in unmatched_trk2:
                pass  # Track ages naturally via predict()
        else:
            pass

        # ── Initialize new tracks from unmatched high-confidence detections ──
        for d_idx in remaining_high_dets:
            track = Track(
                track_id=self._next_id,
                box=det_boxes[d_idx].copy(),
                confidence=float(det_confs[d_idx]),
                label=det_labels[d_idx],
            )
            self._tracks.append(track)
            self._next_id += 1

        # ── Remove dead tracks ──
        self._tracks = [t for t in self._tracks if t.time_since_update <= self.max_age]

        return self._format_output()

    def _format_output(self) -> list[dict]:
        """Format confirmed tracks for downstream consumption."""
        results = []
        for t in self._tracks:
            results.append(
                {
                    "track_id": t.track_id,
                    "box": t.box.tolist(),
                    "confidence": t.confidence,
                    "label": t.label,
                    "confirmed": t.hits >= self.min_hits,
                    "age": t.age,
                }
            )
        return results

    def reset(self) -> None:
        """Clear all tracks."""
        self._tracks.clear()
        self._next_id = 1
