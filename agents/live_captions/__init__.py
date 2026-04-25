"""In-band live captions reader (ytb-009 Phase 1).

Reads timestamped caption events that the daimonion's STT pipeline
writes to ``/dev/shm/hapax-captions/live.jsonl`` and exposes them
with a moving-average audio↔video offset so a downstream GStreamer
``cc708overlay`` consumer can display them aligned to the broadcast
video clock.

This Phase-1 ship is the consumer side only — the GStreamer pipeline
modification (alpha lane) and the daimonion-side caption writer land
in follow-up PRs once this contract is in place.
"""

from agents.live_captions.reader import CaptionEvent, CaptionReader
from agents.live_captions.writer import CaptionWriter

__all__ = ["CaptionEvent", "CaptionReader", "CaptionWriter"]
