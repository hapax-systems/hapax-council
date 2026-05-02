"""Tests for shared.music_sources.

39-LOC music-source taxonomy + broadcast-decommission gates.
Untested before this commit.
"""

from __future__ import annotations

import pytest

from shared import music_sources

# ── Normalisation ──────────────────────────────────────────────────


class TestNormalize:
    @pytest.mark.parametrize(
        ("inp", "expected"),
        [
            ("Epidemic", "epidemic"),
            ("  EPIDEMIC  ", "epidemic"),
            ("soundcloud-oudepode", "soundcloud-oudepode"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_normalize_source(self, inp: str | None, expected: str) -> None:
        assert music_sources.normalize_source(inp) == expected


# ── Decommission gate (string source) ──────────────────────────────


class TestDecommissionedSource:
    def test_epidemic_is_decommissioned(self) -> None:
        assert music_sources.is_decommissioned_broadcast_source("epidemic")

    def test_epidemic_case_insensitive(self) -> None:
        assert music_sources.is_decommissioned_broadcast_source("EPIDEMIC")
        assert music_sources.is_decommissioned_broadcast_source("  Epidemic ")

    @pytest.mark.parametrize(
        "source",
        [
            "soundcloud-oudepode",
            "found-sound",
            "wwii-newsclip",
            "streambeats",
            "pretzel",
            "youtube-audio-library",
            "local",
            "",
            None,
        ],
    )
    def test_active_sources_not_decommissioned(self, source: str | None) -> None:
        assert not music_sources.is_decommissioned_broadcast_source(source)


# ── Path-based decommission detection ──────────────────────────────


class TestDecommissionedPath:
    def test_path_with_epidemic_segment_flagged(self) -> None:
        assert music_sources.path_looks_decommissioned_broadcast_source("music/epidemic/track.mp3")

    def test_path_segment_match_is_case_insensitive(self) -> None:
        assert music_sources.path_looks_decommissioned_broadcast_source("music/Epidemic/x.mp3")

    def test_path_with_no_decommissioned_segment_passes(self) -> None:
        assert not music_sources.path_looks_decommissioned_broadcast_source(
            "music/soundcloud-oudepode/track.mp3"
        )

    def test_substring_in_filename_does_not_match(self) -> None:
        """The check operates on path SEGMENTS, not substrings — a file
        named ``epidemic-related.mp3`` is not flagged unless ``epidemic``
        is a directory in the path."""
        assert not music_sources.path_looks_decommissioned_broadcast_source(
            "music/oudepode/epidemic-related.mp3"
        )

    def test_url_path_returns_false_early(self) -> None:
        """Anything with ``://`` is treated as a URL and returns False
        regardless of segment names."""
        assert not music_sources.path_looks_decommissioned_broadcast_source(
            "https://example.com/epidemic/x.mp3"
        )

    def test_empty_path(self) -> None:
        assert not music_sources.path_looks_decommissioned_broadcast_source("")
        assert not music_sources.path_looks_decommissioned_broadcast_source(None)


# ── Combined selection check ───────────────────────────────────────


class TestDecommissionedSelection:
    def test_blocked_when_source_is_decommissioned(self) -> None:
        assert music_sources.is_decommissioned_broadcast_selection(
            path="safe/path/track.mp3", source="epidemic"
        )

    def test_blocked_when_path_segment_matches(self) -> None:
        assert music_sources.is_decommissioned_broadcast_selection(
            path="music/epidemic/track.mp3", source="local"
        )

    def test_passes_when_neither_matches(self) -> None:
        assert not music_sources.is_decommissioned_broadcast_selection(
            path="music/oudepode/track.mp3", source="soundcloud-oudepode"
        )


# ── Constant pinning ──────────────────────────────────────────────


class TestConstants:
    def test_decommissioned_set_is_just_epidemic(self) -> None:
        """Pin the current decommission set so additions are deliberate."""
        assert frozenset({"epidemic"}) == music_sources.DECOMMISSIONED_BROADCAST_SOURCES

    def test_active_source_constants_present(self) -> None:
        """The seven canonical SOURCE_* constants are exported."""
        assert music_sources.SOURCE_OUDEPODE == "soundcloud-oudepode"
        assert music_sources.SOURCE_FOUND_SOUND == "found-sound"
        assert music_sources.SOURCE_WWII_NEWSCLIP == "wwii-newsclip"
        assert music_sources.SOURCE_STREAMBEATS == "streambeats"
        assert music_sources.SOURCE_PRETZEL == "pretzel"
        assert music_sources.SOURCE_YT_AUDIO_LIBRARY == "youtube-audio-library"
        assert music_sources.SOURCE_LOCAL == "local"
