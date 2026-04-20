"""Scrim-translucency metric (OQ-02 bound 2).

Composite structural-content score = min(edge_density_ratio,
luminance_variance_score, entropy_floor_score). Pure, stateless, reference-
free. Per research at
``docs/research/2026-04-20-oq02-scrim-translucency-metric.md``.

The aggregate-by-min semantics encodes a conjunctive guarantee: a frame
passes B2 only if EVERY sub-metric clears its threshold. Three dimensions
of B2 failure (edge collapse, regional flat-tone, channel-entropy collapse)
each get an independent veto. This is the bound-2 sibling of the
brightness-ceiling pattern shipped in D-25 (`presets/neon.json` colorgrade
brightness ≤ 1.0).

Stateless + pure: same frame → same score. Rolling-window state lives in
``ScrimTranslucencyTracker`` (separate module).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np

SCHEMA_VERSION: Final[int] = 1
DEFAULT_THRESHOLDS_PATH: Final[Path] = Path("axioms/scrim/scrim_translucency_thresholds.json")
# Reference edge density derived from a healthy livestream frame (gear +
# inhabitants + content). Concrete value lives in the threshold file once
# calibration runs; this is the math-only fallback so unit tests can run
# without a calibration artifact.
DEFAULT_REFERENCE_EDGE_DENSITY: Final[float] = 0.08


@dataclass(frozen=True)
class TranslucencyThresholds:
    """Calibrated cutoff values per sub-metric. Loaded from JSON at startup."""

    edge_density_min: float
    luminance_variance_min: float
    entropy_floor_min: float
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def load(cls, path: Path = DEFAULT_THRESHOLDS_PATH) -> TranslucencyThresholds:
        """Load and validate calibration thresholds from disk.

        Fail-CLOSED on missing/malformed files: raises so the runtime
        check refuses to start without current thresholds. Per research
        §7 — same posture as ``shared/governance/consent.py`` consent
        contract loading.
        """
        if not path.exists():
            raise FileNotFoundError(
                f"scrim translucency thresholds missing at {path}; run "
                "the calibration script before enabling the bound-2 runtime check"
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        version = data.get("schema_version", 0)
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"scrim translucency threshold schema mismatch: file version "
                f"{version}, code expects {SCHEMA_VERSION}"
            )
        return cls(
            edge_density_min=float(data["edge_density_min"]),
            luminance_variance_min=float(data["luminance_variance_min"]),
            entropy_floor_min=float(data["entropy_floor_min"]),
        )


@dataclass(frozen=True)
class TranslucencyScore:
    """Decomposed B2 score. ``aggregate`` is min(...) of the three components."""

    edge_density_ratio: float
    luminance_variance_score: float
    entropy_floor_score: float
    aggregate: float
    passed: bool

    @property
    def failing_component(self) -> str | None:
        """Name of the lowest-scoring component when ``passed`` is False."""
        if self.passed:
            return None
        components = {
            "edge_density_ratio": self.edge_density_ratio,
            "luminance_variance_score": self.luminance_variance_score,
            "entropy_floor_score": self.entropy_floor_score,
        }
        return min(components.items(), key=lambda kv: kv[1])[0]


def _to_grayscale(frame: np.ndarray) -> np.ndarray:
    """Convert HxWx3 RGB uint8 frame to HxW float32 luminance in [0, 1]."""
    if frame.ndim == 2:
        return frame.astype(np.float32) / 255.0
    if frame.ndim != 3 or frame.shape[2] not in (3, 4):
        raise ValueError(f"expected HxWx3 or HxW frame; got shape {frame.shape}")
    rgb = frame[..., :3].astype(np.float32) / 255.0
    # Standard ITU-R BT.601 luminance weights.
    return 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]


def _sobel_edges(luma: np.ndarray) -> np.ndarray:
    """Compute Sobel-magnitude edge map without scipy (np.gradient)."""
    gy, gx = np.gradient(luma)
    return np.sqrt(gx * gx + gy * gy)


def compute_edge_density_ratio(
    frame: np.ndarray,
    reference_density: float = DEFAULT_REFERENCE_EDGE_DENSITY,
) -> float:
    """Sobel edge fraction divided by calibrated reference. Clipped to [0, 1].

    A pure-color frame yields 0.0 (no edges); a healthy "studio with gear"
    frame sits near 1.0 by construction; a noise-saturated frame would
    exceed 1.0 but we clip there (high-edge-density is not a B2 failure).
    """
    if reference_density <= 0:
        raise ValueError(f"reference_density must be > 0; got {reference_density}")
    luma = _to_grayscale(frame)
    edges = _sobel_edges(luma)
    # "Edge present" = magnitude > 0.05 in [0, 1] luminance space (modest
    # threshold so faint texture still counts).
    edge_fraction = float((edges > 0.05).mean())
    ratio = edge_fraction / reference_density
    return float(min(1.0, max(0.0, ratio)))


def compute_luminance_variance_score(
    frame: np.ndarray,
    grid: tuple[int, int] = (4, 4),
) -> float:
    """Per-cell luminance variance, normalized, then *minimum* across cells.

    Returns the variance of the worst (lowest-variance) grid cell. Catches
    regional collapse: bright saturation in one corner, dark crush in
    another, single-hue field across the bottom third — any of these drops
    the score even if other regions are busy.

    Normalization: luminance variance is bounded by 0.25 (the variance of
    a uniformly-distributed 0/1 signal); we divide by 0.25 so the score
    sits in [0, 1].
    """
    rows, cols = grid
    if rows < 1 or cols < 1:
        raise ValueError(f"grid must have positive dimensions; got {grid}")
    luma = _to_grayscale(frame)
    h, w = luma.shape
    cell_h, cell_w = h // rows, w // cols
    if cell_h < 2 or cell_w < 2:
        # Frame too small for the requested grid — fallback to whole-frame variance.
        return float(min(1.0, luma.var() / 0.25))
    min_var = math.inf
    for r in range(rows):
        for c in range(cols):
            cell = luma[r * cell_h : (r + 1) * cell_h, c * cell_w : (c + 1) * cell_w]
            v = float(cell.var())
            if v < min_var:
                min_var = v
    if not math.isfinite(min_var):
        return 0.0
    return float(min(1.0, max(0.0, min_var / 0.25)))


def compute_entropy_floor_score(
    frame: np.ndarray,
    bins: int = 64,
) -> float:
    """Shannon entropy of each RGB channel histogram, normalized, then min.

    A frame whose blue channel has collapsed to a single value yields
    entropy_blue ≈ 0 → score ≈ 0, regardless of how busy R and G are.
    Catches per-channel collapse (e.g. material→single-hue field).

    Normalization: Shannon entropy is bounded by log2(bins) for a discrete
    histogram with ``bins`` bins; we divide by that ceiling so the score
    sits in [0, 1].
    """
    if frame.ndim != 3 or frame.shape[2] not in (3, 4):
        # Single-channel frame: just compute one entropy.
        flat = frame.reshape(-1)
        hist, _ = np.histogram(flat, bins=bins, range=(0, 256))
        return _normalized_entropy(hist, bins)
    channel_scores: list[float] = []
    for c in range(3):
        flat = frame[..., c].reshape(-1)
        hist, _ = np.histogram(flat, bins=bins, range=(0, 256))
        channel_scores.append(_normalized_entropy(hist, bins))
    return float(min(channel_scores))


def _normalized_entropy(hist: np.ndarray, bins: int) -> float:
    """Shannon entropy of ``hist`` divided by log2(bins). Returns 0 on empty."""
    total = float(hist.sum())
    if total <= 0:
        return 0.0
    p = hist.astype(np.float64) / total
    nonzero = p[p > 0]
    if nonzero.size == 0:
        return 0.0
    entropy = float(-(nonzero * np.log2(nonzero)).sum())
    ceiling = math.log2(bins) if bins > 1 else 1.0
    return float(min(1.0, max(0.0, entropy / ceiling)))


def evaluate(
    frame: np.ndarray,
    thresholds: TranslucencyThresholds,
    *,
    reference_edge_density: float = DEFAULT_REFERENCE_EDGE_DENSITY,
) -> TranslucencyScore:
    """Score a single egress frame against the calibrated thresholds.

    Aggregate is min(edge_density_ratio, luminance_variance_score,
    entropy_floor_score) — every sub-metric must independently clear its
    cutoff for ``passed`` to be True. Conjunctive guarantee per research §1.
    """
    edge = compute_edge_density_ratio(frame, reference_edge_density)
    var_score = compute_luminance_variance_score(frame)
    entropy = compute_entropy_floor_score(frame)
    aggregate = min(edge, var_score, entropy)
    passed = (
        edge >= thresholds.edge_density_min
        and var_score >= thresholds.luminance_variance_min
        and entropy >= thresholds.entropy_floor_min
    )
    return TranslucencyScore(
        edge_density_ratio=edge,
        luminance_variance_score=var_score,
        entropy_floor_score=entropy,
        aggregate=aggregate,
        passed=passed,
    )
