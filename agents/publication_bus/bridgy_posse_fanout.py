"""Bridgy POSSE fanout — syndicate omg.lol weblog entries to Mastodon + Bluesky.

Wires the OmgLolWeblogPublisher → BridgyPublisher chain: when an
omg.lol weblog entry publishes successfully, this module fans out
webmentions to Bridgy for each configured syndication target (default:
Mastodon + Bluesky).

The fanout is a standalone function (not embedded in the publisher) to
match the V5 publication-bus convention: publishers are one-shot
emitters, orchestrators compose the chain.

Usage::

    from agents.publication_bus.bridgy_posse_fanout import posse_after_weblog_publish

    weblog_result = weblog_publisher.publish(payload)
    if weblog_result.ok:
        entry_url = f"https://hapax.omg.lol/weblog/{payload.target}"
        outcomes = posse_after_weblog_publish(entry_url=entry_url)
"""

from __future__ import annotations

import logging

from agents.publication_bus.bridgy_publisher import (
    BRIDGY_POSSE_TARGETS,
    BridgyPublisher,
)
from agents.publication_bus.publisher_kit.base import PublisherPayload, PublisherResult

log = logging.getLogger(__name__)

BRIDGY_PUBLISH_TARGET_PREFIX: str = "https://brid.gy/publish/"


def posse_after_weblog_publish(
    *,
    entry_url: str,
    targets: list[str] | None = None,
    publisher: BridgyPublisher | None = None,
) -> dict[str, PublisherResult]:
    """Fan out webmentions to Bridgy for each POSSE target.

    Args:
        entry_url: The published omg.lol entry URL that Bridgy should crawl.
        targets: Syndication target names (default: mastodon, bluesky).
        publisher: Optional pre-configured BridgyPublisher instance.

    Returns:
        ``{target_name: PublisherResult}`` for each target.
    """
    if targets is None:
        targets = list(BRIDGY_POSSE_TARGETS)
    if publisher is None:
        publisher = BridgyPublisher()

    outcomes: dict[str, PublisherResult] = {}
    for target_name in targets:
        bridgy_target = f"{BRIDGY_PUBLISH_TARGET_PREFIX}{target_name}"
        payload = PublisherPayload(target=bridgy_target, text=entry_url)
        result = publisher.publish(payload)
        outcomes[target_name] = result
        if result.ok:
            log.info("bridgy POSSE %s: ok (%s)", target_name, result.detail)
        else:
            log.warning("bridgy POSSE %s: %s", target_name, result.detail)
    return outcomes


__all__ = [
    "BRIDGY_PUBLISH_TARGET_PREFIX",
    "posse_after_weblog_publish",
]
