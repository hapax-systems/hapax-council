"""#127 SPLATTRIBUTION - verify twitch_director migrated both
``transport_state == "PLAYING"`` gates to ``field.vinyl_playing``.

Structural contract test: re-reads the source of `twitch_director.py`
and asserts (a) there are no remaining string-equality gates against
``transport_state == "PLAYING"``, and (b) `field.vinyl_playing` is
referenced at least twice (the two migrated sites - MIDI-sync album
pulse and the pressure-counter active-signal tally). This locks the
migration so a future edit cannot silently revert one of the two
gates.

Behavioral test complement: when the tendency sampler shows a positive
beat_position_rate and transport=PLAYING, the beat-pulse emission fires
(matches pre-#127 behavior); when transport=STOPPED or the rate stalls
to 0, it does not.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.studio_compositor import compositional_consumer as cc
from agents.studio_compositor import twitch_director as td
from shared import perceptual_field as pf


@pytest.fixture(autouse=True)
def _redirect(monkeypatch, tmp_path):
    monkeypatch.setattr(pf, "_PERCEPTION_STATE", tmp_path / "perception-state.json")
    monkeypatch.setattr(pf, "_STIMMUNG_STATE", tmp_path / "stimmung-state.json")
    monkeypatch.setattr(pf, "_ALBUM_STATE", tmp_path / "album-state.json")
    monkeypatch.setattr(pf, "_CHAT_STATE", tmp_path / "chat-state.json")
    monkeypatch.setattr(pf, "_CHAT_RECENT", tmp_path / "chat-recent.json")
    monkeypatch.setattr(pf, "_STREAM_LIVE", tmp_path / "stream-live")
    monkeypatch.setattr(pf, "_PRESENCE_STATE", tmp_path / "presence-state.json")
    monkeypatch.setattr(pf, "_WORKING_MODE", tmp_path / "working-mode")
    monkeypatch.setattr(pf, "_CONSENT_CONTRACTS_DIR", tmp_path / "contracts")
    monkeypatch.setattr(pf, "_OBJECTIVES_DIR", tmp_path / "objectives")
    monkeypatch.setattr(pf, "_read_stream_mode", lambda: None)
    monkeypatch.setattr(td, "_NARRATIVE_STATE", tmp_path / "narrative-state.json")
    monkeypatch.setattr(cc, "_HERO_CAMERA_OVERRIDE", tmp_path / "hero-camera-override.json")
    monkeypatch.setattr(cc, "_OVERLAY_ALPHA_OVERRIDES", tmp_path / "overlay-alpha-overrides.json")
    monkeypatch.setattr(cc, "_RECENT_RECRUITMENT", tmp_path / "recent-recruitment.json")
    monkeypatch.setattr(cc, "_YOUTUBE_DIRECTION", tmp_path / "youtube-direction.json")
    monkeypatch.setattr(cc, "_STREAM_MODE_INTENT", tmp_path / "stream-mode-intent.json")
    pf.reset_tendency_cache()
    yield
    pf.reset_tendency_cache()


def _write_narrative(tmp_path: Path, stance: str = "nominal") -> None:
    (tmp_path / "narrative-state.json").write_text(
        json.dumps({"stance": stance, "activity": "react", "condition_id": "cond-x"})
    )


def _write_perception(tmp_path: Path, **kwargs: object) -> None:
    (tmp_path / "perception-state.json").write_text(json.dumps(kwargs))


# -- Structural migration pin ---------------------------------------------


def test_no_transport_state_playing_string_gates_remain():
    """Neither of the two pre-#127 ``transport_state == "PLAYING"`` gates
    is allowed to survive in twitch_director.py. The migration must be
    total; a half-migration would diverge the beat-pulse gate from the
    pressure counter and re-introduce misattribution during silent sides.
    """
    src = Path(td.__file__).read_text()
    forbidden = 'transport_state == "PLAYING"'
    code_only_lines = [line for line in src.splitlines() if not line.lstrip().startswith("#")]
    code_only = "\n".join(code_only_lines)
    assert forbidden not in code_only, (
        "twitch_director.py still contains a raw transport_state==PLAYING "
        "gate; #127 SPLATTRIBUTION requires field.vinyl_playing instead."
    )


def test_vinyl_playing_gate_referenced_both_sites():
    """The migration must preserve BOTH gate sites (MIDI pulse + pressure
    tally). At least 2 references to `field.vinyl_playing` are required.
    """
    src = Path(td.__file__).read_text()
    assert src.count("field.vinyl_playing") >= 2, (
        "Expected at least 2 field.vinyl_playing references in "
        "twitch_director.py (MIDI-sync album pulse + pressure counter); "
        f"found {src.count('field.vinyl_playing')}."
    )


# -- Behavioral pin -------------------------------------------------------


def test_vinyl_playing_true_emits_album_pulse(tmp_path):
    """Warm the tendency sampler then emit - matches pre-#127 positive
    path (PLAYING + advancing beat position)."""
    _write_narrative(tmp_path, stance="nominal")
    _write_perception(tmp_path, beat_position=0.5, transport_state="PLAYING")
    pf.build_perceptual_field()
    _write_perception(tmp_path, beat_position=1.0, transport_state="PLAYING")
    t = td.TwitchDirector()
    assert "overlay.foreground.album" in t.tick_once()


def test_vinyl_playing_false_when_stopped_suppresses_album_pulse(tmp_path):
    """Even with a beat_position change, STOPPED transport must veto."""
    _write_narrative(tmp_path, stance="nominal")
    _write_perception(tmp_path, beat_position=0.5, transport_state="STOPPED")
    pf.build_perceptual_field()
    _write_perception(tmp_path, beat_position=1.0, transport_state="STOPPED")
    t = td.TwitchDirector()
    assert "overlay.foreground.album" not in t.tick_once()


def test_vinyl_playing_false_when_rate_zero_suppresses_album_pulse(tmp_path):
    """Scratch stop: transport PLAYING but beat position frozen -> no pulse."""
    _write_narrative(tmp_path, stance="nominal")
    _write_perception(tmp_path, beat_position=1.0, transport_state="PLAYING")
    pf.build_perceptual_field()
    # Same beat position twice -> rate == 0.0 -> vinyl_playing False.
    _write_perception(tmp_path, beat_position=1.0, transport_state="PLAYING")
    t = td.TwitchDirector()
    assert "overlay.foreground.album" not in t.tick_once()
