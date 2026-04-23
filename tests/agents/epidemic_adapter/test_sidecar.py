"""Sidecar reader/writer tests for the Epidemic adapter (Phase 3).

Pins:
  * sidecar parse + merge applies provenance + attribution to LocalMusicTrack
  * missing sidecar → no merge, file-tag-derived fields untouched
  * malformed sidecar → fail-soft (log + skip, don't raise)
  * round-trip write→read preserves all fields
  * scan() integration: sidecar override beats file-tag default
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agents.epidemic_adapter.sidecar import (
    EpidemicSidecar,
    load_sidecar,
    merge_sidecar_into_track,
    sidecar_path_for,
    write_sidecar,
)
from shared.music_repo import LocalMusicRepo, LocalMusicTrack

# ── sidecar_path_for ────────────────────────────────────────────────────────


def test_sidecar_path_replaces_extension(tmp_path: Path) -> None:
    audio = tmp_path / "song.flac"
    assert sidecar_path_for(audio) == tmp_path / "song.yaml"


def test_sidecar_path_handles_string_input(tmp_path: Path) -> None:
    assert sidecar_path_for(str(tmp_path / "song.mp3")) == tmp_path / "song.yaml"


def test_sidecar_path_handles_no_extension(tmp_path: Path) -> None:
    assert sidecar_path_for(tmp_path / "song") == tmp_path / "song.yaml"


# ── load_sidecar ────────────────────────────────────────────────────────────


def test_load_sidecar_missing_returns_none(tmp_path: Path) -> None:
    assert load_sidecar(tmp_path / "no-such.flac") is None


def test_load_sidecar_minimal_valid(tmp_path: Path) -> None:
    audio = tmp_path / "track.flac"
    (tmp_path / "track.yaml").write_text(
        "attribution:\n"
        "  artist: Dusty Decks\n"
        "  title: Direct Drive\n"
        "  epidemic_id: 146b162e-fad2-4da3-871e-e894cd81db9b\n"
        "content_risk: tier_1_platform_cleared\n"
        "source: epidemic\n",
        encoding="utf-8",
    )
    sidecar = load_sidecar(audio)
    assert sidecar is not None
    assert sidecar.attribution.artist == "Dusty Decks"
    assert sidecar.attribution.title == "Direct Drive"
    assert sidecar.attribution.epidemic_id == "146b162e-fad2-4da3-871e-e894cd81db9b"
    assert sidecar.content_risk == "tier_1_platform_cleared"
    assert sidecar.source == "epidemic"


def test_load_sidecar_malformed_yaml_returns_none(tmp_path: Path) -> None:
    audio = tmp_path / "bad.flac"
    (tmp_path / "bad.yaml").write_text("[: not yaml at all", encoding="utf-8")
    assert load_sidecar(audio) is None


def test_load_sidecar_non_dict_returns_none(tmp_path: Path) -> None:
    """A YAML scalar (e.g. just a string) is not a valid sidecar shape."""
    audio = tmp_path / "scalar.flac"
    (tmp_path / "scalar.yaml").write_text("just a string", encoding="utf-8")
    assert load_sidecar(audio) is None


def test_load_sidecar_extra_fields_ignored(tmp_path: Path) -> None:
    """Pydantic ConfigDict(extra='ignore') means future fields don't break old code."""
    audio = tmp_path / "future.flac"
    (tmp_path / "future.yaml").write_text(
        "attribution:\n  artist: x\n  title: y\nfuture_field: ignored\n",
        encoding="utf-8",
    )
    sidecar = load_sidecar(audio)
    assert sidecar is not None
    assert sidecar.attribution.artist == "x"


# ── merge_sidecar_into_track ────────────────────────────────────────────────


def _base_track(path: str = "/x.flac") -> LocalMusicTrack:
    return LocalMusicTrack(
        path=path,
        title="From Tags",
        artist="From Tags",
        duration_s=120.0,
        tags=["existing"],
    )


def test_merge_overrides_provenance_fields() -> None:
    track = _base_track()
    sidecar = EpidemicSidecar(
        content_risk="tier_2_provenance_known",
        broadcast_safe=False,
        source="freesound-cc0",
    )
    merged = merge_sidecar_into_track(track, sidecar)
    assert merged.content_risk == "tier_2_provenance_known"
    assert merged.broadcast_safe is False
    assert merged.source == "freesound-cc0"


def test_merge_populates_whitelist_source_from_epidemic_id() -> None:
    track = _base_track()
    sidecar = EpidemicSidecar.model_validate({"attribution": {"epidemic_id": "abc-123"}})
    merged = merge_sidecar_into_track(track, sidecar)
    assert merged.whitelist_source == "abc-123"


def test_merge_overrides_title_when_sidecar_provides() -> None:
    track = _base_track()
    sidecar = EpidemicSidecar.model_validate(
        {"attribution": {"title": "Sidecar Title", "artist": "Sidecar Artist"}}
    )
    merged = merge_sidecar_into_track(track, sidecar)
    assert merged.title == "Sidecar Title"
    assert merged.artist == "Sidecar Artist"


def test_merge_keeps_file_artist_when_sidecar_unknown() -> None:
    """attribution.artist defaulting to 'unknown' must NOT clobber the file's tag."""
    track = _base_track()
    sidecar = EpidemicSidecar.model_validate(
        {"attribution": {"title": "X"}}  # artist defaults to "unknown"
    )
    merged = merge_sidecar_into_track(track, sidecar)
    assert merged.artist == "From Tags"


