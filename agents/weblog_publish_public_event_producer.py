"""Produce canonical public events from the Hapax omg.lol weblog RSS feed.

The producer polls the public weblog RSS feed and emits one
``ResearchVehiclePublicEvent`` per newly observed post. It keeps its own
seen-item state so a fresh daemon start does not repost the whole feed by
default; pass ``--emit-existing`` for an explicit backfill. Direct Bridgy
POSSE is opt-in with ``--posse``; the default runtime path writes the bus only.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from hashlib import sha256
from pathlib import Path
from xml.etree import ElementTree as ET

from shared.research_vehicle_public_event import (
    PrivacyClass,
    PublicEventChapterRef,
    PublicEventProvenance,
    PublicEventSource,
    PublicEventSurfacePolicy,
    ResearchVehiclePublicEvent,
    RightsClass,
    Surface,
)

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

DEFAULT_RSS_URL = os.environ.get(
    "HAPAX_WEBLOG_PUBLISH_RSS_URL",
    "https://hapax.weblog.lol/rss.xml",
)
RSS_REQUEST_TIMEOUT_S = float(os.environ.get("HAPAX_WEBLOG_PUBLISH_RSS_TIMEOUT_S", "30"))
PUBLIC_EVENT_PATH = Path(
    os.environ.get(
        "HAPAX_RESEARCH_VEHICLE_PUBLIC_EVENT_PATH",
        "/dev/shm/hapax-public-events/events.jsonl",
    )
)
STATE_PATH = Path(
    os.environ.get(
        "HAPAX_WEBLOG_PUBLISH_EVENT_STATE",
        str(Path.home() / ".cache/hapax/weblog-publish-public-event-state.json"),
    )
)
DEFAULT_TICK_S = float(os.environ.get("HAPAX_WEBLOG_PUBLISH_EVENT_TICK_S", "60"))
TASK_ANCHOR = "weblog-publish-event-producer"

_PUBLIC_SAFE_RIGHTS = {"operator_original", "operator_controlled", "third_party_attributed"}
_PUBLIC_SAFE_PRIVACY = {"public_safe", "aggregate_only"}
_WEBLOG_ALLOWED_SURFACES: tuple[Surface, ...] = (
    "mastodon",
    "bluesky",
    "arena",
    "archive",
)
_WEBLOG_DENIED_SURFACES: tuple[Surface, ...] = (
    "youtube_description",
    "youtube_cuepoints",
    "youtube_chapters",
    "youtube_captions",
    "youtube_shorts",
    "youtube_channel_sections",
    "youtube_channel_trailer",
    "omg_statuslog",
    "omg_weblog",
    "omg_now",
    "discord",
    "replay",
    "github_readme",
    "github_profile",
    "github_release",
    "github_package",
    "github_pages",
    "zenodo",
    "captions",
    "cuepoints",
    "health",
    "monetization",
)

FetchRss = Callable[[str], bytes | None]
TimeFn = Callable[[], float]
PosseCallback = Callable[["WeblogRssItem", "ResearchVehiclePublicEvent"], None]


@dataclass(frozen=True)
class WeblogPublishPolicyConfig:
    """Policy defaults for mapping RSS items to public events."""

    source_substrate_id: str = "omg_lol_weblog_rss"
    rights_class: RightsClass = "operator_original"
    privacy_class: PrivacyClass = "public_safe"
    rights_basis: str = "operator-authored weblog entry published on hapax.weblog.lol"
    task_anchor: str = TASK_ANCHOR
    salience: float = 0.74


@dataclass(frozen=True)
class WeblogRssItem:
    """Minimal RSS item shape needed for public-event emission."""

    item_id: str
    title: str
    link: str | None
    published_at: str | None
    description: str


class WeblogPublishPublicEventProducer:
    """Poll weblog RSS and append canonical RVPE rows for new posts."""

    def __init__(
        self,
        *,
        rss_url: str = DEFAULT_RSS_URL,
        public_event_path: Path = PUBLIC_EVENT_PATH,
        state_path: Path = STATE_PATH,
        policy: WeblogPublishPolicyConfig | None = None,
        fetcher: FetchRss | None = None,
        time_fn: TimeFn = time.time,
        emit_existing_on_first_run: bool = False,
        posse_callback: PosseCallback | None = None,
    ) -> None:
        self._rss_url = rss_url
        self._public_event_path = public_event_path
        self._state_path = state_path
        self._policy = policy or WeblogPublishPolicyConfig()
        self._fetcher = fetcher or fetch_rss
        self._time = time_fn
        self._emit_existing_on_first_run = emit_existing_on_first_run
        self._posse_callback = posse_callback
        self._known_event_ids: set[str] | None = None

    def run_once(self) -> int:
        """Fetch one RSS snapshot and write events for unseen posts."""

        xml = self._fetcher(self._rss_url)
        if xml is None:
            return 0

        items = parse_weblog_rss_items(xml)
        if not items:
            log.warning("weblog RSS snapshot had no parseable items")
            return 0

        seen, state_exists = self._read_seen_item_ids()
        current_ids = {item.item_id for item in items}
        if not state_exists and not self._emit_existing_on_first_run:
            self._write_seen_item_ids(current_ids)
            log.info("seeded weblog RSS baseline with %d existing item(s)", len(current_ids))
            return 0

        written = 0
        changed = not state_exists
        for item in reversed(items):
            if item.item_id in seen:
                continue
            event = build_weblog_publish_public_event(
                item,
                feed_url=self._rss_url,
                generated_at=_iso_from_epoch(self._time()),
                policy=self._policy,
            )
            if self._event_already_written(event.event_id):
                seen.add(item.item_id)
                changed = True
                continue
            if not self._append_public_event(event):
                break
            self._fire_posse(item, event)
            seen.add(item.item_id)
            changed = True
            written += 1

        if changed:
            self._write_seen_item_ids(seen)
        return written

    def _append_public_event(self, event: ResearchVehiclePublicEvent) -> bool:
        try:
            self._public_event_path.parent.mkdir(parents=True, exist_ok=True)
            with self._public_event_path.open("a", encoding="utf-8") as fh:
                fh.write(event.to_json_line())
        except OSError:
            log.warning("public event write failed at %s", self._public_event_path, exc_info=True)
            return False
        if self._known_event_ids is not None:
            self._known_event_ids.add(event.event_id)
        return True

    def _fire_posse(self, item: WeblogRssItem, event: ResearchVehiclePublicEvent) -> None:
        if self._posse_callback is None:
            return
        try:
            self._posse_callback(item, event)
        except Exception:
            log.warning("POSSE callback failed for %s", event.event_id, exc_info=True)

    def _event_already_written(self, event_id: str) -> bool:
        if self._known_event_ids is None:
            self._known_event_ids = _load_event_ids(self._public_event_path)
        return event_id in self._known_event_ids

    def _read_seen_item_ids(self) -> tuple[set[str], bool]:
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return set(), False
        except (json.JSONDecodeError, OSError):
            log.warning(
                "weblog publish state unreadable at %s; treating as empty", self._state_path
            )
            return set(), True
        ids = payload.get("seen_item_ids") if isinstance(payload, dict) else None
        if not isinstance(ids, list):
            return set(), True
        return {item for item in ids if isinstance(item, str) and item}, True

    def _write_seen_item_ids(self, item_ids: set[str]) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_path.with_suffix(".tmp")
            payload = {
                "schema_version": 1,
                "seen_item_ids": sorted(item_ids),
                "last_checked_at": _iso_from_epoch(self._time()),
            }
            tmp.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
            tmp.replace(self._state_path)
        except OSError:
            log.warning("weblog publish state write failed at %s", self._state_path, exc_info=True)


def fetch_rss(url: str = DEFAULT_RSS_URL) -> bytes | None:
    """GET the weblog RSS feed and return raw XML bytes."""

    if requests is None:
        log.warning("requests library not available; skipping weblog RSS fetch")
        return None
    try:
        response = requests.get(url, timeout=RSS_REQUEST_TIMEOUT_S)
    except requests.RequestException as exc:
        log.warning("weblog RSS fetch raised: %s", exc)
        return None
    if response.status_code != 200:
        log.warning("weblog RSS fetch returned HTTP %s", response.status_code)
        return None
    return response.content


def parse_weblog_rss_items(xml_bytes: bytes) -> list[WeblogRssItem]:
    """Parse RSS 2.0 ``<item>`` rows from a feed snapshot."""

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    channel = _first_child(root, "channel")
    if channel is None:
        return []

    items: list[WeblogRssItem] = []
    for item in _children(channel, "item"):
        title = _text_or_empty(item, "title")
        link = _clean_optional_str(_text_or_empty(item, "link"))
        guid = _clean_optional_str(_text_or_empty(item, "guid"))
        pub_date = _clean_optional_str(_text_or_empty(item, "pubDate"))
        description = _text_or_empty(item, "description")
        fallback_id = ":".join(part for part in (title, link or "", pub_date or "") if part)
        item_id = guid or link or _clean_optional_str(fallback_id)
        if item_id is None:
            continue
        items.append(
            WeblogRssItem(
                item_id=item_id,
                title=title or "Weblog post",
                link=link,
                published_at=_normalise_rss_datetime(pub_date),
                description=description,
            )
        )
    return items


def build_weblog_publish_public_event(
    item: WeblogRssItem,
    *,
    feed_url: str,
    generated_at: str,
    policy: WeblogPublishPolicyConfig | None = None,
) -> ResearchVehiclePublicEvent:
    """Map one weblog RSS item to an ``omg.weblog`` public event."""

    cfg = policy or WeblogPublishPolicyConfig()
    event_id = weblog_publish_event_id(item)
    occurred_at = item.published_at or generated_at
    provenance_token = f"omg_weblog:{event_id}" if item.link else None
    blockers = _policy_blockers(item=item, provenance_token=provenance_token, policy=cfg)
    surface_policy = _surface_policy(blockers=blockers)
    evidence_ref = f"{feed_url}#item={_short_digest(item.item_id)}"
    return ResearchVehiclePublicEvent(
        schema_version=1,
        event_id=event_id,
        event_type="omg.weblog",
        occurred_at=occurred_at,
        broadcast_id=None,
        programme_id=None,
        condition_id=None,
        source=PublicEventSource(
            producer="agents.weblog_publish_public_event_producer",
            substrate_id=cfg.source_substrate_id,
            task_anchor=cfg.task_anchor,
            evidence_ref=evidence_ref,
            freshness_ref="rss.item.pubDate",
        ),
        salience=cfg.salience,
        state_kind="public_post",
        rights_class=cfg.rights_class,
        privacy_class=cfg.privacy_class,
        provenance=PublicEventProvenance(
            token=provenance_token,
            generated_at=generated_at,
            producer="agents.weblog_publish_public_event_producer",
            evidence_refs=_evidence_refs(blockers),
            rights_basis=cfg.rights_basis,
            citation_refs=[item.link] if item.link else [],
        ),
        public_url=item.link,
        frame_ref=None,
        chapter_ref=PublicEventChapterRef(
            kind="chapter",
            label=item.title,
            timecode="00:00",
            source_event_id=event_id,
        ),
        attribution_refs=[],
        surface_policy=surface_policy,
    )


def weblog_publish_event_id(item: WeblogRssItem) -> str:
    """Stable idempotency key for one weblog RSS item."""

    slug_source = item.link or item.title or item.item_id
    slug = _slug_from_url_or_text(slug_source)
    digest = _short_digest(item.item_id)
    return _sanitize_event_id(f"rvpe:omg_weblog:{slug}:{digest}")


def _policy_blockers(
    *,
    item: WeblogRssItem,
    provenance_token: str | None,
    policy: WeblogPublishPolicyConfig,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if not item.link:
        blockers.append("missing_public_url")
    if provenance_token is None:
        blockers.append("missing_provenance")
    if policy.rights_class not in _PUBLIC_SAFE_RIGHTS:
        blockers.append("rights_blocked")
    if policy.privacy_class not in _PUBLIC_SAFE_PRIVACY:
        blockers.append("privacy_blocked")
    return tuple(dict.fromkeys(blockers))


def _surface_policy(*, blockers: tuple[str, ...]) -> PublicEventSurfacePolicy:
    if blockers:
        return PublicEventSurfacePolicy(
            allowed_surfaces=[],
            denied_surfaces=[*_WEBLOG_ALLOWED_SURFACES, *_WEBLOG_DENIED_SURFACES],
            claim_live=False,
            claim_archive=False,
            claim_monetizable=False,
            requires_egress_public_claim=False,
            requires_audio_safe=False,
            requires_provenance=True,
            requires_human_review=False,
            rate_limit_key="omg.weblog:public_post",
            redaction_policy="none",
            fallback_action="hold",
            dry_run_reason=";".join(blockers),
        )
    return PublicEventSurfacePolicy(
        allowed_surfaces=list(_WEBLOG_ALLOWED_SURFACES),
        denied_surfaces=list(_WEBLOG_DENIED_SURFACES),
        claim_live=False,
        claim_archive=True,
        claim_monetizable=False,
        requires_egress_public_claim=False,
        requires_audio_safe=False,
        requires_provenance=True,
        requires_human_review=False,
        rate_limit_key="omg.weblog:public_post",
        redaction_policy="none",
        fallback_action="hold",
        dry_run_reason=None,
    )


def _evidence_refs(blockers: tuple[str, ...]) -> list[str]:
    refs = [
        "omg.lol.weblog.rss",
        "rss.item.guid",
        "rss.item.link",
        "rss.item.pubDate",
    ]
    refs.extend(f"blocker:{blocker}" for blocker in blockers)
    return refs


def _load_event_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ids
    for raw in lines:
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and isinstance(item.get("event_id"), str):
            ids.add(item["event_id"])
    return ids


def _children(element: ET.Element, tag: str) -> list[ET.Element]:
    return [child for child in list(element) if _local_name(child.tag) == tag]


def _first_child(element: ET.Element, tag: str) -> ET.Element | None:
    for child in list(element):
        if _local_name(child.tag) == tag:
            return child
    return None


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _text_or_empty(element: ET.Element, tag: str) -> str:
    found = _first_child(element, tag)
    if found is None or found.text is None:
        return ""
    return found.text.strip()


def _clean_optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _normalise_rss_datetime(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _iso_from_epoch(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s, tz=UTC).isoformat().replace("+00:00", "Z")


def _short_digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()[:16]


def _slug_from_url_or_text(value: str) -> str:
    text = value.rstrip("/").rsplit("/", 1)[-1] if "://" in value else value
    text = re.sub(r"\.[a-z0-9]{2,5}$", "", text.lower())
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text[:48] or "post"


def _sanitize_event_id(value: str) -> str:
    lowered = value.lower().replace("+00:00", "z")
    cleaned = re.sub(r"[^a-z0-9_:]+", "_", lowered)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_:")
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"rvpe:{cleaned}"
    return cleaned


BRIDGY_ALLOWLIST_TARGET = "https://hapax.omg.lol/weblog"


def bridgy_posse_callback(item: WeblogRssItem, event: ResearchVehiclePublicEvent) -> None:
    """Fire Bridgy webmention for POSSE fanout to Mastodon + Bluesky."""
    if not item.link:
        log.info("POSSE skipped (no link): %s", event.event_id)
        return
    from agents.publication_bus.bridgy_publisher import BridgyPublisher
    from agents.publication_bus.publisher_kit.base import PublisherPayload

    publisher = BridgyPublisher()
    payload = PublisherPayload(
        target=BRIDGY_ALLOWLIST_TARGET,
        text=item.link,
    )
    result = publisher.publish(payload)
    if result.ok:
        log.info("POSSE OK via Bridgy for %s", item.link)
    elif result.refused:
        log.warning("POSSE refused for %s: %s", item.link, result.detail)
    else:
        log.warning("POSSE error for %s: %s", item.link, result.detail)


def _run_forever(producer: WeblogPublishPublicEventProducer, tick_s: float) -> None:
    stop = False

    def _stop(*_args: object) -> None:
        nonlocal stop
        stop = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _stop)
        except ValueError:
            pass
    while not stop:
        producer.run_once()
        time.sleep(max(1.0, tick_s))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="process one RSS snapshot and exit")
    parser.add_argument("--rss-url", default=DEFAULT_RSS_URL)
    parser.add_argument("--public-event-path", type=Path, default=PUBLIC_EVENT_PATH)
    parser.add_argument("--state-path", type=Path, default=STATE_PATH)
    parser.add_argument("--tick-s", type=float, default=DEFAULT_TICK_S)
    parser.add_argument(
        "--emit-existing",
        action="store_true",
        help="emit current feed items on first run instead of seeding a baseline",
    )
    posse_group = parser.add_mutually_exclusive_group()
    posse_group.add_argument(
        "--posse",
        dest="posse",
        action="store_true",
        help="enable direct Bridgy POSSE fanout to Mastodon/Bluesky",
    )
    posse_group.add_argument(
        "--no-posse",
        dest="posse",
        action="store_false",
        help="keep default RVPE-only behavior without direct Bridgy POSSE",
    )
    parser.set_defaults(posse=False)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", os.environ.get("HAPAX_LOG_LEVEL", "INFO"))
    )
    posse_cb = bridgy_posse_callback if args.posse else None
    producer = WeblogPublishPublicEventProducer(
        rss_url=args.rss_url,
        public_event_path=args.public_event_path,
        state_path=args.state_path,
        emit_existing_on_first_run=args.emit_existing,
        posse_callback=posse_cb,
    )
    if args.once:
        return 0 if producer.run_once() >= 0 else 1
    _run_forever(producer, args.tick_s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_RSS_URL",
    "RSS_REQUEST_TIMEOUT_S",
    "TASK_ANCHOR",
    "WeblogPublishPolicyConfig",
    "WeblogPublishPublicEventProducer",
    "WeblogRssItem",
    "bridgy_posse_callback",
    "build_weblog_publish_public_event",
    "fetch_rss",
    "main",
    "parse_weblog_rss_items",
    "weblog_publish_event_id",
]
