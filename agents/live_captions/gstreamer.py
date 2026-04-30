"""GStreamer caption-path decision for ytb-009 production wiring.

The original task notes named ``cc708overlay`` as the in-band caption
insertion point. The deployed GStreamer stack does not provide that
element. It does provide ``cccombiner``, but that element combines
already-packetized CEA-608/708 caption buffers or caption metadata with
video. This repo does not currently contain an STT JSONL -> CEA packetizer,
so adding ``cccombiner`` to the RTMP bin would create a live pipeline
branch with no valid caption buffers to combine.

For this release, production wiring is the daimonion STT -> routed JSONL
caption bridge. The GStreamer CEA path remains explicitly retired until a
packetizer exists.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

CC708OVERLAY_ELEMENT = "cc708overlay"
CCCOMBINER_ELEMENT = "cccombiner"


@dataclass(frozen=True)
class GStreamerCaptionPathDecision:
    """Decision record for whether native GStreamer in-band captions can run."""

    enabled: bool
    retired: bool
    element: str | None
    reason_codes: tuple[str, ...]
    detail: str


def decide_gstreamer_caption_path(
    *,
    cc708overlay_available: bool,
    cccombiner_available: bool,
    cea_packetizer_available: bool = False,
) -> GStreamerCaptionPathDecision:
    """Return the current GStreamer caption insertion decision.

    ``cc708overlay`` is tracked only to document its retirement: the
    viable native insertion element is ``cccombiner`` plus a source of
    valid ``closedcaption/x-cea-608`` or ``closedcaption/x-cea-708``
    buffers. Without that packetizer, the STT JSONL stream cannot be
    muxed into RTMP as CEA captions by GStreamer alone.
    """
    reasons: list[str] = []
    if not cc708overlay_available:
        reasons.append("cc708overlay_absent")
    else:
        reasons.append("cc708overlay_retired")

    if not cccombiner_available:
        reasons.append("cccombiner_absent")
    if not cea_packetizer_available:
        reasons.append("cea_packetizer_missing")

    if cccombiner_available and cea_packetizer_available:
        return GStreamerCaptionPathDecision(
            enabled=True,
            retired=False,
            element=CCCOMBINER_ELEMENT,
            reason_codes=tuple(reasons + ["cccombiner_ready"]),
            detail=(
                "Use cccombiner before the H.264 encoder once the STT stream is "
                "converted to closedcaption/x-cea-608 or x-cea-708 buffers."
            ),
        )

    return GStreamerCaptionPathDecision(
        enabled=False,
        retired=True,
        element=None,
        reason_codes=tuple(reasons),
        detail=(
            "Retired for ytb-009 production wiring: cc708overlay is not the "
            "deployed element, and cccombiner is not useful until a CEA "
            "packetizer turns routed STT captions into closedcaption buffers."
        ),
    )


def gst_element_available(element: str) -> bool:
    """Return True iff ``gst-inspect-1.0 <element>`` succeeds."""
    inspector = shutil.which("gst-inspect-1.0")
    if inspector is None:
        return False
    try:
        result = subprocess.run(
            [inspector, element],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def inspect_gstreamer_caption_path(
    *,
    cea_packetizer_available: bool = False,
) -> GStreamerCaptionPathDecision:
    """Inspect local GStreamer elements and return the production decision."""
    return decide_gstreamer_caption_path(
        cc708overlay_available=gst_element_available(CC708OVERLAY_ELEMENT),
        cccombiner_available=gst_element_available(CCCOMBINER_ELEMENT),
        cea_packetizer_available=cea_packetizer_available,
    )


__all__ = [
    "CC708OVERLAY_ELEMENT",
    "CCCOMBINER_ELEMENT",
    "GStreamerCaptionPathDecision",
    "decide_gstreamer_caption_path",
    "gst_element_available",
    "inspect_gstreamer_caption_path",
]
