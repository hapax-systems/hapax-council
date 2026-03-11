"""gmail.py — Parser for Gmail MBOX exports.

Gmail Takeout exports as .mbox files. These can be 30GB+.
We MUST stream — never load the full file into memory.

Strategy:
- Headers (from, to, date, subject, labels) → structured path
- Body → unstructured path (truncated to max_body_chars)
- Automated senders (noreply, notifications) → filtered out
"""
from __future__ import annotations

import logging
import mailbox
import shutil
import tempfile
import zipfile
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from shared.email_utils import (
    MAX_BODY_CHARS,
    SKIP_SENDER_PATTERNS,
    decode_header as _decode_header,
    extract_body as _extract_body,
    extract_email_addr as _extract_email_addr,
    is_automated as _is_automated,
    parse_email_date as _parse_email_date,
)
from shared.takeout.models import NormalizedRecord, ServiceConfig, make_record_id

log = logging.getLogger("takeout.gmail")


def parse(zf: zipfile.ZipFile, config: ServiceConfig) -> Iterator[NormalizedRecord]:
    """Parse Gmail MBOX files from a Takeout ZIP.

    Extracts to a temp file to enable mailbox.mbox streaming.
    """
    prefix_options = [
        "Takeout/Mail/",
        "Mail/",
    ]

    mbox_files = []
    for name in zf.namelist():
        if not name.endswith(".mbox"):
            continue
        for prefix in prefix_options:
            if name.startswith(prefix):
                mbox_files.append(name)
                break

    for mbox_name in mbox_files:
        yield from _parse_mbox(zf, mbox_name, config)


def _parse_mbox(
    zf: zipfile.ZipFile,
    mbox_name: str,
    config: ServiceConfig,
) -> Iterator[NormalizedRecord]:
    """Stream-parse an MBOX file from within the ZIP.

    mailbox.mbox requires a file path, so we extract to a temp file.
    This avoids loading the entire MBOX into memory.
    """
    # Check available disk space before extracting
    info = zf.getinfo(mbox_name)
    avail = shutil.disk_usage(tempfile.gettempdir()).free
    if info.file_size > avail:
        log.error(
            "Insufficient disk space for Gmail MBOX: need %dMB, have %dMB",
            info.file_size // (1024 * 1024),
            avail // (1024 * 1024),
        )
        return

    with tempfile.NamedTemporaryFile(suffix=".mbox", delete=True) as tmp:
        # Extract MBOX to temp file
        with zf.open(mbox_name) as src:
            while True:
                chunk = src.read(1024 * 1024)  # 1MB chunks
                if not chunk:
                    break
                tmp.write(chunk)
        tmp.flush()

        # Parse with stdlib mailbox
        mbox = mailbox.mbox(tmp.name)
        for msg in mbox:
            record = _message_to_record(msg, mbox_name, config)
            if record:
                yield record


def _message_to_record(
    msg: mailbox.mboxMessage,
    source_path: str,
    config: ServiceConfig,
) -> NormalizedRecord | None:
    """Convert a single email message to a NormalizedRecord."""
    # Extract headers
    from_addr = _decode_header(msg.get("From", ""))
    to_addr = _decode_header(msg.get("To", ""))
    subject = _decode_header(msg.get("Subject", ""))
    date_str = msg.get("Date", "")
    message_id = msg.get("Message-ID", "")

    # Skip automated senders
    if _is_automated(from_addr):
        return None

    # Skip empty messages
    if not subject and not from_addr:
        return None

    # Parse date
    timestamp = _parse_email_date(date_str)

    # Extract body (text/plain preferred, fallback to text/html)
    body = _extract_body(msg)
    if body:
        body = body[:MAX_BODY_CHARS]

    # People
    people: list[str] = []
    for addr in [from_addr, to_addr]:
        extracted = _extract_email_addr(addr)
        if extracted and extracted not in people:
            people.append(extracted)

    # CC
    cc = _decode_header(msg.get("Cc", ""))
    if cc:
        for addr in cc.split(","):
            extracted = _extract_email_addr(addr.strip())
            if extracted and extracted not in people:
                people.append(extracted)

    # Labels (X-Gmail-Labels header)
    labels_str = msg.get("X-Gmail-Labels", "")
    labels = [l.strip() for l in labels_str.split(",") if l.strip()] if labels_str else []

    # Build text
    text_parts = []
    if subject:
        text_parts.append(f"Subject: {subject}")
    if from_addr:
        text_parts.append(f"From: {from_addr}")
    if to_addr:
        text_parts.append(f"To: {to_addr}")
    if body:
        text_parts.append(f"\n{body}")

    text = "\n".join(text_parts)
    title = subject or f"Email from {from_addr}"

    # Record ID from Message-ID or hash
    source_key = message_id or f"{date_str}:{from_addr}:{subject}"
    record_id = make_record_id("google", "gmail", source_key)

    # Structured fields for header data
    structured: dict = {
        "from": from_addr,
        "to": to_addr,
    }
    if message_id:
        structured["message_id"] = message_id

    # Dual path: headers → structured, full message → unstructured
    yield_record = NormalizedRecord(
        record_id=record_id,
        platform="google",
        service="gmail",
        title=title,
        text=text,
        content_type="email",
        timestamp=timestamp,
        modality_tags=list(config.modality_defaults),
        people=people,
        categories=labels,
        structured_fields=structured,
        data_path=config.data_path,
        source_path=source_path,
    )

    return yield_record
