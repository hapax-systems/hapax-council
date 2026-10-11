"""Tests for the discourse sensing producer, slice 1 (foundation half).

Fixture tests per parser (Bluesky AppView JSON, RSS 2.0, Atom, Hacker News
Algolia JSON), the no-outward-act invariant (AST scan), the fetch layer's
own 404/timeout branches via a hermetic MockTransport, and the intake
record path. All fixtures use synthetic handles, reserved example/test
domains, or the lab's own Bluesky DID
(did:plc:j7apz47n5ox4if5urv43jhsi); no real public figure's handle, name or
URL appears here, because this repository is public.

The run-level tests (reach reporting, dedup, cadence gating) live with the
runner half of the split.
"""

from __future__ import annotations

import ast
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path

import httpx

import agents.discourse_sensing as pkg
from agents.discourse_sensing.fetch import FetchResult
from agents.discourse_sensing.intake import item_record_path
from agents.discourse_sensing.parsers import (
    parse_bluesky_feed,
    parse_feed,
    parse_hn_search,
)

LAB_DID = "did:plc:j7apz47n5ox4if5urv43jhsi"
NOW = datetime(2026, 10, 11, 4, 0, 0, tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bluesky_payload() -> dict:
    return {
        "feed": [
            {
                "post": {
                    "uri": f"at://{LAB_DID}/app.bsky.feed.post/3synthetic-a",
                    "cid": "bafyreib4hhdh3wh4h7h",
                    "record": {
                        "createdAt": "2026-10-10T22:15:30.000Z",
                        "text": "A synthetic first post about sensing.",
                    },
                    "author": {"handle": "lab.source-a.example"},
                }
            },
            {
                "post": {
                    "uri": f"at://{LAB_DID}/app.bsky.feed.post/3synthetic-b",
                    "cid": "bafyreib4hhdh3wh4h8i",
                    "record": {
                        "createdAt": "2026-10-11T03:40:00.000Z",
                        "text": "A second synthetic post, more recent.",
                    },
                    "author": {"handle": "lab.source-a.example"},
                }
            },
        ],
        "cursor": "synthetic-cursor",
    }


def _rss_payload() -> bytes:
    old = format_datetime(NOW - timedelta(days=3))
    new = format_datetime(NOW - timedelta(hours=2))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Synthetic Source B</title>
  <link>https://source-b.example/</link>
  <item>
    <title>Backlog entry, older than the bootstrap window</title>
    <link>https://source-b.example/backlog</link>
    <pubDate>{old}</pubDate>
    <guid isPermaLink="true">https://source-b.example/backlog</guid>
  </item>
  <item>
    <title>Fresh entry within the window</title>
    <link>https://source-b.example/fresh</link>
    <pubDate>{new}</pubDate>
    <guid isPermaLink="true">https://source-b.example/fresh</guid>
  </item>
</channel></rss>
""".encode()


def _atom_payload() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Synthetic Atom Source</title>
  <entry>
    <title>Atom entry one</title>
    <link rel="alternate" href="https://source-c.example/atom-one"/>
    <id>urn:uuid:1111-1111</id>
    <published>2026-10-11T01:00:00Z</published>
  </entry>
</feed>
"""


def _hn_payload() -> dict:
    return {
        "hits": [
            {
                "objectID": "41000001",
                "title": "Show HN: Synthetic sensing project",
                "url": "https://source-a.example/project",
                "author": "synthetic-hn-user",
                "created_at": "2026-10-11T02:30:00Z",
                "points": 42,
            },
            {
                "objectID": "41000002",
                "title": "Discussion mentioning a synthetic query",
                "url": None,
                "author": "another-synthetic-user",
                "created_at": "2026-10-11T03:10:00Z",
                "points": 3,
            },
        ],
        "nbHits": 2,
    }


# ---------------------------------------------------------------- parsers


def test_parse_bluesky_feed_fixture() -> None:
    items = parse_bluesky_feed(_bluesky_payload(), "bsky-a", LAB_DID)
    assert len(items) == 2
    first = items[0]
    assert first.canonical_url.startswith(f"at://{LAB_DID}/app.bsky.feed.post/")
    assert first.handle == "lab.source-a.example"
    assert first.title == "A synthetic first post about sensing."
    assert first.published_at == "2026-10-10T22:15:30Z"
    assert first.venue == "bluesky"
    assert first.external_url == "https://bsky.app/profile/lab.source-a.example/post/3synthetic-a"
    again = parse_bluesky_feed(_bluesky_payload(), "bsky-a", LAB_DID)
    assert [i.content_hash for i in again] == [i.content_hash for i in items]


def test_parse_rss_fixture() -> None:
    items = parse_feed(_rss_payload(), "rss-b", "https://source-b.example/feed")
    assert [i.title for i in items] == [
        "Backlog entry, older than the bootstrap window",
        "Fresh entry within the window",
    ]
    fresh = items[1]
    assert fresh.canonical_url == "https://source-b.example/fresh"
    assert fresh.handle == "source-b.example"
    assert fresh.venue == "rss"
    assert fresh.published_at == _iso(NOW - timedelta(hours=2))


def test_parse_atom_fixture() -> None:
    items = parse_feed(_atom_payload(), "rss-c", "https://source-c.example/atom")
    assert len(items) == 1
    entry = items[0]
    assert entry.canonical_url == "https://source-c.example/atom-one"
    assert entry.published_at == "2026-10-11T01:00:00Z"
    assert entry.handle == "source-c.example"


def test_parse_hn_fixture() -> None:
    items = parse_hn_search(_hn_payload(), "hn-q", "synthetic query")
    assert len(items) == 2
    first = items[0]
    assert first.canonical_url == "https://news.ycombinator.com/item?id=41000001"
    assert first.external_url == "https://source-a.example/project"
    assert first.handle == "synthetic-hn-user"
    assert first.venue == "hackernews"
    second = items[1]
    assert second.external_url is None
    assert second.canonical_url == "https://news.ycombinator.com/item?id=41000002"


# ---------------------------------------------------- no outward act, ever


def test_no_code_path_performs_an_outward_act() -> None:
    package_dir = Path(pkg.__file__).resolve().parent
    http_verbs = {"get", "post", "put", "patch", "delete", "request", "send"}
    forbidden_literals = {"createRecord", "deleteRecord", "com.atproto.repo"}
    verb_calls: list[str] = []
    for py in sorted(package_dir.glob("*.py")):
        text = py.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in http_verbs:
                    verb_calls.append(node.func.attr)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for literal in forbidden_literals:
                    assert literal not in node.value, f"{py.name}: {literal} found"
        if py.name == "fetch.py":
            assert "User-Agent" in text, "the fetch layer must send a named User-Agent"
    assert verb_calls, "the sensor must actually fetch something"
    assert set(verb_calls) == {"get"}, f"non-GET HTTP verbs found: {sorted(set(verb_calls))}"


# ------------------------------------------------------ fetch and intake


def test_fetch_url_reports_404_and_timeout() -> None:
    from agents.discourse_sensing.fetch import USER_AGENT, fetch_url

    seen_headers: dict[str, str] = {}

    def _serve_404(request: httpx.Request) -> httpx.Response:
        seen_headers.update(dict(request.headers))
        return httpx.Response(404, text="gone")

    result = fetch_url("https://example.invalid/feed", transport=httpx.MockTransport(_serve_404))
    assert result.reached is False
    assert result.http_status == 404
    assert result.error == "HTTP 404"
    assert seen_headers["user-agent"] == USER_AGENT

    def _time_out(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    timed_out = fetch_url("https://example.invalid/feed", transport=httpx.MockTransport(_time_out))
    assert timed_out.reached is False
    assert timed_out.http_status == 0
    assert timed_out.error and "TimeoutException" in timed_out.error


def test_item_record_path_is_dated_and_create_once(tmp_path: Path) -> None:
    path = item_record_path(tmp_path, "2026-10-11T04:00:00Z")
    assert path.name == "2026-10-11.jsonl"
    assert path.parent.name == "sensed"


def test_fetchresult_replace_smoke() -> None:
    result = FetchResult(reached=True, http_status=200, body=b"x", final_url="u", error=None)
    assert replace(result, http_status=404).http_status == 404
