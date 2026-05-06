"""Auto-clip Shorts pipeline.

The :mod:`segment_detection` submodule ships the LLM-assisted layer that
scans a rolling transcript / impingement / chat window and proposes
high-resonance segment candidates for the downstream clip-extraction
pipeline (cc-task ``auto-clip-shorts-livestream-pipeline``, in flight).
"""

from agents.auto_clip.segment_detection import (
    DecoderChannel,
    LlmSegmentDetector,
    RollingContext,
    SegmentCandidate,
)

__all__ = [
    "DecoderChannel",
    "LlmSegmentDetector",
    "RollingContext",
    "SegmentCandidate",
]
