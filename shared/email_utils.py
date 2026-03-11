"""email_utils.py — Shared email parsing utilities.

Extracted from gmail.py for reuse across email parsers (Gmail, Proton, etc.).
All functions operate on stdlib email.message.Message objects.
"""

from __future__ import annotations

import email.header
import email.utils
import re
from datetime import datetime

# Senders to skip (automated, no behavioral signal)
SKIP_SENDER_PATTERNS = [
    r"noreply@",
    r"no-reply@",
    r"notifications?@",
    r"mailer-daemon@",
    r"postmaster@",
    r"@.*\.noreply\.github\.com$",
    r"@bounce\.",
    r"@email\.",
    r"do-not-reply@",
]

MAX_BODY_CHARS = 2000


def is_automated(from_addr: str) -> bool:
    """Check if sender is an automated/notification address."""
    addr_lower = from_addr.lower()
    return any(re.search(pattern, addr_lower) for pattern in SKIP_SENDER_PATTERNS)


def extract_body(msg) -> str:
    """Extract text body from email message.

    Prefers text/plain, falls back to text/html with tag stripping.
    Works with any email.message.Message-like object.
    """
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                try:
                    charset = part.get_content_charset() or "utf-8"
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode(charset, errors="replace")
                except Exception:
                    continue
        # Fallback: try text/html
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                try:
                    charset = part.get_content_charset() or "utf-8"
                    payload = part.get_payload(decode=True)
                    if payload:
                        html = payload.decode(charset, errors="replace")
                        return re.sub(r"<[^>]+>", " ", html).strip()
                except Exception:
                    continue
    else:
        try:
            charset = msg.get_content_charset() or "utf-8"
            payload = msg.get_payload(decode=True)
            if payload:
                return payload.decode(charset, errors="replace")
        except Exception:
            pass

    return ""


def extract_email_addr(addr_str: str) -> str:
    """Extract email address from a header value like 'Name <email@example.com>'."""
    if not addr_str:
        return ""
    _, email_addr = email.utils.parseaddr(addr_str)
    return email_addr.lower() if email_addr else ""


def decode_header(value: str) -> str:
    """Decode RFC 2047 encoded header value."""
    if not value:
        return ""
    try:
        decoded_parts = email.header.decode_header(value)
        parts = []
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                parts.append(part.decode(charset or "utf-8", errors="replace"))
            else:
                parts.append(part)
        return " ".join(parts)
    except Exception:
        return value


def parse_email_date(date_str: str) -> datetime | None:
    """Parse email date header."""
    if not date_str:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(date_str)
        return parsed.replace(tzinfo=None)
    except Exception:
        return None
