#!/usr/bin/env python3
"""Verify end-to-end weblog event producer deployment.

1. Checks /dev/shm/hapax-public-events/events.jsonl for an omg.weblog event
2. Checks Mastodon and Bluesky poster idempotency logs for the event
3. Only with --live-egress: publishes a test post through the publication bus
4. Only with --cleanup-live: deletes the test post after live verification

Usage:
    uv run python scripts/verify-weblog-producer-deploy.py
    uv run python scripts/verify-weblog-producer-deploy.py --check-only
    uv run python scripts/verify-weblog-producer-deploy.py --live-egress
    uv run python scripts/verify-weblog-producer-deploy.py --live-egress --cleanup-live
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

PUBLIC_EVENT_PATH = Path("/dev/shm/hapax-public-events/events.jsonl")
MASTODON_IDS_PATH = Path.home() / ".cache/hapax/mastodon-post-event-ids.json"
BLUESKY_IDS_PATH = Path.home() / ".cache/hapax/bluesky-post-event-ids.json"
TEST_ENTRY_ID = "deploy-verify-weblog-producer"
ADDRESS = "hapax"
MAX_WAIT_S = 180
POLL_INTERVAL_S = 10


def check_service_running() -> bool:
    result = subprocess.run(
        ["systemctl", "--user", "is-active", "hapax-weblog-publish-public-event-producer.service"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() == "active"


def publish_test_post() -> bool:
    from agents.publication_bus.omg_weblog_publisher import OmgLolWeblogPublisher
    from agents.publication_bus.publisher_kit import PublisherPayload
    from agents.publication_bus.publisher_kit.allowlist import load_allowlist
    from shared.omg_lol_client import OmgLolClient

    client = OmgLolClient()
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M %Z")
    content = (
        f"Date: {timestamp}\n\n"
        f"# Deployment verification\n\n"
        f"Automated test post from weblog event producer deployment verification. "
        f"This live test post exists only for deployment verification.\n\n"
        f"Timestamp: {timestamp}"
    )
    OmgLolWeblogPublisher.allowlist = load_allowlist(
        OmgLolWeblogPublisher.surface_name,
        [TEST_ENTRY_ID],
    )
    publisher = OmgLolWeblogPublisher(client=client, address=ADDRESS)
    result = publisher.publish(PublisherPayload(target=TEST_ENTRY_ID, text=content))
    if result.ok:
        log.info("test post published through publication bus: %s", TEST_ENTRY_ID)
        return True
    log.error("failed to publish test post through publication bus: %s", result.detail)
    return False


def delete_test_post() -> bool:
    from shared.omg_lol_client import OmgLolClient

    client = OmgLolClient()
    result = client.delete_entry(ADDRESS, TEST_ENTRY_ID)
    if result is not None:
        log.info("test post deleted: %s", TEST_ENTRY_ID)
        return True
    log.warning("failed to delete test post")
    return False


def find_weblog_event(after_ts: float) -> dict | None:
    if not PUBLIC_EVENT_PATH.exists():
        return None
    for line in PUBLIC_EVENT_PATH.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event_type") != "omg.weblog":
            continue
        if TEST_ENTRY_ID in event.get("event_id", ""):
            return event
        if TEST_ENTRY_ID in (event.get("source", {}).get("evidence_ref") or ""):
            return event
        title = (event.get("chapter_ref") or {}).get("label", "")
        if "deployment verification" in title.lower():
            return event
    return None


def check_social_fanout(event_id: str) -> dict[str, bool]:
    results = {}
    for name, path in [("mastodon", MASTODON_IDS_PATH), ("bluesky", BLUESKY_IDS_PATH)]:
        if not path.exists():
            results[name] = False
            continue
        try:
            ids = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            results[name] = False
            continue
        if isinstance(ids, dict):
            event_ids = ids.get("event_ids")
            posts = ids.get("posts")
            if ids.get("schema_version") == 2 or isinstance(posts, list):
                results[name] = isinstance(posts, list) and any(
                    _post_receipt_proves_public_fanout(post, event_id) for post in posts
                )
                continue
            results[name] = isinstance(event_ids, list) and event_id in event_ids
        elif isinstance(ids, list):
            results[name] = event_id in ids
        else:
            results[name] = False
    return results


def _post_receipt_proves_public_fanout(post: object, event_id: str) -> bool:
    if not isinstance(post, dict):
        return False
    if post.get("event_id") != event_id or post.get("result") != "ok":
        return False
    event_public_url = post.get("event_public_url")
    text = post.get("text")
    if not isinstance(event_public_url, str) or not event_public_url:
        return False
    if not isinstance(text, str) or event_public_url not in text:
        return False
    return bool(post.get("public_url") or post.get("uri"))


def _required_social_fanout_ok(fanout: dict[str, bool]) -> bool:
    return all(
        fanout.get(surface, False)
        for surface in (
            "mastodon",
            "bluesky",
        )
    )


def wait_for_event(after_ts: float) -> dict | None:
    deadline = time.time() + MAX_WAIT_S
    while time.time() < deadline:
        event = find_weblog_event(after_ts)
        if event:
            return event
        remaining = int(deadline - time.time())
        log.info("waiting for weblog event... (%ds remaining)", remaining)
        time.sleep(POLL_INTERVAL_S)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live-egress",
        action="store_true",
        help="publish a live test weblog entry through the publication bus",
    )
    parser.add_argument(
        "--cleanup-live",
        dest="cleanup_live",
        action="store_true",
        help="delete the live test post after --live-egress verification",
    )
    parser.add_argument(
        "--cleanup",
        dest="cleanup_live",
        action="store_true",
        help="deprecated alias for --cleanup-live; only honored with --live-egress",
    )
    parser.add_argument(
        "--no-cleanup",
        dest="cleanup_live",
        action="store_false",
        help="deprecated compatibility flag; live cleanup is opt-in",
    )
    parser.add_argument(
        "--check-only", action="store_true", help="check existing events without publishing"
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    if not check_service_running():
        log.error("weblog producer service is not running")
        return 1
    log.info("weblog producer service: active")

    if args.check_only or not args.live_egress:
        event = find_weblog_event(0)
        if event:
            log.info("found weblog event: %s", event.get("event_id"))
            fanout = check_social_fanout(event["event_id"])
            log.info("social fanout: %s", fanout)
            if _required_social_fanout_ok(fanout):
                return 0
            log.error("missing required social fanout proof for %s", event.get("event_id"))
            return 1
        log.warning("no weblog events found in events.jsonl")
        return 1

    before_ts = time.time()

    if not publish_test_post():
        return 1

    log.info("waiting for producer to detect RSS update (tick=60s, max=%ds)...", MAX_WAIT_S)
    event = wait_for_event(before_ts)

    if event is None:
        log.error("timed out waiting for weblog event after %ds", MAX_WAIT_S)
        if args.cleanup_live:
            delete_test_post()
        return 1

    event_id = event.get("event_id", "unknown")
    log.info("weblog event detected: %s", event_id)
    log.info("event_type: %s", event.get("event_type"))
    log.info("state_kind: %s", event.get("state_kind"))
    log.info("salience: %s", event.get("salience"))

    log.info("waiting 30s for social posters to process...")
    time.sleep(30)

    fanout = check_social_fanout(event_id)
    log.info("social fanout results: %s", fanout)

    if args.cleanup_live:
        delete_test_post()

    all_ok = event is not None and _required_social_fanout_ok(fanout)
    if all_ok:
        log.info("PASS: weblog event producer deployment verified")
    else:
        log.error("FAIL: deployment verification failed")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
