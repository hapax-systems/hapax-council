"""Tests for gmail_sync — schemas, formatting, profiler facts."""
from __future__ import annotations


def test_email_metadata_defaults():
    from agents.gmail_sync import EmailMetadata
    e = EmailMetadata(
        message_id="abc123",
        thread_id="thread1",
        subject="Test Subject",
        sender="alice@company.com",
        timestamp="2026-03-10T09:00:00Z",
    )
    assert e.labels == []
    assert e.recipients == []
    assert e.is_unread is False
    assert e.thread_length == 1
    assert e.has_attachments is False


def test_gmail_sync_state_empty():
    from agents.gmail_sync import GmailSyncState
    s = GmailSyncState()
    assert s.history_id == ""
    assert s.messages == {}


def test_email_metadata_with_labels():
    from agents.gmail_sync import EmailMetadata
    e = EmailMetadata(
        message_id="def456",
        thread_id="thread2",
        subject="Important",
        sender="boss@company.com",
        timestamp="2026-03-10T10:00:00Z",
        labels=["IMPORTANT", "INBOX"],
        is_unread=True,
    )
    assert "IMPORTANT" in e.labels
    assert e.is_unread is True


def test_format_email_markdown_metadata_only():
    from agents.gmail_sync import EmailMetadata, _format_email_markdown
    e = EmailMetadata(
        message_id="msg1",
        thread_id="thread1",
        subject="Q1 Budget Review",
        sender="alice@company.com",
        timestamp="2026-03-10T09:00:00Z",
        recipients=["bob@company.com"],
        labels=["INBOX", "IMPORTANT"],
        is_unread=True,
        snippet="Please review the attached budget...",
    )
    md = _format_email_markdown(e)
    assert "platform: google" in md
    assert "service: gmail" in md
    assert "source_service: gmail" in md
    assert "people: [alice@company.com, bob@company.com]" in md
    assert "Q1 Budget Review" in md
    assert "alice@company.com" in md


def test_format_email_no_recipients():
    from agents.gmail_sync import EmailMetadata, _format_email_markdown
    e = EmailMetadata(
        message_id="msg2",
        thread_id="thread2",
        subject="Newsletter",
        sender="news@example.com",
        timestamp="2026-03-10T12:00:00Z",
        labels=["CATEGORY_PROMOTIONS"],
    )
    md = _format_email_markdown(e)
    assert "Newsletter" in md
    assert "people: [news@example.com]" in md


def test_generate_gmail_profile_facts():
    from agents.gmail_sync import (
        _generate_profile_facts, GmailSyncState, EmailMetadata,
    )
    state = GmailSyncState()
    state.messages = {
        "1": EmailMetadata(message_id="1", thread_id="t1",
             subject="Budget Review", sender="alice@company.com",
             timestamp="2026-03-10T09:00:00Z", labels=["INBOX", "IMPORTANT"]),
        "2": EmailMetadata(message_id="2", thread_id="t2",
             subject="Standup Notes", sender="bob@company.com",
             timestamp="2026-03-10T10:00:00Z", labels=["INBOX"]),
        "3": EmailMetadata(message_id="3", thread_id="t1",
             subject="Re: Budget Review", sender="alice@company.com",
             timestamp="2026-03-10T11:00:00Z", labels=["INBOX"]),
    }
    facts = _generate_profile_facts(state)
    assert len(facts) > 0
    dims = {f["dimension"] for f in facts}
    assert "communication_patterns" in dims
    assert all(f["confidence"] == 0.95 for f in facts)
