"""Tests for the discourse sensing producer, slice 1 (foundation half).

Fixture tests per parser (Bluesky AppView JSON, RSS 2.0, Atom, Hacker News
Algolia JSON), the no-outward-act invariant (AST scan), the fetch layer's
own 404/timeout branches via a hermetic MockTransport, and the intake
record path. Direct tests for the source-list loader and each of its
refusal branches, the dedup/cadence state (round trip, missing file,
corruption), the intake write paths (dated JSONL, create-once run reports),
and the feed parser's pre-parse refusal of DTD and entity declarations.
All fixtures use synthetic handles, reserved example/test domains, or the
lab's own Bluesky DID (did:plc:j7apz47n5ox4if5urv43jhsi); no real public
figure's handle, name or URL appears here, because this repository is
public.

The run-level tests (reach reporting, dedup, cadence gating) live with the
runner half of the split.
"""

from __future__ import annotations

import ast
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path

import httpx
import pytest

import agents.discourse_sensing as pkg
from agents.discourse_sensing.fetch import FetchResult
from agents.discourse_sensing.intake import append_items, item_record_path, write_run_report
from agents.discourse_sensing.parsers import (
    SensedItem,
    parse_bluesky_feed,
    parse_feed,
    parse_hn_search,
)
from agents.discourse_sensing.sources import BLUESKY_APPVIEW, HN_SEARCH_BY_DATE, load_sources
from agents.discourse_sensing.state import SensingState, load_state, save_state, state_path

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


def test_parse_feed_refuses_dtd_and_entity_declarations_before_parsing() -> None:
    laughs = (
        b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
        b'<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>'
        b'<rss version="2.0"><channel><item><title>&lol2;</title>'
        b"<link>https://source-b.example/boom</link></item></channel></rss>"
    )
    with pytest.raises(ValueError, match="DOCTYPE") as excinfo:
        parse_feed(laughs, "rss-b", "https://source-b.example/feed")
    assert "refused before parsing" in str(excinfo.value)
    entity_only = b'<?xml version="1.0"?><rss version="2.0"><!ENTITY x "y"><channel/></rss>'
    with pytest.raises(ValueError, match="ENTITY"):
        parse_feed(entity_only, "rss-b", "https://source-b.example/feed")


def test_parse_feed_reports_malformed_xml_as_a_parse_failure() -> None:
    truncated = b"<rss version='2.0'><channel><item><title>snip"
    with pytest.raises(ValueError, match="not well-formed XML") as excinfo:
        parse_feed(truncated, "rss-b", "https://source-b.example/feed")
    assert "check or replace the source feed URL" in str(excinfo.value)


def test_parse_feed_rejects_a_feed_that_is_neither_rss_nor_atom() -> None:
    with pytest.raises(ValueError, match="neither an RSS 2.0 nor an Atom feed") as excinfo:
        parse_feed(
            b"<html><body>not a feed</body></html>", "rss-b", "https://source-b.example/feed"
        )
    assert "RSS or Atom feed URL" in str(excinfo.value)


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


# ---------------------------------------------------------- source list


def _entry(overrides: dict | None = None) -> dict:
    entry = {
        "id": "rss-b",
        "venue": "web",
        "kind": "rss_feed",
        "cadence_minutes": "60",
        "checked_at_source": "'2026-10-02'",
        "terms_note": "public web feed, read-only",
        "url": "https://source-b.example/feed",
    }
    if overrides:
        entry.update(overrides)
    return entry


def _sources_yaml(*entries: dict) -> str:
    lines = ["sources:"]
    for entry in entries:
        first = True
        for key, value in entry.items():
            lines.append(f"{'  - ' if first else '    '}{key}: {value}")
            first = False
    return "\n".join(lines) + "\n"