def test_merge_appends_mood_and_taxonomy_tags_dedup() -> None:
    track = _base_track()
    track = track.model_copy(update={"tags": ["existing", "boom-bap"]})
    sidecar = EpidemicSidecar(
        mood_tags=["dreamy", "laid back"],
        taxonomy_tags=["boom-bap", "old school hip hop"],  # boom-bap dupes
    )
    merged = merge_sidecar_into_track(track, sidecar)
    # tag normalization (lowercase, dedup) is on the field validator
    assert "dreamy" in merged.tags
    assert "laid back" in merged.tags
    assert "old school hip hop" in merged.tags
    # boom-bap appeared twice but should be deduped
    assert merged.tags.count("boom-bap") == 1


def test_merge_overrides_bpm_and_duration_when_provided() -> None:
    track = _base_track().model_copy(update={"bpm": 110.0, "duration_s": 60.0})
    sidecar = EpidemicSidecar(bpm=92.0, duration_seconds=151.123)
    merged = merge_sidecar_into_track(track, sidecar)
    assert merged.bpm == 92.0
    assert merged.duration_s == 151.123


# ── write_sidecar round-trip ────────────────────────────────────────────────


def test_write_then_load_round_trip(tmp_path: Path) -> None:
    audio = tmp_path / "track.flac"
    sidecar = EpidemicSidecar.model_validate(
        {
            "attribution": {
                "artist": "Dusty Decks",
                "title": "Direct Drive",
                "epidemic_id": "146b162e-fad2-4da3-871e-e894cd81db9b",
                "cover_art_url": "https://cdn.epidemicsound.com/release-cover-images/.../3000x3000.png",
            },
            "license": {"spdx": "epidemic-sound-personal", "attribution_required": False},
            "content_risk": "tier_1_platform_cleared",
            "broadcast_safe": True,
            "source": "epidemic",
            "bpm": 92.0,
            "musical_key": "f-minor",
            "duration_seconds": 151.123,
            "mood_tags": ["dreamy", "laid back"],
            "taxonomy_tags": ["boom-bap", "old school hip hop"],
            "vocals": False,
            "stems_available": ["DRUMS", "MELODY", "BASS", "INSTRUMENTS"],
        }
    )
    written = write_sidecar(audio, sidecar)
    assert written == tmp_path / "track.yaml"
    reloaded = load_sidecar(audio)
    assert reloaded is not None
    assert reloaded.attribution.epidemic_id == sidecar.attribution.epidemic_id
    assert reloaded.bpm == 92.0
    assert reloaded.musical_key == "f-minor"
    assert reloaded.stems_available == ["DRUMS", "MELODY", "BASS", "INSTRUMENTS"]


def test_write_excludes_none_fields(tmp_path: Path) -> None:
    """exclude_none keeps the YAML clean — no 'bpm: null' noise."""
    audio = tmp_path / "minimal.flac"
    sidecar = EpidemicSidecar(
        content_risk="tier_1_platform_cleared",
        broadcast_safe=True,
        source="epidemic",
    )
    write_sidecar(audio, sidecar)
    raw = yaml.safe_load((tmp_path / "minimal.yaml").read_text(encoding="utf-8"))
    assert "bpm" not in raw
    assert "musical_key" not in raw


# ── scan() integration: sidecar overrides defaults during _track_from_file ──


def test_scan_picks_up_sidecar_provenance(tmp_path: Path) -> None:
    """A real audio-shaped file with sidecar must merge fields during scan."""
    audio = tmp_path / "epi-track.mp3"
    # Minimal byte content — mutagen will fail to read tags but the scan
    # path produces a degraded record we can still inspect.
    audio.write_bytes(b"\x00" * 100)
    sidecar = EpidemicSidecar.model_validate(
        {
            "attribution": {
                "artist": "Dusty Decks",
                "title": "Direct Drive",
                "epidemic_id": "uuid-123",
            },
            "content_risk": "tier_1_platform_cleared",
            "broadcast_safe": True,
            "source": "epidemic",
            "bpm": 92.0,
        }
    )
    write_sidecar(audio, sidecar)

    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    repo.scan(tmp_path)
    tracks = repo.all_tracks()
    assert len(tracks) == 1
    track = tracks[0]
    assert track.source == "epidemic"
    assert track.content_risk == "tier_1_platform_cleared"
    assert track.whitelist_source == "uuid-123"
    assert track.title == "Direct Drive"
    assert track.artist == "Dusty Decks"
    assert track.bpm == 92.0


def test_scan_without_sidecar_uses_defaults(tmp_path: Path) -> None:
    audio = tmp_path / "untagged.mp3"
    audio.write_bytes(b"\x00" * 100)
    # No sidecar written.

    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    repo.scan(tmp_path)
    tracks = repo.all_tracks()
    assert len(tracks) == 1
    track = tracks[0]
    assert track.source == "local"  # default
    assert track.content_risk == "tier_0_owned"  # default
    assert track.whitelist_source is None
    assert track.broadcast_safe is True


# ── EpidemicSidecar Pydantic validation ─────────────────────────────────────


def test_unknown_content_risk_rejected_at_sidecar_layer() -> None:
    with pytest.raises(Exception):  # ValidationError
        EpidemicSidecar(content_risk="tier_99_quantum")  # type: ignore[arg-type]
