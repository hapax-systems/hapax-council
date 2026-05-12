"""Auto-clip Shorts pipeline.

Detects livestream highlights via LLM, extracts clips from the HLS
archive, renders vertical Shorts with V5 attribution, and dispatches
to YouTube Shorts / Instagram Reels / TikTok.
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
