"""Regression: PerceptualField.album must suppress catalog fields when not playing.

Operator-reported regression 2026-05-01: the LLM kept emitting present-tense
narrations of vinyl rotation that did not exist ("the bass on this Metal
Fingers cut", "OTO is keeping the rotation steady on these Special Herbs
volumes"). Refusal gate caught >40 hallucinated narrations in 30 minutes.

Root cause: ``shared/perceptual_field.py::build_perceptual_field`` populated
``AlbumField`` with raw artist / title / current_track / year regardless of
the album-state's ``playing`` flag. ``PerceptualField.model_dump_json
(exclude_none=True)`` then exposed those catalog fields to the director's
prompt, where the LLM grounded in them as factual present-tense state
(``grounding_provenance: ["album.artist", "album.title"]``).

album-identifier writes ``playing: false`` correctly when its own
``_vinyl_probably_playing`` gate is False (override flag absent + IR
hand-zone not turntable + IR hand-activity not scratching). The leak was
that the consumer ignored that flag.

This test pins the guard: when album-state's ``playing`` is False (or
absent), the populated PerceptualField.album must have None for
artist / title / current_track / year, so they're stripped by
``exclude_none=True`` and the LLM cannot ground in catalog state.
``confidence`` is allowed through — downstream classifiers may want
the visual confidence in the cover identification, that's not a
present-tense claim.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from shared.perceptual_field import build_perceptual_field


def _patch_album_state(tmp_path: Path, payload: dict):
    """Context manager-style patch for the live album-state path."""

    state_file = tmp_path / "album-state.json"
    state_file.write_text(json.dumps(payload), encoding="utf-8")
    return patch("shared.perceptual_field._ALBUM_STATE", state_file)


def test_album_artist_title_suppressed_when_playing_false(tmp_path: Path) -> None:
    payload = {
        "artist": "Metal Fingers (MF DOOM)",
        "title": "Special Herbs, Vols. 7 & 8",
        "current_track": "",
        "year": 2004,
        "confidence": 0.85,
        "playing": False,
    }
    with _patch_album_state(tmp_path, payload):
        field = build_perceptual_field()
    assert field.album.artist is None
    assert field.album.title is None
    assert field.album.current_track is None
    assert field.album.year is None
    # confidence is preserved — downstream classifiers may want the
    # visual-recognition confidence even when nothing is playing.
    assert field.album.confidence == 0.85


def test_album_artist_title_suppressed_when_playing_field_absent(
    tmp_path: Path,
) -> None:
    """Old album-state files may predate the playing field. Treat
    absence as not-playing — fail-closed."""

    payload = {
        "artist": "Some Artist",
        "title": "Some Title",
        "current_track": "Track 1",
        "year": 2020,
    }
    with _patch_album_state(tmp_path, payload):
        field = build_perceptual_field()
    assert field.album.artist is None
    assert field.album.title is None


def test_album_fields_pass_through_when_playing_true(tmp_path: Path) -> None:
    payload = {
        "artist": "Dusty Decks",
        "title": "Direct Drive",
        "current_track": "Track 3",
        "year": 2025,
        "confidence": 0.92,
        "playing": True,
    }
    with _patch_album_state(tmp_path, payload):
        field = build_perceptual_field()
    assert field.album.artist == "Dusty Decks"
    assert field.album.title == "Direct Drive"
    assert field.album.current_track == "Track 3"
    assert field.album.year == 2025
    assert field.album.confidence == 0.92


def test_perceptual_field_json_excludes_album_artist_when_not_playing(
    tmp_path: Path,
) -> None:
    """The downstream invariant: model_dump_json(exclude_none=True) must
    NOT contain album.artist / album.title when playing is False, so the
    LLM cannot extract them from the JSON block."""

    payload = {
        "artist": "Metal Fingers (MF DOOM)",
        "title": "Special Herbs, Vols. 7 & 8",
        "playing": False,
    }
    with _patch_album_state(tmp_path, payload):
        field = build_perceptual_field()
    rendered = field.model_dump_json(exclude_none=True)
    assert "Metal Fingers" not in rendered
    assert "MF DOOM" not in rendered
    assert "Special Herbs" not in rendered
