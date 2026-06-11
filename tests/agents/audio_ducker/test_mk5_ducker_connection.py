"""mk5 ducker-connection tests (segment-audio-hosting-readiness AC#2/#6).

Covers the hosting-segment hold-open subscription, deepest-duck arbitration with
the segment trigger, fail-open behaviour, and the mk5 node re-targeting / disabled
TTS-duck path. SOURCE+tests only — no live PipeWire actuation.
"""

from __future__ import annotations

import json
import time

import pytest

from agents.audio_ducker.__main__ import (
    MUSIC_DUCK_NODE,
    MUSIC_DUCK_OPERATOR,
    MUSIC_DUCK_TTS,
    RODE_CAPTURE_NODE,
    TTS_DUCK_NODE,
    UNITY,
    compute_targets,
    read_mixer_gain,
    read_segment_active,
    write_mixer_gain,
)


class TestMk5NodeRetargeting:
    def test_music_duck_resolves_to_mk5_node(self) -> None:
        assert MUSIC_DUCK_NODE == "hapax-music-duck-mk5"

    def test_operator_mic_resolves_to_live_rode_node(self) -> None:
        assert RODE_CAPTURE_NODE.startswith("hapax-mic-rode")

    def test_tts_duck_node_disabled_single_owner(self) -> None:
        # No software TTS duck on mk5 (analog S-4 path); single duck owner.
        assert TTS_DUCK_NODE is None


class TestNoneNodeGuards:
    def test_write_to_none_node_is_noop_success(self) -> None:
        result = write_mixer_gain(None, 0.5)
        assert result.ok is True
        assert result.error is None

    def test_read_from_none_node_reports_unity(self) -> None:
        readback = read_mixer_gain(None)
        assert readback.ok is True
        assert readback.gain == 1.0


class TestSegmentHoldOpenArbitration:
    def test_segment_alone_ducks_music_at_tts_depth(self) -> None:
        music, tts = compute_targets(False, False, segment_active=True)
        assert music == MUSIC_DUCK_TTS  # -8 dB, same content class as TTS
        assert tts == UNITY  # a segment does not duck the TTS/voice path

    def test_segment_plus_operator_composes_in_db(self) -> None:
        music, _ = compute_targets(True, False, segment_active=True)
        # operator (-12) + segment-as-TTS-class (-8) compose in dB → -20
        # (voice-p2-duck-handoff dB-domain compose; was deepest-wins min()).
        assert music == pytest.approx(MUSIC_DUCK_OPERATOR * MUSIC_DUCK_TTS)

    def test_segment_plus_tts_does_not_double_duck(self) -> None:
        music, _ = compute_targets(False, True, segment_active=True)
        # The chain RMS envelope and the segment subscription are two
        # WITNESSES of the same TTS-class content, never two stacking
        # sources — the composed duck stays at -8, never -16.
        assert music == MUSIC_DUCK_TTS

    def test_segment_gated_by_fortress_coupling(self) -> None:
        # A hosting segment IS broadcast TTS content; when TTS-into-broadcast is
        # disabled (fortress), the segment must not duck the broadcast bed.
        music, _ = compute_targets(
            False, False, segment_active=True, allow_tts_into_broadcast=False
        )
        assert music == UNITY

    def test_no_triggers_is_unity_passthrough(self) -> None:
        music, tts = compute_targets(False, False, segment_active=False)
        assert music == UNITY
        assert tts == UNITY


class TestReadSegmentActiveSubscription:
    def _write(self, path, payload) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_fresh_file_with_programme_id_holds(self, tmp_path) -> None:
        p = tmp_path / "active-segment.json"
        self._write(p, {"programme_id": "prog-123", "role": "tier_list"})
        assert read_segment_active(p) is True

    def test_missing_file_fails_open(self, tmp_path) -> None:
        assert read_segment_active(tmp_path / "absent.json") is False

    def test_stale_file_fails_open(self, tmp_path) -> None:
        p = tmp_path / "active-segment.json"
        self._write(p, {"programme_id": "prog-123"})
        # now far in the future relative to the file mtime → stale → no hold.
        assert read_segment_active(p, now_s=time.time() + 100.0) is False

    def test_empty_programme_id_fails_open(self, tmp_path) -> None:
        p = tmp_path / "active-segment.json"
        self._write(p, {"programme_id": ""})
        assert read_segment_active(p) is False

    def test_missing_programme_id_fails_open(self, tmp_path) -> None:
        p = tmp_path / "active-segment.json"
        self._write(p, {"role": "rant"})
        assert read_segment_active(p) is False

    def test_corrupt_json_fails_open(self, tmp_path) -> None:
        p = tmp_path / "active-segment.json"
        p.write_text("{not json", encoding="utf-8")
        assert read_segment_active(p) is False

    def test_non_dict_root_fails_open(self, tmp_path) -> None:
        p = tmp_path / "active-segment.json"
        p.write_text(json.dumps(["a", "list"]), encoding="utf-8")
        assert read_segment_active(p) is False
