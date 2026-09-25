"""Communication pathway: canonical content digests and mechanical message checks.

An outbound message is admitted only against a record that was witnessed before the send and is bound to the
content *as the recipient will decode it*. This module computes that binding and runs the checks that can be
decided mechanically on the message itself. It is pure: no I/O, no network, no clock except where a caller passes
one.

Canonical digest. ``sha256`` over the RFC 8785 (JCS) serialisation of a manifest. JCS preserves strings as they
are, so every normalisation happens before serialisation:

- text is NFC-normalised and its line ends become LF;
- charset names are lowercased and common aliases mapped (charset values are not case sensitive, RFC 2046 §4.1.2);
- ``format=flowed`` text is hashed as reconstructed paragraphs (RFC 3676 §4.1-4.4), so a re-wrap does not change
  the digest;
- only reader-visible headers are kept (from, to, cc, reply-to, subject), unfolded and whitespace-collapsed;
  transport headers such as Date, Message-ID and MIME-Version, and the MIME boundary, are excluded;
- filenames are taken decoded (RFC 2231) and NFC-normalised.

Manifests contain only strings, integers, booleans, null, lists and objects with ASCII keys. Floats are refused,
which keeps the serialisation byte-stable. For these inputs, Python's sorted-key compact JSON is identical to JCS.

What this module does not do: judge whether a message *should* be sent, resolve links, or verify a witness. Those
belong to the refusing component and the witnessed record.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from email.message import EmailMessage
from email.utils import getaddresses
from typing import Any

_CHARSET_ALIASES: dict[str, str] = {
    "utf8": "utf-8",
    "utf-8": "utf-8",
    "latin1": "iso-8859-1",
    "latin-1": "iso-8859-1",
    "l1": "iso-8859-1",
    "iso8859-1": "iso-8859-1",
    "iso_8859-1": "iso-8859-1",
    "iso-8859-1": "iso-8859-1",
    "ascii": "us-ascii",
    "us-ascii": "us-ascii",
    "ansi_x3.4-1968": "us-ascii",
}
_READER_VISIBLE_HEADERS: tuple[tuple[str, str], ...] = (
    ("from", "From"),
    ("to", "To"),
    ("cc", "Cc"),
    ("reply_to", "Reply-To"),
)
_URL = re.compile(r"https?://\S+")
_TRAILING_PUNCTUATION = ".,:;!?)]}'\""
_MARKDOWN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("atx_heading", re.compile(r"^#{1,6} ")),
    ("bold", re.compile(r"\*\*[^*\n]+\*\*")),
    ("pipe_table", re.compile(r"^\s*\|.*\|\s*$")),
)
_SUBJECT_MAX = 998


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _lf(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _collapse(value: str) -> str:
    return " ".join(value.split())


def normalize_charset(name: str | None) -> str | None:
    """Lowercase a charset name and map common aliases to one preferred name."""
    if name is None:
        return None
    key = name.strip().lower()
    return _CHARSET_ALIASES.get(key, key)


def flowed_text(text: str, *, delsp: bool) -> str:
    """Reconstruct ``format=flowed`` paragraphs (RFC 3676), so equivalent wrappings compare equal.

    A line ending in a space is a soft break, except the signature separator ``-- ``. One leading space is removed
    (space-stuffing). With ``delsp``, the space before a soft break is deleted. Quote depth is kept as a ``>``
    prefix, and a change of depth ends a paragraph.
    """
    body = _lf(text)
    trailing_newline = body.endswith("\n")
    lines = body.split("\n")
    if trailing_newline:
        lines = lines[:-1]
    out: list[str] = []
    current: list[str] = []
    current_depth = 0
    for raw in lines:
        depth = len(raw) - len(raw.lstrip(">"))
        line = raw[depth:]
        if line.startswith(" "):
            line = line[1:]
        soft = line.endswith(" ") and line != "-- "
        if current and depth != current_depth:
            out.append(">" * current_depth + "".join(current))
            current = []
        current_depth = depth
        if soft:
            current.append(line[:-1] if delsp else line)
            continue
        current.append(line)
        out.append(">" * depth + "".join(current))
        current = []
    if current:
        out.append(">" * current_depth + "".join(current))
    return "\n".join(out) + ("\n" if trailing_newline else "")


def _addresses(values: Iterable[str]) -> list[dict[str, str]]:
    return [
        {"display": _nfc(_collapse(display)), "addr": _nfc(addr.strip())}
        for display, addr in getaddresses(list(values))
        if addr
    ]


def email_manifest(msg: EmailMessage) -> dict[str, Any]:
    """Build the canonical manifest of an email as a recipient's client decodes it."""
    headers: dict[str, Any] = {}
    for key, name in _READER_VISIBLE_HEADERS:
        values = msg.get_all(name) or []
        addresses = _addresses(str(v) for v in values)
        if addresses:
            headers[key] = addresses
    subject = msg.get("Subject")
    if subject is not None and _collapse(str(subject)):
        headers["subject"] = _nfc(_collapse(str(subject)))

    parts: list[dict[str, Any]] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        content_type = part.get_content_type()
        entry: dict[str, Any] = {
            "index": len(parts),
            "content_type": content_type,
            "disposition": part.get_content_disposition(),
            "filename": _nfc(part.get_filename()) if part.get_filename() else None,
        }
        if part.get_content_maintype() == "text":
            fmt = (part.get_param("format") or "fixed").lower()
            delsp = str(part.get_param("delsp") or "no").lower() == "yes"
            text = _nfc(_lf(part.get_content()))
            if fmt == "flowed":
                text = flowed_text(text, delsp=delsp)
            entry["charset"] = normalize_charset(part.get_content_charset())
            entry["format"] = fmt
            entry["delsp"] = delsp if fmt == "flowed" else False
            entry["text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        else:
            entry["bytes_sha256"] = hashlib.sha256(part.get_payload(decode=True) or b"").hexdigest()
        parts.append(entry)
    return {"channel": "email", "headers": headers, "parts": parts}


def _check_jcs_safe(value: Any) -> None:
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return
    if isinstance(value, float):
        raise ValueError("canonical manifests must not contain floats")
    if isinstance(value, Mapping):
        for k, v in value.items():
            if not isinstance(k, str) or not k.isascii():
                raise ValueError(f"manifest keys must be ASCII strings: {k!r}")
            _check_jcs_safe(v)
        return
    if isinstance(value, (list, tuple)):
        for v in value:
            _check_jcs_safe(v)
        return
    raise ValueError(f"unsupported manifest value type: {type(value).__name__}")


def canonical_digest(manifest: Mapping[str, Any]) -> str:
    """sha256 of the manifest's JCS serialisation (RFC 8785), for the value types this module allows."""
    _check_jcs_safe(manifest)
    data = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def duplicated_parts(manifest: Mapping[str, Any]) -> list[tuple[int, int]]:
    """Pairs of parts whose decoded content is identical, for example a body that repeats an attachment."""
    seen: dict[str, int] = {}
    pairs: list[tuple[int, int]] = []
    for part in manifest.get("parts", []):
        digest = part.get("text_sha256") or part.get("bytes_sha256")
        if digest in seen:
            pairs.append((seen[digest], part["index"]))
        else:
            seen[digest] = part["index"]
    return pairs


def bare_line_ends(stream: bytes) -> list[str]:
    """Report CR and LF bytes that are not part of a CRLF pair (RFC 5321 §2.3.8 allows only CRLF)."""
    problems: list[str] = []
    for i, byte in enumerate(stream):
        if byte == 0x0D and (i + 1 >= len(stream) or stream[i + 1] != 0x0A):
            problems.append(f"bare CR at byte {i}")
        elif byte == 0x0A and (i == 0 or stream[i - 1] != 0x0D):
            problems.append(f"bare LF at byte {i}")
    return problems


def to_crlf(stream: bytes) -> bytes:
    """Turn every LF that is not already preceded by CR into CRLF."""
    return re.sub(rb"(?<!\r)\n", b"\r\n", stream)


def url_punctuation_flags(text: str) -> list[str]:
    """URLs immediately followed by punctuation, which a copy or a linkifier may keep and break."""
    return [m.group(0) for m in _URL.finditer(text) if m.group(0)[-1] in _TRAILING_PUNCTUATION]


def markdown_flags(text: str) -> list[tuple[str, int]]:
    """Markdown constructs that show as raw syntax in text/plain: ATX headings, bold, pipe-table rows."""
    flags: list[tuple[str, int]] = []
    for number, line in enumerate(_lf(text).split("\n"), start=1):
        for kind, pattern in _MARKDOWN_PATTERNS:
            if pattern.search(line):
                flags.append((kind, number))
    return flags


def long_lines(text: str, limit: int = 78) -> list[int]:
    """Line numbers of decoded lines longer than ``limit`` characters."""
    return [n for n, line in enumerate(_lf(text).split("\n"), start=1) if len(line) > limit]


def subject_problems(subject: str, mandatory: Sequence[str]) -> list[str]:
    """Mechanical subject checks: no control characters, every mandatory pattern present, at most 998 chars."""
    problems: list[str] = []
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in subject):
        problems.append("control character in subject")
    for pattern in mandatory:
        if pattern not in subject:
            problems.append(f"missing mandatory pattern: {pattern}")
    if len(subject) > _SUBJECT_MAX:
        problems.append(f"subject longer than {_SUBJECT_MAX} characters")
    return problems


def act_seen(digest: str, nonce: str, act_log: Iterable[Mapping[str, Any]]) -> bool:
    """True if this (digest, nonce) pair already appears in the refusing component's own act log."""
    return any(e.get("canonical_digest") == digest and e.get("nonce") == nonce for e in act_log)


def within_window(now: datetime, not_before: datetime, not_after: datetime) -> bool:
    """True if ``now`` lies inside the record's validity window. Naive datetimes are refused."""
    for value in (now, not_before, not_after):
        if value.tzinfo is None:
            raise ValueError("validity-window datetimes must be timezone-aware")
    return not_before <= now <= not_after


def norm_table_missing(statements: Sequence[str], table: Mapping[str, str]) -> list[str]:
    """Channel statements that the record's norm table does not decide (import, adapt or depart)."""
    return [s for s in statements if s not in table]
