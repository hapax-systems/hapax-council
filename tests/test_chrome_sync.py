"""Tests for chrome_sync — schemas, formatting, timestamp conversion, profiler facts."""

from __future__ import annotations

from datetime import UTC, datetime


def test_history_entry_defaults():
    from agents.chrome_sync import HistoryEntry

    e = HistoryEntry(url="https://example.com/page")
    assert e.title == ""
    assert e.domain == ""
    assert e.visit_count == 0
    assert e.last_visit is None
    assert e.first_visit is None


def test_bookmark_entry_defaults():
    from agents.chrome_sync import BookmarkEntry

    b = BookmarkEntry(url="https://example.com")
    assert b.title == ""
    assert b.folder == ""
    assert b.added_at is None


def test_chrome_sync_state_empty():
    from agents.chrome_sync import ChromeSyncState

    s = ChromeSyncState()
    assert s.last_visit_time == 0
    assert s.domains == {}
    assert s.bookmark_hash == ""


def test_should_skip_domain():
    from agents.chrome_sync import _should_skip_domain

    # Noise domains should be skipped
    assert _should_skip_domain("localhost") is True
    assert _should_skip_domain("127.0.0.1") is True
    assert _should_skip_domain("0.0.0.0") is True
    assert _should_skip_domain("chrome://") is True
    assert _should_skip_domain("chrome-extension://") is True
    assert _should_skip_domain("newtab") is True
    assert _should_skip_domain("mail.google.com") is True
    assert _should_skip_domain("calendar.google.com") is True
    assert _should_skip_domain("drive.google.com") is True
    assert _should_skip_domain("docs.google.com") is True
    assert _should_skip_domain("youtube.com") is True
    assert _should_skip_domain("www.youtube.com") is True
    assert _should_skip_domain("music.youtube.com") is True
    assert _should_skip_domain("accounts.google.com") is True
    assert _should_skip_domain("myaccount.google.com") is True
    assert _should_skip_domain("") is True
    # Real domains should pass
    assert _should_skip_domain("github.com") is False
    assert _should_skip_domain("stackoverflow.com") is False
    assert _should_skip_domain("news.ycombinator.com") is False
    assert _should_skip_domain("docs.python.org") is False


def test_webkit_timestamp_conversion():
    from agents.chrome_sync import _webkit_to_datetime

    # 2026-01-01 00:00:00 UTC
    # Unix timestamp: 1767225600
    # WebKit: (1767225600 + 11644473600) * 1_000_000
    webkit_ts = (1767225600 + 11644473600) * 1_000_000
    result = _webkit_to_datetime(webkit_ts)
    expected = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    assert result == expected

    # Zero timestamp should return epoch
    zero = _webkit_to_datetime(0)
    assert zero == datetime(1970, 1, 1, tzinfo=UTC)


def test_format_domain_markdown():
    from agents.chrome_sync import HistoryEntry, _format_domain_markdown

    entries = [
        HistoryEntry(
            url="https://github.com/user/repo",
            title="My Repo",
            domain="github.com",
            visit_count=10,
        ),
        HistoryEntry(
            url="https://github.com/user/other",
            title="Other Repo",
            domain="github.com",
            visit_count=5,
        ),
    ]
    md = _format_domain_markdown("github.com", entries, total_visits=15)
    assert "platform: chrome" in md
    assert "source_service: chrome" in md
    assert "domain: github.com" in md
    assert "total_visits: 15" in md
    assert "# github.com" in md
    assert "My Repo" in md
    assert "Other Repo" in md


def test_format_bookmarks_markdown():
    from agents.chrome_sync import BookmarkEntry, _format_bookmarks_markdown

    bookmarks = [
        BookmarkEntry(url="https://github.com", title="GitHub", folder="Dev"),
        BookmarkEntry(url="https://python.org", title="Python", folder="Dev"),
        BookmarkEntry(url="https://news.ycombinator.com", title="HN", folder="News"),
    ]
    md = _format_bookmarks_markdown(bookmarks)
    assert "platform: chrome" in md
    assert "source_service: chrome" in md
    assert "bookmark_count: 3" in md
    assert "## Dev" in md
    assert "## News" in md
    assert "GitHub" in md
    assert "Python" in md
    assert "HN" in md


def test_generate_chrome_profile_facts():
    from agents.chrome_sync import ChromeSyncState, _generate_profile_facts

    state = ChromeSyncState()
    state.domains = {
        "github.com": 50,
        "stackoverflow.com": 30,
        "docs.python.org": 20,
    }
    facts = _generate_profile_facts(state)
    assert len(facts) > 0
    dims = {f["dimension"] for f in facts}
    assert "information_seeking" in dims
    keys = {f["key"] for f in facts}
    assert "browsing_top_domains" in keys
    # Check the top domains fact contains our domains
    top_fact = next(f for f in facts if f["key"] == "browsing_top_domains")
    assert "github.com" in top_fact["value"]
    assert top_fact["confidence"] == 0.85


import pytest


@pytest.mark.parametrize(
    "payload,kind",
    [("null", "null"), ('"a"', "string"), ("[1,2]", "list"), ("42", "int")],
)
def test_read_bookmarks_non_dict_root_returns_empty(tmp_path, payload, kind):
    """Pin _read_bookmarks against non-dict JSON. data.get('roots', {})
    raised AttributeError on non-dict roots — the broad Exception catch
    around json.loads didn't cover it."""
    from agents.chrome_sync import _read_bookmarks

    path = tmp_path / "bookmarks.json"
    path.write_text(payload)
    assert _read_bookmarks(path) == [], f"non-dict root={kind} must yield empty"


def test_read_bookmarks_non_dict_roots_field_returns_empty(tmp_path):
    """Pin: dict root with non-dict 'roots' field falls back to empty."""
    import json

    path = tmp_path / "bookmarks.json"
    path.write_text(json.dumps({"roots": "not-a-dict"}))
    from agents.chrome_sync import _read_bookmarks

    assert _read_bookmarks(path) == []
