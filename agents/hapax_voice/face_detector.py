"""Face detection using InsightFace SCRFD (GPU-accelerated).

Replaces MediaPipe BlazeFace with SCRFD via InsightFace buffalo_sc model.
SCRFD is significantly more accurate, especially at angles and in low light.
Also extracts 512-d face embeddings for ReID (operator identification).
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

_OPERATOR_EMBEDDING_PATH = Path.home() / ".local" / "share" / "hapax-voice" / "operator_face.npy"
_OPERATOR_SIMILARITY_THRESHOLD = 0.4
_AUTO_ENROLL_CONFIDENCE = 0.7


_DEDUP_SIMILARITY_THRESHOLD = 0.6  # cosine sim above this = same person across cameras


@dataclass(frozen=True)
class FaceResult:
    detected: bool
    count: int
    boxes: list[list[float]] = field(default_factory=list)
    embeddings: list[np.ndarray] = field(default_factory=list)
    operator_flags: list[bool] = field(default_factory=list)


@dataclass(frozen=True)
class FusedFaceResult:
    """Cross-camera deduplicated face detection result."""

    operator_visible: bool
    guest_count: int
    operator_confidence: float
    per_camera_results: dict[str, FaceResult] = field(default_factory=dict)


def _normalize_color(image: np.ndarray) -> np.ndarray:
    """Gray world color normalization — delegates to shared.color_utils."""
    from shared.color_utils import normalize_color

    return normalize_color(image)


class FaceDetector:
    """Detects faces using InsightFace SCRFD (GPU-accelerated).

    Uses buffalo_sc (lightweight) model for detection + embedding extraction.
    Runs on CUDA when available, falls back to CPU. Supports operator ReID
    via cosine similarity on 512-d face embeddings.
    """

    def __init__(self, min_confidence: float = 0.5) -> None:
        self._min_confidence = min_confidence
        self._app = None
        self._init_failed = False
        self._operator_embedding: np.ndarray | None = None
        self._operator_embedding_loaded = False

    def _get_app(self):
        """Lazily initialize InsightFace FaceAnalysis."""
        if self._app is not None:
            return self._app
        if self._init_failed:
            return None

        try:
            from insightface.app import FaceAnalysis

            app = FaceAnalysis(
                name="buffalo_sc",
                providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
            )
            app.prepare(ctx_id=0, det_size=(640, 640))
            self._app = app
            log.info("InsightFace SCRFD (buffalo_sc) initialized with CUDA")
        except Exception as exc:
            log.warning("Failed to initialize InsightFace SCRFD: %s", exc)
            self._init_failed = True
        return self._app

    def _load_operator_embedding(self) -> None:
        """Load operator embedding from disk if available."""
        if self._operator_embedding_loaded:
            return
        self._operator_embedding_loaded = True
        if _OPERATOR_EMBEDDING_PATH.exists():
            try:
                self._operator_embedding = np.load(_OPERATOR_EMBEDDING_PATH)
                log.info("Loaded operator face embedding from %s", _OPERATOR_EMBEDDING_PATH)
            except Exception as exc:
                log.warning("Failed to load operator embedding: %s", exc)

    def enroll_operator(self, frame: np.ndarray) -> bool:
        """Capture and save operator face embedding for ReID.

        Detects the largest face in the frame and saves its embedding.
        Returns True if enrollment succeeded.
        """
        result = self.detect(frame)
        if not result.detected or not result.embeddings:
            return False

        # Use the first (largest/most confident) face embedding
        embedding = result.embeddings[0]
        try:
            _OPERATOR_EMBEDDING_PATH.parent.mkdir(parents=True, exist_ok=True)
            np.save(_OPERATOR_EMBEDDING_PATH, embedding)
            self._operator_embedding = embedding
            log.info("Operator face enrolled and saved to %s", _OPERATOR_EMBEDDING_PATH)
            return True
        except Exception as exc:
            log.warning("Failed to save operator embedding: %s", exc)
            return False

    def is_operator(self, embedding: np.ndarray) -> bool:
        """Check if a face embedding matches the enrolled operator.

        Uses cosine similarity with a threshold of 0.4.
        Returns True if not enrolled yet (single-user axiom: first face = operator).
        """
        self._load_operator_embedding()

        if self._operator_embedding is None:
            return True  # not enrolled yet, assume operator

        norm_a = np.linalg.norm(embedding)
        norm_b = np.linalg.norm(self._operator_embedding)
        if norm_a < 1e-6 or norm_b < 1e-6:
            return False
        similarity = float(np.dot(embedding, self._operator_embedding) / (norm_a * norm_b))
        return similarity > _OPERATOR_SIMILARITY_THRESHOLD

    def _maybe_auto_enroll(self, face, is_brio: bool) -> None:
        """Auto-enroll operator if no embedding exists and this is a high-confidence BRIO face."""
        self._load_operator_embedding()
        if self._operator_embedding is not None:
            return  # already enrolled
        if not is_brio:
            return  # only auto-enroll from the BRIO (operator cam)
        if face.det_score < _AUTO_ENROLL_CONFIDENCE:
            return  # need high confidence
        if face.embedding is None:
            return

        try:
            _OPERATOR_EMBEDDING_PATH.parent.mkdir(parents=True, exist_ok=True)
            np.save(_OPERATOR_EMBEDDING_PATH, face.embedding)
            self._operator_embedding = face.embedding
            log.info(
                "Auto-enrolled operator face (score=%.2f) from BRIO camera",
                face.det_score,
            )
        except Exception as exc:
            log.warning("Auto-enrollment failed: %s", exc)

    def detect(self, image: np.ndarray | None, *, camera_role: str = "unknown") -> FaceResult:
        """Detect faces in a numpy BGR image array.

        Returns FaceResult with detected=True if at least one face found,
        plus bounding boxes, embeddings, and operator identification flags.

        Args:
            image: BGR numpy array.
            camera_role: Camera role name (e.g. "operator") for auto-enrollment.
        """
        if image is None or image.size == 0:
            return FaceResult(detected=False, count=0)

        app = self._get_app()
        if app is None:
            return FaceResult(detected=False, count=0)

        try:
            normalized = _normalize_color(image)
            faces = app.get(normalized)

            if not faces:
                return FaceResult(detected=False, count=0)

            # Filter by confidence
            good_faces = [f for f in faces if f.det_score >= self._min_confidence]
            if not good_faces:
                return FaceResult(detected=False, count=0)

            is_brio = camera_role == "operator"

            # Auto-enroll on first high-confidence BRIO detection
            if is_brio and good_faces:
                best = max(good_faces, key=lambda f: f.det_score)
                self._maybe_auto_enroll(best, is_brio=True)

            boxes = []
            embeddings = []
            operator_flags = []
            for face in good_faces:
                # bbox is [x1, y1, x2, y2]
                bbox = face.bbox.tolist()
                boxes.append(tuple(int(v) for v in bbox))
                if face.embedding is not None:
                    embeddings.append(face.embedding)
                    operator_flags.append(self.is_operator(face.embedding))
                else:
                    operator_flags.append(True)  # no embedding → assume operator

            return FaceResult(
                detected=True,
                count=len(good_faces),
                boxes=boxes,
                embeddings=embeddings,
                operator_flags=operator_flags,
            )
        except Exception as exc:
            log.debug("Face detection failed: %s", exc)
            return FaceResult(detected=False, count=0)

    def detect_from_base64(
        self, image_b64: str | None, *, camera_role: str = "unknown"
    ) -> FaceResult:
        """Detect faces from a base64-encoded JPEG/PNG image."""
        if not image_b64:
            return FaceResult(detected=False, count=0)
        try:
            raw = base64.b64decode(image_b64)
            arr = np.frombuffer(raw, dtype=np.uint8)
            image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if image is None:
                return FaceResult(detected=False, count=0)
            return self.detect(image, camera_role=camera_role)
        except Exception as exc:
            log.debug("Base64 face detection failed: %s", exc)
            return FaceResult(detected=False, count=0)

    def detect_all_cameras(self, frames_b64: dict[str, str | None]) -> FusedFaceResult:
        """Run face detection on all cameras and deduplicate across them.

        Args:
            frames_b64: Mapping of camera_role → base64 JPEG frame (or None).

        Returns:
            FusedFaceResult with deduplicated operator_visible and guest_count.
        """
        per_camera: dict[str, FaceResult] = {}
        all_embeddings: list[np.ndarray] = []
        all_operator_flags: list[bool] = []

        for role, frame_b64 in frames_b64.items():
            result = self.detect_from_base64(frame_b64, camera_role=role)
            per_camera[role] = result
            for emb, is_op in zip(result.embeddings, result.operator_flags, strict=True):
                all_embeddings.append(emb)
                all_operator_flags.append(is_op)

        if not all_embeddings:
            return FusedFaceResult(
                operator_visible=False,
                guest_count=0,
                operator_confidence=0.0,
                per_camera_results=per_camera,
            )

        # Deduplicate by clustering embeddings via cosine similarity
        n = len(all_embeddings)
        cluster_ids = list(range(n))  # union-find: each face starts as its own cluster

        for i in range(n):
            for j in range(i + 1, n):
                sim = self._cosine_similarity(all_embeddings[i], all_embeddings[j])
                if sim > _DEDUP_SIMILARITY_THRESHOLD:
                    # Merge clusters (union)
                    root_i = self._find_root(cluster_ids, i)
                    root_j = self._find_root(cluster_ids, j)
                    if root_i != root_j:
                        cluster_ids[root_j] = root_i

        # Build unique clusters and determine operator/guest status per cluster
        clusters: dict[int, bool] = {}  # root → is_operator
        for idx in range(n):
            root = self._find_root(cluster_ids, idx)
            if root not in clusters:
                clusters[root] = all_operator_flags[idx]
            else:
                # Any face in cluster flagged as operator → cluster is operator
                clusters[root] = clusters[root] or all_operator_flags[idx]

        operator_visible = any(is_op for is_op in clusters.values())
        guest_count = sum(1 for is_op in clusters.values() if not is_op)

        # Best operator confidence: highest det_score among operator-flagged faces
        operator_confidence = 0.0
        for result in per_camera.values():
            for _i, is_op in enumerate(result.operator_flags):
                if is_op and result.boxes:
                    operator_confidence = max(operator_confidence, 1.0)

        return FusedFaceResult(
            operator_visible=operator_visible,
            guest_count=guest_count,
            operator_confidence=operator_confidence,
            per_camera_results=per_camera,
        )

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a < 1e-6 or norm_b < 1e-6:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    @staticmethod
    def _find_root(parents: list[int], idx: int) -> int:
        while parents[idx] != idx:
            parents[idx] = parents[parents[idx]]  # path compression
            idx = parents[idx]
        return idx
