"""Hapax weblog RSS feed validator — Phase 1 + Phase 2.

Per cc-task ``cold-contact-activitypub-rss-self-federate`` (Phase 1)
and ``self-federate-rss-cadence-closeout`` (Phase 2). Verifies
that the Hapax omg.lol weblog RSS feed is:

  1. Reachable (HTTP 200)
  2. Well-formed XML with a ``<channel>`` element (RSS 2.0 minimum)
  3. Items include Zenodo DOI cross-links where applicable

Phase 1 ships the validator + DOI extraction. **Phase 2 (this
revision) wires the weekly cadence (systemd timer, already deployed
in ``systemd/units/hapax-self-federate-rss.timer`` Sun 03:00 UTC)
and ntfy-on-validity-loss with on-disk dedup so the operator only
gets paged on a transition from valid → invalid, not on every
sustained-loss tick.** Deferred Phase 3 adds Bridgy Fed bridge
activation for ActivityPub.

Drop 5 anti-pattern noted: omg.lol does NOT serve native ActivityPub.
RSS is the native subscription surface; ActivityPub bridge requires
Bridgy Fed (operator decision).
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC
from pathlib import Path
from xml.etree import ElementTree as ET

from prometheus_client import Counter

from shared.notify import send_notification

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


DEFAULT_VALIDITY_STATE_PATH: Path = (
    Path.home() / ".cache" / "hapax" / "self-federate-rss-validity.json"
)
"""On-disk last-known validity state. Used for valid→invalid edge detection.

Written atomically (tmp + os.replace) so a partial-write does not
corrupt the next tick's edge detection. Schema:
    {"last_outcome": str, "captured_at": iso-8601 UTC}
"""


rss_validity_total = Counter(
    "hapax_self_federate_rss_validity_total",
    "Self-federate RSS validity-check outcomes per result.",
    ["outcome"],
)


rss_notification_total = Counter(
    "hapax_self_federate_rss_notification_total",
    "Self-federate validity-loss ntfy events sent per outcome.",
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


def load_validity_state(path: Path = DEFAULT_VALIDITY_STATE_PATH) -> str | None:
    """Return the last persisted outcome label, or None if no state yet."""
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    outcome = payload.get("last_outcome")
    return outcome if isinstance(outcome, str) else None


def write_validity_state(outcome: str, path: Path = DEFAULT_VALIDITY_STATE_PATH) -> None:
    """Atomically persist this tick's outcome label for next-tick edge detection."""
    from datetime import datetime

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_outcome": outcome,
        "captured_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def notify_on_validity_loss(prior_outcome: str | None, current_outcome: str) -> bool:
    """Send an ntfy if this tick's outcome is a transition into a non-ok state.

    Edge-triggered: notify only on ``prior == "ok" → current != "ok"`` or
    on the first observed non-ok outcome (``prior is None``). Sustained
    failure does not re-notify; recovery (``prior != "ok" → current == "ok"``)
    sends an explicit recovery notification.

    Returns True if a notification was sent, False otherwise.
    """
    if current_outcome == "ok":
        if prior_outcome is not None and prior_outcome != "ok":
            sent = send_notification(
                title="Hapax RSS feed recovered",
                message=(f"Self-federate RSS validity restored (prior outcome: {prior_outcome})."),
                priority="default",
                tags=["white_check_mark"],
            )
            rss_notification_total.labels(outcome="recovery").inc()
            return bool(sent)
        return False

    if prior_outcome == current_outcome:
        return False  # sustained failure — already notified once

    sent = send_notification(
        title="Hapax RSS feed validity loss",
        message=(
            f"Self-federate validator outcome={current_outcome} "
            f"at {DEFAULT_HAPAX_RSS_URL}. Subscribers may stop receiving "
            f"updates until the feed is restored."
        ),
        priority="high",
        tags=["warning", "rss"],
    )
    rss_notification_total.labels(outcome=current_outcome).inc()
    return bool(sent)


def _classify_outcome(xml: bytes | None) -> tuple[str, int, int]:
    """Map a fetch+parse result to an outcome label + counts.

    Returns ``(outcome, item_count, items_with_doi)``. Outcome labels are
    stable strings used both for Prometheus and for on-disk dedup state.
    """
    if xml is None:
        return ("transport-error", 0, 0)
    if not validate_rss(xml):
        return ("invalid-xml", 0, 0)
    items = extract_items(xml)
    augmented = items_with_doi_links(items)
    return ("ok", len(items), sum(1 for it in augmented if it["dois"]))


def main() -> int:
    """Single-pass validation entry for systemd timer.

    Fetches the Hapax weblog RSS feed; validates structure; logs item
    count + DOI cross-link coverage; emits Prometheus counter outcome;
    notifies the operator on the valid → invalid edge (and on recovery)
    via ``shared.notify.send_notification``. Daemon-friendly: every
    failure path is non-fatal; the function always returns 0.
    """
    logging.basicConfig(level=logging.INFO)
    xml = fetch_rss()
    outcome, item_count, doi_count = _classify_outcome(xml)
    rss_validity_total.labels(outcome=outcome).inc()

    if outcome == "ok":
        log.info(
            "RSS feed valid: %d items / %d with DOI cross-links",
            item_count,
            doi_count,
        )
    elif outcome == "invalid-xml":
        log.warning("RSS feed at %s is malformed", DEFAULT_HAPAX_RSS_URL)
    else:
        log.info("RSS fetch failed (%s); will retry next tick", outcome)

    prior = load_validity_state()
    notify_on_validity_loss(prior, outcome)
    write_validity_state(outcome)
    return 0


__all__ = [
    "DEFAULT_HAPAX_RSS_URL",
    "DEFAULT_VALIDITY_STATE_PATH",
    "DOI_PATTERN",
    "RSS_REQUEST_TIMEOUT_S",
    "_classify_outcome",
    "extract_items",
    "fetch_rss",
    "items_with_doi_links",
    "load_validity_state",
    "main",
    "notify_on_validity_loss",
    "rss_notification_total",
    "rss_validity_total",
    "validate_rss",
    "write_validity_state",
]


if __name__ == "__main__":
    raise SystemExit(main())
