"""Tests for shared/email_utils.py — shared email parsing utilities.

Tests operate on stdlib email.message.Message objects — no I/O.
"""

from __future__ import annotations

import email
from email.message import Message

from shared.email_utils import (
    decode_header,
    extract_body,
    extract_email_addr,
    is_automated,
    parse_email_date,
)

# ── is_automated tests ──────────────────────────────────────────────────────


class TestIsAutomated:
    def test_noreply(self):
        assert is_automated("noreply@example.com")

    def test_no_reply_hyphen(self):
        assert is_automated("no-reply@service.com")

    def test_notifications(self):
        assert is_automated("notifications@github.com")

    def test_notification_singular(self):
        assert is_automated("notification@jira.com")

    def test_mailer_daemon(self):
        assert is_automated("mailer-daemon@mail.google.com")

    def test_github_noreply(self):
        assert is_automated("user@users.noreply.github.com")

    def test_bounce(self):
        assert is_automated("bounce@bounce.example.com")

    def test_do_not_reply(self):
        assert is_automated("do-not-reply@company.com")

    def test_email_subdomain(self):
        assert is_automated("info@email.company.com")

    def test_real_person(self):
        assert not is_automated("alice@example.com")

    def test_real_person_with_name(self):
        assert not is_automated("bob.smith@company.com")

    def test_case_insensitive(self):
        assert is_automated("NoReply@Example.COM")


# ── extract_email_addr tests ──────────────────────────────────────────────


class TestExtractEmailAddr:
    def test_plain_address(self):
        assert extract_email_addr("alice@example.com") == "alice@example.com"

    def test_name_and_address(self):
        assert extract_email_addr("Alice Smith <alice@example.com>") == "alice@example.com"

    def test_empty_string(self):
        assert extract_email_addr("") == ""

    def test_lowercase(self):
        assert extract_email_addr("Bob@Example.COM") == "bob@example.com"

    def test_quoted_name(self):
        assert extract_email_addr('"Smith, Alice" <alice@example.com>') == "alice@example.com"


# ── decode_header tests ─────────────────────────────────────────────────────


class TestDecodeHeader:
    def test_plain_ascii(self):
        assert decode_header("Hello World") == "Hello World"

    def test_empty_string(self):
        assert decode_header("") == ""

    def test_rfc2047_utf8(self):
        encoded = "=?utf-8?B?SGVsbG8gV29ybGQ=?="
        result = decode_header(encoded)
        assert result == "Hello World"

    def test_rfc2047_iso8859(self):
        encoded = "=?iso-8859-1?Q?caf=E9?="
        result = decode_header(encoded)
        assert "caf" in result


# ── parse_email_date tests ──────────────────────────────────────────────────


class TestParseEmailDate:
    def test_standard_date(self):
        result = parse_email_date("Mon, 01 Mar 2026 07:00:00 +0000")
        assert result is not None
        assert result.year == 2026
        assert result.month == 3
        assert result.day == 1
        # Timezone should be stripped
        assert result.tzinfo is None

    def test_empty_string(self):
        assert parse_email_date("") is None

    def test_invalid_date(self):
        assert parse_email_date("not a date") is None

    def test_date_with_timezone(self):
        result = parse_email_date("Tue, 15 Jun 2025 14:30:00 -0700")
        assert result is not None
        assert result.hour == 14
        assert result.minute == 30


# ── extract_body tests ──────────────────────────────────────────────────────


class TestExtractBody:
    def test_plain_text_message(self):
        msg = email.message_from_string("Content-Type: text/plain; charset=utf-8\n\nHello, world!")
        body = extract_body(msg)
        assert "Hello, world!" in body

    def test_multipart_prefers_plain(self):
        msg = Message()
        msg["Content-Type"] = "multipart/alternative"

        plain = Message()
        plain["Content-Type"] = "text/plain; charset=utf-8"
        plain.set_payload(b"Plain text body", "utf-8")

        html = Message()
        html["Content-Type"] = "text/html; charset=utf-8"
        html.set_payload(b"<b>HTML body</b>", "utf-8")

        msg.attach(plain)
        msg.attach(html)

        body = extract_body(msg)
        assert "Plain text body" in body

    def test_html_fallback_strips_tags(self):
        msg = Message()
        msg["Content-Type"] = "multipart/alternative"

        html = Message()
        html["Content-Type"] = "text/html; charset=utf-8"
        html.set_payload(b"<p>HTML <b>content</b></p>", "utf-8")

        msg.attach(html)

        body = extract_body(msg)
        assert "HTML" in body
        assert "content" in body
        assert "<b>" not in body

    def test_empty_message(self):
        msg = email.message_from_string("Content-Type: text/plain\n\n")
        body = extract_body(msg)
        assert body == "" or body.strip() == ""
