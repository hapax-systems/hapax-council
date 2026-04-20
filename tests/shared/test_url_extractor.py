"""Tests for shared/url_extractor.py — Phase 1 of YouTube broadcast bundle."""

from __future__ import annotations

import pytest  # noqa: TC002

from shared.url_extractor import classify_url, extract_urls


class TestExtractUrls:
    def test_bare_url(self) -> None:
        assert extract_urls("check this https://example.com/path") == ["https://example.com/path"]

    def test_multiple_urls(self) -> None:
        text = "first https://a.com/x and second https://b.com/y"
        assert extract_urls(text) == ["https://a.com/x", "https://b.com/y"]

    def test_dedup_preserves_first_seen_order(self) -> None:
        text = "https://a.com/x ... https://b.com/y ... https://a.com/x again"
        assert extract_urls(text) == ["https://a.com/x", "https://b.com/y"]

    def test_strips_trailing_punctuation(self) -> None:
        assert extract_urls("see https://a.com/x.") == ["https://a.com/x"]
        assert extract_urls("see https://a.com/x,") == ["https://a.com/x"]
        assert extract_urls("see https://a.com/x?") == ["https://a.com/x"]
        assert extract_urls("(see https://a.com/x)") == ["https://a.com/x"]

    def test_markdown_link_extracted(self) -> None:
        # Bracketed URLs — the URL inside (...) gets extracted
        result = extract_urls("[click here](https://a.com/x) please")
        assert "https://a.com/x" in result

    def test_no_urls_returns_empty(self) -> None:
        assert extract_urls("just some text without links") == []

    def test_http_only_too_short_skipped(self) -> None:
        # "https://" alone is too short to be useful
        assert extract_urls("see https://") == []

    def test_case_preserved_in_path(self) -> None:
        urls = extract_urls("https://Example.com/MyPath")
        # We don't lowercase the URL itself (only the regex is case-i)
        assert urls == ["https://Example.com/MyPath"]


class TestClassifyUrl:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://doi.org/10.1234/abcd", "doi"),
            ("https://dx.doi.org/10.1234/abcd", "doi"),
            ("https://github.com/foo/bar", "github"),
            ("https://gist.github.com/foo/abc", "github"),
            ("https://twitter.com/user/status/123", "tweet"),
            ("https://x.com/user/status/123", "tweet"),
            ("https://www.youtube.com/watch?v=abc", "youtube"),
            ("https://youtu.be/abc", "youtube"),
            ("https://en.wikipedia.org/wiki/Foo", "wikipedia"),
            ("https://commons.wikimedia.org/wiki/Bar", "wikipedia"),
            ("https://artist.bandcamp.com/album/x", "album-ref"),
            ("https://soundcloud.com/user/track", "album-ref"),
            ("https://open.spotify.com/track/abc", "album-ref"),
            ("https://www.discogs.com/release/123", "album-ref"),
            ("https://www.nature.com/articles/123", "citation"),
            ("https://arxiv.org/abs/2024.01234", "citation"),
            ("https://www.sciencedirect.com/science/article/pii/abc", "citation"),
            ("https://example.com/random", "other"),
            ("https://news.ycombinator.com/item?id=1", "other"),
        ],
    )
    def test_classification(self, url: str, expected: str) -> None:
        assert classify_url(url) == expected

    def test_invalid_url_returns_other(self) -> None:
        assert classify_url("not a url") == "other"

    def test_no_scheme_returns_other(self) -> None:
        assert classify_url("example.com/path") == "other"


class TestEndToEnd:
    """Common chat-message shapes."""

    def test_realistic_chat_message_with_one_url(self) -> None:
        msg = "the paper is at https://nature.com/articles/abc123 — really good"
        urls = extract_urls(msg)
        assert urls == ["https://nature.com/articles/abc123"]
        assert classify_url(urls[0]) == "citation"

    def test_realistic_chat_with_album_ref_and_tweet(self) -> None:
        msg = (
            "track is https://artist.bandcamp.com/track/x and the artist "
            "tweeted about it https://twitter.com/artist/status/999"
        )
        urls = extract_urls(msg)
        kinds = [classify_url(u) for u in urls]
        assert "album-ref" in kinds
        assert "tweet" in kinds

    def test_message_with_no_urls(self) -> None:
        assert extract_urls("just chatting nothing linkable") == []
