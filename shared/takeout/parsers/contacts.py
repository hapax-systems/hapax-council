"""contacts.py — Parser for Google Contacts VCF exports.

Contacts Takeout includes .vcf (vCard) files.
We parse into structured records for the social graph.

Uses regex-based parsing to avoid requiring the `vobject` library.
"""
from __future__ import annotations

import logging
import re
import zipfile
from collections.abc import Iterator
from datetime import datetime

from shared.takeout.models import NormalizedRecord, ServiceConfig, make_record_id

log = logging.getLogger("takeout.contacts")


def parse(zf: zipfile.ZipFile, config: ServiceConfig) -> Iterator[NormalizedRecord]:
    """Parse Contacts from a Takeout ZIP."""
    prefix_options = [
        "Takeout/Contacts/",
        "Contacts/",
    ]

    for name in sorted(zf.namelist()):
        if not name.endswith(".vcf"):
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

        yield from _parse_vcf(raw, name, config)


def _parse_vcf(
    text: str,
    source_path: str,
    config: ServiceConfig,
) -> Iterator[NormalizedRecord]:
    """Parse vCard entries from VCF text."""
    # Unfold VCF line continuations (RFC 6350 §3.2)
    # Long lines are split with CRLF + space/tab
    text = re.sub(r'\r?\n[ \t]', '', text)

    # Split into individual vCards
    cards = re.findall(
        r"BEGIN:VCARD(.*?)END:VCARD",
        text,
        re.DOTALL,
    )

    for card_text in cards:
        record = _vcard_to_record(card_text, source_path, config)
        if record:
            yield record


def _vcard_to_record(
    card_text: str,
    source_path: str,
    config: ServiceConfig,
) -> NormalizedRecord | None:
    """Convert a single vCard to a NormalizedRecord."""
    fields = _extract_vcard_fields(card_text)

    # Name
    fn = fields.get("FN", "")
    n = fields.get("N", "")
    name = fn or n
    if not name:
        return None

    # Emails
    emails = fields.get("EMAIL", [])
    if isinstance(emails, str):
        emails = [emails]

    # Phones
    phones = fields.get("TEL", [])
    if isinstance(phones, str):
        phones = [phones]

    # Organization
    org = fields.get("ORG", "")

    # Title/role
    title = fields.get("TITLE", "")

    # Build text description
    text_parts = [f"Name: {name}"]
    if org:
        text_parts.append(f"Organization: {org}")
    if title:
        text_parts.append(f"Title: {title}")
    for email in emails:
        text_parts.append(f"Email: {email}")
    for phone in phones:
        text_parts.append(f"Phone: {phone}")

    # Address
    adr = fields.get("ADR", "")
    if adr:
        text_parts.append(f"Address: {adr}")

    # Notes
    note = fields.get("NOTE", "")
    if note:
        text_parts.append(f"Note: {note}")

    text = "\n".join(text_parts)

    # Unique ID
    uid = fields.get("UID", f"{source_path}:{name}")

    # Structured fields
    structured: dict = {}
    if emails:
        structured["emails"] = emails
    if phones:
        structured["phones"] = phones
    if org:
        structured["organization"] = org
    if title:
        structured["title"] = title

    # Groups/categories
    categories: list[str] = []
    cats = fields.get("CATEGORIES", "")
    if cats:
        categories = [c.strip() for c in cats.split(",") if c.strip()]

    record_id = make_record_id("google", "contacts", uid)

    return NormalizedRecord(
        record_id=record_id,
        platform="google",
        service="contacts",
        title=name,
        text=text,
        content_type="contact",
        modality_tags=list(config.modality_defaults),
        people=emails,
        categories=categories,
        structured_fields=structured,
        data_path=config.data_path,
        source_path=source_path,
    )


def _extract_vcard_fields(card_text: str) -> dict:
    """Extract key-value pairs from a vCard.

    Handles multi-value fields (EMAIL, TEL) as lists.
    """
    fields: dict = {}
    multi_keys = {"EMAIL", "TEL", "ADR"}

    for line in card_text.splitlines():
        line = line.strip()
        if not line:
            continue

        # Split on first colon
        match = re.match(r"([A-Za-z][A-Za-z0-9_-]*(?:;[^:]*)?)\s*:\s*(.*)", line)
        if not match:
            continue

        key_with_params = match.group(1)
        value = match.group(2).strip()

        # Strip parameters
        key = key_with_params.split(";")[0].upper()

        if key in multi_keys:
            if key not in fields:
                fields[key] = []
            fields[key].append(value)
        else:
            fields[key] = value

    return fields
