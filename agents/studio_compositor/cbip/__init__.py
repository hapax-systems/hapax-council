"""CBIP (Chess Board Interpretive Platter) — platter ward enhancement system.

Spec: ``docs/superpowers/specs/2026-04-21-cbip-phase-1-design.md``.
Concept: ``docs/research/2026-04-20-cbip-1-name-cultural-lineage.md``.
Enhancement families: ``docs/research/2026-04-20-cbip-vinyl-enhancement-research.md``.

Phase 0 (PR #1112) — deterministic hash tint, foundation.
Phase 1 (this module) — first two enhancement families + intensity router
+ override surface + recognizability harness + Ring-2 pre-render gate.
"""

from agents.studio_compositor.cbip.intensity_router import (
    DEGRADED_COHERENCE_THRESHOLD,
    CbipIntensity,
    intensity_for_stimmung,
    resolve_effective_intensity,
)
from agents.studio_compositor.cbip.override import (
    DEFAULT_OVERRIDE_PATH,
    OverrideValue,
    read_override,
    write_override,
)
from agents.studio_compositor.cbip.recognizability_harness import (
    CLIP_MIN_COSINE,
    EDGE_IOU_ABSTRACT_MIN,
    EDGE_IOU_GEOMETRIC_MIN,
    HUMAN_ID_MIN_RATE,
    OCR_MIN_CHAR_ACCURACY,
    PALETTE_MAX_DELTA_E,
    PHASH_MAX_HAMMING_BITS,
    ClipScorer,
    CoverShape,
    HarnessResult,
    MetricResult,
    ObjectShape,
    Severity,
    edge_iou_sobel,
    evaluate,
    ocr_character_accuracy,
    palette_delta_e,
    perceptual_hash_distance,
)
from agents.studio_compositor.cbip.ring2_gate import (
    COPYRIGHT_FRESHNESS_MAX_AGE_S,
    DEMONET_RISK_BLOCK_THRESHOLD,
    ContentIdLookup,
    CopyrightFreshnessClock,
    DemonetRiskScorer,
    GateName,
    GateOutcome,
    GateResult,
    Ring2PreRenderGate,
)

__all__ = [
    "CLIP_MIN_COSINE",
    "COPYRIGHT_FRESHNESS_MAX_AGE_S",
    "DEFAULT_OVERRIDE_PATH",
    "DEGRADED_COHERENCE_THRESHOLD",
    "DEMONET_RISK_BLOCK_THRESHOLD",
    "EDGE_IOU_ABSTRACT_MIN",
    "EDGE_IOU_GEOMETRIC_MIN",
    "HUMAN_ID_MIN_RATE",
    "OCR_MIN_CHAR_ACCURACY",
    "PALETTE_MAX_DELTA_E",
    "PHASH_MAX_HAMMING_BITS",
    "CbipIntensity",
    "ClipScorer",
    "ContentIdLookup",
    "CopyrightFreshnessClock",
    "CoverShape",
    "DemonetRiskScorer",
    "GateName",
    "GateOutcome",
    "GateResult",
    "HarnessResult",
    "MetricResult",
    "ObjectShape",
    "OverrideValue",
    "Ring2PreRenderGate",
    "Severity",
    "edge_iou_sobel",
    "evaluate",
    "intensity_for_stimmung",
    "ocr_character_accuracy",
    "palette_delta_e",
    "perceptual_hash_distance",
    "read_override",
    "resolve_effective_intensity",
    "write_override",
]
