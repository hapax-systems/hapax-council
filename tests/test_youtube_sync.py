"""Tests for youtube_sync — schemas, formatting, profiler facts."""
from __future__ import annotations


def test_liked_video_defaults():
    from agents.youtube_sync import LikedVideo
    v = LikedVideo(
        video_id="abc123",
        title="Cool Beat Tutorial",
        channel="Producer Channel",
        published_at="2026-03-01T10:00:00Z",
    )
    assert v.category == ""
    assert v.tags == []
    assert v.liked_at == ""


def test_subscription_defaults():
    from agents.youtube_sync import Subscription
    s = Subscription(
        channel_id="ch123",
        channel_name="Music Theory",
    )
    assert s.description == ""
    assert s.subscribed_at == ""


def test_youtube_sync_state_empty():
    from agents.youtube_sync import YouTubeSyncState
    s = YouTubeSyncState()
    assert s.liked_videos == {}
    assert s.subscriptions == {}
    assert s.playlists == {}


def test_format_liked_video_markdown():
    from agents.youtube_sync import LikedVideo, _format_liked_video_markdown
    v = LikedVideo(
        video_id="abc123",
        title="Making Lo-Fi Beats on SP-404",
        channel="Beat Producer",
        published_at="2026-02-15T10:00:00Z",
        liked_at="2026-03-01T20:00:00Z",
        category="Music",
        tags=["sp-404", "lo-fi", "beats"],
    )
    md = _format_liked_video_markdown(v)
    assert "platform: google" in md
    assert "service: youtube" in md
    assert "source_service: youtube" in md
    assert "content_type: liked_video" in md
    assert "Making Lo-Fi Beats" in md
    assert "Beat Producer" in md


def test_format_subscriptions_markdown():
    from agents.youtube_sync import Subscription, _format_subscriptions_markdown
    subs = [
        Subscription(channel_id="ch1", channel_name="Music Theory",
                     description="Learn music theory", video_count=150),
        Subscription(channel_id="ch2", channel_name="Beat Making",
                     description="Hip hop production", video_count=80),
    ]
    md = _format_subscriptions_markdown(subs)
    assert "source_service: youtube" in md
    assert "Music Theory" in md
    assert "Beat Making" in md


def test_generate_youtube_profile_facts():
    from agents.youtube_sync import (
        _generate_profile_facts, YouTubeSyncState, LikedVideo, Subscription,
    )
    state = YouTubeSyncState()
    state.liked_videos = {
        "v1": LikedVideo(video_id="v1", title="Beat Tutorial",
              channel="Producer", tags=["beats", "sp-404"]),
        "v2": LikedVideo(video_id="v2", title="Synth Jam",
              channel="SynthHead", tags=["synth", "ambient"]),
    }
    state.subscriptions = {
        "ch1": Subscription(channel_id="ch1", channel_name="Producer"),
    }
    facts = _generate_profile_facts(state)
    assert len(facts) > 0
    dims = {f["dimension"] for f in facts}
    assert "information_seeking" in dims
