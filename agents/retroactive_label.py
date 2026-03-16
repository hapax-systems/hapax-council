"""Retroactive person labeling — batch scan Qdrant docs and tag with person_ids.

Scans the 'documents' collection and extracts person identifiers from
text content and metadata. Updates point payloads in-place with a `people`
field. Non-destructive — only adds fields, never removes existing data.

Usage:
    uv run python -m agents.retroactive_label --dry-run        # preview
    uv run python -m agents.retroactive_label --limit 1000     # small batch
    uv run python -m agents.retroactive_label                  # full run
"""

from __future__ import annotations

import argparse
import logging
from collections import Counter

try:
    from shared import langfuse_config  # noqa: F401
except ImportError:
    pass

from shared.config import get_qdrant
from shared.governance.person_extract import extract_emails, extract_person_ids

log = logging.getLogger(__name__)

COLLECTION = "documents"
BATCH_SIZE = 100


def _extract_for_source(
    source_service: str,
    text: str,
    payload: dict,
) -> frozenset[str]:
    """Source-aware person extraction.

    Different source services store person data in different formats.
    """
    metadata: dict = {}

    if source_service == "gcalendar":
        # Calendar docs have "**Attendees:** name1, name2" in text
        metadata["people"] = payload.get("people", [])
        # Also parse attendees from text
        import re

        attendee_match = re.search(r"\*\*Attendees:\*\*\s*(.+?)(?:\n|$)", text)
        if attendee_match:
            names = [n.strip() for n in attendee_match.group(1).split(",") if n.strip()]
            metadata.setdefault("people", [])
            if isinstance(metadata["people"], list):
                metadata["people"].extend(names)

    elif source_service == "gmail":
        # Email docs have "**From:**", "**To:**" lines
        metadata["people"] = payload.get("people", [])
        import re

        for field in ("From", "To", "Cc"):
            match = re.search(rf"\*\*{field}:\*\*\s*(.+?)(?:\n|$)", text)
            if match:
                emails = extract_emails(match.group(1))
                metadata.setdefault("people", [])
                if isinstance(metadata["people"], list):
                    metadata["people"].extend(emails)

    elif source_service in ("gdrive", "drive"):
        # Drive docs — scan for emails
        metadata["people"] = payload.get("people", [])

    else:
        # obsidian, chrome, claude-code — generic email scan
        metadata["people"] = payload.get("people", [])

    return extract_person_ids(text, metadata=metadata)


def run(
    dry_run: bool = False,
    limit: int | None = None,
    verbose: bool = False,
) -> dict:
    """Scan Qdrant documents and tag with person_ids.

    Returns stats dict with counts.
    """
    client = get_qdrant()

    stats: Counter[str] = Counter()
    offset = None
    processed = 0

    while True:
        # Scroll through collection
        points, next_offset = client.scroll(
            collection_name=COLLECTION,
            limit=BATCH_SIZE,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )

        if not points:
            break

        for point in points:
            payload = point.payload or {}
            text = payload.get("text", "")
            source_service = payload.get("source_service", "unknown")

            # Skip if already labeled
            existing_people = payload.get("people")
            if existing_people is not None:
                stats["already_labeled"] += 1
                processed += 1
                if limit and processed >= limit:
                    break
                continue

            # Extract person IDs
            person_ids = _extract_for_source(source_service, text, payload)
            stats["scanned"] += 1
            stats[f"source_{source_service}"] += 1

            if person_ids:
                stats["has_persons"] += 1
                people_list = sorted(person_ids)

                if verbose:
                    filename = payload.get("filename", "?")
                    log.info(
                        "Found %d persons in %s (%s): %s",
                        len(people_list),
                        filename,
                        source_service,
                        people_list[:3],
                    )

                if not dry_run:
                    client.set_payload(
                        collection_name=COLLECTION,
                        payload={
                            "people": people_list,
                            "consent_review_needed": True,
                        },
                        points=[point.id],
                    )
                    stats["updated"] += 1
                else:
                    stats["would_update"] += 1
            else:
                # Tag as scanned with empty people list
                if not dry_run:
                    client.set_payload(
                        collection_name=COLLECTION,
                        payload={"people": []},
                        points=[point.id],
                    )
                stats["no_persons"] += 1

            processed += 1
            if limit and processed >= limit:
                break

            if processed % 1000 == 0:
                log.info("Progress: %d processed", processed)

        if limit and processed >= limit:
            break

        offset = next_offset
        if offset is None:
            break

    return dict(stats)


def main() -> None:
    parser = argparse.ArgumentParser(description="Retroactive person labeling for Qdrant docs")
    parser.add_argument("--dry-run", action="store_true", help="Preview without updating")
    parser.add_argument("--limit", type=int, help="Max points to process")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    from shared.log_setup import configure_logging

    configure_logging(agent="retroactive-label", level="DEBUG" if args.verbose else None)

    log.info(
        "Starting retroactive labeling (dry_run=%s, limit=%s)",
        args.dry_run,
        args.limit,
    )

    stats = run(dry_run=args.dry_run, limit=args.limit, verbose=args.verbose)

    print("\nRetroactive Labeling Results")
    print("=" * 40)
    for key, value in sorted(stats.items()):
        print(f"  {key}: {value:,}")

    if args.dry_run:
        print("\n(dry run — no changes made)")


if __name__ == "__main__":
    main()
