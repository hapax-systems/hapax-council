"""Production-wire tests for ytb-009 live captions."""

from __future__ import annotations

import inspect

from agents.hapax_daimonion.conversation_pipeline import (
    ConversationPipeline,
    _emit_caption_bridge_for_transcript,
)
from agents.live_captions.gstreamer import (
    CCCOMBINER_ELEMENT,
    decide_gstreamer_caption_path,
)
from agents.live_captions.routing import RoutingPolicy
from agents.live_captions.smoke import run_caption_smoke


class _Bridge:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def emit_transcription(
        self,
        *,
        audio_start_ts: float,
        audio_duration_s: float,
        text: str,
        speaker: str | None = None,
    ) -> bool:
        self.calls.append(
            {
                "audio_start_ts": audio_start_ts,
                "audio_duration_s": audio_duration_s,
                "text": text,
                "speaker": speaker,
            }
        )
        return True


class _BrokenBridge:
    def emit_transcription(self, **_kwargs) -> bool:
        raise RuntimeError("caption writer unavailable")


class TestConversationPipelineCallsite:
    def test_callsite_is_after_rejection_gates(self) -> None:
        source = inspect.getsource(ConversationPipeline._process_utterance_inner)

        emit_idx = source.index("_emit_caption_bridge_for_transcript(")
        assert source.index("if self._is_echo(transcript):") < emit_idx
        assert source.index("transcript = self._strip_echo_prefix(transcript)") < emit_idx
        assert source.index("self._last_transcript = transcript") < emit_idx
        assert source.index('self._emit("user_utterance"') < emit_idx
        assert "speaker=_pid" in source

    def test_bridge_helper_computes_audio_start_from_pcm_duration(self) -> None:
        bridge = _Bridge()
        one_second_pcm = b"\x00\x00" * 16000

        ok = _emit_caption_bridge_for_transcript(
            transcript="  accepted words  ",
            audio_bytes=one_second_pcm,
            now_s=100.0,
            bridge_factory=lambda: bridge,
        )

        assert ok is True
        assert bridge.calls == [
            {
                "audio_start_ts": 99.0,
                "audio_duration_s": 1.0,
                "text": "accepted words",
                "speaker": None,
            }
        ]

    def test_bridge_helper_preserves_principal_speaker_for_routing(self) -> None:
        bridge = _Bridge()

        ok = _emit_caption_bridge_for_transcript(
            transcript="guest words",
            audio_bytes=b"\x00\x00" * 16000,
            speaker="guest-1",
            now_s=100.0,
            bridge_factory=lambda: bridge,
        )

        assert ok is True
        assert bridge.calls[0]["speaker"] == "guest-1"

    def test_bridge_helper_is_best_effort(self) -> None:
        ok = _emit_caption_bridge_for_transcript(
            transcript="accepted words",
            audio_bytes=b"\x00\x00",
            now_s=100.0,
            bridge_factory=lambda: _BrokenBridge(),
        )

        assert ok is False


class TestGStreamerCaptionPathDecision:
    def test_cccombiner_path_retired_without_cea_packetizer(self) -> None:
        decision = decide_gstreamer_caption_path(
            cc708overlay_available=False,
            cccombiner_available=True,
            cea_packetizer_available=False,
        )

        assert decision.enabled is False
        assert decision.retired is True
        assert decision.element is None
        assert "cc708overlay_absent" in decision.reason_codes
        assert "cea_packetizer_missing" in decision.reason_codes

    def test_cccombiner_can_enable_when_packetizer_exists(self) -> None:
        decision = decide_gstreamer_caption_path(
            cc708overlay_available=False,
            cccombiner_available=True,
            cea_packetizer_available=True,
        )

        assert decision.enabled is True
        assert decision.retired is False
        assert decision.element == CCCOMBINER_ELEMENT
        assert "cccombiner_ready" in decision.reason_codes


class TestCaptionSmoke:
    def test_roundtrip_observes_av_offset(self, tmp_path) -> None:
        result = run_caption_smoke(
            tmp_path / "live.jsonl",
            text="ytb-009 smoke",
            audio_duration_s=1.0,
            av_offset_s=0.25,
            now_s=100.0,
        )

        assert result.ok is True
        assert result.emitted is True
        assert result.observed_events == 1
        assert result.observed_text == "ytb-009 smoke"
        assert result.audio_start_ts == 99.0
        assert result.observed_ts == 99.25
        assert result.av_offset_s == 0.25


class TestProductionRoutingConfig:
    def test_unknown_speaker_is_denied_by_default_config(self) -> None:
        policy = RoutingPolicy.load()

        assert policy.allows("operator") is True
        assert policy.allows("oudepode") is True
        assert policy.allows("guest-1") is False
