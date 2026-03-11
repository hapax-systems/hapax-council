"""Tests for shared.proton — Proton Mail export ingestion pipeline."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from shared.email_utils import (
    decode_header,
    extract_body,
    extract_email_addr,
    is_automated,
    parse_email_date,
)
from shared.proton.labels import (
    SYSTEM_LABELS,
    decode_flags,
    get_folder_name,
    get_label_names,
    is_sent,
    is_spam_or_trash,
)
from shared.proton.parser import parse_export
from shared.proton.processor import ProcessResult, process_export


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _make_metadata(
    *,
    proton_id: str = "test-id-123",
    subject: str = "Test Subject",
    sender_name: str = "Alice",
    sender_addr: str = "alice@example.com",
    to_name: str = "Bob",
    to_addr: str = "bob@example.com",
    label_ids: list[str] | None = None,
    flags: int = 9229,
    timestamp: int = 1740003519,
    num_attachments: int = 0,
    cc_list: list | None = None,
) -> dict:
    """Create a minimal Proton metadata dict."""
    return {
        "Version": 1,
        "Payload": {
            "ID": proton_id,
            "LabelIDs": label_ids or ["0", "5", "15"],
            "Subject": subject,
            "Sender": {"Name": sender_name, "Address": sender_addr},
            "ToList": [{"Name": to_name, "Address": to_addr}],
            "CCList": cc_list or [],
            "BCCList": [],
            "Flags": flags,
            "Time": timestamp,
            "NumAttachments": num_attachments,
            "MIMEType": "text/plain",
            "Headers": "",
        },
    }


def _make_eml(
    *,
    from_addr: str = "alice@example.com",
    to_addr: str = "bob@example.com",
    subject: str = "Test Subject",
    body: str = "Hello, this is a test email.",
    date: str = "Thu, 20 Feb 2025 10:00:00 +0000",
) -> bytes:
    """Create a minimal RFC 5322 email."""
    return (
        f"From: {from_addr}\r\n"
        f"To: {to_addr}\r\n"
        f"Subject: {subject}\r\n"
        f"Date: {date}\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n"
        f"\r\n"
        f"{body}\r\n"
    ).encode("utf-8")


def _write_pair(
    directory: Path,
    stem: str = "abc123",
    metadata: dict | None = None,
    eml: bytes | None = None,
) -> tuple[Path, Path]:
    """Write a .metadata.json + .eml pair to a directory."""
    if metadata is None:
        metadata = _make_metadata()
    if eml is None:
        eml = _make_eml()

    meta_path = directory / f"{stem}.metadata.json"
    eml_path = directory / f"{stem}.eml"
    meta_path.write_text(json.dumps(metadata), encoding="utf-8")
    eml_path.write_bytes(eml)
    return meta_path, eml_path


# ── TestLabels ───────────────────────────────────────────────────────────────

class TestLabels:
    def test_system_label_lookup(self):
        assert SYSTEM_LABELS["0"] == "Inbox"
        assert SYSTEM_LABELS["7"] == "Sent"
        assert SYSTEM_LABELS["4"] == "Spam"

    def test_is_spam_or_trash_spam(self):
        assert is_spam_or_trash(["4", "5"]) is True

    def test_is_spam_or_trash_trash(self):
        assert is_spam_or_trash(["3"]) is True

    def test_is_spam_or_trash_inbox(self):
        assert is_spam_or_trash(["0", "5", "15"]) is False

    def test_is_sent(self):
        assert is_sent(["2", "5"]) is True
        assert is_sent(["7"]) is True
        assert is_sent(["0", "5"]) is False

    def test_decode_flags_received(self):
        flags = decode_flags(1)
        assert "received" in flags

    def test_decode_flags_sent(self):
        flags = decode_flags(2)
        assert "sent" in flags

    def test_decode_flags_multiple(self):
        flags = decode_flags(9)  # 1 + 8 = received + e2e
        assert "received" in flags
        assert "e2e" in flags

    def test_decode_flags_zero(self):
        assert decode_flags(0) == set()

    def test_get_label_names(self):
        names = get_label_names(["0", "5", "21"])
        assert "Inbox" in names
        assert "AllMail" in names
        assert "custom:21" in names

    def test_get_folder_name_inbox(self):
        assert get_folder_name(["0", "5"]) == "inbox"

    def test_get_folder_name_sent(self):
        assert get_folder_name(["7", "5"]) == "sent"

    def test_get_folder_name_default(self):
        assert get_folder_name(["5", "15"]) == "mail"


# ── TestEmailUtils ───────────────────────────────────────────────────────────

class TestEmailUtils:
    def test_is_automated_noreply(self):
        assert is_automated("noreply@example.com") is True

    def test_is_automated_regular(self):
        assert is_automated("alice@example.com") is False

    def test_is_automated_github(self):
        assert is_automated("user@users.noreply.github.com") is True

    def test_extract_email_addr_with_name(self):
        assert extract_email_addr("Alice <alice@example.com>") == "alice@example.com"

    def test_extract_email_addr_plain(self):
        assert extract_email_addr("bob@example.com") == "bob@example.com"

    def test_extract_email_addr_empty(self):
        assert extract_email_addr("") == ""

    def test_decode_header_plain(self):
        assert decode_header("Hello World") == "Hello World"

    def test_decode_header_empty(self):
        assert decode_header("") == ""

    def test_parse_email_date_valid(self):
        result = parse_email_date("Thu, 20 Feb 2025 10:00:00 +0000")
        assert result == datetime(2025, 2, 20, 10, 0, 0)

    def test_parse_email_date_empty(self):
        assert parse_email_date("") is None

    def test_parse_email_date_invalid(self):
        assert parse_email_date("not a date") is None

    def test_extract_body_plain(self):
        import email
        msg = email.message_from_string(
            "Content-Type: text/plain\r\n\r\nHello world"
        )
        assert extract_body(msg) == "Hello world"


# ── TestParser ───────────────────────────────────────────────────────────────

class TestParser:
    def test_parse_single_received(self, tmp_path):
        _write_pair(tmp_path, stem="msg1")
        records = list(parse_export(tmp_path))
        assert len(records) == 1
        r = records[0]
        assert r.platform == "proton"
        assert r.service == "mail"
        assert r.content_type == "email"
        assert "Test Subject" in r.title
        assert "alice@example.com" in r.people
        assert r.data_path == "unstructured"

    def test_parse_sent_mail(self, tmp_path):
        meta = _make_metadata(label_ids=["7", "5", "15"])
        _write_pair(tmp_path, stem="sent1", metadata=meta)
        records = list(parse_export(tmp_path))
        assert len(records) == 1
        assert records[0].data_path == "structured"
        assert records[0].structured_fields["direction"] == "sent"

    def test_skip_spam(self, tmp_path):
        meta = _make_metadata(label_ids=["4", "5"])
        _write_pair(tmp_path, stem="spam1", metadata=meta)
        records = list(parse_export(tmp_path))
        assert len(records) == 0

    def test_include_spam(self, tmp_path):
        meta = _make_metadata(label_ids=["4", "5"])
        _write_pair(tmp_path, stem="spam1", metadata=meta)
        records = list(parse_export(tmp_path, skip_spam=False))
        assert len(records) == 1

    def test_skip_automated(self, tmp_path):
        meta = _make_metadata(sender_addr="noreply@example.com")
        _write_pair(tmp_path, stem="auto1", metadata=meta)
        records = list(parse_export(tmp_path))
        assert len(records) == 0

    def test_date_filter(self, tmp_path):
        # Timestamp 1740003519 = 2025-02-19 ~22:18 UTC
        _write_pair(tmp_path, stem="old1")
        # Filter: only after 2025-03-01
        since = datetime(2025, 3, 1)
        records = list(parse_export(tmp_path, since=since))
        assert len(records) == 0

    def test_date_filter_includes(self, tmp_path):
        _write_pair(tmp_path, stem="new1")
        # Filter: after 2025-01-01 (email is from Feb 2025)
        since = datetime(2025, 1, 1)
        records = list(parse_export(tmp_path, since=since))
        assert len(records) == 1

    def test_multiple_emails(self, tmp_path):
        for i in range(5):
            meta = _make_metadata(proton_id=f"id-{i}", subject=f"Email {i}")
            _write_pair(tmp_path, stem=f"msg{i}", metadata=meta)
        records = list(parse_export(tmp_path))
        assert len(records) == 5

    def test_body_extraction(self, tmp_path):
        eml = _make_eml(body="This is the actual body content.")
        _write_pair(tmp_path, stem="body1", eml=eml)
        records = list(parse_export(tmp_path))
        assert len(records) == 1
        assert "This is the actual body content." in records[0].text

    def test_missing_eml(self, tmp_path):
        """If .eml is missing, record should still be created from metadata."""
        meta = _make_metadata()
        meta_path = tmp_path / "noeml.metadata.json"
        meta_path.write_text(json.dumps(meta))
        records = list(parse_export(tmp_path))
        assert len(records) == 1
        assert records[0].text  # Should still have text from metadata

    def test_cc_in_people(self, tmp_path):
        meta = _make_metadata(
            cc_list=[{"Name": "Charlie", "Address": "charlie@example.com"}],
        )
        _write_pair(tmp_path, stem="cc1", metadata=meta)
        records = list(parse_export(tmp_path))
        assert "charlie@example.com" in records[0].people

    def test_modality_tags(self, tmp_path):
        _write_pair(tmp_path, stem="mod1")
        records = list(parse_export(tmp_path))
        assert "text" in records[0].modality_tags
        assert "social" in records[0].modality_tags
        assert "temporal" in records[0].modality_tags

    def test_empty_directory(self, tmp_path):
        records = list(parse_export(tmp_path))
        assert len(records) == 0


# ── TestProcessor ────────────────────────────────────────────────────────────

class TestProcessor:
    def test_dry_run(self, tmp_path):
        export_dir = tmp_path / "export"
        export_dir.mkdir()
        output_dir = tmp_path / "output"
        structured = tmp_path / "structured.jsonl"

        for i in range(3):
            meta = _make_metadata(proton_id=f"id-{i}", subject=f"Email {i}")
            _write_pair(export_dir, stem=f"msg{i}", metadata=meta)

        result = process_export(
            export_dir,
            output_dir=output_dir,
            structured_path=structured,
            dry_run=True,
        )
        assert result.records_written == 3
        assert result.total_files == 3
        # Dry run: no files written
        assert not output_dir.exists()
        assert not structured.exists()

    def test_actual_write(self, tmp_path):
        export_dir = tmp_path / "export"
        export_dir.mkdir()
        output_dir = tmp_path / "output"
        structured = tmp_path / "structured.jsonl"

        _write_pair(export_dir, stem="msg1")
        result = process_export(
            export_dir,
            output_dir=output_dir,
            structured_path=structured,
        )
        assert result.records_written == 1
        # Check markdown was written
        md_files = list(output_dir.rglob("*.md"))
        assert len(md_files) == 1
        content = md_files[0].read_text()
        assert "platform: proton" in content

    def test_max_records(self, tmp_path):
        export_dir = tmp_path / "export"
        export_dir.mkdir()
        output_dir = tmp_path / "output"
        structured = tmp_path / "structured.jsonl"

        for i in range(10):
            meta = _make_metadata(proton_id=f"id-{i}", subject=f"Email {i}")
            _write_pair(export_dir, stem=f"msg{i}", metadata=meta)

        result = process_export(
            export_dir,
            output_dir=output_dir,
            structured_path=structured,
            max_records=3,
            dry_run=True,
        )
        assert result.records_written == 3

    def test_since_filter(self, tmp_path):
        export_dir = tmp_path / "export"
        export_dir.mkdir()
        output_dir = tmp_path / "output"
        structured = tmp_path / "structured.jsonl"

        # Timestamp 1740003519 = 2025-02-19
        _write_pair(export_dir, stem="msg1")

        result = process_export(
            export_dir,
            since="2025-03-01",
            output_dir=output_dir,
            structured_path=structured,
            dry_run=True,
        )
        assert result.records_written == 0

    def test_sent_goes_to_structured(self, tmp_path):
        export_dir = tmp_path / "export"
        export_dir.mkdir()
        output_dir = tmp_path / "output"
        structured = tmp_path / "structured.jsonl"

        meta = _make_metadata(label_ids=["7", "5"])
        _write_pair(export_dir, stem="sent1", metadata=meta)

        result = process_export(
            export_dir,
            output_dir=output_dir,
            structured_path=structured,
        )
        assert result.records_written == 1
        # Sent mail goes to structured JSONL
        assert structured.exists()
        lines = structured.read_text().strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["structured_fields"]["direction"] == "sent"

    def test_progress_tracking(self, tmp_path):
        export_dir = tmp_path / "export"
        export_dir.mkdir()
        output_dir = tmp_path / "output"
        structured = tmp_path / "structured.jsonl"

        _write_pair(export_dir, stem="msg1")

        result = process_export(
            export_dir,
            output_dir=output_dir,
            structured_path=structured,
        )
        assert result.records_written == 1
        assert not result.errors

    def test_empty_export(self, tmp_path):
        export_dir = tmp_path / "export"
        export_dir.mkdir()
        output_dir = tmp_path / "output"
        structured = tmp_path / "structured.jsonl"

        result = process_export(
            export_dir,
            output_dir=output_dir,
            structured_path=structured,
            dry_run=True,
        )
        assert result.records_written == 0
        assert result.total_files == 0
