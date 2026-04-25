"""Daimonion-side caption bridge (ytb-009 Phase 4).

Glue between the daimonion's STT pipeline and the live-caption JSONL
writer. The STT pipeline already returns transcribed text from
``ResidentSTT.transcribe()``; the caller knows the audio start
timestamp and the audio duration, but not the writer / routing
shape. This bridge makes the wire-in a one-liner.

Usage from the CPAL or pipeline layer (the follow-up actually adds
this call site)::

    from agents.live_captions.daimonion_bridge import (
        get_caption_bridge,
    )

    bridge = get_caption_bridge()  # singleton
    transcript = await stt.transcribe(pcm_bytes)
    bridge.emit_transcription(
        audio_start_ts=ts_when_audio_began,
        audio_duration_s=len(pcm_bytes) / (16000 * 2),
        text=transcript,
        speaker="oudepode",  # operator narration
    )

The bridge is best-effort: failures log without raising so caption
emission can never break the STT call path.
"""

from __future__ import annotations

import logging

from agents.live_captions.routing import (
    DEFAULT_ROUTING_CONFIG,
    RoutedCaptionWriter,
    RoutingPolicy,
)
from agents.live_captions.writer import CaptionWriter

log = logging.getLogger(__name__)

# Operator-narration speaker tag — the empty/None speaker would also
# work (RoutingPolicy.allows always passes empty), but the explicit
# tag makes the JSONL self-documenting and the caption-routing.yaml
# allow-list can grant or revoke per-tag without a code change.
OPERATOR_SPEAKER = "oudepode"


class DaimonionCaptionBridge:
    """Bridge ``ResidentSTT.transcribe()`` output → captions JSONL.

    Constructor parameters
    ----------------------
    routed_writer:
        ``RoutedCaptionWriter`` to forward to. Tests inject a mock;
        production wires the default reading
        ``config/caption-routing.yaml``.
    """

    def __init__(self, *, routed_writer: RoutedCaptionWriter) -> None:
        self._routed_writer = routed_writer

    def emit_transcription(
        self,
        *,
        audio_start_ts: float,
        audio_duration_s: float,
        text: str,
        speaker: str | None = None,
    ) -> bool:
        """Emit one transcribed segment as a caption.

        ``audio_start_ts`` is the epoch-seconds timestamp of the first
        sample of the transcribed audio chunk (the audio clock domain
        the reader's AV-offset estimator aligns from). The duration
        becomes the caption's display window.

        Returns True iff the caption was forwarded (subject to routing
        policy). False means the policy filtered it. Empty/whitespace
        text is silently dropped at the writer layer.

        Never raises — caption emission is best-effort observability;
        a broken bridge must not break the STT caller.
        """
        try:
            return self._routed_writer.emit(
                ts=audio_start_ts,
                text=text.strip(),
                duration_ms=max(0, int(audio_duration_s * 1000)),
                speaker=speaker or OPERATOR_SPEAKER,
            )
        except Exception:  # noqa: BLE001
            log.exception("caption bridge emit raised; dropping caption")
            return False


# Module-level singleton — daimonion's STT loop wants a stable handle
# across utterances rather than constructing a bridge per call. The
# first ``get_caption_bridge()`` call constructs from the default
# routing config; tests override via ``set_caption_bridge()``.
_bridge: DaimonionCaptionBridge | None = None


def get_caption_bridge() -> DaimonionCaptionBridge:
    """Return the process-wide caption bridge, lazily constructing it."""
    global _bridge
    if _bridge is None:
        policy = RoutingPolicy.load(DEFAULT_ROUTING_CONFIG)
        writer = CaptionWriter()
        _bridge = DaimonionCaptionBridge(
            routed_writer=RoutedCaptionWriter(policy=policy, writer=writer),
        )
    return _bridge


def set_caption_bridge(bridge: DaimonionCaptionBridge | None) -> None:
    """Override the singleton. Pass None to reset.

    Tests use this to inject a mock-backed bridge without touching
    the on-disk routing config or live JSONL stream.
    """
    global _bridge
    _bridge = bridge


__all__ = [
    "OPERATOR_SPEAKER",
    "DaimonionCaptionBridge",
    "get_caption_bridge",
    "set_caption_bridge",
]
