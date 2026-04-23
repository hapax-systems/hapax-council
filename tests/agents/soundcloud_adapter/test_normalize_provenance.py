"""Pin: SC adapter normalizes records with provenance fields the music
programmer needs.

Regression context: 2026-04-23 — the music programmer's weighted picker
treats records by their ``source`` field (epidemic / streambeats /
soundcloud-oudepode / etc) and the broadcast safety gate keys off
``broadcast_safe`` + ``content_risk``. Earlier revisions of this
adapter wrote records WITHOUT these fields, so model_validate filled
in defaults (``source="local"`` from SOURCE_LOCAL fallback, no
broadcast safety promise). Result: oudepode tracks were treated as
anonymous local files, the 1-in-8 oudepode cap stopped firing, and
the operator's tagging had to be re-applied by hand after every hourly
sync.
"""

from __future__ import annotations

from types import SimpleNamespace

from agents.soundcloud_adapter.__main__ import (
    _normalize_sclib_track,
    _normalize_soundcloud_track,
)


def test_sclib_normalize_includes_source_and_safety_fields() -> None:
    track = SimpleNamespace(
        title="UNKNOWNTRON",
        artist="Oudepode",
        permalink_url="https://soundcloud.com/oudepode/unknowntron",
        duration=152_000,
        genre="hip-hop",
    )
    row = _normalize_sclib_track(track)
    assert row["source"] == "soundcloud-oudepode"
    assert row["content_risk"] == "tier_0_owned"
    assert row["broadcast_safe"] is True
    assert row["whitelist_source"] is None
    assert "soundcloud" in row["tags"]


def test_soundcloud_dict_normalize_includes_source_and_safety_fields() -> None:
    track = {
        "title": "PLUMPCORP",
        "user": {"username": "Oudepode"},
        "permalink_url": "https://soundcloud.com/oudepode/plumpcorp",
        "duration": 270_000,
        "genre": "",
    }
    row = _normalize_soundcloud_track(track)
    assert row["source"] == "soundcloud-oudepode"
    assert row["content_risk"] == "tier_0_owned"
    assert row["broadcast_safe"] is True
    assert row["whitelist_source"] is None


def test_normalized_row_round_trips_through_local_music_track() -> None:
    """Pin: the normalize output validates as LocalMusicTrack with all
    provenance preserved (no silent default substitution).
    """
    from shared.music_repo import LocalMusicTrack

    track = SimpleNamespace(
        title="BIOSCOPE",
        artist="Oudepode",
        permalink_url="https://soundcloud.com/oudepode/bioscope",
        duration=200_000,
        genre="",
    )
    row = _normalize_sclib_track(track)
    parsed = LocalMusicTrack.model_validate(row)
    assert parsed.source == "soundcloud-oudepode"
    assert parsed.broadcast_safe is True
    assert parsed.content_risk == "tier_0_owned"
