"""parser.py — Parse Proton Mail export (paired .eml + .metadata.json files).

Proton Mail exports are flat directories of paired files:
  <hash>.eml          — RFC 5322 full message
  <hash>.metadata.json — Proton-specific structured metadata

Each pair is parsed into a NormalizedRecord for the dual-path pipeline.
"""
from __future__ import annotations

import email
import json
import logging
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from shared.email_utils import (
    MAX_BODY_CHARS,
    extract_body,
    extract_email_addr,
    is_automated,
)
from shared.proton.labels import get_label_names, is_sent, is_spam_or_trash
from shared.takeout.models import NormalizedRecord, make_record_id

log = logging.getLogger("proton")


def parse_export(
    export_dir: Path,
    *,
    since: datetime | None = None,
    skip_spam: bool = True,
) -> Iterator[NormalizedRecord]:
    """Parse a Proton Mail export directory.

    Discovers *.metadata.json files, pairs with .eml files, and yields
    NormalizedRecords for both structured and unstructured paths.

    Args:
        export_dir: Path to the Proton export directory.
        since: If set, skip emails before this date.
        skip_spam: If True (default), skip Spam and Trash.
    """
    metadata_files = sorted(export_dir.glob("*.metadata.json"))
    if not metadata_files:
        log.warning("No metadata files found in %s", export_dir)
        return

    log.info("Found %d metadata files in %s", len(metadata_files), export_dir)

    for meta_path in metadata_files:
        # Derive the .eml path from the metadata filename
        stem = meta_path.name.removesuffix(".metadata.json")
        eml_path = meta_path.parent / f"{stem}.eml"

        try:
            record = _parse_pair(meta_path, eml_path, since=since, skip_spam=skip_spam)
            if record is not None:
                yield record
        except Exception as e:
            log.debug("Skipping %s: %s", meta_path.name, e)


def _parse_pair(
    meta_path: Path,
    eml_path: Path,
    *,
    since: datetime | None,
    skip_spam: bool,
) -> NormalizedRecord | None:
    """Parse a single .metadata.json + .eml pair into a NormalizedRecord."""
    # Read metadata
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    payload = meta.get("Payload", {})

    # Extract structured fields from metadata
    label_ids = payload.get("LabelIDs", [])
    subject = payload.get("Subject", "")
    sender = payload.get("Sender", {})
    sender_addr = sender.get("Address", "")
    sender_name = sender.get("Name", "")
    to_list = payload.get("ToList", [])
    cc_list = payload.get("CCList", [])
    flags = payload.get("Flags", 0)
    timestamp_unix = payload.get("Time", 0)
    num_attachments = payload.get("NumAttachments", 0)
    external_id = payload.get("ExternalID", "")
    proton_id = payload.get("ID", "")

    # Skip spam/trash
    if skip_spam and is_spam_or_trash(label_ids):
        return None

    # Skip automated senders
    if is_automated(sender_addr):
        return None

    # Parse timestamp
    timestamp: datetime | None = None
    if timestamp_unix:
        timestamp = datetime.fromtimestamp(timestamp_unix, tz=timezone.utc).replace(tzinfo=None)

    # Date filter
    if since and timestamp:
        if timestamp < since.replace(tzinfo=None):
            return None

    # People
    people: list[str] = []
    from_email = extract_email_addr(sender_addr)
    if from_email:
        people.append(from_email)
    for recipient in to_list + cc_list:
        addr = extract_email_addr(recipient.get("Address", ""))
        if addr and addr not in people:
            people.append(addr)

    # Label names for categories
    categories = get_label_names(label_ids)

    # Determine if sent vs received
    sent = is_sent(label_ids)

    # Build from/to display strings
    from_display = f"{sender_name} <{sender_addr}>" if sender_name else sender_addr
    to_display = ", ".join(
        f"{r.get('Name', '')} <{r.get('Address', '')}>".strip()
        for r in to_list
    ) if to_list else ""

    # Structured fields (always available from metadata)
    structured: dict = {
        "from": sender_addr,
        "to": [r.get("Address", "") for r in to_list],
        "direction": "sent" if sent else "received",
        "num_attachments": num_attachments,
        "label_ids": label_ids,
        "flags": flags,
    }
    if external_id:
        structured["external_id"] = external_id

    # For sent mail, metadata is sufficient — structured path only
    if sent:
        title = subject or f"Sent to {to_display}"
        text = f"Subject: {subject}\nFrom: {from_display}\nTo: {to_display}"

        return NormalizedRecord(
            record_id=make_record_id("proton", "mail", proton_id or f"{timestamp_unix}:{sender_addr}:{subject}"),
            platform="proton",
            service="mail",
            title=title,
            text=text,
            content_type="email",
            timestamp=timestamp,
            modality_tags=["text", "social", "temporal"],
            people=people,
            categories=categories,
            structured_fields=structured,
            data_path="structured",
            source_path=str(meta_path.name),
        )

    # Received mail: parse .eml for body content → unstructured path
    body = ""
    if eml_path.exists():
        try:
            raw = eml_path.read_bytes()
            msg = email.message_from_bytes(raw)
            body = extract_body(msg)
            if body:
                body = body[:MAX_BODY_CHARS]
        except Exception as e:
            log.debug("Failed to parse EML %s: %s", eml_path.name, e)

    # Build text
    text_parts = []
    if subject:
        text_parts.append(f"Subject: {subject}")
    text_parts.append(f"From: {from_display}")
    if to_display:
        text_parts.append(f"To: {to_display}")
    if body:
        text_parts.append(f"\n{body}")

    text = "\n".join(text_parts)
    title = subject or f"Email from {from_display}"

    return NormalizedRecord(
        record_id=make_record_id("proton", "mail", proton_id or f"{timestamp_unix}:{sender_addr}:{subject}"),
        platform="proton",
        service="mail",
        title=title,
        text=text,
        content_type="email",
        timestamp=timestamp,
        modality_tags=["text", "social", "temporal"],
        people=people,
        categories=categories,
        structured_fields=structured,
        data_path="unstructured",
        source_path=str(meta_path.name),
    )
