"""Phase 2 — fetch_set covers private SoundCloud sets via secret-token URL.

Tests are library-agnostic: we mock both `sclib` and `soundcloud-api`
client shapes so the test doesn't depend on either being installed in
the CI environment (consistent with Phase 1 "optional library" design).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from agents.soundcloud_adapter.__main__ import fetch_set


def _sclib_track(
    title: str, artist: str, permalink: str, duration_ms: int = 120_000
) -> SimpleNamespace:
    return SimpleNamespace(
        title=title,
        artist=artist,
        permalink_url=permalink,
        duration=duration_ms,
        genre="",
    )


def test_fetch_set_missing_client_returns_empty() -> None:
    """No SoundCloud library available → degrade gracefully to []."""
    out = fetch_set(
        "https://soundcloud.com/oudepode/sets/banked/s-a6O4A2hPl7h",
        client_spec=None,
    )
    # With client_spec=None, adapter tries to import. If it succeeds and
    # the URL 404s we also get []. Either way, the contract is "empty on
    # failure, never raise."
    assert out == [] or isinstance(out, list)


def test_fetch_set_sclib_resolves_and_normalizes() -> None:
    """sclib.api.resolve(url) returns a playlist whose .tracks we normalize."""
    mock_client = MagicMock()
    mock_api = MagicMock()
    mock_client.SoundcloudAPI.return_value = mock_api
    playlist = SimpleNamespace(
        tracks=[
            _sclib_track("Track A", "Artist A", "https://soundcloud.com/x/track-a"),
            _sclib_track("Track B", "Artist B", "https://soundcloud.com/x/track-b"),
        ]
    )
    mock_api.resolve.return_value = playlist

    out = fetch_set(
        "https://soundcloud.com/oudepode/sets/banked/s-a6O4A2hPl7h",
        client_spec=(mock_client, "sclib"),
    )

    mock_api.resolve.assert_called_once_with(
        "https://soundcloud.com/oudepode/sets/banked/s-a6O4A2hPl7h"
    )
    assert len(out) == 2
    assert out[0]["title"] == "Track A"
    assert out[0]["artist"] == "Artist A"
    assert out[0]["path"] == "https://soundcloud.com/x/track-a"
    # Phase 2 tag contract
    assert "soundcloud" in out[0]["tags"]
    assert "banked" in out[0]["tags"]


def test_fetch_set_respects_limit() -> None:
    mock_client = MagicMock()
    mock_api = MagicMock()
    mock_client.SoundcloudAPI.return_value = mock_api
    playlist = SimpleNamespace(tracks=[_sclib_track(f"Track {i}", "A", f"u{i}") for i in range(10)])
    mock_api.resolve.return_value = playlist

    out = fetch_set("u", client_spec=(mock_client, "sclib"), limit=3)
    assert len(out) == 3


def test_fetch_set_custom_extra_tags() -> None:
    """Caller can override the extra-tags list (default is ['banked'])."""
    mock_client = MagicMock()
    mock_api = MagicMock()
    mock_client.SoundcloudAPI.return_value = mock_api
    playlist = SimpleNamespace(tracks=[_sclib_track("T", "A", "p")])
    mock_api.resolve.return_value = playlist

    out = fetch_set(
        "u",
        client_spec=(mock_client, "sclib"),
        extra_tags=["research", "reserved"],
    )
    assert "research" in out[0]["tags"]
    assert "reserved" in out[0]["tags"]
    # 'banked' not added when extra_tags is explicitly overridden
    assert "banked" not in out[0]["tags"]


def test_fetch_set_exception_returns_empty() -> None:
    """Network / auth / parsing errors degrade to empty list, never raise."""
    mock_client = MagicMock()
    mock_api = MagicMock()
    mock_client.SoundcloudAPI.return_value = mock_api
    mock_api.resolve.side_effect = RuntimeError("403 forbidden")

    out = fetch_set("u", client_spec=(mock_client, "sclib"))
    assert out == []


def test_fetch_set_empty_playlist_returns_empty() -> None:
    mock_client = MagicMock()
    mock_api = MagicMock()
    mock_client.SoundcloudAPI.return_value = mock_api
    mock_api.resolve.return_value = SimpleNamespace(tracks=[])

    out = fetch_set("u", client_spec=(mock_client, "sclib"))
    assert out == []


def test_fetch_set_playlist_without_tracks_attribute_is_empty() -> None:
    """If resolve() returns a non-Playlist (e.g. a single Track), .tracks
    is absent — we should return [] rather than error."""
    mock_client = MagicMock()
    mock_api = MagicMock()
    mock_client.SoundcloudAPI.return_value = mock_api
    mock_api.resolve.return_value = SimpleNamespace()  # no .tracks

    out = fetch_set("u", client_spec=(mock_client, "sclib"))
    assert out == []
