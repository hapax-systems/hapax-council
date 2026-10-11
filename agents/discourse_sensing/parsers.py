"""Payload parsers: fetched bytes become SensedItems with canonical URLs."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from xml.etree import ElementTree

ATOM_NS = "{http://www.w3.org/2005/Atom}"
HN_ITEM_URL = "https://news.ycombinator.com/item?id="
BSKY_POST_URL = "https://bsky.app/profile"
TITLE_CLIP = 280


def _clip_title(text: str) -> str:
    return text if len(text) <= TITLE_CLIP else text[: TITLE_CLIP - 1] + "…"


def _normalize_utc(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _content_hash(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SensedItem:
    source_id: str
    venue: str
    source_name: str
    canonical_url: str
    handle: str
    title: str
    published_at: str
    content_hash: str
    external_url: str | None = None


def parse_bluesky_feed(payload: dict, source_id: str, actor: str) -> list[SensedItem]:
    """Parse a public AppView getAuthorFeed response."""
    items: list[SensedItem] = []
    for entry in payload.get("feed", []):
        post = entry.get("post") or {}
        uri = str(post.get("uri") or "")
        if not uri:
            continue
        record = post.get("record") or {}
        author = post.get("author") or {}
        handle = str(author.get("handle") or actor)
        rkey = uri.rsplit("/", 1)[-1]
        items.append(
            SensedItem(
                source_id=source_id,
                venue="bluesky",
                source_name=actor,
                canonical_url=uri,
                handle=handle,
                title=_clip_title(str(record.get("text") or "")),
                published_at=_normalize_utc(_parse_iso(str(record.get("createdAt") or ""))),
                content_hash=_content_hash(uri, str(post.get("cid") or "")),
                external_url=f"{BSKY_POST_URL}/{handle}/post/{rkey}",
            )
        )
    return items


def _child_text(node: ElementTree.Element, tag: str) -> str:
    child = node.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _feed_host(feed_url: str) -> str:
    return urlparse(feed_url).netloc


def _parse_atom(
    root: ElementTree.Element, source_id: str, feed_url: str, host: str
) -> list[SensedItem]:
    items: list[SensedItem] = []
    for node in root.findall(f"{ATOM_NS}entry"):
        title = _child_text(node, f"{ATOM_NS}title")
        link = ""
        for candidate in node.findall(f"{ATOM_NS}link"):
            if candidate.get("rel", "alternate") == "alternate" and candidate.get("href"):
                link = candidate.get("href") or ""
                break
        if not link:
            link = _child_text(node, f"{ATOM_NS}id")
        if not link:
            continue
        published_text = _child_text(node, f"{ATOM_NS}published") or _child_text(
            node, f"{ATOM_NS}updated"
        )
        items.append(
            SensedItem(
                source_id=source_id,
                venue="rss",
                source_name=feed_url,
                canonical_url=link,
                handle=host,
                title=_clip_title(title),
                published_at=_normalize_utc(_parse_iso(published_text)),
                content_hash=_content_hash(link, title),
            )
        )
    return items


def parse_feed(body: bytes, source_id: str, feed_url: str) -> list[SensedItem]:
    """Parse an RSS 2.0 or Atom feed into sensed items."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise ValueError(f"{feed_url}: feed is not well-formed XML ({exc})") from exc
    host = _feed_host(feed_url)
    if root.tag == f"{ATOM_NS}feed":
        return _parse_atom(root, source_id, feed_url, host)
    channel = root if root.tag == "channel" else root.find("channel")
    if channel is None:
        raise ValueError(f"{feed_url}: neither an RSS 2.0 nor an Atom feed")
    items: list[SensedItem] = []
    for node in channel.findall("item"):
        title = _child_text(node, "title")
        link = _child_text(node, "link")
        if not link:
            continue
        canonical = link
        guid = node.find("guid")
        if guid is not None:
            guid_text = (guid.text or "").strip()
            if guid_text and guid.get("isPermaLink", "true") != "false":
                canonical = guid_text
        published: datetime | None = None
        pub_date = _child_text(node, "pubDate")
        if pub_date:
            try:
                published = parsedate_to_datetime(pub_date)
            except (TypeError, ValueError):
                published = None
        items.append(
            SensedItem(
                source_id=source_id,
                venue="rss",
                source_name=feed_url,
                canonical_url=canonical,
                handle=host,
                title=_clip_title(title),
                published_at=_normalize_utc(published),
                content_hash=_content_hash(link, title),
            )
        )
    return items


def parse_hn_search(payload: dict, source_id: str, query: str) -> list[SensedItem]:
    """Parse a Hacker News Algolia search_by_date response."""
    items: list[SensedItem] = []
    for hit in payload.get("hits", []):
        object_id = str(hit.get("objectID") or "")
        if not object_id:
            continue
        title = _clip_title(str(hit.get("title") or ""))
        external_url = hit.get("url") or None
        items.append(
            SensedItem(
                source_id=source_id,
                venue="hackernews",
                source_name=query,
                canonical_url=f"{HN_ITEM_URL}{object_id}",
                handle=str(hit.get("author") or ""),
                title=title,
                published_at=_normalize_utc(_parse_iso(str(hit.get("created_at") or ""))),
                content_hash=_content_hash(object_id, title, str(external_url or "")),
                external_url=str(external_url) if external_url else None,
            )
        )
    return items
