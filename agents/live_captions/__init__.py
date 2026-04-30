"""Live captions production bridge (ytb-009).

Reads timestamped caption events that the daimonion's STT pipeline
writes to ``/dev/shm/hapax-captions/live.jsonl`` and exposes them
with a moving-average audio↔video offset. The production STT callsite
is ``ConversationPipeline._process_utterance_inner`` after echo and
duplicate rejection. The native GStreamer CEA path is explicitly retired
until an STT JSONL -> CEA packetizer exists; see
``agents.live_captions.gstreamer``.
"""

from agents.live_captions.daimonion_bridge import (
    DaimonionCaptionBridge,
    get_caption_bridge,
    set_caption_bridge,
)
from agents.live_captions.gstreamer import (
    GStreamerCaptionPathDecision,
    decide_gstreamer_caption_path,
    inspect_gstreamer_caption_path,
)
from agents.live_captions.reader import CaptionEvent, CaptionReader
from agents.live_captions.routing import RoutedCaptionWriter, RoutingPolicy
from agents.live_captions.writer import CaptionWriter

__all__ = [
    "CaptionEvent",
    "CaptionReader",
    "CaptionWriter",
    "DaimonionCaptionBridge",
    "GStreamerCaptionPathDecision",
    "RoutedCaptionWriter",
    "RoutingPolicy",
    "decide_gstreamer_caption_path",
    "get_caption_bridge",
    "inspect_gstreamer_caption_path",
    "set_caption_bridge",
]
