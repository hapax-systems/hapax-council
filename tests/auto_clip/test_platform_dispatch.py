"""Tests for platform_dispatch module."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from agents.auto_clip.platform_dispatch import (
    CITABLE_NEXUS_URL,
    RAIL_PAGES,
    ClipMetadata,
    InstagramUploader,
    TikTokUploader,
    YouTubeUploader,
    build_description,
    dispatch_clip,
)


def _sample_metadata() -> ClipMetadata:
    return ClipMetadata(
        title="Test Short",
        description="A test clip",
        decoder_channel="visual",
        tags=["hapax", "test"],
        clip_id="clip-test-001",
    )


def _description_value(desc: str, label: str) -> str:
    prefix = f"{label}: "
    return next(line.removeprefix(prefix) for line in desc.splitlines() if line.startswith(prefix))


def test_build_description_contains_attribution():
    desc = build_description(_sample_metadata())
    canonical = _description_value(desc, "Canonical")
    parsed = urlparse(canonical)
    assert canonical == CITABLE_NEXUS_URL
    # Attribution must point at an operator-owned surface; hapax.github.io
    # belongs to an unrelated third-party GitHub account.
    assert (parsed.scheme, parsed.hostname) == ("https", "hapax.weblog.lol")
    assert "hapax.github.io" not in desc
    assert "CC-BY-4.0" in desc


def test_build_description_contains_rail_pages():
    desc = build_description(_sample_metadata())
    rail_urls = {_description_value(desc, "Support")}
    assert rail_urls == set(RAIL_PAGES.values())
    # Single no-perk support rail; no personal sponsors or dead rails.
    assert {urlparse(url).hostname for url in rail_urls} == {"hapax.weblog.lol"}
    assert "sponsors/ryanklee" not in desc
    assert "opencollective.com" not in desc


def test_youtube_uploader_not_configured_by_default():
    uploader = YouTubeUploader()
    assert not uploader.is_configured()
    result = uploader.upload(Path("/fake.mp4"), _sample_metadata())
    assert not result.success
    assert result.error == "credentials_not_configured"


def test_instagram_uploader_not_configured_by_default():
    uploader = InstagramUploader()
    assert not uploader.is_configured()


def test_tiktok_uploader_not_configured_by_default():
    uploader = TikTokUploader()
    assert not uploader.is_configured()


def test_dispatch_skips_unconfigured_platforms(tmp_path: Path):
    clip = tmp_path / "test.mp4"
    clip.write_bytes(b"fake")
    results = dispatch_clip(clip, _sample_metadata())
    assert len(results) == 3
    for r in results:
        assert not r.success
