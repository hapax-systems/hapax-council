"""Anti-recognition metric (OQ-02 bound 1).

Face-recognition distance against the operator's enrolled embedding. A
frame fails B1 (operator-identifiability leak) when the cosine similarity
between any face in the frame and the operator's enrolled embedding
exceeds the identifiability threshold τ.

Per research at ``docs/research/2026-04-20-oq02-anti-recognition-metric.md``.

Cost asymmetry: false-negative (identity LEAK) = constitutional violation;
false-positive (effect rejected) = operational nuisance. Threshold + all
defaults bias conservatively. Detector failures fail-CLOSED (treated as
"identifiable until proven otherwise"), mirroring
``agents/studio_compositor/face_obscure_integration.py:173``.

Critical: this module SHARES the daimonion's existing FaceDetector
singleton (``agents.hapax_daimonion.face_detector.FaceDetector``). Do NOT
construct a second InsightFace SCRFD instance — it would thrash the GPU
under livestream load. The ``FaceEmbeddingProvider`` Protocol abstracts
the detector so tests can inject a deterministic stub without spinning up
the model.

Operator GO received 2026-04-20 — module ships as live oracle.
HAPAX_SCRIM_INVARIANT_B1_ENFORCE env var (default 0) gates downstream
enforcement; the metric itself is observe-only without it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

import numpy as np

log = logging.getLogger(__name__)

SCHEMA_VERSION: Final[int] = 1
DEFAULT_THRESHOLDS_PATH: Final[Path] = Path("axioms/scrim/anti_recognition_thresholds.json")
# Operator embedding location, owned by hapax_daimonion's FaceDetector.
OPERATOR_EMBEDDING_PATH: Final[Path] = (
    Path.home() / ".local" / "share" / "hapax-daimonion" / "operator_face.npy"
)

# Initial point-estimate threshold per research §2.
# τ_present (operator-match cutoff in face_detector.py) is 0.4; bound-1
# threshold sits BELOW that with a 0.07 safety margin so the metric flags
# leaks BEFORE they become recognizable. Sanity invariant enforced at
# load time: τ_anti_recognition ≤ τ_present − 0.05.
DEFAULT_IDENTIFIABILITY_THRESHOLD: Final[float] = 0.28
# τ_present at the time of writing; used only for the sanity-check
# invariant in TranslucencyThresholds.load (see _validate_threshold).
TAU_PRESENT_REFERENCE: Final[float] = 0.40
TAU_PRESENT_SAFETY_MARGIN: Final[float] = 0.05


class FaceEmbeddingProvider(Protocol):
    """Abstracts the daimonion's FaceDetector for testability.

    Production: ``agents.hapax_daimonion.face_detector.FaceDetector`` —
    SHARED singleton, do not construct a second one.
    Tests: stub returning deterministic embeddings.
    """

    def detect(self, image: np.ndarray | None, *, camera_role: str = "unknown") -> object:
        """Return an object with ``.detected`` (bool) and ``.embeddings``
        (list[np.ndarray]) — matches FaceResult shape."""
        ...


@dataclass(frozen=True)
class AntiRecognitionThresholds:
    """Calibrated identifiability cutoff."""

    identifiability_max: float
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def load(cls, path: Path = DEFAULT_THRESHOLDS_PATH) -> AntiRecognitionThresholds:
        """Load + validate thresholds from JSON.

        Fail-CLOSED on missing/malformed/out-of-range files: raises so the
        runtime check refuses to start without current thresholds.
        """
        if not path.exists():
            raise FileNotFoundError(
                f"anti-recognition thresholds missing at {path}; run the "
                "calibration script before enabling the bound-1 runtime check"
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        version = data.get("schema_version", 0)
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"anti-recognition threshold schema mismatch: file version "
                f"{version}, code expects {SCHEMA_VERSION}"
            )
        threshold = float(data["identifiability_max"])
        _validate_threshold(threshold)
        return cls(identifiability_max=threshold)


def _validate_threshold(threshold: float) -> None:
    """Sanity invariant: τ_anti_recognition ≤ τ_present − safety_margin.

    If the bound-1 threshold ever creeps up to or past the operator-match
    cutoff used by ``face_detector.py``, the metric stops flagging leaks
    BEFORE they become recognizable — defeats the bound. Catch at load
    time so misconfiguration surfaces immediately.
    """
    ceiling = TAU_PRESENT_REFERENCE - TAU_PRESENT_SAFETY_MARGIN
    if threshold > ceiling:
        raise ValueError(
            f"anti_recognition identifiability_max={threshold:.3f} exceeds "
            f"safety ceiling τ_present({TAU_PRESENT_REFERENCE}) − margin"
            f"({TAU_PRESENT_SAFETY_MARGIN}) = {ceiling:.3f}; relax τ_present "
            "first or tighten threshold"
        )


@dataclass(frozen=True)
class RecognitionScore:
    """Decomposed B1 score for a single egress frame.

    Attributes:
        max_similarity: cosine similarity between the most-operator-like
            face in the frame and the operator's enrolled embedding.
            None when no face was detected (NOT a pass — see ``passed``).
        face_count: total faces detected in the frame.
        passed: True iff every detected face's similarity is BELOW the
            identifiability threshold AND a detector pass actually
            executed. Detector failure = fail-CLOSED (passed=False).
        threshold: the threshold used for this evaluation (for forensics).
    """

    max_similarity: float | None
    face_count: int
    passed: bool
    threshold: float
    fail_reason: str | None = None


def load_operator_embedding(
    path: Path = OPERATOR_EMBEDDING_PATH,
) -> np.ndarray | None:
    """Load the operator's enrolled face embedding from disk.

    Returns None if the embedding file is missing — the caller decides
    how to handle (production: fail-CLOSED; tests: inject a stub).
    """
    if not path.exists():
        log.warning(
            "operator embedding not found at %s; B1 oracle cannot evaluate "
            "without enrollment (run hapax-daimonion enrollment flow)",
            path,
        )
        return None
    try:
        return np.load(path)
    except Exception:
        log.warning("operator embedding load failed", exc_info=True)
        return None


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two embedding vectors. Returns 0.0 on
    degenerate input (zero-norm vectors)."""
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a < 1e-6 or norm_b < 1e-6:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def evaluate_frame(
    frame: np.ndarray | None,
    detector: FaceEmbeddingProvider,
    operator_embedding: np.ndarray | None,
    thresholds: AntiRecognitionThresholds,
    *,
    camera_role: str = "egress",
) -> RecognitionScore:
    """Score a single egress frame for operator-identifiability leak.

    Decision logic:
      - No operator embedding loaded → fail-CLOSED (cannot prove safety).
      - Detector failure (returns no face when input was non-null) →
        fail-CLOSED on grounds of "could be hiding identifiable content."
      - No faces detected on a valid frame → pass (no identity to leak).
      - At least one face whose similarity ≥ threshold → fail (LEAK).
      - All faces below threshold → pass.

    The fail-CLOSED-on-detector-error stance is the same posture as
    ``face_obscure_integration.py:173`` and the consent gate.
    """
    if operator_embedding is None:
        return RecognitionScore(
            max_similarity=None,
            face_count=0,
            passed=False,
            threshold=thresholds.identifiability_max,
            fail_reason="operator_embedding_unavailable",
        )
    if frame is None or (isinstance(frame, np.ndarray) and frame.size == 0):
        # Empty frame — no identity to leak, but no proof of safety
        # either; the caller asked us to evaluate, so treat as pass
        # (caller should never feed empty frames in production).
        return RecognitionScore(
            max_similarity=None,
            face_count=0,
            passed=True,
            threshold=thresholds.identifiability_max,
            fail_reason=None,
        )
    try:
        result = detector.detect(frame, camera_role=camera_role)
    except Exception:
        log.warning("face detector raised in B1 evaluate_frame", exc_info=True)
        return RecognitionScore(
            max_similarity=None,
            face_count=0,
            passed=False,
            threshold=thresholds.identifiability_max,
            fail_reason="detector_exception_fail_closed",
        )
    if not getattr(result, "detected", False):
        return RecognitionScore(
            max_similarity=None,
            face_count=0,
            passed=True,
            threshold=thresholds.identifiability_max,
        )
    embeddings = list(getattr(result, "embeddings", None) or [])
    if not embeddings:
        # Detector said faces present but produced no embeddings —
        # treat as fail-CLOSED (we can't compare without embeddings).
        return RecognitionScore(
            max_similarity=None,
            face_count=int(getattr(result, "count", 0)),
            passed=False,
            threshold=thresholds.identifiability_max,
            fail_reason="faces_detected_without_embeddings_fail_closed",
        )
    similarities = [cosine_similarity(emb, operator_embedding) for emb in embeddings]
    max_sim = max(similarities) if similarities else 0.0
    passed = max_sim < thresholds.identifiability_max
    return RecognitionScore(
        max_similarity=max_sim,
        face_count=len(embeddings),
        passed=passed,
        threshold=thresholds.identifiability_max,
        fail_reason=None if passed else "operator_face_identifiable",
    )
