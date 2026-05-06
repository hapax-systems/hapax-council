"""CBIP recognizability test harness — the gate every enhancement crosses.

Spec §4 of `docs/superpowers/specs/2026-04-21-cbip-phase-1-design.md`.

Each enhancement family (Family 1 = Palette Lineage; Family 2 = Poster Print;
Family 3 = Contour Forward; Family 4 = Dither & Degradation; Family 5 = Glitch
Burst) is a function ``original RGBA → enhanced RGBA``. This harness measures
six invariants of the (original, enhanced) pair:

* **OCR title round-trip** (INVARIANT) — Tesseract on the title region;
  ≥90 % character-level accuracy of the original title text.
* **Perceptual-hash distance** (INVARIANT) — `imagehash.phash` 64-bit Hamming
  distance ≤ 8 bits (~16 % drift).
* **Palette delta-E (CIELAB)** (QUALITY) — K-means K=8 dominant colors;
  pairwise CIE2000 distance, mean ≤ 40 units per matched pair.
* **Edge IoU (Sobel σ=1)** (QUALITY) — Jaccard over thresholded Sobel edges;
  ≥ 0.65 for geometric objects, ≥ 0.50 for abstract objects.
* **CLIP cosine** (QUALITY) — vision-language similarity between original
  and enhanced; ≥ 0.75. Optional (CLIP model load is heavy); skipped if the
  caller does not provide a CLIP scorer.
* **Human-ID rate** (INVARIANT, operator-run) — ≥ 80 % identification across
  a canonical object panel × 3 intensity levels. Not callable from automation;
  the harness records the value when the operator submits it.

INVARIANT failures block ship; QUALITY failures warn but do not block. The
harness returns a structured ``HarnessResult`` so CI gates can act on
``invariants_passed`` while observability dashboards consume the full
metric set.

Pure logic + boundary I/O: no GPU, no LLM, no network. Caller supplies the
images as ``PIL.Image.Image`` instances.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

log = logging.getLogger(__name__)

# ── Thresholds (spec §4) ─────────────────────────────────────────────────

OCR_MIN_CHAR_ACCURACY = 0.90
PHASH_MAX_HAMMING_BITS = 8
PALETTE_MAX_DELTA_E = 40.0
EDGE_IOU_GEOMETRIC_MIN = 0.65
EDGE_IOU_ABSTRACT_MIN = 0.50
CLIP_MIN_COSINE = 0.75
HUMAN_ID_MIN_RATE = 0.80


class Severity(StrEnum):
    """Two enforcement tiers per spec §4."""

    INVARIANT = "invariant"  # blocks ship
    QUALITY = "quality"  # warns, does not block


class CoverShape(StrEnum):
    """Recognizability bound depends on object topology (spec §4)."""

    GEOMETRIC = "geometric"  # ≥0.65 edge IoU required
    ABSTRACT = "abstract"  # ≥0.50 edge IoU required


ObjectShape = CoverShape


@dataclass(frozen=True)
class MetricResult:
    """One metric reading + threshold + severity."""

    name: str
    value: float | None
    threshold: float
    passed: bool
    severity: Severity
    detail: str = ""


@dataclass(frozen=True)
class HarnessResult:
    """Aggregate result over the full recognizability suite."""

    metrics: tuple[MetricResult, ...]
    cover_shape: CoverShape

    @property
    def invariants_passed(self) -> bool:
        return all(m.passed for m in self.metrics if m.severity is Severity.INVARIANT)

    @property
    def all_passed(self) -> bool:
        return all(m.passed for m in self.metrics)

    @property
    def failures(self) -> tuple[MetricResult, ...]:
        return tuple(m for m in self.metrics if not m.passed)


class ClipScorer(Protocol):
    """Optional CLIP cosine scorer.

    Implementations load a CLIP model and return cosine similarity in
    ``[-1.0, 1.0]`` between two images. Decoupled from the harness so the
    test suite can run without CLIP installed.
    """

    def __call__(self, original: Any, enhanced: Any) -> float: ...


# ── Individual metrics ───────────────────────────────────────────────────


def ocr_character_accuracy(
    enhanced: Any,
    *,
    expected_title: str,
    title_region: tuple[int, int, int, int] | None = None,
) -> float:
    """Tesseract OCR on the title region; return char-level accuracy.

    ``title_region`` is ``(left, upper, right, lower)``; if None the whole
    image is read.
    """
    import pytesseract

    region = enhanced.crop(title_region) if title_region else enhanced
    extracted = pytesseract.image_to_string(region, config="--psm 7").strip()
    return _character_accuracy(extracted, expected_title)


def perceptual_hash_distance(original: Any, enhanced: Any) -> int:
    """64-bit pHash Hamming distance between original and enhanced."""
    import imagehash

    return int(imagehash.phash(original) - imagehash.phash(enhanced))


def palette_delta_e(original: Any, enhanced: Any, *, k: int = 8) -> float:
    """Mean CIE2000 distance between K-means palettes of the two images."""
    import numpy as np
    from skimage import color

    palette_orig = _kmeans_palette_lab(np.asarray(original.convert("RGB")), k)
    palette_enh = _kmeans_palette_lab(np.asarray(enhanced.convert("RGB")), k)

    distances = []
    for lab_orig in palette_orig:
        deltas = [color.deltaE_ciede2000(lab_orig, lab_enh) for lab_enh in palette_enh]
        distances.append(min(deltas))
    return float(np.mean(distances))


def edge_iou_sobel(original: Any, enhanced: Any, *, sigma: float = 1.0) -> float:
    """Jaccard over Sobel edges (binarized at the per-image median)."""
    import numpy as np
    from skimage import filters
    from skimage.color import rgb2gray

    gray_orig = rgb2gray(np.asarray(original.convert("RGB")) / 255.0)
    gray_enh = rgb2gray(np.asarray(enhanced.convert("RGB")) / 255.0)

    edges_orig = filters.sobel(filters.gaussian(gray_orig, sigma=sigma))
    edges_enh = filters.sobel(filters.gaussian(gray_enh, sigma=sigma))

    bin_orig = edges_orig > np.median(edges_orig)
    bin_enh = edges_enh > np.median(edges_enh)

    intersection = int(np.logical_and(bin_orig, bin_enh).sum())
    union = int(np.logical_or(bin_orig, bin_enh).sum())
    if union == 0:
        return 1.0  # degenerate empty edges; treat as identical
    return intersection / union


# ── Aggregation ──────────────────────────────────────────────────────────


def evaluate(
    original: Any,
    enhanced: Any,
    *,
    expected_title: str | None = None,
    title_region: tuple[int, int, int, int] | None = None,
    cover_shape: CoverShape = CoverShape.GEOMETRIC,
    clip_scorer: ClipScorer | None = None,
    human_id_rate: float | None = None,
) -> HarnessResult:
    """Run the full recognizability suite and return a HarnessResult.

    ``expected_title`` is required to score OCR; if None the OCR metric
    is recorded as ``passed=True, value=None`` and skipped.
    ``clip_scorer`` is optional — without it, CLIP cosine is skipped.
    ``human_id_rate`` is operator-supplied; pass the most recent panel
    measurement (or None to skip).
    """
    metrics: list[MetricResult] = []

    # OCR
    if expected_title is not None:
        try:
            accuracy = ocr_character_accuracy(
                enhanced, expected_title=expected_title, title_region=title_region
            )
            metrics.append(
                MetricResult(
                    name="ocr_title_accuracy",
                    value=accuracy,
                    threshold=OCR_MIN_CHAR_ACCURACY,
                    passed=accuracy >= OCR_MIN_CHAR_ACCURACY,
                    severity=Severity.INVARIANT,
                )
            )
        except Exception as e:
            metrics.append(
                MetricResult(
                    name="ocr_title_accuracy",
                    value=None,
                    threshold=OCR_MIN_CHAR_ACCURACY,
                    passed=False,
                    severity=Severity.INVARIANT,
                    detail=f"OCR raised {type(e).__name__}: {e}",
                )
            )

    # Perceptual hash
    try:
        bits = perceptual_hash_distance(original, enhanced)
        metrics.append(
            MetricResult(
                name="perceptual_hash_distance",
                value=float(bits),
                threshold=float(PHASH_MAX_HAMMING_BITS),
                passed=bits <= PHASH_MAX_HAMMING_BITS,
                severity=Severity.INVARIANT,
            )
        )
    except Exception as e:
        metrics.append(
            MetricResult(
                name="perceptual_hash_distance",
                value=None,
                threshold=float(PHASH_MAX_HAMMING_BITS),
                passed=False,
                severity=Severity.INVARIANT,
                detail=f"phash raised {type(e).__name__}: {e}",
            )
        )

    # Palette delta-E (quality)
    try:
        delta = palette_delta_e(original, enhanced)
        metrics.append(
            MetricResult(
                name="palette_delta_e",
                value=delta,
                threshold=PALETTE_MAX_DELTA_E,
                passed=delta <= PALETTE_MAX_DELTA_E,
                severity=Severity.QUALITY,
            )
        )
    except Exception as e:
        metrics.append(
            MetricResult(
                name="palette_delta_e",
                value=None,
                threshold=PALETTE_MAX_DELTA_E,
                passed=True,  # quality only — don't fail if scorer broke
                severity=Severity.QUALITY,
                detail=f"delta-E raised {type(e).__name__}: {e}",
            )
        )

    # Edge IoU (quality)
    try:
        iou = edge_iou_sobel(original, enhanced)
        threshold = (
            EDGE_IOU_GEOMETRIC_MIN if cover_shape is CoverShape.GEOMETRIC else EDGE_IOU_ABSTRACT_MIN
        )
        metrics.append(
            MetricResult(
                name=f"edge_iou_sobel_{cover_shape.value}",
                value=iou,
                threshold=threshold,
                passed=iou >= threshold,
                severity=Severity.QUALITY,
            )
        )
    except Exception as e:
        metrics.append(
            MetricResult(
                name="edge_iou_sobel",
                value=None,
                threshold=EDGE_IOU_GEOMETRIC_MIN,
                passed=True,
                severity=Severity.QUALITY,
                detail=f"Sobel IoU raised {type(e).__name__}: {e}",
            )
        )

    # CLIP cosine (quality, optional)
    if clip_scorer is not None:
        try:
            cosine = float(clip_scorer(original, enhanced))
            metrics.append(
                MetricResult(
                    name="clip_cosine",
                    value=cosine,
                    threshold=CLIP_MIN_COSINE,
                    passed=cosine >= CLIP_MIN_COSINE,
                    severity=Severity.QUALITY,
                )
            )
        except Exception as e:
            metrics.append(
                MetricResult(
                    name="clip_cosine",
                    value=None,
                    threshold=CLIP_MIN_COSINE,
                    passed=True,
                    severity=Severity.QUALITY,
                    detail=f"CLIP raised {type(e).__name__}: {e}",
                )
            )

    # Human ID rate (invariant, operator-supplied)
    if human_id_rate is not None:
        metrics.append(
            MetricResult(
                name="human_identification_rate",
                value=human_id_rate,
                threshold=HUMAN_ID_MIN_RATE,
                passed=human_id_rate >= HUMAN_ID_MIN_RATE,
                severity=Severity.INVARIANT,
                detail="operator-supplied panel measurement",
            )
        )

    return HarnessResult(metrics=tuple(metrics), cover_shape=cover_shape)


# ── Helpers ──────────────────────────────────────────────────────────────


def _character_accuracy(observed: str, expected: str) -> float:
    """Char-level accuracy via Levenshtein-normalized similarity.

    Empty expected → 1.0 (degenerate case). Empty observed but non-empty
    expected → 0.0.
    """
    if not expected:
        return 1.0
    if not observed:
        return 0.0
    distance = _levenshtein(observed.lower(), expected.lower())
    longest = max(len(observed), len(expected))
    return max(0.0, 1.0 - distance / longest)


def _levenshtein(a: str, b: str) -> int:
    """Standard DP Levenshtein. O(len(a) * len(b)) time + space."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


