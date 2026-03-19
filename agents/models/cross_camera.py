"""Cross-camera trajectory stitching.

Unifies person trajectories across multiple cameras using:
1. Temporal proximity: entity disappeared from cam A, appeared on cam B within T seconds
2. Visual similarity: face embedding distance (InsightFace, already loaded)
3. Spatial consistency: camera topology (known adjacency/overlap)

Pure computation module — receives face embeddings and entity metadata,
returns merge suggestions. Does not own any models.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import numpy as np

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MergeSuggestion:
    """Suggestion to merge two entities across cameras."""

    entity_a: str  # entity_id on camera A
    entity_b: str  # entity_id on camera B
    camera_a: str
    camera_b: str
    confidence: float  # 0-1
    reason: str  # "face_match", "temporal_proximity", "both"


@dataclass
class EntityAppearance:
    """Track appearance/disappearance events for cross-camera matching."""

    entity_id: str
    camera: str
    label: str
    last_seen: float
    face_embedding: np.ndarray | None = None
    box: list[float] = field(default_factory=list)


# Camera adjacency graph — which cameras have overlapping FOVs
# Updated for 6-camera setup (3 Brio + 3 C920)
DEFAULT_ADJACENCY: dict[str, list[str]] = {
    "brio-operator": ["c920-hardware", "brio-room"],
    "brio-room": ["brio-operator", "c920-room", "brio-aux"],
    "brio-aux": ["brio-room", "c920-aux"],
    "c920-hardware": ["brio-operator"],
    "c920-room": ["brio-room", "c920-aux"],
    "c920-aux": ["brio-aux", "c920-room"],
}


class CrossCameraStitcher:
    """Cross-camera trajectory stitcher.

    Maintains a buffer of recently-disappeared entities and tries to
    match them with newly-appeared entities on adjacent cameras.

    Args:
        temporal_window_s: Max seconds between disappearance and reappearance.
        face_threshold: Cosine distance threshold for face embedding match.
        adjacency: Camera adjacency graph (which cameras overlap).
    """

    def __init__(
        self,
        temporal_window_s: float = 10.0,
        face_threshold: float = 0.6,
        adjacency: dict[str, list[str]] | None = None,
    ) -> None:
        self.temporal_window_s = temporal_window_s
        self.face_threshold = face_threshold
        self.adjacency = adjacency or DEFAULT_ADJACENCY
        # Recently disappeared entities (candidates for stitching)
        self._disappeared: list[EntityAppearance] = []
        # Recently appeared entities (new on their camera)
        self._appeared: list[EntityAppearance] = []
        self._merge_history: list[MergeSuggestion] = []

    def report_disappeared(
        self,
        entity_id: str,
        camera: str,
        label: str,
        face_embedding: np.ndarray | None = None,
    ) -> None:
        """Report that an entity disappeared from a camera."""
        self._disappeared.append(
            EntityAppearance(
                entity_id=entity_id,
                camera=camera,
                label=label,
                last_seen=time.time(),
                face_embedding=face_embedding,
            )
        )
        # Prune old entries
        cutoff = time.time() - self.temporal_window_s * 2
        self._disappeared = [e for e in self._disappeared if e.last_seen > cutoff]

    def report_appeared(
        self,
        entity_id: str,
        camera: str,
        label: str,
        face_embedding: np.ndarray | None = None,
    ) -> list[MergeSuggestion]:
        """Report that a new entity appeared on a camera. Returns merge suggestions."""
        now = time.time()
        suggestions: list[MergeSuggestion] = []

        for dis in self._disappeared:
            # Must be same class (person→person)
            if dis.label != label:
                continue

            # Must be on adjacent camera
            adjacent = self.adjacency.get(dis.camera, [])
            if camera not in adjacent:
                continue

            # Temporal proximity check
            dt = now - dis.last_seen
            if dt > self.temporal_window_s:
                continue

            # Compute confidence
            temporal_score = max(0.0, 1.0 - dt / self.temporal_window_s)
            face_score = 0.0

            if face_embedding is not None and dis.face_embedding is not None:
                # Cosine similarity
                sim = float(
                    np.dot(face_embedding, dis.face_embedding)
                    / (np.linalg.norm(face_embedding) * np.linalg.norm(dis.face_embedding) + 1e-8)
                )
                if sim >= self.face_threshold:
                    face_score = sim

            if face_score > 0:
                confidence = 0.4 * temporal_score + 0.6 * face_score
                reason = "both"
            elif temporal_score > 0.5:
                confidence = temporal_score * 0.6
                reason = "temporal_proximity"
            else:
                continue

            suggestions.append(
                MergeSuggestion(
                    entity_a=dis.entity_id,
                    entity_b=entity_id,
                    camera_a=dis.camera,
                    camera_b=camera,
                    confidence=round(confidence, 3),
                    reason=reason,
                )
            )

        # Sort by confidence, return best suggestions
        suggestions.sort(key=lambda s: s.confidence, reverse=True)
        if suggestions:
            self._merge_history.extend(suggestions[:1])
        return suggestions

    @property
    def recent_merges(self) -> list[MergeSuggestion]:
        """Return recent merge history."""
        return self._merge_history[-20:]

    def reset(self) -> None:
        """Clear all state."""
        self._disappeared.clear()
        self._appeared.clear()
        self._merge_history.clear()
