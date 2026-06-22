"""AVSDLC visual-eval — realized per-region perceptual vector (PR 4a).

Computes the REALIZED ``{luma, edge_energy}`` vector per AESTHETIC region from a
captured frame, so the independent runtime-witness can confirm a pre-authored
``VisualIntentRecord`` (``shared.avsdlc_visual_intent.intent_pass``) against what
ACTUALLY rendered — the "confirm" half of predict-then-confirm.

Pure + numpy-only. What this module does NOT do (later slices):
- read live frames from /dev/video52 / OBS and emit the vector into the witness
  manifest + receipt (witness producer wiring);
- wire ``intent_pass`` into the release gate (overall PASS = floors AND intent_pass).

Phase-1 metrics: ``luma`` (0-255 mean, Rec.601) + ``edge_energy`` (mean gradient
magnitude). The region ROIs are vendored from the matrix witness's
``AESTHETIC_REGIONS`` (non-importable, hyphenated filename);
``test_phase1_region_rois_match_witness`` pins this copy against drift.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

#: Vendored normalized ``(x0, y0, x1, y1)`` ROIs, pinned to the witness AESTHETIC_REGIONS.
PHASE1_REGION_ROIS: dict[str, tuple[float, float, float, float]] = {
    "ceiling": (0.18, 0.02, 0.82, 0.24),
    "left_wall": (0.02, 0.18, 0.35, 0.72),
    "right_wall": (0.65, 0.18, 0.98, 0.72),
    "floor": (0.12, 0.70, 0.88, 0.98),
    "entity_core": (0.36, 0.25, 0.64, 0.66),
    "negative_space": (0.02, 0.02, 0.22, 0.34),
}

_REC601 = np.array([0.299, 0.587, 0.114])


def _to_luma(frame: np.ndarray) -> np.ndarray:
    arr = np.asarray(frame)
    if arr.ndim == 3 and arr.shape[2] >= 3:
        return arr[..., :3].astype(np.float64) @ _REC601
    return arr.astype(np.float64)


def _crop(luma: np.ndarray, roi: tuple[float, float, float, float]) -> np.ndarray:
    h, w = luma.shape[:2]
    x0, y0, x1, y1 = roi
    cx0, cy0 = int(round(x0 * w)), int(round(y0 * h))
    cx1 = max(cx0 + 1, int(round(x1 * w)))
    cy1 = max(cy0 + 1, int(round(y1 * h)))
    return luma[cy0:cy1, cx0:cx1]


def _luma_metric(region: np.ndarray) -> float:
    return float(region.mean()) if region.size else 0.0


def _edge_energy_metric(region: np.ndarray) -> float:
    if region.shape[0] < 2 or region.shape[1] < 2:
        return 0.0
    dy = np.abs(np.diff(region, axis=0))
    dx = np.abs(np.diff(region, axis=1))
    return float((dy.mean() + dx.mean()) / 2.0)


def realized_vector_from_frame(
    frame: np.ndarray,
    pov_label: str,
    region_rois: Mapping[str, tuple[float, float, float, float]] = PHASE1_REGION_ROIS,
) -> dict[str, dict[str, dict[str, float]]]:
    """``{pov_label: {region: {"luma": float, "edge_energy": float}}}`` — exactly the
    realized-vector shape ``shared.avsdlc_visual_intent.intent_pass`` consumes."""
    luma = _to_luma(frame)
    regions: dict[str, dict[str, float]] = {}
    for region, roi in region_rois.items():
        crop = _crop(luma, roi)
        regions[region] = {
            "luma": _luma_metric(crop),
            "edge_energy": _edge_energy_metric(crop),
        }
    return {pov_label: regions}
