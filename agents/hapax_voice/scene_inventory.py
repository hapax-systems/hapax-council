"""Persistent scene inventory — track objects across cameras and time.

Maintains a unified inventory of all objects detected across all cameras,
with cross-camera matching, mobility classification, and persistence to disk.
Thread-safe for concurrent access from the vision inference loop.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_SIGHTING_RING_SIZE = 10
_SNAPSHOT_MAX_OBJECTS = 50

# GC expiry times (seconds)
_STATIC_EXPIRY = 24 * 3600  # 24h
_DYNAMIC_EXPIRY = 30 * 60  # 30min
_UNKNOWN_EXPIRY = 10 * 60  # 10min


@dataclass
class SceneObject:
    """A tracked object in the scene inventory."""

    entity_id: str
    label: str
    last_camera: str
    last_box: list[float]  # [x1, y1, x2, y2]
    last_confidence: float
    first_seen: float
    last_seen: float
    seen_count: int
    mobility: str  # "static" | "dynamic" | "unknown"
    mobility_score: float  # 0.0=static, 1.0=dynamic
    sightings: list[dict] = field(default_factory=list)  # ring buffer
    camera_history: set[str] = field(default_factory=set)
    yolo_track_ids: dict[str, int] = field(default_factory=dict)  # camera -> last track_id

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON persistence."""
        return {
            "entity_id": self.entity_id,
            "label": self.label,
            "last_camera": self.last_camera,
            "last_box": self.last_box,
            "last_confidence": self.last_confidence,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "seen_count": self.seen_count,
            "mobility": self.mobility,
            "mobility_score": round(self.mobility_score, 3),
            "sightings": self.sightings[-_SIGHTING_RING_SIZE:],
            "camera_history": sorted(self.camera_history),
            "yolo_track_ids": self.yolo_track_ids,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SceneObject:
        """Deserialize from JSON."""
        return cls(
            entity_id=d["entity_id"],
            label=d["label"],
            last_camera=d["last_camera"],
            last_box=d["last_box"],
            last_confidence=d["last_confidence"],
            first_seen=d["first_seen"],
            last_seen=d["last_seen"],
            seen_count=d["seen_count"],
            mobility=d.get("mobility", "unknown"),
            mobility_score=d.get("mobility_score", 0.5),
            sightings=d.get("sightings", []),
            camera_history=set(d.get("camera_history", [])),
            yolo_track_ids=d.get("yolo_track_ids", {}),
        )


def _iou(box_a: list[float], box_b: list[float]) -> float:
    """Compute intersection-over-union between two [x1,y1,x2,y2] boxes."""
    x1 = max(box_a[0], box_b[0])
    y1 = max(box_a[1], box_b[1])
    x2 = min(box_a[2], box_b[2])
    y2 = min(box_a[3], box_b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter == 0:
        return 0.0
    area_a = (box_a[2] - box_a[0]) * (box_a[3] - box_a[1])
    area_b = (box_b[2] - box_b[0]) * (box_b[3] - box_b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


class SceneInventory:
    """Cross-camera persistent scene object inventory."""

    def __init__(self, persist_path: Path | None = None) -> None:
        self._objects: dict[str, SceneObject] = {}
        self._lock = threading.RLock()
        self._persist_path = (
            persist_path or Path.home() / ".cache" / "hapax-voice" / "scene-inventory.json"
        )
        self._persist_counter = 0
        self._load()

    def ingest(self, detections: list[dict], camera_role: str, timestamp: float) -> None:
        """Process a batch of detections from one camera tick.

        Each detection dict should have: label, confidence, box, track_id.
        """
        with self._lock:
            matched_ids: set[str] = set()

            for det in detections:
                label = det.get("label", "")
                if not label:
                    continue
                box = det.get("box", [0, 0, 0, 0])
                conf = det.get("confidence", 0.0)
                track_id = det.get("track_id")

                obj = self._match_detection(det, camera_role, matched_ids)

                if obj is not None:
                    matched_ids.add(obj.entity_id)
                    # Update existing object
                    old_box = obj.last_box if obj.last_camera == camera_role else None
                    obj.last_camera = camera_role
                    obj.last_box = box
                    obj.last_confidence = conf
                    obj.last_seen = timestamp
                    obj.seen_count += 1
                    obj.camera_history.add(camera_role)
                    if track_id is not None:
                        obj.yolo_track_ids[camera_role] = track_id

                    # Update mobility score based on position change
                    if old_box is not None:
                        iou_val = _iou(old_box, box)
                        # Low IoU = moved a lot = more dynamic
                        movement = 1.0 - iou_val
                        # Exponential moving average
                        obj.mobility_score = 0.8 * obj.mobility_score + 0.2 * movement
                    # Classify mobility
                    if obj.seen_count >= 5:
                        if obj.mobility_score < 0.15:
                            obj.mobility = "static"
                        elif obj.mobility_score > 0.4:
                            obj.mobility = "dynamic"

                    # Ring buffer sighting
                    obj.sightings.append(
                        {
                            "camera": camera_role,
                            "box": box,
                            "conf": round(conf, 3),
                            "ts": timestamp,
                        }
                    )
                    if len(obj.sightings) > _SIGHTING_RING_SIZE:
                        obj.sightings = obj.sightings[-_SIGHTING_RING_SIZE:]
                else:
                    # Create new object
                    eid = str(uuid.uuid4())[:12]
                    new_obj = SceneObject(
                        entity_id=eid,
                        label=label,
                        last_camera=camera_role,
                        last_box=box,
                        last_confidence=conf,
                        first_seen=timestamp,
                        last_seen=timestamp,
                        seen_count=1,
                        mobility="unknown",
                        mobility_score=0.5,
                        sightings=[
                            {
                                "camera": camera_role,
                                "box": box,
                                "conf": round(conf, 3),
                                "ts": timestamp,
                            }
                        ],
                        camera_history={camera_role},
                        yolo_track_ids={camera_role: track_id} if track_id is not None else {},
                    )
                    self._objects[eid] = new_obj

            self._maybe_gc(timestamp)

            # Persist periodically (every 10 ingests)
            self._persist_counter += 1
            if self._persist_counter % 10 == 0:
                self._persist()

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot for perception-state.json."""
        with self._lock:
            now = time.time()
            static_count = sum(1 for o in self._objects.values() if o.mobility == "static")
            dynamic_count = sum(1 for o in self._objects.values() if o.mobility == "dynamic")

            # Only include recent objects in snapshot, capped at max
            recent = sorted(
                self._objects.values(),
                key=lambda o: o.last_seen,
                reverse=True,
            )[:_SNAPSHOT_MAX_OBJECTS]

            objects_out = []
            for o in recent:
                age = now - o.last_seen
                objects_out.append(
                    {
                        "entity_id": o.entity_id,
                        "label": o.label,
                        "camera": o.last_camera,
                        "confidence": o.last_confidence,
                        "mobility": o.mobility,
                        "seen_count": o.seen_count,
                        "age_s": round(age, 1),
                    }
                )

            return {
                "object_count": len(self._objects),
                "static_count": static_count,
                "dynamic_count": dynamic_count,
                "objects": objects_out,
                "summary": self.summary(),
            }

    def by_label(self, label: str) -> list[SceneObject]:
        """Find all objects with a given label."""
        with self._lock:
            return [o for o in self._objects.values() if o.label == label]

    def by_camera(self, camera: str) -> list[SceneObject]:
        """Find all objects last seen on a given camera."""
        with self._lock:
            return [o for o in self._objects.values() if o.last_camera == camera]

    def recent(self, seconds: float = 300) -> list[SceneObject]:
        """Objects seen within the last N seconds."""
        with self._lock:
            cutoff = time.time() - seconds
            return [o for o in self._objects.values() if o.last_seen >= cutoff]

    def summary(self) -> str:
        """One-line summary of the inventory."""
        if not self._objects:
            return "no objects tracked"
        labels: dict[str, int] = {}
        for o in self._objects.values():
            labels[o.label] = labels.get(o.label, 0) + 1
        parts = [
            f"{count}x {label}" for label, count in sorted(labels.items(), key=lambda x: -x[1])[:8]
        ]
        return f"{len(self._objects)} objects: {', '.join(parts)}"

    def _match_detection(
        self,
        det: dict,
        camera: str,
        already_matched: set[str],
    ) -> SceneObject | None:
        """Find existing object matching this detection.

        Priority:
        1. YOLO track_id match (same camera, same track_id)
        2. IoU + label match (same camera, IoU > 0.3)
        3. Label uniqueness (cross-camera, for singleton objects like "desk")
        """
        label = det.get("label", "")
        box = det.get("box", [0, 0, 0, 0])
        track_id = det.get("track_id")

        best: SceneObject | None = None
        best_score = 0.0

        for obj in self._objects.values():
            if obj.entity_id in already_matched:
                continue
            if obj.label != label:
                continue

            score = 0.0

            # Track ID match (same camera)
            track_match = 0.0
            if (
                track_id is not None
                and camera in obj.yolo_track_ids
                and obj.yolo_track_ids[camera] == track_id
            ):
                track_match = 1.0
            score += 0.3 * track_match

            # IoU (same camera only)
            iou_val = 0.0
            if obj.last_camera == camera:
                iou_val = _iou(obj.last_box, box)
            score += 0.4 * iou_val

            # Confidence similarity
            conf_sim = 1.0 - abs(obj.last_confidence - det.get("confidence", 0))
            score += 0.2 * conf_sim

            # Recency
            age = time.time() - obj.last_seen
            recency = max(0.0, 1.0 - age / 60.0)  # decay over 60s
            score += 0.1 * recency

            if score > best_score:
                best_score = score
                best = obj

        # Require minimum score for match
        if best is not None and best_score >= 0.25:
            return best

        # Fallback: singleton label match (cross-camera, for unique objects)
        same_label = [
            o
            for o in self._objects.values()
            if o.label == label and o.entity_id not in already_matched
        ]
        if len(same_label) == 1:
            return same_label[0]

        return None

    def _maybe_gc(self, now: float) -> None:
        """Expire old objects based on mobility classification."""
        to_remove: list[str] = []
        for eid, obj in self._objects.items():
            age = now - obj.last_seen
            if (
                (obj.mobility == "static" and age > _STATIC_EXPIRY)
                or (obj.mobility == "dynamic" and age > _DYNAMIC_EXPIRY)
                or (obj.mobility == "unknown" and age > _UNKNOWN_EXPIRY)
            ):
                to_remove.append(eid)
        for eid in to_remove:
            del self._objects[eid]
        if to_remove:
            log.debug("Scene inventory GC: removed %d expired objects", len(to_remove))

    def _persist(self) -> None:
        """Save inventory to disk."""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "version": 1,
                "saved_at": time.time(),
                "objects": [o.to_dict() for o in self._objects.values()],
            }
            tmp = self._persist_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.rename(self._persist_path)
        except OSError:
            log.debug("Failed to persist scene inventory", exc_info=True)

    def _load(self) -> None:
        """Load inventory from disk on startup."""
        try:
            if not self._persist_path.exists():
                return
            raw = json.loads(self._persist_path.read_text(encoding="utf-8"))
            if raw.get("version") != 1:
                return
            now = time.time()
            for obj_dict in raw.get("objects", []):
                try:
                    obj = SceneObject.from_dict(obj_dict)
                    # Skip very stale objects on load
                    if now - obj.last_seen > _STATIC_EXPIRY:
                        continue
                    self._objects[obj.entity_id] = obj
                except (KeyError, TypeError, ValueError):
                    continue
            log.info("Scene inventory loaded: %d objects from disk", len(self._objects))
        except (OSError, json.JSONDecodeError):
            log.debug("Failed to load scene inventory", exc_info=True)
