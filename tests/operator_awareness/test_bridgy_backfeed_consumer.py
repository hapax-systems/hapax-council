"""Tests for ``agents.operator_awareness.bridgy_backfeed_consumer``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from agents.operator_awareness.bridgy_backfeed_consumer import (
    BackfeedEvent,
    aggregate_24h_counts,
    parse_webmention_payload,
    poll_omg_lol_webmentions,
    render_dot_grid_compact,
)


def test_parse_classifies_bluesky():
    payload = {
        "source": "https://bsky.app/profile/alice/post/abc",
        "target": "https://hapax.weblog.lol/post/x",
        "timestamp": "2026-04-26T20:00:00+00:00",
        "author": "alice.bsky.social",
        "excerpt": "interesting take",
    }
    event = parse_webmention_payload(payload)
    assert event is not None
    assert event.platform == "bluesky"
    assert event.author_handle == "alice.bsky.social"


def test_parse_classifies_mastodon():
    payload = {
        "source": "https://mastodon.social/@bob/123",
        "target": "https://hapax.weblog.lol/post/x",
        "timestamp": "2026-04-26T20:00:00Z",
    }
    event = parse_webmention_payload(payload)
    assert event is not None
    assert event.platform == "mastodon"


def test_parse_classifies_github():
    payload = {
        "source": "https://github.com/alice/repo/issues/42",
        "target": "https://hapax.weblog.lol/post/x",
        "timestamp": "2026-04-26T20:00:00Z",
    }
    event = parse_webmention_payload(payload)
    assert event is not None
    assert event.platform == "github"


def test_parse_returns_none_on_missing_fields():
    assert parse_webmention_payload({}) is None
    assert parse_webmention_payload({"source": "https://x"}) is None


def test_parse_returns_none_on_unknown_platform():
    payload = {
        "source": "https://random-site.example/post",
        "target": "https://hapax.weblog.lol/post/x",
        "timestamp": "2026-04-26T20:00:00Z",
    }
    assert parse_webmention_payload(payload) is None


def test_parse_truncates_excerpt_to_80_chars():
    payload = {
        "source": "https://bsky.app/x",
        "target": "https://hapax.weblog.lol/post/x",
        "timestamp": "2026-04-26T20:00:00Z",
        "excerpt": "x" * 200,
    }
    event = parse_webmention_payload(payload)
    assert event is not None
    assert len(event.excerpt) == 80


def test_aggregate_24h_counts_filters_old():
    now = datetime(2026, 4, 26, 22, 0, tzinfo=UTC)
    recent = BackfeedEvent(
        timestamp=now - timedelta(hours=1),
        platform="bluesky",
        author_handle="x",
        in_reply_to="t",
        excerpt="",
    )
    old = BackfeedEvent(
        timestamp=now - timedelta(hours=48),
        platform="mastodon",
        author_handle="y",
        in_reply_to="t",
        excerpt="",
    )
    counts = aggregate_24h_counts([recent, old], now=now)
    assert counts["bluesky"] == 1
    assert counts["mastodon"] == 0


def test_render_dot_grid_compact():
    out = render_dot_grid_compact({"mastodon": 3, "bluesky": 1, "github": 0})
    assert out == "M:3 B:1 G:0"


def test_render_dot_grid_handles_missing_keys():
    out = render_dot_grid_compact({})
    assert out == "M:0 B:0 G:0"


def test_poll_returns_empty_in_phase_1():
    # Phase 1 stub returns [] regardless of input
    assert poll_omg_lol_webmentions("hapax.weblog.lol") == []


def test_module_does_not_post_to_bridgy_replies():
    """Read-only contract: the consumer module must not contain any
    POST/reply call site to brid.gy/replies or /publish/reply.
    """
    source = (
        Path(__file__)
        .resolve()
        .parents[1]
        .joinpath(
            "..",
            "agents",
            "operator_awareness",
            "bridgy_backfeed_consumer.py",
        )
        .resolve()
    )
    text = source.read_text(encoding="utf-8")
    # The constitutional refusal — these substrings must NOT appear
    forbidden = ("brid.gy/replies", "/publish/reply", "POST.*brid.gy/publish")
    for needle in forbidden:
        assert needle not in text, f"read-only contract violated: {needle!r} in {source}"
