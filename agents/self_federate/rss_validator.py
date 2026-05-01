"""Hapax weblog RSS feed validator.

Per cc-task ``cold-contact-activitypub-rss-self-federate`` (Phase 1)
and ``self-federate-rss-cadence-closeout`` (Phase 2). Verifies that the
Hapax omg.lol weblog RSS feed is:

  1. Reachable (HTTP 200)
  2. Well-formed XML with a ``<channel>`` element (RSS 2.0 minimum)
  3. Items include Zenodo DOI cross-links where applicable

Phase 1 shipped the validator + DOI extraction. Phase 2 wires the
weekly cadence (``hapax-self-federate-rss.timer`` — Sun 03:00 UTC,
``Persistent=true``) and ntfy on validity loss in :func:`main`.
Deferred Phase 3 adds Bridgy Fed bridge activation for ActivityPub.

Drop 5 anti-pattern noted: omg.lol does NOT serve native ActivityPub.
RSS is the native subscription surface; ActivityPub bridge requires
Bridgy Fed (operator decision).
"""

from __future__ import annotations

import logging
import re
from xml.etree import ElementTree as ET

from prometheus_client import Counter

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

DEFAULT_HAPAX_RSS_URL: str = "https://hapax.weblog.lol/rss"
"""Operator-owned omg.lol weblog RSS feed.

Drop 5 §3: omg.lol weblog exposes RSS natively (via ytb-OMG8 shipped
infrastructure). This URL is the public-facing feed."""

RSS_REQUEST_TIMEOUT_S: float = 30.0

DOI_PATTERN: re.Pattern[str] = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
"""Crossref-spec DOI prefix pattern (10.NNNN/...). Matches both the
short slash-form (10.5281/zenodo.123) and bracketed forms in feed
description bodies."""


rss_validity_total = Counter(
    "hapax_self_federate_rss_validity_total",
    "Self-federate RSS validity-check outcomes per result.",
    ["outcome"],
)


def fetch_rss(url: str = DEFAULT_HAPAX_RSS_URL) -> bytes | None:
    """GET the RSS feed; return raw XML bytes or None on failure."""
    if requests is None:
        log.warning("requests library not available; skipping rss fetch")
        return None
    try:
        response = requests.get(url, timeout=RSS_REQUEST_TIMEOUT_S)
    except requests.RequestException as exc:
        log.warning("rss fetch raised: %s", exc)
        rss_validity_total.labels(outcome="transport-error").inc()
        return None
    if response.status_code != 200:
        rss_validity_total.labels(outcome=f"http-{response.status_code}").inc()
        return None
    return response.content


def validate_rss(xml_bytes: bytes) -> bool:
    """Return True iff ``xml_bytes`` is well-formed RSS 2.0 with a channel.

    The canonical RSS 2.0 spec requires `<rss><channel>...</channel></rss>`.
    This validator is intentionally minimal: parse-success + presence
    of `<channel>` is sufficient. Strict schema validation against the
    full RSS 2.0 spec is a Phase 2 concern.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return False
    return root.find("channel") is not None


def extract_items(xml_bytes: bytes) -> list[dict[str, str]]:
    """Pull `<item>` elements out of the feed; return list of dicts.

    Each dict carries ``title``, ``link``, ``pubDate``, ``description``
    (empty string if any field is missing). Malformed XML returns an
    empty list — the validator must remain operational on partial-data.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    channel = root.find("channel")
    if channel is None:
        return []
    items: list[dict[str, str]] = []
    for item in channel.findall("item"):
        items.append(
            {
                "title": _text_or_empty(item, "title"),
                "link": _text_or_empty(item, "link"),
                "pubDate": _text_or_empty(item, "pubDate"),
                "description": _text_or_empty(item, "description"),
            }
        )
    return items


def items_with_doi_links(items: list[dict[str, str]]) -> list[dict[str, object]]:
    """Augment each item dict with a ``dois`` list extracted from description.

    Uses the canonical Crossref DOI regex against the full description
    text. Items with zero DOIs get ``dois=[]`` (the cc-task spec is
    "include Zenodo DOI when applicable" — not every item has one).
    """
    augmented: list[dict[str, object]] = []
    for item in items:
        dois = DOI_PATTERN.findall(item.get("description", ""))
        augmented.append({**item, "dois": list(dois)})
    return augmented


def _text_or_empty(element: ET.Element, tag: str) -> str:
    found = element.find(tag)
    if found is None or found.text is None:
        return ""
    return found.text.strip()


def _notify_validity_loss(reason: str, url: str) -> None:
    """Push ntfy notification on RSS validity loss.

    Daemon-friendly: any send failure is swallowed so the validator
    exits 0 even if ntfy is down.
    """
    try:
        from shared.notify import send_notification

        send_notification(
            title="Hapax weblog RSS validity loss",
            message=f"{reason}: {url}",
            priority="default",
            tags=["self-federate", "rss"],
        )
    except Exception:
        log.debug("notify send failed", exc_info=True)


def main() -> int:
    """Single-pass validation entry for systemd timer.

    Fetches the Hapax weblog RSS feed; validates structure; logs item
    count + DOI cross-link coverage. On transport failure or malformed
    XML, pushes an ntfy notification so the operator notices the feed
    has gone bad between weekly ticks. Daemon-friendly: every failure
    path emits a counter outcome and exits 0.
    """
    logging.basicConfig(level=logging.INFO)
    xml = fetch_rss()
    if xml is None:
        log.info("RSS fetch failed; will retry next tick")
        _notify_validity_loss("RSS fetch failed", DEFAULT_HAPAX_RSS_URL)
        return 0
    if not validate_rss(xml):
        rss_validity_total.labels(outcome="invalid-xml").inc()
        log.warning("RSS feed at %s is malformed", DEFAULT_HAPAX_RSS_URL)
        _notify_validity_loss("RSS feed malformed", DEFAULT_HAPAX_RSS_URL)
        return 0
    items = extract_items(xml)
    augmented = items_with_doi_links(items)
    items_with_dois = sum(1 for it in augmented if it["dois"])
    rss_validity_total.labels(outcome="ok").inc()
    log.info(
        "RSS feed valid: %d items / %d with DOI cross-links",
        len(items),
        items_with_dois,
    )
    return 0


__all__ = [
    "DEFAULT_HAPAX_RSS_URL",
    "DOI_PATTERN",
    "RSS_REQUEST_TIMEOUT_S",
    "_notify_validity_loss",
    "extract_items",
    "fetch_rss",
    "items_with_doi_links",
    "main",
    "rss_validity_total",
    "validate_rss",
]


if __name__ == "__main__":
    raise SystemExit(main())
