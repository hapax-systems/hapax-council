"""Tests for shared.email_utils.

109-LOC stdlib email parsing utilities used across email parsers.
Untested before this commit.
"""

from __future__ import annotations

from email.message import EmailMessage

import pytest

from shared.email_utils import (
    SKIP_SENDER_PATTERNS,
    decode_header,
    extract_body,
    extract_email_addr,
    is_automated,
    parse_email_date,
)

# ── is_automated ───────────────────────────────────────────────────


class TestIsAutomated:
    @pytest.mark.parametrize(
        "addr",
        [
            "noreply@example.com",
            "no-reply@example.com",
            "notification@example.com",
            "notifications@example.com",
            "mailer-daemon@example.com",
            "postmaster@example.com",
            "do-not-reply@example.com",
            "alerts@bounce.example.com",
            "x@email.example.com",
            "user@user.noreply.github.com",
        ],
    )
    def test_automated_addresses_recognised(self, addr: str) -> None:
        assert is_automated(addr)

    def test_human_address_not_automated(self) -> None:
        assert not is_automated("alice@example.com")

    def test_case_insensitive(self) -> None:
        assert is_automated("NoReply@Example.com")
        assert is_automated("MAILER-DAEMON@Example.com")


# ── extract_email_addr ─────────────────────────────────────────────


class TestExtractEmailAddr:
    def test_plain_address(self) -> None:
        assert extract_email_addr("user@example.com") == "user@example.com"

    def test_named_address(self) -> None:
        assert (
            extract_email_addr('"Alice Smith" <alice@example.com>')
            == "alice@example.com"
        )

    def test_lowercased(self) -> None:
        assert (
            extract_email_addr("Alice@Example.COM") == "alice@example.com"
        )

    def test_empty_returns_empty(self) -> None:
        assert extract_email_addr("") == ""

    def test_unparseable_returns_empty(self) -> None:
        # parseaddr returns ('', '') for entirely invalid input.
        assert extract_email_addr(",,,") == ""


# ── decode_header ──────────────────────────────────────────────────


class TestDecodeHeader:
    def test_plain_ascii_passthrough(self) -> None:
        assert decode_header("Hello world") == "Hello world"

    def test_empty_returns_empty(self) -> None:
        assert decode_header("") == ""

    def test_decodes_rfc2047_utf8(self) -> None:
        # =?utf-8?b?...?= base64 encoding
        encoded = "=?utf-8?b?SGFsbMO2?="  # "Hallö"
        result = decode_header(encoded)
        assert result == "Hallö"


# ── parse_email_date ───────────────────────────────────────────────


class TestParseEmailDate:
    def test_rfc2822_parsed(self) -> None:
        result = parse_email_date("Mon, 1 May 2026 12:00:00 +0000")
        assert result is not None
        assert result.year == 2026
        assert result.month == 5
        assert result.day == 1

    def test_empty_returns_none(self) -> None:
        assert parse_email_date("") is None

    def test_unparseable_returns_none(self) -> None:
        assert parse_email_date("not a date") is None


# ── extract_body ───────────────────────────────────────────────────


class TestExtractBody:
    def test_plain_text_singlepart(self) -> None:
        msg = EmailMessage()
        msg.set_content("Hello body")
        result = extract_body(msg)
        # set_content adds a trailing newline; check inclusion not equality.
        assert "Hello body" in result

    def test_multipart_prefers_text_plain(self) -> None:
        """A multipart/alternative with text/plain + text/html prefers
        text/plain over the HTML."""
        msg = EmailMessage()
        msg.set_content("plain content")
        msg.add_alternative(
            "<p>html <b>content</b></p>", subtype="html"
        )
        result = extract_body(msg)
        assert "plain content" in result
        assert "html" not in result

    def test_singlepart_text_html_returned_as_is(self) -> None:
        """Single-part (non-multipart) text/html messages decode the
        payload without tag stripping — tag stripping is only the
        multipart-text/html fallback path."""
        single = EmailMessage()
        single["Content-Type"] = "text/html"
        single.set_payload(b"<p>hello <b>html</b></p>")
        result = extract_body(single)
        assert "hello" in result


# ── Constant pinning ──────────────────────────────────────────────


class TestConstants:
    def test_skip_sender_patterns_non_empty(self) -> None:
        assert len(SKIP_SENDER_PATTERNS) > 0
