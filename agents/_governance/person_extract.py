"""Person ID extraction from structured and unstructured data.

Dispatch-based, source-aware extraction. No NER at query time — relies on:
1. Structured metadata (Qdrant `people` field, Calendar `attendees`)
2. Email address regex (cheap, high precision)
3. Known-person list from ConsentRegistry (scan for names already in system)

Full NER runs only in the offline retroactive labeling batch job.
"""

from __future__ import annotations

import re

# RFC 5322 simplified — matches most real-world email addresses
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


def extract_person_ids(
    content: str,
    metadata: dict | None = None,
    known_persons: frozenset[str] = frozenset(),
) -> frozenset[str]:
    """Extract person identifiers from content and/or structured metadata.

    Args:
        content: Text to scan for person identifiers.
        metadata: Optional structured metadata (Qdrant payload, etc.).
            Checked for 'people', 'attendees', 'from', 'to' fields.
        known_persons: Known person names/IDs from ConsentRegistry.
            If provided, scans content for these names (case-insensitive).

    Returns:
        Frozenset of person identifiers found.
    """
    ids: set[str] = set()

    # 1. Structured metadata
    if metadata:
        for key in ("people", "attendees"):
            val = metadata.get(key)
            if isinstance(val, list):
                ids.update(str(v) for v in val if v)
            elif isinstance(val, str) and val:
                ids.add(val)

        for key in ("from", "to", "sender", "organizer"):
            val = metadata.get(key)
            if isinstance(val, str) and val:
                # Extract email from "Name <email>" format
                emails = _EMAIL_RE.findall(val)
                ids.update(emails)
                if not emails:
                    ids.add(val)

    # 2. Email addresses in text
    ids.update(_EMAIL_RE.findall(content))

    # 3. Known-person lookup (case-insensitive scan)
    if known_persons:
        content_lower = content.lower()
        for person in known_persons:
            if person.lower() in content_lower:
                ids.add(person)

    return frozenset(ids)


def extract_emails(text: str) -> frozenset[str]:
    """Extract email addresses from text. Convenience wrapper."""
    return frozenset(_EMAIL_RE.findall(text))


def extract_calendar_persons(event_text: str) -> frozenset[str]:
    """Extract person identifiers from calendar event text.

    Parses the format produced by handle_get_calendar_today:
    "- 2026-03-15T10:00:00Z: Meeting title (with Alice, Bob, charlie@corp.com)"
    """
    ids: set[str] = set()

    # Extract emails
    ids.update(_EMAIL_RE.findall(event_text))

    # Extract names from "(with Name1, Name2)" pattern
    with_match = re.findall(r"\(with\s+([^)]+)\)", event_text)
    for match in with_match:
        for name in match.split(","):
            name = name.strip()
            if name:
                ids.add(name)

    return frozenset(ids)


def extract_email_persons(email_text: str) -> frozenset[str]:
    """Extract person identifiers from email text.

    Parses formats like:
    "- From: alice@corp.com | Subject: ..."
    "[filename (gmail), relevance=0.85]\\nFrom: Bob <bob@corp.com>"
    """
    ids: set[str] = set()

    # Extract all emails
    ids.update(_EMAIL_RE.findall(email_text))

    # Extract "From: Name" patterns (without email)
    from_matches = re.findall(r"From:\s*([^|<\n]+)", email_text)
    for match in from_matches:
        name = match.strip().rstrip(",")
        if name and not _EMAIL_RE.match(name) and name != "?":
            ids.add(name)

    return frozenset(ids)
