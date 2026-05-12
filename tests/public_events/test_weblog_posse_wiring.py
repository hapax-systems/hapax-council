"""Tests for Bridgy POSSE wiring into weblog event producer."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.weblog_publish_public_event_producer import (
    WeblogPublishPublicEventProducer,
    WeblogRssItem,
    bridgy_posse_callback,
    build_weblog_publish_public_event,
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
    guid: str = "https://hapax.weblog.lol/2026/05/test-post",
    title: str = "Test Post",
    link: str = "https://hapax.weblog.lol/2026/05/test-post",
    pub_date: str = "Sun, 10 May 2026 10:15:00 +0000",
) -> str:
    return f"""\
    <item>
      <title>{title}</title>
      <link>{link}</link>
      <guid>{guid}</guid>
      <pubDate>{pub_date}</pubDate>
      <description>Public weblog post.</description>
    </item>"""


def test_posse_callback_fires_on_new_event(tmp_path: Path) -> None:
    public = tmp_path / "public.jsonl"
    state = tmp_path / "state.json"
    callback = MagicMock()

    producer = WeblogPublishPublicEventProducer(
        rss_url=FEED_URL,
        public_event_path=public,
        state_path=state,
        fetcher=lambda _url: _rss(_item()),
        time_fn=lambda: NOW,
        emit_existing_on_first_run=True,
        posse_callback=callback,
    )

    assert producer.run_once() == 1
    assert callback.call_count == 1
    item_arg, event_arg = callback.call_args[0]
    assert isinstance(item_arg, WeblogRssItem)
    assert item_arg.link == "https://hapax.weblog.lol/2026/05/test-post"
    assert event_arg.event_type == "omg.weblog"


def test_posse_callback_not_fired_for_existing_items(tmp_path: Path) -> None:
    public = tmp_path / "public.jsonl"
    state = tmp_path / "state.json"
    callback = MagicMock()

    producer = WeblogPublishPublicEventProducer(
        rss_url=FEED_URL,
        public_event_path=public,
        state_path=state,
        fetcher=lambda _url: _rss(_item()),
        time_fn=lambda: NOW,
        emit_existing_on_first_run=False,
        posse_callback=callback,
    )

    producer.run_once()
    assert callback.call_count == 0


def test_posse_callback_not_fired_when_none(tmp_path: Path) -> None:
    public = tmp_path / "public.jsonl"
    state = tmp_path / "state.json"

    producer = WeblogPublishPublicEventProducer(
        rss_url=FEED_URL,
        public_event_path=public,
        state_path=state,
        fetcher=lambda _url: _rss(_item()),
        time_fn=lambda: NOW,
        emit_existing_on_first_run=True,
        posse_callback=None,
    )

    assert producer.run_once() == 1


def test_posse_callback_error_does_not_break_producer(tmp_path: Path) -> None:
    public = tmp_path / "public.jsonl"
    state = tmp_path / "state.json"
    callback = MagicMock(side_effect=RuntimeError("bridgy down"))

    producer = WeblogPublishPublicEventProducer(
        rss_url=FEED_URL,
        public_event_path=public,
        state_path=state,
        fetcher=lambda _url: _rss(_item()),
        time_fn=lambda: NOW,
        emit_existing_on_first_run=True,
        posse_callback=callback,
    )

    assert producer.run_once() == 1
    events = [json.loads(l) for l in public.read_text().splitlines()]
    assert len(events) == 1


def test_posse_fires_for_each_new_item(tmp_path: Path) -> None:
    public = tmp_path / "public.jsonl"
    state = tmp_path / "state.json"
    callback = MagicMock()

    producer = WeblogPublishPublicEventProducer(
        rss_url=FEED_URL,
        public_event_path=public,
        state_path=state,
        fetcher=lambda _url: _rss(
            _item(guid="post-1", title="Post 1", link="https://hapax.weblog.lol/2026/05/post-1"),
            _item(guid="post-2", title="Post 2", link="https://hapax.weblog.lol/2026/05/post-2"),
        ),
        time_fn=lambda: NOW,
        emit_existing_on_first_run=True,
        posse_callback=callback,
    )

    assert producer.run_once() == 2
    assert callback.call_count == 2


@patch("agents.publication_bus.bridgy_publisher.requests")
def test_bridgy_posse_callback_posts_webmention(mock_requests: MagicMock) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_requests.post.return_value = mock_response
    mock_requests.RequestException = Exception

    item = WeblogRssItem(
        item_id="post-1",
        title="Test Post",
        link="https://hapax.weblog.lol/2026/05/test-post",
        published_at="2026-05-10T10:15:00Z",
        description="A test.",
    )
    event = build_weblog_publish_public_event(item, feed_url=FEED_URL, generated_at=GENERATED_AT)

    bridgy_posse_callback(item, event)

    mock_requests.post.assert_called_once()
    call_kwargs = mock_requests.post.call_args
    assert call_kwargs[1]["data"]["source"] == "https://hapax.weblog.lol/2026/05/test-post"
    assert call_kwargs[1]["data"]["target"] == "https://hapax.omg.lol/weblog"


def test_bridgy_posse_callback_skips_when_no_link() -> None:
    item = WeblogRssItem(
        item_id="post-1",
        title="Test Post",
        link=None,
        published_at="2026-05-10T10:15:00Z",
        description="A test.",
    )
    event = build_weblog_publish_public_event(item, feed_url=FEED_URL, generated_at=GENERATED_AT)

    bridgy_posse_callback(item, event)
