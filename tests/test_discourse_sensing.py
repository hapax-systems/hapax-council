"""Tests for the discourse sensing producer, slice 1.

Fixture tests per parser (Bluesky AppView JSON, RSS 2.0, Atom, Hacker News
Algolia JSON), the no-outward-act invariant (AST scan), and the
unreachable-not-"no items" invariant. All fixtures use synthetic handles,
reserved example/test domains, or the lab's own Bluesky DID
(did:plc:j7apz47n5ox4if5urv43jhsi); no real public figure's handle, name or
URL appears here, because this repository is public.
"""

from __future__ import annotations

import ast
import json
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
from agents.discourse_sensing.run import run_once
from agents.discourse_sensing.sources import load_sources

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


def _sources_yaml(tmp_path: Path) -> Path:
    path = tmp_path / "SOURCES.yaml"
    path.write_text(
        "\n".join(
            [
                "version: 1",
                "sources:",
                "  - id: bsky-a",
                "    venue: bluesky",
                "    kind: bluesky_author_feed",
                f"    actor: {LAB_DID}",
                "    cadence_minutes: 60",
                '    checked_at_source: "2026-10-11"',
                "    terms_note: synthetic fixture source",
                "  - id: rss-b",
                "    venue: rss",
                "    kind: rss_feed",
                "    url: https://source-b.example/feed",
                "    cadence_minutes: 60",
                '    checked_at_source: "2026-10-11"',
                "    terms_note: synthetic fixture source",
                "  - id: hn-q",
                "    venue: hackernews",
                "    kind: hn_algolia_query",
                "    query: synthetic query",
                "    cadence_minutes: 60",
                '    checked_at_source: "2026-10-11"',
                "    terms_note: synthetic fixture source",
                "  - id: rss-dead",
                "    venue: rss",
                "    kind: rss_feed",
                "    url: https://dead.example/feed",
                "    cadence_minutes: 60",
                '    checked_at_source: "2026-10-11"',
                "    terms_note: synthetic fixture source",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


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


# ------------------------------------------------------ reach and coverage


class _StubFetch:
    """Records requested URLs; serves canned fixture payloads by source."""

    def __init__(self, payloads: dict[str, object], failures: dict[str, FetchResult]) -> None:
        self.payloads = payloads
        self.failures = failures
        self.urls: list[str] = []

    def __call__(self, url: str, timeout_s: float = 20.0) -> FetchResult:
        self.urls.append(url)
        for key, result in self.failures.items():
            if key in url:
                return result
        for key, payload in self.payloads.items():
            if key in url:
                if isinstance(payload, FetchResult):
                    return payload
                body = (
                    payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
                )
                return FetchResult(
                    reached=True,
                    http_status=200,
                    body=body,
                    final_url=url,
                    error=None,
                )
        raise AssertionError(f"stub fetch got unexpected url {url!r}")


def _run_with_stub(tmp_path: Path, stub: _StubFetch, now_epoch: int) -> dict:
    import agents.discourse_sensing.run as run_module

    original = run_module.fetch_url
    run_module.fetch_url = stub
    try:
        return run_once(
            sources_path=_sources_yaml(tmp_path),
            intake_dir=tmp_path / "intake",
            now_epoch=now_epoch,
        )
    finally:
        run_module.fetch_url = original


def test_unreachable_source_is_reported_as_unreachable(tmp_path, monkeypatch) -> None:
    stub = _StubFetch(
        payloads={
            LAB_DID: _bluesky_payload(),
            "source-b.example": _rss_payload(),
            "hn.algolia.com": _hn_payload(),
        },
        failures={
            "dead.example": FetchResult(
                reached=False, http_status=404, body=b"", final_url="", error="HTTP 404"
            ),
        },
    )
    report = _run_with_stub(tmp_path, stub, now_epoch=int(NOW.timestamp()))
    by_id = {entry["source_id"]: entry for entry in report["sources"]}
    dead = by_id["rss-dead"]
    assert dead["unreachable"] is True
    assert dead["http_status"] == 404
    assert dead["items_returned"] == 0
    assert "error" in dead and dead["error"]
    # Reachable sources are never conflated with the unreachable one.
    assert by_id["rss-b"]["unreachable"] is False
    assert by_id["rss-b"]["items_returned"] == 2


def test_timeout_is_recorded_as_unreachable(tmp_path, monkeypatch) -> None:
    stub = _StubFetch(
        payloads={},
        failures={
            "source-b.example": FetchResult(
                reached=False, http_status=0, body=b"", final_url="", error="timeout"
            ),
            "dead.example": FetchResult(
                reached=False, http_status=0, body=b"", final_url="", error="timeout"
            ),
            LAB_DID: FetchResult(
                reached=False, http_status=0, body=b"", final_url="", error="timeout"
            ),
            "hn.algolia.com": FetchResult(
                reached=False, http_status=0, body=b"", final_url="", error="timeout"
            ),
        },
    )
    report = _run_with_stub(tmp_path, stub, now_epoch=int(NOW.timestamp()))
    assert report["sources"], "report must exist even when every source is unreachable"
    for entry in report["sources"]:
        assert entry["unreachable"] is True
        assert entry["items_returned"] == 0


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


def test_dedup_records_each_new_item_once(tmp_path, monkeypatch) -> None:
    stub = _StubFetch(
        payloads={
            LAB_DID: _bluesky_payload(),
            "source-b.example": _rss_payload(),
            "hn.algolia.com": _hn_payload(),
            "dead.example": FetchResult(
                reached=False, http_status=404, body=b"", final_url="", error="HTTP 404"
            ),
        },
        failures={},
    )
    now_epoch = int(NOW.timestamp())
    first = _run_with_stub(tmp_path, stub, now_epoch=now_epoch)
    by_id = {entry["source_id"]: entry for entry in first["sources"]}
    # Bootstrap window: the 3-day-old backlog item is seen but not recorded.
    assert by_id["rss-b"]["items_returned"] == 2
    assert by_id["rss-b"]["new_items"] == 1
    assert by_id["bsky-a"]["new_items"] == 2
    assert by_id["hn-q"]["new_items"] == 2
    records = (tmp_path / "intake" / "sensed").glob("*.jsonl")
    lines = [line for f in records for line in f.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 5
    record = json.loads(lines[0])
    assert set(record) >= {
        "source_id",
        "venue",
        "source",
        "canonical_url",
        "handle",
        "title",
        "published_at",
        "first_seen_at",
        "content_hash",
    }

    second = _run_with_stub(tmp_path, stub, now_epoch=now_epoch + 3600)
    by_id2 = {entry["source_id"]: entry for entry in second["sources"]}
    assert all(entry["new_items"] == 0 for entry in by_id2.values())
    lines2 = [
        line
        for f in (tmp_path / "intake" / "sensed").glob("*.jsonl")
        for line in f.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert len(lines2) == 5

    # An edited post (same URI, new cid/text) is a new item under the content hash.
    edited = _bluesky_payload()
    edited["feed"][0]["post"]["cid"] = "bafyreib4hhdh3wh4hNEW"
    edited["feed"][0]["post"]["record"]["text"] = "Edited synthetic first post."
    stub.payloads[LAB_DID] = edited
    third = _run_with_stub(tmp_path, stub, now_epoch=now_epoch + 7200)
    by_id3 = {entry["source_id"]: entry for entry in third["sources"]}
    assert by_id3["bsky-a"]["new_items"] == 1


def test_per_source_cadence_gates_fetch(tmp_path, monkeypatch) -> None:
    import agents.discourse_sensing.run as run_module
    from agents.discourse_sensing.state import load_state, save_state

    state_path = tmp_path / "intake" / ".sensing-state.json"
    state = load_state(state_path)
    now_epoch = int(NOW.timestamp())
    for spec in load_sources(_sources_yaml(tmp_path)):
        state.last_success[spec.id] = now_epoch - 30 * 60
    save_state(state_path, state)

    seen_urls: list[str] = []
    original = run_module.fetch_url

    def _spy(url: str, timeout_s: float = 20.0) -> FetchResult:
        seen_urls.append(url)
        return FetchResult(reached=False, http_status=404, body=b"", final_url=url, error="stubbed")

    run_module.fetch_url = _spy
    try:
        report = run_once(
            sources_path=_sources_yaml(tmp_path),
            intake_dir=tmp_path / "intake",
            now_epoch=now_epoch,
        )
    finally:
        run_module.fetch_url = original
    assert seen_urls == [], "no source is due 30 minutes into a 60-minute cadence"
    assert report["sources"] == [], "a run with no due sources reports no source rows"


def test_item_record_path_is_dated_and_create_once(tmp_path: Path) -> None:
    path = item_record_path(tmp_path, "2026-10-11T04:00:00Z")
    assert path.name == "2026-10-11.jsonl"
    assert path.parent.name == "sensed"


def test_fetchresult_replace_smoke() -> None:
    result = FetchResult(reached=True, http_status=200, body=b"x", final_url="u", error=None)
    assert replace(result, http_status=404).http_status == 404
