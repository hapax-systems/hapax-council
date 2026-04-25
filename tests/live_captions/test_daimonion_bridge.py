"""Tests for ``agents.live_captions.daimonion_bridge``."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from agents.live_captions.daimonion_bridge import (
    OPERATOR_SPEAKER,
    DaimonionCaptionBridge,
    get_caption_bridge,
    set_caption_bridge,
)
from agents.live_captions.routing import RoutedCaptionWriter, RoutingPolicy
from agents.live_captions.writer import CaptionWriter


def _routed_writer_with(jsonl: Path) -> RoutedCaptionWriter:
    return RoutedCaptionWriter(
        policy=RoutingPolicy(),
        writer=CaptionWriter(captions_path=jsonl),
    )


# ── DaimonionCaptionBridge.emit_transcription ──────────────────────


class TestEmitTranscription:
    def test_forwards_to_routed_writer(self, tmp_path):
        out = tmp_path / "live.jsonl"
        bridge = DaimonionCaptionBridge(routed_writer=_routed_writer_with(out))
        ok = bridge.emit_transcription(
            audio_start_ts=10.0,
            audio_duration_s=1.5,
            text="the operator says",
        )
        assert ok is True
        records = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l]
        assert records[0]["text"] == "the operator says"
        assert records[0]["duration_ms"] == 1500
        assert records[0]["speaker"] == OPERATOR_SPEAKER

    def test_explicit_speaker_overrides_default(self, tmp_path):
        out = tmp_path / "live.jsonl"
        bridge = DaimonionCaptionBridge(routed_writer=_routed_writer_with(out))
        bridge.emit_transcription(
            audio_start_ts=10.0,
            audio_duration_s=0.5,
            text="guest",
            speaker="guest-1",
        )
        records = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l]
        assert records[0]["speaker"] == "guest-1"

    def test_text_stripped(self, tmp_path):
        out = tmp_path / "live.jsonl"
        bridge = DaimonionCaptionBridge(routed_writer=_routed_writer_with(out))
        bridge.emit_transcription(
            audio_start_ts=10.0,
            audio_duration_s=0.5,
            text="  hello  \n",
        )
        records = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l]
        assert records[0]["text"] == "hello"

    def test_empty_text_after_strip_dropped(self, tmp_path):
        """Whitespace-only transcripts (silence chunks) silently dropped."""
        out = tmp_path / "live.jsonl"
        bridge = DaimonionCaptionBridge(routed_writer=_routed_writer_with(out))
        bridge.emit_transcription(audio_start_ts=10.0, audio_duration_s=0.5, text="   ")
        # No file written → no records.
        assert not out.exists() or out.read_text(encoding="utf-8") == ""

    def test_negative_duration_clamped_to_zero(self, tmp_path):
        out = tmp_path / "live.jsonl"
        bridge = DaimonionCaptionBridge(routed_writer=_routed_writer_with(out))
        bridge.emit_transcription(audio_start_ts=10.0, audio_duration_s=-1.0, text="x")
        records = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l]
        assert records[0]["duration_ms"] == 0

    def test_routing_filter_returns_false(self, tmp_path):
        out = tmp_path / "live.jsonl"
        routed = RoutedCaptionWriter(
            policy=RoutingPolicy(deny=frozenset({"banned"})),
            writer=CaptionWriter(captions_path=out),
        )
        bridge = DaimonionCaptionBridge(routed_writer=routed)
        ok = bridge.emit_transcription(
            audio_start_ts=10.0,
            audio_duration_s=0.5,
            text="x",
            speaker="banned",
        )
        assert ok is False
        assert not out.exists() or out.read_text(encoding="utf-8") == ""

    def test_writer_exception_doesnt_propagate(self, tmp_path):
        """A broken downstream writer must not break the STT caller."""
        bad = mock.Mock(spec=RoutedCaptionWriter)
        bad.emit.side_effect = RuntimeError("disk full")
        bridge = DaimonionCaptionBridge(routed_writer=bad)
        # Should not raise.
        ok = bridge.emit_transcription(audio_start_ts=10.0, audio_duration_s=0.5, text="x")
        assert ok is False


# ── Singleton get/set ─────────────────────────────────────────────


class TestSingleton:
    def test_get_returns_same_instance(self):
        set_caption_bridge(None)  # reset
        try:
            a = get_caption_bridge()
            b = get_caption_bridge()
            assert a is b
        finally:
            set_caption_bridge(None)

    def test_set_overrides_singleton(self):
        try:
            override = mock.Mock(spec=DaimonionCaptionBridge)
            set_caption_bridge(override)
            assert get_caption_bridge() is override
        finally:
            set_caption_bridge(None)

    def test_set_none_resets(self):
        set_caption_bridge(mock.Mock(spec=DaimonionCaptionBridge))
        set_caption_bridge(None)
        # Next get() constructs a real bridge (not the mock).
        bridge = get_caption_bridge()
        assert isinstance(bridge, DaimonionCaptionBridge)
        set_caption_bridge(None)
