"""Weblog RSS ResearchVehiclePublicEvent producer tests."""

from __future__ import annotations

import json
from pathlib import Path

from agents.weblog_publish_public_event_producer import (
    WeblogPublishPolicyConfig,
    WeblogPublishPublicEventProducer,
    WeblogRssItem,
    build_weblog_publish_public_event,
    parse_weblog_rss_items,
    weblog_publish_event_id,
)

NOW = 1_777_777_777.0
GENERATED_AT = "2026-05-10T10:30:00Z"
FEED_URL = "https://hapax.weblog.lol/rss.xml"


def _rss(*items: str) -> bytes:
    body = "\n".join(items)
    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Hapax weblog</title>
    <link>https://hapax.weblog.lol</link>
    <description>Infrastructure as argument.</description>
    {body}
  </channel>
</rss>
""".encode()


def _item(
    *,
    guid: str,
    title: str,
    link: str,
    pub_date: str = "Sun, 10 May 2026 10:15:00 +0000",
) -> str:
    return f"""\
    <item>
      <title>{title}</title>
      <link>{link}</link>
      <guid>{guid}</guid>
      <pubDate>{pub_date}</pubDate>
      <description>Public weblog post.</description>
    </item>
"""


def _read_public_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_parse_weblog_rss_items_extracts_stable_fields() -> None:
    items = parse_weblog_rss_items(
        _rss(
            _item(
                guid="https://hapax.weblog.lol/visibility-engine",
                title="Visibility Engine Online",
                link="https://hapax.weblog.lol/visibility-engine",
            )
        )
    )

    assert len(items) == 1
    assert items[0].item_id == "https://hapax.weblog.lol/visibility-engine"
    assert items[0].title == "Visibility Engine Online"
    assert items[0].link == "https://hapax.weblog.lol/visibility-engine"
    assert items[0].published_at == "2026-05-10T10:15:00Z"


def test_build_weblog_event_maps_to_social_fanout_policy() -> None:
    item = WeblogRssItem(
        item_id="https://hapax.weblog.lol/visibility-engine",
        title="Visibility Engine Online",
        link="https://hapax.weblog.lol/visibility-engine",
        published_at="2026-05-10T10:15:00Z",
        description="Public weblog post.",
    )

    event = build_weblog_publish_public_event(
        item,
        feed_url=FEED_URL,
        generated_at=GENERATED_AT,
    )

    assert event.event_type == "omg.weblog"
    assert event.state_kind == "public_post"
    assert event.occurred_at == "2026-05-10T10:15:00Z"
    assert event.public_url == "https://hapax.weblog.lol/visibility-engine"
    assert event.source.producer == "agents.weblog_publish_public_event_producer"
    assert event.source.task_anchor == "weblog-publish-event-producer"
    assert event.provenance.token == f"omg_weblog:{event.event_id}"
    assert event.chapter_ref is not None
    assert event.chapter_ref.label == "Visibility Engine Online"
    assert event.surface_policy.claim_live is False
    assert event.surface_policy.claim_archive is True
    assert event.surface_policy.requires_egress_public_claim is False
    assert event.surface_policy.dry_run_reason is None
    for surface in ("mastodon", "bluesky", "arena", "archive"):
        assert surface in event.surface_policy.allowed_surfaces


def test_build_weblog_event_fails_closed_without_public_url() -> None:
    item = WeblogRssItem(
        item_id="guid-only",
        title="Untethered",
        link=None,
        published_at=None,
        description="No link.",
    )

    event = build_weblog_publish_public_event(
        item,
        feed_url=FEED_URL,
        generated_at=GENERATED_AT,
        policy=WeblogPublishPolicyConfig(),
    )

    assert event.public_url is None
    assert event.provenance.token is None
    assert event.surface_policy.allowed_surfaces == []
    assert event.surface_policy.dry_run_reason is not None
    assert "missing_public_url" in event.surface_policy.dry_run_reason
    assert "missing_provenance" in event.surface_policy.dry_run_reason


def test_first_run_seeds_baseline_without_backfill(tmp_path: Path) -> None:
    public = tmp_path / "events.jsonl"
    state = tmp_path / "state.json"
    producer = WeblogPublishPublicEventProducer(
        rss_url=FEED_URL,
        public_event_path=public,
        state_path=state,
        fetcher=lambda _url: _rss(
            _item(
                guid="post-1",
                title="Existing post",
                link="https://hapax.weblog.lol/existing-post",
            )
        ),
        time_fn=lambda: NOW,
    )

    assert producer.run_once() == 0
    assert not public.exists()
    payload = json.loads(state.read_text(encoding="utf-8"))
    assert payload["seen_item_ids"] == ["post-1"]


def test_producer_emits_only_items_new_after_baseline(tmp_path: Path) -> None:
    public = tmp_path / "events.jsonl"
    state = tmp_path / "state.json"
    snapshots = [
        _rss(
            _item(
                guid="post-1",
                title="Existing post",
                link="https://hapax.weblog.lol/existing-post",
            )
        )
    ]
    producer = WeblogPublishPublicEventProducer(
        rss_url=FEED_URL,
        public_event_path=public,
        state_path=state,
        fetcher=lambda _url: snapshots[-1],
        time_fn=lambda: NOW,
    )

    assert producer.run_once() == 0
    snapshots.append(
        _rss(
            _item(
                guid="post-2",
                title="New post",
                link="https://hapax.weblog.lol/new-post",
                pub_date="Sun, 10 May 2026 10:45:00 +0000",
            ),
            _item(
                guid="post-1",
                title="Existing post",
                link="https://hapax.weblog.lol/existing-post",
            ),
        )
    )

    assert producer.run_once() == 1
    events = _read_public_events(public)
    assert len(events) == 1
    assert events[0]["event_type"] == "omg.weblog"
    assert events[0]["public_url"] == "https://hapax.weblog.lol/new-post"
    assert events[0]["chapter_ref"]["label"] == "New post"
    payload = json.loads(state.read_text(encoding="utf-8"))
    assert payload["seen_item_ids"] == ["post-1", "post-2"]


def test_emit_existing_allows_intentional_backfill(tmp_path: Path) -> None:
    public = tmp_path / "events.jsonl"
    state = tmp_path / "state.json"
    producer = WeblogPublishPublicEventProducer(
        rss_url=FEED_URL,
        public_event_path=public,
        state_path=state,
        fetcher=lambda _url: _rss(
            _item(
                guid="newer",
                title="Newer post",
                link="https://hapax.weblog.lol/newer-post",
            ),
            _item(
                guid="older",
                title="Older post",
                link="https://hapax.weblog.lol/older-post",
                pub_date="Sun, 10 May 2026 09:45:00 +0000",
            ),
        ),
        time_fn=lambda: NOW,
        emit_existing_on_first_run=True,
    )

    assert producer.run_once() == 2
    events = _read_public_events(public)
    assert [event["chapter_ref"]["label"] for event in events] == ["Older post", "Newer post"]
    payload = json.loads(state.read_text(encoding="utf-8"))
    assert payload["seen_item_ids"] == ["newer", "older"]


def test_existing_public_event_id_prevents_duplicate_after_state_loss(tmp_path: Path) -> None:
    public = tmp_path / "events.jsonl"
    state = tmp_path / "state.json"
    item = WeblogRssItem(
        item_id="post-1",
        title="Existing post",
        link="https://hapax.weblog.lol/existing-post",
        published_at="2026-05-10T10:15:00Z",
        description="Public weblog post.",
    )
    public.write_text(
        json.dumps({"event_id": weblog_publish_event_id(item), "event_type": "omg.weblog"}) + "\n",
        encoding="utf-8",
    )
    producer = WeblogPublishPublicEventProducer(
        rss_url=FEED_URL,
        public_event_path=public,
        state_path=state,
        fetcher=lambda _url: _rss(
            _item(
                guid="post-1",
                title="Existing post",
                link="https://hapax.weblog.lol/existing-post",
            )
        ),
        time_fn=lambda: NOW,
        emit_existing_on_first_run=True,
    )

    assert producer.run_once() == 0
    assert len(public.read_text(encoding="utf-8").splitlines()) == 1
    payload = json.loads(state.read_text(encoding="utf-8"))
    assert payload["seen_item_ids"] == ["post-1"]
