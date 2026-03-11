"""calendar.py — Parser for Google Calendar ICS exports.

Calendar Takeout includes .ics files (iCalendar format).
We parse events into structured records with temporal + social modality.

Uses regex-based parsing to avoid requiring the `icalendar` library.
If `icalendar` is available, we use it for better parsing.
"""

from __future__ import annotations

import logging
import re
import zipfile
from collections.abc import Iterator
from datetime import datetime

from shared.takeout.models import NormalizedRecord, ServiceConfig, make_record_id

log = logging.getLogger("takeout.calendar")


def parse(zf: zipfile.ZipFile, config: ServiceConfig) -> Iterator[NormalizedRecord]:
    """Parse Calendar events from a Takeout ZIP."""
    prefix_options = [
        "Takeout/Calendar/",
        "Calendar/",
    ]

    for name in sorted(zf.namelist()):
        if not name.endswith(".ics"):
            continue

        matched = False
        for prefix in prefix_options:
            if name.startswith(prefix):
                matched = True
                break

        if not matched:
            continue

        try:
            raw = zf.read(name).decode("utf-8", errors="replace")
        except KeyError:
            continue

        yield from _parse_ics(raw, name, config)


def _parse_ics(
    text: str,
    source_path: str,
    config: ServiceConfig,
) -> Iterator[NormalizedRecord]:
    """Parse events from ICS text using regex.

    Handles VEVENT blocks with SUMMARY, DTSTART, DTEND, LOCATION,
    ATTENDEE, DESCRIPTION, and UID fields.
    """
    # Split into VEVENT blocks
    events = re.findall(
        r"BEGIN:VEVENT(.*?)END:VEVENT",
        text,
        re.DOTALL,
    )

    for event_text in events:
        event = _extract_ics_fields(event_text)

        summary = event.get("SUMMARY", "")
        if not summary:
            continue

        # Parse timestamps
        dtstart = _parse_ics_datetime(event.get("DTSTART", ""))
        dtend = _parse_ics_datetime(event.get("DTEND", ""))

        # Location
        location = event.get("LOCATION", "")

        # Attendees
        attendees = event.get("ATTENDEE", [])
        people: list[str] = []
        for att in attendees if isinstance(attendees, list) else [attendees]:
            # ATTENDEE;CN=Name:mailto:email
            email_match = re.search(r"mailto:([^\s;]+)", att)
            if email_match:
                people.append(email_match.group(1))

        # Description
        description = event.get("DESCRIPTION", "")
        # Unescape ICS
        description = description.replace("\\n", "\n").replace("\\,", ",")

        # Build text
        text_parts = [summary]
        if dtstart:
            text_parts.append(f"Start: {dtstart.isoformat()}")
        if dtend:
            text_parts.append(f"End: {dtend.isoformat()}")
        if location:
            text_parts.append(f"Location: {location}")
        if people:
            text_parts.append(f"Attendees: {', '.join(people)}")
        if description:
            text_parts.append(f"\n{description}")

        text = "\n".join(text_parts)

        # UID for dedup
        uid = event.get("UID", f"{source_path}:{summary}:{event.get('DTSTART', '')}")
        record_id = make_record_id("google", "calendar", uid)

        # Structured fields
        structured: dict = {}
        if dtend and dtstart:
            duration = dtend - dtstart
            structured["duration_minutes"] = int(duration.total_seconds() / 60)
        if event.get("RRULE"):
            structured["recurring"] = True
            structured["rrule"] = event["RRULE"]
        if event.get("STATUS"):
            structured["status"] = event["STATUS"]

        # Modality tags
        modality_tags = list(config.modality_defaults)
        if location:
            modality_tags.append("spatial")

        yield NormalizedRecord(
            record_id=record_id,
            platform="google",
            service="calendar",
            title=summary,
            text=text,
            content_type="calendar_event",
            timestamp=dtstart,
            modality_tags=modality_tags,
            people=people,
            location=location,
            structured_fields=structured,
            data_path=config.data_path,
            source_path=source_path,
        )


def _extract_ics_fields(event_text: str) -> dict:
    """Extract key-value pairs from an ICS VEVENT block.

    Handles multi-line values (continuation lines starting with space/tab)
    and multiple values for the same key (e.g., ATTENDEE).
    """
    fields: dict = {}

    # Unfold continuation lines (RFC 5545 §3.1)
    unfolded = re.sub(r"\r?\n[ \t]", "", event_text)

    for line in unfolded.splitlines():
        line = line.strip()
        if not line or line.startswith(("BEGIN:", "END:")):
            continue

        # Split on first colon, but handle params like DTSTART;VALUE=DATE:20250615
        match = re.match(r"([A-Z][A-Z0-9_-]*(?:;[^:]*)?)\s*:\s*(.*)", line)
        if not match:
            continue

        key_with_params = match.group(1)
        value = match.group(2)

        # Strip parameters from key
        key = key_with_params.split(";")[0]

        if key == "ATTENDEE":
            # Multiple attendees → list
            if key not in fields:
                fields[key] = []
            fields[key].append(f"{key_with_params}:{value}")
        else:
            fields[key] = value

    return fields


def _parse_ics_datetime(value: str) -> datetime | None:
    """Parse ICS datetime value.

    Handles: 20250615T103000Z, 20250615T103000, 20250615
    """
    if not value:
        return None

    # Strip VALUE=DATE: prefix if present
    value = re.sub(r"^.*:", "", value).strip()

    for fmt in (
        "%Y%m%dT%H%M%SZ",
        "%Y%m%dT%H%M%S",
        "%Y%m%d",
    ):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    return None