def _kmeans_palette_lab(rgb_array: Any, k: int) -> Any:
    """K-means in CIELAB space; return K cluster centers as Lab vectors."""
    import numpy as np
    from skimage import color
    from sklearn.cluster import KMeans

    h, w, _ = rgb_array.shape
    pixels = rgb_array.reshape(-1, 3) / 255.0
    lab = color.rgb2lab(pixels.reshape(1, -1, 3)).reshape(-1, 3)
    # Subsample for performance — K-means quality unaffected at 50k samples.
    if lab.shape[0] > 50_000:
        rng = np.random.default_rng(0)
        idx = rng.choice(lab.shape[0], size=50_000, replace=False)
        lab = lab[idx]
    km = KMeans(n_clusters=k, n_init=4, random_state=0)
    km.fit(lab)
    return km.cluster_centers_


__all__ = [
    "CLIP_MIN_COSINE",
    "EDGE_IOU_ABSTRACT_MIN",
    "EDGE_IOU_GEOMETRIC_MIN",
    "HUMAN_ID_MIN_RATE",
    "OCR_MIN_CHAR_ACCURACY",
    "PALETTE_MAX_DELTA_E",
    "PHASH_MAX_HAMMING_BITS",
    "ClipScorer",
    "CoverShape",
    "HarnessResult",
    "MetricResult",
    "Severity",
    "edge_iou_sobel",
    "evaluate",
    "ocr_character_accuracy",
    "palette_delta_e",
    "perceptual_hash_distance",
]