def _write_sources(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "SOURCES.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_load_sources_reads_the_declared_list(tmp_path: Path) -> None:
    bsky = _entry(
        {
            "id": "bsky-a",
            "venue": "bluesky",
            "kind": "bluesky_author_feed",
            "actor": LAB_DID,
        }
    )
    bsky.pop("url")
    hn = _entry(
        {
            "id": "hn-q",
            "venue": "hackernews",
            "kind": "hn_algolia_query",
            "query": "sensing synthesis",
        }
    )
    hn.pop("url")
    specs = load_sources(_write_sources(tmp_path, _sources_yaml(bsky, _entry(), hn)))
    assert [spec.id for spec in specs] == ["bsky-a", "rss-b", "hn-q"]
    bsky_spec, rss_spec, hn_spec = specs
    assert bsky_spec.address() == LAB_DID
    assert bsky_spec.request_url(0, 500) == (
        f"{BLUESKY_APPVIEW}?actor={LAB_DID}&filter=posts_no_reply&limit=100"
    )
    assert rss_spec.address() == "https://source-b.example/feed"
    assert rss_spec.request_url(0, 100) == rss_spec.url
    assert hn_spec.address() == "sensing synthesis"
    assert hn_spec.request_url(1700000000, 500) == (
        f"{HN_SEARCH_BY_DATE}?query=sensing%20synthesis&tags=story&hitsPerPage=50"
        "&numericFilters=created_at_i>1700000000"
    )


def test_load_sources_missing_file_names_the_repair(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="DISCOURSE_SENSING_SOURCES"):
        load_sources(tmp_path / "absent.yaml")


def test_load_sources_rejects_invalid_yaml(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid YAML"):
        load_sources(_write_sources(tmp_path, "sources: [oops\n"))


@pytest.mark.parametrize("body", ["sources: 7\n", "- one\n- two\n", "{}\n"])
def test_load_sources_requires_a_sources_list(tmp_path: Path, body: str) -> None:
    with pytest.raises(ValueError, match="top-level 'sources' list"):
        load_sources(_write_sources(tmp_path, body))


def test_load_sources_rejects_a_non_mapping_entry(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a mapping"):
        load_sources(_write_sources(tmp_path, "sources:\n  - just-a-string\n"))


def test_load_sources_reports_missing_required_fields(tmp_path: Path) -> None:
    entry = _entry()
    del entry["terms_note"]
    del entry["checked_at_source"]
    with pytest.raises(ValueError, match="lacks") as excinfo:
        load_sources(_write_sources(tmp_path, _sources_yaml(entry)))
    message = str(excinfo.value)
    assert "terms_note" in message and "checked_at_source" in message


def test_load_sources_rejects_an_unknown_kind(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="expected one of"):
        load_sources(_write_sources(tmp_path, _sources_yaml(_entry({"kind": "mastodon_account"}))))


def test_load_sources_requires_the_kind_address_field(tmp_path: Path) -> None:
    entry = _entry()
    del entry["url"]
    with pytest.raises(ValueError, match="non-empty url"):
        load_sources(_write_sources(tmp_path, _sources_yaml(entry)))


def test_load_sources_rejects_duplicate_ids(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="duplicate source id"):
        load_sources(_write_sources(tmp_path, _sources_yaml(_entry(), _entry())))


@pytest.mark.parametrize("cadence", ["'30'", "-5", "true", "1.5"])
def test_load_sources_rejects_a_bad_cadence(tmp_path: Path, cadence: str) -> None:
    with pytest.raises(ValueError, match="positive integer cadence_minutes"):
        load_sources(_write_sources(tmp_path, _sources_yaml(_entry({"cadence_minutes": cadence}))))


# ------------------------------------------------- dedup and cadence state


def test_state_round_trips_seen_hashes_and_last_success(tmp_path: Path) -> None:
    path = state_path(tmp_path)
    state = SensingState(
        seen={
            "hash-fresh-entry-0001": "2026-10-11T02:00:00Z",
            "hash-second-entry-0002": "2026-10-11T03:00:00Z",
        },
        last_success={"bsky-a": 1760164800, "rss-b": 1760168400},
    )
    save_state(path, state)
    loaded = load_state(path)
    assert loaded.seen == state.seen
    assert loaded.last_success == state.last_success
    assert not path.with_name(path.name + ".tmp").exists()


def test_state_missing_file_is_a_fresh_state(tmp_path: Path) -> None:
    loaded = load_state(tmp_path / "absent-state.json")
    assert loaded.seen == {}
    assert loaded.last_success == {}


def test_state_corruption_is_not_silently_tolerated(tmp_path: Path) -> None:
    path = state_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_state(path)


# ----------------------------------------------------- intake write paths


def _item(**overrides: object) -> SensedItem:
    fields: dict[str, object] = dict(
        source_id="rss-b",
        venue="rss",
        source_name="https://source-b.example/feed",
        canonical_url="https://source-b.example/fresh",
        handle="source-b.example",
        title="Fresh entry within the window",
        published_at="2026-10-11T02:00:00Z",
        content_hash="hash-fresh-entry-0001",
    )
    fields.update(overrides)
    return SensedItem(**fields)  # type: ignore[arg-type]


def test_append_items_writes_one_jsonl_record_per_item(tmp_path: Path) -> None:
    second = _item(
        canonical_url="https://source-b.example/second",
        content_hash="hash-second-entry-0002",
        external_url="https://source-a.example/second",
    )
    append_items(tmp_path, [_item(), second], "2026-10-11T04:00:00Z")
    lines = (tmp_path / "sensed" / "2026-10-11.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    assert len(records) == 2
    flat = records[0]
    assert flat["source_id"] == "rss-b"
    assert flat["venue"] == "rss"
    assert flat["first_seen_at"] == "2026-10-11T04:00:00Z"
    assert flat["content_hash"] == "hash-fresh-entry-0001"
    assert flat["title"] == "Fresh entry within the window"
    assert "external_url" not in flat
    assert records[1]["external_url"] == "https://source-a.example/second"


def test_append_items_with_no_items_creates_nothing(tmp_path: Path) -> None:
    append_items(tmp_path, [], "2026-10-11T04:00:00Z")
    assert not (tmp_path / "sensed").exists()


def test_write_run_report_is_create_once(tmp_path: Path) -> None:
    stamp = "20261011T040000Z"
    first = write_run_report(tmp_path, {"sources": 3, "new_items_total": 7}, stamp)
    again = write_run_report(tmp_path, {"sources": 99}, stamp)
    assert again == first
    assert json.loads(first.read_text(encoding="utf-8"))["sources"] == 3
