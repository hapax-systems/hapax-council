#!/usr/bin/env python3
"""Publish the Show HN blog post to hapax.weblog.lol via the publication bus.

Usage:
    uv run python scripts/publish-hn-blog-post.py [--dry-run]

Reads the draft from docs/publication-drafts/2026-05-10-show-hn-governance-that-ships.md,
strips the YAML frontmatter, and publishes to hapax.omg.lol/weblog via
OmgLolWeblogPublisher. Optionally triggers Bridgy POSSE fanout to
Mastodon + Bluesky.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DRAFT_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "publication-drafts"
    / "2026-05-10-show-hn-governance-that-ships.md"
)

ENTRY_SLUG = "show-hn-governance-that-ships"


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].lstrip("\n")
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish Show HN blog post")
    parser.add_argument("--dry-run", action="store_true", help="Print content without publishing")
    parser.add_argument("--no-posse", action="store_true", help="Skip Bridgy POSSE fanout")
    args = parser.parse_args()

    if not DRAFT_PATH.exists():
        print(f"Draft not found: {DRAFT_PATH}", file=sys.stderr)
        return 1

    raw = DRAFT_PATH.read_text()
    body = _strip_frontmatter(raw)

    if args.dry_run:
        print(f"=== DRY RUN: would publish to hapax.omg.lol/weblog/{ENTRY_SLUG} ===")
        print(f"=== Body length: {len(body)} chars ===")
        print(body[:500])
        print("...")
        return 0

    from agents.publication_bus.omg_weblog_publisher import OmgLolWeblogPublisher
    from agents.publication_bus.publisher_kit import PublisherPayload
    from agents.publication_bus.publisher_kit.allowlist import load_allowlist
    from shared.omg_lol_client import OmgLolClient

    client = OmgLolClient()
    if not client.enabled:
        print("OmgLolClient disabled (no API key). Run: pass show omg-lol/api-key", file=sys.stderr)
        return 1

    OmgLolWeblogPublisher.allowlist = load_allowlist(
        OmgLolWeblogPublisher.surface_name, [ENTRY_SLUG]
    )
    publisher = OmgLolWeblogPublisher(client=client, address="hapax")
    payload = PublisherPayload(target=ENTRY_SLUG, text=body)

    print(f"Publishing to hapax.omg.lol/weblog/{ENTRY_SLUG}...")
    result = publisher.publish(payload)

    if result.ok:
        print(f"Published: {result.detail}")
    elif result.refused:
        print(f"Refused: {result.detail}", file=sys.stderr)
        return 1
    else:
        print(f"Error: {result.detail}", file=sys.stderr)
        return 1

    if not args.no_posse:
        from agents.publication_bus.bridgy_posse_fanout import posse_after_weblog_publish

        entry_url = f"https://hapax.omg.lol/weblog/{ENTRY_SLUG}"
        print(f"POSSE fanout to Mastodon + Bluesky for {entry_url}...")
        outcomes = posse_after_weblog_publish(entry_url=entry_url)
        for target, res in outcomes.items():
            status = "ok" if res.ok else ("refused" if res.refused else "error")
            print(f"  {target}: {status} ({res.detail})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
