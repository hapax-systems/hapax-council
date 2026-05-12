"""Tests for platform_dispatch module."""

from __future__ import annotations

from pathlib import Path

from agents.auto_clip.platform_dispatch import (
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


def test_build_description_contains_attribution():
    desc = build_description(_sample_metadata())
    assert "hapax.github.io" in desc
    assert "CC-BY-4.0" in desc


def test_build_description_contains_rail_pages():
    desc = build_description(_sample_metadata())
    assert "github.com/sponsors" in desc
    assert "opencollective.com" in desc


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
