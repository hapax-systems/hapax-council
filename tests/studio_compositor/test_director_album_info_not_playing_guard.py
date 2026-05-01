"""Regression: _read_album_info must not leak artist/title when not playing.

Album-identifier writes ``/dev/shm/hapax-compositor/album-state.json`` from
its IR-vision cover recognition every few seconds, regardless of whether
vinyl is actually spinning. When a record is sitting on the deck not
playing, the file looks like::

    {
      "artist": "Metal Fingers (MF DOOM)",
      "title":  "Special Herbs, Vols. 7 & 8",
      "current_track": "",
      "playing": false,
      ...
    }

The director loop's ``_read_album_info`` previously concatenated
``f"{title} by {artist}"`` unconditionally. The grounded LLM then wrote
present-tense narrations like "the low-end on this Metal Fingers cut
is hitting…" which the refusal gate caught as ``claim_below_floor`` —
but the cycle kept burning tokens.

This test pins the guard: when ``playing`` is False (or the artist/
title fields are empty), ``_read_album_info`` must return a string that
contains neither the artist nor the title — i.e., the LLM cannot ground
in the visually-recognized catalog state.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch


def _run_with_album_state(tmp_dir: Path, payload: dict) -> str:
    """Patch the director's ALBUM_STATE_FILE pointer and call the function."""

    state_path = tmp_dir / "album-state.json"
    state_path.write_text(json.dumps(payload), encoding="utf-8")
    from agents.studio_compositor import director_loop

    with patch.object(director_loop, "ALBUM_STATE_FILE", state_path):
        # Suppress the vinyl-rate import side effects; the rate probe is a
        # try/except in the function under test, so we don't need real shm.
        return director_loop._read_album_info()


def test_album_info_returns_no_music_playing_marker_when_playing_is_false(
    tmp_path: Path,
) -> None:
    payload = {
        "artist": "Metal Fingers (MF DOOM)",
        "title": "Special Herbs, Vols. 7 & 8",
        "current_track": "",
        "playing": False,
    }
    result = _run_with_album_state(tmp_path, payload)
    assert "Metal Fingers" not in result
    assert "MF DOOM" not in result
    assert "Special Herbs" not in result
    assert "no music playing" in result.lower()


def test_album_info_returns_unknown_when_artist_or_title_is_empty(
    tmp_path: Path,
) -> None:
    """A cleared album-state file (artist='', title='') used to degenerate
    to 'unknown by unknown', which the model treats as a license to
    invent an artist. The guard must collapse it to 'unknown'."""

    payload = {
        "artist": "",
        "title": "",
        "current_track": "",
        "playing": True,  # even when playing, blank fields must not leak
    }
    result = _run_with_album_state(tmp_path, payload)
    # Either path is acceptable: "unknown" or the explicit no-music marker;
    # the invariant is that no concatenated 'unknown by unknown' emerges.
    assert "unknown by unknown" not in result.lower()
    assert "unknown" in result.lower()


def test_album_info_returns_attributed_string_when_playing_true(
    tmp_path: Path,
) -> None:
    payload = {
        "artist": "Dusty Decks",
        "title": "Direct Drive",
        "current_track": "Track 3",
        "playing": True,
    }
    # Mock vinyl rate to avoid touching real shm
    from agents.studio_compositor import director_loop

    state_path = tmp_path / "album-state.json"
    state_path.write_text(json.dumps(payload), encoding="utf-8")

    with patch.object(director_loop, "ALBUM_STATE_FILE", state_path):
        result = director_loop._read_album_info()

    assert "Direct Drive" in result
    assert "Dusty Decks" in result
    # Track field round-trips when present + playing
    assert "Track 3" in result


def test_album_info_returns_unknown_when_state_file_missing(
    tmp_path: Path,
) -> None:
    from agents.studio_compositor import director_loop

    missing = tmp_path / "absent.json"
    with patch.object(director_loop, "ALBUM_STATE_FILE", missing):
        result = director_loop._read_album_info()
    assert result == "unknown"
