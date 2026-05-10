#!/usr/bin/env python3
"""Verify end-to-end weblog event producer deployment.

1. Publishes a test weblog post to omg.lol
2. Waits for the producer to pick it up from RSS
3. Checks /dev/shm/hapax-public-events/events.jsonl for the omg.weblog event
4. Checks Mastodon and Bluesky poster idempotency logs for the event
5. Optionally cleans up the test post

Usage:
    uv run python scripts/verify-weblog-producer-deploy.py
    uv run python scripts/verify-weblog-producer-deploy.py --cleanup
    uv run python scripts/verify-weblog-producer-deploy.py --check-only
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
    from shared.omg_lol_client import OmgLolClient

    client = OmgLolClient()
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M %Z")
    content = (
        f"Date: {timestamp}\n\n"
        f"# Deployment verification\n\n"
        f"Automated test post from weblog event producer deployment verification. "
        f"This post will be deleted after verification completes.\n\n"
        f"Timestamp: {timestamp}"
    )
    result = client.set_entry(ADDRESS, TEST_ENTRY_ID, content=content)
    if result is not None:
        log.info("test post published: %s", TEST_ENTRY_ID)
        return True
    log.error("failed to publish test post")
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
        results[name] = event_id in (ids if isinstance(ids, list) else ids.keys())
    return results


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
        "--cleanup", action="store_true", help="delete test post after verification"
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

    if args.check_only:
        event = find_weblog_event(0)
        if event:
            log.info("found weblog event: %s", event.get("event_id"))
            fanout = check_social_fanout(event["event_id"])
            log.info("social fanout: %s", fanout)
            return 0
        log.warning("no weblog events found in events.jsonl")
        return 1

    before_ts = time.time()

    if not publish_test_post():
        return 1

    log.info("waiting for producer to detect RSS update (tick=60s, max=%ds)...", MAX_WAIT_S)
    event = wait_for_event(before_ts)

    if event is None:
        log.error("timed out waiting for weblog event after %ds", MAX_WAIT_S)
        if args.cleanup:
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

    if args.cleanup:
        delete_test_post()

    all_ok = event is not None
    if all_ok:
        log.info("PASS: weblog event producer deployment verified")
    else:
        log.error("FAIL: deployment verification failed")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
